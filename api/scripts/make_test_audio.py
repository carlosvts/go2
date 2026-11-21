"""Gera os áudios de teste do roteiro da rodada (F-006, F-007).

Uso:
    uv run python scripts/make_test_audio.py ../audio-teste

Cria no diretório (novo ou vazio):
    tom-3s.wav   tom de 440 Hz, 3 s, WAV PCM 16 bits 44,1 kHz estéreo
    tom-3s.mp3   o mesmo em MP3
    tom-30s.mp3  30 s em MP3 (o WAV passaria do limite de 5 MB), para cortar e trocar
    tom-1mb.wav  ~1 MB de WAV (~6 s), para o envio sob carga
"""

import argparse
import math
import wave
from pathlib import Path

import av
import numpy as np

RATE = 44100
CHANNELS = 2


def tone(seconds: float, freq: float = 440.0) -> bytes:
    """PCM 16 bits estéreo intercalado, com volume baixo (20%)."""
    n = round(seconds * RATE)
    t = np.arange(n) / RATE
    mono = (0.2 * 32767 * np.sin(2 * math.pi * freq * t)).astype("<i2")
    return np.repeat(mono, CHANNELS).tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    """Grava `pcm` como WAV 16 bits, 44,1 kHz, estéreo."""
    with wave.open(str(path), "wb") as out:
        out.setnchannels(CHANNELS)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)


def write_mp3(path: Path, pcm: bytes) -> None:
    """Codifica `pcm` em MP3 com o PyAV (sem ffmpeg instalado)."""
    samples = np.frombuffer(pcm, "<i2").reshape(1, -1)
    with av.open(str(path), "w", format="mp3") as container:
        stream = container.add_stream("mp3", rate=RATE)
        stream.layout = "stereo"
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="stereo")
        frame.sample_rate = RATE
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def main() -> None:
    """Gera os quatro arquivos."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    write_wav(args.out / "tom-3s.wav", tone(3))
    write_mp3(args.out / "tom-3s.mp3", tone(3))
    write_mp3(args.out / "tom-30s.mp3", tone(30, freq=330.0))
    one_mb_seconds = 1_000_000 / (RATE * CHANNELS * 2)
    write_wav(args.out / "tom-1mb.wav", tone(one_mb_seconds, freq=550.0))
    for path in sorted(args.out.iterdir()):
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
