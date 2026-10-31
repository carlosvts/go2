"""Formato do envelope das requests esportivas."""

import json
import random
import time
from typing import Any, ClassVar


class SportRequestBuilder:
    """Monta o envelope de request — padrão exigido pelo webrtc_bridge.

    Réplica de `publish_request_new` (`msgs/pub_sub.py` da lib), necessária
    porque a lib não tem "mandar request sem esperar resposta". Por ser cópia,
    pode divergir se a lib mudar o formato.
    """

    _INT32_MODULUS: ClassVar[int] = 2_147_483_648
    _MAX_JITTER: ClassVar[int] = 1000

    @classmethod
    def build(cls, api_id: int, parameter: object = None) -> dict[str, Any]:
        """Monta o envelope de um comando.

        Args:
            api_id: Identificador do comando em `SPORT_CMD`.
            parameter: Argumento do comando. `dict` vira string JSON; `str`
                passa direto, sem duplo encode; `None` vira string vazia.
        """
        # O aninhamento header.identity.{id,api_id} é obrigatório em todos os
        # níveis, e `parameter` é sempre string (vazia se não houver argumento).
        payload: dict[str, Any] = {
            "header": {"identity": {"id": cls._new_id(), "api_id": api_id}},
            "parameter": "",
        }
        if parameter is not None:
            payload["parameter"] = (
                parameter if isinstance(parameter, str) else json.dumps(parameter)
            )
        return payload

    @classmethod
    def _new_id(cls) -> int:
        """Id de correlação que o robô ecoa: epoch em ms dobrado em int32 + jitter."""
        epoch_ms = int(time.time() * 1000)
        return epoch_ms % cls._INT32_MODULUS + random.randint(0, cls._MAX_JITTER)  # noqa: S311
