"""Exceções de domínio da go2-api.

Todas herdam de :class:`Go2Error`, o que permite à camada HTTP traduzi-las
em respostas num único ponto (ver :mod:`app.error_handlers`) sem que o
domínio conheça status codes.
"""


class Go2Error(Exception):
    """Base de todas as exceções levantadas pela go2-api."""


class RobotUnavailableError(Go2Error):
    """Não há conexão viva com o robô.

    A API nunca reconecta sozinha no meio de um comando: mascarar um robô
    desligado com um retry silencioso esconde exatamente o problema que o
    operador precisa ver.
    """


class RobotTimeoutError(Go2Error):
    """O robô não respondeu dentro de `GO2_REQUEST_TIMEOUT_S`."""


class InvalidCommandError(Go2Error, ValueError):
    """Um comando foi construído com valores inaceitáveis.

    Levantada pelo próprio objeto de valor na construção (por exemplo,
    :class:`app.robot.commands.MoveCommand`), de modo que um comando inválido
    simplesmente não chega a existir.
    """
