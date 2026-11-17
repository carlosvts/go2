"""E-002: eval/conversation_e002.yaml com o modelo de embeddings real.

Pulado se o modelo não estiver no cache local (não baixa nada).
Falso positivo (meta 0, rejeita a E-002) = comando despachado fora do `expect`.
Errar `llm` × `reject` sem despachar nada é informativo (relatado, não falha).
"""

from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.conversation import ConversationRules
from app.interpret.evaluate import LLM, STOP, conversation_outcome, dispatched
from app.interpret.interpreter import Interpreter, Thresholds

pytestmark = pytest.mark.model
ROOT = Path(__file__).resolve().parent.parent
CASES = yaml.safe_load((ROOT / "eval" / "conversation_e002.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def monkeypatch_module():
    patcher = pytest.MonkeyPatch()
    yield patcher
    patcher.undo()


@pytest.fixture(scope="module")
def results(catalog, monkeypatch_module):
    settings = Settings(_env_file=None)
    monkeypatch_module.setenv("HF_HUB_OFFLINE", "1")
    try:
        from app.interpret.embed import SentenceTransformerEmbedder

        embedder = SentenceTransformerEmbedder(settings.embed_model, settings.embed_threads)
    except Exception as error:  # modelo fora do cache
        pytest.skip(f"modelo de embeddings indisponível: {error}")
    interpreter = Interpreter(
        catalog,
        embedder,
        Thresholds(
            settings.tau_accept,
            settings.tau_margin,
            settings.tau_slot_accept,
            settings.tau_slot_margin,
            settings.max_clauses,
            settings.tau_stop_accept,
        ),
    )
    rules = ConversationRules.load(ROOT / "llm" / "conversation_markers.yaml")
    return [
        (
            case,
            conversation_outcome(interpreter, case["text"], settings.wake_words, catalog, rules)[0],
        )
        for case in CASES
    ]


def expected_commands(expect) -> list[str]:
    if isinstance(expect, list):
        return expect
    if isinstance(expect, dict):
        return list(expect["commands"])
    return []


def goes_to_llm(got) -> bool:
    return got == LLM or isinstance(got, dict)


def test_no_false_positive(results):
    """Nenhum comando despachado fora do esperado (inclui o despacho parcial)."""
    wrong = [
        (case["text"], got)
        for case, got in results
        if dispatched(got) and dispatched(got) != expected_commands(case["expect"])
    ]
    assert wrong == []


def test_stop_attempts_never_reach_llm_nor_dispatch(results):
    wrong = [
        (case["text"], got)
        for case, got in results
        if case["expect"] == "not_llm" and (goes_to_llm(got) or dispatched(got))
    ]
    assert wrong == []


def test_expected_rejections_do_not_reach_llm(results):
    wrong = [
        (case["text"], got)
        for case, got in results
        if case["expect"] == "reject" and goes_to_llm(got)
    ]
    assert wrong == []


def test_regressions_keep_todays_outcome(results):
    wrong = [
        (case["text"], got)
        for case, got in results
        if (isinstance(case["expect"], list) or case["expect"] == STOP) and got != case["expect"]
    ]
    assert wrong == []


def test_report_llm_recall(results, capsys):
    """Informativo: quantas frases rotuladas `llm` (ou mista) de fato iriam ao Llama."""
    positives = [(c, g) for c, g in results if c["expect"] == LLM or isinstance(c["expect"], dict)]
    misses = [(c["text"], g) for c, g in positives if c["expect"] != g]
    with capsys.disabled():
        print(
            f"\nE-002 eval: {len(positives) - len(misses)}/{len(positives)} acertos de Llama/mista"
        )
        for text, got in misses:
            print(f"  não foi como esperado: {text!r} → {got}")
