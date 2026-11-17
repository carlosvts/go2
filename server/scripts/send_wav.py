"""Envia uma frase ao servidor, para testar sem a TV Box.

    uv run python scripts/send_wav.py frase.wav
    uv run python scripts/send_wav.py --say "hey jarvis senta"
    uv run python scripts/send_wav.py --cancel stop

`--say` sintetiza a frase (Piper se houver voz em models/piper, senão espeak-ng; e sox).

E-002: se a resposta vier com `reply_pending: true` (status `thinking`, ou
`enqueued` na frase mista), o script busca a resposta falada em
GET /v1/reply/{utterance_id} e salva o WAV em `--reply-out`.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tts import synthesize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("wav", nargs="?", type=Path, help="WAV mono 16 kHz PCM16")
    parser.add_argument("--say", help="sintetiza esta frase em vez de ler um arquivo")
    parser.add_argument("--cancel", choices=["stop"], help="chama /v1/cancel")
    parser.add_argument("--server", default="http://127.0.0.1:9000")
    parser.add_argument("--edge-id", default="send-wav")
    parser.add_argument("--reason", default="wake_word", help="padrão: wake_word, como a TV Box")
    parser.add_argument("--utterance-id", help="padrão: um UUID novo")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--reply-out", type=Path, default=Path("reply.wav"), help="onde salvar a resposta falada"
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.server, timeout=args.timeout) as client:
        if args.cancel:
            response = client.post(
                "/v1/cancel", json={"edge_id": args.edge_id, "reason": args.cancel}
            )
            print(response.status_code, response.text)
            return 0 if response.is_success else 1

        if args.say:
            audio = synthesize(args.say)
        elif args.wav:
            audio = args.wav.read_bytes()
        else:
            parser.error("informe um WAV, --say ou --cancel")
        meta = {
            "utterance_id": args.utterance_id or str(uuid.uuid4()),
            "edge_id": args.edge_id,
            "reason": args.reason,
        }
        started = time.perf_counter()
        response = client.post(
            "/v1/utterance",
            files={"audio": ("utterance.wav", audio, "audio/wav")},
            data={"meta": json.dumps(meta, ensure_ascii=False)},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"HTTP {response.status_code} em {elapsed_ms:.0f} ms")
        try:
            body = response.json()
            print(json.dumps(body, ensure_ascii=False, indent=2))
        except ValueError:
            print(response.text)
            return 1
        if response.is_success and body.get("reply_pending"):
            fetch_reply(client, meta["utterance_id"], args.reply_out)
    return 0 if response.is_success else 1


def fetch_reply(client: httpx.Client, utterance_id: str, out: Path) -> None:
    started = time.perf_counter()
    reply = client.get(f"/v1/reply/{utterance_id}")
    elapsed_ms = (time.perf_counter() - started) * 1000
    if reply.status_code == 200:
        out.write_bytes(reply.content)
        print(f"resposta falada: {len(reply.content)} bytes em {elapsed_ms:.0f} ms → {out}")
    elif reply.status_code == 204:
        print(f"sem resposta falada (204) em {elapsed_ms:.0f} ms")
    else:
        print(f"GET /v1/reply: HTTP {reply.status_code} {reply.text}")


if __name__ == "__main__":
    sys.exit(main())
