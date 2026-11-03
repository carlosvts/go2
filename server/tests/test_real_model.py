"""O conjunto rotulado, com o modelo de embeddings real e os limiares padrão.

Pulado se o modelo não estiver no cache local (não baixa nada).
"""

from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.interpret.evaluate import outcome
from app.interpret.interpreter import Interpreter, Thresholds
from app.interpret.recovery import RegexRecovery

pytestmark = pytest.mark.model
CASES = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "eval" / "phrases.yaml").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def results(catalog, monkeypatch_module):
    settings = Settings(_env_file=None)
    monkeypatch_module.setenv("HF_HUB_OFFLINE", "1")
    try:
        from app.interpret.embed import SentenceTransformerEmbedder

        embedder = SentenceTransformerEmbedder(settings.embed_model, settings.embed_threads)
    except Exception as error:  # modelo fora do cache
        pytest.skip(f"modelo de embeddings indisponível: {error}")
    thresholds = Thresholds(
        settings.tau_accept,
        settings.tau_margin,
        settings.tau_slot_accept,
        settings.tau_slot_margin,
        settings.max_clauses,
        settings.tau_stop_accept,
    )
    # O caminho de produção: com a regex da E-001, se ligada.
    recovery = (
        RegexRecovery.from_file(catalog, settings.regex_patterns_path)
        if settings.regex_recovery
        else None
    )
    interpreter = Interpreter(catalog, embedder, thresholds, recovery)
    plain = Interpreter(catalog, embedder, thresholds)
    return [
        (
            case,
            outcome(interpreter, case["text"], settings.wake_words)[0],
            outcome(plain, case["text"], settings.wake_words)[0],
        )
        for case in CASES
    ]


@pytest.fixture(scope="module")
def monkeypatch_module():
    patcher = pytest.MonkeyPatch()
    yield patcher
    patcher.undo()


def test_no_false_positive_in_the_labeled_set(results):
    """Nenhuma frase pode virar um comando que não era o esperado."""
    wrong = [
        (c["text"], got) for c, got, _ in results if isinstance(got, list) and got != c["expect"]
    ]
    assert wrong == []


def test_every_stop_stops(results):
    missed = [c["text"] for c, got, _ in results if c["expect"] == "stop" and got != "stop"]
    assert missed == []


def test_nothing_stops_by_mistake(results):
    wrong = [c["text"] for c, got, _ in results if got == "stop" and c["expect"] != "stop"]
    assert wrong == []


def test_recall_does_not_regress(results):
    positives = [(c, got) for c, got, _ in results if isinstance(c["expect"], list)]
    hits = sum(got == c["expect"] for c, got in positives)
    assert hits / len(positives) >= 0.75


def test_regex_loses_no_hit_of_the_plain_interpreter(results):
    """E-001: tudo o que a main acerta continua certo com a regex."""
    lost = [c["text"] for c, got, plain in results if plain == c["expect"] and got != c["expect"]]
    assert lost == []


def test_no_stop_becomes_a_command(results):
    """E-001: parada nunca vira comando, nem pela regex."""
    wrong = [c["text"] for c, got, _ in results if c["expect"] == "stop" and isinstance(got, list)]
    assert wrong == []
