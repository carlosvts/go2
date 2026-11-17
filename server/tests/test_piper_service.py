"""E-002: Piper em processo separado. Aqui com uma voz falsa: não testa o Piper."""

import threading

import httpx
import pytest

from app.reply.piper_service import make_server
from app.reply.tts import PiperClient


class FakeVoice:
    def __init__(self):
        self.texts = []

    def synthesize(self, text):
        self.texts.append(text)
        if text == "quebra":
            raise RuntimeError("voz falhou")
        return b"RIFF" + text.encode()


@pytest.fixture
def service():
    voice = FakeVoice()
    server = make_server(voice, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, voice
    server.shutdown()


def url(server):
    return f"http://127.0.0.1:{server.server_port}"


def test_client_gets_the_wav_from_the_other_process(service):
    server, voice = service
    client = PiperClient(url(server), 2.0)
    assert client.synthesize("Eu. Go2.") == b"RIFFEu. Go2."
    assert voice.texts == ["Eu. Go2."]
    client.close()


def test_health(service):
    server, _ = service
    assert httpx.get(url(server) + "/health").status_code == 200


def test_voice_failure_is_an_http_error(service):
    server, _ = service
    client = PiperClient(url(server), 2.0)
    with pytest.raises(httpx.HTTPStatusError):
        client.synthesize("quebra")


@pytest.mark.parametrize("body", [b"nada", b"{}", b'{"text": ""}'])
def test_bad_request_is_422(service, body):
    server, _ = service
    response = httpx.post(url(server) + "/synthesize", content=body)
    assert response.status_code == 422
