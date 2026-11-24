"""Leitura de `multipart/form-data` em streaming, com teto (F-006, F-007).

O `UploadFile` do Starlette lê o corpo inteiro antes da rota e passa de 1 MiB
para arquivo temporário em disco. Aqui o corpo é lido aos pedaços, o arquivo
fica só em memória, e a leitura para assim que ele passa do teto: o resto do
corpo não é lido.

Usado por `POST /audio/files` (arquivo + `name` opcional) e por
`POST /speaker/play` (só o arquivo).
"""

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.exceptions import InvalidCommandError, PayloadTooLargeError

FILE_FIELD = "file"
MAX_TEXT_FIELD_BYTES = 4096
"""Teto de cada campo de texto (o `name` válido tem até 64 caracteres)."""

_ENVELOPE_SLACK_BYTES = 64 * 1024
"""Folga para os cabeçalhos do multipart na recusa pelo `Content-Length`."""


@dataclass(frozen=True)
class MultipartUpload:
    """O arquivo enviado e os campos de texto pedidos que vieram."""

    data: bytes
    filename: str | None
    """`filename` do `Content-Disposition`, ou `None` se não veio."""
    fields: dict[str, str] = field(default_factory=dict)
    """Só os campos pedidos em `text_fields` que vieram no corpo."""


def too_large_message(max_bytes: int) -> str:
    """Mensagem do `413`."""
    mib = max_bytes / (1024 * 1024)
    return f"❌ Arquivo acima de {mib:g} MiB (GO2_AUDIO_MAX_UPLOAD_MB)."


class _Collector:
    """Callbacks do `python_multipart`: guarda o arquivo e os campos pedidos."""

    def __init__(
        self, file_field: str, text_fields: frozenset[str], max_bytes: int
    ) -> None:
        self._file_field = file_field
        self._text_fields = text_fields
        self._max_bytes = max_bytes
        self._header_name = b""
        self._header_value = b""
        self._disposition = b""
        self._target: str | None = None
        self.file = bytearray()
        self.filename: str | None = None
        self.has_file = False
        self.texts: dict[str, bytearray] = {}

    def on_part_begin(self) -> None:
        self._disposition = b""
        self._target = None

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
        if name == self._file_field and not self.has_file:
            self.has_file = True
            raw = options.get(b"filename")
            self.filename = raw.decode("utf-8", "replace") if raw is not None else None
            self._target = self._file_field
        elif name in self._text_fields and name not in self.texts:
            self.texts[name] = bytearray()
            self._target = name

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._target is None:
            return
        piece = data[start:end]
        if self._target == self._file_field:
            if len(self.file) + len(piece) > self._max_bytes:
                raise PayloadTooLargeError(too_large_message(self._max_bytes))
            self.file += piece
            return
        text = self.texts[self._target]
        if len(text) + len(piece) > MAX_TEXT_FIELD_BYTES:
            msg = f"❌ O campo `{self._target}` é grande demais."
            raise InvalidCommandError(msg)
        text += piece

    def on_part_end(self) -> None:
        self._target = None

    def callbacks(self) -> dict[str, object]:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
        }


async def read_multipart(  # noqa: PLR0913 - tudo por nome, sem objeto extra
    content_type: str | None,
    content_length: str | None,
    stream: AsyncIterator[bytes],
    *,
    max_bytes: int,
    file_field: str = FILE_FIELD,
    text_fields: Iterable[str] = (),
) -> MultipartUpload:
    """Lê o arquivo de `file_field` e os campos `text_fields`, com teto.

    Raises:
        PayloadTooLargeError: o arquivo, ou o `Content-Length` (com folga
            para os cabeçalhos), passa de `max_bytes`; o resto do corpo não é
            lido.
        InvalidCommandError: não é `multipart/form-data`, está malformado,
            falta o arquivo ou um campo de texto passa de
            :data:`MAX_TEXT_FIELD_BYTES` (vira `422`).
    """
    kind, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if kind != b"multipart/form-data" or not boundary:
        msg = f"❌ Envie multipart/form-data com o arquivo no campo `{file_field}`."
        raise InvalidCommandError(msg)
    if (
        content_length is not None
        and content_length.isdigit()
        and int(content_length) > max_bytes + _ENVELOPE_SLACK_BYTES
    ):
        raise PayloadTooLargeError(too_large_message(max_bytes))
    collector = _Collector(file_field, frozenset(text_fields), max_bytes)
    parser = MultipartParser(boundary, collector.callbacks())  # type: ignore[arg-type]
    try:
        async for chunk in stream:
            parser.write(chunk)
        parser.finalize()
    except FormParserError as exc:
        msg = "❌ multipart/form-data malformado."
        raise InvalidCommandError(msg) from exc
    if not collector.has_file:
        msg = f"❌ Falta o arquivo no campo `{file_field}`."
        raise InvalidCommandError(msg)
    fields = {k: v.decode("utf-8", "replace") for k, v in collector.texts.items()}
    return MultipartUpload(bytes(collector.file), collector.filename, fields)
