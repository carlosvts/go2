"""Piper na CPU: texto → WAV, com silêncio no começo (E-002).

`PiperSynthesizer` roda no processo próprio do Piper (`app.reply.piper_service`);
o go2-server usa só o `PiperClient`, por HTTP.

O alto-falante USB da TV Box (Anker) corta o começo do som quando o `aplay`
abre o dispositivo; por isso o mesmo silêncio inicial dos sons de `media/`
(250 ms, `tvbox/scripts/add_lead_silence.py`).

`piper-tts` é importado só aqui, ao carregar a voz (extra `llm` do pyproject).
"""

import io
import threading
import wave
from pathlib import Path

import httpx


class PiperSynthesizer:
    def __init__(self, voice_path: Path, lead_silence_ms: int) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(str(voice_path))
        self._lead_silence_ms = lead_silence_ms
        self._lock = threading.Lock()  # uma síntese por vez: CPU dividida com a go2-api

    def synthesize(self, text: str) -> bytes:
        raw = io.BytesIO()
        with self._lock, wave.open(raw, "wb") as out:
            self._voice.synthesize_wav(text, out)
        return add_lead_silence(raw.getvalue(), self._lead_silence_ms)


class PiperClient:
    """O lado do go2-server: pede a síntese ao processo do Piper."""

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)

    def synthesize(self, text: str) -> bytes:
        response = self._client.post("/synthesize", json={"text": text})
        response.raise_for_status()
        return response.content

    def close(self) -> None:
        self._client.close()


def add_lead_silence(wav: bytes, ms: int) -> bytes:
    with wave.open(io.BytesIO(wav), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    pad = b"\x00" * (params.framerate * ms // 1000) * params.sampwidth * params.nchannels
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setparams(params)
        target.writeframes(pad + frames)
    return out.getvalue()
