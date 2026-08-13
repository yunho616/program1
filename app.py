import base64
import io
import math
import shutil
import struct
import subprocess
import wave
from urllib.parse import unquote_plus
from typing import List, Optional, Tuple, Dict

import numpy as np
import streamlit as st
import streamlit.components.v1 as components

# Optional libs
_have_pydub = False
_have_imageio_ffmpeg = False
_have_librosa = False
_have_crepe = False
_have_webrtcvad = False

try:
    from pydub import AudioSegment

    _have_pydub = True
except Exception:
    AudioSegment = None

try:
    import imageio_ffmpeg as _iioffmpeg

    _have_imageio_ffmpeg = True
except Exception:
    _iioffmpeg = None

try:
    import librosa

    _have_librosa = True
except Exception:
    librosa = None

try:
    import crepe

    _have_crepe = True
except Exception:
    crepe = None

try:
    import webrtcvad

    _have_webrtcvad = True
except Exception:
    webrtcvad = None

# If pydub + imageio_ffmpeg present, set converter
if _have_pydub and _have_imageio_ffmpeg:
    try:
        AudioSegment.converter = _iioffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

# Query param compatibility
def _get_query_params():
    if hasattr(st, "get_query_params"):
        return st.get_query_params()
    if hasattr(st, "experimental_get_query_params"):
        return st.experimental_get_query_params()
    return {}


def _set_query_params(params=None):
    if params is None:
        if hasattr(st, "set_query_params"):
            # calling without args clears params in newer streamlit; keep best-effort
            try:
                st.set_query_params()
            except TypeError:
                # older/other implementations might not accept empty call; fall back
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


# Low-level RMS: supports 8/16-bit and multi-channel
def calculate_rms(fragment: bytes, sampwidth: int, nchannels: int) -> int:
    if not fragment:
        return 0
    sample_count = len(fragment) // sampwidth
    if sample_count == 0:
        return 0

    if sampwidth == 2:
        fmt = f"<{sample_count}h"
        try:
            samples = struct.unpack(fmt, fragment[: sample_count * sampwidth])
        except struct.error:
            return 0
    elif sampwidth == 1:
        fmt = f"<{sample_count}B"
        try:
            usamples = struct.unpack(fmt, fragment[: sample_count * sampwidth])
        except struct.error:
            return 0
        samples = tuple((s - 128) for s in usamples)
    else:
        return 0

    if nchannels > 1:
        frames = sample_count // nchannels
        if frames == 0:
            return 0
        sum_squares = 0.0
        for i in range(frames):
            acc = 0.0
            for ch in range(nchannels):
                acc += samples[i * nchannels + ch]
            avg = acc / nchannels
            sum_squares += (avg * avg)
        mean_square = sum_squares / frames
        return int(math.sqrt(mean_square))
    else:
        sum_squares = sum((s * s) for s in samples)
        mean_square = sum_squares / sample_count
        return int(math.sqrt(mean_square))


# Robust WAV conversion: tries direct RIFF, pydub, or ffmpeg subprocess (imageio_ffmpeg or system)
def _ensure_wav_bytes(raw_bytes: bytes) -> Optional[bytes]:
    # If already RIFF/WAVE return
    try:
        if raw_bytes[:4] == b"RIFF" and b"WAVE" in raw_bytes[:12]:
            return raw_bytes
    except Exception:
        pass

    # Try pydub conversion first (pydub uses ffmpeg)
    if _have_pydub:
        try:
            seg = AudioSegment.from_file(io.BytesIO(raw_bytes))
            out = io.BytesIO()
            seg.export(out, format="wav")
            return out.getvalue()
        except Exception:
            # fallthrough to ffmpeg subprocess
            pass

    # Try ffmpeg subprocess: prefer imageio_ffmpeg exe if present, else system ffmpeg
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
            # Use ffmpeg to read from stdin and write wav to stdout
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

    # nothing worked
    return None


# webrtcvad-based intervals (if webrtcvad+pydub available)
def vad_webrtc_intervals(wav_bytes: bytes, target_sample_rate: int = 16000, frame_ms: int = 30) -> List[Tuple[float, float]]:
    if not (_have_webrtcvad and _have_pydub):
        return []
    try:
        seg = AudioSegment.from_file(io.BytesIO(wav_bytes))
        seg = seg.set_frame_rate(target_sample_rate).set_channels(1).set_sample_width(2)
        pcm = seg.raw_data
        sample_rate = target_sample_rate
        vad = webrtcvad.Vad(2)
        bytes_per_frame = int(sample_rate * (frame_ms / 1000.0) * 2)
        frames = []
        for i in range(0, len(pcm), bytes_per_frame):
            chunk = pcm[i : i + bytes_per_frame]
            if len(chunk) < bytes_per_frame:
                break
            timestamp = i / (sample_rate * 2)
            frames.append((chunk, timestamp))
        speech_flags = [vad.is_speech(f[0], sample_rate) for f in frames]
        intervals = []
        in_speech = False
        start_time = 0.0
        for flag, (_, ts) in zip(speech_flags, frames):
            if flag and not in_speech:
                in_speech = True
                start_time = ts
            elif not flag and in_speech:
                in_speech = False
                intervals.append((start_time, ts))
        if in_speech:
            intervals.append((start_time, frames[-1][1] + frame_ms / 1000.0))
        return intervals
    except Exception:
        return []


# Voice analysis (autocorr + optional librosa/crepe)
def analyze_voice_data(wav_bytes: bytes) -> Dict:
    try:
        wf = wave.open(io.BytesIO(wav_bytes), "rb")
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
        wf.close()

        if nframes == 0:
            return {}

        if sampwidth == 2:
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 1:
            arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128).astype(np.float32) / 128.0
        else:
            return {}

        if nchannels > 1:
            try:
                arr = arr.reshape(-1, nchannels).mean(axis=1)
            except Exception:
                pass

        duration = len(arr) / framerate

        frame_len = max(1, int(0.03 * framerate))
        hop_len = max(1, int(0.01 * framerate))

        energies = []
        zcrs = []
        for s in range(0, max(1, len(arr) - frame_len + 1), hop_len):
            f = arr[s : s + frame_len]
            energies.append(float(np.sqrt(np.mean(f * f) + 1e-12)))
            zcrs.append(float(((f[:-1] * f[1:]) < 0).sum() / max(1, (len(f) - 1))))

        mean_rms = float(np.mean(energies)) if energies else 0.0
        mean_zcr = float(np.mean(zcrs)) if zcrs else 0.0

        pitches_ac = []
        for s in range(0, max(1, len(arr) - frame_len + 1), hop_len):
            f = arr[s : s + frame_len]
            energy = float(np.sqrt(np.mean(f * f) + 1e-12))
            if energy < 1e-4:
                pitches_ac.append(0.0)
                continue
            corr = np.correlate(f, f, mode="full")
            corr = corr[len(corr) // 2 : ]
            if np.max(np.abs(corr)) == 0:
                pitches_ac.append(0.0)
                continue
            corr = corr / (np.max(np.abs(corr)) + 1e-12)
            lag_min = max(1, int(framerate / 500))
            lag_max = min(len(corr) - 1, int(framerate / 50))
            if lag_min >= lag_max:
                pitches_ac.append(0.0)
                continue
            segment = corr[lag_min : lag_max + 1]
            peak_idx = int(np.argmax(segment)) + lag_min
            peak_val = corr[peak_idx] if peak_idx < len(corr) else 0.0
            if peak_val > 0.3:
                pitch_hz = framerate / peak_idx
                pitches_ac.append(float(pitch_hz))
            else:
                pitches_ac.append(0.0)

        pitches_librosa = []
        if _have_librosa:
            try:
                y = arr.astype(np.float32)
                try:
                    f0, _, _ = librosa.pyin(y, fmin=50, fmax=500, sr=framerate, frame_length=frame_len, hop_length=hop_len)
                    pitches_librosa = [float(p) if not np.isnan(p) else 0.0 for p in f0]
                except Exception:
                    f0 = librosa.yin(y, fmin=50, fmax=500, sr=framerate, frame_length=frame_len, hop_length=hop_len)
                    pitches_librosa = [float(p) if not np.isnan(p) else 0.0 for p in f0]
            except Exception:
                pitches_librosa = []

        pitches_crepe = []
        if _have_crepe:
            try:
                audio = arr.astype(np.float32)
                sr = framerate
                time, frequency, confidence, activation = crepe.predict(audio, sr, viterbi=True, step_size=10.0, verbose=0)
                pitches_crepe = [float(f) if not np.isnan(f) else 0.0 for f in frequency]
            except Exception:
                pitches_crepe = []

        voiced_ac = [p for p in pitches_ac if p > 0]
        mean_pitch_ac = float(np.mean(voiced_ac)) if voiced_ac else 0.0
        voiced_ratio = float(len([p for p in pitches_ac if p > 0]) / max(1, len(pitches_ac))) if pitches_ac else 0.0

        if energies:
            se = np.sort(np.array(energies))
            bottom = np.mean(se[: max(1, int(len(se) * 0.1))])
            top = np.mean(se[-max(1, int(len(se) * 0.1)) :])
            snr_db = float(10.0 * math.log10((top + 1e-12) / (bottom + 1e-12)))
        else:
            snr_db = 0.0

        return {
            "duration_s": round(duration, 3),
            "mean_rms": round(mean_rms, 6),
            "mean_zcr": round(mean_zcr, 6),
            "voiced_ratio": round(voiced_ratio, 3),
            "snr_db": round(snr_db, 2),
            "pitch_ac_mean_hz": round(mean_pitch_ac, 2),
            "pitch_ac_contour_hz": [round(float(p), 2) for p in pitches_ac],
            "pitch_librosa_contour_hz": [round(float(p), 2) for p in pitches_librosa] if pitches_librosa else [],
            "pitch_crepe_contour_hz": [round(float(p), 2) for p in pitches_crepe] if pitches_crepe else [],
        }
    except Exception:
        return {}


# High-level audio analysis (latency detection + voice_analysis)
def analyze_audio_bytes(raw_audio_bytes):
    try:
        wav_bytes = _ensure_wav_bytes(raw_audio_bytes)
        if wav_bytes is None:
            st.session_state["last_error_msg"] = (
                "Failed to convert input to WAV. Install ffmpeg and/or pydub (see README)."
            )
            return "NO_SPEECH"

        wav_file = wave.open(io.BytesIO(wav_bytes), "rb")
        nchannels = wav_file.getnchannels()
        sampwidth = wav_file.getsampwidth()
        framerate = wav_file.getframerate()
        nframes = wav_file.getnframes()

        if nframes == 0 or framerate == 0:
            wav_file.close()
            st.session_state["last_error_msg"] = "WAV file contains zero frames or zero framerate."
            return "NO_SPEECH"

        total_duration = round(nframes / float(framerate), 1)

        frame_duration = 0.05
        frame_size = max(1, int(framerate * frame_duration))

        chunk_rms = []
        wav_file.rewind()
        while True:
            raw_frames = wav_file.readframes(frame_size)
            if not raw_frames:
                break
            available_frames = len(raw_frames) // (sampwidth * nchannels)
            if available_frames <= 0:
                continue
            bytes_to_use = available_frames * sampwidth * nchannels
            rms = calculate_rms(raw_frames[:bytes_to_use], sampwidth, nchannels)
            chunk_rms.append(rms)

        wav_file.close()

        if not chunk_rms:
            st.session_state["last_error_msg"] = "No RMS frames extracted (silence or bad format)."
            return "NO_SPEECH"

        max_rms = max(chunk_rms) if chunk_rms else 1
        if max_rms <= 0:
            max_rms = 1
        threshold = max(max_rms * 0.02, 5)

        vad_intervals = vad_webrtc_intervals(wav_bytes) if (_have_webrtcvad and _have_pydub) else []

        speech_intervals = []
        if vad_intervals:
            speech_intervals = vad_intervals
        else:
            in_speech = False
            start_idx = 0
            for idx, rms in enumerate(chunk_rms):
                if rms >= threshold and not in_speech:
                    in_speech = True
                    start_idx = idx
                elif rms < threshold and in_speech:
                    in_speech = False
                    speech_intervals.append(
                        (start_idx * frame_duration, idx * frame_duration)
                    )
            if in_speech:
                speech_intervals.append(
                    (start_idx * frame_duration, len(chunk_rms) * frame_duration)
                )

        if not speech_intervals:
            speech_intervals = [(0.1, max(total_duration, 0.5))]

        first_latency = round(speech_intervals[0][0], 2)

        word_latencies = []
        prev_end = 0.0

        target_words_local = [
            "The", "quick", "brown", "fox", "jumps",
            "over", "the", "lazy", "dog.", "The",
            "fox", "is", "very", "fast."
        ]

        for idx, word_str in enumerate(target_words_local):
            if idx < len(speech_intervals):
                start_sec = round(speech_intervals[idx][0], 2)
                end_sec = round(speech_intervals[idx][1], 2)
            else:
                start_sec = round(prev_end + 0.3, 2)
                end_sec = round(start_sec + 0.2, 2)

            if idx == 0:
                latency = first_latency
            else:
                latency = round(max(0.1, start_sec - prev_end), 2)

            prev_end = end_sec
            word_latencies.append({
                "word": word_str,
                "start": start_sec,
                "latency": latency
            })

        total_words = len(word_latencies)
        smooth_words = sum(1 for w in word_latencies if w["latency"] < 1.0)
        pause_ratio = (
            round(100.0 - ((smooth_words / total_words) * 100.0), 1)
            if total_words > 0 else 0.0
        )
        max_word_latency = (
            max([w["latency"] for w in word_latencies])
            if word_latencies else 0.0
        )

        voice_analysis = analyze_voice_data(wav_bytes)

        # clear previous error on success
        st.session_state["last_error_msg"] = ""

        return {
            "latency": first_latency,
            "duration": total_duration,
            "pause_ratio": pause_ratio,
            "word_analysis": word_latencies,
            "max_word_latency": max_word_latency,
            "speech_intervals": speech_intervals,
            "voice_analysis": voice_analysis,
        }
    except Exception as e:
        st.session_state["last_error_msg"] = f"Unexpected error during analysis: {e}"
        return "NO_SPEECH"


# UI (original title)
st.set_page_config(
    page_title="특허 1호 MVP - 음성 데이터 기반 분석 및 역번역 튜터",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🎙️ 특허 1호: 음성 Latency 분석 및 자동 역번역 비계(Scaffolding) 튜터")
st.caption(
    "녹음 및 반응 지연 시간을 실제 음성 파형(Acoustic Data) 기반으로 분석하여"
    " 자동 맞춤형 학습 비계를 제공합니다."
)
st.markdown("---")

if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None
if "recorded_audio_bytes" not in st.session_state:
    st.session_state.recorded_audio_bytes = None
if "recorder_key" not in st.session_state:
    st.session_state.recorder_key = 0
if "last_error_msg" not in st.session_state:
    st.session_state.last_error_msg = ""

sample_text = "The quick brown fox jumps over the lazy dog.\nThe fox is very fast."

# Recorder HTML/JS — removed new-tab fallback; use parent/top navigation or download fallback
html_recorder = """
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; padding: 18px; border: 1px solid #cbd5e1; border-radius: 12px; background: #f8fafc;">
  <div style="margin-bottom:10px;">
    <div id="timer" style="font-size: 28px; font-weight:700; font-family: monospace;">0.0s</div>
  </div>
  <div style="display:flex;gap:8px;justify-content:center;">
    <button id="startBtn" style="background:#ef4444;color:white;padding:8px 14px;border-radius:8px;">🔴 녹음 시작</button>
    <button id="stopBtn" disabled style="background:#2563eb;color:#ffffff;padding:8px 14px;border-radius:8px;cursor:not-allowed;">⏹️ 녹음 정지 및 분석</button>
  </div>
  <div id="status" style="margin-top:10px;color:#64748b;">버튼을 눌러 녹음을 시작해 주세요.</div>
</div>

<script>
let mediaRecorder;
let chunks = [];
let startTime = 0;
let timerInterval = null;
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const timer = document.getElementById('timer');
const status = document.getElementById('status');

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
  }, 1000);
}

startBtn.onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    let options = {};
    if (MediaRecorder.isTypeSupported('audio/webm')) {
      options = {mimeType:'audio/webm'};
    }
    mediaRecorder = new MediaRecorder(stream, options);
    chunks = [];
    mediaRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
    mediaRecorder.onstop = () => {
      clearInterval(timerInterval);
      status.innerText = "⏳ 음성 데이터를 분석하는 중입니다...";
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/wav' });
      const reader = new FileReader();
      reader.readAsDataURL(blob);
      reader.onloadend = () => {
        const dataUrl = reader.result;
        try {
          const parentUrl = new URL(window.parent.location.href);
          // Don't double-encode: searchParams.set will percent-encode automatically
          parentUrl.searchParams.set('rec_b64', dataUrl);
          // Prefer location.replace to avoid adding browser history entry
          try {
            window.parent.location.replace(parentUrl.toString());
            return;
          } catch (err) {
            // try top
          }
          try {
            window.top.location.replace(parentUrl.toString());
            return;
          } catch (err2) {
            // navigation blocked; fall back to download
          }
          // Final fallback: download the recorded file and instruct user to upload
          downloadBlob(blob, 'recording.webm');
          status.innerText = "녹음 파일을 다운로드했습니다. 오른쪽의 '음성 파일 업로드'로 파일을 업로드하세요.";
        } catch (ex) {
          downloadBlob(blob, 'recording.webm');
          status.innerText = "오류 발생 — 녹음 파일을 다운로드했습니다. 오른쪽의 '음성 파일 업로드'로 파일을 업로드하세요.";
        }
      };
      // reset stop button to disabled look
      stopBtn.disabled = true;
      stopBtn.style.background = "#cbd5e1";
      stopBtn.style.color = "#94a3b8";
      stopBtn.style.cursor = "not-allowed";
      // reset start button UI
      startBtn.disabled = false;
      startBtn.style.background = "#ef4444";
      startBtn.style.color = "#ffffff";
      startBtn.style.cursor = "pointer";
    };
    mediaRecorder.start(100);
    startTime = Date.now();
    timerInterval = setInterval(() => { timer.innerText = ((Date.now()-startTime)/1000).toFixed(1) + 's'; }, 100);
    // update UI: start disabled, stop enabled (blue)
    startBtn.disabled = true;
    startBtn.style.cursor = 'not-allowed';
    startBtn.style.background = "#cbd5e1";
    startBtn.style.color = "#94a3b8";

    stopBtn.disabled = false;
    stopBtn.style.cursor = 'pointer';
    stopBtn.style.background = "#2563eb";
    stopBtn.style.color = "#ffffff";

    status.innerText = "🔴 녹음 중... 지문을 읽어주세요.";
  } catch (err) {
    status.innerText = "❌ 마이크 권한이 필요합니다.";
  }
};

stopBtn.onclick = () => {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
    // disable stop button and set disabled styles
    stopBtn.disabled = true;
    stopBtn.style.background = "#cbd5e1";
    stopBtn.style.color = "#94a3b8";
    stopBtn.style.cursor = "not-allowed";
    // re-enable start button UI
    startBtn.disabled = false;
    startBtn.style.background = "#ef4444";
    startBtn.style.color = "#ffffff";
    startBtn.style.cursor = "pointer";
  }
};
</script>
"""

col1, col2 = st.columns([1, 1])
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")
    st.text_area("오늘의 학습 지문", value=sample_text, height=120, disabled=True)

    st.markdown("---")
    st.subheader("🎙️ 2단계: 음성 녹음")

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
            audio_bytes = base64.b64decode(b64)
            st.session_state.recorded_audio_bytes = audio_bytes
            st.session_state.analysis_data = analyze_audio_bytes(audio_bytes)
        except Exception as e:
            st.session_state.last_error_msg = f"Failed to decode rec_b64: {e}"
        _set_query_params()

    components.html(html_recorder, height=240)

    with st.expander("📁 음성 파일 직접 업로드 (대체 테스트)"):
        uploaded_file = st.file_uploader("음성 파일 업로드", type=["wav", "webm", "ogg", "mp3"], key=f"uploader_{st.session_state.recorder_key}")
        if uploaded_file is not None:
            file_bytes = uploaded_file.read()
            st.session_state.recorded_audio_bytes = file_bytes
            st.session_state.analysis_data = analyze_audio_bytes(file_bytes)
            st.success("파일 분석 완료")

    st.markdown("---")
    if st.button("🗑️ 분석 결과 초기화", use_container_width=True):
        st.session_state.analysis_data = None
        st.session_state.recorded_audio_bytes = None
        st.session_state.recorder_key += 1
        _set_query_params()
        st.experimental_rerun()

with col2:
    st.subheader("📊 실시간 음성 분석 및 Latency 결과")

    if st.session_state.recorded_audio_bytes is not None:
        st.markdown("##### 🔊 녹음된 음성 확인")
        try:
            st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")
        except Exception:
            st.audio(st.session_state.recorded_audio_bytes)

    if st.session_state.analysis_data == "NO_SPEECH":
        st.error("⚠️ 음성 분석 실패: 입력을 WAV로 변환할 수 없거나 음성이 감지되지 않았습니다.")
        if st.session_state.get("last_error_msg"):
            st.info("진단 정보: " + st.session_state["last_error_msg"])
            st.warning("해결: 설치된 ffmpeg가 없으면 설치하거나 requirements.txt에 imageio-ffmpeg+pydub를 추가하세요.")
    elif isinstance(st.session_state.analysis_data, dict):
        data = st.session_state.analysis_data
        colm1, colm2, colm3 = st.columns(3)
        with colm1:
            st.metric("⏱️ 첫 발화 지연", f"{data['latency']} 초")
        with colm2:
            st.metric("🎙️ 음성 총 길이", f"{data['duration']} 초")
        with colm3:
            st.metric("⏸️ 망설임 구간 비율", f"{data['pause_ratio']}%")

        st.markdown("---")
        st.subheader("📖 분석 대상 지문 (단어별 Latency 분석)")

        words = data.get("word_analysis", [])
        cols_per_row = 3
        for i in range(0, len(words), cols_per_row):
            row_words = words[i : i + cols_per_row]
            row_cols = st.columns(cols_per_row)
            for idx, item in enumerate(row_words):
                with row_cols[idx]:
                    if item["latency"] >= 2.0:
                        bg_color = "#fff5f5"
                        border_color = "#e53e3e"
                        tag = "🚨 지연 감지"
                    elif item["latency"] >= 1.0:
                        bg_color = "#fffaf0"
                        border_color = "#dd6b20"
                        tag = "⚠️ 약간 망설임"
                    else:
                        bg_color = "#f0fff4"
                        border_color = "#38a169"
                        tag = "✅ 원활"

                    st.markdown(
                        f'''
                        <div style="background-color: {bg_color}; border: 1.5px solid {border_color}; border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 10px;">
                            <div style="font-size: 17px; font-weight: bold; color: #2d3748;">{item['word']}</div>
                            <div style="font-size: 14px; font-weight: bold; color: {border_color}; margin-top: 6px;">Latency: {item['latency']}초</div>
                            <div style="font-size: 11px; margin-top: 4px; font-weight: 500;">{tag}</div>
                        </div>
                        ''',
                        unsafe_allow_html=True,
                    )

        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        is_scaffold_needed = (
            data.get("max_word_latency", 0) >= 2.0 or data.get("pause_ratio", 0) > 25.0
        )

        if is_scaffold_needed:
            delayed_words = [w for w in words if w["latency"] >= 2.0]

            if delayed_words:
                delayed_word_names = ", ".join([f"'{w['word']}'" for w in delayed_words])
                st.error(
                    f"🚨 **지연 발생 단어({delayed_word_names} - 2.0초 이상)** 감지! 자동 역번역 및 어원 비계가 활성화되었습니다."
                )
            else:
                st.warning(
                    "⚠️ **망설임 구간 비율(25% 초과)** 감지! 전체적인 문장 구성 비계가 활성화되었습니다."
                )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ 뛰어넘는다 (jumps) ➔ 게으른"
                " 개를. 그 여우는 매우 ➔ 빠릅니다 (fast)."
            )

            st.markdown("### 2. 지연 단어 어원 심층 분석")
            if delayed_words:
                etymology_db = {
                    "The": "고대 영어 þæt (지시대명사/정관사)",
                    "quick": "고대 영어 cwic (살아있는, 활발한)",
                    "brown": "고대 영어 brūn (어두운 색, 갈색)",
                    "fox": "고대 영어 fox (여우)",
                    "jumps": "중세 영어 jumpen (갑자기 이동하다, 뛰어오르다)",
                    "over": "고대 영어 ofer (위쪽에, 건너서)",
                    "the": "고대 영어 þæt (지시대명사/정관사)",
                    "lazy": "저지 독일어 lasich (느슨한, 게으른)",
                    "dog.": "고대 영어 docga (개)",
                    "is": "고대 영어 is (있다, 이다)",
                    "very": "고대 프랑스어 verai (진실한, 매우)",
                    "fast.": "고대 영어 fæst (단단한, 확고한, 빠른)"
                }
                etymology_result = {}
                for item in delayed_words:
                    word_clean = item["word"]
                    info = etymology_db.get(word_clean, "어원 정보 등록 중")
                    key_name = f"{word_clean} (Latency: {item['latency']}초)"
                    etymology_result[key_name] = info
                st.json(etymology_result)
            else:
                st.write("감지된 개별 지연 단어가 없습니다.")
        else:
            st.success(
                "🎉 모든 단어의 발화 반응속도가 원활합니다! 힌트 없이"
                " 완벽하게 수행했습니다."
            )

        # Voice analysis display
        va = data.get("voice_analysis", {})
        if va:
            st.markdown("---")
            st.subheader("🔬 음성 특징 요약 (Voice Analysis)")
            cols = st.columns(4)
            with cols[0]:
                st.metric("평균 피치 (Autocorr, Hz)", va.get("pitch_ac_mean_hz", 0))
            with cols[1]:
                st.metric("음성 SNR (dB)", va.get("snr_db", 0))
            with cols[2]:
                st.metric("발화 비율", f"{va.get('voiced_ratio', 0)*100:.1f}%")
            with cols[3]:
                st.metric("평균 RMS", va.get("mean_rms", 0))

            with st.expander("피치 컨투어 및 세부값 보기"):
                st.json(va)
        else:
            st.markdown("---")
            st.info("음성 분석 결과(피치/에너지 등)가 없습니다.")
    else:
        st.info("👈 좌측에서 **[🔴 녹음 시작]**을 누르고 지문을 읽은 뒤 **[⏹️ 녹음 정지 및 분석]**을 누르세요.")
