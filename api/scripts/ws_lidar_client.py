"""Cliente de diagnóstico do `/ws/lidar` (F-001, roteiro H1).

Conecta, valida o cabeçalho de cada frame e imprime, a cada segundo:
frames/s, `n_points` (mín./médio/máx.), bytes/frame e buracos no `seq`.
Imprime também as transições de estado da conexão com o robô.

Uso:
    uv run python scripts/ws_lidar_client.py [--url ws://localhost:8000/ws/lidar]
        [--seconds 60] [--save DIR --save-count 5]

Os frames salvos (`frame_<seq>.bin`) abrem com:
    np.frombuffer(open(f, "rb").read(), "<f4", offset=40).reshape(-1, 3)
"""

import argparse
import asyncio
import json
import struct
import time
from pathlib import Path

import websockets

HEADER = struct.Struct("<BBHIdIf3fI")
MAX_FRAME_BYTES = 64 * 1024 * 1024
"""O padrão do `websockets` (1 MiB) corta acima de ~87 mil pontos."""


class Stats:
    """Acumula as métricas de uma janela de um segundo."""

    def __init__(self) -> None:
        """Começa a janela zerada."""
        self.frames = 0
        self.points: list[int] = []
        self.bytes: list[int] = []
        self.gaps = 0
        self.last_seq: int | None = None

    def add(self, seq: int, n_points: int, size: int) -> None:
        """Conta um frame e detecta buraco no `seq`."""
        if self.last_seq is not None:
            self.gaps += (seq - self.last_seq - 1) & 0xFFFFFFFF
        self.last_seq = seq
        self.frames += 1
        self.points.append(n_points)
        self.bytes.append(size)

    def report(self, elapsed: float) -> str:
        """Linha de resumo da janela."""
        if not self.frames:
            return f"{0:5.1f} frames/s (nenhum frame)"
        avg = sum(self.points) / len(self.points)
        return (
            f"{self.frames / elapsed:5.1f} frames/s | pontos "
            f"{min(self.points)}/{avg:.0f}/{max(self.points)} | "
            f"{sum(self.bytes) / len(self.bytes) / 1024:.1f} KiB/frame | "
            f"buracos no seq: {self.gaps}"
        )


def parse_frame(frame: bytes) -> tuple[int, int, float, int, float, tuple[float, ...]]:
    """Valida e desmonta o cabeçalho: (version, seq, ts, n_points, res, origin)."""
    version, _flags, header_len, seq, ts, n_points, res, ox, oy, oz, _ = (
        HEADER.unpack_from(frame, 0)
    )
    if version != 1:
        msg = f"versão desconhecida: {version}"
        raise ValueError(msg)
    if len(frame) != header_len + 12 * n_points:
        msg = f"tamanho {len(frame)} não bate com n_points={n_points}"
        raise ValueError(msg)
    return version, seq, ts, n_points, res, (ox, oy, oz)


async def run(url: str, seconds: float, save: Path | None, save_count: int) -> None:
    """Lê o stream por `seconds` e imprime as métricas."""
    stats = Stats()
    saved = 0
    window = time.monotonic()
    end = window + seconds
    async with websockets.connect(url, max_size=MAX_FRAME_BYTES) as ws:
        while time.monotonic() < end:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except TimeoutError:
                message = None
            if isinstance(message, str):
                print("estado:", json.loads(message)["data"]["state"])
            elif isinstance(message, bytes):
                _, seq, ts, n_points, res, origin = parse_frame(message)
                stats.add(seq, n_points, len(message))
                if save is not None and saved < save_count:
                    (save / f"frame_{seq}.bin").write_bytes(message)
                    saved += 1
                    print(
                        f"salvo frame {seq}: n={n_points} resolution={res} "
                        f"origin={origin} atraso={time.time() - ts:.3f}s"
                    )
            now = time.monotonic()
            if now - window >= 1.0:
                print(stats.report(now - window))
                last_seq = stats.last_seq
                stats = Stats()
                stats.last_seq = last_seq
                window = now


def main() -> None:
    """Lê os argumentos e roda o cliente."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://localhost:8000/ws/lidar")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--save", type=Path, default=None)
    parser.add_argument("--save-count", type=int, default=5)
    args = parser.parse_args()
    if args.save is not None:
        args.save.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.url, args.seconds, args.save, args.save_count))


if __name__ == "__main__":
    main()
