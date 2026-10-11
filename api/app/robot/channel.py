"""Envio de comandos pelo data channel."""

import asyncio
from collections.abc import Mapping
from typing import Any

from app.exceptions import RobotTimeoutError
from app.robot.envelope import SportRequestBuilder
from app.robot.link import RobotLink
from app.robot.unitree import (
    DATA_CHANNEL_TYPE,
    OBSTACLES_AVOID_API,
    RTC_TOPIC,
    SPORT_CMD,
)


class ApiChannel:
    """Despacha os comandos de um serviço do robô, referidos pelo nome.

    Cada serviço tem um tópico de request e uma tabela nome → `api_id`; o
    envelope é o mesmo em todos.

    Duas formas de envio, com propósitos diferentes:

    - :meth:`send`, sem esperar resposta: caminho padrão. A API responde ao
      *aceitar* o comando, não depois que o robô termina de se mexer. Além
      disso, `pub_sub.publish` aguarda um future que nada cancela por timeout;
      num reenvio a 30Hz, esperar resposta acumularia futures pendentes se o
      robô ficasse mudo.
    - :meth:`request`, aguardando resposta com timeout próprio.
    """

    def __init__(
        self,
        link: RobotLink,
        request_timeout_s: float,
        *,
        topic: str,
        api_ids: Mapping[str, int],
    ) -> None:
        """Recebe a conexão, o teto de :meth:`request` e o serviço atendido."""
        self._link = link
        self._request_timeout_s = request_timeout_s
        self._topic = topic
        self._api_ids = api_ids

    def send(self, command_name: str, parameter: object = None) -> None:
        """Envia o comando sem esperar a resposta do robô.

        Raises:
            RobotUnavailableError: se não há conexão viva.
        """
        pub_sub = self._link.ensure_connected()
        # Padrão exigido pelo webrtc_bridge: tópico de request com
        # `type: "req"` — como `msg` (default da lib) o comando não executa.
        pub_sub.publish_without_callback(
            self._topic,
            SportRequestBuilder.build(self._api_ids[command_name], parameter),
            DATA_CHANNEL_TYPE["REQUEST"],
        )

    async def request(
        self, command_name: str, parameter: object = None
    ) -> dict[str, Any]:
        """Envia o comando e aguarda a resposta, com timeout próprio.

        Raises:
            RobotUnavailableError: se não há conexão viva.
            RobotTimeoutError: se o robô não responde dentro do teto.
        """
        pub_sub = self._link.ensure_connected()
        options: dict[str, Any] = {"api_id": self._api_ids[command_name]}
        if parameter is not None:
            options["parameter"] = parameter
        try:
            return await asyncio.wait_for(
                pub_sub.publish_request_new(self._topic, options),
                timeout=self._request_timeout_s,
            )
        except TimeoutError as exc:
            raise RobotTimeoutError(
                f"❌ Robô não respondeu em {self._request_timeout_s}s."
            ) from exc


class SportChannel(ApiChannel):
    """Comandos esportivos (`SPORT_CMD`) em `rt/api/sport/request`."""

    def __init__(self, link: RobotLink, request_timeout_s: float) -> None:
        """Recebe a conexão e o teto de espera de :meth:`request`."""
        super().__init__(
            link, request_timeout_s, topic=RTC_TOPIC["SPORT_MOD"], api_ids=SPORT_CMD
        )


class ObstacleAvoidChannel(ApiChannel):
    """Desvio de obstáculo (`OBSTACLES_AVOID_API`), em tópico próprio."""

    def __init__(self, link: RobotLink, request_timeout_s: float) -> None:
        """Recebe a conexão e o teto de espera de :meth:`request`."""
        super().__init__(
            link,
            request_timeout_s,
            topic=RTC_TOPIC["OBSTACLES_AVOID"],
            api_ids=OBSTACLES_AVOID_API,
        )
