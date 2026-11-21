"""Cliente de diagnóstico do `/ws/video` (F-003, roteiro H1).

Conecta, valida o cabeçalho, decodifica cada JPEG e imprime, a cada segundo:
frames/s, bytes/quadro (mín./médio/máx.), resolução, JPEGs que não
decodificaram, buracos no `seq`, atraso `received_at − ts` e intervalo de
`media_time`. Imprime também as transições de `connection` e `video`.

Uso:
    uv run python scripts/ws_video_client.py [--url ws://localhost:8000/ws/video]
        [--seconds 60]

Os buracos no `seq` se cruzam com a linha `video_metrics` do log da api, que
diz em que fila cada quadro foi descartado.
"""

import argparse
import asyncio
import json
import math
import struct
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
import websockets

HEADER = struct.Struct("<BBHIdHHId")
FRAME_VERSION = 1
MAX_FRAME_BYTES = 16 * 1024 * 1024
"""O padrão do `websockets` (1 MiB) pode cortar um JPEG grande."""


@dataclass(frozen=True)
class VideoHeader:
    """Cabeçalho v1 de um frame do `/ws/video` (ver `ws-video.md`)."""

    seq: int
    ts: float
    width: int
    height: int
    jpeg_len: int
    media_time: float
    header_len: int


def parse_frame(frame: bytes) -> VideoHeader:
    """Valida e desmonta o cabeçalho.

    Raises:
        ValueError: versão desconhecida ou tamanho que não bate.
    """
    version, _flags, header_len, seq, ts, width, height, jpeg_len, media_time = (
        HEADER.unpack_from(frame, 0)
    )
    if version != FRAME_VERSION:
        msg = f"versão desconhecida: {version}"
        raise ValueError(msg)
    if len(frame) != header_len + jpeg_len:
        msg = f"tamanho {len(frame)} não bate com jpeg_len={jpeg_len}"
        raise ValueError(msg)
    return VideoHeader(seq, ts, width, height, jpeg_len, media_time, header_len)


def jpeg_decodes(frame: bytes, header: VideoHeader) -> bool:
    """O JPEG decodifica na resolução do cabeçalho."""
    body = np.frombuffer(frame, np.uint8, offset=header.header_len)
    image = cv2.imdecode(body, cv2.IMREAD_COLOR)
    return image is not None and image.shape[:2] == (header.height, header.width)


@dataclass
class Stats:
    """Acumula as métricas de uma janela de um segundo."""

    frames: int = 0
    sizes: list[int] = field(default_factory=list)
    resolutions: set[tuple[int, int]] = field(default_factory=set)
    undecodable: int = 0
    gaps: int = 0
    delays: list[float] = field(default_factory=list)
    media_intervals: list[float] = field(default_factory=list)
    last_seq: int | None = None
    last_media_time: float | None = None

    def add(
        self, header: VideoHeader, size: int, received_at: float, *, ok: bool
    ) -> None:
        """Conta um frame, detecta buraco no `seq` e mede os intervalos."""
        if self.last_seq is not None:
            self.gaps += (header.seq - self.last_seq - 1) & 0xFFFFFFFF
        self.last_seq = header.seq
        if not math.isnan(header.media_time):
            if self.last_media_time is not None:
                self.media_intervals.append(header.media_time - self.last_media_time)
            self.last_media_time = header.media_time
        self.frames += 1
        self.sizes.append(size)
        self.resolutions.add((header.width, header.height))
        self.delays.append(received_at - header.ts)
        if not ok:
            self.undecodable += 1

    def next_window(self) -> "Stats":
        """Janela nova que continua a contagem de buracos e intervalos."""
        return Stats(last_seq=self.last_seq, last_media_time=self.last_media_time)

    def report(self, elapsed: float) -> str:
        """Linha de resumo da janela."""
        if not self.frames:
            return f"{0:5.1f} frames/s (nenhum frame)"
        kib = [s / 1024 for s in self.sizes]
        res = ", ".join(f"{w}x{h}" for w, h in sorted(self.resolutions))
        delay = sum(self.delays) / len(self.delays) * 1000
        media = (
            f"{sum(self.media_intervals) / len(self.media_intervals) * 1000:.1f} ms"
            if self.media_intervals
            else "—"
        )
        return (
            f"{self.frames / elapsed:5.1f} frames/s | {res} | KiB "
            f"{min(kib):.1f}/{sum(kib) / len(kib):.1f}/{max(kib):.1f} | "
            f"não decodificaram: {self.undecodable} | buracos no seq: {self.gaps} | "
            f"atraso médio {delay:.0f} ms | intervalo media_time {media}"
        )


async def run(url: str, seconds: float) -> None:
    """Lê o stream por `seconds` e imprime as métricas."""
    stats = Stats()
    window = time.monotonic()
    end = window + seconds
    async with websockets.connect(url, max_size=MAX_FRAME_BYTES) as ws:
        while time.monotonic() < end:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except TimeoutError:
                message = None
            if isinstance(message, str):
                text = json.loads(message)
                print(f"{text['topic']}: {text['data']['state']}")
            elif isinstance(message, bytes):
                received_at = time.time()
                header = parse_frame(message)
                ok = jpeg_decodes(message, header)
                stats.add(header, len(message), received_at, ok=ok)
            now = time.monotonic()
            if now - window >= 1.0:
                print(stats.report(now - window))
                stats = stats.next_window()
                window = now


def main() -> None:
    """Lê os argumentos e roda o cliente."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://localhost:8000/ws/video")
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.seconds))


if __name__ == "__main__":
    main()
