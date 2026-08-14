import base64
import difflib
import io
import math
import shutil
import struct
import subprocess
import wave
from io import BytesIO
from typing import List, Optional, Tuple, Dict

import numpy as np
import streamlit as st

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
    webrtcvad = None


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


def calculate_accuracy(target_text: str, user_text: str) -> float:
    t_clean = target_text.strip().lower()
    u_clean = user_text.strip().lower()
    if not u_clean:
        return 0.0
    matcher = difflib.SequenceMatcher(None, t_clean, u_clean)
    return round(matcher.ratio() * 100, 1)


def analyze_audio_bytes(raw_audio_bytes: bytes) -> Dict:
    try:
        wav_bytes = _ensure_wav_bytes(raw_audio_bytes)
        if wav_bytes is None:
            return {"error": "Failed to convert input to WAV."}
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

    return {
        "duration_sec": round(duration_sec, 1),
        "total_rms": round(total_rms, 6),
        "zcr": round(zcr, 6),
        "snr_db": round(snr_db, 2),
        "latency_ms": round(latency_ms, 1),
        "avg_pitch_hz": round(avg_pitch, 1),
        "sample_rate": sr,
        "num_samples": samples.size,
        "voicing_frames": voicing.tolist(),
    }


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
    st.session_state.user_transcript = "We need accelerate business strategy to expand."

st.title("🛡️ 특허 1호 MVP: 음성 Latency 분석 및 자동 역번역 비계 튜터")
st.caption("AI-Powered Voice Scaffolding & Real-time Acoustic Latency Analyzer")

st.sidebar.subheader("💡 학습 가이드")
st.sidebar.info("""
1. 마이크 직접 녹음기 버튼을 눌러 음성을 녹음하세요.
2. '🎙️ 테스트용 사운드'의 AI 음성 생성 버튼을 누르면 테스트용 오디오와 분석 결과가 제공됩니다.
3. 오른쪽 영역에서 녹음된 오디오를 듣고 인식된 발화를 확인하세요.
""")

if st.session_state.last_error_msg:
    st.error(st.session_state.last_error_msg)

target_sentence = "We need to accelerate our business strategy to expand market share."

col_rec, col_scaff = st.columns([1, 1])

with col_rec:
    st.markdown("**🎯 오늘의 학습 지문:**")
    st.markdown(f"> \"{target_sentence}\"")
    
    st.subheader("1. 마이크 실시간 녹음")
    
    # 마이크 직접 녹음기 위젯
    audio_file = st.audio_input("마이크 직접 녹음기")

    if audio_file is not None:
        raw_bytes = audio_file.read()
        if st.session_state.get("last_raw_bytes") != raw_bytes:
            st.session_state.last_raw_bytes = raw_bytes
            wav_bytes = _ensure_wav_bytes(raw_bytes)
            if wav_bytes is not None:
                st.session_state.recorded_audio_bytes = wav_bytes
                st.session_state.analysis_data = analyze_audio_bytes(wav_bytes)
                st.session_state.last_error_msg = None
            else:
                st.session_state.last_error_msg = "오디오 포맷 변환 실패: WAV로 변환하지 못했습니다."

    st.write("---")
    
    # 🎙️ 테스트용 사운드 영역
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
            "voicing_frames": [1, 1, 1, 1]
        }
        st.session_state.user_transcript = "We need accelerate business strategy to expand."
        st.toast("테스트용 사운드와 분석 데이터가 생성되었습니다!")
        _safe_rerun()

    st.write("---")

    if st.button("🔄 녹음 데이터 초기화", use_container_width=True):
        st.session_state.recorded_audio_bytes = None
        st.session_state.analysis_data = None
        st.session_state.last_error_msg = None
        st.toast("녹음 데이터와 분석 결과가 초기화되었습니다.")
        _safe_rerun()

with col_scaff:
    st.subheader("2. AI 자동 역번역 비계 (Scaffolding)")

    if st.session_state.analysis_data and "error" not in st.session_state.analysis_data:
        res = st.session_state.analysis_data
        st.markdown("##### 📊 음성 데이터 분석 결과")
        
        # 녹음 시간(0.1초 단위), WPM, CPM을 나란히 배치하기 위해 3개 컬럼 생성
        duration_val = res.get('duration_sec', 0.0)
        
        # 발화 텍스트 기반 WPM / CPM 대략적 계산
        words = [w for w in st.session_state.user_transcript.split() if w.strip()]
        num_words = len(words)
        num_chars = len(st.session_state.user_transcript.replace(" ", ""))
        
        if duration_val > 0:
            wpm = int((num_words / duration_val) * 60)
            cpm = int((num_chars / duration_val) * 60)
        else:
            wpm = 0
            cpm = 0

        m1, m2, m3 = st.columns(3)
        m1.metric("⏱️ 녹음 시간", f"{duration_val:.1f} 초")
        m2.metric("WPM", f"{wpm}")
        m3.metric("CPM", f"{cpm}")

        st.write("---")
        
        # 🔊 사용자가 녹음한 오디오 재생 플레이어
        if st.session_state.recorded_audio_bytes:
            st.markdown("🔊 **내 녹음 듣기:**")
            st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")

        user_transcript = st.text_input("🗣️ 인식된 사용자 발화:", value=st.session_state.user_transcript)
        st.session_state.user_transcript = user_transcript

        accuracy = calculate_accuracy(target_sentence, user_transcript)
        st.metric("🎯 대본 일치율 (Accuracy)", f"{accuracy}%")

        if accuracy <= 75.0:
            st.warning("⚠️ **발화 일치율이 75% 이하입니다.** 어원 비계 힌트를 참고하세요!")
            st.markdown("""
            * **Accelerate** (v.) [어원: *ac-* + *celer*] → *가속하다*
            * **Strategy** (n.) [어원: *stratos* + *agein*] → *전략*
            * **Expand** (v.) [어원: *ex-* + *pandere*] → *확장하다*
            """)
        else:
            st.success("🎉 **발화 일치율 75% 초과!** 완벽합니다.")
    elif st.session_state.analysis_data and "error" in st.session_state.analysis_data:
        st.error(st.session_state.analysis_data["error"])
    else:
        st.info("👈 좌측에서 마이크로 음성을 녹음하거나 '테스트용 AI 음성 및 분석 생성' 버튼을 눌러보세요.")
