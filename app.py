import base64
import datetime
import difflib
import io
import math
import os
import shutil
import struct
import subprocess
import wave
from io import BytesIO
from typing import List, Optional, Tuple, Dict

import numpy as np
import streamlit as st

# --- NLTK 라이브러리 및 최신 품사 판별 리소스 설정 ---
import nltk
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)

try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)

try:
    nltk.data.find('taggers/averaged_perceptron_tagger')
except LookupError:
    nltk.download('averaged_perceptron_tagger', quiet=True)

try:
    nltk.data.find('taggers/averaged_perceptron_tagger_eng')
except LookupError:
    nltk.download('averaged_perceptron_tagger_eng', quiet=True)

from nltk.tokenize import word_tokenize
from nltk.tag import pos_tag

# OpenAI 라이브러리 임포트
try:
    import openai
    _have_openai = True
except ImportError:
    _have_openai = False

# Optional libs detection
_have_pydub = False
_have_imageio_ffmpeg = False
_have_librosa = False

try:
    from pydub import AudioSegment  # type: ignore
    _have_pydub = True
except Exception:
    AudioSegment = None

try:
    import imageio_ffmpeg as _iioffmpeg  # type: ignore
    _have_imageio_ffmpeg = True
except Exception:
    _iioffmpeg = None

try:
    import librosa  # type: ignore
    _have_librosa = True
except Exception:
    librosa = None


# ---------------------------
# Streamlit config & helpers
# ---------------------------
st.set_page_config(
    page_title="Patent #1 MVP - Voice Scaffolding",
    layout="wide",
    initial_sidebar_state="expanded",
)

def _safe_rerun():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    elif hasattr(st, "rerun"):
        st.rerun()

def _ensure_wav_bytes(raw_bytes: bytes) -> Optional[bytes]:
    try:
        if raw_bytes[:4] == b"RIFF" and b"WAVE" in raw_bytes[:12]:
            return raw_bytes
    except Exception:
        pass
    if _have_pydub:
        try:
            seg = AudioSegment.from_file(io.BytesIO(raw_bytes))
            out = BytesIO()
            seg.export(out, format="wav")
            return out.getvalue()
        except Exception:
            pass
    return None

def parse_wav_bytes(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_frames = wf.readframes(n_frames)
    if n_frames == 0 or framerate == 0:
        return np.array([], dtype=np.float32), framerate
    
    samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)
    return samples, framerate

def compute_rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples ** 2) + 1e-12))

def fallback_vad(samples: np.ndarray, sr: int) -> np.ndarray:
    frame_size = int(sr * 0.03)
    voicing = [1 if compute_rms(samples[i:i+frame_size]) > 0.015 else 0 for i in range(0, len(samples), frame_size)]
    return np.array(voicing, dtype=int)

def calculate_word_accuracy_details(target_text: str, user_text: str) -> Tuple[float, int, int, List[str]]:
    target_words = [w.strip(".,?!") for w in target_text.strip().lower().split() if w.strip()]
    user_words = [w.strip(".,?!") for w in user_text.strip().lower().split() if w.strip()]
    if not target_words: return 0.0, 0, 0, []
    matcher = difflib.SequenceMatcher(None, target_words, user_words)
    correct_count = sum(i2 - i1 for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag == 'equal')
    wrong_words = [target_words[idx] for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag in ('replace', 'delete') for idx in range(i1, i2)]
    return round((correct_count / len(target_words)) * 100.0, 1), correct_count, len(target_words) - correct_count, wrong_words

# ---------------------------
# STT 및 분석 함수
# ---------------------------
def analyze_audio_with_whisper(wav_bytes: bytes, api_key: str) -> Dict:
    if not _have_openai or not api_key:
        return {"transcript": "OpenAI API Key가 설정되지 않았습니다. 사이드바에서 설정해주세요."}
    try:
        client = openai.OpenAI(api_key=api_key)
        transcript_obj = client.audio.transcriptions.create(
            model="whisper-1", file=("audio.wav", wav_bytes), response_format="verbose_json", timestamp_granularities=["word"]
        )
        words_info = getattr(transcript_obj, "words", [])
        word_latencies = [(w.get("word", "").strip(), round(w.get("start", 0.0) - (words_info[i-1].get("end", 0.0) if i > 0 else 0), 1)) for i, w in enumerate(words_info)]
        return {"transcript": transcript_obj.text, "word_latencies": word_latencies}
    except Exception as e:
        return {"transcript": f"오류 발생: {str(e)}"}

# ---------------------------
# UI 및 상태관리
# ---------------------------
if "openai_api_key" not in st.session_state: st.session_state.openai_api_key = ""
if "recorded_audio_bytes" not in st.session_state: st.session_state.recorded_audio_bytes = None
if "analysis_data" not in st.session_state: st.session_state.analysis_data = None

st.title("🛡️ 특허 1호 MVP: 음성 Latency 분석")

# 사이드바 API 설정
st.sidebar.subheader("💡 설정")
api_key_input = st.sidebar.text_input("OpenAI API Key", type="password", value=st.session_state.openai_api_key)

if st.sidebar.button("API Key 확인 및 적용"):
    st.session_state.openai_api_key = api_key_input.strip()
    st.sidebar.success("✅ 적용 완료")
    # [핵심] 키 적용 시 이미 녹음된 파일이 있다면 즉시 재분석
    if st.session_state.recorded_audio_bytes:
        with st.spinner("재분석 중..."):
            st.session_state.analysis_data = analyze_audio_with_whisper(st.session_state.recorded_audio_bytes, st.session_state.openai_api_key)
        _safe_rerun()

# 메인 UI
col_rec, col_res = st.columns(2)
with col_rec:
    audio_file = st.audio_input("마이크 녹음")
    if audio_file:
        wav = _ensure_wav_bytes(audio_file.read())
        if wav:
            st.session_state.recorded_audio_bytes = wav
            st.session_state.analysis_data = analyze_audio_with_whisper(wav, st.session_state.openai_api_key)

with col_res:
    if st.session_state.analysis_data:
        res = st.session_state.analysis_data
        st.write("### 결과")
        st.info(res.get("transcript", ""))
        
        # Latency 표시
        latencies = res.get("word_latencies", [])
        for word, gap in latencies:
            st.write(f"{word}: {gap}초")
    else:
        st.info("녹음을 시작하거나 API 키를 설정하세요.")
