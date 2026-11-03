"""E-001: recuperação por regex de cláusulas rejeitadas (specs/experimentos/E-001-...).

A regex só roda numa cláusula rejeitada por incerteza (gestos) ou por palavra
desconhecida no movimento, e nunca transforma parada em comando nem assume
uma direção.
"""

from pathlib import Path

import pytest
import yaml

from app.interpret.evaluate import REJECT, STOP, outcome
from app.interpret.interpreter import Interpreter, Thresholds
from app.interpret.recovery import ALLOWED_GESTURES, RecoveryError, RegexRecovery
from app.interpret.text import words
from tests.conftest import ROOT, StubEmbedder

WAKE_WORDS = ["hey jarvis", "jarvis"]
PATTERNS = ROOT / "regex" / "patterns.yaml"

# Padrões só dos testes, para não depender do conteúdo do arquivo real.
TEST_PATTERNS = {
    "gestures": {
        "stand_down": {"patterns": ["pode deitar"], "examples": ["pode deitar"]},
        "stand_up": {"patterns": ["pode levantar"], "examples": ["pode levantar"]},
        "sit": {"patterns": ["senta (?:no chao|para mim)"], "examples": ["senta no chão"]},
        "hello": {"patterns": ["acena para mim"], "examples": ["acena para mim"]},
        "stretch": {"patterns": ["abaixa"], "examples": ["abaixa"]},
        "wiggle_hips": {"patterns": ["abaixa"], "examples": ["abaixa"]},
    },
    "movement": {
        "verb_words": {"andar": ["avance", "bora"], "virar": ["rode"]},
        "patterns": [
            r"(?P<verb>\w+)(?: rapidinho)? para (?:a |o |ao |as |os )?(?:lado )?(?P<direction>\w+)",
            r"(?P<verb>\w+) de (?P<direction>re)",
        ],
        "examples": ["avance para frente"],
    },
}


@pytest.fixture
def stub() -> StubEmbedder:
    return StubEmbedder()


@pytest.fixture
def recovery(catalog) -> RegexRecovery:
    return RegexRecovery(catalog, TEST_PATTERNS)


@pytest.fixture
def interpreter(catalog, stub, recovery) -> Interpreter:
    return Interpreter(catalog, stub, Thresholds(accept=0.8, margin=0.1), recovery=recovery)


def run(interpreter: Interpreter, text: str):
    return outcome(interpreter, text, WAKE_WORDS)


# ─── Gestos e posturas ─────────────────────────────────────────────────────


def test_low_similarity_gesture_is_recovered(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "fora": 0.9})
    commands, result = run(interpreter, "pode deitar")
    assert commands == ["stand_down"]
    clause = result.clauses[0]
    assert clause.method == "regex"
    assert clause.recovered_from == "low_similarity"


def test_ambiguous_gesture_is_recovered(catalog, stub, recovery):
    interpreter = Interpreter(catalog, stub, Thresholds(accept=0.6, margin=0.1), recovery=recovery)
    stub.mix("pode deitar", {"deita": 0.72, "senta": 0.69})
    commands, result = run(interpreter, "pode deitar")
    assert commands == ["stand_down"]
    assert result.clauses[0].recovered_from == "ambiguous"


def test_without_recovery_the_same_clause_is_rejected(catalog, stub):
    interpreter = Interpreter(catalog, stub, Thresholds(accept=0.8, margin=0.1))
    stub.mix("pode deitar", {"deita": 0.5, "fora": 0.9})
    assert run(interpreter, "pode deitar")[0] == REJECT


def test_stop_like_top1_is_never_recovered(interpreter, stub):
    """Parada abaixo de stop_accept sai como low_similarity: não pode virar gesto."""
    stub.mix("pode deitar", {"parar": 0.5, "fora": 0.9})
    commands, result = run(interpreter, "pode deitar")
    assert commands == REJECT
    assert result.clauses[0].label == "__stop__"


def test_stop_like_top2_is_never_recovered(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "parar": 0.45, "fora": 0.9})
    commands, result = run(interpreter, "pode deitar")
    assert commands == REJECT
    assert result.clauses[0].runner_up == "__stop__"


def test_movement_like_top1_is_never_recovered_as_gesture(interpreter, stub):
    stub.mix("pode deitar", {"andar para frente": 0.5, "fora": 0.9})
    assert run(interpreter, "pode deitar")[0] == REJECT


def test_movement_like_top2_is_never_recovered_as_gesture(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "virar para direita": 0.45, "fora": 0.9})
    assert run(interpreter, "pode deitar")[0] == REJECT


def test_stop_word_blocks_the_gesture_path(interpreter, stub):
    """Em gestos, nenhuma palavra de parada passa, nem como preposição."""
    stub.mix("acena para mim", {"acena": 0.5, "fora": 0.9})
    assert run(interpreter, "acena para mim")[0] == REJECT


def test_gesture_path_needs_the_embedder(catalog, recovery):
    interpreter = Interpreter(catalog, None, recovery=recovery)
    assert run(interpreter, "pode deitar")[0] == REJECT


def test_pattern_matching_two_commands_is_rejected(interpreter, stub):
    stub.mix("abaixa", {"alonga": 0.5, "fora": 0.9})
    assert run(interpreter, "abaixa")[0] == REJECT


def test_other_rejection_reasons_are_not_recovered(interpreter, stub):
    """Comando desabilitado e lexical_only continuam rejeitados."""
    stub.mix("pode deitar", {"faz uma pose": 1.0})
    _, result = run(interpreter, "pode deitar")
    assert result.reject_reason == "command_disabled"
    stub.mix("pode levantar", {"desligar motores": 1.0})
    _, result = run(interpreter, "pode levantar")
    assert result.reject_reason == "lexical_only_command"


def test_negation_is_never_recovered(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "fora": 0.9})
    assert run(interpreter, "não pode deitar")[0] == REJECT


# ─── Várias cláusulas ──────────────────────────────────────────────────────


def test_one_recovered_clause_next_to_a_resolved_one(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "fora": 0.9})
    assert run(interpreter, "levanta e pode deitar")[0] == ["stand_up", "stand_down"]


def test_two_candidate_clauses_keep_the_sentence_rejected(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "fora": 0.9})
    stub.mix("pode levantar", {"levanta": 0.5, "fora": 0.9})
    assert run(interpreter, "pode deitar e pode levantar")[0] == REJECT


def test_other_clause_rejected_for_another_reason_keeps_it_rejected(interpreter, stub):
    stub.mix("pode deitar", {"deita": 0.5, "fora": 0.9})
    stub.mix("faz uma pose bonita", {"faz uma pose": 1.0})
    assert run(interpreter, "pode deitar e faz uma pose bonita")[0] == REJECT


# ─── Movimento ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("avance para frente", ["move_forward"]),  # verbo da lista do padrão
        ("bora para trás", ["move_backward"]),
        ("anda rapidinho para frente", ["move_forward"]),  # verbo do léxico
        ("anda rapidinho pra frente", ["move_forward"]),  # "pra" vira "para"
        ("vira para o lado direito", ["turn_right"]),  # "lado" e "direito" (1 letra)
        ("vira pro lado esquerdo", ["turn_left"]),
        ("avance para o lado direito", ["strafe_right"]),
        ("rode para a direita", ["turn_right"]),
        ("anda de ré", ["move_backward"]),
    ],
)
def test_movement_with_explicit_direction_is_recovered(interpreter, text, expected):
    commands, result = run(interpreter, text)
    assert commands == expected
    assert result.clauses[0].method == "regex"
    assert result.clauses[0].recovered_from == "movement_unknown_word"


@pytest.mark.parametrize(
    "text",
    [
        "anda rapidinho",  # sem direção: nunca assume uma
        "bora lá",
        "pula para frente",  # verbo que não é de movimento
        "olha para a direita",
        "dança para frente",
        "rebola para a direita",
        "para frente",  # direção sozinha (movement_missing_verb)
        "para de andar",  # "para" que não é preposição de direção
        "vira rapidinho para frente",  # virar + frente não existe
        "anda rapidinho para frente para trás",  # duas direções
        "vira avance para frente",  # dois verbos diferentes
    ],
)
def test_movement_without_a_clear_direction_or_verb_is_rejected(interpreter, text):
    assert run(interpreter, text)[0] == REJECT


def test_stop_still_wins(interpreter):
    assert run(interpreter, "anda rapidinho para frente para")[0] == STOP


# ─── Arquivo de padrões ────────────────────────────────────────────────────


def test_damp_can_never_be_a_pattern(catalog):
    data = {"gestures": {"damp": {"patterns": ["desliga tudo"], "examples": []}}}
    with pytest.raises(RecoveryError):
        RegexRecovery(catalog, data)


def test_command_outside_the_allowed_set_is_refused(catalog):
    for name in ("pose", "stop", "move_forward", "inexistente"):
        with pytest.raises(RecoveryError):
            RegexRecovery(catalog, {"gestures": {name: {"patterns": ["x"], "examples": []}}})


def test_movement_pattern_needs_both_groups(catalog):
    data = {"movement": {"verb_words": {}, "patterns": [r"\w+ para (?P<direction>\w+)"]}}
    with pytest.raises(RecoveryError):
        RegexRecovery(catalog, data)


def test_verb_word_must_name_a_catalog_verb(catalog):
    data = {"movement": {"verb_words": {"pular": ["pula"]}, "patterns": []}}
    with pytest.raises(RecoveryError):
        RegexRecovery(catalog, data)


def test_allowed_set_is_the_one_in_the_spec():
    expected = frozenset(
        {
            "stand_up", "sit", "stand_down", "hello", "stretch", "finger_heart", "rise_sit",
            "balance_stand", "recovery_stand", "wiggle_hips", "dance1", "dance2", "scrape",
        }
    )  # fmt: skip
    assert expected == ALLOWED_GESTURES


def test_real_patterns_file_loads(catalog):
    RegexRecovery.from_file(catalog, PATTERNS)


def test_real_patterns_never_fire_on_reject_or_stop_phrases(catalog):
    """Nenhum padrão do arquivo real dispara em frase `reject`/`stop` do conjunto 1.

    Pior caso: toda cláusula rejeitada é testada nos dois caminhos, como se o
    embedding a deixasse passar pelo gatilho.
    """
    recovery = RegexRecovery.from_file(catalog, PATTERNS)
    plain = Interpreter(catalog, None)
    cases = yaml.safe_load((ROOT / "eval" / "phrases.yaml").read_text(encoding="utf-8"))
    fired = []
    for case in cases:
        if case["expect"] not in (REJECT, STOP):
            continue
        _, result = outcome(plain, case["text"], WAKE_WORDS)
        for clause in result.clauses:
            if not clause.reject_reason:
                continue
            tokens = words(catalog.tokenize(clause.text))
            hit = recovery.match_gesture(tokens) or recovery.match_movement(tokens)
            if hit:
                fired.append((case["text"], hit))
    assert fired == []


def test_real_patterns_recover_their_own_examples(catalog):
    """Cada exemplo escrito no arquivo é pego pelo seu próprio padrão."""
    recovery = RegexRecovery.from_file(catalog, PATTERNS)
    data = yaml.safe_load(Path(PATTERNS).read_text(encoding="utf-8"))
    for name, block in data.get("gestures", {}).items():
        for example in block["examples"]:
            assert recovery.match_gesture(words(catalog.tokenize(example))) == name, example
    for example in data["movement"]["examples"]:
        assert recovery.match_movement(words(catalog.tokenize(example))), example


# ─── Achados da revisão de código ──────────────────────────────────────────


@pytest.fixture
def real(catalog) -> RegexRecovery:
    return RegexRecovery.from_file(catalog, PATTERNS)


@pytest.mark.parametrize(
    "text",
    [
        "segue direito",  # quer dizer "em frente"; "direito" viraria direita
        "siga direito",
        "anda devagar para frente",  # pediu devagar: não pode sair na velocidade normal
        "anda devagarinho para trás",
    ],
)
def test_real_patterns_refuse_misleading_movement(real, catalog, text):
    assert real.match_movement(words(catalog.tokenize(text))) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("vira ao lado direito", "turn_right"), ("anda pro lado esquerdo", "strafe_left")],
)
def test_real_patterns_accept_every_article_of_c1(real, catalog, text, expected):
    assert real.match_movement(words(catalog.tokenize(text))) == expected


@pytest.mark.parametrize(
    "data",
    [
        {"gestures": {"sit": None}},
        {"gestures": ["sit"]},
        {"gestures": {"sit": {"patterns": "senta ai"}}},
        {"movement": ["x"]},
        {"movement": {"verb_words": ["bora"]}},
        {"movement": {"verb_words": {"andar": "bora"}}},
    ],
)
def test_malformed_file_gives_the_aggregated_error(catalog, data):
    with pytest.raises(RecoveryError):
        RegexRecovery(catalog, data)
