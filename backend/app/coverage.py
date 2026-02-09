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


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _build_requirement_catalog(requirements: dict[str, object]) -> tuple[dict[str, str], dict[str, str]]:
    canonical: dict[str, str] = {}
    aliases: dict[str, str] = {}

    questions = requirements.get("questions", [])
    if isinstance(questions, list):
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            prompt = str(question.get("prompt", "")).strip()
            if not prompt:
                continue
            raw_id = str(question.get("id", "")).strip()
            identifier = raw_id or f"Q{index}"
            canonical[identifier] = prompt

            aliases[_normalize_text(identifier)] = identifier
            aliases[_normalize_text(prompt)] = identifier

            digits_match = re.fullmatch(r"[Qq]?(\d+)", identifier)
            if digits_match:
                number = digits_match.group(1)
                aliases[_normalize_text(number)] = identifier
                aliases[_normalize_text(f"question {number}")] = identifier

    attachments = requirements.get("required_attachments", [])
    if isinstance(attachments, list):
        attachment_index = 1
        for attachment in attachments:
            attachment_text = str(attachment).strip()
            if not attachment_text:
                continue
            identifier = f"A{attachment_index}"
            attachment_index += 1
            canonical[identifier] = attachment_text
            aliases[_normalize_text(identifier)] = identifier
            aliases[_normalize_text(attachment_text)] = identifier

    return canonical, aliases


def normalize_coverage_payload(
    requirements: dict[str, object],
    payload: dict[str, object],
) -> dict[str, object]:
    canonical, aliases = _build_requirement_catalog(requirements)
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []

    normalized_items: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_requirement_id = str(item.get("requirement_id", "")).strip()
        if not raw_requirement_id:
            continue

        alias_key = _normalize_text(raw_requirement_id)
        requirement_id = aliases.get(alias_key, raw_requirement_id)
        status = str(item.get("status", "")).strip()
        notes = str(item.get("notes", "")).strip()
        refs = item.get("evidence_refs", [])
        if not isinstance(refs, list):
            refs = []

        if not notes:
            notes = "Coverage note unavailable."
        if status not in {"met", "partial", "missing"}:
            status = "missing"

        existing_index = next(
            (index for index, existing in enumerate(normalized_items) if existing["requirement_id"] == requirement_id),
            None,
        )
        if existing_index is not None:
            continue

        normalized_items.append(
            {
                "requirement_id": requirement_id,
                "status": status,
                "notes": notes,
                "evidence_refs": [str(ref) for ref in refs],
            }
        )
        seen_ids.add(requirement_id)

    for requirement_id, requirement_text in canonical.items():
        if requirement_id in seen_ids:
            continue
        normalized_items.append(
            {
                "requirement_id": requirement_id,
                "status": "missing",
                "notes": f"No coverage item returned for requirement: {requirement_text}",
                "evidence_refs": [],
            }
        )

    return {"items": normalized_items}


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
