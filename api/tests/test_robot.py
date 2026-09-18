"""Testes da camada de conexão — formato dos comandos e cache de estado."""

from __future__ import annotations

import asyncio

import pytest
from unitree_webrtc_connect import DATA_CHANNEL_TYPE, RTC_TOPIC, SPORT_CMD

from app.robot import RobotConnection, RobotTimeoutError, RobotUnavailableError


async def test_posture_envia_api_id_correto(robot: RobotConnection, pub_sub) -> None:
    await robot.posture("StandUp")

    assert pub_sub.api_ids == [SPORT_CMD["StandUp"]]
    enviado = pub_sub.sent[0]
    assert enviado["topic"] == RTC_TOPIC["SPORT_MOD"]
    assert enviado["type"] == DATA_CHANNEL_TYPE["REQUEST"]
    # Postura não leva parâmetro.
    assert enviado["data"]["parameter"] == ""


async def test_move_usa_payload_x_y_yaw(robot: RobotConnection, pub_sub) -> None:
    await robot.start_move(vx=0.3, vy=-0.1, vyaw=0.5, duration_s=0.05)

    assert pub_sub.api_ids[0] == SPORT_CMD["Move"]
    assert pub_sub.parameter_of(0) == {"x": 0.3, "y": -0.1, "yaw": 0.5}


async def test_move_reenvia_e_para_no_fim_da_janela(
    robot: RobotConnection, pub_sub
) -> None:
    # 50Hz durante 0.2s: o disparo imediato mais ~10 reenvios, e um StopMove.
    await robot.start_move(vx=0.2, vy=0.0, vyaw=0.0, duration_s=0.2)
    await asyncio.sleep(0.4)

    ids = pub_sub.api_ids
    assert ids[-1] == SPORT_CMD["StopMove"]
    reenvios = [i for i in ids if i == SPORT_CMD["Move"]]
    assert len(reenvios) > 3, f"esperava reenvio contínuo, veio {ids}"


async def test_move_novo_cancela_o_anterior(robot: RobotConnection) -> None:
    await robot.start_move(vx=0.2, vy=0.0, vyaw=0.0, duration_s=5.0)
    primeira = robot._move_task

    await robot.start_move(vx=0.4, vy=0.0, vyaw=0.0, duration_s=0.05)

    assert primeira is not None and primeira.cancelled()
    await robot.stop()


async def test_stop_cancela_movimento_e_envia_stopmove(
    robot: RobotConnection, pub_sub
) -> None:
    await robot.start_move(vx=0.2, vy=0.0, vyaw=0.0, duration_s=5.0)
    tarefa = robot._move_task

    await robot.stop()

    assert tarefa is not None and tarefa.cancelled()
    assert pub_sub.api_ids[-1] == SPORT_CMD["StopMove"]


async def test_posture_interrompe_movimento_em_curso(robot: RobotConnection) -> None:
    await robot.start_move(vx=0.2, vy=0.0, vyaw=0.0, duration_s=5.0)
    tarefa = robot._move_task

    await robot.posture("Damp")

    assert tarefa is not None and tarefa.cancelled()


async def test_set_speed_usa_payload_data(robot: RobotConnection, pub_sub) -> None:
    await robot.set_speed_level(1)

    assert pub_sub.api_ids == [SPORT_CMD["SpeedLevel"]]
    assert pub_sub.parameter_of(0) == {"data": 1}


async def test_get_speed_extrai_nivel_da_resposta(
    robot: RobotConnection, pub_sub
) -> None:
    pub_sub.response = {"data": {"data": 2}}

    level, raw = await robot.get_speed_level()

    assert level == 2
    assert raw == {"data": 2}


async def test_get_speed_devolve_none_em_formato_desconhecido(
    robot: RobotConnection, pub_sub
) -> None:
    """Formato não reconhecido vira `None` — nunca um valor inventado."""
    pub_sub.response = {"data": {"algo_inesperado": 9}}

    level, raw = await robot.get_speed_level()

    assert level is None
    assert raw == {"algo_inesperado": 9}


async def test_get_speed_estoura_timeout(robot: RobotConnection, pub_sub) -> None:
    async def nunca_responde(topic, options=None):
        await asyncio.sleep(10)

    pub_sub.publish_request_new = nunca_responde

    with pytest.raises(RobotTimeoutError):
        await robot.get_speed_level()


# ─── Robô inacessível ──────────────────────────────────────────────────────


async def test_comando_sem_conexao_levanta_unavailable(
    offline_robot: RobotConnection,
) -> None:
    with pytest.raises(RobotUnavailableError):
        await offline_robot.posture("StandUp")


async def test_datachannel_fechado_conta_como_desconectado(
    robot: RobotConnection, fake_conn
) -> None:
    fake_conn.datachannel.data_channel_opened = False

    assert robot.is_connected is False
    with pytest.raises(RobotUnavailableError):
        await robot.stop()


async def test_nao_reconecta_sozinho(robot: RobotConnection, fake_conn) -> None:
    """Queda de conexão não dispara reconexão silenciosa."""
    fake_conn.isConnected = False

    with pytest.raises(RobotUnavailableError):
        await robot.posture("StandUp")

    assert robot._conn is fake_conn  # nenhuma conexão nova foi criada


# ─── Cache de estado ───────────────────────────────────────────────────────


async def test_assina_os_topicos_de_estado_uma_vez(
    robot: RobotConnection, pub_sub
) -> None:
    assert set(pub_sub.subscriptions) == {
        RTC_TOPIC["SPORT_MOD_STATE"],
        RTC_TOPIC["LOW_STATE"],
    }


async def test_status_le_do_cache_sem_falar_com_o_robo(
    robot: RobotConnection, pub_sub
) -> None:
    pub_sub.subscriptions[RTC_TOPIC["LOW_STATE"]](
        {"topic": RTC_TOPIC["LOW_STATE"], "data": {"bms_state": {"soc": 87}}}
    )
    pub_sub.subscriptions[RTC_TOPIC["SPORT_MOD_STATE"]](
        {"topic": RTC_TOPIC["SPORT_MOD_STATE"], "data": {"mode": 1}}
    )
    enviados_antes = len(pub_sub.sent)

    snapshot = robot.status()

    assert snapshot.connected is True
    assert snapshot.battery_percent == 87
    assert snapshot.mode == 1
    assert len(pub_sub.sent) == enviados_antes  # nenhum round-trip novo


async def test_status_sem_estado_recebido(robot: RobotConnection) -> None:
    snapshot = robot.status()

    assert snapshot.battery_percent is None
    assert snapshot.mode is None
    assert snapshot.low_state_age_s is None


async def test_gesture_envia_api_id_sem_parametro(
    robot: RobotConnection, pub_sub
) -> None:
    await robot.gesture("Hello")

    assert pub_sub.api_ids == [SPORT_CMD["Hello"]]
    assert pub_sub.sent[0]["data"]["parameter"] == ""


async def test_gesture_cancela_movimento_em_curso(
    robot: RobotConnection, pub_sub
) -> None:
    await robot.start_move(vx=0.2, vy=0.0, vyaw=0.0, duration_s=5.0)
    await robot.gesture("Hello")
    enviados = len(pub_sub.sent)
    await asyncio.sleep(0.1)

    assert pub_sub.api_ids[-1] == SPORT_CMD["Hello"]
    assert len(pub_sub.sent) == enviados  # o reenvio do Move parou
