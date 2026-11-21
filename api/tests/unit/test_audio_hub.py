"""F-006: `AudioHub` — ganchos, estado do envio e queda de conexão (A3, A6, A8)."""

import asyncio
import base64
import hashlib
import json
from typing import Any

import pytest

from app.exceptions import (
    ConflictError,
    InvalidCommandError,
    NotFoundError,
    RobotTimeoutError,
)
from app.robot.audio import (
    AudioHub,
    AudioName,
    UploadReader,
    UploadSource,
    UploadState,
)
from app.robot.service import Go2Robot
from app.robot.unitree import RTC_TOPIC
from tests.audio_files import make_wav
from tests.fakes import FakeConnection, FakeConnectionFactory, FakePubSub

HUB = RTC_TOPIC["AUDIO_HUB_REQ"]


def resposta(code: int = 0, data: object = "") -> dict[str, Any]:
    return {"data": {"header": {"status": {"code": code}}, "data": data}}


def lista(*items: tuple[str, str]) -> dict[str, Any]:
    audio_list = [{"UNIQUE_ID": i, "CUSTOM_NAME": n, "ADD_TIME": 1} for i, n in items]
    return resposta(data=json.dumps({"audio_list": audio_list}))


class Robo:
    """Responde pelo api_id; a lista ganha o arquivo depois do último bloco."""

    def __init__(self, existentes: list[tuple[str, str]] | None = None) -> None:
        self.files = list(existentes or [])
        self.blocks: list[dict[str, Any]] = []
        self.block_code = 0
        self.hang_on_block: int | None = None
        self.on_block: dict[int, Any] = {}

    async def __call__(self, options: dict[str, Any]) -> dict[str, Any]:
        api_id = options["api_id"]
        if api_id == 1001:
            return lista(*self.files)
        if api_id == 2001:
            p = json.loads(options["parameter"])
            self.blocks.append(p)
            index = p["current_block_index"]
            if index in self.on_block:
                await self.on_block[index]()
            if index == self.hang_on_block:
                await asyncio.Event().wait()
            if index == p["total_block_number"] and self.block_code == 0:
                self.files.append((f"id-{p['file_name']}", p["file_name"]))
            return resposta(code=self.block_code)
        return resposta()


def hub_requests(pub_sub: FakePubSub, api_id: int | None = None) -> list[Any]:
    return [
        m["options"]
        for m in pub_sub.sent
        if m["topic"] == HUB and (api_id is None or m["options"]["api_id"] == api_id)
    ]


async def esperar_fim(hub: AudioHub, upload_id: str) -> Any:
    for _ in range(500):
        record = hub.upload_status(upload_id)
        if record.state is not UploadState.uploading:
            return record
        await asyncio.sleep(0.01)
    raise AssertionError("o envio não terminou")


def fonte(
    data: bytes, name: str | None = None, filename: str = "som.wav"
) -> UploadReader:
    async def ler() -> UploadSource:
        return UploadSource(data=data, filename=filename, name=name)

    return ler


@pytest.fixture
def robo(pub_sub: FakePubSub) -> Robo:
    fake = Robo([("velho", "outro")])
    pub_sub.responder = fake
    return fake


@pytest.fixture
def hub(robot: Go2Robot) -> AudioHub:
    robot.audio.block_interval_s = 0
    return robot.audio


# ─── Nome ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [("ola", "ola"), ("  com espaço  ", "com espaço"), ("x" * 64, "x" * 64)],
)
def test_nome_valido(raw: str, esperado: str) -> None:
    assert AudioName.validate(raw) == esperado


@pytest.mark.parametrize(
    "raw", ["", "   ", "x" * 65, "a/b", "a\\b", "a\nb", "a\x00b", "a\x7fb"]
)
def test_nome_invalido(raw: str) -> None:
    with pytest.raises(InvalidCommandError):
        AudioName.validate(raw)


# ─── A3: envio completo ──────────────────────────────────────────────────────


async def test_a3_envio_reconstroi_o_arquivo_e_termina_done(
    hub: AudioHub, robo: Robo, pub_sub: FakePubSub
) -> None:
    wav = make_wav(seconds=0.4)

    record = await hub.upload(fonte(wav, filename="bip.wav"))
    final = await esperar_fim(hub, record.upload_id)

    assert final.state is UploadState.done
    assert final.name == "bip"
    assert final.sent_chunks == final.total_chunks == len(robo.blocks)
    assert final.file_id == "id-bip"
    assert final.error is None
    assert base64.b64decode("".join(b["block_content"] for b in robo.blocks)) == wav
    assert [b["current_block_index"] for b in robo.blocks] == list(
        range(1, len(robo.blocks) + 1)
    )
    assert all(len(b["block_content"]) <= 4096 for b in robo.blocks)
    assert {b["file_md5"] for b in robo.blocks} == {hashlib.md5(wav).hexdigest()}  # noqa: S324
    assert {b["total_block_number"] for b in robo.blocks} == {len(robo.blocks)}
    # Lista antes (nome repetido) e depois (file_id).
    assert len(hub_requests(pub_sub, 1001)) == 2


async def test_a3_nome_explicito_vence_o_do_arquivo(hub: AudioHub, robo: Robo) -> None:
    record = await hub.upload(fonte(make_wav(0.1), name=" Meu Som ", filename="x.wav"))
    final = await esperar_fim(hub, record.upload_id)

    assert final.name == "Meu Som"
    assert {b["file_name"] for b in robo.blocks} == {"Meu Som"}


async def test_a3_file_id_null_se_nada_novo_aparece(
    hub: AudioHub, robo: Robo, pub_sub: FakePubSub
) -> None:
    async def lista_fixa(options: dict[str, Any]) -> dict[str, Any]:
        if options["api_id"] == 1001:
            return lista(("velho", "outro"))
        return resposta()

    pub_sub.responder = lista_fixa
    record = await hub.upload(fonte(make_wav(0.1)))
    final = await esperar_fim(hub, record.upload_id)

    assert final.state is UploadState.done
    assert final.file_id is None


async def test_espera_o_intervalo_entre_blocos(robot: Go2Robot, robo: Robo) -> None:
    pausas: list[float] = []

    async def dorme(segundos: float) -> None:
        pausas.append(segundos)

    hub = robot.audio
    hub._sleep = dorme
    record = await hub.upload(fonte(make_wav(0.4)))
    final = await esperar_fim(hub, record.upload_id)

    assert final.total_chunks > 1
    assert pausas == [pytest.approx(0.1)] * (final.total_chunks - 1)


async def test_upload_id_desconhecido_e_404(hub: AudioHub) -> None:
    with pytest.raises(NotFoundError):
        hub.upload_status("nao-existe")


async def test_guarda_so_os_ultimos_20(hub: AudioHub, robo: Robo) -> None:
    ids = []
    for i in range(21):
        record = await hub.upload(fonte(make_wav(0.01), name=f"s{i}"))
        await esperar_fim(hub, record.upload_id)
        ids.append(record.upload_id)

    with pytest.raises(NotFoundError):
        hub.upload_status(ids[0])
    assert hub.upload_status(ids[-1]).state is UploadState.done
    assert hub.upload_status(ids[1]).name == "s1"


# ─── A5 no hub: conflitos ────────────────────────────────────────────────────


async def test_a5_nome_repetido_e_409_sem_publicar_bloco(
    hub: AudioHub, robo: Robo, pub_sub: FakePubSub
) -> None:
    with pytest.raises(ConflictError):
        await hub.upload(fonte(make_wav(0.1), name="outro"))

    assert hub_requests(pub_sub, 2001) == []
    # Liberou a vaga.
    record = await hub.upload(fonte(make_wav(0.1), name="novo"))
    assert (await esperar_fim(hub, record.upload_id)).state is UploadState.done


async def test_a5_segundo_envio_em_andamento_e_409_sem_ler_o_corpo(
    hub: AudioHub, robo: Robo
) -> None:
    robo.hang_on_block = 1
    await hub.upload(fonte(make_wav(0.1)))
    lido = False

    async def ler() -> UploadSource:
        nonlocal lido
        lido = True
        return UploadSource(data=make_wav(0.1), filename="b.wav", name=None)

    with pytest.raises(ConflictError):
        await hub.upload(ler)
    assert lido is False
    await hub.cancel_upload()


async def test_falha_ao_ler_libera_a_vaga(hub: AudioHub, robo: Robo) -> None:
    with pytest.raises(InvalidCommandError):
        await hub.upload(fonte(make_wav(0.1), name="a/b"))

    record = await hub.upload(fonte(make_wav(0.1)))
    assert (await esperar_fim(hub, record.upload_id)).state is UploadState.done


# ─── A6: timeout, recusa e queda ─────────────────────────────────────────────


async def test_a6_bloco_sem_resposta_vira_failed_timeout(
    hub: AudioHub, robo: Robo
) -> None:
    robo.hang_on_block = 2
    record = await hub.upload(fonte(make_wav(0.4)))
    final = await esperar_fim(hub, record.upload_id)

    assert final.state is UploadState.failed
    assert final.error == "timeout"
    assert final.sent_chunks == 1


async def test_a6_codigo_diferente_de_zero_vira_failed(
    hub: AudioHub, robo: Robo
) -> None:
    robo.block_code = 9
    record = await hub.upload(fonte(make_wav(0.4)))
    final = await esperar_fim(hub, record.upload_id)

    assert final.state is UploadState.failed
    assert final.error is not None
    assert final.error.startswith("rejected")
    assert final.sent_chunks == 0


async def test_a6_conexao_que_cai_e_volta_entre_blocos_vira_disconnected(
    robot: Go2Robot, factory: FakeConnectionFactory, robo: Robo
) -> None:
    hub = robot.audio
    hub.block_interval_s = 0
    velho = factory.pub_sub
    novo_conn = FakeConnection()
    novo_conn.datachannel.pub_sub.responder = robo

    async def cai_e_volta() -> None:
        await robot._link.disconnect()
        factory.connection = novo_conn
        await robot._link.connect()

    robo.on_block[2] = cai_e_volta
    record = await hub.upload(fonte(make_wav(0.4)))
    final = await esperar_fim(hub, record.upload_id)

    assert robot.is_connected
    assert final.state is UploadState.failed
    assert final.error == "disconnected"
    assert final.sent_chunks == 2
    indices = [
        json.loads(o["parameter"])["current_block_index"]
        for ps in (velho, novo_conn.datachannel.pub_sub)
        for o in hub_requests(ps, 2001)
    ]
    assert indices == [1, 2]


async def test_a6_conexao_caida_sem_volta_vira_disconnected(
    hub: AudioHub, robo: Robo, factory: FakeConnectionFactory
) -> None:
    async def cai() -> None:
        factory.connection.datachannel.data_channel_opened = False

    robo.on_block[1] = cai
    record = await hub.upload(fonte(make_wav(0.4)))
    final = await esperar_fim(hub, record.upload_id)

    assert final.error == "disconnected"
    assert final.sent_chunks == 1


async def test_disconnect_do_robo_encerra_o_envio(robot: Go2Robot, robo: Robo) -> None:
    robo.hang_on_block = 1
    robot.audio.block_interval_s = 0
    record = await robot.audio.upload(fonte(make_wav(0.1)))

    await robot.disconnect()

    final = robot.audio.upload_status(record.upload_id)
    assert final.state is UploadState.failed
    assert final.error == "disconnected"


# ─── Gancho 1: silence chama o stopper do alto-falante (A8) ──────────────────


async def test_a8_silence_pausa_o_hub_e_chama_o_stopper(
    hub: AudioHub, pub_sub: FakePubSub
) -> None:
    pub_sub.response = resposta()
    chamadas: list[str] = []

    async def para_alto_falante() -> None:
        chamadas.append("speaker")

    hub.set_speaker_stopper(para_alto_falante)
    await hub.silence()

    assert chamadas == ["speaker"]
    assert [o["api_id"] for o in hub_requests(pub_sub)] == [1003]
    assert hub_requests(pub_sub)[0]["parameter"] == "{}"


async def test_silence_sem_stopper_so_pausa(hub: AudioHub, pub_sub: FakePubSub) -> None:
    pub_sub.response = resposta()

    await hub.silence()

    assert [o["api_id"] for o in hub_requests(pub_sub)] == [1003]


async def test_silence_chama_o_stopper_mesmo_se_o_pause_falhar(
    hub: AudioHub, pub_sub: FakePubSub
) -> None:
    pub_sub.hang_on_request = True
    chamadas: list[str] = []

    async def para_alto_falante() -> None:
        chamadas.append("speaker")

    hub.set_speaker_stopper(para_alto_falante)
    with pytest.raises(RobotTimeoutError):
        await hub.silence()
    assert chamadas == ["speaker"]


async def test_silence_pausa_mesmo_se_o_stopper_falhar(
    hub: AudioHub, pub_sub: FakePubSub
) -> None:
    pub_sub.response = resposta()

    async def quebra() -> None:
        raise RuntimeError("alto-falante")

    hub.set_speaker_stopper(quebra)
    with pytest.raises(RuntimeError):
        await hub.silence()
    assert [o["api_id"] for o in hub_requests(pub_sub)] == [1003]


# ─── Gancho 2: AUDIO_HUB_PLAY_STATE ──────────────────────────────────────────


async def test_assina_o_play_state_a_cada_conexao(
    robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    topic = RTC_TOPIC["AUDIO_HUB_PLAY_STATE"]
    assert topic in factory.pub_sub.subscriptions

    await robot.disconnect()
    factory.connection = FakeConnection()
    await robot.connect()

    assert topic in factory.pub_sub.subscriptions


async def test_player_guarda_o_ultimo_data_e_a_idade(
    settings: Any, factory: FakeConnectionFactory
) -> None:
    agora = [100.0]
    robot = Go2Robot.from_settings(settings, factory)
    robot.audio._clock = lambda: agora[0]
    await robot.connect()
    topic = RTC_TOPIC["AUDIO_HUB_PLAY_STATE"]

    assert robot.audio.player().data is None
    assert robot.audio.player().age_s is None

    factory.pub_sub.publish_state(topic, {"play_state": "playing"})
    agora[0] = 102.5

    leitura = robot.audio.player()
    assert leitura.data == {"play_state": "playing"}
    assert leitura.age_s == pytest.approx(2.5)
    await robot.disconnect()


async def test_ouvintes_do_play_state_recebem_o_data_cru(
    robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    recebidos: list[Any] = []

    def quebra(_: Any) -> None:
        raise RuntimeError("ouvinte com defeito")

    robot.audio.subscribe_player_state(quebra)
    cancelar = robot.audio.subscribe_player_state(recebidos.append)
    topic = RTC_TOPIC["AUDIO_HUB_PLAY_STATE"]

    factory.pub_sub.publish_state(topic, {"a": 1})
    cancelar()
    factory.pub_sub.publish_state(topic, {"a": 2})

    assert recebidos == [{"a": 1}]
    assert robot.audio.player().data == {"a": 2}
