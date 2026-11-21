"""Estatísticas de taxa e frequência de uma gravação do `record_lidar.py` (F-002).

Uso:
    uv run python scripts/lidar_stats.py ../gravacoes/h1-parado [outra ...]

Para cada gravação, escreve `estatisticas.md` e `estatisticas.json` dentro do
diretório dela e imprime o markdown. Fontes:

- mapas de LiDAR (`lidar/index.jsonl`): `ts` = chegada na api (relógio da
  máquina); `received_at` = chegada no gravador;
- `lidar_pose` (`telemetry.jsonl`): `header.stamp` = relógio do robô;
- `lidar_state`: valores que o próprio sensor reporta;
- `lidar_metrics`: o que a api mediu em janelas de 1 s.

O que é medido pela api ou pelo gravador mede a **entrega**, não o sensor:
a taxa do LiDAR pelo WebRTC difere da taxa interna do laser.
"""

import json
import math
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

GAP_FACTOR = 2.0
"""Intervalo maior que `GAP_FACTOR ×` a mediana conta como lacuna."""


def percentile(values: list[float], q: float) -> float:
    """Percentil por interpolação linear (q entre 0 e 100)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q / 100
    low, high = math.floor(pos), math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def describe(values: list[float]) -> dict[str, float] | None:
    """n, média, desvio, mín., p5, mediana, p95, p99 e máx."""
    if not values:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return {
        "n": len(values),
        "mean": mean,
        "std": math.sqrt(var),
        "min": min(values),
        "p5": percentile(values, 5),
        "median": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
    }


def timing(times: list[float]) -> dict[str, Any] | None:
    """Taxa e intervalos (ms) de uma série de instantes (s)."""
    if len(times) < 2:  # noqa: PLR2004
        return None
    intervals = [(b - a) * 1000 for a, b in pairwise(times)]
    stats = describe(intervals)
    assert stats is not None  # noqa: S101 - len(times) >= 2
    span = times[-1] - times[0]
    gap_limit = GAP_FACTOR * stats["median"]
    return {
        "count": len(times),
        "span_s": span,
        "rate_hz": (len(times) - 1) / span if span > 0 else None,
        "rate_from_median_hz": 1000 / stats["median"] if stats["median"] > 0 else None,
        "interval_ms": stats,
        "jitter_ms": stats["std"],
        "gaps": sum(i > gap_limit for i in intervals),
        "gap_limit_ms": gap_limit,
    }


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def analyze(directory: Path) -> dict[str, Any]:
    """Calcula as estatísticas de uma gravação."""
    meta = json.loads((directory / "meta.json").read_text())
    telemetry = _lines(directory / "telemetry.jsonl")
    index = _lines(directory / "lidar" / "index.jsonl")
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for line in telemetry:
        by_topic.setdefault(line["frame"]["topic"], []).append(line)

    seqs = [entry["seq"] for entry in index]
    seq_gaps = sum((b - a - 1) & 0xFFFFFFFF for a, b in pairwise(seqs))
    lidar = {
        "frames": len(index),
        "seq_gaps": seq_gaps,
        "at_api": timing([e["ts"] for e in index]),
        "at_recorder": timing([e["received_at"] for e in index]),
        "n_points": describe([float(e["n_points"]) for e in index]),
        "api_to_recorder_ms": describe(
            [(e["received_at"] - e["ts"]) * 1000 for e in index]
        ),
    }

    poses = by_topic.get("lidar_pose", [])
    stamps = []
    for line in poses:
        stamp = (line["frame"]["data"].get("header") or {}).get("stamp") or {}
        if "sec" in stamp:
            stamps.append(stamp["sec"] + stamp.get("nanosec", 0) * 1e-9)
    pose = {
        "messages": len(poses),
        "by_robot_clock": timing(stamps),
        "at_recorder": timing([p["received_at"] for p in poses]),
        "robot_clock_minus_recorder_ms": describe(
            [(s - p["received_at"]) * 1000 for s, p in zip(stamps, poses, strict=False)]
        ),
    }

    states = [s["frame"]["data"] for s in by_topic.get("lidar_state", [])]
    reported: dict[str, Any] = {}
    for key in (
        "cloud_frequency",
        "cloud_packet_loss_rate",
        "cloud_size",
        "cloud_scan_num",
        "imu_frequency",
        "imu_packet_loss_rate",
        "sys_rotation_speed",
        "com_rotation_speed",
        "dirty_percentage",
    ):
        values = [float(s[key]) for s in states if isinstance(s.get(key), int | float)]
        reported[key] = describe(values)
    state = {
        "messages": len(states),
        "at_recorder": timing(
            [s["received_at"] for s in by_topic.get("lidar_state", [])]
        ),
        "sensor_reported": reported,
        "error_state": dict(Counter(str(s.get("error_state")) for s in states)),
        "versions": sorted(
            {
                f"fw {s.get('firmware_version')} sw {s.get('software_version')} "
                f"sdk {s.get('sdk_version')}"
                for s in states
            }
        ),
    }

    metrics = [m["frame"]["data"] for m in by_topic.get("lidar_metrics", [])]

    def window(key: str, sub: str | None = None) -> dict[str, float] | None:
        values = []
        for m in metrics:
            value = m.get(key) if sub is None else (m.get(key) or {}).get(sub)
            if isinstance(value, int | float):
                values.append(float(value))
        return describe(values)

    api = {
        "windows": len(metrics),
        "active_windows": sum(bool(m.get("active")) for m in metrics),
        "rate_hz_per_window": window("rate_hz"),
        "decode_ms_mean": window("decode_ms", "mean"),
        "decode_ms_max": window("decode_ms", "max"),
        "pipeline_ms_mean": window("pipeline_ms", "mean"),
        "pipeline_ms_max": window("pipeline_ms", "max"),
        "compressed_kb_mean": describe(
            [
                m["compressed_bytes"]["mean"] / 1024
                for m in metrics
                if m["compressed_bytes"]["mean"]
            ]
        ),
        "src_size": sorted(
            {m["src_size"]["mean"] for m in metrics if m["src_size"]["mean"]}
        ),
        "resolution": sorted({m["resolution"] for m in metrics if m["resolution"]}),
        "totals": {
            key: sum(m.get(key) or 0 for m in metrics)
            for key in (
                "received",
                "decoded",
                "dropped_decode_queue",
                "dropped_lidar_clients",
                "malformed",
                "decode_errors",
                "dropped",
            )
        },
    }
    duration = meta["ended_at"] - meta["started_at"]
    return {
        "recording": directory.name,
        "duration_s": duration,
        "api_commit": meta.get("api_commit"),
        "ending": meta.get("ending"),
        "bytes_written": meta.get("bytes_written"),
        "mb_per_s": meta.get("bytes_written", 0) / 1024 / 1024 / duration
        if duration
        else None,
        "topics": dict(Counter(line["frame"]["topic"] for line in telemetry)),
        "lidar": lidar,
        "pose": pose,
        "state": state,
        "api": api,
    }


def _f(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _row(name: str, stats: dict[str, float] | None, digits: int = 2) -> str:
    if stats is None:
        return f"| {name} | — | | | | | | | | |"
    cells = [
        _f(stats[k], digits)
        for k in ("mean", "std", "min", "p5", "median", "p95", "p99", "max")
    ]
    return f"| {name} | {stats['n']:.0f} | " + " | ".join(cells) + " |"


HEADER = (
    "| | n | média | desvio | mín. | p5 | mediana | p95 | p99 | máx. |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def _timing_lines(name: str, t: dict[str, Any] | None) -> list[str]:
    if t is None:
        return [f"- **{name}:** sem dados"]
    return [
        f"- **{name}:** {t['count']} mensagens em {t['span_s']:.1f} s → "
        f"**{_f(t['rate_hz'])} Hz** "
        f"(pela mediana do intervalo: {_f(t['rate_from_median_hz'])} Hz); "
        f"jitter (desvio do intervalo) {_f(t['jitter_ms'])} ms; "
        f"lacunas > {t['gap_limit_ms']:.0f} ms: {t['gaps']}"
    ]


def render(r: dict[str, Any]) -> str:
    """Relatório em markdown."""
    lidar, pose, state, api = r["lidar"], r["pose"], r["state"], r["api"]
    out = [
        f"# Estatísticas — `{r['recording']}`",
        "",
        f"Duração {r['duration_s']:.1f} s · api `{r['api_commit']}` · "
        f"término `{r['ending']}` · "
        f"{r['bytes_written'] / 1024 / 1024:.0f} MB em disco "
        f"({_f(r['mb_per_s'])} MB/s)",
        "",
        "Mensagens por tópico: "
        + ", ".join(f"`{k}` {v}" for k, v in r["topics"].items()),
        "",
        "## Taxas de entrega",
        "",
        *_timing_lines("Mapas de LiDAR, chegada na api", lidar["at_api"]),
        *_timing_lines("Mapas de LiDAR, chegada no gravador", lidar["at_recorder"]),
        *_timing_lines("Pose (`lidar_pose`), relógio do robô", pose["by_robot_clock"]),
        *_timing_lines("Pose, chegada no gravador", pose["at_recorder"]),
        *_timing_lines(
            "Estado do sensor (`lidar_state`), chegada", state["at_recorder"]
        ),
        f"- **Buracos no `seq` do LiDAR:** {lidar['seq_gaps']} "
        f"em {lidar['frames']} frames",
        "",
        "Intervalos entre mensagens (ms):",
        "",
        HEADER,
        _row("LiDAR (api)", (lidar["at_api"] or {}).get("interval_ms")),
        _row("LiDAR (gravador)", (lidar["at_recorder"] or {}).get("interval_ms")),
        _row("Pose (robô)", (pose["by_robot_clock"] or {}).get("interval_ms")),
        _row("Pose (gravador)", (pose["at_recorder"] or {}).get("interval_ms")),
        _row("Estado (gravador)", (state["at_recorder"] or {}).get("interval_ms")),
        "",
        "## O que o sensor reporta (`lidar_state`)",
        "",
        HEADER,
        *(_row(k, v) for k, v in state["sensor_reported"].items()),
        "",
        f"`error_state`: {state['error_state']} · "
        f"versões: {', '.join(state['versions']) or '—'}",
        "",
        "## Nuvem e processamento na api",
        "",
        HEADER,
        _row("pontos por frame", lidar["n_points"], 0),
        _row("comprimido por mapa (KB), média da janela", api["compressed_kb_mean"]),
        _row("taxa por janela de 1 s (Hz)", api["rate_hz_per_window"]),
        _row("decodificação (ms), média da janela", api["decode_ms_mean"]),
        _row("decodificação (ms), máx. da janela", api["decode_ms_max"]),
        _row("callback → frame pronto (ms), média", api["pipeline_ms_mean"]),
        _row("callback → frame pronto (ms), máx.", api["pipeline_ms_max"]),
        _row("api → gravador (ms)", lidar["api_to_recorder_ms"]),
        _row("relógio do robô − gravador (ms)", pose["robot_clock_minus_recorder_ms"]),
        "",
        f"`src_size`: {api['src_size']} · `resolution`: {api['resolution']} · "
        f"janelas com LiDAR ativo: {api['active_windows']}/{api['windows']}",
        "",
        "Totais da api: " + ", ".join(f"`{k}` {v}" for k, v in api["totals"].items()),
        "",
        'Notas: taxas "na api" e "no gravador" medem a entrega pelo WebRTC e '
        "pela rede, "
        'não o sensor. "Relógio do robô − gravador" inclui a latência de rede. '
        "O `stamp` de `lidar_state` não é usado: a precisão dele é de ~128 s.",
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    """Analisa cada diretório passado."""
    if len(sys.argv) < 2:  # noqa: PLR2004
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        directory = Path(arg)
        result = analyze(directory)
        report = render(result)
        (directory / "estatisticas.md").write_text(report, encoding="utf-8")
        (directory / "estatisticas.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
