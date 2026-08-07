import os
import tempfile
import streamlit as st
from audio_recorder_streamlit import audio_recorder
import openai

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
    "실제 녹음된 음성 파일의 타임스탬프를 분석하여 자동 맞춤형 학습 비계를 제공합니다."
)
st.markdown("---")

# OpenAI API 키 설정 (Streamlit Secrets 또는 사이드바 입력)
with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input(
        "OpenAI API Key",
        value=os.getenv("OPENAI_API_KEY", ""),
        type="password",
        help="Whisper 음성 분석 및 타임스탬프 추출을 위해 API 키가 필요합니다."
    )
    if api_key:
        openai.api_key = api_key

# 2. 세션 상태 초기화
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None

# 학습 지문
sample_text = (
    "The quick brown fox jumps over the lazy dog.\n"
    "The fox is very fast."
)

# 어원 DB
etymology_db = {
    "the": "고대 영어 þæt (지시대명사/정관사)",
    "quick": "고대 영어 cwic (살아있는, 활발한)",
    "brown": "고대 영어 brūn (어두운 색, 갈색)",
    "fox": "고대 영어 fox (여우)",
    "jumps": "중세 영어 jumpen (갑자기 이동하다, 뛰어오르다)",
    "over": "고대 영어 ofer (위쪽에, 건너서)",
    "lazy": "저지 독일어 lasich (느슨한, 게으른)",
    "dog": "고대 영어 docga (개)",
    "is": "고대 영어 is (있다, 이다)",
    "very": "고대 프랑스어 verai (진실한, 매우)",
    "fast": "고대 영어 fæst (단단한, 확고한, 빠른)",
}

# ---------------------------------------------------------
# 실제 음성 타임스탬프 기반 Latency 연산 함수
# ---------------------------------------------------------
def analyze_audio_timestamps(audio_bytes):
    """Whisper API를 활용해 실제 발음 데이터의 단어별 타임스탬프 및 Latency를 구합니다."""
    # 임시 파일 저장
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_path = tmp_file.name

    try:
        client = openai.OpenAI(api_key=openai.api_key)
        
        # Whisper API 호출 (단어 단위 타임스탬프 세그먼트 활성화)
        with open(tmp_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )

        words_info = transcript.words
        word_latencies = []
        
        prev_end = 0.0
        first_latency = 0.0

        for idx, w in enumerate(words_info):
            word_str = w['word'].strip()
            start_t = round(w['start'], 2)
            end_t = round(w['end'], 2)
            
            # 이전 단어 끝~현재 단어 시작 사이의 간격을 Latency(지연)로 계산
            if idx == 0:
                latency = round(start_t, 2)
                first_latency = latency
            else:
                latency = round(max(0.0, start_t - prev_end), 2)

            prev_end = end_t

            word_latencies.append({
                "word": word_str,
                "start": start_t,
                "end": end_t,
                "latency": latency
            })

        total_words = len(word_latencies)
        total_duration = round(words_info[-1]['end'], 1) if words_info else 0.0
        smooth_words = sum(1 for w in word_latencies if w["latency"] < 1.0)
        pause_ratio = round(100.0 - ((smooth_words / total_words) * 100.0), 1) if total_words > 0 else 0.0
        max_word_latency = max([w["latency"] for w in word_latencies]) if word_latencies else 0.0

        return {
            "latency": first_latency,
            "duration": total_duration,
            "pause_ratio": pause_ratio,
            "word_analysis": word_latencies,
            "max_word_latency": max_word_latency,
        }

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------
# 화면 레이아웃 (좌: 지문 및 실제 녹음 / 우: 음성 분석 결과)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 실제 음성 녹음
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")
    st.text_area("오늘의 학습 지문", value=sample_text, height=100, disabled=True)

    st.markdown("---")
    st.subheader("🎙️ 2단계: 실제 마이크 음성 녹음")
    st.write("아이콘을 눌러 지문을 읽고 녹음해 보세요.")

    # 실제 마이크 입력 위젯
    audio_bytes = audio_recorder(
        text="녹음 시작/정지 버튼 클릭",
        recording_color="#e84c3d",
        neutral_color="#6aa84f",
        icon_name="microphone",
        icon_size="2x",
    )

    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")
        
        if st.button("🔍 녹음된 음성 데이터 Latency 분석 실행", type="primary", use_container_width=True):
            if not api_key:
                st.warning("⚠️ 사이드바에 OpenAI API Key를 입력해야 실제 음성 타임스탬프 분석이 가능합니다.")
            else:
                with st.spinner("🎧 음성 파형 분석 및 단어별 Latency 계산 중..."):
                    try:
                        res = analyze_audio_timestamps(audio_bytes)
                        st.session_state.analysis_data = res
                        st.success("실제 음성 데이터 분석이 완료되었습니다!")
                    except Exception as e:
                        st.error(f"분석 중 오류 발생: {e}")

    st.markdown("---")
    if st.button("🗑️ 전체 상태 리셋", use_container_width=True):
        st.session_state.analysis_data = None
        st.rerun()


# =========================================================
# [RIGHT COLUMN] 실제 음성 분석 및 Latency 결과
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
        # 실제 추출된 단어별 Latency 분석 (Grid 형태)
        # ---------------------------------------------------------
        st.markdown("---")
        st.subheader("📖 인식된 단어별 Latency 분석 (실제 음성 데이터)")
        
        words_data = data.get("word_analysis", [])
        
        cols_per_row = 3
        for i in range(0, len(words_data), cols_per_row):
            row_words = words_data[i : i + cols_per_row]
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
                        f"""
                        <div style="background-color: {bg_color}; border: 1.5px solid {border_color}; border-radius: 8px; padding: 10px; text-align: center; margin-bottom: 8px;">
                            <div style="font-size: 16px; font-weight: bold; color: #2d3748;">{item['word']}</div>
                            <div style="font-size: 12px; color: #718096; margin-top: 4px;">발화 시점: <b>{item['start']}s ~ {item['end']}s</b></div>
                            <div style="font-size: 13px; font-weight: bold; color: {border_color}; margin-top: 2px;">지연(Latency): {item['latency']}초</div>
                            <div style="font-size: 11px; margin-top: 4px; font-weight: 500;">{tag}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        # ---------------------------------------------------------
        # 자동 비계 (Scaffolding) 도출
        # ---------------------------------------------------------
        st.markdown("---")
        st.subheader("💡 자동 생성된 역번역/어원 비계 (Scaffolding)")

        is_scaffold_needed = (
            data["max_word_latency"] >= 2.0 or data["pause_ratio"] > 25.0
        )

        if is_scaffold_needed:
            delayed_words = [w for w in words_data if w["latency"] >= 2.0]

            if delayed_words:
                delayed_word_names = ", ".join([f"'{w['word']}'" for w in delayed_words])
                st.error(
                    f"🚨 **실제 지연 감지 단어({delayed_word_names} - 2.0초 이상)**가 발견되었습니다!"
                )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 지문 음성 중 반응 속도가 느렸던 구간 위주로 다시 한 번 연결 어순을 연습해보세요."
            )

            st.markdown("### 2. 지연 단어 어원 심층 분석")
            if delayed_words:
                etymology_result = {}
                for item in delayed_words:
                    word_clean = item["word"].lower().strip(".,!?")
                    info = etymology_db.get(word_clean, "어원 정보 사전 등록 중")
                    key_name = f"{item['word']} (실제 Latency: {item['latency']}초)"
                    etymology_result[key_name] = info
                
                st.json(etymology_result)
        else:
            st.success(
                "🎉 실제 발화 속도가 매우 원활합니다! 지연 구간 없이 완벽히 읽었습니다."
            )
    else:
        st.info(
            "👈 좌측에서 마이크 아이콘을 눌러 지문을 직접 읽고 **[분석 실행]**을 누르면 실제 Latency를 계산합니다."
        )
