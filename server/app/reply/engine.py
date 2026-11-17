"""Gera a resposta de uma frase de conversa e a deixa no `ReplyStore`.

Uma geração por vez: se chegar outra com uma em curso, a nova fica "sem
resposta" na hora (spec E-002). Tudo em segundo plano: quem chama `start` não
espera nada, e o `/v1/utterance` responde na hora.
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from app.reply.echo import EchoFilter
from app.reply.store import ReplyStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Generation:
    text: str
    tokens: int | None = None


class Llm(Protocol):
    async def health(self, timeout_s: float) -> bool: ...

    async def generate(self, text: str, timeout_s: float) -> Generation: ...


class Synthesizer(Protocol):
    def synthesize(self, text: str) -> bytes: ...


class ReplyEngine:
    def __init__(self, llm: Llm, tts: Synthesizer, echo: EchoFilter, store: ReplyStore) -> None:
        self.llm = llm
        self.tts = tts
        self.echo = echo
        self.store = store
        self._busy = False
        self._tasks: set[asyncio.Task] = set()

    def start(self, utterance_id: str, text: str) -> None:
        """Abre o registro da resposta e dispara a geração, sem esperar."""
        self.store.create(utterance_id)
        if self._busy:
            self.store.finish(utterance_id, None)
            self._log(utterance_id, text, outcome="busy")
            return
        self._busy = True
        task = asyncio.create_task(self._run(utterance_id, text))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, utterance_id: str, text: str) -> None:
        started = time.monotonic()
        record: dict = {}
        wav: bytes | None = None
        outcome = "error"
        try:
            timeout = self.store.remaining_s(utterance_id)
            generation = await asyncio.wait_for(
                self.llm.generate(text, timeout), timeout=max(timeout, 0.001)
            )
            generated = time.monotonic()
            final, reason = await asyncio.to_thread(self.echo.check, generation.text)
            checked = time.monotonic()
            wav = await asyncio.to_thread(self.tts.synthesize, final)
            done = time.monotonic()
            record = {
                "llm_text": generation.text,
                "llm_tokens": generation.tokens,
                "reply_text": final,
                "echo_filter": reason,
                "llm_ms": round((generated - started) * 1000, 1),
                "echo_ms": round((checked - generated) * 1000, 1),
                "tts_ms": round((done - checked) * 1000, 1),
                "wav_bytes": len(wav),
            }
            outcome = "ready"
        except TimeoutError:
            outcome = "timeout"
        except Exception as error:  # Llama ou Piper falharam: sem resposta
            record["error"] = repr(error)
        finally:
            self._busy = False
        if not self.store.finish(utterance_id, wav) and outcome == "ready":
            outcome = "late"
        record["total_ms"] = round((time.monotonic() - started) * 1000, 1)
        self._log(utterance_id, text, outcome=outcome, **record)

    def _log(self, utterance_id: str, text: str, **fields) -> None:
        log.info(
            "llm_reply %s",
            fields.get("outcome"),
            extra={"event": "llm_reply", "utterance_id": utterance_id, "llm_input": text, **fields},
        )

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
