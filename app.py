import base64
import math
import struct
import wave
from io import BytesIO
from urllib.parse import unquote_plus, quote_plus

import numpy as np
import streamlit as st

# ==========================================
# 0. STREAMLIT CONFIG & UTILS
# ==========================================
st.set_page_config(
    page_title="Patent #1 MVP - Voice Scaffolding & Latency Analyzer",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Helper for Query Params across Streamlit Versions
def _get_query_params():
    if hasattr(st, "query_params"):
        return st.query_params
    elif hasattr(st, "experimental_get_query_params"):
        return st.experimental_get_query_params()
    return {}

def _set_query_params(params_dict=None):
    if params_dict is None:
        params_dict = {}
    if hasattr(st, "query_params"):
        st.query_params.clear()
        for k, v in params_dict.items():
            st.query_params[k] = v
    elif hasattr(st, "experimental_set_query_params"):
        st.experimental_set_query_params(**params_dict)

# Safe Rerun helper
def _safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()


# ==========================================
# 1. OPTIONAL LIBRARIES (FALLBACK IMPLEMENTATIONS)
# ==========================================
try:
    import webrtcvad
    HAS_WEBRTCVAD = True
except ImportError:
    HAS_WEBRTCVAD = False

try:
    import pydub
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False


# ==========================================
# 2. AUDIO PROCESSING & DSP CORE LOGIC
# ==========================================
def parse_wav_bytes(audio_bytes):
    """
    Python 표준 wave 라이브러리를 사용해 WAV 바이너리에서 PCM 샘플을 추출합니다.
    """
    with wave.open(BytesIO(audio_bytes), 'rb') as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_frames = wf.readframes(n_frames)
    
    # 16-bit PCM (2 bytes per sample) 기준 처리
    if sampwidth == 2:
        fmt = f"<{n_frames * n_channels}h"
        samples = np.array(struct.unpack(fmt, raw_frames), dtype=np.float32) / 32768.0
    elif sampwidth == 1:
        # 8-bit unsigned
        fmt = f"<{n_frames * n_channels}B"
        samples = (np.array(struct.unpack(fmt, raw_frames), dtype=np.float32) - 128.0) / 128.0
    else:
        # 기타 sample width일 경우 float 변환
        samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0

    # 스테레오일 경우 모노로 변환
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    return samples, framerate


def compute_rms(samples):
    """RMS (Root Mean Square) 에너지 계산"""
    if len(samples) == 0:
        return 0.0
    return math.sqrt(np.mean(samples ** 2))


def compute_zcr(samples):
    """Zero Crossing Rate (영교차율) 계산"""
    if len(samples) < 2:
        return 0.0
    zero_crossings = np.diff(np.signbit(samples))
    return np.sum(zero_crossings != 0) / (len(samples) - 1)


def compute_snr(samples):
    """간이 Signal-to-Noise Ratio (SNR, dB) 추정"""
    rms_total = compute_rms(samples)
    if rms_total < 1e-6:
        return 0.0
    # 하위 10% 에너지를 Noise Floor로 추정
    sorted_abs = np.sort(np.abs(samples))
    noise_floor = np.mean(sorted_abs[:max(1, int(len(sorted_abs) * 0.1))])
    if noise_floor < 1e-6:
        noise_floor = 1e-6
    snr_db = 20 * math.log10(rms_total / noise_floor)
    return max(0.0, snr_db)


def estimate_pitch_autocorr(samples, sr):
    """
    자기상관함수(Autocorrelation) 기반의 피치(F0) 추정 알고리즘 (Fallback)
    """
    if len(samples) < 256:
        return 0.0
    
    # Autocorrelation via FFT
    n = len(samples)
    f = np.fft.fft(samples, n=2*n)
    power = np.abs(f) ** 2
    autocorr = np.fft.ifft(power).real[:n]
    
    # 50Hz ~ 400Hz 음성 피치 범위 검색
    min_lag = int(sr / 400)
    max_lag = int(sr / 50)
    
    if max_lag >= len(autocorr) or min_lag >= max_lag:
        return 0.0
        
    peak_idx = min_lag + np.argmax(autocorr[min_lag:max_lag])
    if autocorr[0] == 0:
        return 0.0
        
    reliability = autocorr[peak_idx] / autocorr[0]
    if reliability > 0.2:
        return float(sr / peak_idx)
    return 0.0


def fallback_vad(samples, sr, frame_duration_ms=30, energy_threshold=0.015):
    """
    WebRTCVAD 미설치 시 작동하는 자체 RMS 에너지 기반 VAD (Voice Activity Detection)
    """
    frame_size = int(sr * (frame_duration_ms / 1000.0))
    voicing = []
    
    for i in range(0, len(samples) - frame_size, frame_size):
        frame = samples[i:i + frame_size]
        rms = compute_rms(frame)
        voicing.append(1 if rms > energy_threshold else 0)
        
    return np.array(voicing)


def analyze_audio_bytes(audio_bytes):
    """
    음성 바이너리를 분석하여 Latency, Pitch, VAD, 음향 지표를 통합 추출하는 메인 함수
    """
    try:
        samples, sr = parse_wav_bytes(audio_bytes)
    except Exception as e:
        return {"error": f"WAV 파일 파싱 실패: {str(e)}"}

    duration_sec = len(samples) / sr if sr > 0 else 0
    total_rms = compute_rms(samples)
    zcr = compute_zcr(samples)
    snr_db = compute_snr(samples)

    # 1. Voice Activity Detection (VAD) 및 Latency 계산
    voicing = fallback_vad(samples, sr)
    frame_duration_ms = 30
    frame_size_sec = frame_duration_ms / 1000.0
    
    # 첫 발화(Speech Start) 지점 감지 -> Latency 추정
    first_speech_frame = np.argmax(voicing == 1) if np.any(voicing == 1) else -1
    speech_latency_ms = (first_speech_frame * frame_size_sec * 1000) if first_speech_frame >= 0 else 0.0

    # 2. Pitch 추정
    if HAS_LIBROSA:
        try:
            f0, _, _ = librosa.pyin(samples, fmin=50, fmax=400, sr=sr)
            valid_f0 = f0[~np.isnan(f0)]
            avg_pitch = float(np.mean(valid_f0)) if len(valid_f0) > 0 else 0.0
        except:
            avg_pitch = estimate_pitch_autocorr(samples, sr)
    else:
        avg_pitch = estimate_pitch_autocorr(samples, sr)

    return {
        "duration_sec": round(duration_sec, 2),
        "total_rms": round(total_rms, 4),
        "zcr": round(zcr, 4),
        "snr_db": round(snr_db, 2),
        "latency_ms": round(speech_latency_ms, 1),
        "avg_pitch_hz": round(avg_pitch, 1),
        "sample_rate": sr,
        "num_samples": len(samples),
        "voicing_frames": voicing.tolist()
    }


# ==========================================
# 3. HTML5 JS RECORDING WEB COMPONENT
# ==========================================
def render_html5_recorder():
    """
    브라우저 표준 MediaRecorder API를 통해 마이크 음성을 녹음하고,
    Base64 변환 후 Streamlit URL Parameter로 전송하는 HTML/JS 컴포넌트
    """
    html_code = """
    <div style="border: 2px dashed #4A90E2; padding: 20px; border-radius: 12px; text-align: center; background-color: #F8FAFC;">
        <h4 style="margin-top:0; color: #1E293B;">🎙️ Web Audio Real-time Recorder</h4>
        <p style="font-size: 13px; color: #64748B;">버튼을 누르고 영어 문장을 발화하세요. (완료 시 자동 분석)</p>
        
        <button id="startBtn" onclick="startRecording()" style="padding: 10px 20px; font-weight: bold; background-color: #22C55E; color: white; border: none; border-radius: 6px; cursor: pointer; margin-right: 10px;">
            🔴 녹음 시작
        </button>
        <button id="stopBtn" onclick="stopRecording()" disabled style="padding: 10px 20px; font-weight: bold; background-color: #EF4444; color: white; border: none; border-radius: 6px; cursor: pointer;">
            ⏹️ 녹음 중지
        </button>
        
        <div id="status" style="margin-top: 12px; font-weight: bold; color: #3B82F6;">대기 중...</div>
    </div>

    <script>
        let mediaRecorder;
        let audioChunks = [];

        async function startRecording() {
            audioChunks = [];
            document.getElementById("status").innerText = "🎙️ 음성 녹음 중...";
            document.getElementById("startBtn").disabled = true;
            document.getElementById("stopBtn").disabled = false;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                
                mediaRecorder.ondataavailable = event => {
                    if (event.data.size > 0) {
                        audioChunks.push(event.data);
                    }
                };

                mediaRecorder.onstop = async () => {
                    document.getElementById("status").innerText = "⚙️ 음성 데이터 처리 및 서버 전송 중...";
                    const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                    
                    const reader = new FileReader();
                    reader.readAsDataURL(audioBlob);
                    reader.onloadend = function () {
                        const base64Audio = reader.result;
                        const encoded = encodeURIComponent(base64Audio);
                        
                        // Streamlit Query Parameter를 통해 인코딩된 바이너리 전송
                        const url = new URL(window.parent.location.href);
                        url.searchParams.set("rec_b64", encoded);
                        window.parent.location.href = url.toString();
                    };
                };

                mediaRecorder.start();
            } catch (err) {
                document.getElementById("status").innerText = "❌ 마이크 접근 권한 실패: " + err;
                document.getElementById("startBtn").disabled = false;
                document.getElementById("stopBtn").disabled = true;
            }
        }

        function stopRecording() {
            if (mediaRecorder && mediaRecorder.state !== "inactive") {
                mediaRecorder.stop();
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
            }
            document.getElementById("startBtn").disabled = false;
            document.getElementById("stopBtn").disabled = true;
        }
    </script>
    """
    st.components.v1.html(html_code, height=180)


# ==========================================
# 4. STREAMLIT UI & STATE MANAGEMENT
# ==========================================

# Session State 초기화
if "recorded_audio_bytes" not in st.session_state:
    st.session_state.recorded_audio_bytes = None
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None
if "last_error_msg" not in st.session_state:
    st.session_state.last_error_msg = None


# 🌟 [수정 핵심 반영 지점] Query Parameter 데이터 수신 및 안전한 URL Clean Up & Rerun
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
        st.session_state.last_error_msg = None
    except Exception as e:
        st.session_state.last_error_msg = f"음성 데이터 디코딩 실패: {e}"
    
    # 주소창을 즉시 깨끗하게 비우고 화면을 리프레시하여 로딩 멈춤 방지
    _set_query_params({})
    _safe_rerun()


# --- HEADER & SIDEBAR ---
st.title("🛡️ 특허 1호 MVP: 음성 Latency 분석 및 자동 역번역 비계 튜터")
st.caption("AI-Powered Voice Scaffolding & Real-time Acoustic Latency Analyzer")

st.sidebar.header("⚙️ 시스템 환경 모니터링")
st.sidebar.markdown(f"""
* **webrtcvad:** `{'✅ 사용 가능' if HAS_WEBRTCVAD else '⚠️ Fallback 모드 (RMS 사용)'}`
* **pydub:** `{'✅ 사용 가능' if HAS_PYDUB else '⚠️ 표준 wave 모듈 동작'}`
* **librosa:** `{'✅ 사용 가능' if HAS_LIBROSA else '⚠️ Fallback 모드 (Autocorr 사용)'}`
""")
st.sidebar.divider()
st.sidebar.subheader("💡 학습 가이드")
st.sidebar.info("""
1. 화면 중앙의 마이크를 통해 **영어 제안/대답**을 음성으로 녹음하세요.
2. 시스템이 **발화 반응 속도(Latency)**와 **음향 지표**를 실시간 분석합니다.
3. 역번역 비계(Scaffolding) 엔진이 **어체 및 어원 힌트**를 자동 제시합니다.
""")

# 에러 메시지 표시
if st.session_state.last_error_msg:
    st.error(st.session_state.last_error_msg)


# --- MAIN CONTENT AREA ---
col_rec, col_scaff = st.columns([1, 1])

with col_rec:
    st.subheader("1. 실시간 음성 수신 및 Latency 분석")
    render_html5_recorder()
    
    st.write("---")
    st.write("📁 **또는 테스트용 WAV 파일 직접 업로드**")
    uploaded_file = st.file_uploader("WAV 파일을 선택하세요", type=["wav"])
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        if st.button("업로드 파일 분석 실행", use_container_width=True):
            st.session_state.recorded_audio_bytes = file_bytes
            st.session_state.analysis_data = analyze_audio_bytes(file_bytes)
            _safe_rerun()

with col_scaff:
    st.subheader("2. AI 자동 역번역 비계 (Scaffolding)")
    
    target_sentence = "We need to accelerate our business strategy to expand market share."
    st.markdown(f"**🎯 목표 발화 (Target Sentence):**")
    st.blockquote(f"\"{target_sentence}\"")
    
    st.markdown("**🔍 어원 및 어휘 비계(Scaffolding) 힌트:**")
    st.markdown("""
    * **Accelerate** (v.) [어원: *ac-* (향하여) + *celer* (빠른)] → *속도를 높이다, 가속하다*
    * **Strategy** (n.) [어원: *stratos* (군대) + *agein* (이끌다)] → *전략, 계획*
    * **Expand** (v.) [어원: *ex-* (밖으로) + *pandere* (펼치다)] → *확장하다*
    """)


# --- ANALYSIS RESULT DISPLAY ---
if st.session_state.analysis_data:
    st.divider()
    st.subheader("📊 음성 실시간 분석 결과 (Patent Metrics)")
    
    res = st.session_state.analysis_data
    
    if "error" in res:
        st.error(res["error"])
    else:
        # 주요 지표 4개 메트릭 카드로 표시
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("⏱️ 음성 Latency", f"{res['latency_ms']} ms")
        m2.metric("🎵 평균 Pitch", f"{res['avg_pitch_hz']} Hz")
        m3.metric("🔊 Signal RMS", f"{res['total_rms']}")
        m4.metric("📡 SNR (신호대잡음비)", f"{res['snr_db']} dB")
        m5.metric("⏳ 전체 총 길이", f"{res['duration_sec']} 초")
        
        # 음성 오디오 재생기
        if st.session_state.recorded_audio_bytes:
            st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")
            
        # VAD 프레임 그래프 시각화
        st.markdown("##### 📈 Voice Activity Detection (VAD) 타임라인")
        voicing_data = res.get("voicing_frames", [])
        if voicing_data:
            st.line_chart(voicing_data, height=150)
            st.caption("1.0: 음성 구간 (Voice Detected) | 0.0: 묵음/배경 소음 (Silence)")
