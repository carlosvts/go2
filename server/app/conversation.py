"""E-002: decide se uma frase rejeitada vai para o Llama, e com que comandos.

Só lê a `Interpretation` que o interpretador já produziu; não muda nada nela.
O Llama nunca decide comando: na frase mista, os comandos que saem são os das
cláusulas que o interpretador ACEITOU, e saem antes de o Llama rodar.

Regras (spec E-002, "Quando roda"):

- C1–C4 por cláusula: `low_similarity`, embedder carregado, top-1/top-2 que não
  são parada nem movimento, filtro de ruído (mínimo de palavras + marcador).
- F1–F4 sobre a frase: palavras de parada, nenhuma outra rejeição, exatamente
  uma cláusula de conversa, demais cláusulas aceitas sem embedding e sem `damp`.

F5 (idade da fala) e F6 (saúde do llama-server) ficam no serviço, que tem o
relógio e o estado do llama-server.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

from app.catalog import Catalog
from app.interpret.interpreter import MOVE_CLASS, STOP_CLASS, Clause, Interpretation, Kind
from app.interpret.text import fold, words

# Comando que só sai por frase exata e nunca acompanha uma resposta (F4).
DAMP_ID = "damp"
_PARA = "para"


class Route(Enum):
    NONE = "none"  # a frase segue exatamente como hoje
    PURE = "pure"  # só conversa: nada é despachado
    MIXED = "mixed"  # despacha os comandos aceitos e vai ao Llama


@dataclass(frozen=True)
class ConversationRules:
    min_words: int
    markers: frozenset[str]  # sem acento
    # F1: o que pode vir depois de "para" no meio da conversa (sem acento,
    # cada item como tupla de palavras: "a gente" = ("a", "gente")).
    para_pronouns: tuple[tuple[str, ...], ...] = ()

    @classmethod
    def load(cls, path: Path) -> "ConversationRules":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            min_words=int(data["min_words"]),
            markers=frozenset(fold(str(word)).lower() for word in data["markers"]),
            para_pronouns=tuple(
                tuple(fold(str(item)).lower().split()) for item in data.get("para_pronouns", [])
            ),
        )


@dataclass
class Decision:
    route: Route
    text: str = ""  # o que vai ao Llama: só a cláusula de conversa
    commands: list[str] = field(default_factory=list)  # só na mista
    reason: str | None = None  # por que não foi (para o log)

    def log(self) -> dict:
        return {"route": self.route.value, "commands": self.commands, "reason": self.reason}


def _tokens(clause: Clause) -> list[str]:
    return [fold(word) for word in clause.text.split()]


def is_candidate(clause: Clause, rules: ConversationRules, embedder_loaded: bool) -> bool:
    """C1–C4: a cláusula é de conversa."""
    if clause.reject_reason != "low_similarity" or not embedder_loaded:  # C1, C2
        return False
    if STOP_CLASS in (clause.top1, clause.top2) or MOVE_CLASS in (clause.top1, clause.top2):
        return False  # C3
    tokens = _tokens(clause)
    return len(tokens) >= rules.min_words and any(t in rules.markers for t in tokens)  # C4


def _followed_by_pronoun(tokens: list[str], index: int, rules: ConversationRules) -> bool:
    after = tokens[index + 1 :]
    return any(tuple(after[: len(p)]) == p for p in rules.para_pronouns)


def _stop_word_blocks(
    clauses: list[Clause],
    candidate: Clause,
    all_words: list[str],
    catalog: Catalog,
    rules: ConversationRules,
) -> bool:
    """F1. True se alguma palavra de parada barra a frase."""
    others = catalog.stop_words - {_PARA}
    if any(word in others for word in all_words):
        return True
    for clause in clauses:
        tokens = _tokens(clause)
        is_move = clause.command_id is not None and clause.method == "slots"
        is_conversation = clause is candidate
        for index, token in enumerate(tokens):
            if token != _PARA:
                continue
            if index == len(tokens) - 1:
                return True  # "para" no fim de qualquer cláusula
            if is_move:
                continue  # preposição do movimento (movement.ignore)
            if not is_conversation:
                return True  # cláusula aceita que não é movimento, ou rejeitada
            if index == 0 or not _followed_by_pronoun(tokens, index, rules):
                return True  # "para" abrindo a conversa, ou sem pronome depois
    return False


def _dispatchable(clause: Clause) -> bool:
    """F4: aceita, sem embedding, e não é `damp`."""
    if clause.command_id is None or clause.reject_reason is not None:
        return False
    if clause.command_id == DAMP_ID:
        return False
    if clause.method == "lexical":
        return True
    return clause.method == "slots" and clause.slots_lexical is True


def decide(
    interpretation: Interpretation,
    text: str,
    catalog: Catalog,
    rules: ConversationRules,
    embedder_loaded: bool,
) -> Decision:
    """`text` é a frase já sem a wake word, a mesma que foi interpretada."""
    if interpretation.kind is not Kind.REJECTED or not interpretation.clauses:
        return Decision(Route.NONE, reason="not_rejected_by_clause")
    clauses = interpretation.clauses
    candidates = [c for c in clauses if is_candidate(c, rules, embedder_loaded)]
    if not candidates:
        return Decision(Route.NONE, reason="no_candidate")

    if len(candidates) > 1:  # F3
        return Decision(Route.NONE, reason="f3_many_conversation_clauses")
    candidate = candidates[0]
    others = [c for c in clauses if c is not candidate]
    if any(c.reject_reason is not None for c in others):  # F2 (e F3: low_similarity sem C2–C4)
        return Decision(Route.NONE, reason="f2_other_rejection")
    all_words = [fold(word) for word in words(catalog.tokenize(text))]
    if _stop_word_blocks(clauses, candidate, all_words, catalog, rules):  # F1
        return Decision(Route.NONE, reason="f1_stop_word")
    if not all(_dispatchable(c) for c in others):  # F4
        return Decision(Route.NONE, reason="f4_not_dispatchable")

    if not others:
        return Decision(Route.PURE, text=candidate.text)
    return Decision(
        Route.MIXED, text=candidate.text, commands=[c.command_id for c in others if c.command_id]
    )
