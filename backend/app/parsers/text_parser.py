from __future__ import annotations

from pathlib import Path

from app.parsers.base import ParseResult, ParsedPage


TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
}


class TextDocumentParser:
    parser_id = "text"

    def supports(self, *, file_name: str, content_type: str) -> bool:
        if content_type.startswith("text/"):
            return True
        return Path(file_name).suffix.lower() in TEXT_FILE_EXTENSIONS

    def parse(self, *, content: bytes, file_name: str, content_type: str) -> ParseResult:
        del file_name, content_type
        text: str | None = None
        for encoding in ("utf-8", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            return ParseResult(
                parser_id=self.parser_id,
                pages=[],
                text_extractable=True,
                error="text decode failed using utf-8 and latin-1",
            )

        pages = text.replace("\r\n", "\n").split("\f")
        result_pages: list[ParsedPage] = []
        for idx, page_text in enumerate(pages, start=1):
            cleaned = page_text.strip()
            if cleaned:
                result_pages.append(ParsedPage(page=idx, text=cleaned))

        return ParseResult(
            parser_id=self.parser_id,
            pages=result_pages,
            text_extractable=True,
        )
