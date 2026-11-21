"""Áudios gerados nos testes da F-006 (WAV pela stdlib, MP3 pelo PyAV)."""

import io
import wave
from typing import cast

import av
import numpy as np

MP3_FRAME_SAMPLES = 1152


def _tone(seconds: float, rate: int, channels: int) -> np.ndarray:
    """Seno de 440 Hz, `int16`, intercalado `(amostras × canais,)`."""
    samples = int(seconds * rate)
    t = np.arange(samples) / rate
    mono = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
    return np.repeat(mono, channels)


def make_wav(seconds: float = 0.5, rate: int = 16000, channels: int = 1) -> bytes:
    """WAV PCM 16 bits com um seno."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(_tone(seconds, rate, channels).tobytes())
    return buffer.getvalue()


def make_mp3(
    seconds: float = 1.0,
    rate: int = 22050,
    channels: int = 1,
    bit_rate: int = 64000,
) -> bytes:
    """MP3 com um seno, codificado pelo PyAV (libmp3lame)."""
    layout = "mono" if channels == 1 else "stereo"
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp3") as container:
        stream = cast(
            "av.AudioStream",
            container.add_stream("libmp3lame", rate=rate, layout=layout),
        )
        stream.bit_rate = bit_rate
        pcm = _tone(seconds, rate, channels)
        step = MP3_FRAME_SAMPLES * 8 * channels
        for start in range(0, len(pcm), step):
            chunk = pcm[start : start + step].reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(chunk, format="s16", layout=layout)
            frame.sample_rate = rate
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


def make_mp3_of_size(size_bytes: int) -> bytes:
    """MP3 estéreo a 320 kbit/s com pelo menos `size_bytes`, cortado no tamanho.

    Cortar no fim deixa o último quadro incompleto, o que o decoder tolera.
    """
    seconds = size_bytes * 8 / 320_000 + 1
    data = make_mp3(seconds=seconds, rate=44100, channels=2, bit_rate=320_000)
    return data[:size_bytes]


def wav_info(data: bytes) -> tuple[int, int, int, float]:
    """`(canais, bytes por amostra, taxa, duração em s)` de um WAV."""
    with wave.open(io.BytesIO(data), "rb") as reader:
        frames = reader.getnframes()
        rate = reader.getframerate()
        return reader.getnchannels(), reader.getsampwidth(), rate, frames / rate
