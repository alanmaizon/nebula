from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class ExtractedPage:
    page: int
    text: str


@dataclass(frozen=True)
class ChunkPayload:
    chunk_index: int
    page: int
    text: str
    embedding: list[float]


def _is_text_file(content_type: str, file_name: str) -> bool:
    if content_type.startswith("text/"):
        return True
    return Path(file_name).suffix.lower() in TEXT_FILE_EXTENSIONS


def extract_text_pages(content: bytes, content_type: str, file_name: str) -> list[ExtractedPage]:
    if not _is_text_file(content_type=content_type, file_name=file_name):
        return []

    text: str | None = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        return []

    pages = text.replace("\r\n", "\n").split("\f")
    result: list[ExtractedPage] = []
    for idx, page_text in enumerate(pages, start=1):
        cleaned = page_text.strip()
        if cleaned:
            result.append(ExtractedPage(page=idx, text=cleaned))
    return result


def chunk_pages(
    pages: list[ExtractedPage],
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    embedding_dim: int,
) -> list[ChunkPayload]:
    if chunk_size_chars < 1:
        raise ValueError("chunk_size_chars must be >= 1")
    if embedding_dim < 8:
        raise ValueError("embedding_dim must be >= 8")

    step = max(1, chunk_size_chars - max(0, chunk_overlap_chars))
    chunk_counter = 0
    chunks: list[ChunkPayload] = []

    for page in pages:
        start = 0
        text = page.text
        while start < len(text):
            end = min(start + chunk_size_chars, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk_counter += 1
                chunks.append(
                    ChunkPayload(
                        chunk_index=chunk_counter,
                        page=page.page,
                        text=chunk_text,
                        embedding=embed_text(chunk_text, embedding_dim),
                    )
                )
            if end >= len(text):
                break
            start += step

    return chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def embed_text(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vector dimensions do not match")
    return float(sum(x * y for x, y in zip(a, b)))

