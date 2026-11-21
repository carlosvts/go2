"""Erros ativos do robô, vindos do data channel (F-004).

A lib 2.2.0 só imprime as mensagens `errors`, `add_error` e `rm_error`; o
gancho em :mod:`app.robot.unitree` as entrega aqui. Formato, lido no código
da lib (que cita o app oficial): `[timestamp, source, code]`, com `code`
inteiro; `data` é um item só ou uma lista de itens. Não visto no robô.

`None` quer dizer **desconhecido**, nunca "sem erros": é o valor até a
primeira mensagem `errors`/`add_error` da conexão e depois de uma queda.
"""

import logging
import math
import time
from collections.abc import Callable
from typing import Any

from app.robot.connection import ConnectionState
from app.robot.unitree import describe_error

log = logging.getLogger(__name__)

ERRORS_TYPE = "errors"
ADD_ERROR_TYPE = "add_error"
RM_ERROR_TYPE = "rm_error"

_ITEM_LEN = 3

ActiveError = dict[str, Any]
"""Erro ativo, com as chaves de `ActiveErrorItem` (`app/responses/status.py`)."""

ErrorsListener = Callable[[list[ActiveError] | None, float], None]
"""Recebe a lista nova (cópia, ou `None`) e o instante (Unix) da mudança."""


def _source_or_code(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _robot_ts(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class ActiveErrors:
    """Lista dos erros ativos da conexão atual, em ordem de entrada.

    `errors` substitui a lista; `add_error` acrescenta sem duplicar o par
    `(source, code)`; `rm_error` remove o par. Cada mudança avisa os ouvintes.
    """

    def __init__(self, wall_clock: Callable[[], float] = time.time) -> None:
        """Recebe o relógio de parede (`seen_at`)."""
        self._wall_clock = wall_clock
        self._errors: list[ActiveError] | None = None
        self._channel: object = None
        self._listeners: list[ErrorsListener] = []
        self.message_count = 0
        """Mensagens de erro recebidas desde a criação (métricas)."""

    @property
    def current(self) -> list[ActiveError] | None:
        """Cópia da lista atual, ou `None` (desconhecido)."""
        if self._errors is None:
            return None
        return [dict(error) for error in self._errors]

    def subscribe(self, listener: ErrorsListener) -> None:
        """Registra `listener` para cada mudança da lista."""
        self._listeners.append(listener)

    def reset(self, *, notify: bool = False) -> None:
        """Volta a `None` (desconhecido) e esquece o canal.

        Args:
            notify: Avisa os ouvintes se mudou. Na queda é `False`: o
                `/ws/state` manda `errors: null` junto com o `connection`.
        """
        changed = self._errors is not None
        self._errors = None
        self._channel = None
        if notify and changed:
            self._notify()

    def on_connection(self, payload: dict[str, str]) -> None:
        """Fora de `connected`, a lista volta a `None` (sem avisar)."""
        if ConnectionState(payload["state"]) is not ConnectionState.connected:
            self.reset()

    def on_message(self, channel: object, message: dict[str, Any]) -> None:
        """Aplica uma mensagem `errors`/`add_error`/`rm_error` de `channel`.

        Mensagem de um canal diferente do último visto começa a lista do zero
        (conexão nova). Itens malformados são ignorados (log).
        """
        msg_type = message.get("type")
        if msg_type not in {ERRORS_TYPE, ADD_ERROR_TYPE, RM_ERROR_TYPE}:
            return
        self.message_count += 1
        if channel is not self._channel:
            self._errors = None
            self._channel = channel
        items = self._items(message.get("data"))
        if items is None:
            log.warning("Mensagem %s com data malformado: %.200r", msg_type, message)
            return
        before = self._errors
        if msg_type == ERRORS_TYPE:
            self._replace(items)
        elif msg_type == ADD_ERROR_TYPE:
            self._add(items)
        else:
            self._remove(items)
        if self._errors != before:
            self._notify()

    # ─── Regras ────────────────────────────────────────────────────────────

    @staticmethod
    def _items(data: object) -> list[tuple[object, int, int]] | None:
        """Normaliza `data` para `[(ts, source, code)]`; `None` se não é lista."""
        if data is None:
            return []
        if not isinstance(data, list | tuple):
            return None
        if data and not isinstance(data[0], list | tuple):
            data = [data]
        items: list[tuple[object, int, int]] = []
        for item in data:
            if not isinstance(item, list | tuple) or len(item) != _ITEM_LEN:
                log.warning("Item de erro malformado: %.200r", item)
                continue
            source, code = _source_or_code(item[1]), _source_or_code(item[2])
            if source is None or code is None:
                log.warning("Item de erro malformado: %.200r", item)
                continue
            items.append((item[0], source, code))
        return items

    def _entry(self, robot_ts: object, source: int, code: int) -> ActiveError:
        source_text, code_hex, code_text = describe_error(source, code)
        return {
            "source": source,
            "source_text": source_text,
            "code": code,
            "code_hex": code_hex,
            "code_text": code_text,
            "robot_ts": _robot_ts(robot_ts),
            "seen_at": float(self._wall_clock()),
        }

    def _replace(self, items: list[tuple[object, int, int]]) -> None:
        """Fotografia: substitui; o par que já estava mantém o `seen_at`."""
        previous = {(e["source"], e["code"]): e for e in self._errors or []}
        errors: list[ActiveError] = []
        seen: set[tuple[int, int]] = set()
        for robot_ts, source, code in items:
            if (source, code) in seen:
                continue
            seen.add((source, code))
            errors.append(
                previous.get((source, code)) or self._entry(robot_ts, source, code)
            )
        self._errors = errors

    def _add(self, items: list[tuple[object, int, int]]) -> None:
        errors = list(self._errors or [])
        for robot_ts, source, code in items:
            if not any(e["source"] == source and e["code"] == code for e in errors):
                errors.append(self._entry(robot_ts, source, code))
        self._errors = errors

    def _remove(self, items: list[tuple[object, int, int]]) -> None:
        errors = list(self._errors) if self._errors is not None else None
        for _, source, code in items:
            kept = [
                e
                for e in errors or []
                if not (e["source"] == source and e["code"] == code)
            ]
            if errors is None or len(kept) == len(errors):
                log.debug("rm_error de par ausente: (%s, %s).", source, code)
                continue
            errors = kept
        self._errors = errors

    def _notify(self) -> None:
        current = self.current
        now = self._wall_clock()
        for listener in self._listeners:
            try:
                listener(current, now)
            except Exception:
                log.exception("❌ Falha num ouvinte dos erros ativos.")
