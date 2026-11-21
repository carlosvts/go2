"""F-006 A4/A5: detecção de formato e conversão MP3 → WAV (PyAV)."""

import pytest

from app.exceptions import PayloadTooLargeError, UnsupportedMediaError
from app.robot.audio_format import AudioConverter, SourceFormat
from tests.audio_files import make_mp3, make_wav, wav_info

LIMIT = 5 * 1024 * 1024


def test_wav_passa_como_veio() -> None:
    wav = make_wav(rate=16000, channels=1)

    prepared = AudioConverter.prepare(wav, LIMIT)

    assert prepared.source_format is SourceFormat.wav
    assert prepared.wav == wav


@pytest.mark.parametrize(("rate", "channels"), [(22050, 1), (48000, 2)])
def test_a4_mp3_vira_wav_pcm16_44100_com_os_canais_e_a_duracao(
    rate: int, channels: int
) -> None:
    mp3 = make_mp3(seconds=1.5, rate=rate, channels=channels)

    prepared = AudioConverter.prepare(mp3, LIMIT)

    assert prepared.source_format is SourceFormat.mp3
    got_channels, width, got_rate, duration = wav_info(prepared.wav)
    assert (got_channels, width, got_rate) == (channels, 2, 44100)
    assert duration == pytest.approx(1.5, abs=0.05)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"isto nao e audio" * 100,
        b"OggS" + bytes(500),
        b"RIFF\x00\x00\x00\x00WAVE" + b"lixo" * 200,
        b"ID3" + bytes(range(256)) * 4,
    ],
    ids=["vazio", "texto", "ogg", "wav-corrompido", "mp3-corrompido"],
)
def test_a5_nao_wav_nem_mp3_ou_corrompido_e_415(data: bytes) -> None:
    with pytest.raises(UnsupportedMediaError):
        AudioConverter.prepare(data, LIMIT)


def test_a5_mp3_pequeno_que_vira_wav_grande_e_413_com_o_tamanho() -> None:
    mp3 = make_mp3(seconds=3.0, rate=22050, channels=1)
    limit = len(mp3) * 4  # o WAV de 3 s a 44,1 kHz tem ~265 kB

    with pytest.raises(PayloadTooLargeError, match=r"\d+ bytes"):
        AudioConverter.prepare(mp3, limit)


def test_wav_final_no_limite_exato_e_aceito() -> None:
    mp3 = make_mp3(seconds=1.0)
    size = len(AudioConverter.prepare(mp3, LIMIT).wav)

    assert len(AudioConverter.prepare(mp3, size).wav) == size
    with pytest.raises(PayloadTooLargeError):
        AudioConverter.prepare(mp3, size - 1)
