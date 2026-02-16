from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


CoverageStatus = Literal["met", "partial", "missing"]


class CoverageItem(BaseModel):
    requirement_id: str = Field(..., min_length=1)
    internal_id: str | None = Field(default=None, min_length=1)
    original_id: str | None = Field(default=None, min_length=1)
    status: CoverageStatus
    notes: str = Field(..., min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class CoverageArtifact(BaseModel):
    items: list[CoverageItem] = Field(default_factory=list)


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _normalize_optional_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    return normalized


def _build_requirement_catalog(
    requirements: dict[str, object],
) -> tuple[dict[str, str], dict[str, str], dict[str, str | None]]:
    canonical: dict[str, str] = {}
    aliases: dict[str, str] = {}
    original_ids: dict[str, str | None] = {}

    questions = requirements.get("questions", [])
    if isinstance(questions, list):
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            prompt = str(question.get("prompt", "")).strip()
            if not prompt:
                continue
            raw_id = str(question.get("internal_id") or question.get("id") or "").strip()
            identifier = raw_id or f"Q{index}"
            canonical[identifier] = prompt
            original_ids[identifier] = _normalize_optional_id(question.get("original_id"))

            aliases[_normalize_text(identifier)] = identifier
            aliases[_normalize_text(prompt)] = identifier
            if original_ids[identifier]:
                aliases[_normalize_text(str(original_ids[identifier]))] = identifier

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
            original_ids[identifier] = None
            aliases[_normalize_text(identifier)] = identifier
            aliases[_normalize_text(attachment_text)] = identifier

    return canonical, aliases, original_ids


def _attachment_index_from_token(token: str) -> int | None:
    cleaned = token.strip().lower()
    if not cleaned:
        return None
    if cleaned.isdigit():
        value = int(cleaned)
        return value if value >= 1 else None
    if len(cleaned) == 1 and "a" <= cleaned <= "z":
        return ord(cleaned) - ord("a") + 1
    return None


def _token_set(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    return set(normalized.split())


def _resolve_requirement_id(
    raw_requirement_id: str,
    canonical: dict[str, str],
    aliases: dict[str, str],
) -> str | None:
    alias_key = _normalize_text(raw_requirement_id)
    if not alias_key:
        return None

    direct = aliases.get(alias_key)
    if direct in canonical:
        return direct

    question_match = re.search(r"\bq(?:uestion)?[_\s-]*(\d+)\b", raw_requirement_id, flags=re.IGNORECASE)
    if question_match:
        question_index = int(question_match.group(1))
        candidate = f"Q{question_index}"
        if candidate in canonical:
            return candidate

    attachment_letter_match = re.search(r"\battachment[_\s-]*([a-z0-9])\b", raw_requirement_id, flags=re.IGNORECASE)
    if attachment_letter_match:
        attachment_index = _attachment_index_from_token(attachment_letter_match.group(1))
        if attachment_index is not None:
            candidate = f"A{attachment_index}"
            if candidate in canonical:
                return candidate

    attachment_digit_match = re.search(r"\ba[_\s-]*(\d+)\b", raw_requirement_id, flags=re.IGNORECASE)
    if attachment_digit_match:
        attachment_index = int(attachment_digit_match.group(1))
        candidate = f"A{attachment_index}"
        if candidate in canonical:
            return candidate

    raw_tokens = _token_set(raw_requirement_id)
    if not raw_tokens:
        return None

    best_id: str | None = None
    best_score = 0.0
    for requirement_id, requirement_text in canonical.items():
        target_tokens = _token_set(requirement_id) | _token_set(requirement_text)
        if not target_tokens:
            continue
        overlap = len(raw_tokens & target_tokens) / len(raw_tokens)
        if overlap > best_score:
            best_score = overlap
            best_id = requirement_id

    if best_id and best_score >= 0.6:
        return best_id
    return None


def normalize_coverage_payload(
    requirements: dict[str, object],
    payload: dict[str, object],
) -> dict[str, object]:
    canonical, aliases, original_ids = _build_requirement_catalog(requirements)
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []

    normalized_items: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_requirement_id = (
            str(item.get("internal_id", "")).strip()
            or str(item.get("requirement_id", "")).strip()
            or str(item.get("original_id", "")).strip()
        )
        if not raw_requirement_id:
            continue

        requirement_id = _resolve_requirement_id(raw_requirement_id, canonical, aliases)
        if requirement_id is None:
            continue
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
                "internal_id": requirement_id,
                "original_id": original_ids.get(requirement_id),
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
                "internal_id": requirement_id,
                "original_id": original_ids.get(requirement_id),
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
        req_id = str(question.get("internal_id") or question.get("id") or "").strip() or "unknown"
        original_id = _normalize_optional_id(question.get("original_id"))
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
                "internal_id": req_id,
                "original_id": original_id,
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
        internal_id = str(item.get("internal_id", "")).strip() or requirement_id
        original_id = _normalize_optional_id(item.get("original_id"))
        status = str(item.get("status", "")).strip()
        notes = str(item.get("notes", "")).strip()
        refs = item.get("evidence_refs", [])
        if not isinstance(refs, list):
            refs = []
        if requirement_id and internal_id and status in {"met", "partial", "missing"} and notes:
            repaired_items.append(
                {
                    "requirement_id": requirement_id,
                    "internal_id": internal_id,
                    "original_id": original_id,
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
