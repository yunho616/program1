import io
import time
import wave
import pandas as pd
import streamlit as st
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
    st.subheader("⏱️ 2단계: 발화 준비 및 타이머")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("▶️ 지문 읽기 시작 (타이머 작동)", use_container_width=True):
            st.session_state.prep_start_time = time.time()
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.recording_duration = 0.0
            st.success(
                "타이머 시작! 지문을 파악한 후 아래 [녹음 시작] 버튼을 누르세요."
            )

    with col_btn2:
        if st.button("🔄 타이머 리셋", use_container_width=True):
            st.session_state.prep_start_time = None
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.recording_duration = 0.0
            st.rerun()

    # 준비 시작 시간 표시
    if st.session_state.prep_start_time:
        elapsed_prep = round(time.time() - st.session_state.prep_start_time, 1)
        st.info(f"⏳ 준비 시작 후 경과 시간: **{elapsed_prep}초**")

    st.markdown("---")
    st.subheader("🎙️ 3단계: 녹음 및 데이터 제어")

    col_rec1, col_rec2 = st.columns([2, 1])
    with col_rec1:
        st.write("아래 버튼을 눌러 **녹음 시작** 및 **녹음 정지**를 진행하세요.")
    with col_rec2:
        # 데이터 초기화 버튼 (기존 녹음 데이터 및 수치 리셋)
        if st.button("🗑️ 데이터 초기화", use_container_width=True):
            st.session_state.prep_start_time = None
            st.session_state.latency = None
            st.session_state.recording_completed = False
            st.session_state.recording_duration = 0.0
            st.session_state.reset_trigger += 1  # 녹음 위젯 상태 초기화 키
            st.rerun()

    # [녹음 버튼]과 [녹음 시간 표시 칸]을 나란히 배치
    col_mic, col_dur = st.columns([1, 1])

    with col_mic:
        audio = mic_recorder(
            start_prompt="▶️ 녹음 시작",
            stop_prompt="⏹️ 녹음 정지",
            key=f"recorder_{st.session_state.reset_trigger}",
        )

    with col_dur:
        # 실제 녹음된 시간을 보여주는 메트릭 칸
        dur_val = (
            f"{st.session_state.recording_duration} 초"
            if st.session_state.recording_completed
            else "0.0 초"
        )
        st.metric(label="⏱️ 실제 녹음 시간", value=dur_val)

    # 녹음 완료 후 음성 데이터 수신 처리
    if audio:
        audio_bytes = audio["bytes"]

        if not st.session_state.recording_completed:
            st.session_state.recording_completed = True

            # 1. 실제 녹음 음성 길이(초) 계산
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)
                    st.session_state.recording_duration = round(duration, 1)
            except Exception:
                st.session_state.recording_duration = 0.0

            # 2. Latency 계산 (지문 읽기 시작 후 녹음 정지까지 걸린 시간)
            if st.session_state.prep_start_time:
                st.session_state.latency = round(
                    time.time() - st.session_state.prep_start_time, 2
                )
            else:
                st.session_state.latency = (
                    3.4  # 타이머 미작동 시 테스트 기본값
                )

            st.rerun()

        st.success("🟢 **녹음이 성공적으로 완료되었습니다.**")
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

        # 지연시간(Latency) 지표 메트릭 표시
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

        # Latency에 따른 맞춤형 힌트 분기
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
