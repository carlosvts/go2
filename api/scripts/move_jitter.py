"""Desvio do reenvio do `move` a partir do log DEBUG da api (F-001 A14, F-002 A18).

A api registra "Move reenviado; intervalo X ms." a cada reenvio quando sobe com
`--log-config logging-debug.json`. Este script lê esse log e calcula, contra o
período nominal (`1000 / GO2_MOVE_RATE_HZ`), o p99 do desvio e o maior intervalo.

Uso:
    uv run python scripts/move_jitter.py api.log --rate-hz 40
    uv run python scripts/move_jitter.py base.log carga.log --rate-hz 40

Com dois arquivos (linha de base e com LiDAR), aplica a régua do F-001:
p99(carga) ≤ p99(base) + 10% do período, e máx(carga) ≤ 2× o período.
"""

import argparse
import math
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"Move reenviado; intervalo ([0-9.]+) ms")


def intervals(path: Path) -> list[float]:
    """Intervalos (ms) registrados no log, em ordem."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [float(m.group(1)) for m in PATTERN.finditer(text)]


def p99(values: list[float]) -> float:
    """Percentil 99 pelo método do posto mais próximo."""
    ordered = sorted(values)
    rank = max(math.ceil(0.99 * len(ordered)) - 1, 0)
    return ordered[rank]


def summary(values: list[float], period_ms: float) -> dict[str, float]:
    """n, p99 do desvio e intervalo máximo (ms)."""
    deviations = [abs(v - period_ms) for v in values]
    return {"n": len(values), "p99_dev_ms": p99(deviations), "max_ms": max(values)}


def main() -> int:
    """Imprime o resumo e, com dois logs, o veredito da régua."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--rate-hz", type=float, required=True)
    args = parser.parse_args()
    period = 1000.0 / args.rate_hz
    results = []
    for path in args.logs:
        values = intervals(path)
        if not values:
            print(f"{path}: nenhuma linha 'Move reenviado' (log DEBUG ligado?)")
            return 2
        result = summary(values, period)
        results.append(result)
        print(
            f"{path}: n={result['n']:.0f} p99 desvio={result['p99_dev_ms']:.2f} ms"
            f" máx={result['max_ms']:.1f} ms (período {period:.1f} ms)"
        )
    if len(results) == 2:  # noqa: PLR2004 - base e carga
        base, load = results
        limit = base["p99_dev_ms"] + 0.10 * period
        ok_p99 = load["p99_dev_ms"] <= limit
        ok_max = load["max_ms"] <= 2 * period
        verdict = {True: "sim", False: "NÃO"}
        print(f"p99: {load['p99_dev_ms']:.2f} ≤ {limit:.2f} ms? {verdict[ok_p99]}")
        print(f"máx: {load['max_ms']:.1f} ≤ {2 * period:.1f} ms? {verdict[ok_max]}")
        return 0 if ok_p99 and ok_max else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
