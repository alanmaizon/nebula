from __future__ import annotations

import io
from pathlib import Path

from app.parsers.base import ParseResult, ParsedPage


class PdfDocumentParser:
    parser_id = "pdf"
    _CONTENT_TYPES = {"application/pdf"}

    def supports(self, *, file_name: str, content_type: str) -> bool:
        if content_type.lower() in self._CONTENT_TYPES:
            return True
        return Path(file_name).suffix.lower() == ".pdf"

    def parse(self, *, content: bytes, file_name: str, content_type: str) -> ParseResult:
        del file_name, content_type
        try:
            from pypdf import PdfReader
        except ImportError:
            return ParseResult(
                parser_id=self.parser_id,
                pages=[],
                text_extractable=True,
                error="pypdf is not installed",
            )

        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            pages: list[ParsedPage] = []
            for index, page in enumerate(reader.pages, start=1):
                extracted = page.extract_text() or ""
                cleaned = " ".join(extracted.split()).strip()
                if cleaned:
                    pages.append(ParsedPage(page=index, text=cleaned))

            return ParseResult(
                parser_id=self.parser_id,
                pages=pages,
                text_extractable=True,
            )
        except Exception as exc:
            return ParseResult(
                parser_id=self.parser_id,
                pages=[],
                text_extractable=True,
                error=f"pdf parse failed: {exc}",
            )
