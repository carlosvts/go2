"""Grava o `/ws/video` em disco para análise offline (F-003).

Regra de uso (F-003, Impacto HRI): avise as pessoas no lab antes de ligar o
vídeo e não grave quem não foi avisado.

Uso:
    uv run python scripts/record_video.py [--out gravacoes/video-<data>]
        [--seconds 30] [--frames N] [--url ws://localhost:8000/ws/video]
        [--api-commit abc123]

Diretório gerado (precisa ser novo; o padrão fica em `gravacoes/`, fora do
que o git versiona):
    frames/<n>_<seq>.jpg  JPEG de cada frame
    index.jsonl           {"n", "seq", "ts", "received_at", "media_time",
                           "width", "height", "jpeg_len", "file"}
    states.jsonl          {"received_at", "frame"} por frame de texto
    meta.json             URL, início, fim, contagens e como terminou

Sai com código 0 no fim do tempo ou de `--frames`, e com 1 se o servidor
fechar o socket (1013, 1011, 1001) ou a conexão cair. Não reconecta.
"""

import argparse
import asyncio
import json
import math
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

HEADER = struct.Struct("<BBHIdHHId")
MAX_FRAME_BYTES = 16 * 1024 * 1024


@dataclass
class VideoRecorder:
    """Escreve os arquivos da gravação. Não sabe nada de rede (testável)."""

    out: Path
    url: str
    api_commit: str | None = None
    started_at: float = field(default_factory=time.time)
    frames: int = 0
    texts: int = 0

    def __post_init__(self) -> None:
        """Cria o diretório; recusa um que já exista."""
        self.out.mkdir(parents=True, exist_ok=False)
        (self.out / "frames").mkdir()
        self._index = (self.out / "index.jsonl").open("a", encoding="utf-8")
        self._states = (self.out / "states.jsonl").open("a", encoding="utf-8")

    def on_text(self, text: str, received_at: float) -> None:
        """Grava um frame de texto (`connection` ou `video`)."""
        line = {"received_at": received_at, "frame": json.loads(text)}
        self._states.write(json.dumps(line) + "\n")
        self.texts += 1

    def on_frame(self, frame: bytes, received_at: float) -> None:
        """Grava o JPEG de um frame binário e a linha do índice."""
        _, _, header_len, seq, ts, width, height, jpeg_len, media_time = (
            HEADER.unpack_from(frame, 0)
        )
        name = f"{self.frames}_{seq}.jpg"
        (self.out / "frames" / name).write_bytes(frame[header_len:])
        entry = {
            "n": self.frames,
            "seq": seq,
            "ts": ts,
            "received_at": received_at,
            "media_time": None if math.isnan(media_time) else media_time,
            "width": width,
            "height": height,
            "jpeg_len": jpeg_len,
            "file": f"frames/{name}",
        }
        self._index.write(json.dumps(entry) + "\n")
        self.frames += 1

    def finish(
        self, ended_by: str, closed: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Fecha os arquivos e escreve o `meta.json`."""
        self._index.close()
        self._states.close()
        meta = {
            "url": self.url,
            "api_commit": self.api_commit,
            "started_at": self.started_at,
            "ended_at": time.time(),
            "frames": self.frames,
            "texts": self.texts,
            "ended_by": ended_by,
            "closed": closed,
        }
        (self.out / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return meta


async def record(
    recorder: VideoRecorder, seconds: float, max_frames: int | None
) -> int:
    """Grava até o tempo ou `max_frames`; devolve o código de saída."""
    end = time.monotonic() + seconds
    try:
        async with websockets.connect(recorder.url, max_size=MAX_FRAME_BYTES) as ws:
            while time.monotonic() < end:
                if max_frames is not None and recorder.frames >= max_frames:
                    recorder.finish("frames")
                    return 0
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except TimeoutError:
                    continue
                if isinstance(message, str):
                    recorder.on_text(message, time.time())
                else:
                    recorder.on_frame(message, time.time())
    except websockets.ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd else None
        reason = exc.rcvd.reason if exc.rcvd else ""
        recorder.finish("closed", {"code": code, "reason": reason})
        print(f"socket fechado: {code} {reason}", file=sys.stderr)
        return 1
    except OSError as exc:
        recorder.finish("error", {"code": None, "reason": str(exc)})
        print(f"sem conexão: {exc}", file=sys.stderr)
        return 1
    recorder.finish("seconds")
    return 0


def main() -> None:
    """Lê os argumentos e grava."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_out = Path("gravacoes") / time.strftime("video-%Y%m%d-%H%M%S")
    parser.add_argument("--out", type=Path, default=default_out)
    parser.add_argument("--url", default="ws://localhost:8000/ws/video")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--api-commit", default=None)
    args = parser.parse_args()
    recorder = VideoRecorder(out=args.out, url=args.url, api_commit=args.api_commit)
    code = asyncio.run(record(recorder, args.seconds, args.frames))
    print(f"{recorder.frames} quadros em {args.out}")
    sys.exit(code)


if __name__ == "__main__":
    main()
