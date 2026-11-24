"""F-003 A3: o gancho da track de vídeo funciona com a classe real da lib."""

import asyncio

from unitree_webrtc_connect.webrtc_video import WebRTCVideoChannel

from app.robot.unitree import VideoHookedConnection


class _StubPeer:
    """Só o que o `WebRTCVideoChannel` real chama no `__init__`."""

    def addTransceiver(self, *args: object, **kwargs: object) -> None:  # noqa: N802
        """Nada a negociar sem rede."""


async def test_a3_track_chega_ao_ouvinte_e_o_callback_retorna() -> None:
    # Sem `__init__`: nada de descoberta nem rede, só o gancho em `video`.
    connection = VideoHookedConnection.__new__(VideoHookedConnection)
    received: list[object] = []
    connection.video_track_listener = received.append

    # O que a lib faz em `init_webrtc`, antes do evento `track`.
    connection.video = WebRTCVideoChannel(_StubPeer(), None)
    track = object()
    # A lib espera cada callback com `await`: ele precisa retornar logo.
    await asyncio.wait_for(connection.video.track_handler(track), 1.0)

    assert received == [track]
    assert isinstance(connection.video, WebRTCVideoChannel)


async def test_a3_sem_ouvinte_a_track_e_ignorada_sem_erro() -> None:
    connection = VideoHookedConnection.__new__(VideoHookedConnection)
    connection.video = WebRTCVideoChannel(_StubPeer(), None)
    await asyncio.wait_for(connection.video.track_handler(object()), 1.0)
