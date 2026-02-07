from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError


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
