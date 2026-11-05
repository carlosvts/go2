"""O desfecho de uma frase em texto, como o serviço o decide depois de transcrever.

Usado pela calibração e pelos testes, para medir exatamente o caminho de
produção: remoção da wake word e interpretação.
"""

from app.interpret.interpreter import Interpretation, Interpreter, Kind
from app.wake_word import strip_wake_word

STOP = "stop"
REJECT = "reject"
IGNORED = "ignored"


def outcome(
    interpreter: Interpreter, text: str, wake_words: list[str]
) -> tuple[str | list[str], Interpretation]:
    """`STOP`, `REJECT`, `IGNORED` ou a lista de IDs de comando."""
    stripped, _ = strip_wake_word(text, wake_words)
    result = interpreter.interpret(stripped)
    return _from_interpretation(result), result


def _from_interpretation(result: Interpretation) -> str | list[str]:
    if result.kind is Kind.EMPTY:
        return IGNORED
    if result.kind is Kind.STOP:
        return STOP
    if result.kind is Kind.REJECTED:
        return REJECT
    return result.commands


# ─── E-002: a camada de conversa por cima do interpretador ─────────────────

LLM = "llm"


def conversation_outcome(
    interpreter: Interpreter, text: str, wake_words: list[str], catalog, rules
) -> tuple[str | list[str] | dict, Interpretation]:
    """Como `outcome`, com a decisão da E-002 (sem F5/F6, que dependem do serviço).

    `LLM` (só conversa), `{"commands": [...], "llm": True}` (mista), ou o
    desfecho de hoje (`STOP`, `REJECT`, `IGNORED`, lista de IDs).
    """
    from app.conversation import Route, decide

    stripped, _ = strip_wake_word(text, wake_words)
    result = interpreter.interpret(stripped)
    decision = decide(result, stripped, catalog, rules, interpreter.has_embedder)
    if decision.route is Route.PURE:
        return LLM, result
    if decision.route is Route.MIXED:
        return {"commands": decision.commands, "llm": True}, result
    return _from_interpretation(result), result


def dispatched(got: str | list[str] | dict) -> list[str]:
    """Os comandos que sairiam para a fila com este desfecho."""
    if isinstance(got, list):
        return got
    if isinstance(got, dict):
        return list(got["commands"])
    return []
