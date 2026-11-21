"""Quadros de vídeo sintéticos para os testes do `/ws/video` (F-003).

Gerados pelo teste, não vistos no robô: servem para conferir formato,
cores e o caminho dos dados, não a câmera.
"""

import threading
from fractions import Fraction
from typing import Any

import av
import numpy as np
from numpy.typing import NDArray

RED_SQUARE = (100, 200, 160, 260)
"""`(y0, y1, x0, x1)` do quadrado vermelho puro na imagem de teste."""


def sample_image(width: int = 1280, height: int = 720) -> NDArray[np.uint8]:
    """Gradiente suave (RGB) com um quadrado vermelho puro em posição conhecida."""
    xs = np.linspace(0, 255, width, dtype=np.float64)
    ys = np.linspace(0, 255, height, dtype=np.float64)
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[..., 0] = xs[np.newaxis, :].astype(np.uint8)
    image[..., 1] = ys[:, np.newaxis].astype(np.uint8)
    image[..., 2] = 128
    y0, y1, x0, x1 = RED_SQUARE
    if y1 <= height and x1 <= width:
        image[y0:y1, x0:x1] = (255, 0, 0)
    return image


def video_frame(
    image: NDArray[np.uint8] | None = None,
    *,
    width: int = 64,
    height: int = 48,
    time_s: float | None = 1.0,
) -> av.VideoFrame:
    """`av.VideoFrame` RGB, com `frame.time = time_s` (ou sem tempo)."""
    if image is None:
        image = sample_image(width, height)
    frame = av.VideoFrame.from_ndarray(image, format="rgb24")
    if time_s is not None:
        frame.time_base = Fraction(1, 90000)
        frame.pts = round(time_s * 90000)
    return frame


class SpyFrame:
    """Quadro que registra em que thread o `to_ndarray` rodou."""

    def __init__(self, frame: av.VideoFrame, threads: list[int]) -> None:
        """Embrulha `frame` e anota cada chamada em `threads`."""
        self._frame = frame
        self._threads = threads
        self.width = frame.width
        self.height = frame.height
        self.time = frame.time

    def to_ndarray(self, **kwargs: Any) -> Any:
        """Repassa ao quadro real, registrando a thread."""
        self._threads.append(threading.get_ident())
        return self._frame.to_ndarray(**kwargs)


class BrokenFrame:
    """Quadro cuja conversão falha (quadro corrompido)."""

    width = 64
    height = 48
    time = 1.0

    def to_ndarray(self, **kwargs: Any) -> Any:
        """Sempre falha."""
        msg = "quadro corrompido"
        raise ValueError(msg)
