import io
import os
import tempfile
import librosa
import numpy as np
import streamlit as st
from audio_recorder_streamlit import audio_recorder

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="특허 1호 MVP - 로컬 음성 데이터 기반 분석 및 역번역 튜터",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title(
    "🎙️ 특허 1호: 음성 Latency 분석 및 자동 역번역 비계(Scaffolding) 튜터"
)
st.caption(
    "💡 **API Key 없음 (100% 무료 로컬 처리)**: librosa 음성 신호 분석 알고리즘 기반으로 무음 및 Latency를 감지합니다."
)
st.markdown("---")

# 세션 상태 초기화
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None

# 학습 지문
sample_text = (
    "The quick brown fox jumps over the lazy dog.\n"
    "The fox is very fast."
)

# 학습 지문 단어 리스트
target_words = [
    "The", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog.",
    "The", "fox", "is", "very", "fast."
]

# 어원 DB
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
    "fast.": "고대 영어 fæst (단단한, 확고한, 빠른)",
}


# ---------------------------------------------------------
# [무료 로컬 분석] Librosa 기반 음성 파형 & 무음/Latency 계산
# ---------------------------------------------------------
def analyze_audio_local(audio_bytes):
    """
    OpenAI API 없이 librosa를 이용해 무음 구간(Silence Interval)과 
    음성 구간(Non-silent Intervals)을 감지하여 단어별 Latency를 추정합니다.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_path = tmp_file.name

    try:
        # 1. 음성 로드 (Sampling Rate: 22050Hz)
        y, sr = librosa.load(tmp_path, sr=None)
        total_duration = round(float(librosa.get_duration(y=y, sr=sr)), 1)

        # 2. 음성 구간 감지 (top_db=25: 25dB 이하 소리를 무음/쉬어감으로 판단)
        intervals = librosa.effects.split(y, top_db=25)

        if len(intervals) == 0:
            return None

        # 첫 번째 발화 지연 (첫 음성 구간 시작 시점)
        first_latency = round(float(intervals[0][0] / sr), 2)

        word_latencies = []
        prev_end = 0.0

        # 지문 단어 수와 음성 발화 구간 매핑
        for idx, word_str in enumerate(target_words):
            if idx < len(intervals):
                start_sec = round(float(intervals[idx][0] / sr), 2)
                end_sec = round(float(intervals[idx][1] / sr), 2)
            else:
                # 발화 구간이 단어 수보다 부족할 경우 추정값 보정
                start_sec = round(prev_end + 0.5, 2)
                end_sec = round(start_sec + 0.4, 2)

            # 지연시간(Latency) = 이전 단어 종료 ~ 현재 단어 시작 구간
            if idx == 0:
                latency = first_latency
            else:
                latency = round(max(0.1, start_sec - prev_end), 2)

            prev_end = end_sec

            word_latencies.append({
                "word": word_str,
                "start": start_sec,
                "end": end_sec,
                "latency": latency
            })

        total_words = len(word_latencies)
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
# 화면 레이아웃 (좌: 지문 및 마이크 / 우: 음성 분석 결과)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 실제 음성 녹음
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")
    st.text_area("오늘의 학습 지문", value=sample_text, height=100, disabled=True)

    st.markdown("---")
    st.subheader("🎙️ 2단계: 무료 로컬 마이크 녹음")
    st.write("아이콘을 눌러 지문을 읽은 후 정지해 보세요.")

    # 마이크 녹음 위젯
    audio_bytes = audio_recorder(
        text="녹음 시작/정지 클릭",
        recording_color="#e84c3d",
        neutral_color="#6aa84f",
        icon_name="microphone",
        icon_size="2x",
    )

    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")

        if st.button("⚡ 로컬 음성 신호 Latency 분석 실행", type="primary", use_container_width=True):
            with st.spinner("🎧 음성 파형(Signal/Silence) 분석 중..."):
                try:
                    res = analyze_audio_local(audio_bytes)
                    if res:
                        st.session_state.analysis_data = res
                        st.success("무료 로컬 음성 데이터 분석 완료!")
                    else:
                        st.warning("음성 데이터가 너무 짧거나 감지되지 않았습니다. 다시 녹음해 주세요.")
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
        # 로컬 추출 단어별 Latency Grid 분석
        # ---------------------------------------------------------
        st.markdown("---")
        st.subheader("📖 단어별 Latency 분석 (로컬 음성 파형 처리)")

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
                            <div style="font-size: 12px; color: #718096; margin-top: 4px;">구간: <b>{item['start']}s ~ {item['end']}s</b></div>
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
                    f"🚨 **지연 감지 단어({delayed_word_names} - 2.0초 이상)**가 발생하여 어원 및 역번역 비계를 제공합니다."
                )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ **[지연 구간] 뛰어넘는다 (jumps)** ➔ 게으른 개를. "
                "그 여우는 매우 **[지연 구간] 빠릅니다 (fast)**."
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
                "🎉 발화 끊김이 적고 자연스럽게 읽으셨습니다! 비계 힌트가 필요하지 않습니다."
            )
    else:
        st.info(
            "👈 좌측 마이크로 지문을 읽으신 후 **[로컬 음성 신호 Latency 분석 실행]**을 누르면 즉시 분석됩니다."
        )
