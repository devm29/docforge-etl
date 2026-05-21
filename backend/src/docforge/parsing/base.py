from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath
from typing import Protocol

from docforge.domain.documents import DocumentFormat, DocumentModel
from docforge.errors import UnsupportedFormatError


class Parser(Protocol):
    formats: frozenset[DocumentFormat]
    version: str

    def parse(self, data: bytes) -> DocumentModel: ...


def detect_format(filename: str, data: bytes) -> DocumentFormat:
    """Sniff the format from magic bytes, using the extension only to disambiguate text files."""
    if data.startswith(b"%PDF"):
        return DocumentFormat.PDF
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise UnsupportedFormatError(f"{filename} looks like a zip archive but cannot be opened") from exc
        if "word/document.xml" in names:
            return DocumentFormat.DOCX
        if "xl/workbook.xml" in names:
            return DocumentFormat.XLSX
        raise UnsupportedFormatError(f"{filename} is an OOXML package that is neither DOCX nor XLSX")
    if PurePosixPath(filename).suffix.lower() == ".csv":
        try:
            data[:4096].decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UnsupportedFormatError(f"{filename} is not UTF-8 text") from exc
        return DocumentFormat.CSV
    raise UnsupportedFormatError(f"cannot determine the format of {filename}")


class ParserRegistry:
    def __init__(self, parsers: list[Parser]) -> None:
        self._by_format: dict[DocumentFormat, Parser] = {}
        for parser in parsers:
            for fmt in parser.formats:
                self._by_format[fmt] = parser

    def for_format(self, fmt: DocumentFormat) -> Parser:
        parser = self._by_format.get(fmt)
        if parser is None:
            raise UnsupportedFormatError(f"no parser registered for {fmt.value}")
        return parser

    def version(self) -> str:
        return ",".join(f"{fmt.value}:{parser.version}" for fmt, parser in sorted(self._by_format.items()))


def default_registry() -> ParserRegistry:
    from docforge.parsing.docx import DocxParser
    from docforge.parsing.pdf import PdfParser
    from docforge.parsing.spreadsheet import CsvParser, XlsxParser

    return ParserRegistry([PdfParser(), DocxParser(), XlsxParser(), CsvParser()])
