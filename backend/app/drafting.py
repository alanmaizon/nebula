from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

INLINE_CITATION_PATTERN = re.compile(
    r"\(\s*(?:doc(?:_id)?|source)\s*[:=]\s*([^,)\n]+)\s*,\s*page\s*[:=]\s*(\d+)\s*\)",
    flags=re.IGNORECASE,
)


class DraftCitation(BaseModel):
    doc_id: str = Field(..., min_length=1)
    page: int = Field(..., ge=1)
    snippet: str = Field(..., min_length=1)


class DraftParagraph(BaseModel):
    text: str = Field(..., min_length=1)
    citations: list[DraftCitation] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class MissingEvidenceItem(BaseModel):
    claim: str = Field(..., min_length=1)
    suggested_upload: str = Field(..., min_length=1)


class DraftArtifact(BaseModel):
    section_key: str = Field(..., min_length=1)
    paragraphs: list[DraftParagraph] = Field(default_factory=list)
    missing_evidence: list[MissingEvidenceItem] = Field(default_factory=list)


def _confidence_from_score(score: float) -> float:
    mapped = (score + 1.0) / 2.0
    return max(0.0, min(1.0, mapped))


def build_draft_payload(section_key: str, ranked_chunks: list[dict[str, object]]) -> dict[str, object]:
    if not ranked_chunks:
        return {
            "section_key": section_key,
            "paragraphs": [],
            "missing_evidence": [
                {
                    "claim": f"Insufficient evidence to draft section '{section_key}'.",
                    "suggested_upload": "Upload an RFP and relevant source documents containing program outcomes.",
                }
            ],
        }

    paragraphs: list[dict[str, object]] = []
    for chunk in ranked_chunks[:3]:
        text = str(chunk["text"]).strip()
        snippet = text[:240].strip()
        paragraph_text = (
            f"{section_key}: {text[:450].strip()}"
            if not text.lower().startswith(section_key.lower())
            else text[:450].strip()
        )
        paragraphs.append(
            {
                "text": paragraph_text,
                "citations": [
                    {
                        "doc_id": str(chunk["file_name"]),
                        "page": int(chunk["page"]),
                        "snippet": snippet,
                    }
                ],
                "confidence": round(_confidence_from_score(float(chunk["score"])), 3),
            }
        )

    return {
        "section_key": section_key,
        "paragraphs": paragraphs,
        "missing_evidence": [],
    }


def _normalize_doc_key(value: str) -> str:
    name = Path(value.strip()).name
    stem = Path(name).stem
    return re.sub(r"[^a-z0-9]+", "", stem.lower())


def _coerce_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _truncate(text: str, limit: int = 240) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _extract_inline_citations(paragraph_text: str) -> tuple[str, list[dict[str, object]]]:
    candidates: list[dict[str, object]] = []
    for match in INLINE_CITATION_PATTERN.finditer(paragraph_text):
        doc_id = match.group(1).strip()
        page = _coerce_positive_int(match.group(2))
        if not doc_id or page is None:
            continue
        candidates.append({"doc_id": doc_id, "page": page, "snippet": ""})
    cleaned_text = " ".join(INLINE_CITATION_PATTERN.sub("", paragraph_text).split()).strip()
    return cleaned_text, candidates


def _build_evidence_index(ranked_chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for chunk in ranked_chunks:
        file_name = str(chunk.get("file_name", "")).strip()
        page = _coerce_positive_int(chunk.get("page"))
        text = str(chunk.get("text", "")).strip()
        if not file_name or page is None or not text:
            continue
        entries.append(
            {
                "file_name": file_name,
                "doc_key": _normalize_doc_key(file_name),
                "page": page,
                "text": text,
            }
        )
    return entries


def _normalize_citation_candidate(citation: object) -> dict[str, object] | None:
    if not isinstance(citation, dict):
        return None
    doc_id = str(
        citation.get("doc_id")
        or citation.get("doc")
        or citation.get("source")
        or citation.get("file_name")
        or ""
    ).strip()
    if not doc_id:
        return None
    page = _coerce_positive_int(citation.get("page"))
    snippet = str(citation.get("snippet") or citation.get("text") or "").strip()
    return {
        "doc_id": doc_id,
        "doc_key": _normalize_doc_key(doc_id),
        "page": page,
        "snippet": snippet,
    }


def _pick_evidence_match(candidate: dict[str, object], evidence_entries: list[dict[str, object]]) -> dict[str, object] | None:
    doc_key = str(candidate.get("doc_key", "")).strip()
    page = _coerce_positive_int(candidate.get("page"))

    if doc_key and page is not None:
        for entry in evidence_entries:
            if entry["doc_key"] == doc_key and entry["page"] == page:
                return entry
    if doc_key:
        for entry in evidence_entries:
            if entry["doc_key"] == doc_key:
                return entry
        return None
    if page is not None:
        for entry in evidence_entries:
            if entry["page"] == page:
                return entry
    return None


def ground_draft_payload(
    payload: dict[str, object],
    ranked_chunks: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, int]]:
    repaired = repair_draft_payload(payload)
    evidence_entries = _build_evidence_index(ranked_chunks)

    stats = {
        "paragraphs_total": len(repaired.get("paragraphs", [])),
        "citations_before": 0,
        "citations_after": 0,
        "inline_citations_parsed": 0,
        "fallback_citations_added": 0,
        "citations_dropped": 0,
    }

    for paragraph in repaired.get("paragraphs", []):
        if not isinstance(paragraph, dict):
            continue
        paragraph_text = str(paragraph.get("text", "")).strip()
        cleaned_text, inline_candidates = _extract_inline_citations(paragraph_text)
        if cleaned_text:
            paragraph["text"] = cleaned_text

        raw_citations = paragraph.get("citations", [])
        if not isinstance(raw_citations, list):
            raw_citations = []
        stats["citations_before"] += len(raw_citations)
        stats["inline_citations_parsed"] += len(inline_candidates)

        candidates: list[dict[str, object]] = []
        for item in raw_citations:
            normalized = _normalize_citation_candidate(item)
            if normalized is not None:
                candidates.append(normalized)
        for item in inline_candidates:
            normalized = _normalize_citation_candidate(item)
            if normalized is not None:
                candidates.append(normalized)
        had_citation_candidates = len(candidates) > 0

        grounded: list[dict[str, object]] = []
        seen: set[str] = set()
        for candidate in candidates:
            match = _pick_evidence_match(candidate, evidence_entries)
            if match is None:
                stats["citations_dropped"] += 1
                continue
            snippet = str(candidate.get("snippet", "")).strip()
            evidence_text = str(match["text"])
            if not snippet or snippet.lower() not in evidence_text.lower():
                snippet = _truncate(evidence_text)
            citation = {
                "doc_id": str(match["file_name"]),
                "page": int(match["page"]),
                "snippet": snippet,
            }
            dedupe_key = f"{citation['doc_id'].lower()}:{citation['page']}:{citation['snippet'].lower()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            grounded.append(citation)

        if not grounded and evidence_entries and not had_citation_candidates:
            top = evidence_entries[0]
            grounded.append(
                {
                    "doc_id": str(top["file_name"]),
                    "page": int(top["page"]),
                    "snippet": _truncate(str(top["text"])),
                }
            )
            stats["fallback_citations_added"] += 1

        paragraph["citations"] = grounded
        stats["citations_after"] += len(grounded)

    return repaired, stats


def normalize_draft_section_key(payload: dict[str, object], section_key: str) -> dict[str, object]:
    normalized = dict(payload)
    normalized["section_key"] = section_key
    return normalized


def repair_draft_payload(payload: dict[str, object]) -> dict[str, object]:
    repaired = dict(payload)
    if not isinstance(repaired.get("paragraphs"), list):
        repaired["paragraphs"] = []
    if not isinstance(repaired.get("missing_evidence"), list):
        repaired["missing_evidence"] = []

    fixed_paragraphs: list[dict[str, object]] = []
    for paragraph in repaired["paragraphs"]:
        if not isinstance(paragraph, dict):
            continue
        text = str(paragraph.get("text", "")).strip()
        if not text:
            continue
        citations = paragraph.get("citations", [])
        if not isinstance(citations, list):
            citations = []
        confidence = paragraph.get("confidence", 0.2)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.2
        fixed_paragraphs.append(
            {
                "text": text,
                "citations": citations,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    repaired["paragraphs"] = fixed_paragraphs

    fixed_missing: list[dict[str, str]] = []
    for item in repaired["missing_evidence"]:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        suggested = str(item.get("suggested_upload", "")).strip()
        if claim and suggested:
            fixed_missing.append({"claim": claim, "suggested_upload": suggested})
    if not fixed_paragraphs and not fixed_missing:
        section_name = str(repaired.get("section_key", "section")).strip() or "section"
        fixed_missing.append(
            {
                "claim": f"No draft content generated for section '{section_name}'.",
                "suggested_upload": "Upload stronger evidence or regenerate this section with the relevant source documents.",
            }
        )
    repaired["missing_evidence"] = fixed_missing
    return repaired


def validate_with_repair(payload: dict[str, object]) -> tuple[DraftArtifact | None, bool, list[str]]:
    try:
        return DraftArtifact.model_validate(payload), False, []
    except ValidationError as err:
        initial_errors = [issue["msg"] for issue in err.errors()]

    repaired_payload = repair_draft_payload(payload)
    try:
        return DraftArtifact.model_validate(repaired_payload), True, initial_errors
    except ValidationError as repaired_err:
        final_errors = [issue["msg"] for issue in repaired_err.errors()]
        return None, True, initial_errors + final_errors
