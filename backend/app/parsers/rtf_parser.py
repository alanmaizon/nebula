from __future__ import annotations

from pathlib import Path

from app.parsers.base import ParseResult, ParsedPage


class RtfDocumentParser:
    parser_id = "rtf"
    _CONTENT_TYPES = {"application/rtf", "text/rtf"}

    def supports(self, *, file_name: str, content_type: str) -> bool:
        if content_type.lower() in self._CONTENT_TYPES:
            return True
        return Path(file_name).suffix.lower() == ".rtf"

    def parse(self, *, content: bytes, file_name: str, content_type: str) -> ParseResult:
        del file_name, content_type
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError:
            return ParseResult(
                parser_id=self.parser_id,
                pages=[],
                text_extractable=True,
                error="striprtf is not installed",
            )

        decoded: str | None = None
        for encoding in ("utf-8", "latin-1"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if decoded is None:
            return ParseResult(
                parser_id=self.parser_id,
                pages=[],
                text_extractable=True,
                error="rtf decode failed using utf-8 and latin-1",
            )

        try:
            text = rtf_to_text(decoded)
        except Exception as exc:
            return ParseResult(
                parser_id=self.parser_id,
                pages=[],
                text_extractable=True,
                error=f"rtf parse failed: {exc}",
            )

        cleaned = "\n".join([line.strip() for line in text.splitlines() if line.strip()]).strip()
        pages = [ParsedPage(page=1, text=cleaned)] if cleaned else []
        return ParseResult(
            parser_id=self.parser_id,
            pages=pages,
            text_extractable=True,
        )
