"""Gravador `scripts/record_lidar.py` (F-002, A16), sem rede."""

import json
from pathlib import Path

import numpy as np
import pytest

from app.robot.lidar import RawLidarMessage, build_frame
from scripts.record_lidar import Closed, Recorder


def _frame(seq: int, n_points: int) -> bytes:
    points = np.arange(n_points * 3, dtype=np.float64).reshape(-1, 3)
    raw = RawLidarMessage(
        seq=seq,
        ts=1000.0 + seq,
        payload=b"",
        src_size=0,
        origin=(0.0, 0.0, 0.0),
        resolution=0.05,
    )
    return build_frame(raw, lambda *_: points)


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a16_grava_os_arquivos_esperados(tmp_path: Path) -> None:
    out = tmp_path / "sessao"
    recorder = Recorder(out=out, url_base="ws://api:8000", api_commit="abc123")
    telemetry = json.dumps({"topic": "lidar_metrics", "ts": 1.0, "data": {"x": 1}})

    recorder.on_telemetry(telemetry, received_at=5.0)
    recorder.on_lidar(_frame(7, 2), received_at=6.0)
    recorder.on_lidar(_frame(8, 0), received_at=7.0)
    meta = recorder.finish("seconds")

    assert _lines(out / "telemetry.jsonl") == [
        {"received_at": 5.0, "frame": json.loads(telemetry)}
    ]
    index = _lines(out / "lidar" / "index.jsonl")
    assert index == [
        {
            "n": 0,
            "seq": 7,
            "ts": 1007.0,
            "n_points": 2,
            "file": "lidar/0_7.bin",
            "received_at": 6.0,
        },
        {
            "n": 1,
            "seq": 8,
            "ts": 1008.0,
            "n_points": 0,
            "file": "lidar/1_8.bin",
            "received_at": 7.0,
        },
    ]
    assert (out / "lidar" / "0_7.bin").read_bytes() == _frame(7, 2)
    on_disk = json.loads((out / "meta.json").read_text())
    assert on_disk == meta
    assert meta["ending"] == "seconds"
    assert meta["closed_by_server"] is None
    assert meta["api_commit"] == "abc123"
    assert (meta["lidar_frames"], meta["telemetry_frames"]) == (2, 1)


def test_a16_seq_repetido_nao_sobrescreve(tmp_path: Path) -> None:
    recorder = Recorder(out=tmp_path / "s", url_base="ws://api")

    recorder.on_lidar(_frame(0, 1), received_at=1.0)
    recorder.on_lidar(_frame(0, 3), received_at=2.0)  # api reiniciou: seq voltou a 0
    recorder.finish("seconds")

    files = sorted(p.name for p in (tmp_path / "s" / "lidar").glob("*.bin"))
    assert files == ["0_0.bin", "1_0.bin"]


def test_a16_registra_fechamento_pelo_servidor(tmp_path: Path) -> None:
    recorder = Recorder(out=tmp_path / "s", url_base="ws://api")

    meta = recorder.finish(
        "closed_by_server", Closed("/ws/lidar", 1011, "lidar_unavailable")
    )

    assert meta["closed_by_server"] == {
        "route": "/ws/lidar",
        "code": 1011,
        "reason": "lidar_unavailable",
    }


def test_recusa_diretorio_existente(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        Recorder(out=tmp_path, url_base="ws://api")


def test_limite_de_disco(tmp_path: Path) -> None:
    recorder = Recorder(out=tmp_path / "s", url_base="ws://api", max_bytes=100)

    recorder.on_lidar(_frame(0, 10), received_at=1.0)

    assert recorder.full
    recorder.finish("max_mb")


def test_texto_do_ws_lidar_nao_entra_na_telemetria(tmp_path: Path) -> None:
    recorder = Recorder(out=tmp_path / "s", url_base="ws://api")
    connection = json.dumps({"topic": "connection", "ts": 1.0, "data": {}})

    recorder.on_message("/ws/lidar", connection, 1.0)
    recorder.on_message("/ws/lidar", _frame(3, 1), 2.0)
    recorder.on_message("/ws/telemetry", connection, 3.0)
    recorder.finish("seconds")

    assert recorder.telemetry_frames == 1
    assert recorder.lidar_frames == 1
    assert _lines(tmp_path / "s" / "telemetry.jsonl")[0]["received_at"] == 3.0
