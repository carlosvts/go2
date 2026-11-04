"""Filtro de eco: a resposta do Llama não pode soar como comando nem parada.

A resposta tocada pelo alto-falante pode entrar no microfone (ou no pré-roll)
da frase seguinte. Antes do TTS, o texto é conferido de dois jeitos; se
qualquer um acusar, ele é trocado por uma frase fixa (spec E-002):

1. pelo interpretador: parada, comando, ou qualquer cláusula aceita;
2. pela lista explícita de palavras proibidas (`llm/forbidden_words.yaml`).
"""

import random
from pathlib import Path

import yaml

from app.interpret.interpreter import Interpreter, Kind
from app.interpret.text import fold, words


class EchoFilter:
    def __init__(
        self,
        interpreter: Interpreter,
        forbidden_words: frozenset[str],
        fallback_replies: list[str],
        rng: random.Random | None = None,
    ) -> None:
        self._interpreter = interpreter
        self._forbidden = forbidden_words
        self.fallback_replies = fallback_replies
        self._rng = rng or random.Random()

    @classmethod
    def load(
        cls, interpreter: Interpreter, llm_dir: Path, rng: random.Random | None = None
    ) -> "EchoFilter":
        groups = yaml.safe_load((llm_dir / "forbidden_words.yaml").read_text(encoding="utf-8"))
        forbidden = frozenset(
            fold(str(word)).lower() for group in groups.values() for word in group
        )
        fixed = yaml.safe_load((llm_dir / "fallback_replies.yaml").read_text(encoding="utf-8"))
        return cls(interpreter, forbidden, list(fixed["replies"]), rng)

    def command_like(self, text: str) -> str | None:
        """Item 1. O motivo, ou None se o interpretador não vê comando nem parada."""
        if self._interpreter.is_stop_only(text):
            return "stop_only"
        result = self._interpreter.interpret(text)
        if result.kind in (Kind.STOP, Kind.COMMANDS):
            return f"interpreter_{result.kind.value}"
        if any(clause.command_id for clause in result.clauses):
            return "interpreter_clause"
        return None

    def forbidden(self, text: str, allow: frozenset[str] | set[str] = frozenset()) -> str | None:
        """Item 2. A primeira palavra proibida, ou None."""
        for word in words(self._interpreter.tokenize(text)):
            folded = fold(word)
            if folded in self._forbidden and folded not in allow:
                return folded
        return None

    def check(self, text: str) -> tuple[str, str | None]:
        """(texto final, motivo da troca ou None)."""
        reason = self.command_like(text)
        if reason is None:
            word = self.forbidden(text)
            reason = None if word is None else f"forbidden_word:{word}"
        if reason is None:
            return text, None
        return self._rng.choice(self.fallback_replies), reason
