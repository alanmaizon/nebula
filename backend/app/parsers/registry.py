from __future__ import annotations

from app.parsers.base import DocumentParser, ParseResult
from app.parsers.docx_parser import DocxDocumentParser
from app.parsers.pdf_parser import PdfDocumentParser
from app.parsers.rtf_parser import RtfDocumentParser
from app.parsers.text_parser import TextDocumentParser


class ParserRegistry:
    def __init__(self, parsers: list[DocumentParser] | None = None) -> None:
        self._parsers = parsers or [
            PdfDocumentParser(),
            DocxDocumentParser(),
            RtfDocumentParser(),
            TextDocumentParser(),
        ]

    def parse(self, *, content: bytes, file_name: str, content_type: str) -> ParseResult:
        for parser in self._parsers:
            if not parser.supports(file_name=file_name, content_type=content_type):
                continue
            return parser.parse(content=content, file_name=file_name, content_type=content_type)
        return ParseResult(
            parser_id="none",
            pages=[],
            text_extractable=False,
            error="No parser registered for this file type.",
        )
