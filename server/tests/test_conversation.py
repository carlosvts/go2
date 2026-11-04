"""E-002: a camada que decide se uma frase rejeitada vai ao Llama (C1–C4, F1–F4).

Embeddings falsos (StubEmbedder): texto desconhecido tem cosseno 0 com todos os
exemplos, então cai em `low_similarity`, com top-1/top-2 de gestos.
"""

from pathlib import Path

import pytest

from app.conversation import ConversationRules, Route, decide
from app.interpret.interpreter import STOP_CLASS, Interpreter, Kind, Thresholds
from app.wake_word import strip_wake_word
from tests.conftest import StubEmbedder

ROOT = Path(__file__).resolve().parent.parent
WAKE_WORDS = ["hey jarvis", "ei jarvis", "jarvis"]


@pytest.fixture(scope="module")
def rules() -> ConversationRules:
    return ConversationRules.load(ROOT / "llm" / "conversation_markers.yaml")


@pytest.fixture
def stub() -> StubEmbedder:
    return StubEmbedder()


@pytest.fixture
def interpreter(catalog, stub) -> Interpreter:
    return Interpreter(catalog, stub, Thresholds())


def route(interpreter, catalog, rules, raw: str, embedder_loaded: bool = True):
    text, _ = strip_wake_word(raw, WAKE_WORDS)
    interpretation = interpreter.interpret(text)
    return decide(interpretation, text, catalog, rules, embedder_loaded), interpretation


# ─── Clause registra top-1/top-2 e a origem dos slots ──────────────────────


def test_rejected_clause_logs_top_labels(interpreter):
    result = interpreter.interpret("qual é o seu nome")
    assert result.kind is Kind.REJECTED and result.reject_reason == "low_similarity"
    clause = result.clauses[0]
    assert clause.top1 is not None and clause.top2 is not None
    assert "top1" in clause.log() and "top2" in clause.log()


def test_lexical_slots_are_marked(interpreter):
    clause = interpreter.interpret("anda para frente").clauses[0]
    assert clause.command_id == "move_forward" and clause.slots_lexical is True


# ─── Só conversa ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["qual é o seu nome", "quem te criou", "o que você sabe fazer", "fala pra mim quem é você"],
)
def test_pure_conversation_goes_to_llm(interpreter, catalog, rules, text):
    decision, _ = route(interpreter, catalog, rules, text)
    assert decision.route is Route.PURE
    assert decision.commands == []
    assert decision.text


def test_wake_word_is_not_sent_to_llm(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "hey jarvis qual é o seu nome")
    assert decision.route is Route.PURE and "jarvis" not in decision.text


# ─── C4: filtro de ruído ───────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["banana", "banana azul grande", "toca uma música", "bom dia"])
def test_noise_does_not_go_to_llm(interpreter, catalog, rules, text):
    decision, _ = route(interpreter, catalog, rules, text)
    assert decision.route is Route.NONE


def test_fillers_do_not_count_as_words(interpreter, catalog, rules):
    # "por favor" e "robô" são enchimento: sobram 2 palavras.
    decision, _ = route(interpreter, catalog, rules, "por favor robô quem é")
    assert decision.route is Route.NONE


# ─── C2 e C3 ───────────────────────────────────────────────────────────────


def test_without_embedder_nothing_goes_to_llm(catalog, rules):
    interpreter = Interpreter(catalog, None, Thresholds())
    decision, _ = route(interpreter, catalog, rules, "qual é o seu nome", embedder_loaded=False)
    assert decision.route is Route.NONE


def test_stop_like_top_label_blocks(interpreter, catalog, rules, stub):
    # Parecida com parada, mas abaixo do limiar de parada: low_similarity com
    # top-1 __stop__. Nunca vira conversa.
    stub.mix("chega disso você", {"pare": 0.6, "outro eixo": 0.8})
    decision, interpretation = route(interpreter, catalog, rules, "chega disso você")
    assert interpretation.reject_reason == "low_similarity"
    assert STOP_CLASS in (interpretation.clauses[0].top1, interpretation.clauses[0].top2)
    assert decision.route is Route.NONE


# ─── Mista ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "commands"),
    [
        ("senta e fala seu nome", ["sit"]),
        ("levanta e me diz quem é você", ["stand_up"]),
        ("andar para frente e qual é o seu nome", ["move_forward"]),
        ("vira à direita e qual é o seu nome", ["turn_right"]),
        ("anda adiante e me conta uma piada", ["move_forward"]),
    ],
)
def test_mixed_dispatches_and_goes_to_llm(interpreter, catalog, rules, text, commands):
    decision, _ = route(interpreter, catalog, rules, text)
    assert decision.route is Route.MIXED
    assert decision.commands == commands
    assert decision.text  # só a cláusula de conversa


def test_mixed_sends_only_the_conversation_clause(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "senta e fala seu nome")
    assert "senta" not in decision.text and "nome" in decision.text


def test_mixed_with_noise_is_rejected(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "senta e banana")
    assert decision.route is Route.NONE


def test_f4_embedding_command_blocks(interpreter, catalog, rules, stub):
    # "a gente senta" aceita por embedding: na mista, rejeita tudo.
    stub.mix("a gente senta", {"senta": 1.0})
    decision, interpretation = route(
        interpreter, catalog, rules, "a gente senta e depois você me conta como foi"
    )
    assert any(c.command_id == "sit" and c.method == "embedding" for c in interpretation.clauses)
    assert decision.route is Route.NONE


def test_f4_damp_blocks(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "desligar motores e qual é o seu nome")
    assert decision.route is Route.NONE


def test_f3_two_conversation_clauses_block(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "qual é o seu nome e quem te criou")
    assert decision.route is Route.NONE


def test_f2_other_rejection_blocks(interpreter, catalog, rules):
    # "anda para cima": movimento sem direção conhecida (movement_*), outra rejeição.
    decision, _ = route(interpreter, catalog, rules, "anda para cima e qual é o seu nome")
    assert decision.route is Route.NONE


def test_negation_blocks(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "senta e não fala nada")
    assert decision.route is Route.NONE


# ─── F1: palavras de parada ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "pare de falar e me conta uma piada",  # "pare" em qualquer lugar
        "você pode parar de me seguir",  # "parar"
        "ei para de me seguir",  # "para de"
        "olha para com isso que você tá fazendo",  # "para com"
        "robô para de me seguir",  # posição depois dos fillers
        "hey jarvis para de me seguir",  # posição depois da wake word
        "você para de dançar",
        "você vai bater para e anda para trás",  # "para" no fim da cláusula
        "senta e você para com isso",
        "senta e pra que você serve",  # "para" abrindo a conversa
    ],
)
def test_stop_attempts_never_go_to_llm(interpreter, catalog, rules, text):
    decision, interpretation = route(interpreter, catalog, rules, text)
    assert decision.route is Route.NONE


def test_stop_by_interpreter_is_untouched(interpreter, catalog, rules):
    decision, interpretation = route(interpreter, catalog, rules, "anda para frente e para")
    assert interpretation.kind is Kind.STOP
    assert decision.route is Route.NONE


def test_accepted_non_movement_clause_with_para_blocks(interpreter, catalog, rules, stub):
    stub.mix("para senta", {"senta": 1.0})
    decision, interpretation = route(interpreter, catalog, rules, "para senta e qual é o seu nome")
    assert decision.route is Route.NONE


@pytest.mark.parametrize(
    "text",
    [
        "você pode parar de me seguir",
        "ei para de me seguir",
        "olha para com isso que você tá fazendo",
        "robô para de me seguir",
        "hey jarvis para de me seguir",
        "você para de dançar",
        "você está batendo para e anda para trás",  # "para" no fim da cláusula
        "senta e você para com isso",
        "senta e pra que você serve",
    ],
)
def test_f1_is_what_blocks(interpreter, catalog, rules, text):
    """Os casos acima chegam a ter cláusula de conversa: quem barra é o F1."""
    decision, _ = route(interpreter, catalog, rules, text)
    assert decision.reason == "f1_stop_word"


def test_para_in_the_middle_of_conversation_passes(interpreter, catalog, rules):
    decision, _ = route(interpreter, catalog, rules, "fala pra mim quem é você")
    assert decision.route is Route.PURE


@pytest.mark.parametrize(
    "text",
    ["fala para mim quem é você", "conta para ele quem te criou", "diz para a gente quem é você"],
)
def test_para_followed_by_pronoun_passes(interpreter, catalog, rules, text):
    decision, _ = route(interpreter, catalog, rules, text)
    assert decision.route is Route.PURE


@pytest.mark.parametrize("text", ["você para já que eu mandei", "ei você para agora mesmo"])
def test_para_without_pronoun_blocks(interpreter, catalog, rules, text):
    decision, _ = route(interpreter, catalog, rules, text)
    assert decision.reason == "f1_stop_word"
