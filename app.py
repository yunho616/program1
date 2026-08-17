import streamlit as st
from patent1_engine import analyze_audio_with_whisper, _ensure_wav_bytes

st.title("🛡️ 특허 1호 MVP: 역번역 비계 튜터")

# (이후 기존 UI 코드에서 로직 부분만 patent1_engine.analyze_audio_with_whisper로 대체)
# 예: analysis_res = analyze_audio_with_whisper(wav_bytes, api_key=st.session_state.openai_api_key)
