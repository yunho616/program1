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
if "rec_start_time" not in st.session_state:
    st.session_state.rec_start_time = None
if "is_recording" not in st.session_state:
    st.session_state.is_recording = False
if "final_rec_duration" not in st.session_state:
    st.session_state.final_rec_duration = None
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None

sample_text = "The quick brown fox jumps over the lazy dog."

# ---------------------------------------------------------
# 화면 레이아웃 (좌: 지문 및 녹음 제어 / 우: 음성 분석 결과)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 녹음 제어
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")

    st.text_area("오늘의 학습 지문", value=sample_text, height=90, disabled=True)

    st.markdown("---")
    st.subheader("🎙️ 2단계: 녹음 제어 및 데이터 분석")

    # ---------------------------------------------------------
    # 실시간 녹음 타이머 위젯 (st.fragment 적용으로 0.1초 업데이트)
    # ---------------------------------------------------------
    @st.fragment(run_every=0.1)
    def render_recording_section():
        if not st.session_state.is_recording:
            # 녹음 완료 후 최종 타이머 표시 유지
            if st.session_state.final_rec_duration is not None:
                st.markdown(
                    f"""
                    <div style="background-color: #f0fff4; border: 2px solid #68d391; border-radius: 10px; padding: 12px; text-align: center; margin-bottom: 12px;">
                        <div style="font-size: 13px; color: #276749; font-weight: bold;">🟢 녹음 완료 (총 녹음 시간)</div>
                        <div style="font-size: 28px; font-weight: bold; color: #2f855a; font-family: monospace;">{st.session_state.final_rec_duration:.1f} 초</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if st.button(
                "🔴 녹음 시작", use_container_width=True, type="primary"
            ):
                st.session_state.is_recording = True
                st.session_state.rec_start_time = time.time()
                st.session_state.final_rec_duration = None
                st.rerun()
        else:
            # 녹음 진행 중 상태
            current_dur = round(
                time.time() - st.session_state.rec_start_time, 1
            )

            st.markdown(
                f"""
                <div style="background-color: #fff5f5; border: 2px solid #feb2b2; border-radius: 10px; padding: 12px; text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 13px; color: #c53030; font-weight: bold;">🎙️ 실시간 녹음 진행 중</div>
                    <div style="font-size: 28px; font-weight: bold; color: #e53e3e; font-family: monospace;">{current_dur:.1f} 초</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button(
                "⏹️ 녹음 정지 및 분석 실행",
                use_container_width=True,
            ):
                end_time = time.time()
                rec_duration = max(
                    round(end_time - st.session_state.rec_start_time, 1), 1.0
                )

                # 단어별 타임스탬프 및 Latency 데이터 생성
                word_latencies = [
                    {"word": "The", "start": 0.2, "latency": 0.2, "status": "Good"},
                    {"word": "quick", "start": 0.6, "latency": 0.4, "status": "Good"},
                    {"word": "brown", "start": 1.1, "latency": 0.5, "status": "Good"},
                    {"word": "fox", "start": 1.8, "latency": 0.7, "status": "Warning"},
                    {"word": "jumps", "start": 3.4, "latency": 1.6, "status": "Delay"},  # 망설임 구간 발생
                    {"word": "over", "start": 4.1, "latency": 0.7, "status": "Good"},
                    {"word": "the", "start": 4.6, "latency": 0.5, "status": "Good"},
                    {"word": "lazy", "start": 5.2, "latency": 0.6, "status": "Good"},
                    {"word": "dog.", "start": 5.9, "latency": 0.7, "status": "Good"},
                ]

                max_word_latency = max([w["latency"] for w in word_latencies])

                st.session_state.final_rec_duration = rec_duration
                st.session_state.analysis_data = {
                    "latency": 0.2,  # 첫 단어 발화 지연 시간
                    "duration": rec_duration,
                    "pause_ratio": 18.5,
                    "word_analysis": word_latencies,
                    "max_word_latency": max_word_latency,
                }
                st.session_state.is_recording = False
                st.rerun()

    # 타이머 위젯 실행
    render_recording_section()

    st.markdown("---")
    if st.button("🗑️ 전체 상태 리셋", use_container_width=True):
        st.session_state.rec_start_time = None
        st.session_state.is_recording = False
        st.session_state.final_rec_duration = None
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
                label="⏱️ 첫 발화 지연 (Latency)", value=f"{data['latency']} 초"
            )
        with col_m2:
            st.metric(label="🎙️ 음성 총 길이", value=f"{data['duration']} 초")
        with col_m3:
            st.metric(label="⏸️ 망설임 구간 비율", value=f"{data['pause_ratio']}%")

        # ---------------------------------------------------------
        # 단어별 Latency 분석 (점수 표시 제외)
        # ---------------------------------------------------------
        st.markdown("---")
        st.subheader("📖 분석 대상 지문 (단어별 Latency 분석)")
        
        words_data = data.get("word_analysis", [])
        
        # 단어별 Latency 시각화 Grid
        cols_per_row = 3
        for i in range(0, len(words_data), cols_per_row):
            row_words = words_data[i : i + cols_per_row]
            row_cols = st.columns(cols_per_row)
            for idx, item in enumerate(row_words):
                with row_cols[idx]:
                    # 지연 시간에 따른 상태 색상 부여
                    if item["latency"] >= 1.2:
                        bg_color = "#fff5f5"
                        border_color = "#e53e3e"
                        tag = "🚨 지연 감지"
                    elif item["latency"] >= 0.6:
                        bg_color = "#fffaf0"
                        border_color = "#dd6b20"
                        tag = "⚠️ 약간 망설임"
                    else:
                        bg_color = "#f0fff4"
                        border_color = "#38a169"
                        tag = "✅ 원활"

                    st.markdown(
                        f"""
                        <div style="background-color: {bg_color}; border: 1.5px solid {border_color}; border-radius: 8px; padding: 10px; text-align: center; margin-bottom: 8px;">
                            <div style="font-size: 16px; font-weight: bold; color: #2d3748;">{item['word']}</div>
                            <div style="font-size: 12px; color: #718096; margin-top: 4px;">시작 시점: <b>{item['start']}초</b></div>
                            <div style="font-size: 13px; font-weight: bold; color: {border_color}; margin-top: 2px;">Latency: {item['latency']}초</div>
                            <div style="font-size: 11px; margin-top: 4px; font-weight: 500;">{tag}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        is_scaffold_needed = (
            data["max_word_latency"] >= 1.2 or data["pause_ratio"] > 25.0
        )

        if is_scaffold_needed:
            st.error(
                "🚨 **특정 단어(jumps) 발화지연(1.2초 이상)** 감지! 자동 역번역 및 어원 비계가 활성화되었습니다."
            )
            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ **[지연 구간] 뛰어넘는다 (jumps)** ➔ 게으른 개를"
            )
            st.markdown("### 2. 지연 단어 어원 심층 분석")
            st.json({
                "jumps [지연 발생]": "중세 영어 jumpen (갑자기 이동하다, 뛰어오르다)",
                "quick": "고대 영어 cwic (살아있는, 활발한)",
                "lazy": "저지 독일어 lasich (느슨한, 게으른)",
            })
        else:
            st.success(
                "🎉 모든 단어의 발화 반응속도가 원활합니다! 힌트 없이 완벽하게 수행했습니다."
            )
            st.json({
                "표현 확장 팁": (
                    "'jumps over' 대신 'clears' 또는 'leaps over' 표현을"
                    " 사용할 수 있습니다."
                )
            })
    else:
        st.info(
            "👈 좌측에서 **[🔴 녹음 시작]** 후 **[⏹️ 녹음 정지 및 분석 실행]**을"
            " 누르시면 즉시 단어별 Latency 분석 데이터와 비계 힌트가 출력됩니다."
        )
