from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


CoverageStatus = Literal["met", "partial", "missing"]


class CoverageItem(BaseModel):
    requirement_id: str = Field(..., min_length=1)
    status: CoverageStatus
    notes: str = Field(..., min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class CoverageArtifact(BaseModel):
    items: list[CoverageItem] = Field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _overlap_score(requirement_text: str, paragraph_text: str) -> float:
    req_tokens = _tokens(requirement_text)
    para_tokens = _tokens(paragraph_text)
    if not req_tokens:
        return 0.0
    return len(req_tokens & para_tokens) / len(req_tokens)


def _evidence_refs(paragraph: dict[str, object]) -> list[str]:
    refs: list[str] = []
    for citation in paragraph.get("citations", []):
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id", "")).strip()
        page = citation.get("page")
        if doc_id and isinstance(page, int):
            refs.append(f"{doc_id}:p{page}")
    return refs


def build_coverage_payload(requirements: dict[str, object], draft: dict[str, object]) -> dict[str, object]:
    questions = requirements.get("questions", [])
    paragraphs = draft.get("paragraphs", [])
    items: list[dict[str, object]] = []

    if not isinstance(questions, list):
        questions = []
    if not isinstance(paragraphs, list):
        paragraphs = []

    for question in questions:
        if not isinstance(question, dict):
            continue
        req_id = str(question.get("id", "")).strip() or "unknown"
        prompt = str(question.get("prompt", "")).strip()
        if not prompt:
            continue

        best_score = 0.0
        best_refs: list[str] = []
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            score = _overlap_score(prompt, str(paragraph.get("text", "")))
            if score > best_score:
                best_score = score
                best_refs = _evidence_refs(paragraph)

        if best_score >= 0.2 and best_refs:
            status: CoverageStatus = "met"
            notes = "Requirement appears fully addressed with cited evidence."
        elif best_score >= 0.08:
            status = "partial"
            notes = "Requirement has partial draft coverage; needs stronger evidence alignment."
        else:
            status = "missing"
            notes = "No meaningful evidence-backed coverage found in draft."

        items.append(
            {
                "requirement_id": req_id,
                "status": status,
                "notes": notes,
                "evidence_refs": best_refs,
            }
        )

    return {"items": items}


def validate_with_repair(payload: dict[str, object]) -> tuple[CoverageArtifact | None, bool, list[str]]:
    try:
        return CoverageArtifact.model_validate(payload), False, []
    except ValidationError as err:
        initial_errors = [issue["msg"] for issue in err.errors()]

    repaired_items: list[dict[str, object]] = []
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id", "")).strip()
        status = str(item.get("status", "")).strip()
        notes = str(item.get("notes", "")).strip()
        refs = item.get("evidence_refs", [])
        if not isinstance(refs, list):
            refs = []
        if requirement_id and status in {"met", "partial", "missing"} and notes:
            repaired_items.append(
                {
                    "requirement_id": requirement_id,
                    "status": status,
                    "notes": notes,
                    "evidence_refs": [str(ref) for ref in refs],
                }
            )

    try:
        return CoverageArtifact.model_validate({"items": repaired_items}), True, initial_errors
    except ValidationError as repaired_err:
        final_errors = [issue["msg"] for issue in repaired_err.errors()]
        return None, True, initial_errors + final_errors
