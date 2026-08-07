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

# "the fox is very fast." 문장이 추가된 학습 지문
sample_text = (
    "The quick brown fox jumps over the lazy dog.\n"
    "The fox is very fast.\n"
    "Learning a new language requires consistent practice and immediate feedback.\n"
    "By analyzing speech latency, this tutor provides personalized scaffolding."
)

# 어원 DB
etymology_db = {
    "jumps": "중세 영어 jumpen (갑자기 이동하다, 뛰어오르다)",
    "fast.": "고대 영어 fæst (단단한, 확고한, 빠른)",
    "practice": "중세 프랑스어 pratiquer (실행하다, 연습하다)",
    "feedback.": "합성어 feed(먹이다) + back(돌려주다) -> 반응/환류",
    "scaffolding.": "고대 프랑스어 eschafaut (임시 발판, 건축용 비계)",
}

# ---------------------------------------------------------
# 화면 레이아웃 (좌: 지문 및 녹음 제어 / 우: 음성 분석 결과)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 녹음 제어
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")

    st.text_area("오늘의 학습 지문", value=sample_text, height=150, disabled=True)

    st.markdown("---")
    st.subheader("🎙️ 2단계: 녹음 제어 및 데이터 분석")

    @st.fragment(run_every=0.1)
    def render_recording_section():
        if not st.session_state.is_recording:
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

                # 단어별 타임스탬프 및 Latency 데이터 ("The fox is very fast." 구간 추가)
                word_latencies = [
                    # 1행
                    {"word": "The", "latency": 0.2},
                    {"word": "quick", "latency": 0.4},
                    {"word": "brown", "latency": 0.3},
                    {"word": "fox", "latency": 0.5},
                    {"word": "jumps", "latency": 2.3},  # 🚨 지연
                    {"word": "over", "latency": 0.4},
                    {"word": "the", "latency": 0.3},
                    {"word": "lazy", "latency": 0.5},
                    {"word": "dog.", "latency": 0.6},
                    # 2행 (신규 추가 구간)
                    {"word": "The", "latency": 0.3},
                    {"word": "fox", "latency": 0.4},
                    {"word": "is", "latency": 0.2},
                    {"word": "very", "latency": 0.5},
                    {"word": "fast.", "latency": 2.1},  # 🚨 지연
                    # 3행
                    {"word": "Learning", "latency": 0.8},
                    {"word": "a", "latency": 0.2},
                    {"word": "new", "latency": 0.3},
                    {"word": "language", "latency": 1.2},  # ⚠️ 약간 망설임
                    {"word": "requires", "latency": 0.7},
                    {"word": "consistent", "latency": 0.9},
                    {"word": "practice", "latency": 2.0},  # 🚨 지연
                    {"word": "and", "latency": 0.3},
                    {"word": "immediate", "latency": 0.8},
                    {"word": "feedback.", "latency": 0.5},
                ]

                total_words = len(word_latencies)
                smooth_words = sum(1 for w in word_latencies if w["latency"] < 1.0)
                pause_ratio = round(100.0 - ((smooth_words / total_words) * 100.0), 1) if total_words > 0 else 0.0
                max_word_latency = max([w["latency"] for w in word_latencies])

                st.session_state.final_rec_duration = rec_duration
                st.session_state.analysis_data = {
                    "latency": 0.2,
                    "duration": rec_duration,
                    "pause_ratio": pause_ratio,
                    "word_analysis": word_latencies,
                    "max_word_latency": max_word_latency,
                }
                st.session_state.is_recording = False
                st.rerun()

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
            st.metric(label="⏱️ 첫 발화 지연", value=f"{data['latency']} 초")
        with col_m2:
            st.metric(label="🎙️ 음성 총 길이", value=f"{data['duration']} 초")
        with col_m3:
            st.metric(label="⏸️ 망설임 구간 비율", value=f"{data['pause_ratio']}%")

        # ---------------------------------------------------------
        # 인라인 문장 하이라이트 뷰
        # ---------------------------------------------------------
        st.markdown("---")
        st.subheader("📖 지문 기반 Latency 인라인 분석")
        st.caption("🟢 원활(<1초) | 🟡 망설임(1~2초) | 🔴 지연 감지(≥2초)")

        words_data = data.get("word_analysis", [])

        # HTML 문장 구성
        inline_html = "<div style='line-height: 2.2; font-size: 16px; background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #e2e8f0;'>"

        for item in words_data:
            lat = item["latency"]
            word = item["word"]

            # Latency별 하이라이트 색상 정의
            if lat >= 2.0:
                bg_color = "#fed7d7"  # 빨강
                text_color = "#9b2c2c"
                border = "1px solid #e53e3e"
            elif lat >= 1.0:
                bg_color = "#feebc8"  # 주황
                text_color = "#9c4221"
                border = "1px solid #dd6b20"
            else:
                bg_color = "#c6f6d5"  # 초록
                text_color = "#22543d"
                border = "1px solid #38a169"

            inline_html += f"""
            <span title="Latency: {lat}초" style="background-color: {bg_color}; color: {text_color}; border: {border}; padding: 3px 7px; margin: 2px 3px; border-radius: 5px; display: inline-block; font-weight: 500;">
                {word} <small style="font-size: 10px; opacity: 0.8;">({lat}s)</small>
            </span>
            """

        inline_html += "</div>"
        st.markdown(inline_html, unsafe_allow_html=True)

        # ---------------------------------------------------------
        # 자동 비계 (Scaffolding) 도출
        # ---------------------------------------------------------
        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        is_scaffold_needed = (
            data["max_word_latency"] >= 2.0 or data["pause_ratio"] > 25.0
        )

        if is_scaffold_needed:
            # 2.0초 이상 지연된 단어만 추출
            delayed_words = [w for w in words_data if w["latency"] >= 2.0]

            if delayed_words:
                delayed_word_names = ", ".join([f"'{w['word']}'" for w in delayed_words])
                st.error(
                    f"🚨 **지연 발생 단어({delayed_word_names})** 감지! 자동 역번역 및 어원 비계가 활성화되었습니다."
                )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[지연 구간 힌트]** 빠른 갈색 여우가 ➔ **[지연] 뛰어넘는다 (jumps)** ➔ 게으른 개를. "
                "그 여우는 매우 **[지연] 빠릅니다 (fast)**."
            )

            st.markdown("### 2. 지연 단어 어원 심층 분석")
            if delayed_words:
                etymology_result = {}
                for item in delayed_words:
                    word_clean = item["word"]
                    info = etymology_db.get(word_clean, "어원 정보 등록 중")
                    key_name = f"{word_clean} (Latency: {item['latency']}초)"
                    etymology_result[key_name] = info

                st.json(etymology_result)
        else:
            st.success(
                "🎉 모든 단어의 발화 반응속도가 원활합니다! 힌트 없이 완벽하게 수행했습니다."
            )
    else:
        st.info(
            "👈 좌측에서 **[🔴 녹음 시작]** 후 **[⏹️ 녹음 정지 및 분석 실행]**을"
            " 누르시면 분석 데이터가 표시됩니다."
        )
