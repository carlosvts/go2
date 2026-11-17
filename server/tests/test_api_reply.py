"""E-002 pelos endpoints: status `thinking`, `reply_pending`, despacho parcial e GET /v1/reply.

go2-api, transcrição, Llama e Piper falsos. Não prova latência nem o robô.
"""

import asyncio
import json

import httpx
import pytest

from app import main
from app.config import Settings
from tests.conftest import FakeTranscriber, StubEmbedder
from tests.test_reply import FakeLlm, FakeTts


@pytest.fixture
def stt() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


@pytest.fixture
def tts() -> FakeTts:
    return FakeTts()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, save_dir=tmp_path / "captures", llm_health_interval_s=0.05)


@pytest.fixture
async def make_client(monkeypatch, fast_catalog, go2, stt, llm, tts):
    monkeypatch.setattr(main, "load_catalog", lambda path: fast_catalog)
    stack = []

    async def factory(settings: Settings, with_llm: bool = True) -> httpx.AsyncClient:
        app = main.create_app(
            settings,
            transcriber=stt,
            embedder=StubEmbedder(),
            go2=go2,
            llm=llm if with_llm else None,
            synthesizer=tts if with_llm else None,
        )
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        client.app = app
        stack.append((client, lifespan))
        return client

    yield factory
    for client, lifespan in stack:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


@pytest.fixture
async def client(make_client, settings):
    return await make_client(settings)


@pytest.fixture
def order(client, monkeypatch) -> list:
    """Ordem de `submit` × início da geração, para a invariante de auditoria."""
    events: list = []
    service = client.app.state.service
    submit, start = service.dispatcher.submit, service.replies.engine.start

    def spy_submit(commands, edge_id, utterance_id):
        events.append(("submit", list(commands), utterance_id))
        return submit(commands, edge_id, utterance_id)

    def spy_start(utterance_id, text):
        events.append(("llm", text, utterance_id))
        return start(utterance_id, text)

    monkeypatch.setattr(service.dispatcher, "submit", spy_submit)
    monkeypatch.setattr(service.replies.engine, "start", spy_start)
    return events


def meta(utterance_id="u1", edge_id="tvbox-sala") -> str:
    return json.dumps({"utterance_id": utterance_id, "edge_id": edge_id, "reason": "wake_word"})


async def post(client, audio: bytes, meta_json: str):
    return await client.post(
        "/v1/utterance",
        files={"audio": ("utterance.wav", audio, "audio/wav")},
        data={"meta": meta_json},
    )


async def drain(client) -> None:
    await asyncio.wait_for(client.app.state.service.dispatcher.wait_idle(), timeout=5)


# ─── Só conversa ───────────────────────────────────────────────────────────


async def test_pure_conversation_is_thinking(client, stt, go2, llm, order):
    response = await post(client, stt.say(1.0, "Qual é o seu nome?"), meta())
    body = response.json()
    assert body["status"] == "thinking"
    assert body["reply_pending"] is True
    assert body["commands"] == [] and body["reject_reason"] is None
    reply = await client.get("/v1/reply/u1")
    assert reply.status_code == 200 and reply.headers["content-type"] == "audio/wav"
    assert reply.content.startswith(b"RIFF")
    await drain(client)
    assert go2.calls == []
    # Invariante: só conversa ⇒ 0 submit.
    assert [e for e in order if e[0] == "submit"] == []
    assert llm.calls == ["qual é o seu nome"]


async def test_long_poll_waits_for_the_reply(client, stt, llm):
    llm.delay = 0.2
    await post(client, stt.say(1.0, "quem te criou"), meta())
    reply = await client.get("/v1/reply/u1")
    assert reply.status_code == 200


async def test_failed_generation_is_204(client, stt, llm):
    llm.fail = True
    await post(client, stt.say(1.0, "quem te criou"), meta())
    assert (await client.get("/v1/reply/u1")).status_code == 204


async def test_unknown_reply_is_404(client):
    assert (await client.get("/v1/reply/nunca-existiu")).status_code == 404


async def test_duplicate_utterance_generates_once(client, stt, llm):
    audio = stt.say(1.0, "quem te criou")
    first = (await post(client, audio, meta())).json()
    second = (await post(client, audio, meta())).json()
    assert first == second
    await client.get("/v1/reply/u1")
    assert llm.calls == ["quem te criou"]


async def test_noise_stays_rejected(client, stt, llm):
    body = (await post(client, stt.say(1.0, "banana"), meta())).json()
    assert body["status"] == "rejected" and body["reject_reason"] == "low_similarity"
    assert body["reply_pending"] is False and llm.calls == []


async def test_stop_is_untouched(client, stt, go2, llm):
    body = (await post(client, stt.say(1.0, "para"), meta())).json()
    assert body["status"] == "stopped" and body["reply_pending"] is False
    assert "stop" in go2.calls and llm.calls == []


# ─── Mista ─────────────────────────────────────────────────────────────────


async def test_mixed_dispatches_then_replies(client, stt, go2, llm, order):
    body = (await post(client, stt.say(1.0, "Senta e fala seu nome."), meta())).json()
    assert body["status"] == "enqueued"
    assert body["commands"] == [{"id": "sit"}]
    assert body["reply_pending"] is True
    assert (await client.get("/v1/reply/u1")).status_code == 200
    await drain(client)
    assert go2.calls == ["sit"]
    # Invariante: um submit só, ANTES da geração, com os comandos aceitos.
    assert order == [("submit", ["sit"], "u1"), ("llm", "fala seu nome", "u1")]


async def test_llm_output_is_never_dispatched(client, stt, go2, llm, tts, order):
    llm.text = "Eu. Sentar. Agora."  # a resposta "pede" um comando
    await post(client, stt.say(1.0, "qual é o seu nome"), meta())
    await client.get("/v1/reply/u1")
    await drain(client)
    assert go2.calls == []
    assert [e for e in order if e[0] == "submit"] == []
    assert tts.texts[0] in client.app.state.service.replies.engine.echo.fallback_replies


async def test_mixed_refused_by_queue_does_not_reach_llm(make_client, settings, stt, go2, llm):
    client = await make_client(settings.model_copy(update={"cross_edge_policy": "reject"}))
    go2.hold = "stand_up"
    await post(client, stt.say(1.0, "levanta"), meta("u0", "outra-tvbox"))
    await asyncio.wait_for(go2.holding.wait(), timeout=2)
    body = (await post(client, stt.say(1.2, "senta e fala seu nome"), meta())).json()
    assert body["status"] == "rejected" and body["reject_reason"] == "busy_other_edge"
    assert body["reply_pending"] is False and llm.calls == []
    go2.release.set()
    await drain(client)


async def test_partial_dispatch_is_logged(client, stt, caplog):
    with caplog.at_level("INFO"):
        await post(client, stt.say(1.0, "senta e fala seu nome"), meta())
        await client.get("/v1/reply/u1")
    events = [getattr(r, "event", None) for r in caplog.records]
    assert "partial_dispatch" in events and "llm_reply" in events
    assert events.index("partial_dispatch") < events.index("llm_reply")


# ─── F5, F6 e E-002 desligada ──────────────────────────────────────────────


async def test_unhealthy_llm_behaves_like_today(client, stt, llm):
    llm.healthy = False
    await asyncio.sleep(0.15)  # o monitor em segundo plano percebe
    body = (await post(client, stt.say(1.0, "qual é o seu nome"), meta())).json()
    assert body["status"] == "rejected" and body["reject_reason"] == "low_similarity"
    assert body["reply_pending"] is False and llm.calls == []
    mixed = (await post(client, stt.say(1.2, "senta e fala seu nome"), meta("u2"))).json()
    assert mixed["status"] == "rejected" and mixed["commands"] == []


async def test_stale_conversation_is_rejected(make_client, settings, stt, llm):
    client = await make_client(settings.model_copy(update={"max_utterance_age_s": 0.05}))
    body = (await post(client, stt.say(1.0, "quem te criou", delay=0.1), meta())).json()
    assert body["status"] == "rejected" and body["reject_reason"] == "stale"
    assert llm.calls == []


async def test_disabled_by_default_changes_nothing(make_client, settings, stt):
    client = await make_client(settings, with_llm=False)
    assert client.app.state.service.replies is None
    body = (await post(client, stt.say(1.0, "qual é o seu nome"), meta())).json()
    assert body["status"] == "rejected" and body["reply_pending"] is False
    assert (await client.get("/v1/reply/u1")).status_code == 404


async def test_stats_count_thinking_and_mixed(client, stt):
    await post(client, stt.say(1.0, "quem te criou"), meta())
    await post(client, stt.say(1.2, "senta e fala seu nome"), meta("u2"))
    by_status = (await client.get("/v1/stats")).json()["wake_word"]["by_status"]
    assert by_status.get("thinking") == 1 and by_status.get("enqueued_with_reply") == 1
