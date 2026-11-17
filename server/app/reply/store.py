"""Respostas prontas (ou "sem resposta"), por `utterance_id`, para o long-poll.

- prazo (`deadline_s`, 10 s na spec): contado da criação, que é a hora da
  resposta ao `/v1/utterance`. WAV que fica pronto depois é descartado.
- validade (`ttl_s`, 30 s): depois disso o registro some e o GET dá 404.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Entry:
    created: float
    done: asyncio.Event = field(default_factory=asyncio.Event)
    wav: bytes | None = None


@dataclass(frozen=True)
class WaitResult:
    found: bool  # False = id desconhecido ou expirado (404)
    wav: bytes | None = None  # None com found=True = sem resposta (204)


class ReplyStore:
    def __init__(
        self, deadline_s: float, ttl_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.deadline_s = deadline_s
        self.ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    def _forget_expired(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._entries.items() if now - e.created > self.ttl_s]:
            del self._entries[key]

    def create(self, utterance_id: str) -> None:
        self._forget_expired()
        self._entries.setdefault(utterance_id, _Entry(self._clock()))

    def remaining_s(self, utterance_id: str) -> float:
        entry = self._entries.get(utterance_id)
        if entry is None:
            return 0.0
        return max(0.0, self.deadline_s - (self._clock() - entry.created))

    def finish(self, utterance_id: str, wav: bytes | None) -> bool:
        """Grava o resultado. False se ele chegou tarde (descartado) ou o id sumiu."""
        entry = self._entries.get(utterance_id)
        if entry is None or entry.done.is_set():
            return False
        late = self._clock() - entry.created > self.deadline_s
        entry.wav = None if late else wav
        entry.done.set()
        return not late

    async def wait(self, utterance_id: str) -> WaitResult:
        self._forget_expired()
        entry = self._entries.get(utterance_id)
        if entry is None:
            return WaitResult(found=False)
        remaining = self.deadline_s - (self._clock() - entry.created)
        if not entry.done.is_set() and remaining > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(entry.done.wait(), timeout=remaining)
        if not entry.done.is_set():
            # Passou do prazo sem resultado: fica "sem resposta" até expirar.
            entry.done.set()
        return WaitResult(found=True, wav=entry.wav)
