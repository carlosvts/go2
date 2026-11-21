"""F-006 A5, F-007 A8: o upload é lido em streaming e a leitura para no limite."""

from collections.abc import AsyncIterator

import pytest

from app.exceptions import InvalidCommandError, PayloadTooLargeError
from app.requests.upload import (
    MAX_TEXT_FIELD_BYTES,
    MultipartUpload,
    read_multipart,
)

BOUNDARY = "xYzBoundary"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"


def _multipart(
    file: bytes | None, filename: str | None = "som.wav", name: str | None = None
) -> bytes:
    parts = b""
    if name is not None:
        parts += (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="name"\r\n\r\n'
            f"{name}\r\n"
        ).encode()
    if file is not None:
        parts += (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"'
            + (f'; filename="{filename}"' if filename is not None else "")
            + "\r\n"
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


async def _read(
    body: bytes,
    *,
    content_type: str | None = CONTENT_TYPE,
    content_length: str | None = None,
    max_bytes: int = 10_000,
    chunk: int = 1024,
) -> tuple[MultipartUpload, _Stream]:
    stream = _Stream(body, chunk=chunk)
    upload = await read_multipart(
        content_type,
        content_length,
        stream.__aiter__(),
        max_bytes=max_bytes,
        text_fields=("name",),
    )
    return upload, stream


async def test_le_arquivo_nome_e_filename() -> None:
    upload, _ = await _read(
        _multipart(b"abc" * 1000, filename="ola.mp3", name="meu som")
    )

    assert upload.data == b"abc" * 1000
    assert upload.filename == "ola.mp3"
    assert upload.fields == {"name": "meu som"}


async def test_sem_name_nem_filename() -> None:
    upload, _ = await _read(_multipart(b"abc", filename=None))

    assert upload.fields == {}
    assert upload.filename is None


async def test_campo_de_texto_nao_pedido_e_ignorado() -> None:
    stream = _Stream(_multipart(b"abc", name="x"))
    upload = await read_multipart(
        CONTENT_TYPE, None, stream.__aiter__(), max_bytes=10_000
    )

    assert upload.fields == {}


async def test_acima_do_limite_para_a_leitura_sem_ler_o_resto() -> None:
    stream = _Stream(_multipart(bytes(100_000)), chunk=1024)

    with pytest.raises(PayloadTooLargeError):
        await read_multipart(CONTENT_TYPE, None, stream.__aiter__(), max_bytes=10_000)

    assert stream.read < len(stream.chunks) // 2


async def test_content_length_acima_do_limite_recusa_sem_ler() -> None:
    stream = _Stream(_multipart(b"abc"))

    with pytest.raises(PayloadTooLargeError):
        await read_multipart(
            CONTENT_TYPE, str(10_000_000), stream.__aiter__(), max_bytes=10_000
        )

    assert stream.read == 0


async def test_no_limite_exato_e_aceito() -> None:
    upload, _ = await _read(_multipart(bytes(10_000)))

    assert len(upload.data) == 10_000


async def test_campo_de_texto_grande_demais_e_422() -> None:
    with pytest.raises(InvalidCommandError):
        await _read(_multipart(b"abc", name="x" * (MAX_TEXT_FIELD_BYTES + 1)))


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        (CONTENT_TYPE, _multipart(None, name="x")),
        ("application/json", b"{}"),
        ("multipart/form-data", b"--x--"),
        (None, b""),
        (CONTENT_TYPE, b"lixo sem boundary"),
    ],
    ids=["sem-file", "nao-multipart", "sem-boundary", "sem-content-type", "malformado"],
)
async def test_corpo_sem_arquivo_ou_invalido_e_422(
    content_type: str | None, body: bytes
) -> None:
    with pytest.raises(InvalidCommandError):
        await _read(body, content_type=content_type)
