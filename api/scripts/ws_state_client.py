"""Cliente de diagnóstico do `/ws/state` (F-004, roteiro da rodada).

Conecta e imprime, a cada segundo, quantos frames de cada tópico chegaram e o
último `data` de `errors`, `connection`, `speaker` e `audio_player` quando
mudam.

Uso:
    uv run python scripts/ws_state_client.py [--url ws://localhost:8000/ws/state]
        [--seconds 60] [--show-data]
"""

import argparse
import asyncio
import json
import time
from collections import Counter

import websockets

ALWAYS_SHOWN = {"connection", "errors", "speaker", "audio_player"}


async def run(url: str, seconds: float, *, show_data: bool) -> None:
    """Lê o stream por `seconds` e imprime a contagem por tópico."""
    counts: Counter[str] = Counter()
    window = time.monotonic()
    end = window + seconds
    async with websockets.connect(url) as ws:
        while time.monotonic() < end:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except TimeoutError:
                message = None
            if isinstance(message, str):
                frame = json.loads(message)
                topic = frame.get("topic", "?")
                counts[topic] += 1
                if show_data or topic in ALWAYS_SHOWN:
                    print(f"{topic}: {json.dumps(frame.get('data'))[:300]}")
            now = time.monotonic()
            if now - window >= 1.0:
                elapsed = now - window
                rates = ", ".join(
                    f"{topic} {n / elapsed:.1f}/s"
                    for topic, n in sorted(counts.items())
                )
                print(f"[{elapsed:.1f} s] {rates or 'nenhum frame'}")
                counts.clear()
                window = now


def main() -> None:
    """Lê os argumentos e roda o cliente."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://localhost:8000/ws/state")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--show-data", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.seconds, show_data=args.show_data))


if __name__ == "__main__":
    main()
