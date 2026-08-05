import time
import streamlit as st
import streamlit.components.v1 as components

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

# 2. 세션 상태(Session State) 초기화 및 URL 파라미터 수신
if "prep_start_time" not in st.session_state:
    st.session_state.prep_start_time = None
if "latency" not in st.session_state:
    st.session_state.latency = None
if "recording_completed" not in st.session_state:
    st.session_state.recording_completed = False
if "recording_duration" not in st.session_state:
    st.session_state.recording_duration = 0.0

# 브라우저 녹음기에서 전달된 실시간 녹음 시간 수신
query_params = st.query_params
if "rec_time" in query_params:
    try:
        rec_dur = float(query_params["rec_time"])
        if (
            not st.session_state.recording_completed
            or st.session_state.recording_duration != rec_dur
        ):
            st.session_state.recording_completed = True
            st.session_state.recording_duration = rec_dur

            # Latency (지연시간) 계산
            if st.session_state.prep_start_time:
                st.session_state.latency = round(
                    time.time() - st.session_state.prep_start_time, 2
                )
            else:
                st.session_state.latency = round(rec_dur + 1.2, 2)
    except Exception:
        pass

# ---------------------------------------------------------
# 화면 레이아웃 (좌: 발화 및 녹음 / 우: 음성 분석 및 역번역 힌트)
# ---------------------------------------------------------
col1, col2 = st.columns([1, 1])

# =========================================================
# [LEFT COLUMN] 지문 제시 및 발화 제어
# =========================================================
with col1:
    st.subheader("📖 1단계: 영어 지문 읽기 및 준비")

    sample_text = "The quick brown fox jumps over the lazy dog."
    st.text_area("오늘의 학습 지문", value=sample_text, height=90, disabled=True)

    st.markdown("---")
    st.subheader("⏱️ 2단계: 발화 준비 및 준비 타이머")

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
            st.query_params.clear()
            st.rerun()

    # 2단계 준비 실시간 경과 시간
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
        st.info("💡 위의 **[▶️ 지문 읽기 시작]** 버튼을 누르면 준비 타이머가 작동합니다.")

    st.markdown("---")
    st.subheader("🎙️ 3단계: 녹음 시작 및 0.1초 실시간 녹음 타이머")

    # 브라우저 기반 0.1초 실시간 녹음 타이머 + 오디오 레코더 컴포넌트
    recorder_html = """
    <div style="font-family: system-ui, -apple-system, sans-serif; background-color: #f8f9fa; border: 1.5px solid #cbd5e0; border-radius: 12px; padding: 16px; margin-bottom: 10px;">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 15px;">
            <!-- 녹음 시작 / 정지 버튼 -->
            <div>
                <button id="recBtn" onclick="toggleRecording()" style="background-color: #3182ce; color: white; border: none; padding: 12px 24px; font-size: 16px; font-weight: bold; border-radius: 8px; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; gap: 8px;">
                    <span id="btnIcon">▶️</span> <span id="btnText">녹음 시작</span>
                </button>
            </div>

            <!-- 0.1초 실시간 녹음 시간 타이머 박스 -->
            <div style="background-color: #ffffff; border: 2px solid #e2e8f0; border-radius: 8px; padding: 8px 18px; text-align: center; min-width: 150px;">
                <div style="font-size: 12px; color: #718096; font-weight: bold;">⏱️ 실시간 녹음 시간</div>
                <div id="timerDisplay" style="font-size: 26px; font-weight: 800; color: #2d3748; font-family: monospace; margin-top: 2px;">0.0 초</div>
            </div>
        </div>

        <!-- 녹음 완료 후 재생 플레이어 -->
        <div id="audioArea" style="margin-top: 14px; display: none;">
            <div style="font-size: 13px; color: #2f855a; font-weight: bold; margin-bottom: 6px;">🟢 녹음 완료 (녹음된 음성 들어보기)</div>
            <audio id="audioPlayer" controls style="width: 100%; height: 40px;"></audio>
        </div>
    </div>

    <script>
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    let startTime;
    let timerInterval;

    async function toggleRecording() {
        const btn = document.getElementById("recBtn");
        const btnIcon = document.getElementById("btnIcon");
        const btnText = document.getElementById("btnText");
        const timerDisplay = document.getElementById("timerDisplay");
        const audioArea = document.getElementById("audioArea");

        if (!isRecording) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];

                mediaRecorder.ondataavailable = event => {
                    audioChunks.push(event.data);
                };

                mediaRecorder.onstop = () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                    const audioUrl = URL.createObjectURL(audioBlob);
                    const audioPlayer = document.getElementById("audioPlayer");
                    audioPlayer.src = audioUrl;
                    audioArea.style.display = "block";

                    // 0.1초 단위 최종 녹음 시간 전달
                    const finalSecs = ((Date.now() - startTime) / 1000).toFixed(1);
                    sendToStreamlit(finalSecs);
                };

                mediaRecorder.start();
                isRecording = true;
                startTime = Date.now();

                // 0.1초 (100ms) 단위 실시간 타이머 작동
                timerInterval = setInterval(() => {
                    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                    timerDisplay.innerText = elapsed + " 초";
                    timerDisplay.style.color = "#e53e3e";
                }, 100);

                // 버튼 스타일 변경 (녹음 중)
                btn.style.backgroundColor = "#e53e3e";
                btnIcon.innerText = "⏹️";
                btnText.innerText = "녹음 정지";

            } catch (err) {
                alert("마이크 접근 권한이 필요합니다: " + err.message);
            }
        } else {
            // 녹음 정지
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
            isRecording = false;
            clearInterval(timerInterval);

            // 버튼 스타일 복구
            btn.style.backgroundColor = "#3182ce";
            btnIcon.innerText = "▶️";
            btnText.innerText = "녹음 시작";
            timerDisplay.style.color = "#2b6cb0";
        }
    }

    function sendToStreamlit(duration) {
        try {
            const url = new URL(window.parent.location.href);
            url.searchParams.set("rec_time", duration);
            window.parent.location.href = url.href;
        } catch(e) {
            console.log("Streamlit sync error:", e);
        }
    }
    </script>
    """
    components.html(recorder_html, height=155)

    # 데이터 초기화 버튼
    if st.button("🗑️ 전체 데이터 초기화", use_container_width=True):
        st.session_state.prep_start_time = None
        st.session_state.latency = None
        st.session_state.recording_completed = False
        st.session_state.recording_duration = 0.0
        st.query_params.clear()
        st.rerun()


# =========================================================
# [RIGHT COLUMN] Latency 분석 및 자동 역번역 비계(Scaffolding)
# =========================================================
with col2:
    st.subheader("📊 Latency 및 음성 분석 결과")

    if st.session_state.recording_completed:
        latency_val = (
            st.session_state.latency if st.session_state.latency else 0.0
        )
        dur_val = st.session_state.recording_duration

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.metric(label="⏱️ 실시간 녹음 총 시간", value=f"{dur_val} 초")
        with col_m2:
            st.metric(
                label="⏱️ 반응 지연 시간 (Latency)", value=f"{latency_val} 초"
            )

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
            "👈 좌측 3단계에서 **[▶️ 녹음 시작]**을 누르고 발화한 후 **[⏹️ 녹음"
            " 정지]**를 누르시면, 실시간 녹음 시간과 함께 **Latency 분석"
            " 결과** 및 **역번역 비계**가 이곳에 표시됩니다."
        )
