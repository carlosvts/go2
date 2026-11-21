"""Leitura em streaming do `multipart/form-data` de `POST /audio/files` (F-006).

O `UploadFile` do FastAPI lê o corpo inteiro antes de a rota rodar. Aqui o
corpo é lido aos pedaços, e a leitura para assim que o arquivo passa do
limite, sem consumir o resto.
"""

from collections.abc import AsyncIterator, Mapping

from python_multipart import MultipartParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header

from app.exceptions import InvalidCommandError, PayloadTooLargeError
from app.robot.audio import UploadSource

FILE_FIELD = "file"
NAME_FIELD = "name"
_MAX_FIELD_BYTES = 4096  # o `name` válido tem até 64 caracteres


class _Collector:
    """Callbacks do parser: guarda o arquivo e o campo `name`."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.file = bytearray()
        self.filename: str | None = None
        self.has_file = False
        self.name: bytearray | None = None
        self.too_large = False
        self.field_too_large = False
        self._header_field = b""
        self._header_value = b""
        self._disposition = b""
        self._target: str | None = None

    def on_part_begin(self) -> None:
        self._disposition = b""
        self._target = None

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        if self._header_field.lower() == b"content-disposition":
            self._disposition = self._header_value
        self._header_field = b""
        self._header_value = b""

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        field = options.get(b"name", b"").decode("utf-8", "replace")
        if field == FILE_FIELD and not self.has_file:
            self.has_file = True
            raw = options.get(b"filename")
            self.filename = raw.decode("utf-8", "replace") if raw is not None else None
            self._target = FILE_FIELD
        elif field == NAME_FIELD and self.name is None:
            self.name = bytearray()
            self._target = NAME_FIELD

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._target == FILE_FIELD:
            if len(self.file) + (end - start) > self.max_bytes:
                self.too_large = True
                return
            self.file += data[start:end]
        elif self._target == NAME_FIELD and self.name is not None:
            if len(self.name) + (end - start) > _MAX_FIELD_BYTES:
                self.field_too_large = True
                return
            self.name += data[start:end]

    def callbacks(self) -> dict[str, object]:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
        }


class StreamingUpload:
    """Lê o arquivo (`file`) e o nome opcional (`name`) de um multipart."""

    @staticmethod
    async def read(
        headers: Mapping[str, str], stream: AsyncIterator[bytes], max_bytes: int
    ) -> UploadSource:
        """Consome `stream` até o fim, ou até o arquivo passar de `max_bytes`.

        Raises:
            PayloadTooLargeError: o arquivo passa de `max_bytes`; o resto do
                corpo não é lido.
            InvalidCommandError: corpo que não é multipart, sem o campo
                `file` ou malformado (vira `422`).
        """
        content_type, params = parse_options_header(headers.get("content-type"))
        boundary = params.get(b"boundary")
        if content_type != b"multipart/form-data" or not boundary:
            msg = "❌ Envie multipart/form-data com o campo `file`."
            raise InvalidCommandError(msg)
        collector = _Collector(max_bytes)
        try:
            parser = MultipartParser(boundary, collector.callbacks())  # type: ignore[arg-type]
            async for chunk in stream:
                parser.write(chunk)
                if collector.too_large:
                    msg = f"❌ O arquivo passa do limite de {max_bytes} bytes."
                    raise PayloadTooLargeError(msg)
                if collector.field_too_large:
                    msg = "❌ O campo `name` é grande demais."
                    raise InvalidCommandError(msg)
            parser.finalize()
        except FormParserError as exc:
            msg = "❌ multipart/form-data malformado."
            raise InvalidCommandError(msg) from exc
        if not collector.has_file:
            msg = "❌ Falta o campo `file`."
            raise InvalidCommandError(msg)
        name = (
            collector.name.decode("utf-8", "replace")
            if collector.name is not None
            else None
        )
        return UploadSource(
            data=bytes(collector.file), filename=collector.filename, name=name
        )
