import streamlit as st
import time

# 1. 웹 페이지 기본 설정
st.set_page_config(page_title="인지부하 제어 튜터링 시스템", layout="centered")

st.title("🧠 특허 1호 기반 인지부하 제어 튜터링 시스템")
st.caption("역번역 비계 & 음성 반응 분석 엔진 (MVP 프로토타입)")

# 2. 사이드바 - 학생 정보 입력
st.sidebar.header("학생 정보")
student_name = st.sidebar.text_input("학생 이름을 입력하세요", value="홍길동")

# 3. 학습 지문 세션 (영어/국어 예시)
st.subheader("📖 [지문] 인지과학 및 형태소 구조")
text_content = """
Entropy is a measure of disorder or randomness in a system.
(엔트로피는 시스템 내부의 무질서도나 불확실성을 나타내는 척도이다.)
"""
st.info(text_content)

# 4. 특허 1호 핵심: 가변적 역번역 비계 (Scaffolding)
st.markdown("### 🔍 특허 1호 역번역(한자-라틴 어원) 비계")

# 비계 토글 버튼
if "show_scaffold" not in st.session_state:
    st.session_state.show_scaffold = False

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("💡 역번역 힌트 보기 (인지 부하 완화)"):
        st.session_state.show_scaffold = True

with col2:
    if st.button("❌ 힌트 닫기"):
        st.session_state.show_scaffold = False

# 비계 텍스트 출력 영역
if st.session_state.show_scaffold:
    st.success("""
    **[역번역 융합 비계 - 한자어 & 라틴어 어원 매핑]**
    * **Entropy (엔트로피):** Greek *en-* (안에) + *trope* (변화/돌림) ➔ '내부적 변화의 정도'
    * **Disorder (무질서):** Latin *dis-* (분리/부정) + *ordo* (질서) ➔ '질서가 흐트러짐'
    """)

# 5. 음성 답변 및 지연시간(Latency) 측정 시뮬레이션
st.markdown("---")
st.markdown("### 🎙️ 음성 답변 및 인지 지연 분석")

st.write("질문: '엔트로피(Entropy)'의 어원적 의미를 바탕으로 시스템의 무질서도를 설명해 보세요.")

# 음성 제출 버튼 (추후 마이크 녹음 라이브러리로 대체)
if st.button("🎙️ 음성 녹음 시작 / 제출 (테스트)"):
    start_time = time.time()
    
    with st.spinner("학생의 음성 분석 및 Latency(지연시간) 측정 중..."):
        time.sleep(2)  # 분석 대기 시뮬레이션
        end_time = time.time()
        
        # 임시 지연시간 계산
        latency = 3.2  # 초단위 (테스트용)
        
        st.write(f"⏱️ **응답 지연 시간(Latency):** `{latency}초`")
        
        # Latency가 기준치(3초) 초과 시 자동 우회 보정 노출
        if latency >= 3.0:
            st.warning("⚠️ 인지 부하 감지! (지연 시간 3초 초과) ➔ 역번역 보정 힌트를 자동 활성화합니다.")
            st.session_state.show_scaffold = True
        else:
            st.success("✅ 원활한 인지 인출 상태입니다.")