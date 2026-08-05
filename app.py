import time
import pandas as pd
import streamlit as st
from audio_recorder_streamlit import audio_recorder

# 페이지 설정
st.set_page_config(
    page_title="특허 1호 MVP - 역번역 & Latency AI 튜터", layout="wide"
)

# 세션 상태 초기화 (응답 지연시간 및 비계 제어용)
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "latency" not in st.session_state:
    st.session_state.latency = 0.0
if "scaffold_active" not in st.session_state:
    st.session_state.scaffold_active = False

# 헤더 영역
st.title("🎓 특허 1호 MVP: 역번역 기반 동적 비계 AI 튜터")
st.caption("학생의 발화 지연시간(Latency)을 실시간 감지하여 최적의 역번역 비계를 제공합니다.")

# 사이드바: 학생 정보 및 제어
with st.sidebar:
    st.header("👤 학생 정보")
    student_id = st.text_input("학생 ID / 이름", value="윤호학생")
    target_subject = st.selectbox("학습 과목 선택", ["영어 (English)", "국어 (Korean)"])

    st.divider()
    st.header("⚙️ 비계(Scaffolding) 임계값")
    latency_threshold = st.slider(
        "역번역 자동 노출 지연시간 (초)", 1.0, 10.0, 3.0, 0.5
    )

# 메인 프레임: 학습 지문 및 문항 제시
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📖 [제시 지문]")
    sample_text = (
        "The **benevolent** leader decided to **magnify** the resources "
        "for the community to ensure **sustainable** growth."
    )
    st.info(sample_text)

    st.write("**❓ 질문:** 위 문장에서 리더의 행동 특징을 설명해 보세요.")

    # 지문 읽기 시작 버튼 (타이머 작동)
    if st.button("⏱️ 답변 준비 완료 (타이머 시작)"):
        st.session_state.start_time = time.time()
        st.session_state.scaffold_active = False
        st.success("타이머가 시작되었습니다! 아래 마이크 버튼을 눌러 답변해 주세요.")

with col2:
    st.subheader("💡 역번역(Reverse-Translation) 비계")

    # 수동 비계 버튼 혹은 Latency 초과 시 자동 노출 영역
    if st.session_state.scaffold_active:
        st.warning("⚠️ **[자동 활성화된 역번역 어원 비계]**")
        st.markdown(
            """
        - **benevolent**: *bene* (좋은, Good) + *volent* (의지, Wish) ➔ **선량한/자비로운**
        - **magnify**: *magni* (큰, Great) + *fy* (만들다, Make) ➔ **확대하다**
        - **sustainable**: *sub* (아래에서) + *tenere* (유지하다) ➔ **지속 가능한**
        """
        )
    else:
        st.write("발화 지연시간이 길어지면 어원 기반 역번역 힌트가 자동으로 노출됩니다.")
        if st.button("👁️ 힌트 수동 보기"):
            st.session_state.scaffold_active = True
            st.rerun()

st.divider()

# 음성 녹음 및 분석 영역
st.subheader("🎙️ 실시간 음성 답변 및 지연시간(Latency) 측정")

st.write("아래 마이크 아이콘을 누르고 답변을 말씀하신 뒤, 한번 더 눌러 녹음을 종료하세요.")
audio_bytes = audio_recorder(
    text="마이크 버튼을 클릭하세요",
    recording_color="#e8b62c",
    neutral_color="#6aa36f",
    icon_name="microphone",
    icon_size="2x",
)

if audio_bytes:
    # 녹음이 완료된 시점에 Latency 계산
    if st.session_state.start_time is not None:
        end_time = time.time()
        st.session_state.latency = round(
            end_time - st.session_state.start_time, 2
        )
    else:
        st.session_state.latency = 0.0

    st.audio(audio_bytes, format="audio/wav")
    st.success(f"✅ 음성 수신 완료! 측정된 응답 지연시간(Latency): **{st.session_state.latency}초**")

    # 임계값 초과 여부 판단 및 자동 비계 개입
    if st.session_state.latency >= latency_threshold:
        st.session_state.scaffold_active = True
        st.error(
            f"응답 지연시간({st.session_state.latency}초)이 임계값({latency_threshold}초)을 초과하여 역번역 비계를 자동으로 제공합니다."
        )

    # 저장 데이터 시각화
    log_data = {
        "학생ID": [student_id],
        "과목": [target_subject],
        "Latency(초)": [st.session_state.latency],
        "비계제공여부": [st.session_state.scaffold_active],
        "기록시각": [time.strftime("%Y-%m-%d %H:%M:%S")],
    }
    df = pd.DataFrame(log_data)
    st.subheader("📊 시뮬레이션 수집 데이터 (DB 저장용)")
    st.dataframe(df)
