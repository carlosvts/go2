"""F-006 A3: protocolo de envio de `upload_audio_file` da lib, em `unitree.py`."""

import base64
import hashlib
import json

import pytest

from app.robot.unitree import (
    AUDIO_API,
    AUDIO_UPLOAD_BLOCK_CHARS,
    AUDIO_UPLOAD_BLOCK_INTERVAL_S,
    RTC_TOPIC,
    AudioUploadBlocks,
)


def test_constantes_vem_da_lib() -> None:
    assert AUDIO_API["UPLOAD_AUDIO_FILE"] == 2001
    assert AUDIO_API["GET_AUDIO_LIST"] == 1001
    assert RTC_TOPIC["AUDIO_HUB_REQ"] == "rt/api/audiohub/request"
    assert RTC_TOPIC["AUDIO_HUB_PLAY_STATE"] == "rt/audiohub/player/state"
    assert AUDIO_UPLOAD_BLOCK_CHARS == 4096
    assert pytest.approx(0.1) == AUDIO_UPLOAD_BLOCK_INTERVAL_S


@pytest.mark.parametrize("size", [1, 3071, 3072, 3073, 10_000, 30_001])
def test_blocos_reconstroem_o_arquivo(size: int) -> None:
    wav = bytes(range(256)) * (size // 256) + bytes(size % 256)
    blocks = AudioUploadBlocks(wav, "teste")

    params = [json.loads(blocks.parameter(i, 123)) for i in range(1, blocks.total + 1)]

    b64 = base64.b64encode(wav).decode()
    assert blocks.total == -(-len(b64) // 4096)
    assert base64.b64decode("".join(p["block_content"] for p in params)) == wav
    assert [p["current_block_index"] for p in params] == list(
        range(1, blocks.total + 1)
    )
    for p in params:
        assert len(p["block_content"]) <= 4096
        assert p["current_block_size"] == len(p["block_content"])
        assert p["total_block_number"] == blocks.total
        assert p["file_md5"] == hashlib.md5(wav).hexdigest()  # noqa: S324
        assert p["file_size"] == len(wav)


def test_parametro_tem_exatamente_os_campos_da_lib_em_ascii() -> None:
    blocks = AudioUploadBlocks(b"RIFF1234WAVE", "olá")

    raw = blocks.parameter(1, 1_700_000_000_000)

    assert raw == json.dumps(
        {
            "file_name": "olá",
            "file_type": "wav",
            "file_size": 12,
            "current_block_index": 1,
            "total_block_number": 1,
            "block_content": base64.b64encode(b"RIFF1234WAVE").decode(),
            "current_block_size": 16,
            "file_md5": hashlib.md5(b"RIFF1234WAVE").hexdigest(),  # noqa: S324
            "create_time": 1_700_000_000_000,
        },
        ensure_ascii=True,
    )
    assert raw.isascii()
