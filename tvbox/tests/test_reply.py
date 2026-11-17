"""E-002 na TV Box: `thinking` / `reply_pending`, busca da resposta e sons.

Servidor falso e aplay falso. Não prova latência, wake word com o alto-falante
tocando nem nada no robô.
"""

import threading
import time
from collections import Counter
from pathlib import Path

import pytest

from sense.audio import SoundPlayer
from sense.fallback_client import FallbackClient, Outcome, Reply, Utterance
from sense.reply_fetcher import MAX_REPLY_BYTES, ReplyFetcher
from sense.thin import ThinMachine, _State
from tests.conftest import OK, wait_for
from tests.test_thin import CONFIG, LOUD, QUIET, Clock, FakeSender, FakeWake, feed, speak

WAV = b"RIFF" + bytes(2000)


# ─── Cliente: thinking e reply_pending ───────────────────────────────────────


def client(server):
    counters = Counter()
    url = f"http://127.0.0.1:{server.server_port}"
    return FallbackClient(url, "tvbox-teste", 2.0, 0.3, OK | {"enqueued"}, counters), counters


def test_thinking_nao_e_confirmacao_nem_rejeicao(server):
    server.answer = (200, {"status": "thinking", "transcript": "qual é o seu nome", "reply_pending": True})
    fallback, counters = client(server)
    reply = fallback.send(Utterance(bytes(3200), "wake_word"))
    assert reply.outcome is Outcome.THINKING and reply.reply_pending is True
    assert counters["fallback_thinking"] == 1


def test_mista_e_confirmada_com_resposta_pendente(server):
    server.answer = (200, {"status": "enqueued", "transcript": "senta e fala seu nome", "reply_pending": True})
    fallback, _ = client(server)
    reply = fallback.send(Utterance(bytes(3200), "wake_word"))
    assert reply.outcome is Outcome.CONFIRMED and reply.reply_pending is True


def test_servidor_sem_o_campo_novo_continua_funcionando(server):
    server.answer = (200, {"status": "enqueued", "transcript": "senta"})
    fallback, _ = client(server)
    reply = fallback.send(Utterance(bytes(3200), "wake_word"))
    assert reply.outcome is Outcome.CONFIRMED and reply.reply_pending is False


# ─── Busca da resposta (GET /v1/reply) ───────────────────────────────────────


def fetch(server, utterance_id="u1"):
    results = []
    fetcher = ReplyFetcher(f"http://127.0.0.1:{server.server_port}", 2.0, Counter())
    fetcher.fetch(utterance_id, lambda *result: results.append(result))
    wait_for(lambda: results)
    return results[0]


def test_200_entrega_o_wav_num_arquivo_fora_de_media(server):
    server.reply = (200, WAV)
    utterance_id, path, error = fetch(server)
    assert utterance_id == "u1" and error is None
    assert path.read_bytes() == WAV
    assert "media" not in path.parts
    path.unlink()


@pytest.mark.parametrize("status", [204, 404, 500])
def test_sem_resposta_nao_entrega_arquivo(server, status):
    server.reply = (status, b"")
    _, path, error = fetch(server)
    assert path is None and error


def test_wav_grande_demais_e_recusado(server):
    server.reply = (200, b"RIFF" + bytes(MAX_REPLY_BYTES))
    _, path, error = fetch(server)
    assert path is None and "grande" in error


def test_timeout_nao_entrega_arquivo(server):
    server.reply, server.reply_delay_s = (200, WAV), 1.0
    results = []
    fetcher = ReplyFetcher(f"http://127.0.0.1:{server.server_port}", 0.2, Counter())
    fetcher.fetch("u1", lambda *result: results.append(result))
    wait_for(lambda: results)
    assert results[0][1] is None


# ─── Máquina de estados ──────────────────────────────────────────────────────


class FakeFetcher:
    def __init__(self):
        self.requests, self.callbacks = [], []

    def fetch(self, utterance_id, on_result):
        self.requests.append(utterance_id)
        self.callbacks.append(on_result)

    def deliver(self, path=None, error=None, index=-1):
        self.callbacks[index](self.requests[index], path, error)


def make():
    wake, sender, counters, sounds, clock = FakeWake(), FakeSender(), Counter(), [], Clock()
    fetcher, played, stops = FakeFetcher(), [], []
    machine = ThinMachine(
        wake, sender, CONFIG, counters, sounds.append, clock,
        fetcher=fetcher, play_file=played.append, stop_sounds=lambda: stops.append(1),
    )
    return machine, wake, sender, counters, sounds, clock, fetcher, played, stops


def reply(sender, outcome, status, reply_pending):
    utterance = sender.utterances[-1]
    sender.callbacks[-1](
        Reply(outcome, utterance.utterance_id, status, "frase", reply_pending=reply_pending)
    )


def test_thinking_toca_espera_busca_e_volta_ao_ocioso(tmp_path):
    machine, wake, sender, _, sounds, clock, fetcher, played, _ = make()
    speak(machine, wake, clock)
    reply(sender, Outcome.THINKING, "thinking", True)
    feed(machine, clock, [QUIET])
    assert sounds[-2:] == ["processing", "thinking"]
    assert fetcher.requests == [sender.utterances[-1].utterance_id]
    # Invariante: a busca não usa submit nem põe a máquina em SENDING.
    assert machine._state is _State.IDLE
    assert len(sender.utterances) == 1
    wav = tmp_path / "r.wav"
    wav.write_bytes(WAV)
    fetcher.deliver(wav)
    feed(machine, clock, [QUIET])
    assert played == [wav]


def test_mista_toca_confirmed_e_depois_espera():
    machine, wake, sender, _, sounds, clock, fetcher, _, _ = make()
    speak(machine, wake, clock)
    reply(sender, Outcome.CONFIRMED, "enqueued", True)
    feed(machine, clock, [QUIET])
    assert sounds[-3:] == ["processing", "confirmed", "thinking"]
    assert len(fetcher.requests) == 1


def test_sem_resposta_na_conversa_pura_toca_rejected():
    machine, wake, sender, _, sounds, clock, fetcher, played, _ = make()
    speak(machine, wake, clock)
    reply(sender, Outcome.THINKING, "thinking", True)
    feed(machine, clock, [QUIET])
    fetcher.deliver(None, "HTTP 204")
    feed(machine, clock, [QUIET])
    assert sounds[-1] == "rejected" and played == []


def test_sem_resposta_na_mista_toca_reply_failed():
    machine, wake, sender, _, sounds, clock, fetcher, played, _ = make()
    speak(machine, wake, clock)
    reply(sender, Outcome.CONFIRMED, "enqueued", True)
    feed(machine, clock, [QUIET])
    fetcher.deliver(None, "HTTP 204")
    feed(machine, clock, [QUIET])
    assert sounds[-1] == "reply_failed" and played == []


def test_wake_word_durante_a_espera_e_aceita_e_descarta_a_resposta(tmp_path):
    machine, wake, sender, counters, sounds, clock, fetcher, played, stops = make()
    speak(machine, wake, clock)
    reply(sender, Outcome.THINKING, "thinking", True)
    feed(machine, clock, [QUIET])
    clock.now += CONFIG.wake_cooldown_s
    machine._cooldown_s = 0.0
    wake.next_score = 1.0
    feed(machine, clock, [LOUD])
    wake.next_score = 0.0
    assert machine._state is _State.LISTENING  # a wake word nova foi aceita
    assert stops  # fila de sons esvaziada e aplay interrompido
    assert sounds[-1] == "beep"
    assert counters["reply_discarded"] == 1
    wav = tmp_path / "tarde.wav"
    wav.write_bytes(WAV)
    fetcher.deliver(wav)  # a resposta antiga chega depois
    feed(machine, clock, [QUIET])
    assert played == [] and not wav.exists()  # descartada e apagada


def test_resposta_sem_reply_pending_nao_busca_nada():
    machine, wake, sender, _, sounds, clock, fetcher, _, _ = make()
    speak(machine, wake, clock)
    reply(sender, Outcome.CONFIRMED, "enqueued", False)
    feed(machine, clock, [QUIET])
    assert sounds[-1] == "confirmed" and fetcher.requests == []


# ─── SoundPlayer: arquivo por caminho, esvaziar, interromper ─────────────────


class InterruptibleAplay:
    """aplay falso que fica "tocando" até ser interrompido ou passar `duration_s`."""

    def __init__(self, duration_s=5.0):
        self.played, self.duration_s = [], duration_s
        self._stop = threading.Event()
        self.started = threading.Event()

    def __call__(self, command, **kwargs):
        self.played.append(command[-1].rsplit("/", 1)[-1])
        self.started.set()
        self._stop.wait(self.duration_s)
        self._stop.clear()

    def interrupt(self):
        self._stop.set()


def media(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes(b"RIFF")
    return tmp_path


def test_toca_arquivo_por_caminho_e_apaga_depois(tmp_path):
    aplay = InterruptibleAplay(duration_s=0.0)
    player = SoundPlayer(tmp_path, runner=aplay)
    reply_wav = tmp_path / "go2-reply.wav"
    reply_wav.write_bytes(WAV)
    player.play_path(1, reply_wav, delete_after=True)
    player.wait_idle()
    assert aplay.played == ["go2-reply.wav"] and not reply_wav.exists()


def test_clear_esvazia_a_fila_e_interrompe_o_som(tmp_path):
    aplay = InterruptibleAplay()
    player = SoundPlayer(media(tmp_path, "processing.wav", "thinking.wav", "confirmed.wav"), runner=aplay)
    player.play(1, "processing")
    aplay.started.wait(2)
    player.play(1, "confirmed")
    player.play(1, "thinking")
    started = time.perf_counter()
    player.clear()
    player.wait_idle()
    assert time.perf_counter() - started < 1.0  # não esperou o som acabar
    assert aplay.played == ["processing.wav"]


def test_clear_apaga_resposta_que_nao_tocou(tmp_path):
    aplay = InterruptibleAplay()
    player = SoundPlayer(media(tmp_path, "processing.wav"), runner=aplay)
    player.play(1, "processing")
    aplay.started.wait(2)
    reply_wav = tmp_path / "go2-reply.wav"
    reply_wav.write_bytes(WAV)
    player.play_path(1, reply_wav, delete_after=True)
    player.clear()
    player.wait_idle()
    assert not reply_wav.exists()


def test_sequencia_da_mista_toca_tudo_em_ordem(tmp_path):
    aplay = InterruptibleAplay(duration_s=0.05)
    player = SoundPlayer(media(tmp_path, "processing.wav", "confirmed.wav", "thinking.wav"), runner=aplay)
    for name in ("processing", "confirmed", "thinking"):
        player.play(1, name)
    player.wait_idle()
    assert aplay.played == ["processing.wav", "confirmed.wav", "thinking.wav"]


def test_falas_novas_tem_pelo_menos_quatro_variantes():
    media_dir = Path(__file__).resolve().parent.parent / "media"
    player = SoundPlayer(media_dir)
    assert len(player.variants("thinking")) >= 4
    assert len(player.variants("reply_failed")) >= 4


def test_erro_inesperado_na_busca_ainda_avisa(server, monkeypatch):
    import http.client

    fetcher = ReplyFetcher(f"http://127.0.0.1:{server.server_port}", 2.0, Counter())

    def broken(utterance_id):
        raise http.client.IncompleteRead(b"RIFF")

    monkeypatch.setattr(fetcher, "_get", broken)
    results = []
    fetcher.fetch("u1", lambda *result: results.append(result))
    wait_for(lambda: results)
    assert results[0][1] is None and "IncompleteRead" in results[0][2]


def test_disco_cheio_nao_deixa_arquivo(server, monkeypatch, tmp_path):
    server.reply = (200, WAV)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    real_fdopen = __import__("os").fdopen

    def full(*args, **kwargs):
        handle = real_fdopen(*args, **kwargs)
        handle.write = lambda data: (_ for _ in ()).throw(OSError(28, "No space left"))
        return handle

    monkeypatch.setattr("sense.reply_fetcher.os.fdopen", full)
    _, path, error = fetch(server)
    assert path is None and "não gravou" in error
    assert list(tmp_path.glob("go2-reply-*")) == []


def test_clear_entre_a_checagem_e_o_aplay_ainda_corta(tmp_path):
    """Corrida: o worker já passou da checagem de geração quando o clear chega."""
    from sense.audio import _Aplay

    aplay = _Aplay()
    started = []

    def popen(command, **kwargs):
        class Process:
            def __init__(self):
                self.terminated = False
                started.append(self)

            def poll(self):
                return 0 if self.terminated else None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

        return Process()

    import sense.audio as audio_module

    original = audio_module.subprocess.Popen
    audio_module.subprocess.Popen = popen
    try:
        aplay(["aplay", "x.wav"], timeout=1, still_wanted=lambda: False)
    finally:
        audio_module.subprocess.Popen = original
    assert started and started[0].terminated
