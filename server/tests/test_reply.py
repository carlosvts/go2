"""E-002: motor da resposta falada (store com long-poll, filtro de eco, Llama ocupado).

Llama e Piper falsos: nada aqui prova latência nem comportamento no robô.
"""

import asyncio
import random
from pathlib import Path

import pytest

from app.interpret.interpreter import Interpreter, Thresholds
from app.reply.echo import EchoFilter
from app.reply.engine import Generation, ReplyEngine
from app.reply.store import ReplyStore
from tests.conftest import StubEmbedder

ROOT = Path(__file__).resolve().parent.parent
LLM_DIR = ROOT / "llm"


class FakeLlm:
    def __init__(self, text: str = "Eu. Go2. Robô quadrúpede.", delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.healthy = True
        self.calls: list[str] = []
        self.fail = False

    async def health(self, timeout_s: float) -> bool:
        return self.healthy

    async def generate(self, text: str, timeout_s: float) -> Generation:
        self.calls.append(text)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("falha simulada")
        return Generation(self.text, tokens=5)


class FakeTts:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return b"RIFF" + text.encode()


@pytest.fixture
def echo(catalog) -> EchoFilter:
    interpreter = Interpreter(catalog, StubEmbedder(), Thresholds())
    return EchoFilter.load(interpreter, LLM_DIR, random.Random(0))


def engine(llm, tts, echo, deadline_s=1.0, ttl_s=3.0) -> ReplyEngine:
    return ReplyEngine(llm, tts, echo, ReplyStore(deadline_s, ttl_s))


# ─── Filtro de eco ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Eu. Sentar.",  # comando do catálogo (léxico e lista)
        "Eu. Andar. Frente.",
        "Para.",  # parada
        "Eu. Não. Saber.",  # negação: só as frases fixas têm exceção
        "Eu. Desligar. Motores.",
        "Eu. Dançar. Muito.",
    ],
)
def test_echo_filter_replaces_suspicious_replies(echo, text):
    final, reason = echo.check(text)
    assert reason is not None
    assert final in echo.fallback_replies


@pytest.mark.parametrize("text", ["Eu. Go2. Robô quadrúpede.", "Eu. Amar. Você.", "Oi. Eu. Feliz."])
def test_echo_filter_keeps_harmless_replies(echo, text):
    assert echo.check(text) == (text, None)


def test_echo_filter_sees_commands_hidden_by_many_sentences(echo):
    """5 frases curtas: o interpretador rejeitaria por too_many_clauses sem resolver nada.

    "Senta." no meio só aparece conferindo frase por frase / sem pontuação.
    """
    assert "senta" in echo._forbidden  # garante que o teste é do item 1
    echo._forbidden = frozenset()
    final, reason = echo.check("Eu. Feliz. Senta. Muito. Você.")
    assert reason is not None and reason.startswith("interpreter")


def test_fixed_replies_pass_the_filter_except_for_nao(echo):
    """Nenhuma frase fixa vira comando nem parada; só "não" é exceção na lista."""
    assert len(echo.fallback_replies) >= 3
    for reply in echo.fallback_replies:
        assert echo.command_like(reply) is None, reply
        assert echo.forbidden(reply, allow={"nao"}) is None, reply


# ─── Store: long-poll ──────────────────────────────────────────────────────


async def test_unknown_id_is_not_found():
    store = ReplyStore(1.0, 3.0)
    assert (await store.wait("nada")).found is False


async def test_wait_returns_wav_when_ready():
    store = ReplyStore(1.0, 3.0)
    store.create("u1")

    async def later():
        await asyncio.sleep(0.05)
        store.finish("u1", b"wav")

    asyncio.create_task(later())
    result = await store.wait("u1")
    assert result.found and result.wav == b"wav"


async def test_wait_gives_no_reply_after_deadline():
    store = ReplyStore(0.1, 3.0)
    store.create("u1")
    result = await store.wait("u1")
    assert result.found and result.wav is None


async def test_late_wav_is_discarded():
    store = ReplyStore(0.05, 3.0)
    store.create("u1")
    await asyncio.sleep(0.1)
    store.finish("u1", b"tarde")
    result = await store.wait("u1")
    assert result.found and result.wav is None


async def test_entry_expires_after_ttl():
    store = ReplyStore(0.01, 0.05)
    store.create("u1")
    await asyncio.sleep(0.1)
    assert (await store.wait("u1")).found is False


# ─── Motor ─────────────────────────────────────────────────────────────────


async def test_engine_generates_filters_and_synthesizes(echo):
    llm, tts = FakeLlm(), FakeTts()
    replies = engine(llm, tts, echo)
    replies.start("u1", "qual é o seu nome")
    result = await replies.store.wait("u1")
    assert result.wav == b"RIFF" + "Eu. Go2. Robô quadrúpede.".encode()
    assert llm.calls == ["qual é o seu nome"]


async def test_engine_swaps_echo_before_tts(echo):
    llm, tts = FakeLlm("Eu. Sentar."), FakeTts()
    replies = engine(llm, tts, echo)
    replies.start("u1", "o que você sabe fazer")
    await replies.store.wait("u1")
    assert tts.texts and tts.texts[0] in echo.fallback_replies


async def test_one_generation_at_a_time(echo):
    llm, tts = FakeLlm(delay=0.2), FakeTts()
    replies = engine(llm, tts, echo)
    replies.start("u1", "qual é o seu nome")
    replies.start("u2", "quem te criou")  # chega com a primeira em curso
    second = await replies.store.wait("u2")
    first = await replies.store.wait("u1")
    assert second.found and second.wav is None  # ocupado: sem resposta
    assert first.wav is not None
    assert llm.calls == ["qual é o seu nome"]


async def test_llm_failure_is_no_reply(echo):
    llm, tts = FakeLlm(), FakeTts()
    llm.fail = True
    replies = engine(llm, tts, echo)
    replies.start("u1", "qual é o seu nome")
    result = await replies.store.wait("u1")
    assert result.found and result.wav is None and tts.texts == []


async def test_slow_llm_is_no_reply(echo):
    llm, tts = FakeLlm(delay=0.5), FakeTts()
    replies = engine(llm, tts, echo, deadline_s=0.1)
    replies.start("u1", "qual é o seu nome")
    result = await replies.store.wait("u1")
    assert result.found and result.wav is None
    await replies.close()


async def test_engine_logs_llm_reply(echo, caplog):
    llm, tts = FakeLlm(), FakeTts()
    replies = engine(llm, tts, echo)
    with caplog.at_level("INFO"):
        replies.start("u1", "qual é o seu nome")
        await replies.store.wait("u1")
        await replies.close()
    events = [r for r in caplog.records if getattr(r, "event", None) == "llm_reply"]
    assert len(events) == 1 and events[0].utterance_id == "u1"
