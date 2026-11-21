"""`scripts/move_jitter.py` e o `logging-debug.json` (instrumento do A14/A18)."""

import json
import logging
import logging.config
from pathlib import Path

import pytest

from app.robot.movement import log as movement_log
from scripts.move_jitter import intervals, p99, summary

API_DIR = Path(__file__).resolve().parents[2]


def test_le_intervalos_do_log(tmp_path: Path) -> None:
    log = tmp_path / "api.log"
    log.write_text(
        "x DEBUG app.robot.movement: Move reenviado; intervalo 25.1 ms.\n"
        "y INFO outra coisa\n"
        "z DEBUG app.robot.movement: Move reenviado; intervalo 30.0 ms.\n"
    )

    assert intervals(log) == [25.1, 30.0]


def test_resumo_contra_o_periodo() -> None:
    values = [25.0] * 99 + [40.0]

    result = summary(values, period_ms=25.0)

    assert result == {"n": 100, "p99_dev_ms": 0.0, "max_ms": 40.0}
    assert p99([1.0, 2.0, 3.0]) == 3.0


def test_config_de_log_mostra_o_debug_do_move(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = json.loads((API_DIR / "logging-debug.json").read_text())
    config["handlers"]["stderr"]["stream"] = "ext://sys.stdout"
    try:
        logging.config.dictConfig(config)
        movement_log.debug("Move reenviado; intervalo %.1f ms.", 25.0)
    finally:
        logging.getLogger("app").handlers.clear()
        logging.getLogger("app").propagate = True
        logging.getLogger("app").setLevel(logging.NOTSET)

    assert "Move reenviado; intervalo 25.0 ms." in capsys.readouterr().out
