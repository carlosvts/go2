"""Leitura tolerante de payloads cujo formato não está fixado."""

from typing import Any


class PayloadReader:
    """Navega em payloads aninhados sem assumir um formato único."""

    @staticmethod
    def first_path(payload: Any, *paths: tuple[str, ...]) -> Any:
        """Devolve o valor do primeiro caminho existente em `payload`, ou `None`.

        O formato exato de `rt/sportmodestate`, `rt/lf/lowstate` e das respostas
        de `GetSpeedLevel` não está fixado em nenhum documento de referência,
        então a extração tenta caminhos plausíveis em vez de assumir um só.
        Campo não reconhecido vira `None` — nunca um valor inventado.

        Args:
            payload: Estrutura lida do robô (normalmente um `dict`).
            *paths: Caminhos candidatos, cada um uma sequência de chaves.
        """
        for path in paths:
            value = PayloadReader._follow(payload, path)
            if value is not None:
                return value
        return None

    @staticmethod
    def _follow(payload: Any, path: tuple[str, ...]) -> Any:
        """Segue `path` em `payload`; `None` se qualquer chave faltar."""
        cursor = payload
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                return None
            cursor = cursor[key]
        return cursor
