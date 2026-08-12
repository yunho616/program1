import base64
import io
import math
import struct
import wave
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------
# [Pure Python] 음량(RMS) 분석 함수 - supports sampwidth=1 or 2 and multi-channel
# ---------------------------------------------------------
def calculate_rms(fragment: bytes, sampwidth: int, nchannels: int) -> int:
    """
    fragment: raw PCM bytes (may contain multiple interleaved channels)
    sampwidth: bytes per sample (1 or 2)
    nchannels: number of channels (1,2,...)
    Returns RMS as int (0 if no samples)
    """
    if not fragment:
        return 0

    sample_count = len(fragment) // sampwidth
    if sample_count == 0:
        return 0

    # Unpack samples as signed 16-bit or unsigned 8-bit as WAV defines
    if sampwidth == 2:
        fmt = f"<{sample_count}h"
        try:
            samples = struct.unpack(fmt, fragment[: sample_count * sampwidth])
        except struct.error:
            return 0
    elif sampwidth == 1:
        fmt = f"<{sample_count}B"
        try:
            usamples = struct.unpack(fmt, fragment[: sample_count * sampwidth])
        except struct.error:
            return 0
        # convert unsigned 8-bit (0..255) to signed centered at 0
        samples = tuple((s - 128) for s in usamples)
    else:
        # unsupported sample width
        return 0

    # If multiple channels, compute per-frame averaged sample then RMS across frames.
    if nchannels > 1:
        frames = sample_count // nchannels
        if frames == 0:
            return 0
        sum_squares = 0.0
        for i in range(frames):
            # average across channels for this frame
            acc = 0.0
            for ch in range(nchannels):
                acc += samples[i * nchannels + ch]
            avg = acc / nchannels
            sum_squares += (avg * avg)
        mean_square = sum_squares / frames
        return int(math.sqrt(mean_square))
    else:
        # single channel
        sum_squares = sum((s * s) for s in samples)
        mean_square = sum_squares / sample_count
        return int(math.sqrt(mean_square))


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
if "recorder_key" not in st.session_state:
    st.session_state.recorder_key = 0

sample_text = (
    "The quick brown fox jumps over the lazy dog.\nThe fox is very fast."
)

target_words = [
    "The", "quick", "brown", "fox", "jumps",
    "over", "the", "lazy", "dog.", "The",
    "fox", "is", "very", "fast."
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
    "fast.": "고대 영어 fæst (단단한, 확고한, 빠른)"
}


# ---------------------------------------------------------
# 3. WAV 분석 함수
# ---------------------------------------------------------
def _ensure_wav_bytes(raw_bytes: bytes) -> bytes | None:
    """
    If raw_bytes already looks like a WAV RIFF, return it.
    Otherwise, try to convert with pydub (requires ffmpeg). If conversion fails, return None.
    """
    try:
        if raw_bytes[:4] == b"RIFF" and b"WAVE" in raw_bytes[:12]:
            return raw_bytes
    except Exception:
        pass

    # Try to convert using pydub (ffmpeg required)
    try:
        from pydub import AudioSegment  # optional dependency
        seg = AudioSegment.from_file(io.BytesIO(raw_bytes))
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue()
    except Exception:
        return None


def analyze_audio_bytes(raw_audio_bytes):
    try:
        wav_bytes = _ensure_wav_bytes(raw_audio_bytes)
        if wav_bytes is None:
            # couldn't interpret input as WAV or convert it
            return "NO_SPEECH"

        wav_file = wave.open(io.BytesIO(wav_bytes), "rb")
        nchannels = wav_file.getnchannels()
        sampwidth = wav_file.getsampwidth()
        framerate = wav_file.getframerate()
        nframes = wav_file.getnframes()

        if nframes == 0 or framerate == 0:
            wav_file.close()
            return "NO_SPEECH"

        total_duration = round(nframes / float(framerate), 1)

        frame_duration = 0.05
        frame_size = int(framerate * frame_duration)

        chunk_rms = []

        # Read frames in a loop; process partial/short final frames as well.
        wav_file.rewind()
        while True:
            raw_frames = wav_file.readframes(frame_size)
            if not raw_frames:
                break
            # how many complete samples are present
            available_frames = len(raw_frames) // (sampwidth * nchannels)
            if available_frames <= 0:
                continue
            bytes_to_use = available_frames * sampwidth * nchannels
            rms = calculate_rms(raw_frames[:bytes_to_use], sampwidth, nchannels)
            chunk_rms.append(rms)

        wav_file.close()

        if not chunk_rms:
            return "NO_SPEECH"

        max_rms = max(chunk_rms) if chunk_rms else 1
        if max_rms <= 0:
            max_rms = 1
        threshold = max(max_rms * 0.02, 5)

        # Simple VAD using RMS threshold -> collect intervals
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
            # fallback: consider a short utterance at start
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
                "latency": latency
            })

        total_words = len(word_latencies)
        smooth_words = sum(1 for w in word_latencies if w["latency"] < 1.0)
        pause_ratio = (
            round(100.0 - ((smooth_words / total_words) * 100.0), 1)
            if total_words > 0 else 0.0
        )
        max_word_latency = (
            max([w["latency"] for w in word_latencies])
            if word_latencies else 0.0
        )

        return {
            "latency": first_latency,
            "duration": total_duration,
            "pause_ratio": pause_ratio,
            "word_analysis": word_latencies,
            "max_word_latency": max_word_latency,
        }
    except Exception:
        # Keep UI-compatible return value, but swallow unexpected exceptions here.
        return "NO_SPEECH"


# ---------------------------------------------------------
# 4. UI 및 레이아웃
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# [왼쪽 칼럼]
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")
    st.text_area(
        "오늘의 학습 지문", value=sample_text, height=100, disabled=True
    )

    st.markdown("---")
    st.subheader("🎙️ 2단계: 음성 녹음")

    # URL query_params를 통한 녹음 데이터 수신 및 URL 자동 정리
    query_params = st.experimental_get_query_params()
    if "rec_b64" in query_params:
        try:
            raw_b64 = query_params["rec_b64"][0]
            # raw_b64 might be a data URL or plain base64; handle both
            if raw_b64.startswith("data:"):
                # data:[<mediatype>][;base64],<data>
                header, b64 = raw_b64.split(",", 1)
            else:
                b64 = raw_b64
            audio_bytes = base64.b64decode(b64)
            st.session_state.recorded_audio_bytes = audio_bytes
            st.session_state.analysis_data = analyze_audio_bytes(audio_bytes)
        except Exception:
            # ignore and continue (analysis_data stays None or previous)
            pass
        # clear query params (use experimental_set_query_params)
        st.experimental_set_query_params()

    # HTML/JS 커스텀 녹음 컴포넌트 (0.1초 타이머 + 시작/정지 버튼)
    # NOTE: Sending raw audio via URL is fragile for larger recordings.
    # Prefer the file_uploader fallback or a server-side POST endpoint for production.
    html_recorder = """
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; padding: 18px; border: 1px solid #cbd5e1; border-radius: 12px; background: #f8fafc; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        
        <!-- 타이머 디스플레이 (0.1초 단위) -->
        <div style="margin-bottom: 15px;">
            <span style="font-size: 13px; font-weight: 600; color: #64748b; letter-spacing: 0.5px;">REC TIME</span>
            <div id="timer" style="font-size: 32px; font-weight: 700; color: #1e293b; font-family: monospace; margin-top: 2px;">0.0s</div>
        </div>

        <!-- 버튼 영역 -->
        <div style="display: flex; gap: 10px; justify-content: center; align-items: center;">
            <button id="startBtn" style="background-color: #ef4444; color: white; border: none; padding: 12px 20px; font-size: 15px; font-weight: 700; border-radius: 8px; cursor: pointer; transition: all 0.2s; min-width: 130px;">
                🔴 녹음 시작
            </button>
            <button id="stopBtn" disabled style="background-color: #cbd5e1; color: #94a3b8; border: none; padding: 12px 20px; font-size: 15px; font-weight: 700; border-radius: 8px; cursor: not-allowed; transition: all 0.2s; min-width: 160px;">
                ⏹️ 녹음 정지 및 분석
            </button>
        </div>

        <!-- 상태 안내 메시지 -->
        <div id="status" style="margin-top: 14px; font-size: 13.5px; color: #64748b; font-weight: 500;">
            버튼을 눌러 녹음을 시작해 주세요.
        </div>
    </div>

    <script>
    let mediaRecorder;
    let audioChunks = [];
    let timerInterval = null;
    let startTime = 0;

    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const timerDisplay = document.getElementById('timer');
    const statusDisplay = document.getElementById('status');

    startBtn.onclick = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            let options = {};
            if (MediaRecorder.isTypeSupported('audio/webm')) {
                options = { mimeType: 'audio/webm' };
            }

            mediaRecorder = new MediaRecorder(stream, options);
            audioChunks = [];

            mediaRecorder.ondataavailable = event => {
                if (event.data.size > 0) audioChunks.push(event.data);
            };

            mediaRecorder.onstop = () => {
                clearInterval(timerInterval);
                statusDisplay.innerText = "⏳ 음성 데이터를 분석하는 중입니다...";
                statusDisplay.style.color = "#2563eb";

                const blobType = mediaRecorder.mimeType || 'audio/wav';
                const audioBlob = new Blob(audioChunks, { type: blobType });
                
                const reader = new FileReader();
                reader.readAsDataURL(audioBlob);
                reader.onloadend = () => {
                    // send the entire data URL (includes MIME) so server can detect type
                    const dataUrl = reader.result;
                    const parentUrl = new URL(window.parent.location.href);
                    parentUrl.searchParams.set('rec_b64', encodeURIComponent(dataUrl));
                    window.parent.location.href = parentUrl.toString();
                };
            };

            mediaRecorder.start(100);
            startTime = Date.now();

            // 0.1초(100ms) 간격 타이머 동작
            timerInterval = setInterval(() => {
                const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1);
                timerDisplay.innerText = elapsedSec + "s";
            }, 100);

            // UI 상태 변경
            startBtn.disabled = true;
            startBtn.style.backgroundColor = "#cbd5e1";
            startBtn.style.color = "#94a3b8";
            startBtn.style.cursor = "not-allowed";

            stopBtn.disabled = false;
            stopBtn.style.backgroundColor = "#2563eb";
            stopBtn.style.color = "#ffffff";
            stopBtn.style.cursor = "pointer";

            statusDisplay.innerText = "🎙️ 녹음 중입니다... 지문을 읽어주세요.";
            statusDisplay.style.color = "#dc2626";

        } catch (err) {
            statusDisplay.innerText = "❌ 마이크 권한을 허용해 주세요.";
            statusDisplay.style.color = "#dc2626";
        }
    };

    stopBtn.onclick = () => {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
            stopBtn.disabled = true;
            stopBtn.style.backgroundColor = "#cbd5e1";
            stopBtn.style.color = "#94a3b8";
            stopBtn.style.cursor = "not-allowed";
        }
    };
    </script>
    """

    components.html(html_recorder, height=200)

    with st.expander("📁 음성 파일 직접 업로드 (대체 테스트)"):
        uploaded_file = st.file_uploader(
            "WAV 음성 파일 직접 업로드",
            type=["wav", "webm", "ogg", "mp3"],
            key=f"file_uploader_{st.session_state.recorder_key}",
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
        st.session_state.recorder_key += 1
        st.experimental_set_query_params()
        st.rerun()

# [오른쪽 칼럼]
with col2:
    st.subheader("📊 실시간 음성 분석 및 Latency 결과")

    if st.session_state.recorded_audio_bytes is not None:
        st.markdown("##### 🔊 녹음된 음성 확인")
        # Note: streamlit audio playback will try its best; if we converted to WAV bytes above,
        # those bytes are playable via st.audio
        st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")
        st.markdown("---")

    if st.session_state.analysis_data == "NO_SPEECH":
        st.error(
            "⚠️ **음성 분석 실패:** 마이크 음성 신호 해석에 실패했습니다. 마이크 접근 권한 및 발화 상태를 확인해 주세요."
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
                        <div style="background-color: {bg_color}; border: 1.5px solid {border_color}; border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 10px;">
                            <div style="font-size: 17px; font-weight: bold; color: #2d3748;">{item['word']}</div>
                            <div style="font-size: 14px; font-weight: bold; color: {border_color}; margin-top: 6px;">Latency: {item['latency']}초</div>
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
