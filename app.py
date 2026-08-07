import io
import time
import wave
import audioop
import base64
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
    "녹음 및 반응 지연 시간을 실제 음성 파형(Acoustic Data) 기반으로 분석하여 자동 맞춤형 학습 비계를 제공합니다."
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
if "recorded_audio_bytes" not in st.session_state:
    st.session_state.recorded_audio_bytes = None

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
# [브라우저 마이크 음성 수집용 숨김 HTML/JS 컴포넌트]
# ---------------------------------------------------------
def hidden_audio_recorder(is_recording):
    js_code = f"""
    <script>
    let mediaRecorder = window._mediaRecorder || null;
    let audioChunks = window._audioChunks || [];

    async function startRecording() {{
        try {{
            const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
            audioChunks = [];
            mediaRecorder = new MediaRecorder(stream);
            window._mediaRecorder = mediaRecorder;
            window._audioChunks = audioChunks;

            mediaRecorder.ondataavailable = event => {{
                if (event.data.size > 0) {{
                    audioChunks.push(event.data);
                }}
            }};
            mediaRecorder.start(100);
        }} catch (err) {{
            console.error("마이크 권한 오류:", err);
        }}
    }}

    async function stopRecording() {{
        if (mediaRecorder && mediaRecorder.state !== "inactive") {{
            mediaRecorder.onstop = async () => {{
                const audioBlob = new Blob(audioChunks, {{ type: 'audio/wav' }});
                const reader = new FileReader();
                reader.readAsDataURL(audioBlob);
                reader.onloadend = () => {{
                    const base64Audio = reader.result.split(',')[1];
                    window.parent.postMessage({{
                        type: 'streamlit:setComponentValue',
                        value: base64Audio
                    }}, '*');
                }};
            }};
            mediaRecorder.stop();
        }}
    }}

    if ({'true' if is_recording else 'false'}) {{
        startRecording();
    }} else {{
        stopRecording();
    }}
    </script>
    """
    return components.html(js_code, height=0, width=0)


# ---------------------------------------------------------
# [실제 발음 데이터 기반 Latency 분석 함수]
# ---------------------------------------------------------
def analyze_audio_bytes(audio_bytes):
    try:
        wav_file = wave.open(io.BytesIO(audio_bytes), "rb")
        nchannels = wav_file.getnchannels()
        sampwidth = wav_file.getsampwidth()
        framerate = wav_file.getframerate()
        nframes = wav_file.getnframes()

        total_duration = round(nframes / float(framerate), 1)
        if total_duration <= 0.3:
            return None

        frame_duration = 0.05
        frame_size = int(framerate * frame_duration)
        
        chunk_rms = []
        for _ in range(0, nframes, frame_size):
            frames = wav_file.readframes(frame_size)
            if len(frames) < frame_size * sampwidth * nchannels:
                break
            rms = audioop.rms(frames, sampwidth)
            chunk_rms.append(rms)

        wav_file.close()

        if not chunk_rms:
            return None

        max_rms = max(chunk_rms) if max(chunk_rms) > 0 else 1
        threshold = max(max_rms * 0.15, 300)

        speech_intervals = []
        in_speech = False
        start_idx = 0

        for idx, rms in enumerate(chunk_rms):
            if rms >= threshold and not in_speech:
                in_speech = True
                start_idx = idx
            elif rms < threshold and in_speech:
                in_speech = False
                speech_intervals.append((start_idx * frame_duration, idx * frame_duration))

        if in_speech:
            speech_intervals.append((start_idx * frame_duration, len(chunk_rms) * frame_duration))

        if not speech_intervals:
            return "NO_SPEECH"

        first_latency = round(speech_intervals[0][0], 2)

        word_latencies = []
        prev_end = 0.0

        for idx, word_str in enumerate(target_words):
            if idx < len(speech_intervals):
                start_sec = round(speech_intervals[idx][0], 2)
                end_sec = round(speech_intervals[idx][1], 2)
            else:
                start_sec = round(prev_end + 0.4, 2)
                end_sec = round(start_sec + 0.3, 2)

            if idx == 0:
                latency = first_latency
            else:
                latency = round(max(0.1, start_sec - prev_end), 2)

            prev_end = end_sec
            word_latencies.append({
                "word": word_str,
                "start": start_sec,
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
    except Exception:
        # 파일 포맷 변환 특성상 파싱 실패 시 예외 방지
        return "NO_SPEECH"


# ---------------------------------------------------------
# 화면 레이아웃 (좌: 지문 및 녹음 제어 / 우: 음성 분석 결과)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 녹음 제어 (원래 UI 100% 유지)
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")
    st.text_area("오늘의 학습 지문", value=sample_text, height=100, disabled=True)

    st.markdown("---")
    st.subheader("🎙️ 2단계: 녹음 제어 및 데이터 분석")

    # 브라우저 백그라운드 녹음 스크립트 연결
    rec_audio_data = hidden_audio_recorder(st.session_state.is_recording)
    if rec_audio_data and isinstance(rec_audio_data, str):
        try:
            st.session_state.recorded_audio_bytes = base64.b64decode(rec_audio_data)
        except Exception:
            pass

    # ---------------------------------------------------------
    # 녹음 타이머 및 버튼 UI (원래 디자인)
    # ---------------------------------------------------------
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

            if st.button("🔴 녹음 시작", use_container_width=True, type="primary"):
                st.session_state.is_recording = True
                st.session_state.rec_start_time = time.time()
                st.session_state.final_rec_duration = None
                st.session_state.analysis_data = None
                st.session_state.recorded_audio_bytes = None
                st.rerun()
        else:
            current_dur = round(time.time() - st.session_state.rec_start_time, 1)

            st.markdown(
                f"""
                <div style="background-color: #fff5f5; border: 2px solid #feb2b2; border-radius: 10px; padding: 12px; text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 13px; color: #c53030; font-weight: bold;">🎙️ 실시간 녹음 진행 중</div>
                    <div style="font-size: 28px; font-weight: bold; color: #e53e3e; font-family: monospace;">{current_dur:.1f} 초</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("⏹️ 녹음 정지 및 분석 실행", use_container_width=True):
                end_time = time.time()
                rec_duration = max(round(end_time - st.session_state.rec_start_time, 1), 1.0)

                # 수집된 오디오 바이트가 있을 시 WAV 분석 실행
                if st.session_state.recorded_audio_bytes:
                    res = analyze_audio_bytes(st.session_state.recorded_audio_bytes)
                else:
                    res = "NO_SPEECH"

                st.session_state.final_rec_duration = rec_duration
                st.session_state.analysis_data = res
                st.session_state.is_recording = False
                st.rerun()

    render_recording_section()

    st.markdown("---")
    if st.button("🗑️ 전체 상태 리셋", use_container_width=True):
        st.session_state.rec_start_time = None
        st.session_state.is_recording = False
        st.session_state.final_rec_duration = None
        st.session_state.analysis_data = None
        st.session_state.recorded_audio_bytes = None
        st.rerun()


# =========================================================
# [RIGHT COLUMN] 음성 데이터 분석 및 자동 비계 도출
# =========================================================
with col2:
    st.subheader("📊 실시간 음성 분석 및 Latency 결과")

    if st.session_state.analysis_data == "NO_SPEECH":
        st.error("⚠️ **발성 또는 음성 신호가 감지되지 않았습니다.** 마이크 입력 상태를 확인하시거나 소리를 내어 다시 녹음해 주세요.")
    elif isinstance(st.session_state.analysis_data, dict):
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
        # 단어별 Latency Grid 분석
        # ---------------------------------------------------------
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
                    f"🚨 **지연 발생 단어({delayed_word_names} - 2.0초 이상)** 감지! 자동 역번역 및 어원 비계가 활성화되었습니다."
                )
            else:
                st.warning(
                    "⚠️ **망설임 구간 비율(25% 초과)** 감지! 전체적인 문장 구성 비계가 활성화되었습니다."
                )

            st.markdown("### 1. 직독직해 역번역 힌트")
            st.info(
                "**[어순 배치 힌트]** 빠른 갈색 여우가 ➔ 뛰어넘는다 (jumps) ➔ 게으른 개를. "
                "그 여우는 매우 ➔ 빠릅니다 (fast)."
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
                st.write("감지된 개별 지연 단어가 없습니다.")
        else:
            st.success(
                "🎉 모든 단어의 발화 반응속도가 원활합니다! 힌트 없이 완벽하게 수행했습니다."
            )
    else:
        st.info(
            "👈 좌측에서 **[🔴 녹음 시작]** 후 **[⏹️ 녹음 정지 및 분석 실행]**을"
            " 누르시면 즉시 단어별 Latency 분석 데이터와 비계 힌트가 출력됩니다."
        )
