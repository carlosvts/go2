"""Arquivos de áudio gerados no teste (F-007): WAV com `wave`, MP3 com PyAV."""

import io
import math
import wave

import av
import numpy as np


def tone(seconds: float, rate: int, channels: int, freq: float = 440.0) -> np.ndarray:
    """Seno em int16, forma `(amostras, canais)`, amplitude ~0,5."""
    count = round(seconds * rate)
    t = np.arange(count) / rate
    mono = (0.5 * 32767 * np.sin(2 * math.pi * freq * t)).astype(np.int16)
    return np.repeat(mono[:, None], channels, axis=1)


def make_wav(
    seconds: float = 0.2, rate: int = 44100, channels: int = 1, freq: float = 440.0
) -> bytes:
    """WAV PCM 16 bits; por padrão mono 44,1 kHz, para exercitar a conversão."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(tone(seconds, rate, channels, freq).tobytes())
    return buffer.getvalue()


def make_mp3(seconds: float = 0.3, rate: int = 44100, bit_rate: int = 128_000) -> bytes:
    """MP3 estéreo (libmp3lame do PyAV)."""
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=rate)
        assert isinstance(stream, av.AudioStream)
        stream.bit_rate = bit_rate
        stream.layout = "stereo"
        samples = tone(seconds, rate, 2)
        step = rate  # 1 s por quadro de entrada; o PyAV refatia para o codec
        for start in range(0, len(samples), step):
            chunk = np.ascontiguousarray(samples[start : start + step])
            frame = av.AudioFrame.from_ndarray(
                chunk.reshape(1, -1), format="s16", layout="stereo"
            )
            frame.sample_rate = rate
            frame.pts = start
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()
