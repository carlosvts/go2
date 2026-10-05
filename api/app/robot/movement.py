"""Reenvio periódico do comando `Move`."""

import asyncio
import contextlib
import logging
import time

from app.exceptions import RobotUnavailableError
from app.robot.channel import SportChannel
from app.robot.commands import MoveCommand

log = logging.getLogger(__name__)


class MoveController:
    """Mantém no máximo um movimento em curso.

    O robô trata `Move` como "velocidade desejada por um instante" (watchdog
    interno), então o movimento contínuo exige reenviar o comando em
    frequência fixa até o fim da janela. Sem lease nesta versão: um novo
    movimento cancela o anterior.
    """

    def __init__(self, channel: SportChannel, rate_hz: float) -> None:
        """Recebe o canal de envio e a frequência de reenvio, em Hz."""
        self._channel = channel
        self._interval_s = 1.0 / rate_hz
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Há um movimento em curso."""
        return self._task is not None and not self._task.done()

    async def start(self, move: MoveCommand) -> None:
        """Cancela o movimento anterior, dispara `Move` e agenda o reenvio."""
        await self.cancel()
        self._channel.send("Move", move.parameter)
        self._task = asyncio.create_task(self._resend(move))

    async def cancel(self) -> None:
        """Interrompe o reenvio em curso, se houver. Não envia `StopMove`."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _resend(self, move: MoveCommand) -> None:
        """Reenvia `Move` até o fim da janela e então para explicitamente."""
        deadline = time.monotonic() + move.duration_s
        parameter = move.parameter
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(self._interval_s)
                self._channel.send("Move", parameter)
        except RobotUnavailableError:
            log.warning("❌ Conexão caiu durante o movimento — loop encerrado.")
            return
        except Exception:
            log.exception("❌ Falha no loop de movimento.")
            return
        # Fim da janela: para explicitamente em vez de depender do watchdog
        # interno do robô.
        with contextlib.suppress(RobotUnavailableError):
            self._channel.send("StopMove")
