"""Ferramentas do lab do `/ws/video` (F-003), sem rede."""

import json
import math
from pathlib import Path

import pytest

from app.robot.video import encode_frame
from scripts.record_video import VideoRecorder
from scripts.ws_video_client import Stats, jpeg_decodes, parse_frame
from tests.video_frames import video_frame


def _frame(seq: int, time_s: float | None = 1.0) -> bytes:
    return encode_frame(video_frame(time_s=time_s), seq, 1000.0 + seq, 80)


def test_cliente_valida_e_decodifica_o_frame() -> None:
    frame = _frame(3)
    header = parse_frame(frame)

    assert (header.seq, header.width, header.height) == (3, 64, 48)
    assert jpeg_decodes(frame, header)


def test_cliente_recusa_versao_e_tamanho_errados() -> None:
    frame = bytearray(_frame(0))
    with pytest.raises(ValueError, match="tamanho"):
        parse_frame(bytes(frame[:-1]))
    frame[0] = 2
    with pytest.raises(ValueError, match="versão"):
        parse_frame(bytes(frame))


def test_cliente_conta_buracos_e_intervalo_de_media_time() -> None:
    stats = Stats()
    for seq, media in ((0, 1.0), (1, 1.04), (4, 1.2)):
        frame = _frame(seq, media)
        stats.add(parse_frame(frame), len(frame), 1000.0 + seq, ok=True)

    assert stats.gaps == 2
    assert stats.media_intervals == pytest.approx([0.04, 0.16])
    assert "buracos no seq: 2" in stats.report(1.0)


def test_gravador_escreve_jpeg_indice_estados_e_meta(tmp_path: Path) -> None:
    out = tmp_path / "sessao"
    recorder = VideoRecorder(out=out, url="ws://api:8000/ws/video", api_commit="abc")
    recorder.on_text(
        json.dumps({"topic": "video", "ts": 1, "data": {"state": "starting"}}), 5.0
    )
    recorder.on_frame(_frame(7), 6.0)
    recorder.on_frame(_frame(8, None), 7.0)
    meta = recorder.finish("seconds")

    index = [
        json.loads(line) for line in (out / "index.jsonl").read_text().splitlines()
    ]
    assert [e["seq"] for e in index] == [7, 8]
    assert index[1]["media_time"] is None
    assert (out / index[0]["file"]).read_bytes()[:2] == b"\xff\xd8"
    states = (out / "states.jsonl").read_text().splitlines()
    assert json.loads(states[0])["frame"]["data"]["state"] == "starting"
    assert meta["frames"] == 2
    assert meta["ended_by"] == "seconds"
    assert not math.isnan(index[0]["media_time"])


def test_gravador_recusa_diretorio_existente(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        VideoRecorder(out=tmp_path, url="ws://x")
