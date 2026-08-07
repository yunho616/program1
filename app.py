import wave
import numpy as np

def analyze_latency_rms(wav_bytes, threshold_db=-30.0, frame_duration_ms=20, trigger_time=0.0):
    """
    WAV 바이너리 데이터를 받아 RMS 기반으로 발화 시작 지연시간을 분석합니다.
    
    :param wav_bytes: WAV 파일 바이너리 데이터
    :param threshold_db: 음성 시작으로 판단할 RMS 임계값 (dBFS 기준)
    :param frame_duration_ms: RMS를 측정할 프레임 단위 (ms)
    :param trigger_time: 음성 입력이 개시되어야 하는 기준 시점 (초)
    :return: dict (지연시간, 발화 시작 시점, RMS 프로파일)
    """
    import io
    
    # 1. WAV 바이너리 로드
    with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        pcm_data = wf.readframes(n_frames)

    # 2. PCM 데이터를 numpy 배열로 변환 (16-bit PCM 기준)
    if sampwidth == 2:
        audio_data = np.frombuffer(pcm_data, dtype=np.int16)
    else:
        raise ValueError("현재 예제는 16-bit PCM format 전용입니다.")

    # 다채널인 경우 모노(Mono)로 변환
    if n_channels > 1:
        audio_data = audio_data.reshape(-1, n_channels).mean(axis=1)

    # 정규화 (-1.0 ~ 1.0)
    max_val = np.iinfo(np.int16).max
    normalized_audio = audio_data / max_val

    # 3. 프레임별 RMS 및 dBFS 계산
    frame_size = int(sample_rate * (frame_duration_ms / 1000.0))
    total_frames = len(normalized_audio) // frame_size

    rms_list = []
    onset_time = None

    for i in range(total_frames):
        frame = normalized_audio[i * frame_size : (i + 1) * frame_size]
        
        # RMS 계산
        rms = np.sqrt(np.mean(frame ** 2)) + 1e-12  # log(0) 방지용 epsilon
        
        # dBFS 변환 (Full Scale 기준 dB)
        dbfs = 20 * np.log10(rms)
        
        current_time = (i * frame_size) / sample_rate
        rms_list.append((current_time, dbfs))

        # 4. 임계값을 초과하는 첫 구간 탐지 (Onset Detection)
        if onset_time is None and dbfs > threshold_db:
            onset_time = current_time

    # 5. 지연시간(Latency) 계산
    if onset_time is not None:
        latency = onset_time - trigger_time
    else:
        latency = None  # 임계값을 넘는 음성을 찾지 못함

    return {
        "onset_time_sec": onset_time,
        "latency_sec": latency,
        "sample_rate": sample_rate,
        "total_duration_sec": len(normalized_audio) / sample_rate,
        "rms_profile": rms_list
    }

# --- 사용 예시 ---
# with open("user_speech.wav", "rb") as f:
#     wav_data = f.read()
# 
# result = analyze_latency_rms(wav_data, threshold_db=-25.0, trigger_time=0.0)
# print(f"발화 시작 시간: {result['onset_time_sec']:.3f}초")
# print(f"측정된 지연시간: {result['latency_sec']:.3f}초")
