"""Contas de `scripts/lidar_stats.py`."""

import pytest

from scripts.lidar_stats import describe, percentile, timing


def test_percentil_interpolado() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([5.0], 99) == 5.0


def test_describe() -> None:
    stats = describe([1.0, 2.0, 3.0])

    assert stats is not None
    assert stats["n"] == 3
    assert stats["mean"] == 2.0
    assert stats["max"] == 3.0
    assert describe([]) is None


def test_timing_taxa_intervalo_e_lacunas() -> None:
    times = [0.0, 0.1, 0.2, 0.3, 0.7]  # um intervalo de 400 ms

    result = timing(times)

    assert result is not None
    assert result["rate_hz"] == pytest.approx(4 / 0.7)
    assert result["interval_ms"]["median"] == pytest.approx(100.0)
    assert result["gaps"] == 1
    assert timing([1.0]) is None
