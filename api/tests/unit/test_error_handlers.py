"""Testes de `ErrorHandlers`: tradução de exceções em respostas HTTP."""

import json
import math
from http import HTTPStatus
from typing import Any

import pytest
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from app.error_handlers import ErrorHandlers
from app.exceptions import (
    Go2Error,
    InvalidCommandError,
    RobotTimeoutError,
    RobotUnavailableError,
)


class _CustomTimeoutError(RobotTimeoutError):
    """Subclasse não registrada: deve herdar o status da classe mapeada."""


@pytest.fixture
def request_stub() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _body(response: Any) -> Any:
    return json.loads(response.body)


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (InvalidCommandError("vx fora do limite"), HTTPStatus.UNPROCESSABLE_ENTITY),
        (RobotUnavailableError("sem conexão"), HTTPStatus.SERVICE_UNAVAILABLE),
        (RobotTimeoutError("sem resposta"), HTTPStatus.GATEWAY_TIMEOUT),
    ],
)
async def test_excecao_mapeada_vira_o_status_configurado(
    request_stub: Request, exc: Go2Error, status: HTTPStatus
) -> None:
    resposta = await ErrorHandlers._handle(request_stub, exc)

    assert resposta.status_code == status
    assert _body(resposta) == {"detail": str(exc)}


async def test_subclasse_de_excecao_mapeada_herda_o_status(
    request_stub: Request,
) -> None:
    resposta = await ErrorHandlers._handle(request_stub, _CustomTimeoutError("lento"))

    assert resposta.status_code == HTTPStatus.GATEWAY_TIMEOUT


@pytest.mark.parametrize("exc", [Go2Error("genérico"), RuntimeError("inesperado")])
async def test_excecao_sem_mapeamento_vira_500(
    request_stub: Request, exc: Exception
) -> None:
    resposta = await ErrorHandlers._handle(request_stub, exc)

    assert resposta.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert _body(resposta) == {"detail": str(exc)}


async def test_validacao_nao_ecoa_input_nem_ctx(request_stub: Request) -> None:
    exc = RequestValidationError(
        [
            {
                "type": "finite_number",
                "loc": ("body", "vx"),
                "msg": "Input should be a finite number",
                "input": math.nan,
                "ctx": {"detalhe": object()},
            }
        ]
    )

    resposta = await ErrorHandlers._handle_validation(request_stub, exc)

    assert resposta.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resposta) == {
        "detail": [
            {
                "type": "finite_number",
                "loc": ["body", "vx"],
                "msg": "Input should be a finite number",
            }
        ]
    }


async def test_validacao_preserva_todos_os_erros(request_stub: Request) -> None:
    exc = RequestValidationError(
        [
            {"type": "missing", "loc": ("body", "vx"), "msg": "Field required"},
            {"type": "missing", "loc": ("body", "vy"), "msg": "Field required"},
        ]
    )

    resposta = await ErrorHandlers._handle_validation(request_stub, exc)

    assert [e["loc"] for e in _body(resposta)["detail"]] == [
        ["body", "vx"],
        ["body", "vy"],
    ]


async def test_validacao_sem_erros_devolve_lista_vazia(request_stub: Request) -> None:
    resposta = await ErrorHandlers._handle_validation(
        request_stub, RequestValidationError([])
    )

    assert resposta.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resposta) == {"detail": []}


async def test_validacao_repassa_excecao_de_outro_tipo(request_stub: Request) -> None:
    """Guarda defensiva: o handler só sabe tratar `RequestValidationError`."""
    with pytest.raises(RuntimeError, match="não é de validação"):
        await ErrorHandlers._handle_validation(
            request_stub, RuntimeError("não é de validação")
        )
