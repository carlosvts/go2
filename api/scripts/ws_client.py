"""Cliente de linha de comando para inspecionar os streams WebSocket da API.

Conecta numa URL ``ws://``/``wss://``, imprime cada mensagem recebida e mostra a
taxa (msgs/s) a cada ``--every`` segundos. Ferramenta de desenvolvimento: não
reconecta e não decodifica quadros binários (só mostra o tamanho).

Se a mensagem for um envelope JSON com ``ts`` (segundos desde a época, como
``time.time()``), mostra a latência ``time.time() - ts``. Ela só faz sentido com
cliente e servidor na mesma máquina ou com os relógios sincronizados. Se o
``data`` do envelope tiver um ``seq`` inteiro, conta os buracos na sequência
(mensagens descartadas).

Uso:
    uv run python scripts/ws_client.py ws://127.0.0.1:8000/ws/telemetry
    uv run python scripts/ws_client.py --summary --every 5 ws://.../ws/telemetry

Códigos de saída: ``0`` ao encerrar com Ctrl+C, ``1`` se a conexão falhar ou o
servidor fechá-la, ``2`` para argumentos inválidos.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosedError, InvalidHandshake, InvalidURI

WS_SCHEMES = ("ws", "wss")


def out(text: str) -> None:
    """Imprime já descarregando o buffer, para funcionar também com pipe."""
    print(text, flush=True)


def err(text: str) -> None:
    """Imprime no stderr."""
    print(text, file=sys.stderr, flush=True)


@dataclass
class Window:
    """Contagens de uma janela de ``--every`` segundos."""

    started: float
    count: int = 0
    latency_sum: float = 0.0
    latency_count: int = 0


@dataclass
class Stats:
    """Contagens acumuladas desde a conexão."""

    started: float = field(default_factory=time.monotonic)
    total: int = 0
    binary: int = 0
    gaps: int = 0
    last_seq: int | None = None
    latency_sum: float = 0.0
    latency_count: int = 0
    window: Window = field(default_factory=lambda: Window(time.monotonic()))

    def start(self) -> None:
        """Zera o relógio: a duração e a taxa contam a partir da conexão."""
        self.started = time.monotonic()
        self.window = Window(self.started)

    def record(self, latency: float | None, seq: int | None) -> None:
        """Conta uma mensagem, com a latência e o ``seq`` dela, se houver."""
        self.total += 1
        self.window.count += 1
        if latency is not None:
            self.latency_sum += latency
            self.latency_count += 1
            self.window.latency_sum += latency
            self.window.latency_count += 1
        if seq is not None:
            if self.last_seq is not None and seq > self.last_seq + 1:
                self.gaps += seq - self.last_seq - 1
            # `seq` menor ou igual ao anterior: o servidor recomeçou a contagem.
            self.last_seq = seq

    def report(self) -> str:
        """Fecha a janela atual e devolve a linha de taxa dela."""
        now = time.monotonic()
        window, self.window = self.window, Window(now)
        rate = window.count / max(now - window.started, 1e-9)
        parts = [f"{rate:.1f} msgs/s", f"total {self.total}"]
        if self.last_seq is not None:
            parts.append(f"buracos no seq {self.gaps}")
        if window.latency_count:
            mean_ms = window.latency_sum / window.latency_count * 1000
            parts.append(f"latência média {mean_ms:.1f} ms")
        return f"[{now - self.started:7.1f}s] " + " | ".join(parts)

    def summary(self) -> str:
        """Resumo final: total, duração e média."""
        duration = time.monotonic() - self.started
        mean = self.total / duration if duration > 0 else 0.0
        lines = [
            "resumo:",
            f"mensagens: {self.total} ({self.binary} binárias)",
            f"duração:   {duration:.1f} s",
            f"média:     {mean:.1f} msgs/s",
        ]
        if self.last_seq is not None:
            lines.append(f"buracos no seq: {self.gaps}")
        if self.latency_count:
            mean_ms = self.latency_sum / self.latency_count * 1000
            lines.append(f"latência média: {mean_ms:.1f} ms (exige relógios iguais)")
        return "\n".join(lines)


def inspect(text: str) -> tuple[float | None, int | None]:
    """Extrai a latência (de ``ts``) e o ``data.seq`` de um envelope JSON."""
    try:
        envelope: object = json.loads(text)
    except ValueError:
        return None, None
    if not isinstance(envelope, dict):
        return None, None

    latency = None
    ts = envelope.get("ts")
    if isinstance(ts, int | float) and not isinstance(ts, bool):
        latency = time.time() - ts

    seq = None
    data = envelope.get("data")
    if isinstance(data, dict):
        value = data.get("seq")
        if isinstance(value, int) and not isinstance(value, bool):
            seq = value
    return latency, seq


async def report_every(stats: Stats, every: float) -> None:
    """Imprime a taxa a cada ``every`` segundos, até ser cancelada."""
    while True:
        await asyncio.sleep(every)
        out(stats.report())


async def consume(ws: ClientConnection, stats: Stats, *, quiet: bool) -> None:
    """Lê as mensagens até o servidor fechar a conexão."""
    async for message in ws:
        if isinstance(message, bytes):
            stats.binary += 1
            stats.record(None, None)
            if not quiet:
                out(f"<binário {len(message)} bytes>")
            continue
        stats.record(*inspect(message))
        if not quiet:
            out(message)


async def run(url: str, stats: Stats, *, every: float, quiet: bool) -> int:
    """Conecta, consome o stream e devolve o código de saída."""
    try:
        async with connect(url) as ws:
            out(f"conectado a {url}")
            stats.start()
            reporter = asyncio.create_task(report_every(stats, every))
            try:
                await consume(ws, stats, quiet=quiet)
            except ConnectionClosedError:
                pass  # fechamento anormal; o código e o motivo estão em `ws`
            finally:
                reporter.cancel()
            reason = ws.close_reason or "sem motivo"
            err(f"servidor fechou a conexão: código {ws.close_code} ({reason})")
    except (OSError, InvalidHandshake, InvalidURI, TimeoutError) as exc:
        err(f"falha ao conectar em {url}: {exc}")
        return 1
    out(stats.summary())
    return 1


def positive(value: str) -> float:
    """Converte ``--every`` e exige um número maior que zero."""
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("precisa ser maior que zero")
    return number


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Lê e valida os argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Conecta num WebSocket da API, imprime as mensagens e a taxa.",
    )
    parser.add_argument("url", help="ex.: ws://127.0.0.1:8000/ws/telemetry")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="não imprime as mensagens, só a taxa e o resumo",
    )
    parser.add_argument(
        "--every",
        type=positive,
        default=1.0,
        metavar="N",
        help="intervalo em segundos entre as linhas de taxa (padrão: 1)",
    )
    args = parser.parse_args(argv)

    scheme = urlsplit(args.url).scheme
    if scheme not in WS_SCHEMES:
        hint = ""
        if scheme in ("http", "https"):
            fixed = "ws" if scheme == "http" else "wss"
            hint = f"; troque {scheme}:// por {fixed}://"
        parser.error(f"a URL precisa começar com ws:// ou wss://{hint}")
    return args


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada; Ctrl+C encerra com o resumo e código 0."""
    # Com saída redirecionada no Windows (cp1252), um caractere fora da página
    # de código derrubaria o script; melhor trocá-lo por `?`.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")

    args = parse_args(argv)
    stats = Stats()
    try:
        return asyncio.run(
            run(args.url, stats, every=args.every, quiet=args.summary),
        )
    except KeyboardInterrupt:
        out("\ninterrompido (Ctrl+C)")
        out(stats.summary())
        return 0


if __name__ == "__main__":
    sys.exit(main())
