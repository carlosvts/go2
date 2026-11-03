"""E-001: recuperação por regex de cláusulas rejeitadas.

Os padrões ficam em `server/regex/patterns.yaml`. Este módulo só responde
"este texto bate num padrão, e em qual comando"; quem decide se a cláusula
pode passar pela recuperação (motivo da rejeição, rótulos do embedding,
outras cláusulas) é o `Interpreter`.

Regras (specs/experimentos/E-001-recuperar-falas-rejeitadas.md):

- gestos: match total na cláusula sem acento; nenhuma palavra de parada; um
  comando só, e só do conjunto permitido;
- movimento: a direção é capturada da frase (exatamente uma), nunca assumida;
  o verbo vem do léxico do catálogo ou de uma palavra listada no arquivo;
  `para` só como preposição logo antes da direção.
"""

import re
from pathlib import Path
from typing import Any

import yaml

from app.catalog import Catalog
from app.interpret.lexicon import SlotLexicon
from app.interpret.text import fold

# Lista explícita da spec. `damp`, `stop` e desabilitados nunca entram.
ALLOWED_GESTURES = frozenset(
    {
        "stand_up", "sit", "stand_down", "hello", "stretch", "finger_heart", "rise_sit",
        "balance_stand", "recovery_stand", "wiggle_hips", "dance1", "dance2", "scrape",
    }
)  # fmt: skip
# Entre `para` e a direção: artigo e `lado`, os dois opcionais (C1). Sem acento:
# "à" já chega como "a".
_ARTICLES = frozenset({"a", "o", "ao", "as", "os"})
_SIDE = "lado"


class RecoveryError(Exception):
    """`patterns.yaml` inválido. A mensagem lista todos os problemas."""


class RegexRecovery:
    def __init__(self, catalog: Catalog, data: dict[str, Any]) -> None:
        self._catalog = catalog
        self._lexicon = SlotLexicon(catalog)
        problems: list[str] = []

        self._gestures: dict[str, list[re.Pattern]] = {}
        for name, block in (data.get("gestures") or {}).items():
            command = catalog.commands.get(name)
            if name not in ALLOWED_GESTURES or command is None:
                problems.append(f"{name}: fora do conjunto permitido da E-001")
                continue
            if not command.enabled or command.match != "embedding":
                problems.append(f"{name}: desabilitado ou lexical_only no catálogo")
                continue
            self._gestures[name] = self._compile(name, block.get("patterns") or [], problems)

        movement = data.get("movement") or {}
        self._verb_words: dict[str, str] = {}
        for verb, verb_words in (movement.get("verb_words") or {}).items():
            if verb not in catalog.verbs:
                problems.append(f"verb_words: {verb!r} não é verbo do catálogo")
                continue
            for word in verb_words:
                previous = self._verb_words.setdefault(fold(word), verb)
                if previous != verb or self._lexicon.lookup(word) not in (None, ("verb", verb)):
                    problems.append(f"verb_words: {word!r} em mais de um verbo ou slot")
        self._movement = self._compile("movement", movement.get("patterns") or [], problems)
        for pattern in self._movement:
            if not {"verbo", "direcao"} <= set(pattern.groupindex):
                problems.append(f"movement: {pattern.pattern!r} sem os grupos verbo e direcao")

        if problems:
            listed = "\n".join(f"  - {problem}" for problem in problems)
            raise RecoveryError(f"patterns.yaml inválido:\n{listed}")

    @classmethod
    def from_file(cls, catalog: Catalog, path: Path) -> "RegexRecovery":
        return cls(catalog, yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    @staticmethod
    def _compile(owner: str, patterns: list[str], problems: list[str]) -> list[re.Pattern]:
        compiled = []
        for pattern in patterns:
            try:
                compiled.append(re.compile(pattern))
            except re.error as error:
                problems.append(f"{owner}: {pattern!r}: {error}")
        return compiled

    # ─── Gestos e posturas ─────────────────────────────────────────────────

    def match_gesture(self, tokens: list[str]) -> str | None:
        """O gesto cujo padrão bate na cláusula inteira; None se zero ou mais de um."""
        folded = [fold(token) for token in tokens]
        if not folded or any(word in self._catalog.stop_words for word in folded):
            return None
        text = " ".join(folded)
        hits = {
            name
            for name, patterns in self._gestures.items()
            if any(pattern.fullmatch(text) for pattern in patterns)
        }
        return hits.pop() if len(hits) == 1 else None

    # ─── Movimento ─────────────────────────────────────────────────────────

    def match_movement(self, tokens: list[str]) -> str | None:
        """O ID do movimento, com direção explícita e verbo determinado; senão None."""
        folded = [fold(token) for token in tokens]
        if not folded or not self._stop_words_are_prepositions(folded):
            return None
        # M1: exatamente uma palavra de direção na cláusula.
        directions = {self._slot(word, "direction") for word in folded} - {None}
        direction_words = [word for word in folded if self._slot(word, "direction")]
        if len(direction_words) != 1 or len(directions) != 1:
            return None
        direction = directions.pop()
        # M2: um verbo só, do léxico ou da lista do arquivo.
        verbs = {self._verb(word) for word in folded} - {None}
        if len(verbs) != 1:
            return None
        verb = verbs.pop()

        text = " ".join(folded)
        results = set()
        for pattern in self._movement:
            match = pattern.fullmatch(text)
            if match is None:
                continue
            if self._verb(match["verbo"]) != verb:
                continue
            if self._slot(match["direcao"], "direction") != direction:
                continue
            rule = self._catalog.rules.get((verb, direction))
            if rule is not None:
                results.add(rule.id)
        return results.pop() if len(results) == 1 else None

    def _slot(self, word: str, kind: str) -> str | None:
        slot = self._lexicon.lookup(word)
        return slot[1] if slot is not None and slot[0] == kind else None

    def _verb(self, word: str) -> str | None:
        return self._verb_words.get(fold(word)) or self._slot(word, "verb")

    def _stop_words_are_prepositions(self, folded: list[str]) -> bool:
        """C1: só `para` logo antes da direção (artigo e `lado` opcionais no meio)."""
        for index, word in enumerate(folded):
            if word not in self._catalog.stop_words:
                continue
            if word != "para":
                return False
            rest = folded[index + 1 :]
            if rest and rest[0] in _ARTICLES:
                rest = rest[1:]
            if rest and rest[0] == _SIDE:
                rest = rest[1:]
            if not rest or self._slot(rest[0], "direction") is None:
                return False
        return True
