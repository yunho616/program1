import io
import wave
import struct
import shutil
import subprocess
import numpy as np
import math
from io import BytesIO
from typing import List, Tuple, Dict, Optional

# Optional libs detection
try: from pydub import AudioSegment
except: AudioSegment = None
try: import imageio_ffmpeg as _iioffmpeg
except: _iioffmpeg = None
try: import librosa
except: librosa = None

def _ensure_wav_bytes(raw_bytes: bytes) -> Optional[bytes]:
    if raw_bytes[:4] == b"RIFF" and b"WAVE" in raw_bytes[:12]:
        return raw_bytes
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        try:
            proc = subprocess.run(
                [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "wav", "pipe:1"],
                input=raw_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            return proc.stdout
        except: pass
    return None

def parse_wav_bytes(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        n_channels, sampwidth, framerate, n_frames = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
        raw_frames = wf.readframes(n_frames)
    if n_frames == 0: return np.array([], dtype=np.float32), framerate
    samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1: samples = samples.reshape(-1, n_channels).mean(axis=1)
    return samples, framerate

def compute_rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples ** 2) + 1e-12)) if samples.size > 0 else 0.0

def compute_zcr(samples: np.ndarray) -> float:
    return float(np.sum(np.abs(np.diff(np.sign(samples)))) / 2.0 / max(1, samples.size - 1)) if samples.size > 1 else 0.0

def compute_snr(samples: np.ndarray) -> float:
    rms = compute_rms(samples)
    if rms < 1e-6: return 0.0
    se = np.sort(np.abs(samples))
    bottom = np.mean(se[: max(1, int(len(se) * 0.1))]) or 1e-6
    return float(max(0.0, 20.0 * math.log10(rms / bottom)))

def analyze_audio_with_whisper(wav_bytes: bytes, api_key: str) -> Dict:
    import openai
    samples, sr = parse_wav_bytes(wav_bytes)
    client = openai.OpenAI(api_key=api_key)
    audio_file = BytesIO(wav_bytes)
    audio_file.name = "audio.wav"
    transcript_obj = client.audio.transcriptions.create(
        model="whisper-1", file=audio_file, response_format="verbose_json", timestamp_granularities=["word"]
    )
    
    words_info = getattr(transcript_obj, "words", [])
    word_latencies = []
    for i, w in enumerate(words_info):
        gap = round(w.get("start", 0.0) - (words_info[i-1].get("end", 0.0) if i > 0 else 0.0), 1)
        word_latencies.append((w.get("word", "").strip(), max(0.0, gap)))
        
    return {
        "transcript": getattr(transcript_obj, "text", ""),
        "word_latencies": word_latencies,
        "snr_db": compute_snr(samples)
    }
