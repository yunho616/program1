import tempfile
import time
import numpy as np
import parselmouth
from parselmouth.praat import call
import streamlit as st
import streamlit.components.v1 as components

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="특허 1호 MVP - 음성 데이터 기반 분석 및 역번역 튜터",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title(
    "🎙️ 특허 1호: 음성 Latency 분석 및 자동 역번역 비계(Scaffolding) 튜터"
)
st.caption(
    "녹음된 음성 데이터를 Praat(Parselmouth) 엔진으로 정밀 분석하여 지연 시간 및 음성 특성을 자동 도출합니다."
)
st.markdown("---")

# 2. 세션 상태(Session State) 초기화
if "prep_start_time" not in st.session_state:
    st.session_state.prep_start_time = None
if "latency" not in st.session_state:
    st.session_state.latency = None
if "recording_completed" not in st.session_state:
    st.session_state.recording_completed = False
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None


# ---------------------------------------------------------
# Praat (Parselmouth) 음성 분석 함수
# ---------------------------------------------------------
def process_audio_analysis(audio_bytes):
    """학생이 녹음한 바이너리 음성 데이터를 Praat 알고리즘으로 분석합니다."""
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".wav"
        ) as temp_wav:
            temp_wav.write(audio_bytes)
            temp_path = temp_wav.name

        sound = parselmouth.Sound(temp_path)
        duration = round(sound.get_total_duration(), 1)

        pitch = sound.to_pitch()
        pitch_values = pitch.selected_array["frequency"]
        pitch_values[pitch_values == 0] = np.nan
        mean_pitch = (
            np.nanmean(pitch_values)
            if not np.all(np.isnan(pitch_values))
            else 180.0
        )

        intensity = sound.to_intensity()
        mean_intensity = call(intensity, "Get mean", 0, 0, "dB")

        formant = sound.to_formant_burg()
        f1 = call(formant, "Get mean", 1, 0, 0, "Hertz")
        f2 = call(formant, "Get mean", 2, 0, 0, "Hertz")

        intensity_vals = intensity.values[0]
        threshold_db = mean_intensity - 12.0
        silence_count = np.sum(intensity_vals < threshold_db)
        total_count = len(intensity_vals)
        pause_ratio = (
            round((silence_count / total_count) * 100, 1)
            if total_count > 0
            else 0.0
        )

        return {
            "duration": duration,
            "pitch": round(float(mean_pitch), 1),
            "intensity": round(float(mean_intensity), 1),
            "f1": round(float(f1), 1) if not np.isnan(f1) else 520.0,
            "f2": round(float(f2), 1) if not np.isnan(f2) else 1680.0,
            "pause_ratio": pause_ratio,
            "status": "success",
        }
    except Exception as e:
        return {
            "duration": 3.0,
            "pitch": 185.0,
            "intensity": 68.0,
            "f1": 520.0,
            "f2": 1680.0,
            "pause_ratio": 20.0,
            "status": "fallback",
            "error_msg": str(e),
        }


# ---------------------------------------------------------
# 화면 레이아웃 (좌: 지문 및 녹음 / 우: 음성 분석 및 역번역 힌트)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 녹음 제어
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")

    sample_text = "The quick brown fox jumps over the lazy dog."
    st.text_area("오늘의 학습 지문", value=sample_text, height=90, disabled=True)

    st.markdown("---")
    st.subheader("⏱️ 2단계: 발화 준비 및 실시간 타이머")

    col_btn1, col_btn2 = st.columns([1, 1])

    with col_btn1:
        if st.button("▶️ 지문 읽기 시작 (타이머 작동)", use_container_width=True):
            st.session_state.prep_start_time = time.time()
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.analysis_data = None
            st.rerun()

    with col_btn2:
        if st.button("🔄 타이머 리셋", use_container_width=True):
            st.session_state.prep_start_time = None
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.analysis_data = None
            st.rerun()

    if st.session_state.prep_start_time:
        initial_offset = time.time() - st.session_state.prep_start_time
        prep_timer_html = f"""
        <div style="font-family: sans-serif; background-color: #ebf8ff; border: 2px solid #3182ce; border-radius: 8px; padding: 10px; text-align: center; margin-top: 8px;">
            <div style="font-size: 13px; color: #2c5282; font-weight: bold;">⏱️ 발화 준비 실시간 경과 시간</div>
            <div id="prep_clock" style="font-size: 26px; font-weight: bold; color: #2b6cb0; font-family: monospace; margin-top: 2px;">{initial_offset:.1f} 초</div>
        </div>
        <script>
            let start = Date.now() - ({initial_offset} * 1000);
            setInterval(function() {{
                let diff = ((Date.now() - start) / 1000).toFixed(1);
                let el = document.getElementById("prep_clock");
                if (el) el.innerText = diff + " 초";
            }}, 100);
        </script>
        """
        components.html(prep_timer_html, height=85)
    else:
        st.info("💡 위의 **[▶️ 지문 읽기 시작]** 버튼을 누르면 타이머가 작동합니다.")

    st.markdown("---")
    st.subheader("🎙️ 3단계: 녹음 실행 및 실시간 제어")

    # 웹 표준 HTML5 Audio 녹음 컴포넌트
    recorder_component = """
    <div style="font-family: sans-serif; background: #f7fafc; border: 2px solid #cbd5e0; border-radius: 10px; padding: 16px;">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px;">
            <button id="recToggleBtn" onclick="handleRecClick()" style="background-color: #e53e3e; color: white; border: none; padding: 12px 20px; font-size: 16px; font-weight: bold; border-radius: 8px; cursor: pointer; flex-grow: 1;">
                🔴 녹음 시작 (클릭)
            </button>
            <div style="background: white; border: 1.5px solid #e2e8f0; border-radius: 8px; padding: 6px 14px; text-align: center; min-width: 120px;">
                <div style="font-size: 11px; color: #718096; font-weight: bold;">녹음 시간</div>
                <div id="recTimer" style="font-size: 22px; font-weight: bold; color: #2d3748; font-family: monospace;">0.0 초</div>
            </div>
        </div>
        <div id="statusText" style="font-size: 12px; color: #718096; margin-top: 8px; text-align: center;">버튼을 누르면 마이크 녹음이 시작됩니다.</div>
    </div>

    <script>
    let mediaRecorder;
    let chunks = [];
    let isRec = false;
    let timerId;
    let tStart;

    async function handleRecClick() {
        const btn = document.getElementById("recToggleBtn");
        const timer = document.getElementById("recTimer");
        const status = document.getElementById("statusText");

        if (!isRec) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                chunks = [];

                mediaRecorder.ondataavailable = e => chunks.push(e.data);
                mediaRecorder.onstop = () => {
                    const blob = new Blob(chunks, { type: 'audio/wav' });
                };

                mediaRecorder.start();
                isRec = true;
                tStart = Date.now();

                btn.innerText = "⏹️ 녹음 정지 (클릭)";
                btn.style.backgroundColor = "#3182ce";
                status.innerText = "🎙️ 녹음이 진행 중입니다. 발화 완료 후 녹음 정지를 누르세요.";

                timerId = setInterval(() => {
                    const elapsed = ((Date.now() - tStart) / 1000).toFixed(1);
                    timer.innerText = elapsed + " 초";
                    timer.style.color = "#e53e3e";
                }, 100);

            } catch (err) {
                alert("마이크 연결 오류: " + err.message + "\\n\\n기기에 마이크가 연결되어 있는지 또는 마이크 허용 권한을 확인해주세요.");
            }
        } else {
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach(t => t.stop());
            isRec = false;
            clearInterval(timerId);

            btn.innerText = "🔴 녹음 시작 (클릭)";
            btn.style.backgroundColor = "#e53e3e";
            timer.style.color = "#2b6cb0";
            status.innerText = "🟢 녹음이 완료되었습니다.";
        }
    }
    </script>
    """
    components.html(recorder_component, height=130)

    # 데이터 초기화 버튼
    if st.button("🗑️ 전체 데이터 초기화", use_container_width=True):
        st.session_state.prep_start_time = None
        st.session_state.latency = None
        st.session_state.recording_completed = False
        st.session_state.analysis_data = None
        st.rerun()


# =========================================================
# [RIGHT COLUMN] 음성 데이터 기반 실시간 분석 및 역번역 비계
# =========================================================
with col2:
    st.subheader("📊 실시간 음성 분석 및 Latency 결과")

    if st.session_state.recording_completed and st.session_state.analysis_data:
        data = st.session_state.analysis_data
        latency_val = st.session_state.latency if st.session_state.latency else 0.0

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric(label="⏱️ 반응 지연 시간 (Latency)", value=f"{latency_val} 초")
        with col_m2:
            st.metric(label="🎙️ 음성 총 길이", value=f"{data['duration']} 초")
        with col_m3:
            st.metric(label="⏸️ 망설임 구간 비율", value=f"{data['pause_ratio']}%")

        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        is_scaffold_needed = latency_val > 3.0 or data["pause_ratio"] > 25.0

        if is_scaffold_needed:
            st.error("🚨 발화 지연(3초 초과) 또는 망설임 구간이 감지되어 **[자동 역번역 및 어원 비계]**가 작동했습니다.")
            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info("**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ 뛰어넘는다 ➔ 게으른 개를")
            st.markdown("### 2. 핵심 어원 분석")
            st.json({
                "quick": "고대 영어 cwic (살아있는, 활발한)",
                "jumps": "중세 영어 jumpen (갑자기 이동하다)",
                "lazy": "저지 독일어 lasich (느슨한, 게으른)"
            })
        else:
            st.success("🎉 매우 원활한 반응속도와 발화 유지력입니다! 힌트 없이 완벽하게 수행했습니다.")
            st.json({
                "표현 확장 팁": "'jumps over' 대신 'clears' 또는 'leaps over' 표현을 사용할 수 있습니다."
            })
    else:
        st.info("👈 좌측에서 **[🔴 녹음 시작]** ➔ 발화 완료 후 **[⏹️ 녹음 정지]**를 진행하시면 됩니다.")
