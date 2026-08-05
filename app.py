import io
import time
import wave
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_mic_recorder import mic_recorder

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="특허 1호 MVP - 음성 분석 및 역번역 튜터",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title(
    "🎙️ 특허 1호: 음성 Latency 분석 및 자동 역번역 비계(Scaffolding) 튜터"
)
st.caption(
    "학생의 발화 지연 시간(Latency)을 실시간 분석하여 맞춤형 역번역 힌트를 제공합니다."
)
st.markdown("---")

# 2. 세션 상태(Session State) 초기화
if "prep_start_time" not in st.session_state:
    st.session_state.prep_start_time = None
if "latency" not in st.session_state:
    st.session_state.latency = None
if "recording_completed" not in st.session_state:
    st.session_state.recording_completed = False
if "recording_duration" not in st.session_state:
    st.session_state.recording_duration = 0.0
if "reset_trigger" not in st.session_state:
    st.session_state.reset_trigger = 0

# ---------------------------------------------------------
# 화면 레이아웃 (좌: 발화 및 녹음 / 우: 음성 분석 및 역번역 힌트)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 발화 제어
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")

    # 학습 지문 박스
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
            st.session_state.recording_duration = 0.0
            st.rerun()

    with col_btn2:
        if st.button("🔄 타이머 리셋", use_container_width=True):
            st.session_state.prep_start_time = None
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.recording_duration = 0.0
            st.rerun()

    # 2단계 전용 실시간 째깍째깍 스톱워치 박스
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
        st.info("💡 위의 **[▶️ 지문 읽기 시작]** 버튼을 누르면 실시간 타이머가 작동합니다.")

    st.markdown("---")
    st.subheader("🎙️ 3단계: 녹음 실행 및 데이터 제어")

    col_rec1, col_rec2 = st.columns([2, 1])
    with col_rec1:
        st.write("지문 파악이 끝나면 아래 버튼으로 녹음을 진행하세요.")
    with col_rec2:
        if st.button("🗑️ 데이터 초기화", use_container_width=True):
            st.session_state.prep_start_time = None
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.recording_duration = 0.0
            st.session_state.reset_trigger += 1
            st.rerun()

    # 녹음 버튼 및 최종 측정 시간 칸
    col_mic, col_dur = st.columns([1, 1])

    with col_mic:
        audio = mic_recorder(
            start_prompt="▶️ 녹음 시작",
            stop_prompt="⏹️ 녹음 정지",
            key=f"recorder_{st.session_state.reset_trigger}",
        )

    with col_dur:
        if st.session_state.recording_completed:
            st.metric(
                label="📊 최종 녹음된 음성 길이",
                value=f"{st.session_state.recording_duration} 초",
            )
        else:
            st.metric(
                label="📊 최종 녹음된 음성 길이",
                value="대기 중...",
                help="[녹음 정지] 후 최종 오디오 데이터의 길이가 수치로 확정됩니다.",
            )

    # 녹음 완료 후 오디오 바이너리 수신 및 시간 계산
    if audio:
        audio_bytes = audio["bytes"]

        if not st.session_state.recording_completed:
            st.session_state.recording_completed = True

            # 1. 오디오 바이너리 헤더 해석을 통한 정확한 음성 길이(초) 추출
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)
                    st.session_state.recording_duration = round(duration, 1)
            except Exception:
                st.session_state.recording_duration = 3.0

            # 2. Latency (반응 지연시간) 계산
            if st.session_state.prep_start_time:
                st.session_state.latency = round(
                    time.time() - st.session_state.prep_start_time, 2
                )
            else:
                st.session_state.latency = 3.4

            st.rerun()

        st.success("🟢 **녹음이 완료되었습니다.**")
        st.audio(audio_bytes, format="audio/wav")


# =========================================================
# [RIGHT COLUMN] Latency 분석 및 자동 역번역 비계(Scaffolding)
# =========================================================
with col2:
    st.subheader("📊 Latency 및 음성 분석 결과")

    if st.session_state.recording_completed:
        latency_val = (
            st.session_state.latency if st.session_state.latency else 0.0
        )

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.metric(
                label="⏱️ 반응 지연 시간 (Latency)", value=f"{latency_val} 초"
            )
        with col_m2:
            target_time = 3.0
            if latency_val <= target_time:
                st.success("✅ 목표 시간 내 발화 (우수)")
            else:
                st.warning("⚠️ 지연 시간 초과 (비계 필요)")

        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        if latency_val > 3.0:
            st.error(
                "🚨 발화 지연 시간이 길어져 **[어원 및 역번역 자동 비계]**가 활성화되었습니다."
            )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ 뛰어넘는다 ➔ 게으른 개를"
            )

            st.markdown("### 2. 핵심 어원 분석")
            st.json(
                {
                    "quick": "고대 영어 cwic (살아있는, 활발한)",
                    "jumps": "중세 영어 jumpen (갑자기 이동하다)",
                    "lazy": "저지 독일어 lasich (느슨한, 게으른)",
                }
            )
        else:
            st.success("🎉 빠른 반응속도입니다! 힌트 없이 완벽하게 발화했습니다.")
            st.json(
                {
                    "표현 확장 팁": (
                        "'jumps over' 대신 'clears' 또는 'leaps over' 표현을"
                        " 사용할 수 있습니다."
                    )
                }
            )

    else:
        st.info(
            "👈 좌측에서 [지문 읽기 시작] 후 [녹음 시작] -> [녹음 정지]를"
            " 완료하면, 이곳에 **Latency 분석 결과**와 **자동 역번역 비계"
            " 힌트**가 실시간으로 생성됩니다."
        )
