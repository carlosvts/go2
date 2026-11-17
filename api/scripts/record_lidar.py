"""Grava `/ws/lidar` e `/ws/telemetry` em disco para análise offline (F-002).

Uso:
    uv run python scripts/record_lidar.py --out gravacoes/sessao1 [--seconds 60]
        [--url-base ws://localhost:8000] [--max-mb 500] [--api-commit abc123]

Diretório gerado (precisa ser novo):
    telemetry.jsonl     {"received_at", "frame"} por frame de /ws/telemetry
    lidar/<n>_<seq>.bin frames de /ws/lidar como chegaram (ver ws-lidar.md)
    lidar/index.jsonl   {"n", "seq", "ts", "n_points", "file", "received_at"}
    meta.json           URL, início, fim, contagens e como terminou

Sai com código 0 no fim do tempo ou do `--max-mb`, e com 1 se o servidor
fechar um dos sockets (1013, 1011, 1001) ou a conexão cair. Não reconecta.
"""

import argparse
import asyncio
import json
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

HEADER = struct.Struct("<BBHIdIf3fI")
FRAME_VERSION = 1
MAX_FRAME_BYTES = 64 * 1024 * 1024
"""O padrão do `websockets` (1 MiB) corta acima de ~87 mil pontos."""


@dataclass
class Closed:
    """Como um socket terminou."""

    route: str
    code: int | None
    reason: str


@dataclass
class Recorder:
    """Escreve os arquivos da gravação. Não sabe nada de rede (testável)."""

    out: Path
    url_base: str
    api_commit: str | None = None
    max_bytes: int | None = None
    started_at: float = field(default_factory=time.time)
    lidar_frames: int = 0
    telemetry_frames: int = 0
    bytes_written: int = 0

    def __post_init__(self) -> None:
        """Cria o diretório; recusa um que já exista."""
        self.out.mkdir(parents=True, exist_ok=False)
        (self.out / "lidar").mkdir()
        self._telemetry = (self.out / "telemetry.jsonl").open("a", encoding="utf-8")
        self._index = (self.out / "lidar" / "index.jsonl").open("a", encoding="utf-8")

    @property
    def full(self) -> bool:
        """Atingiu o `--max-mb`."""
        return self.max_bytes is not None and self.bytes_written >= self.max_bytes

    def on_telemetry(self, text: str, received_at: float) -> None:
        """Grava um frame de texto de `/ws/telemetry`."""
        line = json.dumps({"received_at": received_at, "frame": json.loads(text)})
        self._telemetry.write(line + "\n")
        self.telemetry_frames += 1
        self.bytes_written += len(line) + 1

    def on_lidar(self, frame: bytes, received_at: float) -> None:
        """Grava um frame binário de `/ws/lidar` e a linha do índice."""
        _, _, _, seq, ts, n_points, *_ = HEADER.unpack_from(frame, 0)
        name = f"{self.lidar_frames}_{seq}.bin"
        (self.out / "lidar" / name).write_bytes(frame)
        entry = {
            "n": self.lidar_frames,
            "seq": seq,
            "ts": ts,
            "n_points": n_points,
            "file": f"lidar/{name}",
            "received_at": received_at,
        }
        self._index.write(json.dumps(entry) + "\n")
        self.lidar_frames += 1
        self.bytes_written += len(frame)

    def on_message(self, route: str, message: bytes | str, received_at: float) -> None:
        """Encaminha pelo tipo e pela rota.

        O `connection` do `/ws/lidar` é ignorado: o mesmo estado já chega por
        `/ws/telemetry`, e `telemetry.jsonl` guarda só aquela rota.
        """
        if isinstance(message, bytes):
            self.on_lidar(message, received_at)
        elif route == "/ws/telemetry":
            self.on_telemetry(message, received_at)

    def finish(self, ending: str, closed: Closed | None = None) -> dict[str, Any]:
        """Fecha os arquivos e grava `meta.json`; devolve o conteúdo."""
        self._telemetry.close()
        self._index.close()
        meta: dict[str, Any] = {
            "url_base": self.url_base,
            "frame_version": FRAME_VERSION,
            "api_commit": self.api_commit,
            "started_at": self.started_at,
            "ended_at": time.time(),
            "ending": ending,
            "closed_by_server": None
            if closed is None
            else {"route": closed.route, "code": closed.code, "reason": closed.reason},
            "lidar_frames": self.lidar_frames,
            "telemetry_frames": self.telemetry_frames,
            "bytes_written": self.bytes_written,
        }
        (self.out / "meta.json").write_text(json.dumps(meta, indent=2), "utf-8")
        return meta


async def _pump(
    route: str, ws: websockets.ClientConnection, recorder: Recorder
) -> Closed:
    """Grava o que chega até o socket fechar; devolve como fechou."""
    try:
        async for message in ws:
            recorder.on_message(route, message, time.time())
    except websockets.ConnectionClosed as exc:
        rcvd = exc.rcvd
        return Closed(
            route, rcvd.code if rcvd else None, rcvd.reason if rcvd else str(exc)
        )
    rcvd = ws.close_frame
    return Closed(route, rcvd.code if rcvd else None, rcvd.reason if rcvd else "")


async def record(recorder: Recorder, seconds: float) -> int:
    """Grava até o tempo, o limite de disco ou um fechamento; devolve o código."""
    base = recorder.url_base.rstrip("/")
    async with (
        websockets.connect(f"{base}/ws/lidar", max_size=MAX_FRAME_BYTES) as lidar,
        websockets.connect(f"{base}/ws/telemetry") as telemetry,
    ):
        pumps = {
            asyncio.create_task(_pump("/ws/lidar", lidar, recorder)),
            asyncio.create_task(_pump("/ws/telemetry", telemetry, recorder)),
        }

        async def watch_limits() -> None:
            deadline = time.monotonic() + seconds
            # Amostragem a cada 0,1 s: o tamanho em disco não tem evento próprio.
            while time.monotonic() < deadline and not recorder.full:  # noqa: ASYNC110
                await asyncio.sleep(0.1)

        limits = asyncio.create_task(watch_limits())
        done, _ = await asyncio.wait(
            {*pumps, limits}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in (*pumps, limits):
            task.cancel()
        if limits in done:
            ending = "max_mb" if recorder.full else "seconds"
            recorder.finish(ending)
            return 0
        closed = next(task for task in pumps if task in done).result()
        recorder.finish("closed_by_server", closed)
        print(
            f"❌ {closed.route} fechou: {closed.code} {closed.reason}", file=sys.stderr
        )
        return 1


def main() -> None:
    """Lê os argumentos e grava."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--url-base", default="ws://localhost:8000")
    parser.add_argument("--max-mb", type=float, default=None)
    parser.add_argument("--api-commit", default=None)
    args = parser.parse_args()
    recorder = Recorder(
        out=args.out,
        url_base=args.url_base,
        api_commit=args.api_commit,
        max_bytes=None if args.max_mb is None else int(args.max_mb * 1024 * 1024),
    )
    code = asyncio.run(record(recorder, args.seconds))
    print(
        f"{recorder.lidar_frames} frames de LiDAR, {recorder.telemetry_frames} de "
        f"telemetria, {recorder.bytes_written / 1024 / 1024:.1f} MiB em {args.out}"
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
