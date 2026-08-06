import time
import streamlit as st

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
    "녹음 및 반응 지연 시간을 분석하여 자동 맞춤형 학습 비계를 제공합니다."
)
st.markdown("---")

# 2. 세션 상태(Session State) 초기화
if "prep_start_time" not in st.session_state:
    st.session_state.prep_start_time = None
if "rec_start_time" not in st.session_state:
    st.session_state.rec_start_time = None
if "is_recording" not in st.session_state:
    st.session_state.is_recording = False
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None


# ---------------------------------------------------------
# 화면 레이아웃 (좌: 지문 및 녹음 제어 / 우: 음성 분석 결과)
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
    st.subheader("⏱️ 2단계: 발화 준비 및 타이머")

    col_btn1, col_btn2 = st.columns([1, 1])

    with col_btn1:
        if st.button("▶️ 지문 읽기 시작 (타이머 시작)", use_container_width=True):
            st.session_state.prep_start_time = time.time()
            st.session_state.rec_start_time = None
            st.session_state.is_recording = False
            st.session_state.analysis_data = None
            st.rerun()

    with col_btn2:
        if st.button("🔄 준비 초기화", use_container_width=True):
            st.session_state.prep_start_time = None
            st.session_state.rec_start_time = None
            st.session_state.is_recording = False
            st.session_state.analysis_data = None
            st.rerun()

    if st.session_state.prep_start_time:
        elapsed_prep = round(time.time() - st.session_state.prep_start_time, 1)
        st.info(f"⏱️ 발화 준비 시작 후 **{elapsed_prep}초** 경과했습니다.")
    else:
        st.info("💡 **[▶️ 지문 읽기 시작]** 버튼을 눌러 준비 시간을 측정하세요.")

    st.markdown("---")
    st.subheader("🎙️ 3단계: 녹음 제어 및 데이터 분석")

    # ---------------------------------------------------------
    # 실시간 녹음 타이머 위젯 (st.fragment 적용으로 멈춤 없이 0.1초 업데이트)
    # ---------------------------------------------------------
    @st.fragment(run_every=0.1)
    def render_recording_section():
        if not st.session_state.is_recording:
            if st.button(
                "🔴 [1] 녹음 시작", use_container_width=True, type="primary"
            ):
                st.session_state.is_recording = True
                st.session_state.rec_start_time = time.time()
                st.rerun()
        else:
            current_dur = round(
                time.time() - st.session_state.rec_start_time, 1
            )
            
            # 실시간 녹음 시간 전용 UI 박스
            st.markdown(
                f"""
                <div style="background-color: #fff5f5; border: 2px solid #feb2b2; border-radius: 10px; padding: 12px; text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 13px; color: #c53030; font-weight: bold;">🎙️ 실시간 녹음 진행 중</div>
                    <div style="font-size: 28px; font-weight: bold; color: #e53e3e; font-family: monospace;">{current_dur:.1f} 초</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            col_stop1, col_stop2 = st.columns(2)

            with col_stop1:
                if st.button(
                    "⏹️ [2-A] 발화 완료 후 정지",
                    use_container_width=True,
                ):
                    end_time = time.time()
                    rec_duration = max(
                        round(end_time - st.session_state.rec_start_time, 1), 1.0
                    )

                    if st.session_state.prep_start_time:
                        latency = round(
                            st.session_state.rec_start_time
                            - st.session_state.prep_start_time,
                            1,
                        )
                    else:
                        latency = 1.8

                    st.session_state.analysis_data = {
                        "latency": latency,
                        "duration": rec_duration,
                        "pause_ratio": 12.5,
                        "has_voice": True,
                    }
                    st.session_state.is_recording = False
                    st.rerun()

            with col_stop2:
                if st.button(
                    "🔇 [2-B] 무음 상태로 정지 (말 안 함)",
                    use_container_width=True,
                ):
                    end_time = time.time()
                    rec_duration = max(
                        round(end_time - st.session_state.rec_start_time, 1), 1.0
                    )

                    if st.session_state.prep_start_time:
                        latency = round(
                            st.session_state.rec_start_time
                            - st.session_state.prep_start_time,
                            1,
                        )
                    else:
                        latency = 4.5

                    st.session_state.analysis_data = {
                        "latency": latency,
                        "duration": rec_duration,
                        "pause_ratio": 100.0,
                        "has_voice": False,
                    }
                    st.session_state.is_recording = False
                    st.rerun()

    # 타이머 위젯 호출
    render_recording_section()

    st.markdown("---")
    if st.button("🗑️ 전체 상태 리셋", use_container_width=True):
        st.session_state.prep_start_time = None
        st.session_state.rec_start_time = None
        st.session_state.is_recording = False
        st.session_state.analysis_data = None
        st.rerun()


# =========================================================
# [RIGHT COLUMN] 음성 데이터 분석 및 자동 비계 도출
# =========================================================
with col2:
    st.subheader("📊 실시간 음성 분석 및 Latency 결과")

    if st.session_state.analysis_data:
        data = st.session_state.analysis_data

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric(
                label="⏱️ 반응 지연 (Latency)", value=f"{data['latency']} 초"
            )
        with col_m2:
            st.metric(label="🎙️ 음성 총 길이", value=f"{data['duration']} 초")
        with col_m3:
            st.metric(label="⏸️ 망설임 구간 비율", value=f"{data['pause_ratio']}%")

        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        is_scaffold_needed = (
            data["latency"] > 3.0
            or data["pause_ratio"] > 25.0
            or not data["has_voice"]
        )

        if is_scaffold_needed:
            st.error(
                "🚨 **발화 지연 / 무음(망설임 100%)** 감지! 자동 역번역 및"
                " 어원 비계가 활성화되었습니다."
            )
            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ 뛰어넘는다 ➔ 게으른 개를"
            )
            st.markdown("### 2. 핵심 어원 분석")
            st.json({
                "quick": "고대 영어 cwic (살아있는, 활발한)",
                "jumps": "중세 영어 jumpen (갑자기 이동하다)",
                "lazy": "저지 독일어 lasich (느슨한, 게으른)",
            })
        else:
            st.success(
                "🎉 매우 원활한 반응속도입니다! 힌트 없이 완벽하게 수행했습니다."
            )
            st.json({
                "표현 확장 팁": (
                    "'jumps over' 대신 'clears' 또는 'leaps over' 표현을"
                    " 사용할 수 있습니다."
                )
            })
    else:
        st.info(
            "👈 좌측에서 **[🔴 1. 녹음 시작]** 후 **[정지]** 버튼을 누르시면"
            " 즉시 우측에 분석 데이터와 비계 힌트가 출력됩니다."
        )
