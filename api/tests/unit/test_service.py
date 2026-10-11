"""Testes de `Go2Robot` (fachada)."""

import asyncio

import pytest

from app.exceptions import RobotTimeoutError, RobotUnavailableError
from app.requests import GestureRequest, PostureRequest
from app.robot.commands import MoveCommand, MoveLimits
from app.robot.connection import ConnectionState
from app.robot.service import Go2Robot
from app.robot.unitree import RTC_TOPIC, SPORT_CMD
from tests.fakes import FakeConnectionFactory, FakePubSub

LIMITS = MoveLimits(max_vx=1.0, max_vy=1.0, max_vyaw=2.0, max_duration_s=10.0)


def _move(duration_s: float = 5.0) -> MoveCommand:
    return MoveCommand(vx=0.2, vy=0.0, vyaw=0.0, duration_s=duration_s, limits=LIMITS)


# ─── Ciclo de vida ─────────────────────────────────────────────────────────


async def test_connect_assina_os_topicos_de_estado(
    robot: Go2Robot, pub_sub: FakePubSub
) -> None:
    assert robot.is_connected is True
    assert set(pub_sub.subscriptions) == {
        RTC_TOPIC["SPORT_MOD_STATE"],
        RTC_TOPIC["LOW_STATE"],
    }


async def test_disconnect_encerra_conexao_e_movimento(
    robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    await robot.start_move(_move())

    await robot.disconnect()

    assert factory.connection.disconnected is True
    assert robot.is_connected is False


async def test_robo_desligado_nao_esta_conectado(offline_robot: Go2Robot) -> None:
    assert offline_robot.is_connected is False
    assert offline_robot.status().connected is False


async def test_conectar_publica_connected(robot: Go2Robot) -> None:
    assert robot.connection.state is ConnectionState.connected
    assert robot.status().state is ConnectionState.connected


async def test_robo_desligado_fica_disconnected(offline_robot: Go2Robot) -> None:
    status = offline_robot.status()

    assert status.state is ConnectionState.disconnected
    assert status.since == offline_robot.connection.since


async def test_subscribe_connection_recebe_as_transicoes(
    robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    recebidas: list[dict[str, str]] = []
    robot.subscribe_connection(recebidas.append)

    factory.connection.pc.emit_state("failed")

    assert recebidas == [{"state": "disconnected", "reason": "failed"}]
    assert robot.status().state is ConnectionState.disconnected


# ─── Reconexão em segundo plano ────────────────────────────────────────────


async def _run_keeper(robot: Go2Robot, seconds: float = 0.05) -> None:
    """Deixa `keep_connected` rodar por um instante e o encerra."""
    keeper = asyncio.create_task(robot.keep_connected(0.01))
    await asyncio.sleep(seconds)
    keeper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await keeper


async def test_keep_connected_nao_mexe_em_conexao_saudavel(
    robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    await _run_keeper(robot)

    assert factory.calls == 1
    assert factory.connection.disconnected is False


async def test_keep_connected_reconecta_quando_o_peer_cai(
    robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    recebidas: list[dict[str, str]] = []
    robot.subscribe_connection(recebidas.append)
    factory.connection.pc.emit_state("failed")

    await _run_keeper(robot)

    assert factory.calls == 2  # reconectou uma vez e parou de tentar
    assert robot.is_connected is True
    assert [r["state"] for r in recebidas] == [
        "disconnected",
        "reconnecting",
        "connected",
    ]


async def test_keep_connected_insiste_ate_o_robo_voltar(
    offline_robot: Go2Robot, factory: FakeConnectionFactory
) -> None:
    factory.connection.connect_error = OSError("sem robô")

    await _run_keeper(offline_robot)

    assert factory.calls >= 2
    assert offline_robot.connection.state is ConnectionState.reconnecting
    assert offline_robot.is_connected is False

    factory.connection.connect_error = None  # o robô voltou
    await _run_keeper(offline_robot)

    status = offline_robot.status()
    assert status.state is ConnectionState.connected
    assert status.connected is True
    await offline_robot.disconnect()


async def test_reconectar_nao_reenvia_comandos(
    robot: Go2Robot, factory: FakeConnectionFactory, pub_sub: FakePubSub
) -> None:
    """O robô volta parado: nada é guardado para depois."""
    await robot.start_move(_move())
    enviados = len(pub_sub.fire_and_forget)
    factory.connection.pc.emit_state("failed")

    await _run_keeper(robot)

    assert robot.is_connected is True
    assert len(pub_sub.fire_and_forget) == enviados


# ─── Postura e gesto ───────────────────────────────────────────────────────


@pytest.mark.parametrize("postura", list(PostureRequest.Posture))
async def test_execute_envia_toda_postura_sem_parametro(
    robot: Go2Robot, pub_sub: FakePubSub, postura: PostureRequest.Posture
) -> None:
    await robot.execute(postura)

    assert pub_sub.api_ids == [SPORT_CMD[postura.sport_cmd]]
    assert pub_sub.parameter_of(0) is None


@pytest.mark.parametrize("gesto", list(GestureRequest.Gesture))
async def test_execute_envia_todo_gesto_sem_parametro(
    robot: Go2Robot, pub_sub: FakePubSub, gesto: GestureRequest.Gesture
) -> None:
    await robot.execute(gesto)

    assert pub_sub.api_ids == [SPORT_CMD[gesto.sport_cmd]]


async def test_execute_cancela_movimento_em_curso(
    robot: Go2Robot, pub_sub: FakePubSub
) -> None:
    await robot.start_move(_move())

    await robot.execute(GestureRequest.Gesture.hello)
    enviados = len(pub_sub.sent)
    await asyncio.sleep(0.1)

    assert pub_sub.api_ids[-1] == SPORT_CMD["Hello"]
    assert len(pub_sub.sent) == enviados  # o reenvio do Move parou


async def test_execute_sem_conexao_levanta_unavailable(offline_robot: Go2Robot) -> None:
    with pytest.raises(RobotUnavailableError):
        await offline_robot.execute(PostureRequest.Posture.stand_up)


# ─── Movimento ─────────────────────────────────────────────────────────────


async def test_stop_cancela_movimento_e_envia_stopmove(
    robot: Go2Robot, pub_sub: FakePubSub
) -> None:
    await robot.start_move(_move())

    await robot.stop()
    enviados = len(pub_sub.sent)
    await asyncio.sleep(0.1)

    assert pub_sub.api_ids[-1] == SPORT_CMD["StopMove"]
    assert len(pub_sub.sent) == enviados


async def test_stop_sem_conexao_levanta_unavailable(offline_robot: Go2Robot) -> None:
    with pytest.raises(RobotUnavailableError):
        await offline_robot.stop()


# ─── Velocidade ────────────────────────────────────────────────────────────


async def test_set_speed_usa_payload_data(robot: Go2Robot, pub_sub: FakePubSub) -> None:
    await robot.set_speed_level(1)

    assert pub_sub.api_ids == [SPORT_CMD["SpeedLevel"]]
    assert pub_sub.parameter_of(0) == {"data": 1}


async def test_get_speed_extrai_nivel_e_devolve_o_cru(
    robot: Go2Robot, pub_sub: FakePubSub
) -> None:
    pub_sub.response = {"data": {"data": 2}}

    leitura = await robot.get_speed_level()

    assert leitura.level == 2
    assert leitura.raw == {"data": 2}


async def test_get_speed_estoura_timeout(robot: Go2Robot, pub_sub: FakePubSub) -> None:
    pub_sub.hang_on_request = True

    with pytest.raises(RobotTimeoutError):
        await robot.get_speed_level()


# ─── Estado ────────────────────────────────────────────────────────────────


async def test_status_le_do_cache_sem_falar_com_o_robo(
    robot: Go2Robot, pub_sub: FakePubSub
) -> None:
    pub_sub.publish_state(RTC_TOPIC["LOW_STATE"], {"bms_state": {"soc": 87}})
    pub_sub.publish_state(RTC_TOPIC["SPORT_MOD_STATE"], {"mode": 1})
    enviados_antes = len(pub_sub.sent)

    status = robot.status()

    assert status.connected is True
    assert status.battery_percent == 87
    assert status.mode == 1
    assert len(pub_sub.sent) == enviados_antes  # nenhum round-trip novo


async def test_raw_state_expoe_o_payload_cru(
    robot: Go2Robot, pub_sub: FakePubSub
) -> None:
    pub_sub.publish_state(RTC_TOPIC["SPORT_MOD_STATE"], {"mode": 3})

    assert robot.raw_state["sport_mode_state"] == {"mode": 3}
