"""Formato do áudio enviado ao robô: detecção e conversão MP3 → WAV (F-006).

Igual à lib, só o MP3 é convertido: WAV PCM 16 bits, 44,1 kHz, com os canais
do original. A lib usa o pydub (que exige o `ffmpeg` instalado); aqui é o
PyAV, que traz o ffmpeg no wheel. Tudo é síncrono e pesa na CPU: chame fora
do event loop (`asyncio.to_thread`).
"""

import io
import wave
from dataclasses import dataclass
from enum import StrEnum

import av

from app.exceptions import PayloadTooLargeError, UnsupportedMediaError

TARGET_RATE = 44100
_SAMPLE_WIDTH = 2  # PCM 16 bits
_WAV_HEADER_BYTES = 44  # cabeçalho do `wave` da stdlib, sem chunks extras
# Sincronismo de quadro MPEG: 11 bits em 1 (0xFF e os 3 bits altos do 2º byte).
_MP3_SYNC_FIRST = 0xFF
_MP3_SYNC_MASK = 0xE0


class SourceFormat(StrEnum):
    """Formato detectado pelo conteúdo do arquivo."""

    wav = "wav"
    mp3 = "mp3"


@dataclass(frozen=True)
class PreparedAudio:
    """O WAV que vai ao robô e o formato de origem."""

    wav: bytes
    source_format: SourceFormat


class AudioConverter:
    """Confere o formato pelo conteúdo e entrega o WAV do envio."""

    @classmethod
    def prepare(cls, data: bytes, max_bytes: int) -> PreparedAudio:
        """Valida `data` e devolve o WAV a enviar.

        Args:
            data: Bytes recebidos (WAV ou MP3).
            max_bytes: Teto do WAV final (`GO2_AUDIO_MAX_UPLOAD_MB`).

        Raises:
            UnsupportedMediaError: não é WAV nem MP3, ou não decodifica.
            PayloadTooLargeError: o WAV final passa de `max_bytes`.
        """
        source = cls.detect(data)
        if source is SourceFormat.wav:
            cls._decode(data, source, max_bytes=None)
            wav = data
        else:
            wav = cls._decode(data, source, max_bytes=max_bytes)
        if len(wav) > max_bytes:
            msg = f"❌ O WAV enviado teria {len(wav)} bytes; o limite é {max_bytes}."
            raise PayloadTooLargeError(msg)
        return PreparedAudio(wav=wav, source_format=source)

    @staticmethod
    def detect(data: bytes) -> SourceFormat:
        """Reconhece WAV (`RIFF…WAVE`) ou MP3 (`ID3` ou sincronismo de quadro).

        Raises:
            UnsupportedMediaError: nenhum dos dois.
        """
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return SourceFormat.wav
        frame_sync = (
            len(data) > 1
            and data[0] == _MP3_SYNC_FIRST
            and data[1] & _MP3_SYNC_MASK == _MP3_SYNC_MASK
        )
        if data[:3] == b"ID3" or frame_sync:
            return SourceFormat.mp3
        msg = "❌ O arquivo não é WAV nem MP3."
        raise UnsupportedMediaError(msg)

    @classmethod
    def _decode(
        cls, data: bytes, source: SourceFormat, *, max_bytes: int | None
    ) -> bytes:
        """Decodifica tudo; com `max_bytes`, monta o WAV 44,1 kHz PCM 16.

        Sem `max_bytes` só confere que decodifica e devolve `b""`. Com ele,
        acima do teto continua decodificando só para contar o tamanho final,
        sem guardar as amostras.
        """
        pcm: list[bytes] = []
        size = 0
        decoded = 0
        channels = 0
        try:
            with av.open(io.BytesIO(data), mode="r", format=source.value) as container:
                for stream in container.streams.audio[:1]:
                    channels = stream.codec_context.channels
                    resampler = av.AudioResampler(
                        format="s16",
                        layout=stream.codec_context.layout,
                        rate=TARGET_RATE,
                    )
                    for frame in container.decode(stream):
                        decoded += frame.samples
                        if max_bytes is not None:
                            size = cls._collect(
                                resampler.resample(frame), pcm, size, max_bytes
                            )
                    if max_bytes is not None:
                        size = cls._collect(
                            resampler.resample(None), pcm, size, max_bytes
                        )
        except (av.FFmpegError, ValueError, IndexError) as exc:
            msg = f"❌ O arquivo {source.value.upper()} não decodifica."
            raise UnsupportedMediaError(msg) from exc
        if decoded == 0:
            msg = f"❌ O arquivo {source.value.upper()} não tem amostras."
            raise UnsupportedMediaError(msg)
        if max_bytes is None:
            return b""
        total = _WAV_HEADER_BYTES + size
        if total > max_bytes:
            msg = f"❌ O WAV convertido teria {total} bytes; o limite é {max_bytes}."
            raise PayloadTooLargeError(msg)
        return cls._wav(b"".join(pcm), channels)

    @staticmethod
    def _collect(
        frames: list[av.AudioFrame], pcm: list[bytes], size: int, max_bytes: int
    ) -> int:
        """Soma os bytes PCM de `frames`; guarda-os enquanto cabem no teto."""
        for frame in frames:
            chunk = frame.to_ndarray().tobytes()
            size += len(chunk)
            if _WAV_HEADER_BYTES + size <= max_bytes:
                pcm.append(chunk)
        return size

    @staticmethod
    def _wav(pcm: bytes, channels: int) -> bytes:
        """Embrulha PCM 16 bits intercalado num WAV 44,1 kHz."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(_SAMPLE_WIDTH)
            out.setframerate(TARGET_RATE)
            out.writeframes(pcm)
        return buffer.getvalue()
