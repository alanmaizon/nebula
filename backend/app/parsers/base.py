from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ParsedPage:
    page: int
    text: str


@dataclass(frozen=True)
class ParseResult:
    parser_id: str
    pages: list[ParsedPage]
    text_extractable: bool
    error: str | None = None
    fallback_parser_id: str | None = None


class DocumentParser(Protocol):
    parser_id: str

    def supports(self, *, file_name: str, content_type: str) -> bool:
        ...

    def parse(self, *, content: bytes, file_name: str, content_type: str) -> ParseResult:
        ...
