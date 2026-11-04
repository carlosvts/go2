"""E-002: busca a resposta falada em GET /v1/reply/{utterance_id}, numa thread.

De propósito, NÃO passa pelo `FallbackClient.submit`, não pega o `_in_flight`
e não põe a máquina em ENVIO: a wake word nova (inclusive a da parada) é
aceita durante toda a espera e toda a reprodução.

O servidor segura a requisição (long-poll) até o WAV ficar pronto ou até o
prazo dele (10 s); aqui o timeout é 12 s. Os dois valores estão congelados na
etapa 1 da E-002: não mude durante o experimento.
"""

import logging
import os
import tempfile
import threading
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

REPLY_TIMEOUT_S = 12.0  # INFERIDO; congelado na etapa 1 da E-002
MAX_REPLY_BYTES = 500_000  # 500 KB, aceito pelo humano; INFERIDO
TEMP_PREFIX = "go2-reply-"

# (utterance_id, arquivo com o WAV ou None, motivo de não haver arquivo)
OnResult = Callable[[str, Path | None, str | None], None]


class ReplyFetcher:
    def __init__(self, server_url: str, timeout_s: float, counters: Counter) -> None:
        self._server_url = server_url
        self._timeout_s = timeout_s
        self._counters = counters

    def fetch(self, utterance_id: str, on_result: OnResult) -> None:
        """Busca em segundo plano e entrega o resultado a `on_result`. Nunca bloqueia.

        `on_result` é chamado sempre, mesmo com erro inesperado: sem isso a
        máquina ficaria esperando uma resposta que nunca vem, em silêncio.
        """

        def run() -> None:
            try:
                path, error = self._get(utterance_id)
            except Exception as unexpected:  # IncompleteRead, disco cheio...
                path, error = self._fail(utterance_id, repr(unexpected))
            on_result(utterance_id, path, error)

        threading.Thread(target=run, name="reply-fetch", daemon=True).start()

    def _get(self, utterance_id: str) -> tuple[Path | None, str | None]:
        url = f"{self._server_url}/v1/reply/{urllib.request.quote(utterance_id, safe='')}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout_s) as response:
                if response.status != 200:
                    return self._fail(utterance_id, f"HTTP {response.status}")
                data = response.read(MAX_REPLY_BYTES + 1)
        except urllib.error.HTTPError as error:
            return self._fail(utterance_id, f"HTTP {error.code}")
        except OSError as error:  # timeout ou rede
            return self._fail(utterance_id, str(error) or repr(error))
        if len(data) > MAX_REPLY_BYTES:
            return self._fail(utterance_id, f"WAV grande demais (> {MAX_REPLY_BYTES} bytes)")
        # Fora de `media/`: o arquivo é apagado depois de tocar (SoundPlayer).
        handle, name = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".wav")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(data)
        except OSError as error:  # disco cheio: não deixa arquivo pela metade
            Path(name).unlink(missing_ok=True)
            return self._fail(utterance_id, f"não gravou o WAV: {error}")
        self._counters["reply_received"] += 1
        log.info("Resposta falada %s recebida: %d bytes.", utterance_id, len(data))
        return Path(name), None

    def _fail(self, utterance_id: str, reason: str) -> tuple[None, str]:
        self._counters["reply_missing"] += 1
        log.info("Resposta falada %s não veio: %s.", utterance_id, reason)
        return None, reason
