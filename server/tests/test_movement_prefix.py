"""E-003: movimento com palavra antes do verbo e verbo repetido.

Spec: specs/experimentos/E-003-movimento-com-palavra-antes-do-verbo.md.
Testes em texto com embedder falso: não dizem nada sobre o Whisper nem o robô.
"""

import pytest

from app.interpret.evaluate import REJECT, STOP, outcome
from app.interpret.interpreter import Interpreter, Thresholds
from tests.conftest import StubEmbedder

WAKE_WORDS = ["hey jarvis", "jarvis"]


@pytest.fixture
def interpreter(catalog) -> Interpreter:
    return Interpreter(catalog, StubEmbedder(), Thresholds(accept=0.8, margin=0.1))


def run(interpreter: Interpreter, text: str):
    got, result = outcome(interpreter, text, WAKE_WORDS)
    return got, result.reject_reason


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Mudança 1: lista fechada (vamos, bora, lado).
        ("vamos andar para trás", ["move_backward"]),
        ("vamos andar pra frente", ["move_forward"]),
        ("Vamos girar para a esquerda.", ["turn_left"]),
        ("Mas vamos", None),  # sem verbo nem direção: nem chega ao movimento
        ("bora andar pra frente", ["move_forward"]),
        ("anda pro lado direito", ["strafe_right"]),
        ("vira pro lado esquerdo", ["turn_left"]),
        # Mudança 2: verbo repetido do léxico exato.
        ("vai andar para frente", ["move_forward"]),
        ("Vai caminhar pra trás.", ["move_backward"]),
        ("anda anda pra frente", ["move_forward"]),
    ],
)
def test_recovered(interpreter, text, expected):
    if expected is None:
        assert run(interpreter, text)[0] == REJECT
    else:
        assert run(interpreter, text)[0] == expected


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("anda vira para a direita", "movement_ambiguous"),
        ("vai virar para a direita", "movement_ambiguous"),
        ("anda para frente frente", "movement_ambiguous"),
        ("vamos andar", "movement_missing_direction"),
        ("anda pro lado", "movement_missing_direction"),
        ("banana andar pra frente", "movement_unknown_word"),
        ("vamos caminhar 5 passos à frente", "movement_unknown_word"),
        # Fora da lista de propósito (ver Mudança 1 da spec).
        ("Vai pra frente, mas vai pra trás.", "movement_unknown_word"),
        ("você vai pra frente", "movement_unknown_word"),
        ("pode andar para frente?", "movement_unknown_word"),
    ],
)
def test_still_rejected(interpreter, text, reason):
    assert run(interpreter, text) == (REJECT, reason)


def test_stop_prefix_never_becomes_movement(interpreter):
    """`para` é ignorado no movimento; "para de andar pra frente" tem de parar, não andar."""
    assert run(interpreter, "para de andar pra frente")[0] == STOP


def test_fuzzy_verb_is_not_deduplicated(interpreter):
    """Só o léxico exato é deduplicado: "caminhat" (erro de 1 letra de "caminhar") ao lado de
    "anda" continua ambíguo."""
    assert run(interpreter, "caminhat anda para frente") == (REJECT, "movement_ambiguous")
