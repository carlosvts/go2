"""O caminho de uma frase: áudio → transcrição → interpretação → fila."""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from app.audio import SAMPLE_RATE
from app.catalog import Catalog
from app.config import Settings
from app.conversation import ConversationRules, Decision, Route, decide
from app.dispatch import Dispatcher
from app.interpret.interpreter import Interpretation, Interpreter, Kind
from app.metrics import KNOWN_REASONS, Stats
from app.reply.engine import ReplyEngine
from app.reply.health import HealthMonitor
from app.transcribe.base import TranscriptionPool
from app.wake_word import strip_wake_word

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class CommandRef(BaseModel):
    id: str


class UtteranceResponse(BaseModel):
    utterance_id: str
    status: str  # "enqueued", "rejected", "stopped", "ignored" ou "thinking" (E-002)
    transcript: str
    commands: list[CommandRef] = []
    confidence: float | None = None
    reject_reason: str | None = None
    # E-002: há uma resposta falada a buscar em GET /v1/reply/{utterance_id}.
    # True no `thinking` e no `enqueued` da frase mista; False em todo o resto.
    reply_pending: bool = False


@dataclass
class Replies:
    """O que a E-002 precisa no serviço. None no serviço = E-002 desligada."""

    rules: ConversationRules
    engine: ReplyEngine
    health: HealthMonitor


@dataclass(frozen=True)
class Meta:
    utterance_id: str
    edge_id: str
    reason: str


class Service:
    def __init__(
        self,
        settings: Settings,
        catalog: Catalog,
        interpreter: Interpreter,
        pool: TranscriptionPool,
        dispatcher: Dispatcher,
        replies: Replies | None = None,
    ) -> None:
        self.settings = settings
        self.replies = replies
        self.catalog = catalog
        self.interpreter = interpreter
        self.pool = pool
        self.dispatcher = dispatcher
        self.stats = Stats(settings.stats_window)
        # utterance_id → (quando expira, resposta). A resposta é um Future
        # para que a repetição que chega no meio do processamento espere a
        # mesma resposta em vez de processar de novo.
        self._seen: dict[str, tuple[float, asyncio.Future[UtteranceResponse]]] = {}

    async def handle(self, meta: Meta, audio: np.ndarray, wav: bytes) -> UtteranceResponse:
        """Idempotente por `utterance_id`: a repetição não executa nada."""
        received = time.monotonic()
        self._forget_expired(received)
        known = self._seen.get(meta.utterance_id)
        if known is not None:
            log.info(
                "utterance repetida",
                extra={"event": "duplicate", "utterance_id": meta.utterance_id},
            )
            return await asyncio.shield(known[1])

        future: asyncio.Future[UtteranceResponse] = asyncio.get_running_loop().create_future()
        self._seen[meta.utterance_id] = (received + self.settings.idempotency_ttl_s, future)
        try:
            response = await self._process(meta, audio, wav, received)
        except Exception as error:
            # Não guarda falha: uma nova tentativa tem de poder processar.
            del self._seen[meta.utterance_id]
            future.set_exception(error)
            future.exception()  # marca como lida, para o caso de ninguém esperar
            raise
        except BaseException:
            del self._seen[meta.utterance_id]
            future.cancel()
            raise
        future.set_result(response)
        return response

    def _forget_expired(self, now: float) -> None:
        for utterance_id in [key for key, (expires, _) in self._seen.items() if expires < now]:
            del self._seen[utterance_id]

    async def _process(
        self, meta: Meta, audio: np.ndarray, wav: bytes, received: float
    ) -> UtteranceResponse:
        """`received` é o relógio do servidor: a idade da fala nunca vem do cliente."""
        if meta.reason not in KNOWN_REASONS:
            log.warning("reason desconhecido aceito: %r", meta.reason)

        transcription, lane = await self.pool.transcribe(audio)
        transcribed = time.monotonic()
        raw = transcription.text
        text, wake_word_removed = strip_wake_word(raw, self.settings.wake_words)

        status = "rejected"
        commands: list[str] = []
        confidence: float | None = None
        reject_reason: str | None = None
        interpretation: Interpretation | None = None
        decision: Decision | None = None
        reply_pending = False
        stats_status: str | None = None
        interpreted = transcribed

        if self.interpreter.is_stop_only(text):
            # Caminho curto da parada: sem embedding e sem troca de thread.
            # Vale até para a transcrição que o motor marcou como duvidosa:
            # parar por engano é seguro, deixar de parar não é.
            status, commands, confidence = "stop", [self.catalog.stop_id], 1.0
        elif transcription.reject_reason is not None:
            reject_reason = transcription.reject_reason
        else:
            interpretation = await asyncio.to_thread(self.interpreter.interpret, text)
            interpreted = time.monotonic()
            confidence = interpretation.confidence
            if interpretation.kind is Kind.EMPTY:
                # Só a wake word, ou nada que seja palavra.
                status = "ignored"
            elif interpretation.kind is Kind.STOP:
                status, commands = "stop", interpretation.commands
            elif interpretation.kind is Kind.REJECTED:
                reject_reason = interpretation.reject_reason
                if self.replies is not None:
                    decision = decide(
                        interpretation,
                        text,
                        self.catalog,
                        self.replies.rules,
                        self.interpreter.has_embedder,
                    )
            else:
                commands = interpretation.commands

        if status == "stop":
            cancellation = await self.dispatcher.cancel("stop", meta.edge_id)
            if cancellation.stop_sent:
                status = "stopped"
            else:
                status, reject_reason, commands = "rejected", "stop_not_delivered", []
        elif commands:
            status, reject_reason = self._enqueue(commands, meta, received)
            if status != "enqueued":
                commands = []
        elif decision is not None and decision.route is not Route.NONE:
            status, reject_reason, commands, reply_pending, stats_status = self._converse(
                decision, interpretation, meta, received, reject_reason
            )
        done = time.monotonic()

        response = UtteranceResponse(
            utterance_id=meta.utterance_id,
            status=status,
            transcript=raw,
            commands=[CommandRef(id=command_id) for command_id in commands],
            confidence=None if confidence is None else round(confidence, 4),
            reject_reason=reject_reason,
            reply_pending=reply_pending,
        )
        if status == "thinking" and decision is not None:
            response.confidence = self._candidate_score(interpretation, decision)
        total_ms = (done - received) * 1000
        self.stats.record(meta.reason, stats_status or status, total_ms)
        record = {
            "event": "utterance",
            "utterance_id": meta.utterance_id,
            "edge_id": meta.edge_id,
            "reason": meta.reason,
            "audio_s": round(len(audio) / SAMPLE_RATE, 2),
            "transcript_raw": raw,
            "transcript": text,
            "wake_word_removed": wake_word_removed,
            "normalized": interpretation.normalized if interpretation else None,
            "status": status,
            "commands": commands,
            "confidence": response.confidence,
            "reject_reason": reject_reason,
            "reply_pending": reply_pending,
            "conversation": decision.log() if decision else None,
            "clauses": [clause.log() for clause in interpretation.clauses]
            if interpretation
            else [],
            "stt": transcription.details,
            "stt_lane": lane,
            "stt_ms": round((transcribed - received) * 1000, 1),
            "interpret_ms": round((interpreted - transcribed) * 1000, 1),
            "dispatch_ms": round((done - interpreted) * 1000, 1),
            "total_ms": round(total_ms, 1),
        }
        log.info("utterance %s", status, extra=record)
        if self.settings.save_utterances:
            await asyncio.to_thread(self._save, wav, record)
        return response

    def _converse(
        self,
        decision: Decision,
        interpretation: Interpretation | None,
        meta: Meta,
        received: float,
        reject_reason: str | None,
    ) -> tuple[str, str | None, list[str], bool, str | None]:
        """E-002. (status, reject_reason, commands, reply_pending, status das stats).

        Na mista, o `submit` acontece ANTES de o Llama rodar e recebe só os
        comandos que o interpretador aceitou. Nada da saída do Llama chega aqui.
        """
        replies = self.replies
        assert replies is not None
        if not replies.health.healthy:  # F6: segue como hoje
            decision.reason = "f6_llm_unavailable"
            return "rejected", reject_reason, [], False, None
        if time.monotonic() - received > self.settings.max_utterance_age_s:  # F5
            decision.reason = "f5_stale"
            return "rejected", "stale", [], False, None
        if decision.route is Route.PURE:
            replies.engine.start(meta.utterance_id, decision.text)
            return "thinking", None, [], True, None
        status, queue_reason = self._enqueue(decision.commands, meta, received)
        if status != "enqueued":  # a fila recusou: o Llama não roda
            decision.reason = f"queue_{queue_reason}"
            return "rejected", queue_reason, [], False, None
        log.info(
            "despacho parcial",
            extra={
                "event": "partial_dispatch",
                "utterance_id": meta.utterance_id,
                "commands": decision.commands,
            },
        )
        replies.engine.start(meta.utterance_id, decision.text)
        return "enqueued", None, list(decision.commands), True, "enqueued_with_reply"

    @staticmethod
    def _candidate_score(interpretation: Interpretation | None, decision: Decision) -> float | None:
        if interpretation is None:
            return None
        for clause in interpretation.clauses:
            if clause.text == decision.text and clause.score is not None:
                return round(clause.score, 4)
        return None

    def _enqueue(self, commands: list[str], meta: Meta, received: float) -> tuple[str, str | None]:
        # A saída só pode conter IDs do catálogo, e a parada nunca entra na fila.
        if any(c not in self.catalog.ids or c == self.catalog.stop_id for c in commands):
            return "rejected", "unknown_command"
        if time.monotonic() - received > self.settings.max_utterance_age_s:
            return "rejected", "stale"
        submission = self.dispatcher.submit(commands, meta.edge_id, meta.utterance_id)
        if not submission.accepted:
            return "rejected", submission.reason
        return "enqueued", None

    def _save(self, wav: bytes, record: dict) -> None:
        """Guarda o áudio e o resultado, para montar o conjunto de avaliação."""
        try:
            name = record["utterance_id"]
            if not _SAFE_NAME.match(name):
                # O ID vem do cliente: não vira caminho de arquivo sem conferir.
                name = hashlib.sha256(name.encode()).hexdigest()[:32]
            folder = Path(self.settings.save_dir) / time.strftime("%Y-%m-%d")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{name}.wav").write_bytes(wav)
            (folder / f"{name}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        except OSError as error:
            log.warning("não foi possível salvar a frase: %s", error)
