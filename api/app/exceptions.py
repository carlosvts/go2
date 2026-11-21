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


class RobotRejectedError(Go2Error):
    """O robô respondeu, mas recusou o pedido ou mandou algo ilegível.

    Código ≠ 0 em `header.status`, resposta sem `header.status`, ou leitura
    sem o campo esperado. Vira `502`. O estado do robô fica desconhecido: o
    pedido pode ter sido aplicado.
    """


class InvalidCommandError(Go2Error, ValueError):
    """Um comando foi construído com valores inaceitáveis.

    Levantada pelo próprio objeto de valor na construção (por exemplo,
    :class:`app.robot.commands.MoveCommand`), de modo que um comando inválido
    simplesmente não chega a existir.
    """


class PayloadTooLargeError(Go2Error):
    """O upload passou de `GO2_AUDIO_MAX_UPLOAD_MB`; vira `413`.

    A leitura é interrompida no limite: o resto do corpo não é lido.
    """


class UnsupportedAudioError(Go2Error):
    """O arquivo não é WAV nem MP3 (pelo conteúdo) ou não decodifica; vira `415`."""


class NotFoundError(Go2Error):
    """O recurso pedido não existe na api (ex.: `upload_id` esquecido). Vira `404`."""


class ConflictError(Go2Error):
    """O pedido conflita com o estado atual (envio em andamento, nome repetido).

    Vira `409`.
    """


UnsupportedMediaError = UnsupportedAudioError
"""Nome usado pela F-006; mesma exceção da F-007 (`415`)."""
