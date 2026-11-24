"""Testes de `/device/*`: lanterna, LED e volume pelo tópico VUI (F-005)."""

import asyncio
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.robot.unitree import RTC_TOPIC, SPORT_CMD
from tests.fakes import FakeConnectionFactory, FakePubSub

OK: dict[str, Any] = {"data": {"header": {"status": {"code": 0}}, "data": ""}}


def _resposta(code: int = 0, data: object = "") -> dict[str, Any]:
    """Resposta do robô no formato do exemplo `vui.py`."""
    return {"data": {"header": {"status": {"code": code}}, "data": data}}


def _vui(pub_sub: FakePubSub) -> list[dict[str, Any]]:
    return [msg for msg in pub_sub.sent if msg["topic"] == RTC_TOPIC["VUI"]]


@pytest.fixture
def capped_client(
    settings: Settings, factory: FakeConnectionFactory
) -> Iterator[TestClient]:
    """Cliente com tetos abaixo de 10, como quem distribui configuraria."""
    capped = settings.model_copy(
        update={"max_volume": 6, "max_brightness": 4, "led_max_duration_s": 5}
    )
    with TestClient(create_app(capped, connection_factory=factory)) as test_client:
        yield test_client


@pytest.fixture
def slow_client(
    settings: Settings, factory: FakeConnectionFactory
) -> Iterator[TestClient]:
    """Cliente com timeout folgado, para segurar um pedido VUI pendente."""
    slow = settings.model_copy(update={"request_timeout_s": 5.0})
    with TestClient(create_app(slow, connection_factory=factory)) as test_client:
        yield test_client


# ─── A1: tópico, api_id e parameter ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "corpo", "options"),
    [
        (
            "/device/brightness",
            {"level": 7},
            {"api_id": 1005, "parameter": {"brightness": 7}},
        ),
        ("/device/volume", {"level": 3}, {"api_id": 1003, "parameter": {"volume": 3}}),
        (
            "/device/led",
            {"color": "red", "duration_s": 5},
            {"api_id": 1007, "parameter": {"color": "red", "time": 5}},
        ),
        (
            "/device/led",
            {"color": "cyan", "duration_s": 3, "flash_cycle_ms": 1000},
            {
                "api_id": 1007,
                "parameter": {"color": "cyan", "time": 3, "flash_cycle": 1000},
            },
        ),
    ],
)
def test_a1_put_publica_api_id_e_parameter_no_topico_vui(
    client: TestClient,
    pub_sub: FakePubSub,
    url: str,
    corpo: dict[str, Any],
    options: dict[str, Any],
) -> None:
    pub_sub.response = OK

    resposta = client.put(url, json=corpo)

    assert resposta.status_code == 202
    (enviado,) = pub_sub.sent
    assert enviado["topic"] == RTC_TOPIC["VUI"] == "rt/api/vui/request"
    # `publish_request_new` (espera resposta), com `parameter` como dict.
    assert enviado["type"] == "req"
    assert enviado["options"] == options


def test_a1_led_sem_flash_cycle_nao_manda_flash_cycle(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.response = OK

    client.put("/device/led", json={"color": "white", "duration_s": 2})

    assert "flash_cycle" not in pub_sub.sent[0]["options"]["parameter"]


@pytest.mark.parametrize(
    ("url", "api_id", "campo"),
    [("/device/brightness", 1006, "brightness"), ("/device/volume", 1004, "volume")],
)
def test_a1_get_publica_api_id_sem_parameter(
    client: TestClient, pub_sub: FakePubSub, url: str, api_id: int, campo: str
) -> None:
    pub_sub.response = _resposta(data=json.dumps({campo: 4}))

    resposta = client.get(url)

    assert resposta.status_code == 200
    (enviado,) = pub_sub.sent
    assert enviado["topic"] == RTC_TOPIC["VUI"]
    assert enviado["options"] == {"api_id": api_id}


@pytest.mark.parametrize(
    ("url", "corpo"),
    [
        ("/device/brightness", {"level": 0}),
        ("/device/volume", {"level": 10}),
    ],
)
def test_a1_put_de_nivel_devolve_o_nivel(
    client: TestClient, pub_sub: FakePubSub, url: str, corpo: dict[str, Any]
) -> None:
    pub_sub.response = OK

    assert client.put(url, json=corpo).json() == corpo


def test_a1_put_led_devolve_o_pedido(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.response = OK

    sem_pisca = client.put("/device/led", json={"color": "blue", "duration_s": 4})
    com_pisca = client.put(
        "/device/led", json={"color": "green", "duration_s": 2, "flash_cycle_ms": 500}
    )

    assert sem_pisca.json() == {
        "color": "blue",
        "duration_s": 4,
        "flash_cycle_ms": None,
    }
    assert com_pisca.json() == {
        "color": "green",
        "duration_s": 2,
        "flash_cycle_ms": 500,
    }


@pytest.mark.parametrize(
    "cor", ["white", "red", "yellow", "blue", "green", "cyan", "purple"]
)
def test_a1_aceita_as_sete_cores_da_lib(
    client: TestClient, pub_sub: FakePubSub, cor: str
) -> None:
    pub_sub.response = OK

    resposta = client.put("/device/led", json={"color": cor, "duration_s": 1})

    assert resposta.status_code == 202
    assert pub_sub.sent[0]["options"]["parameter"]["color"] == cor


# ─── A2: validação antes de falar com o robô ─────────────────────────────────


@pytest.mark.parametrize("url", ["/device/brightness", "/device/volume"])
@pytest.mark.parametrize("level", [-1, 11, True, 5.0, "5", None])
def test_a2_level_invalido_responde_422_sem_publicar(
    client: TestClient, pub_sub: FakePubSub, url: str, level: object
) -> None:
    assert client.put(url, json={"level": level}).status_code == 422
    assert pub_sub.sent == []


@pytest.mark.parametrize(
    ("url", "level", "teto"),
    [("/device/brightness", 5, 4), ("/device/volume", 7, 6)],
)
def test_a2_level_acima_do_teto_configurado_responde_422_com_o_teto(
    capped_client: TestClient, pub_sub: FakePubSub, url: str, level: int, teto: int
) -> None:
    resposta = capped_client.put(url, json={"level": level})

    assert resposta.status_code == 422
    assert str(teto) in json.dumps(resposta.json(), ensure_ascii=False)
    assert pub_sub.sent == []


@pytest.mark.parametrize(
    ("url", "level"), [("/device/brightness", 4), ("/device/volume", 6)]
)
def test_a2_level_no_teto_configurado_e_aceito(
    capped_client: TestClient, pub_sub: FakePubSub, url: str, level: int
) -> None:
    pub_sub.response = OK

    assert capped_client.put(url, json={"level": level}).status_code == 202


@pytest.mark.parametrize(
    "corpo",
    [
        {"color": "pink", "duration_s": 5},
        {"color": "RED", "duration_s": 5},
        {"color": "red", "duration_s": 0},
        {"color": "red", "duration_s": 61},
        {"color": "red", "duration_s": True},
        {"color": "red", "duration_s": 5.0},
        {"color": "red", "duration_s": 5, "flash_cycle_ms": 498},
        {"color": "red", "duration_s": 5, "flash_cycle_ms": 5001},
        {"color": "red", "duration_s": 5, "flash_cycle_ms": 1000.0},
        {"color": "red"},
        {"duration_s": 5},
    ],
)
def test_a2_led_invalido_responde_422_sem_publicar(
    client: TestClient, pub_sub: FakePubSub, corpo: dict[str, Any]
) -> None:
    assert client.put("/device/led", json=corpo).status_code == 422
    assert pub_sub.sent == []


def test_a2_led_acima_do_teto_configurado_responde_422_com_o_teto(
    capped_client: TestClient, pub_sub: FakePubSub
) -> None:
    resposta = capped_client.put("/device/led", json={"color": "red", "duration_s": 6})

    assert resposta.status_code == 422
    assert "5" in json.dumps(resposta.json())
    assert pub_sub.sent == []


@pytest.mark.parametrize(
    "corpo",
    [
        {"color": "red", "duration_s": 60},
        {"color": "red", "duration_s": 1},
        {"color": "red", "duration_s": 5, "flash_cycle_ms": 499},
        {"color": "red", "duration_s": 5, "flash_cycle_ms": 5000},
    ],
)
def test_a2_limites_exatos_sao_aceitos(
    client: TestClient, pub_sub: FakePubSub, corpo: dict[str, Any]
) -> None:
    pub_sub.response = OK

    assert client.put("/device/led", json=corpo).status_code == 202


# ─── A3: códigos de resposta ─────────────────────────────────────────────────

ESCRITAS: list[tuple[str, dict[str, Any]]] = [
    ("/device/brightness", {"level": 1}),
    ("/device/volume", {"level": 1}),
    ("/device/led", {"color": "red", "duration_s": 1}),
]


@pytest.mark.parametrize(("url", "corpo"), ESCRITAS)
@pytest.mark.parametrize(
    "resposta_do_robo",
    [
        _resposta(code=1),
        _resposta(code=-1),
        {"data": {"header": {}, "data": ""}},
        {"data": {"data": ""}},
        {"data": None},
        {},
    ],
)
def test_a3_codigo_diferente_de_zero_ou_sem_status_responde_502(
    client: TestClient,
    pub_sub: FakePubSub,
    url: str,
    corpo: dict[str, Any],
    resposta_do_robo: dict[str, Any],
) -> None:
    pub_sub.response = resposta_do_robo

    resposta = client.put(url, json=corpo)

    assert resposta.status_code == 502
    assert resposta.json()["detail"]


@pytest.mark.parametrize(("url", "corpo"), ESCRITAS)
def test_a3_502_traz_o_codigo_no_detail(
    client: TestClient, pub_sub: FakePubSub, url: str, corpo: dict[str, Any]
) -> None:
    pub_sub.response = _resposta(code=3104)

    assert "3104" in client.put(url, json=corpo).json()["detail"]


@pytest.mark.parametrize(("url", "corpo"), ESCRITAS)
def test_a3_sem_conexao_responde_503(
    offline_client: TestClient, url: str, corpo: dict[str, Any]
) -> None:
    assert offline_client.put(url, json=corpo).status_code == 503


@pytest.mark.parametrize("url", ["/device/brightness", "/device/volume"])
def test_a3_get_sem_conexao_responde_503(offline_client: TestClient, url: str) -> None:
    assert offline_client.get(url).status_code == 503


@pytest.mark.parametrize(("url", "corpo"), ESCRITAS)
def test_a3_sem_resposta_responde_504(
    client: TestClient, pub_sub: FakePubSub, url: str, corpo: dict[str, Any]
) -> None:
    pub_sub.hang_on_request = True

    assert client.put(url, json=corpo).status_code == 504


@pytest.mark.parametrize("url", ["/device/brightness", "/device/volume"])
def test_a3_get_sem_resposta_responde_504(
    client: TestClient, pub_sub: FakePubSub, url: str
) -> None:
    pub_sub.hang_on_request = True

    assert client.get(url).status_code == 504


@pytest.mark.parametrize("url", ["/device/brightness", "/device/volume"])
def test_a3_get_com_codigo_diferente_de_zero_responde_502(
    client: TestClient, pub_sub: FakePubSub, url: str
) -> None:
    pub_sub.response = _resposta(code=7, data=json.dumps({"brightness": 1}))

    assert client.get(url).status_code == 502


def test_a3_stop_responde_e_publica_durante_pedido_vui_pendente(
    slow_client: TestClient, pub_sub: FakePubSub
) -> None:
    libera = threading.Event()

    async def responde_depois_de_liberado(_: dict[str, Any]) -> dict[str, Any]:
        # threading.Event: quem libera é a thread do teste, fora do loop.
        while not libera.is_set():  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        return OK

    pub_sub.responder = responde_depois_de_liberado
    resultado: dict[str, int] = {}

    def pede_brilho() -> None:
        resposta = slow_client.put("/device/brightness", json={"level": 2})
        resultado["status"] = resposta.status_code

    pedido = threading.Thread(target=pede_brilho)
    pedido.start()
    try:
        for _ in range(500):
            if _vui(pub_sub):
                break
            threading.Event().wait(0.01)
        assert _vui(pub_sub), "o pedido VUI não chegou ao robô"

        parada = slow_client.post("/commands/stop")

        assert parada.status_code == 202
        assert SPORT_CMD["StopMove"] in pub_sub.api_ids
        assert pedido.is_alive(), "o pedido VUI devia seguir pendente"
    finally:
        libera.set()
        pedido.join(timeout=5)
    assert resultado["status"] == 202


def test_a3_dois_pedidos_simultaneos_recebem_cada_um_a_sua_resposta(
    slow_client: TestClient, pub_sub: FakePubSub
) -> None:
    # O brilho espera o volume responder: as respostas chegam fora de ordem.
    volume_respondeu = threading.Event()

    async def responde_por_api_id(options: dict[str, Any]) -> dict[str, Any]:
        if options["api_id"] == 1006:
            while not volume_respondeu.is_set():  # noqa: ASYNC110
                await asyncio.sleep(0.01)
            return _resposta(data=json.dumps({"brightness": 3}))
        volume_respondeu.set()
        return _resposta(data=json.dumps({"volume": 8}))

    pub_sub.responder = responde_por_api_id
    resultados: dict[str, Any] = {}

    def le(url: str) -> None:
        resultados[url] = slow_client.get(url).json()

    brilho = threading.Thread(target=le, args=("/device/brightness",))
    brilho.start()
    for _ in range(500):
        if _vui(pub_sub):
            break
        threading.Event().wait(0.01)
    le("/device/volume")
    brilho.join(timeout=5)

    assert resultados == {
        "/device/brightness": {"level": 3},
        "/device/volume": {"level": 8},
    }


# ─── A4: leitura de `data.data` ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "campo"),
    [("/device/brightness", "brightness"), ("/device/volume", "volume")],
)
def test_a4_get_le_o_nivel_de_data_data(
    client: TestClient, pub_sub: FakePubSub, url: str, campo: str
) -> None:
    pub_sub.response = _resposta(data=json.dumps({campo: 6}))

    resposta = client.get(url)

    assert resposta.status_code == 200
    assert resposta.json() == {"level": 6}


@pytest.mark.parametrize(
    ("url", "data"),
    [
        ("/device/brightness", json.dumps({"volume": 3})),
        ("/device/volume", json.dumps({"brightness": 3})),
        ("/device/brightness", "não é json"),
        ("/device/volume", ""),
        ("/device/brightness", json.dumps({"brightness": "3"})),
        ("/device/volume", json.dumps({"volume": True})),
        ("/device/brightness", json.dumps([1, 2])),
        ("/device/volume", None),
    ],
)
def test_a4_get_com_campo_ausente_ou_json_invalido_responde_502(
    client: TestClient, pub_sub: FakePubSub, url: str, data: object
) -> None:
    pub_sub.response = _resposta(data=data)

    resposta = client.get(url)

    assert resposta.status_code == 502
    assert resposta.json()["detail"]


def test_a4_led_nao_tem_get(client: TestClient) -> None:
    assert client.get("/device/led").status_code == 405


# ─── A5: /capabilities não muda ──────────────────────────────────────────────


# `version` do `/capabilities` medido antes da F-005 (commit 3912e00).
CAPABILITIES_VERSION_ANTES_DA_F005 = "7e4008fc1641"


def test_a5_device_fora_do_capabilities(client: TestClient) -> None:
    corpo = client.get("/capabilities").json()

    assert not [c for c in corpo["commands"] if c["endpoint"].startswith("/device")]
    assert corpo["version"] == CAPABILITIES_VERSION_ANTES_DA_F005


def test_a5_rotas_device_estao_no_openapi(client: TestClient) -> None:
    caminhos = client.get("/openapi.json").json()["paths"]

    assert {"/device/brightness", "/device/volume", "/device/led"} <= caminhos.keys()
