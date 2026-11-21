"""F-006 A5: o upload é lido em streaming e a leitura para no limite."""

from collections.abc import AsyncIterator

import pytest
from starlette.datastructures import Headers

from app.exceptions import InvalidCommandError, PayloadTooLargeError
from app.requests.library_upload import StreamingUpload

BOUNDARY = "xYzBoundary"
HEADERS = Headers({"content-type": f"multipart/form-data; boundary={BOUNDARY}"})


def _multipart(
    file: bytes | None, filename: str = "som.wav", name: str | None = None
) -> bytes:
    parts = b""
    if name is not None:
        parts += (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="name"\r\n\r\n'
            f"{name}\r\n"
        ).encode()
    if file is not None:
        parts += (
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; "
            f'name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        parts += file + b"\r\n"
    return parts + f"--{BOUNDARY}--\r\n".encode()


class _Stream:
    """Entrega o corpo em pedaços e conta quantos foram lidos."""

    def __init__(self, body: bytes, chunk: int = 1024) -> None:
        self.chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)]
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for piece in self.chunks:
            self.read += 1
            yield piece


async def test_le_arquivo_nome_e_filename() -> None:
    stream = _Stream(_multipart(b"abc" * 1000, filename="ola.mp3", name="meu som"))

    source = await StreamingUpload.read(HEADERS, stream.__aiter__(), 10_000)

    assert source.data == b"abc" * 1000
    assert source.filename == "ola.mp3"
    assert source.name == "meu som"


async def test_sem_name_vem_none() -> None:
    stream = _Stream(_multipart(b"abc"))

    source = await StreamingUpload.read(HEADERS, stream.__aiter__(), 10_000)

    assert source.name is None


async def test_a5_acima_do_limite_para_a_leitura_sem_ler_o_resto() -> None:
    stream = _Stream(_multipart(bytes(100_000)), chunk=1024)

    with pytest.raises(PayloadTooLargeError):
        await StreamingUpload.read(HEADERS, stream.__aiter__(), 10_000)

    assert stream.read < len(stream.chunks) // 2


async def test_no_limite_exato_e_aceito() -> None:
    stream = _Stream(_multipart(bytes(10_000)))

    source = await StreamingUpload.read(HEADERS, stream.__aiter__(), 10_000)

    assert len(source.data) == 10_000


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        (HEADERS, _multipart(None, name="x")),
        (Headers({"content-type": "application/json"}), b"{}"),
        (Headers({"content-type": "multipart/form-data"}), b"--x--"),
        (HEADERS, b"lixo sem boundary"),
    ],
    ids=["sem-file", "nao-multipart", "sem-boundary", "malformado"],
)
async def test_corpo_sem_arquivo_ou_invalido_e_422(
    headers: Headers, body: bytes
) -> None:
    with pytest.raises(InvalidCommandError):
        await StreamingUpload.read(headers, _Stream(body).__aiter__(), 10_000)
