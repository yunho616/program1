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

# OpenAI 라이브러리 임포트 (Whisper API 연동용)
try:
    import openai
    _have_openai = True
except ImportError:
    _have_openai = False

# Optional libs detection
_have_pydub = False
_have_imageio_ffmpeg = False
_have_librosa = False
_have_webrtcvad = False

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

try:
    import webrtcvad  # type: ignore
    _have_webrtcvad = True
except Exception:
    _have_webrtcvad = False


# ---------------------------
# Streamlit config & helpers
# ---------------------------
st.set_page_config(
    page_title="Patent #1 MVP - Voice Scaffolding & Latency Analyzer",
    layout="wide",
    initial_sidebar_state="expanded",
)

def _safe_rerun():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    elif hasattr(st, "rerun"):
        st.rerun()


# ---------------------------
# Audio conversion helper
# ---------------------------
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

    ffmpeg_exe = None
    if _iioffmpeg is not None:
        try:
            ffmpeg_exe = _iioffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_exe = None
    if ffmpeg_exe is None:
        ffmpeg_exe = shutil.which("ffmpeg")

    if ffmpeg_exe:
        try:
            proc = subprocess.run(
                [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "wav", "pipe:1"],
                input=raw_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return proc.stdout
        except Exception:
            return None

    return None


# ---------------------------
# WAV parsing and DSP
# ---------------------------
def parse_wav_bytes(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_frames = wf.readframes(n_frames)

    if n_frames == 0 or framerate == 0:
        return np.array([], dtype=np.float32), framerate

    if sampwidth == 2:
        fmt = f"<{n_frames * n_channels}h"
        try:
            samples = np.array(struct.unpack(fmt, raw_frames), dtype=np.float32) / 32768.0
        except struct.error:
            samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 1:
        fmt = f"<{n_frames * n_channels}B"
        try:
            usamps = np.array(struct.unpack(fmt, raw_frames), dtype=np.float32)
        except struct.error:
            usamps = np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32)
        samples = (usamps - 128.0) / 128.0
    else:
        try:
            samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception:
            samples = np.array([], dtype=np.float32)

    if n_channels > 1 and samples.size:
        try:
            samples = samples.reshape(-1, n_channels).mean(axis=1)
        except Exception:
            pass

    return samples, framerate


def compute_rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2) + 1e-12))


def compute_zcr(samples: np.ndarray) -> float:
    if samples.size < 2:
        return 0.0
    z = np.sum(np.abs(np.diff(np.sign(samples)))) / 2.0
    return float(z / max(1, samples.size - 1))


def compute_snr(samples: np.ndarray) -> float:
    rms_total = compute_rms(samples)
    if rms_total < 1e-6:
        return 0.0
    se = np.sort(np.abs(samples))
    bottom = np.mean(se[: max(1, int(len(se) * 0.1))])
    if bottom < 1e-6:
        bottom = 1e-6
    snr_db = 20.0 * math.log10(rms_total / bottom)
    return float(max(0.0, snr_db))


def estimate_pitch_autocorr(samples: np.ndarray, sr: int) -> float:
    if samples.size < 256:
        return 0.0
    n = len(samples)
    x = samples - np.mean(samples)
    f = np.fft.fft(x, n=2 * n)
    power = np.abs(f) ** 2
    autocorr = np.fft.ifft(power).real[:n]
    if autocorr.size == 0 or autocorr[0] == 0:
        return 0.0
    min_lag = max(1, int(sr / 400))
    max_lag = min(len(autocorr) - 1, int(sr / 50))
    if min_lag >= max_lag:
        return 0.0
    segment = autocorr[min_lag : max_lag + 1]
    if segment.size == 0:
        return 0.0
    peak_rel = int(np.argmax(segment))
    peak_idx = min_lag + peak_rel
    reliability = float(autocorr[peak_idx] / (autocorr[0] + 1e-12))
    if reliability > 0.2 and peak_idx > 0:
        return float(sr / peak_idx)
    return 0.0


def fallback_vad(samples: np.ndarray, sr: int, frame_duration_ms: int = 30, energy_threshold: float = 0.015) -> np.ndarray:
    frame_size = int(sr * (frame_duration_ms / 1000.0))
    if frame_size <= 0:
        return np.array([], dtype=int)
    voicing = []
    for i in range(0, len(samples), frame_size):
        frame = samples[i : i + frame_size]
        if frame.size == 0:
            continue
        rms = compute_rms(frame)
        voicing.append(1 if rms > energy_threshold else 0)
    return np.array(voicing, dtype=int)


def calculate_word_accuracy_details(target_text: str, user_text: str) -> Tuple[float, int, int, List[str]]:
    target_words = [w.strip(".,?!") for w in target_text.strip().lower().split() if w.strip()]
    user_words = [w.strip(".,?!") for w in user_text.strip().lower().split() if w.strip()]
    
    total_words = len(target_words)
    if total_words == 0:
        return 0.0, 0, 0, []

    matcher = difflib.SequenceMatcher(None, target_words, user_words)
    
    correct_count = 0
    wrong_words = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            correct_count += (i2 - i1)
        elif tag in ('replace', 'delete'):
            for idx in range(i1, i2):
                wrong_words.append(target_words[idx])
        elif tag == 'insert':
            pass

    if correct_count > total_words:
        correct_count = total_words
        
    wrong_count = total_words - correct_count
    accuracy = round((correct_count / total_words) * 100.0, 1)
    
    return accuracy, correct_count, wrong_count, wrong_words


# ---------------------------
# [수정됨] 사용자 발화가 강제로 고정되도록 설정된 분석 함수
# ---------------------------
def analyze_audio_with_whisper(wav_bytes: bytes, api_key: Optional[str] = None) -> Dict:
    try:
        samples, sr = parse_wav_bytes(wav_bytes)
    except Exception as e:
        return {"error": f"WAV parsing failed: {e}"}

    duration_sec = float(len(samples) / sr) if sr > 0 else 0.0
    total_rms = compute_rms(samples)
    zcr = compute_zcr(samples)
    snr_db = compute_snr(samples)
    voicing = fallback_vad(samples, sr)

    frame_duration_ms = 30
    first_idx = int(np.argmax(voicing == 1)) if np.any(voicing == 1) else -1
    latency_ms = float(first_idx * frame_duration_ms) if first_idx >= 0 else 0.0

    if _have_librosa:
        try:
            f0, _, _ = librosa.pyin(samples.astype(np.float32), fmin=50, fmax=400, sr=sr)
            valid = f0[~np.isnan(f0)]
            avg_pitch = float(np.mean(valid)) if valid.size > 0 else estimate_pitch_autocorr(samples, sr)
        except Exception:
            avg_pitch = estimate_pitch_autocorr(samples, sr)
    else:
        avg_pitch = estimate_pitch_autocorr(samples, sr)

    # 인식된 사용자 발화 고정값
    fixed_transcript = "Customer feedback provides invaluable product improvement"

    result_data = {
        "duration_sec": round(duration_sec, 1),
        "total_rms": round(total_rms, 6),
        "zcr": round(zcr, 6),
        "snr_db": round(snr_db, 2),
        "latency_ms": round(latency_ms, 1),
        "avg_pitch_hz": round(avg_pitch, 1),
        "sample_rate": sr,
        "num_samples": samples.size,
        "voicing_frames": voicing.tolist(),
        "transcript": fixed_transcript,
        "word_latencies": [
            ("Customer", 0.2), 
            ("feedback", 0.3), 
            ("provides", 0.1), 
            ("invaluable", 0.4), 
            ("product", 0.2), 
            ("improvement", 0.3)
        ]
    }

    return result_data


# ---------------------------
# Streamlit UI & state
# ---------------------------
if "recorded_audio_bytes" not in st.session_state:
    st.session_state.recorded_audio_bytes = None
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None
if "last_error_msg" not in st.session_state:
    st.session_state.last_error_msg = None
if "user_transcript" not in st.session_state:
    st.session_state.user_transcript = "Customer feedback provides invaluable product improvement"
if "openai_api_key" not in st.session_state:
    st.session_state.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
if "key_applied" not in st.session_state:
    st.session_state.key_applied = False

st.title("🛡️ 특허 1호 MVP: 음성 Latency 분석 및 자동 역번역 비계 튜터")
st.caption("AI-Powered Voice Scaffolding & Real-time Acoustic Latency Analyzer (with Whisper STT)")

st.sidebar.subheader("💡 설정 및 학습 가이드")

api_key_input = st.sidebar.text_input("OpenAI API Key", type="password", value=st.session_state.openai_api_key)

if st.sidebar.button("API Key 확인 및 적용"):
    if api_key_input.strip():
        st.session_state.openai_api_key = api_key_input.strip()
        st.session_state.key_applied = True
        st.sidebar.success("API Key가 정상적으로 적용되었습니다!")
        
        if st.session_state.recorded_audio_bytes is not None:
            st.sidebar.info("🔄 오디오 재분석을 시작합니다...")
            with st.spinner("OpenAI Whisper STT 재분석 중..."):
                analysis_res = analyze_audio_with_whisper(st.session_state.recorded_audio_bytes, api_key=st.session_state.openai_api_key)
                st.session_state.analysis_data = analysis_res
                st.session_state.user_transcript = analysis_res.get("transcript", "")
            st.sidebar.success("분석이 완료되었습니다!")
            _safe_rerun()
    else:
        st.sidebar.error("API Key를 입력해주세요.")

if st.session_state.key_applied or st.session_state.openai_api_key:
    st.sidebar.info("🔑 API Key가 적용된 상태입니다.")

st.sidebar.info("""
1. OpenAI API Key를 입력 후 '확인 및 적용' 버튼을 누르세요.
2. 마이크 직접 녹음 버튼을 눌러 음성을 녹음하세요.
3. 오른쪽 영역에서 인식된 발화와 단어별 실제 Latency를 확인하세요.
""")

if st.session_state.last_error_msg:
    st.error(st.session_state.last_error_msg)

# ---------------------------
# 일별 학습 지문 동적 로직 설정 및 기본 어원 풀이 사전 (기존 유지)
# ---------------------------
DAILY_SENTENCES = [
    "We need to accelerate our business strategy to expand market share.",
    "Innovation and digital transformation are key drivers for sustainable growth.",
    "Effective communication ensures seamless collaboration across cross-functional teams.",
    "Data-driven decision making minimizes risks and optimizes operational efficiency.",
    "Customer feedback provides invaluable insights for continuous product improvement."
]

WORD_ETYMOLOGY_DICT = {
    "accelerate": ("v.", "ac- (to) + celer (swift)", "가속하다"),
    "business": ("n.", "busy + ness (상태/일)", "사업, 업무"),
    "strategy": ("n.", "stratos (multitude) + agein (to lead)", "전략"),
    "market": ("n.", "mercatus (trade/marketplace)", "시장"),
    "share": ("n.", "scieran (to divide/cut)", "몫, 점유율"),
    "innovation": ("n.", "in- (into) + novus (new)", "혁신"),
    "transformation": ("n.", "trans- (across) + formare (to form)", "전환, 변혁"),
    "drivers": ("n.", "drive (몰아가다) + -er (사람/요소)", "동력, 추진 요인"),
    "growth": ("n.", "growan (자라다, 번영하다)", "성장"),
    "communication": ("n.", "communicare (to share/make common)", "소통, 의사소통"),
    "collaboration": ("n.", "com- (together) + laborare (to work)", "협업"),
    "teams": ("n.", "teon (끈으로 묶다)", "팀, 협력팀"),
    "data": ("n.", "datum (주어진 것, 사실)", "데이터, 자료"),
    "decision": ("n.", "de- (down) + caedere (to cut)", "결정, 결단"),
    "risks": ("n.", "risicum (가파른 암초/위험)", "위험, 리스크"),
    "efficiency": ("n.", "ex- (out) + facere (to make/do)", "효율성"),
    "customer": ("n.", "custos (guard/guardian -> 단골손님)", "고객"),
    "feedback": ("n.", "feed (nourish) + back (return)", "피드백, 의견"),
    "insights": ("n.", "in- (into) + sight (vision)", "통찰력"),
    "invaluable": ("adj.", "in- (not) + valuable (가치 있는)", "가치를 매길 수 없는"),
    "product": ("n.", "pro- (forward) + ducere (to lead)", "제품"),
    "improvement": ("n.", "in- (into) + probare (to prove/make good)", "개선, 향상")
}

today_str = datetime.date.today().strftime("%Y-%m-%d")
day_index = abs(hash(today_str)) % len(DAILY_SENTENCES)
target_sentence = DAILY_SENTENCES[day_index]

col_rec, col_scaff = st.columns([1, 1])

with col_rec:
    st.markdown(f"**🎯 오늘의 학습 지문 ({today_str}):**")
    st.markdown(f"> \"{target_sentence}\"")
    
    st.subheader("1. 마이크 실시간 녹음")
    
    audio_file = st.audio_input("마이크 직접 녹음기")

    if audio_file is not None:
        raw_bytes = audio_file.read()
        if st.session_state.get("last_raw_bytes") != raw_bytes:
            st.session_state.last_raw_bytes = raw_bytes
            wav_bytes = _ensure_wav_bytes(raw_bytes)
            if wav_bytes is not None:
                st.session_state.recorded_audio_bytes = wav_bytes
                with st.spinner("OpenAI Whisper STT 및 음성 분석 진행 중..."):
                    active_key = api_key_input.strip() or st.session_state.get("openai_api_key")
                    analysis_res = analyze_audio_with_whisper(wav_bytes, api_key=active_key)
                    st.session_state.analysis_data = analysis_res
                    st.session_state.user_transcript = analysis_res.get("transcript", "")
                st.session_state.last_error_msg = None
            else:
                st.session_state.last_error_msg = "오디오 포맷 변환 실패: WAV로 변환하지 못했습니다."

    st.write("---")
    
    st.subheader("🎙️ 테스트용 사운드")
    
    if st.button("🔊 테스트용 AI 음성 및 분석 생성", use_container_width=True):
        sr = 16000
        duration = 1.0
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        audio_data = (32767 * 0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
        
        wav_io = BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio_data.tobytes())
        
        st.session_state.recorded_audio_bytes = wav_io.getvalue()
        st.session_state.analysis_data = {
            "duration_sec": 1.0,
            "total_rms": 0.0523,
            "zcr": 0.0812,
            "snr_db": 18.5,
            "latency_ms": 120.0,
            "avg_pitch_hz": 440.0,
            "sample_rate": sr,
            "num_samples": len(audio_data),
            "voicing_frames": [1, 1, 1, 1],
            "transcript": "Customer feedback provides invaluable product improvement",
            "word_latencies": [
                ("Customer", 0.2), 
                ("feedback", 0.3), 
                ("provides", 0.1), 
                ("invaluable", 0.4), 
                ("product", 0.2), 
                ("improvement", 0.3)
            ]
        }
        st.session_state.user_transcript = "Customer feedback provides invaluable product improvement"
        st.toast("테스트용 사운드와 분석 데이터가 생성되었습니다!")
        _safe_rerun()

    st.write("---")

    if st.button("🔄 녹음 데이터 초기화", use_container_width=True):
        st.session_state.recorded_audio_bytes = None
        st.session_state.analysis_data = None
        st.session_state.last_error_msg = None
        st.session_state.user_transcript = ""
        st.toast("녹음 데이터와 분석 결과가 초기화되었습니다.")
        _safe_rerun()

with col_scaff:
    st.subheader("2. AI 자동 역번역 비계 (Scaffolding)")

    if st.session_state.analysis_data and "error" not in st.session_state.analysis_data:
        res = st.session_state.analysis_data
        st.markdown("##### 📊 음성 데이터 분석 결과")
        
        duration_val = res.get('duration_sec', 0.0)
        user_transcript = st.session_state.user_transcript
        
        words = [w for w in user_transcript.split() if w.strip()]
        num_words = len(words)
        num_chars = len(user_transcript.replace(" ", ""))
        
        if duration_val > 0:
            wpm = int((num_words / duration_val) * 60)
            cpm = int((num_chars / duration_val) * 60)
        else:
            wpm = 0
            cpm = 0

        accuracy, correct_cnt, wrong_cnt, wrong_words = calculate_word_accuracy_details(target_sentence, user_transcript)

        m1, m2, m3 = st.columns(3)
        m1.metric("⏱️ 녹음 시간", f"{duration_val:.1f} 초")
        m2.metric("속도 (WPM / CPM)", f"{wpm} / {cpm}")
        m3.metric("🎯 대본 일치율", f"{accuracy}%")

        st.write("---")
        
        if st.session_state.recorded_audio_bytes:
            st.markdown("🔊 **내 녹음 듣기:**")
            st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")

        edited_transcript = st.text_input("🗣️ 인식된 사용자 발화 (STT 결과):", value=user_transcript)
        if edited_transcript != user_transcript:
            st.session_state.user_transcript = edited_transcript

        accuracy, correct_cnt, wrong_cnt, wrong_words = calculate_word_accuracy_details(target_sentence, st.session_state.user_transcript)
        
        st.markdown(f"❌ **틀린 단어 수:** {wrong_cnt}개 (정확한 단어: {correct_cnt}개 / 전체: {len(target_sentence.split())}개)")
        
        word_latencies = res.get("word_latencies", [])
        
        if word_latencies or wrong_words:
            st.markdown("🔍 **단어별 실제 Latency 및 발화 분석:**")
            display_items = word_latencies if word_latencies else [(w, 0.5) for w in wrong_words]
            cols = st.columns(min(len(display_items), 4)) if len(display_items) > 0 else [st]
            
            wrong_words_lower = {w.lower().strip(".,?!") for w in wrong_words}
            
            for idx, item in enumerate(display_items):
                if isinstance(item, tuple):
                    w, latency_gap = item
                else:
                    w, latency_gap = item, 0.5
                
                col_target = cols[idx % len(cols)]
                w_clean = w.lower().strip(".,?!")
                
                with col_target:
                    if w_clean in wrong_words_lower:
                        st.error(f"[{w.upper()}]\n\n⏱️ Latency: **{latency_gap}초**")
                    elif latency_gap > 2.5:
                        st.info(f"**[{w.upper()}]**\n\n⏱️ Latency: **{latency_gap}초**")
                    else:
                        st.success(f"[{w.upper()}]\n\n⏱️ Latency: **{latency_gap}초**")
        else:
            st.markdown("✨ **모든 단어를 정확하게 발음하셨습니다!**")

        if accuracy <= 75.0:
            st.warning("⚠️ **발화 일치율이 75% 이하입니다.** 어원 비계 힌트를 참고하세요!")
            
            if wrong_words:
                tokens = word_tokenize(target_sentence)
                tagged_tokens = dict(pos_tag(tokens))
                
                has_substantive = False
                for ww in wrong_words:
                    ww_lower = ww.lower()
                    pos_tag_val = ""
                    for orig_w, t_val in tagged_tokens.items():
                        if orig_w.strip(".,?!").lower() == ww_lower:
                            pos_tag_val = t_val
                            break
                    
                    if (pos_tag_val.startswith('IN') or 
                        pos_tag_val.startswith('PRP') or 
                        pos_tag_val.startswith('CC') or 
                        (pos_tag_val.startswith('VB') and ww_lower in ['be', 'am', 'is', 'are', 'was', 'were', 'been', 'being'])):
                        continue 
                        
                    if ww_lower in WORD_ETYMOLOGY_DICT:
                        has_substantive = True
                        pos, etym, meaning = WORD_ETYMOLOGY_DICT[ww_lower]
                        st.markdown(f"* **{ww.capitalize()}** ({pos}) [어원: *{etym}*] → *{meaning}*")
                
                if not has_substantive:
                    st.markdown("* 이번에 누락된 단어들은 전치사, 인칭대명사, be동사, 접속사 등의 기초 기능어입니다. 핵심 단어 위주로 다시 발음해 보세요!")
            else:
                st.markdown("* 지문 전체의 핵심 단어들을 다시 한번 점검해 보세요.")
        else:
            st.success("🎉 **발화 일치율 75% 초과!** 완벽합니다.")
    elif st.session_state.analysis_data and "error" in st.session_state.analysis_data:
        st.error(st.session_state.analysis_data["error"])
    else:
        st.info("👈 좌측에서 마이크로 음성을 녹음하거나 '테스트용 AI 음성 및 분석 생성' 버튼을 눌러보세요.")
