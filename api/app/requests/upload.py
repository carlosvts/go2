"""Leitura de um arquivo de `multipart/form-data` em streaming, com teto.

O `UploadFile` do Starlette lê o corpo inteiro e passa de 1 MiB para arquivo
temporário em disco antes do handler. Aqui o corpo é lido aos pedaços, o
arquivo fica só em memória, e a leitura para assim que passa do teto (F-007).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.exceptions import InvalidCommandError, PayloadTooLargeError

# Folga para os cabeçalhos do multipart no teste do `Content-Length`.
_ENVELOPE_SLACK_BYTES = 64 * 1024


@dataclass(frozen=True)
class UploadedFile:
    """Conteúdo e nome de um arquivo enviado."""

    filename: str
    data: bytes


def too_large_message(max_bytes: int) -> str:
    """Mensagem do `413`."""
    mib = max_bytes / (1024 * 1024)
    return f"❌ Arquivo acima de {mib:g} MiB (GO2_AUDIO_MAX_UPLOAD_MB)."


class _FilePartCollector:
    """Callbacks do `python_multipart`: guarda só o campo `field`."""

    def __init__(self, field: str, max_bytes: int) -> None:
        self._field = field
        self._max_bytes = max_bytes
        self._header_name = b""
        self._header_value = b""
        self._disposition = b""
        self._in_target = False
        self._buffer = bytearray()
        self.found: UploadedFile | None = None
        self._filename = ""

    def on_part_begin(self) -> None:
        self._disposition = b""
        self._in_target = False

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        if self._header_name.lower() == b"content-disposition":
            self._disposition = self._header_value
        self._header_name = b""
        self._header_value = b""

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        name = options.get(b"name", b"").decode("utf-8", "replace")
        self._in_target = self.found is None and name == self._field
        if self._in_target:
            raw = options.get(b"filename", b"")
            self._filename = raw.decode("utf-8", "replace")
            self._buffer = bytearray()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._in_target:
            return
        self._buffer += data[start:end]
        if len(self._buffer) > self._max_bytes:
            raise PayloadTooLargeError(too_large_message(self._max_bytes))

    def on_part_end(self) -> None:
        if self._in_target:
            self.found = UploadedFile(self._filename, bytes(self._buffer))
            self._in_target = False


async def read_file_field(
    content_type: str | None,
    content_length: str | None,
    stream: AsyncIterator[bytes],
    *,
    field: str,
    max_bytes: int,
) -> UploadedFile:
    """Lê o arquivo do campo `field`, parando ao passar de `max_bytes`.

    Raises:
        PayloadTooLargeError: o arquivo (ou o `Content-Length`) passa do teto.
        InvalidCommandError: não é `multipart/form-data` ou falta o campo
            (vira `422`).
    """
    kind, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if kind != b"multipart/form-data" or not boundary:
        msg = f"❌ Envie o arquivo em multipart/form-data, no campo {field!r}."
        raise InvalidCommandError(msg)
    collector = _FilePartCollector(field, max_bytes)
    if (
        content_length is not None
        and content_length.isdigit()
        and int(content_length) > max_bytes + _ENVELOPE_SLACK_BYTES
    ):
        raise PayloadTooLargeError(too_large_message(max_bytes))
    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": collector.on_part_begin,
            "on_part_data": collector.on_part_data,
            "on_part_end": collector.on_part_end,
            "on_header_field": collector.on_header_field,
            "on_header_value": collector.on_header_value,
            "on_header_end": collector.on_header_end,
            "on_headers_finished": collector.on_headers_finished,
        },
    )
    try:
        async for chunk in stream:
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        msg = f"❌ multipart/form-data inválido: {exc}"
        raise InvalidCommandError(msg) from exc
    if collector.found is None:
        msg = f"❌ Falta o arquivo no campo {field!r}."
        raise InvalidCommandError(msg)
    return collector.found
