"""Tradução de exceções de domínio em respostas HTTP."""

from http import HTTPStatus
from typing import ClassVar

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions import (
    Go2Error,
    InvalidCommandError,
    RobotTimeoutError,
    RobotUnavailableError,
)


class ErrorHandlers:
    """Registra, num único lugar, o status HTTP de cada exceção de domínio.

    Os routers só levantam (ou deixam propagar) exceções de domínio; esta
    classe decide como elas aparecem para o cliente. Para mapear uma exceção
    nova, basta acrescentá-la a `_STATUS`.
    """

    _STATUS: ClassVar[dict[type[Go2Error], HTTPStatus]] = {
        InvalidCommandError: HTTPStatus.UNPROCESSABLE_ENTITY,
        RobotUnavailableError: HTTPStatus.SERVICE_UNAVAILABLE,
        RobotTimeoutError: HTTPStatus.GATEWAY_TIMEOUT,
    }

    @classmethod
    def register(cls, app: FastAPI) -> None:
        """Instala o handler para cada exceção mapeada."""
        for exception_type in cls._STATUS:
            app.add_exception_handler(exception_type, cls._handle)
        app.add_exception_handler(RequestValidationError, cls._handle_validation)

    @classmethod
    async def _handle(cls, _: Request, exc: Exception) -> JSONResponse:
        """Responde `{"detail": <mensagem>}` com o status da exceção."""
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        for exception_type, mapped in cls._STATUS.items():
            if isinstance(exc, exception_type):
                status = mapped
                break
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @classmethod
    async def _handle_validation(cls, _: Request, exc: Exception) -> JSONResponse:
        """Responde 422 sem ecoar o valor recebido.

        O handler padrão devolve `input` e `ctx`, que podem não ser
        serializáveis em JSON (`nan`, `inf`) e transformariam o 422 em 500.
        """
        if not isinstance(exc, RequestValidationError):
            raise exc
        errors = [
            {key: value for key, value in error.items() if key not in {"input", "ctx"}}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content={"detail": jsonable_encoder(errors)},
        )
