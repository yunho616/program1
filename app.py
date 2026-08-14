import base64
import difflib
import io
import math
import shutil
import struct
import subprocess
import wave
from io import BytesIO
from urllib.parse import unquote_plus

from typing import List, Optional, Tuple, Dict

import numpy as np
import streamlit as st
import streamlit.components.v1 as components

# Optional libs detection
_have_pydub = False
_have_imageio_ffmpeg = False
_have_librosa = False
_have_crepe = False
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
    import crepe  # type: ignore
    _have_crepe = True
except Exception:
    crepe = None

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

def _get_query_params():
    if hasattr(st, "get_query_params"):
        return st.get_query_params()
    if hasattr(st, "experimental_get_query_params"):
        return st.experimental_get_query_params()
    if hasattr(st, "query_params"):
        return st.query_params
    return {}

def _set_query_params(params: Optional[dict] = None):
    if params is None:
        if hasattr(st, "set_query_params"):
            try:
                st.set_query_params()
            except TypeError:
                st.set_query_params(**{})
        elif hasattr(st, "experimental_set_query_params"):
            try:
                st.experimental_set_query_params()
            except TypeError:
                st.experimental_set_query_params(**{})
        return
    if hasattr(st, "set_query_params"):
        st.set_query_params(**params)
    elif hasattr(st, "experimental_set_query_params"):
        st.experimental_set_query_params(**params)

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


# ---------------------------
# Text Similarity Helper
# ---------------------------
def calculate_accuracy(target_text: str, user_text: str) -> float:
    """두 문장 간의 유사도(0.0 ~ 100.0%)를 계산합니다."""
    t_clean = target_text.strip().lower()
    u_clean = user_text.strip().lower()
    if not u_clean:
        return 0.0
    matcher = difflib.SequenceMatcher(None, t_clean, u_clean)
    return round(matcher.ratio() * 100, 1)


# ---------------------------
# Analyze audio bytes
# ---------------------------
def analyze_audio_bytes(raw_audio_bytes: bytes) -> Dict:
    try:
        wav_bytes = _ensure_wav_bytes(raw_audio_bytes)
        if wav_bytes is None:
            return {"error": "Failed to convert input to WAV. Install ffmpeg and pydub or imageio-ffmpeg."}
        samples, sr = parse_wav_bytes(wav_bytes)
    except Exception as e:
        return {"error": f"WAV parsing failed: {e}"}

    duration_sec = float(len(samples) / sr) if sr > 0 else 0.0
    total_rms = compute_rms(samples)
    zcr = compute_zcr(samples)
    snr_db = compute_snr(samples)

    if _have_webrtcvad:
        try:
            import array
            int16 = (samples * 32767.0).astype(np.int16)
            pcm_bytes = int16.tobytes()
            vad = webrtcvad.Vad(2)
            frame_ms = 30
            bytes_per_frame = int(sr * frame_ms / 1000.0) * 2
            frames = []
            for i in range(0, len(pcm_bytes), bytes_per_frame):
                chunk = pcm_bytes[i : i + bytes_per_frame]
                if len(chunk) < bytes_per_frame:
                    break
                frames.append(1 if vad.is_speech(chunk, sr) else 0)
            voicing = np.array(frames, dtype=int)
        except Exception:
            voicing = fallback_vad(samples, sr)
    else:
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
        "duration_sec": round(duration_sec, 2),
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
# Recorder HTML/JS (component)
# ---------------------------
def render_html_recorder(height: int = 240):
    html = """
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; padding: 12px; border: 1px solid #cbd5e1; border-radius: 12px; background: #f8fafc;">
  <div style="margin-bottom:8px;">
    <div id="status" style="font-size:14px;color:#64748b;">대기 중...</div>
  </div>
  <div style="display:flex;gap:8px;justify-content:center;">
    <button id="startBtn" style="background:#16a34a;color:white;padding:8px 14px;border:none;border-radius:8px;cursor:pointer;">🔴 녹음 시작</button>
    <button id="stopBtn" disabled style="background:#94a3b8;color:#ffffff;padding:8px 14px;border:none;border-radius:8px;cursor:default;">⏹️ 녹음 정지</button>
  </div>
  <div style="margin-top:8px;font-size:12px;color:#475569;">주의: URL 전송 방식은 긴 녹음에 실패할 수 있습니다. 짧은 문장(수초) 권장.</div>
</div>

<script>
let mediaRecorder = null;
let localStream = null;
let chunks = [];

const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const status = document.getElementById('status');

// 현재 날짜(YYYYMMDD) 생성 함수
function getTodayString() {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const day = String(today.getDate()).padStart(2, '0');
  return `${year}${month}${day}`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); document.body.removeChild(a); }, 1000);
}

startBtn.onclick = async () => {
  chunks = [];
  status.innerText = "🎙️ 녹음 중...";
  startBtn.disabled = true;
  startBtn.style.cursor = "default";
  
  stopBtn.disabled = false;
  stopBtn.style.background = "#ef4444";
  stopBtn.style.cursor = "pointer";

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    localStream = stream;
    try {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported('audio/webm')) {
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      } else {
        mediaRecorder = new MediaRecorder(stream);
      }
    } catch (err) {
      mediaRecorder = new MediaRecorder(stream);
    }

    mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };

    mediaRecorder.onstop = () => {
      status.innerText = "⚙️ 데이터 처리 중...";
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
      const reader = new FileReader();
      reader.readAsDataURL(blob);
      
      // 파일명 설정: YYYYMMDD_record.webm
      const dateStr = getTodayString();
      const defaultFilename = `${dateStr}_record.webm`;

      reader.onloadend = () => {
        const dataUrl = reader.result;
        try {
          const url = new URL(window.parent.location.href);
          url.searchParams.set('rec_b64', dataUrl);
          try {
            window.parent.location.replace(url.toString());
            return;
          } catch (err) {}
          try {
            window.top.location.replace(url.toString());
            return;
          } catch (err) {}
          downloadBlob(blob, defaultFilename);
          status.innerText = "녹음 파일을 다운로드했습니다. 업로드 기능을 사용하세요.";
        } catch (e) {
          downloadBlob(blob, defaultFilename);
          status.innerText = "오류 발생 — 파일을 다운로드했습니다.";
        }
      };
      try { if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; } } catch (e) {}
      
      stopBtn.disabled = true;
      stopBtn.style.background = "#94a3b8";
      stopBtn.style.cursor = "default";
      
      startBtn.disabled = false;
      startBtn.style.cursor = "pointer";
    };

    mediaRecorder.start();
  } catch (err) {
    const name = err && err.name ? err.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
      status.innerText = "❌ 마이크 권한이 필요합니다. 브라우저 설정에서 권한을 허용하세요.";
    } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      status.innerText = "❌ 마이크를 찾을 수 없습니다. 장치 연결을 확인하세요.";
    } else {
      status.innerText = "❌ 녹음을 시작할 수 없습니다: " + (err && err.message ? err.message : String(err));
      console.info("Recorder error:", err);
    }
    startBtn.disabled = false;
    startBtn.style.cursor = "pointer";
    
    stopBtn.disabled = true;
    stopBtn.style.background = "#94a3b8";
    stopBtn.style.cursor = "default";
  }
};

stopBtn.onclick = () => {
  try {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    if (localStream) {
      try { localStream.getTracks().forEach(t => t.stop()); } catch (_) {}
      localStream = null;
    } else if (mediaRecorder && mediaRecorder.stream) {
      try { mediaRecorder.stream.getTracks().forEach(t => t.stop()); } catch (_) {}
    }
  } catch (e) {
    console.warn("Stop error:", e);
  } finally {
    stopBtn.disabled = true;
    stopBtn.style.background = "#94a3b8";
    stopBtn.style.cursor = "default";
    
    startBtn.disabled = false;
    startBtn.style.cursor = "pointer";
  }
};
</script>
"""
    components.html(html, height=height, scrolling=False)


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

# Handle incoming rec_b64 query param
query_params = _get_query_params()
if "rec_b64" in query_params:
    try:
        raw_b64 = query_params["rec_b64"]
        if isinstance(raw_b64, (list, tuple)):
            raw_b64 = raw_b64[0]
        raw_b64 = unquote_plus(raw_b64)
        if raw_b64.startswith("data:"):
            _, b64 = raw_b64.split(",", 1)
        else:
            b64 = raw_b64
        raw_bytes = base64.b64decode(b64)
        wav_bytes = _ensure_wav_bytes(raw_bytes)
        if wav_bytes is None:
            st.session_state.last_error_msg = "오디오 포맷 변환 실패: 서버에서 WAV로 변환하지 못했습니다. ffmpeg/pydub 필요."
            st.session_state.analysis_data = {"error": "Conversion to WAV failed"}
            st.session_state.recorded_audio_bytes = None
        else:
            st.session_state.recorded_audio_bytes = wav_bytes
            st.session_state.analysis_data = analyze_audio_bytes(wav_bytes)
            st.session_state.last_error_msg = None
    except Exception as e:
        st.session_state.last_error_msg = f"음성 데이터 디코딩 실패: {e}"
    _set_query_params(None)
    _safe_rerun()

# --- Header ---
st.title("🛡️ 특허 1호 MVP: 음성 Latency 분석 및 자동 역번역 비계 튜터")
st.caption("AI-Powered Voice Scaffolding & Real-time Acoustic Latency Analyzer")

# --- Sidebar ---
st.sidebar.subheader("💡 학습 가이드")
st.sidebar.info("""
1. 마이크로 음성을 녹음하거나 오디오 파일을 업로드하세요.
2. 음성의 반응 속도(Latency)와 피치(Pitch) 등 핵심 지표가 자동으로 분석됩니다.
3. **목표 발화 대비 대본 일치율이 75% 이하일 때만 학습용 어원 힌트(Scaffolding)가 표시됩니다.**
""")

if st.session_state.last_error_msg:
    st.error(st.session_state.last_error_msg)

# 목표 발화 문장 정의
target_sentence = "We need to accelerate our business strategy to expand market share."

# Main layout
col_rec, col_scaff = st.columns([1, 1])

with col_rec:
    # 🎯 [이동 완료] 목표 발화를 최상단으로 배치
    st.markdown("**🎯 목표 발화 (Target Sentence):**")
    st.markdown(f"> \"{target_sentence}\"")
    
    st.subheader("1. 실시간 음성 수신 및 Latency 분석")
    render_html_recorder(260)

    st.write("---")
    st.write("📁 또는 테스트용 파일 업로드 (권장: WAV)")
    uploaded_file = st.file_uploader("WAV / WebM / OGG / MP3 파일 업로드", type=["wav", "webm", "ogg", "mp3", "m4a"])
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        if st.button("업로드 파일 분석 실행", use_container_width=True):
            wav_bytes = _ensure_wav_bytes(file_bytes)
            if wav_bytes is None:
                st.error("업로드한 파일을 WAV로 변환하지 못했습니다. ffmpeg/pydub가 필요합니다.")
            else:
                st.session_state.recorded_audio_bytes = wav_bytes
                st.session_state.analysis_data = analyze_audio_bytes(wav_bytes)
                _safe_rerun()

with col_scaff:
    st.subheader("2. AI 자동 역번역 비계 (Scaffolding)")

    # 음성 데이터가 분석되었을 때만 처리 진행
    if st.session_state.analysis_data and "error" not in st.session_state.analysis_data:
        user_transcript = st.text_input(
            "🗣️ 인식된 사용자 발화 (STT 결과 / 테스트 수정 가능):",
            value=st.session_state.user_transcript
        )
        st.session_state.user_transcript = user_transcript

        # 유사도(일치율) 계산
        accuracy = calculate_accuracy(target_sentence, user_transcript)
        
        # 일치율 표시
        st.metric("🎯 대본 일치율 (Accuracy)", f"{accuracy}%")

        # 75% 이하일 때만 어원 및 어휘 비계 힌트 출력
        if accuracy <= 75.0:
            st.warning("⚠️ **발화 일치율이 75% 이하입니다.** 아래 어원 비계(Scaffolding) 힌트를 참고하여 다시 시도해보세요!")
            st.markdown("**🔍 어원 및 어휘 비계(Scaffolding) 힌트:**")
            st.markdown("""
            * **Accelerate** (v.) [어원: *ac-* (향하여) + *celer* (빠른)] → *속도를 높이다, 가속하다*
            * **Strategy** (n.) [어원: *stratos* (군대) + *agein* (이끌다)] → *전략, 계획*
            * **Expand** (v.) [어원: *ex-* (밖으로) + *pandere* (펼치다)] → *확장하다*
            """)
        else:
            st.success("🎉 **발화 일치율이 75%를 초과했습니다!** 훌륭합니다. 비계 힌트 없이도 완벽하게 발화하셨습니다.")
    else:
        st.info("👈 좌측에서 음성을 녹음하거나 파일 분석을 먼저 진행해 주세요.")

# Analysis display
if st.session_state.analysis_data:
    st.divider()
    st.subheader("📊 음성 실시간 분석 결과 (Patent Metrics)")
    res = st.session_state.analysis_data

    if isinstance(res, dict) and "error" in res:
        st.error(res["error"])
    elif isinstance(res, dict):
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("⏱️ 음성 Latency", f"{res.get('latency_ms', 0)} ms")
        m2.metric("🎵 평균 Pitch", f"{res.get('avg_pitch_hz', 0)} Hz")
        m3.metric("🔊 Signal RMS", f"{res.get('total_rms', 0)}")
        m4.metric("📡 SNR (dB)", f"{res.get('snr_db', 0)} dB")
        m5.metric("⏳ 전체 길이", f"{res.get('duration_sec', 0)} 초")

        if st.session_state.recorded_audio_bytes:
            try:
                st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")
            except Exception:
                st.audio(st.session_state.recorded_audio_bytes)

        st.markdown("##### 📈 Voice Activity Detection (VAD) 타임라인")
        voicing_data = res.get("voicing_frames", [])
        if voicing_data:
            st.line_chart(voicing_data, height=150)
            st.caption("1: 음성 감지 | 0: 묵음")
    else:
        st.info("분석 결과가 없습니다. 좌측에서 녹음 또는 업로드 후 분석하세요.")
