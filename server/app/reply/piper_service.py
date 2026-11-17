"""Piper num processo separado do go2-server (E-002).

O go2-server divide a CPU com a go2-api (que reenvia o `Move` a 40 Hz) e
interpreta a fala seguinte, inclusive a parada. A síntese roda aqui, num
processo (e container) próprio com teto de CPU, e o go2-server só faz HTTP.

    uv run --extra llm python -m app.reply.piper_service \\
        --voice models/piper/pt_BR-faber-medium.onnx --port 5002

    GET  /health       200 quando a voz carregou
    POST /synthesize   JSON {"text": "..."} → audio/wav (com silêncio inicial)

Uma síntese por vez (servidor de uma thread só): é o mesmo limite do Llama.
"""

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 500  # a resposta tem no máximo 32 tokens; acima disto é erro


class _Synth(Protocol):
    def synthesize(self, text: str) -> bytes: ...


def make_server(synth: _Synth, host: str, port: int) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._reply(200 if self.path == "/health" else 404, b"", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/synthesize":
                self._reply(404, b"", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                text = str(json.loads(self.rfile.read(length))["text"]).strip()
            except (ValueError, KeyError, TypeError):
                self._reply(422, b'JSON {"text": ...}', "text/plain")
                return
            if not text or len(text) > MAX_TEXT_CHARS:
                self._reply(422, b"texto vazio ou longo demais", "text/plain")
                return
            try:
                wav = synth.synthesize(text)
            except Exception as error:  # a voz falhou: o go2-server vira "sem resposta"
                log.exception("síntese falhou")
                self._reply(500, repr(error).encode(), "text/plain")
                return
            self._reply(200, wav, "audio/wav")

        def _reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            log.debug(format, *args)

    return HTTPServer((host, port), Handler)


def main() -> None:
    from app.reply.tts import PiperSynthesizer

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--voice", type=Path, required=True, help=".onnx do Piper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--lead-silence-ms", type=int, default=250)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    synth = PiperSynthesizer(args.voice, args.lead_silence_ms)
    server = make_server(synth, args.host, args.port)
    log.info("piper pronto em %s:%d (voz %s)", args.host, args.port, args.voice.name)
    server.serve_forever()


if __name__ == "__main__":
    main()
