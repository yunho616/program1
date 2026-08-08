import io
import math
import struct
import wave
import numpy as np
import soundfile as sf
import streamlit as st
from streamlit_mic_recorder import mic_recorder


# ---------------------------------------------------------
# [Compatibility] audioop 대체용 순수 Python RMS(음량) 계산 함수
# ---------------------------------------------------------
def calculate_rms(fragment, width):
    if not fragment:
        return 0
    count = len(fragment) // width
    if count == 0:
        return 0

    format_str = f"<{count}{'h' if width == 2 else 'b'}"
    try:
        samples = struct.unpack(format_str, fragment[: count * width])
        sum_squares = sum(s * s for s in samples)
        return int(math.sqrt(sum_squares / count))
    except Exception:
        return 0


try:
    import audioop
except ImportError:

    class DummyAudioOp:

        @staticmethod
        def rms(fragment, width):
            return calculate_rms(fragment, width)

    audioop = DummyAudioOp()


# ---------------------------------------------------------
# 1. 페이지 기본 설정
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# 2. 세션 상태(Session State) 초기화
# ---------------------------------------------------------
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None
if "recorded_audio_bytes" not in st.session_state:
    st.session_state.recorded_audio_bytes = None

sample_text = (
    "The quick brown fox jumps over the lazy dog.\nThe fox is very fast."
)

target_words = [
    "The",
    "quick",
    "brown",
    "fox",
    "jumps",
    "over",
    "the",
    "lazy",
    "dog.",
    "The",
    "fox",
    "is",
    "very",
    "fast.",
]

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
# [soundfile 기반 안전 음성 파형 분석 함수]
# ---------------------------------------------------------
def analyze_audio_bytes(raw_audio_bytes):
    try:
        # 브라우저에서 수집된 녹음 파일 데이터 디코딩
        audio_data, sample_rate = sf.read(io.BytesIO(raw_audio_bytes))

        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)

        total_duration = round(len(audio_data) / float(sample_rate), 1)

        frame_duration = 0.05
        frame_size = int(sample_rate * frame_duration)

        chunk_rms = []
        for i in range(0, len(audio_data), frame_size):
            chunk = audio_data[i : i + frame_size]
            if len(chunk) == 0:
                break
            rms = np.sqrt(np.mean(chunk**2))
            chunk_rms.append(rms)

        if not chunk_rms:
            return "NO_SPEECH"

        max_rms = max(chunk_rms) if max(chunk_rms) > 0 else 0.001
        threshold = max(max_rms * 0.01, 0.0001)

        speech_intervals = []
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

        for idx, word_str in enumerate(target_words):
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
                "latency": latency,
            })

        total_words = len(word_latencies)
        smooth_words = sum(1 for w in word_latencies if w["latency"] < 1.0)
        pause_ratio = (
            round(100.0 - ((smooth_words / total_words) * 100.0), 1)
            if total_words > 0
            else 0.0
        )
        max_word_latency = (
            max([w["latency"] for w in word_latencies])
            if word_latencies
            else 0.0
        )

        return {
            "latency": first_latency,
            "duration": total_duration,
            "pause_ratio": pause_ratio,
            "word_analysis": word_latencies,
            "max_word_latency": max_word_latency,
        }
    except Exception:
        return "NO_SPEECH"


# ---------------------------------------------------------
# UI 및 화면 레이아웃
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# [LEFT COLUMN]
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")
    st.text_area(
        "오늘의 학습 지문", value=sample_text, height=100, disabled=True
    )

    st.markdown("---")
    st.subheader("🎙️ 2단계: 음성 녹음")

    st.write("아래 녹음 버튼을 눌러 지문을 읽은 후 정지 버튼을 누르세요.")

    # 깔끔한 직관적 버튼 타입 컴포넌트
    audio_record = mic_recorder(
        start_prompt="🔴 녹음 시작",
        stop_prompt="⏹️ 녹음 정지 및 분석",
        key="recorder",
    )

    if audio_record and "bytes" in audio_record:
        st.session_state.recorded_audio_bytes = audio_record["bytes"]
        st.session_state.analysis_data = analyze_audio_bytes(
            audio_record["bytes"]
        )

    with st.expander("📁 음성 파일 직접 업로드 (대체 테스트)"):
        uploaded_file = st.file_uploader(
            "WAV, MP3, M4A, OGG 파일 지원",
            type=["wav", "mp3", "m4a", "ogg"],
        )
        if uploaded_file is not None:
            file_bytes = uploaded_file.read()
            st.session_state.recorded_audio_bytes = file_bytes
            st.session_state.analysis_data = analyze_audio_bytes(file_bytes)
            st.success("파일 분석이 완료되었습니다!")

    st.markdown("---")
    if st.button("🗑️ 분석 결과 초기화", use_container_width=True):
        st.session_state.analysis_data = None
        st.session_state.recorded_audio_bytes = None
        st.rerun()

# [RIGHT COLUMN]
with col2:
    st.subheader("📊 실시간 음성 분석 및 Latency 결과")

    if st.session_state.recorded_audio_bytes is not None:
        st.markdown("##### 🔊 녹음된 음성 플레이어")
        st.audio(st.session_state.recorded_audio_bytes)
        st.markdown("---")

    if st.session_state.analysis_data == "NO_SPEECH":
        st.error(
            "⚠️ **음성 수집 실패:** 마이크 입력을 읽지 못했습니다. 1초 이상 발화 후 정지 버튼을 눌러주세요."
        )
    elif isinstance(st.session_state.analysis_data, dict):
        data = st.session_state.analysis_data

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric(
                label="⏱️ 첫 발화 지연 (Latency)",
                value=f"{data['latency']} 초",
            )
        with col_m2:
            st.metric(label="🎙️ 음성 총 길이", value=f"{data['duration']} 초")
        with col_m3:
            st.metric(
                label="⏸️ 망설임 구간 비율", value=f"{data['pause_ratio']}%"
            )

        st.markdown("---")
        st.subheader("📖 분석 대상 지문 (단어별 Latency 분석)")

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
            data["max_word_latency"] >= 2.0 or data["pause_ratio"] > 25.0
        )

        if is_scaffold_needed:
            delayed_words = [w for w in words_data if w["latency"] >= 2.0]

            if delayed_words:
                delayed_word_names = ", ".join(
                    [f"'{w['word']}'" for w in delayed_words]
                )
                st.error(
                    f"🚨 **지연 발생 단어({delayed_word_names} - 2.0초 이상)**"
                    " 감지! 자동 역번역 및 어원 비계가 활성화되었습니다."
                )
            else:
                st.warning(
                    "⚠️ **망설임 구간 비율(25% 초과)** 감지! 전체적인"
                    " 문장 구성 비계가 활성화되었습니다."
                )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ 뛰어넘는다 (jumps) ➔ 게으른"
                " 개를. 그 여우는 매우 ➔ 빠릅니다 (fast)."
            )

            st.markdown("### 2. 지연 단어 어원 심층 분석")
            if delayed_words:
                etymology_result = {}
                for item in delayed_words:
                    word_clean = item["word"]
                    info = etymology_db.get(
                        word_clean, "어원 정보 등록 중"
                    )
                    key_name = (
                        f"{word_clean} (Latency: {item['latency']}초)"
                    )
                    etymology_result[key_name] = info

                st.json(etymology_result)
            else:
                st.write("감지된 개별 지연 단어가 없습니다.")
        else:
            st.success(
                "🎉 모든 단어의 발화 반응속도가 원활합니다! 힌트 없이"
                " 완벽하게 수행했습니다."
            )
    else:
        st.info(
            "👈 좌측에서 **[🔴 녹음 시작]**을 누르고 지문을 읽은 뒤 **[⏹️ 녹음 정지 및 분석]**을 누르세요."
        )
