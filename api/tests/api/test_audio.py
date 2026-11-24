"""Testes de `/audio/*`: biblioteca de áudio do robô (F-006)."""

import asyncio
import base64
import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.robot.audio_format import AudioConverter
from app.robot.unitree import RTC_TOPIC, SPORT_CMD
from tests.fakes import FakeConnectionFactory, FakePubSub
from tests.library_audio_files import make_mp3, make_mp3_of_size, make_wav, wav_info
from tests.unit.test_audio_hub import Robo, lista, resposta

HUB = RTC_TOPIC["AUDIO_HUB_REQ"]
MB = 1024 * 1024


def _hub(pub_sub: FakePubSub, api_id: int | None = None) -> list[dict[str, Any]]:
    return [
        m["options"]
        for m in pub_sub.sent
        if m["topic"] == HUB and (api_id is None or m["options"]["api_id"] == api_id)
    ]


def _envia(
    client: TestClient,
    data: bytes,
    filename: str = "som.wav",
    name: str | None = None,
) -> Any:
    form = {"name": name} if name is not None else None
    return client.post(
        "/audio/files",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )


def _espera_fim(client: TestClient, upload_id: str) -> dict[str, Any]:
    for _ in range(500):
        body: dict[str, Any] = client.get(f"/audio/uploads/{upload_id}").json()
        if body["state"] != "uploading":
            return body
        time.sleep(0.01)
    raise AssertionError("o envio não terminou")


@pytest.fixture
def robo(pub_sub: FakePubSub) -> Robo:
    fake = Robo([("velho", "outro")])
    pub_sub.responder = fake
    return fake


@pytest.fixture
def fast(client: TestClient) -> TestClient:
    client.app.state.robot.audio.block_interval_s = 0  # type: ignore[attr-defined]
    return client


@pytest.fixture
def slow(settings: Settings, factory: FakeConnectionFactory) -> Iterator[TestClient]:
    """Timeout folgado, para segurar um bloco do envio sem virar `timeout`."""
    folgado = settings.model_copy(update={"request_timeout_s": 5.0})
    with TestClient(create_app(folgado, connection_factory=factory)) as test_client:
        yield test_client


# ─── A1: tópico, api_id e parameter (string JSON) ────────────────────────────


@pytest.mark.parametrize(
    ("method", "url", "corpo", "api_id", "parameter"),
    [
        (
            "patch",
            "/audio/files/abc",
            {"name": "novo"},
            1008,
            {"unique_id": "abc", "new_name": "novo"},
        ),
        ("delete", "/audio/files/abc", None, 1009, {"unique_id": "abc"}),
        ("post", "/audio/files/abc/play", None, 1002, {"unique_id": "abc"}),
        ("post", "/audio/pause", None, 1003, {}),
        ("post", "/audio/resume", None, 1004, {}),
        (
            "put",
            "/audio/play-mode",
            {"mode": "list_loop"},
            1007,
            {"play_mode": "list_loop"},
        ),
        ("post", "/audio/silence", None, 1003, {}),
    ],
)
def test_a1_escritas_publicam_api_id_e_parameter_string(  # noqa: PLR0917
    client: TestClient,
    pub_sub: FakePubSub,
    method: str,
    url: str,
    corpo: Any,
    api_id: int,
    parameter: dict[str, Any],
) -> None:
    pub_sub.response = resposta()
    kwargs = {"json": corpo} if corpo is not None else {}

    r = client.request(method.upper(), url, **kwargs)

    assert r.status_code == 202, r.text
    [options] = _hub(pub_sub)
    assert options["api_id"] == api_id
    assert isinstance(options["parameter"], str)
    assert json.loads(options["parameter"]) == parameter


@pytest.mark.parametrize(
    ("url", "api_id", "data"),
    [
        ("/audio/files", 1001, json.dumps({"audio_list": []})),
        ("/audio/play-mode", 1010, json.dumps({"play_mode": "no_cycle"})),
    ],
)
def test_a1_leituras_publicam_api_id_e_parameter_vazio(
    client: TestClient, pub_sub: FakePubSub, url: str, api_id: int, data: str
) -> None:
    pub_sub.response = resposta(data=data)

    assert client.get(url).status_code == 200
    [options] = _hub(pub_sub)
    assert options == {"api_id": api_id, "parameter": "{}"}


def test_a1_respostas_das_escritas(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.response = resposta()

    assert client.put("/audio/play-mode", json={"mode": "single_cycle"}).json() == {
        "mode": "single_cycle"
    }
    assert client.patch("/audio/files/abc", json={"name": " x "}).json() == {
        "id": "abc",
        "name": "x",
    }
    assert client.get("/audio/play-mode").status_code == 502  # resposta sem modo


def test_get_play_mode_devolve_o_modo(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.response = resposta(data=json.dumps({"play_mode": "list_loop"}))

    assert client.get("/audio/play-mode").json() == {"mode": "list_loop"}


# ─── A2: lista e erros ───────────────────────────────────────────────────────


def test_a2_lista_vira_id_name_extra(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.response = lista(("u1", "um"), ("u2", "dois"))

    assert client.get("/audio/files").json() == [
        {"id": "u1", "name": "um", "extra": {"ADD_TIME": 1}},
        {"id": "u2", "name": "dois", "extra": {"ADD_TIME": 1}},
    ]


@pytest.mark.parametrize(
    "response",
    [
        resposta(code=3, data=json.dumps({"audio_list": []})),
        {"data": {"data": json.dumps({"audio_list": []})}},
        resposta(data="não é json"),
        resposta(data=json.dumps({"outra": []})),
        resposta(data=json.dumps({"audio_list": "x"})),
        resposta(data=json.dumps({"audio_list": [{"UNIQUE_ID": "a"}]})),
        resposta(
            data=json.dumps({"audio_list": [{"UNIQUE_ID": 1, "CUSTOM_NAME": "a"}]})
        ),
        resposta(data=json.dumps({"audio_list": ["x"]})),
        resposta(data=None),
    ],
)
def test_a2_lista_malformada_ou_recusada_e_502(
    client: TestClient, pub_sub: FakePubSub, response: dict[str, Any]
) -> None:
    pub_sub.response = response

    assert client.get("/audio/files").status_code == 502


@pytest.mark.parametrize(
    "data",
    [json.dumps({"play_mode": "outro"}), json.dumps({}), "x", json.dumps(["a"])],
)
def test_a2_modo_malformado_e_502(
    client: TestClient, pub_sub: FakePubSub, data: str
) -> None:
    pub_sub.response = resposta(data=data)

    assert client.get("/audio/play-mode").status_code == 502


ROTAS = [
    ("GET", "/audio/files", None),
    ("PATCH", "/audio/files/a", {"name": "b"}),
    ("DELETE", "/audio/files/a", None),
    ("POST", "/audio/files/a/play", None),
    ("POST", "/audio/pause", None),
    ("POST", "/audio/resume", None),
    ("GET", "/audio/play-mode", None),
    ("PUT", "/audio/play-mode", {"mode": "no_cycle"}),
    ("POST", "/audio/silence", None),
]


@pytest.mark.parametrize(("method", "url", "corpo"), ROTAS)
def test_a2_sem_conexao_e_503(
    offline_client: TestClient, method: str, url: str, corpo: Any
) -> None:
    kwargs = {"json": corpo} if corpo is not None else {}
    assert offline_client.request(method, url, **kwargs).status_code == 503


@pytest.mark.parametrize(("method", "url", "corpo"), ROTAS)
def test_a2_sem_resposta_e_504(
    client: TestClient, pub_sub: FakePubSub, method: str, url: str, corpo: Any
) -> None:
    pub_sub.hang_on_request = True
    kwargs = {"json": corpo} if corpo is not None else {}
    assert client.request(method, url, **kwargs).status_code == 504


@pytest.mark.parametrize(("method", "url", "corpo"), ROTAS[1:6] + ROTAS[7:])
def test_a2_codigo_diferente_de_zero_e_502(
    client: TestClient, pub_sub: FakePubSub, method: str, url: str, corpo: Any
) -> None:
    pub_sub.response = resposta(code=4)
    kwargs = {"json": corpo} if corpo is not None else {}
    r = client.request(method, url, **kwargs)
    assert r.status_code == 502
    assert "4" in r.json()["detail"]


def test_a2_id_inexistente_nao_consulta_a_lista(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.response = resposta(code=1)

    assert client.post("/audio/files/nao-existe/play").status_code == 502
    assert [o["api_id"] for o in _hub(pub_sub)] == [1002]


# ─── A3: envio de um WAV ─────────────────────────────────────────────────────


def test_a3_envio_de_wav_responde_202_e_termina_done(
    fast: TestClient, robo: Robo
) -> None:
    wav = make_wav(seconds=0.3)

    r = _envia(fast, wav, filename="bip.wav")

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["name"] == "bip"
    assert body["total_chunks"] >= 2
    final = _espera_fim(fast, body["upload_id"])
    assert final == {
        "state": "done",
        "name": "bip",
        "sent_chunks": body["total_chunks"],
        "total_chunks": body["total_chunks"],
        "file_id": "id-bip",
        "error": None,
    }
    assert base64.b64decode("".join(b["block_content"] for b in robo.blocks)) == wav
    assert [b["current_block_index"] for b in robo.blocks] == list(
        range(1, body["total_chunks"] + 1)
    )


def test_upload_id_desconhecido_e_404(client: TestClient) -> None:
    assert client.get("/audio/uploads/nada").status_code == 404


def test_hub_funciona_durante_o_envio(slow: TestClient, robo: Robo) -> None:
    libera = threading.Event()

    async def segura() -> None:
        while not libera.is_set():  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    robo.on_block[1] = segura
    r = _envia(slow, make_wav(0.3))
    try:
        assert r.status_code == 202
        assert slow.get("/audio/files").status_code == 200
        assert slow.post("/audio/files/velho/play").status_code == 202
        upload_id = r.json()["upload_id"]
        assert slow.get(f"/audio/uploads/{upload_id}").json()["state"] == "uploading"
    finally:
        libera.set()


# ─── A4: MP3 ────────────────────────────────────────────────────────────────


def test_a4_mp3_chega_ao_robo_como_wav_44100(fast: TestClient, robo: Robo) -> None:
    mp3 = make_mp3(seconds=1.0, rate=22050, channels=2)

    r = _envia(fast, mp3, filename="musica.mp3")

    assert r.status_code == 202, r.text
    assert _espera_fim(fast, r.json()["upload_id"])["state"] == "done"
    wav = base64.b64decode("".join(b["block_content"] for b in robo.blocks))
    channels, width, rate, duration = wav_info(wav)
    assert (channels, width, rate) == (2, 2, 44100)
    assert duration == pytest.approx(1.0, abs=0.05)
    assert {b["file_type"] for b in robo.blocks} == {"wav"}


# ─── A5: rejeições, nada publicado no hub além da lista ──────────────────────


@pytest.fixture
def small(settings: Settings, factory: FakeConnectionFactory) -> Iterator[TestClient]:
    """Limite de 0,1 MB para os testes de 413."""
    limited = settings.model_copy(update={"audio_max_upload_mb": 0.1})
    with TestClient(create_app(limited, connection_factory=factory)) as test_client:
        yield test_client


def test_a5_arquivo_acima_do_limite_e_413(
    small: TestClient, robo: Robo, pub_sub: FakePubSub
) -> None:
    r = _envia(small, make_wav(seconds=5.0))

    assert r.status_code == 413
    assert _hub(pub_sub) == []


def test_a5_mp3_abaixo_do_limite_com_wav_acima_e_413_com_tamanho(
    small: TestClient, robo: Robo, pub_sub: FakePubSub
) -> None:
    mp3 = make_mp3(seconds=3.0)
    assert len(mp3) < 0.1 * MB

    r = _envia(small, mp3, filename="a.mp3")

    assert r.status_code == 413
    assert "bytes" in r.json()["detail"]
    assert _hub(pub_sub) == []


@pytest.mark.parametrize(
    "data", [b"texto qualquer" * 50, b"RIFF\x00\x00\x00\x00WAVE" + b"x" * 300]
)
def test_a5_nao_audio_ou_corrompido_e_415(
    client: TestClient, robo: Robo, pub_sub: FakePubSub, data: bytes
) -> None:
    r = _envia(client, data)

    assert r.status_code == 415
    assert _hub(pub_sub) == []


@pytest.mark.parametrize(
    ("filename", "name"),
    [
        ("a.wav", "x" * 65),
        ("a.wav", "a/b"),
        ("a.wav", "a\\b"),
        ("a.wav", "a\tb"),
        ("a.wav", "   "),
        (".wav", None),
    ],
)
def test_a5_nome_invalido_e_422(
    client: TestClient,
    robo: Robo,
    pub_sub: FakePubSub,
    filename: str,
    name: str | None,
) -> None:
    r = _envia(client, make_wav(0.1), filename=filename, name=name)

    assert r.status_code == 422, r.text
    assert _hub(pub_sub) == []


def test_a5_sem_arquivo_e_422(client: TestClient, pub_sub: FakePubSub) -> None:
    r = client.post("/audio/files", data={"name": "x"})

    assert r.status_code == 422
    assert _hub(pub_sub) == []


def test_a5_nome_que_ja_existe_e_409_so_com_a_lista(
    client: TestClient, robo: Robo, pub_sub: FakePubSub
) -> None:
    r = _envia(client, make_wav(0.1), name="outro")

    assert r.status_code == 409
    assert [o["api_id"] for o in _hub(pub_sub)] == [1001]


def test_a5_segundo_envio_em_andamento_e_409(
    slow: TestClient, robo: Robo, pub_sub: FakePubSub
) -> None:
    libera = threading.Event()

    async def segura() -> None:
        while not libera.is_set():  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    robo.on_block[1] = segura
    primeiro = _envia(slow, make_wav(0.3), name="um")
    try:
        assert primeiro.status_code == 202
        for _ in range(500):  # o 1º bloco sai em segundo plano; fica retido
            if robo.blocks:
                break
            time.sleep(0.01)
        antes = len(_hub(pub_sub))

        segundo = _envia(slow, make_wav(0.1), name="dois")

        assert segundo.status_code == 409
        assert len(_hub(pub_sub)) == antes
    finally:
        libera.set()


def test_a5_upload_sem_conexao_e_503(offline_client: TestClient) -> None:
    assert _envia(offline_client, make_wav(0.1)).status_code == 503


# ─── A7: stop rápido durante envio e conversão ───────────────────────────────


def _stop_rapido(client: TestClient, pub_sub: FakePubSub) -> float:
    antes = pub_sub.api_ids.count(SPORT_CMD["StopMove"])
    inicio = time.perf_counter()
    r = client.post("/commands/stop")
    duracao = time.perf_counter() - inicio
    assert r.status_code == 202
    assert pub_sub.api_ids.count(SPORT_CMD["StopMove"]) == antes + 1
    return duracao


@pytest.mark.slow
def test_a7_stop_em_menos_de_100ms_durante_o_envio(
    client: TestClient, robo: Robo, pub_sub: FakePubSub
) -> None:
    # Intervalo real de 0,1 s entre blocos; ~25 blocos = ~2,5 s de envio.
    r = _envia(client, make_wav(seconds=2.4, rate=16000))
    assert r.status_code == 202
    upload_id = r.json()["upload_id"]

    tempos = []
    for _ in range(10):
        tempos.append(_stop_rapido(client, pub_sub))
        time.sleep(0.05)
    estado = client.get(f"/audio/uploads/{upload_id}").json()

    assert estado["state"] == "uploading", "o envio devia seguir em andamento"
    assert estado["sent_chunks"] >= 1
    assert max(tempos) < 0.1, tempos


@pytest.mark.slow
def test_a7_stop_em_menos_de_100ms_durante_a_conversao_de_mp3_maximo(
    client: TestClient,
    robo: Robo,
    pub_sub: FakePubSub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limite = client.app.state.settings.audio_max_upload_mb  # type: ignore[attr-defined]
    mp3 = make_mp3_of_size(int(limite * MB))
    convertendo = threading.Event()
    terminou = threading.Event()
    original = AudioConverter.prepare

    def prepare_observado(data: bytes, max_bytes: int) -> Any:
        convertendo.set()
        try:
            return original(data, max_bytes)
        finally:
            terminou.set()

    monkeypatch.setattr(AudioConverter, "prepare", prepare_observado)
    resultado: dict[str, int] = {}

    def envia() -> None:
        resultado["status"] = _envia(client, mp3, filename="grande.mp3").status_code

    thread = threading.Thread(target=envia)
    thread.start()
    try:
        assert convertendo.wait(10), "a conversão não começou"
        tempos: list[float] = []
        durante = 0  # paradas que terminaram com a conversão ainda rodando
        while not terminou.is_set() and len(tempos) < 10:
            tempos.append(_stop_rapido(client, pub_sub))
            durante += not terminou.is_set()
    finally:
        thread.join(timeout=60)

    # 5 MB de MP3 a 320 kbit/s viram ~23 MB de WAV: passa do limite.
    assert resultado["status"] == 413
    assert durante >= 3, f"conversão curta demais ({durante} paradas durante)"
    assert max(tempos) < 0.1, tempos


# ─── A8: modo inválido; silence ──────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["loop", "", 1, None, "LIST_LOOP"])
def test_a8_modo_fora_dos_tres_e_422_sem_publicar(
    client: TestClient, pub_sub: FakePubSub, mode: Any
) -> None:
    r = client.put("/audio/play-mode", json={"mode": mode})

    assert r.status_code == 422
    assert _hub(pub_sub) == []


def test_a8_silence_publica_pause_e_para_o_alto_falante(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.response = resposta()
    chamadas: list[str] = []

    async def para() -> None:
        chamadas.append("speaker")

    client.app.state.robot.audio.set_speaker_stopper(para)  # type: ignore[attr-defined]

    assert client.post("/audio/silence").status_code == 202
    assert chamadas == ["speaker"]
    assert [o["api_id"] for o in _hub(pub_sub)] == [1003]


def test_silence_nao_mexe_no_movimento(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.response = resposta()

    client.post("/audio/silence")

    assert pub_sub.fire_and_forget == []


def test_rename_com_nome_invalido_e_422(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    assert client.patch("/audio/files/a", json={"name": "a/b"}).status_code == 422
    assert _hub(pub_sub) == []


# ─── Player ─────────────────────────────────────────────────────────────────


def test_player_sem_dado_e_com_dado(
    client: TestClient, factory: FakeConnectionFactory
) -> None:
    assert client.get("/audio/player").json() == {"data": None, "age_s": None}

    factory.pub_sub.publish_state(RTC_TOPIC["AUDIO_HUB_PLAY_STATE"], {"x": [1]})

    body = client.get("/audio/player").json()
    assert body["data"] == {"x": [1]}
    assert body["age_s"] >= 0


def test_capabilities_nao_lista_audio(client: TestClient) -> None:
    assert "audio" not in json.dumps(client.get("/capabilities").json()).lower()
