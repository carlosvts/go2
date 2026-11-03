"""Palavra → slot de movimento (verbo ou direção), só pelo léxico do catálogo.

Usado pelo interpretador e pela recuperação por regex (E-001), para que os
dois reconheçam verbo e direção do mesmo jeito.
"""

from app.catalog import Catalog
from app.interpret.text import edit_distance, fold

# Palavra de slot com erro de uma letra só vale a partir deste tamanho.
FUZZY_MIN_LENGTH = 5


class SlotLexicon:
    def __init__(self, catalog: Catalog) -> None:
        # Palavra (sem acento) → (tipo, canônico).
        self.words: dict[str, tuple[str, str]] = {}
        for kind, lexicon in (("verb", catalog.verbs), ("direction", catalog.directions)):
            for name, lexicon_words in lexicon.items():
                for word in lexicon_words:
                    self.words[fold(word)] = (kind, name)

    def lookup(self, word: str) -> tuple[str, str] | None:
        """(tipo, canônico), com erro de uma letra em palavras longas; ou None."""
        key = fold(word)
        if key in self.words:
            return self.words[key]
        if len(key) < FUZZY_MIN_LENGTH:
            return None
        near = {
            slot
            for known, slot in self.words.items()
            if len(known) >= FUZZY_MIN_LENGTH and edit_distance(key, known, limit=1) <= 1
        }
        return near.pop() if len(near) == 1 else None
