"""Saúde do llama-server, consultada em segundo plano (E-002, F6).

O caminho do `/v1/utterance` só lê o último estado: nunca espera o llama-server.
Um llama-server travado não pode segurar a resposta, porque a TV Box fica em
SENDING (wake word ignorada, inclusive a da parada) até ela chegar.
"""

import asyncio
import logging
from contextlib import suppress

from app.reply.engine import Llm

log = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(self, llm: Llm, interval_s: float, timeout_s: float) -> None:
        self._llm = llm
        self._interval_s = interval_s
        self._timeout_s = timeout_s
        self.healthy = False
        self._task: asyncio.Task | None = None

    async def check(self) -> bool:
        try:
            healthy = await asyncio.wait_for(
                self._llm.health(self._timeout_s), timeout=self._timeout_s
            )
        except (TimeoutError, Exception):
            healthy = False
        if healthy != self.healthy:
            log.info(
                "llama-server %s",
                "no ar" if healthy else "fora do ar",
                extra={"event": "llm_health", "healthy": healthy},
            )
        self.healthy = healthy
        return healthy

    async def start(self) -> None:
        await self.check()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            await self.check()

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
