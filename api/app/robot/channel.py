"""Envio de comandos esportivos pelo data channel."""

import asyncio
from typing import Any

from app.exceptions import RobotTimeoutError
from app.robot.envelope import SportRequestBuilder
from app.robot.link import RobotLink
from app.robot.unitree import DATA_CHANNEL_TYPE, RTC_TOPIC, SPORT_CMD


class SportChannel:
    """Despacha comandos esportivos, referidos pelo nome em `SPORT_CMD`.

    Duas formas de envio, com propósitos diferentes:

    - :meth:`send`, sem esperar resposta: caminho padrão. A API responde ao
      *aceitar* o comando, não depois que o robô termina de se mexer. Além
      disso, `pub_sub.publish` aguarda um future que nada cancela por timeout;
      num reenvio a 30Hz, esperar resposta acumularia futures pendentes se o
      robô ficasse mudo.
    - :meth:`request`, aguardando resposta com timeout próprio.
    """

    def __init__(self, link: RobotLink, request_timeout_s: float) -> None:
        """Recebe a conexão e o teto de espera de :meth:`request`."""
        self._link = link
        self._request_timeout_s = request_timeout_s

    def send(self, command_name: str, parameter: object = None) -> None:
        """Envia o comando sem esperar a resposta do robô.

        Raises:
            RobotUnavailableError: se não há conexão viva.
        """
        pub_sub = self._link.ensure_connected()
        # Padrão exigido pelo webrtc_bridge: tópico `rt/api/sport/request` com
        # `type: "req"` — como `msg` (default da lib) o comando não executa.
        pub_sub.publish_without_callback(
            RTC_TOPIC["SPORT_MOD"],
            SportRequestBuilder.build(SPORT_CMD[command_name], parameter),
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
        options: dict[str, Any] = {"api_id": SPORT_CMD[command_name]}
        if parameter is not None:
            options["parameter"] = parameter
        try:
            return await asyncio.wait_for(
                pub_sub.publish_request_new(RTC_TOPIC["SPORT_MOD"], options),
                timeout=self._request_timeout_s,
            )
        except TimeoutError as exc:
            raise RobotTimeoutError(
                f"❌ Robô não respondeu em {self._request_timeout_s}s."
            ) from exc
