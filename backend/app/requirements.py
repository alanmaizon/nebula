from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class QuestionLimit(BaseModel):
    type: Literal["words", "chars", "none"] = "none"
    value: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_limit(self) -> "QuestionLimit":
        if self.type == "none":
            self.value = None
        elif self.value is None:
            self.value = 1
        return self


class RequirementQuestion(BaseModel):
    id: str = Field(..., min_length=1)
    internal_id: str | None = Field(default=None, min_length=1)
    original_id: str | None = Field(default=None, min_length=1)
    prompt: str = Field(..., min_length=1)
    limit: QuestionLimit = Field(default_factory=QuestionLimit)
    provenance: str | None = None


class RequirementsArtifact(BaseModel):
    funder: str | None = None
    deadline: str | None = None
    eligibility: list[str] = Field(default_factory=list)
    questions: list[RequirementQuestion] = Field(default_factory=list)
    required_attachments: list[str] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list)
    disallowed_costs: list[str] = Field(default_factory=list)


def _coerce_text(item: object) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "label", "name", "criterion", "title"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    if isinstance(item, (int, float)):
        return str(item)
    return ""


def _dedupe(items: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = " ".join(_coerce_text(item).split()).strip(" -\t")
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(value)
    return result


def _normalize_text_key(value: str) -> str:
    return " ".join(value.lower().split())


def _normalize_question_key(value: str) -> str:
    stripped = re.sub(r"\([^)]*\)", " ", value.lower())
    stripped = re.sub(r"[^a-z0-9\s]", " ", stripped)
    return " ".join(stripped.split())


def _normalize_question_base_key(value: str) -> str:
    base = value.split(":", maxsplit=1)[0]
    return _normalize_question_key(base)


def _question_prompt_rank(value: str) -> int:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return 0
    rank = len(normalized)
    if ":" in normalized:
        rank += 50
    if _extract_question_limit(normalized).type != "none":
        rank += 20
    return rank


def _normalize_attachment_key(value: str) -> str:
    lowered = value.lower().strip(" -\t")
    lowered = re.sub(r"^include\s+", "", lowered)
    lowered = re.sub(r"^attachment\s+[a-z0-9]+\s*[:\-]\s*", "", lowered)
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return " ".join(lowered.split())


def _normalize_free_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", value.lower())
    return " ".join(normalized.split())


def _normalize_original_requirement_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    return normalized


def _normalize_internal_question_id(raw_id: object, fallback_index: int) -> str:
    candidate = str(raw_id or "").strip()
    if not candidate:
        return f"Q{fallback_index}"

    canonical_match = re.fullmatch(r"[Qq]\s*[_\-]?(\d+)", candidate)
    if canonical_match:
        return f"Q{int(canonical_match.group(1))}"

    number_match = re.fullmatch(r"(?i)(?:question\s*)?(\d+)", candidate)
    if number_match:
        return f"Q{int(number_match.group(1))}"

    return f"Q{fallback_index}"


def _coerce_question_identifiers(
    *,
    raw_internal_id: object,
    raw_original_id: object,
    fallback_index: int,
) -> tuple[str, str | None]:
    internal_id = _normalize_internal_question_id(raw_internal_id, fallback_index)
    original_id = _normalize_original_requirement_id(raw_original_id)
    raw_internal = _normalize_original_requirement_id(raw_internal_id)
    if original_id is None and raw_internal and raw_internal != internal_id:
        original_id = raw_internal
    return internal_id, original_id


def _is_question_or_heading_line(value: str) -> bool:
    lowered = value.lower().strip()
    if _section_from_heading(value) is not None:
        return True
    if lowered.startswith(("funding opportunity", "program overview", "required narrative questions", "submission requirements")):
        return True
    if re.match(r"^(?:q(?:uestion)?\s*)?\d+[\).:\-]\s+", lowered):
        return True
    return False


def _looks_like_rubric_item(value: str) -> bool:
    lowered = value.lower()
    if re.search(r"\(\s*\d+\s*points?\s*\)", lowered):
        return True
    if lowered.strip().endswith("points"):
        return True
    return False


def _is_points_only_fragment(value: str) -> bool:
    lowered = value.lower().strip()
    return re.fullmatch(r"\(?\s*\d+\s*points?\s*\)?", lowered) is not None


def _looks_like_disallowed_cost_item(value: str) -> bool:
    normalized = _normalize_free_text(value)
    if not normalized:
        return False
    if _is_question_or_heading_line(value):
        return False
    if _is_points_only_fragment(value) or _looks_like_rubric_item(value):
        return False
    if normalized in {"restrictions", "disallowed costs", "ineligible costs"}:
        return False
    if len(normalized) < 8:
        return False

    negative_patterns = (
        "no ",
        "not allowed",
        "disallowed",
        "ineligible",
        "unallowable",
        "without prior approval",
        "capped at",
        "cap at",
        "above ",
        "maximum ",
    )
    cost_topics = (
        "cost",
        "costs",
        "expense",
        "expenses",
        "equipment",
        "real estate",
        "alcohol",
        "entertainment",
        "lobbying",
        "political",
        "indirect",
        "overhead",
    )

    has_negative = any(pattern in normalized for pattern in negative_patterns)
    has_topic = any(topic in normalized for topic in cost_topics)
    if has_negative and has_topic:
        return True
    if normalized.startswith("purchase of real estate"):
        return True
    if normalized.startswith("political campaign activity"):
        return True
    if normalized.startswith("expenses unrelated to direct program delivery"):
        return True
    return False


def _clean_disallowed_costs(items: list[str]) -> list[str]:
    filtered = [item for item in items if _looks_like_disallowed_cost_item(item)]
    if not filtered:
        return []

    normalized_items = [_normalize_free_text(item) for item in filtered]
    deduped: list[str] = []
    seen: set[str] = set()
    for item, normalized in zip(filtered, normalized_items, strict=False):
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item)
    return _drop_prefix_fragments(deduped, min_prefix_len=10)


def _drop_prefix_fragments(items: list[str], min_prefix_len: int = 12) -> list[str]:
    normalized = [_normalize_free_text(item) for item in items]
    keep = [True] * len(items)
    for index, key in enumerate(normalized):
        if not key:
            keep[index] = False
            continue
        if len(key) < min_prefix_len:
            continue
        for other_index, other_key in enumerate(normalized):
            if index == other_index:
                continue
            if other_key.startswith(key) and other_key != key:
                keep[index] = False
                break
    return [item for item, should_keep in zip(items, keep, strict=False) if should_keep]


def _is_section_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(":"):
        return False
    if stripped.startswith(("-", "*", "•")):
        return False
    if re.match(r"^\d+[\).:]", stripped):
        return False
    return True


def _section_from_heading(line: str) -> str | None:
    normalized = _normalize_free_text(line.removesuffix(":").strip())
    if not normalized:
        return None
    if normalized.startswith("eligibility"):
        return "eligibility"
    if normalized.startswith("required attachments") or normalized in {"required attachment", "attachments", "attachment"}:
        return "required_attachments"
    if "rubric" in normalized or "scoring criteria" in normalized:
        return "rubric"
    if normalized.startswith("disallowed costs") or normalized.startswith("disallowed cost"):
        return "disallowed_costs"
    if normalized.startswith("ineligible costs") or normalized.startswith("ineligible cost"):
        return "disallowed_costs"
    return None


def _drop_heading_only(items: object, aliases: tuple[str, ...]) -> list[str]:
    values = items if isinstance(items, list) else []
    cleaned = _dedupe(values)
    alias_keys = {_normalize_free_text(alias) for alias in aliases}
    result: list[str] = []
    for item in cleaned:
        key = _normalize_free_text(item.removesuffix(":").strip())
        if key in alias_keys:
            continue
        result.append(item)
    return result


def _clean_requirements_lists(payload: dict[str, object]) -> dict[str, object]:
    cleaned = dict(payload)
    eligibility_items = _drop_heading_only(cleaned.get("eligibility"), ("eligibility",))
    attachment_items = _drop_heading_only(
        cleaned.get("required_attachments"),
        ("required attachments", "required attachment", "attachments", "attachment"),
    )
    rubric_items = _drop_heading_only(
        cleaned.get("rubric"),
        ("rubric", "rubric and scoring criteria", "scoring criteria"),
    )
    disallowed_items = _drop_heading_only(
        cleaned.get("disallowed_costs"),
        ("disallowed costs", "disallowed cost", "ineligible costs", "ineligible cost"),
    )

    rubric_promoted = [item for item in disallowed_items if _looks_like_rubric_item(item)]
    if rubric_promoted:
        rubric_items = _dedupe([*rubric_items, *rubric_promoted])
        disallowed_items = [item for item in disallowed_items if not _looks_like_rubric_item(item)]

    rubric_items = [item for item in rubric_items if not _is_points_only_fragment(item)]

    cleaned["eligibility"] = _drop_prefix_fragments(eligibility_items)
    cleaned["required_attachments"] = _drop_prefix_fragments(attachment_items)
    cleaned["rubric"] = _drop_prefix_fragments(rubric_items)
    cleaned["disallowed_costs"] = _clean_disallowed_costs(disallowed_items)
    return cleaned


def _extract_question_limit(text: str) -> QuestionLimit:
    words_match = re.search(r"(\d{2,5})\s*words?\b", text, flags=re.IGNORECASE)
    if words_match:
        return QuestionLimit(type="words", value=int(words_match.group(1)))

    chars_match = re.search(
        r"(\d{2,6})\s*(?:chars?|characters?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if chars_match:
        return QuestionLimit(type="chars", value=int(chars_match.group(1)))

    return QuestionLimit(type="none")


_QUESTION_PASS_PRIORITY: dict[str, int] = {
    "explicit_tag": 4,
    "structured_outline": 3,
    "inline_indicator": 2,
    "fallback_question": 1,
}

_QUESTION_VERB_PREFIXES = (
    "describe",
    "explain",
    "provide",
    "include",
    "outline",
    "identify",
    "summarize",
    "detail",
    "demonstrate",
    "list",
    "submit",
    "attach",
    "address",
)

_HEADING_NOISE_PREFIXES = (
    "funding opportunity",
    "program overview",
    "required narrative questions",
    "submission requirements",
    "evaluation criteria",
    "rubric",
    "eligibility",
    "disallowed costs",
    "required attachments",
)


def _clean_candidate_prompt(text: str) -> str:
    cleaned = " ".join(text.strip(" -*\t").split())
    if not cleaned:
        return ""

    cleaned = re.sub(r"^(?:q(?:uestion)?\s*\d+\s*[:\).-]?\s*)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(?:\d+(?:\.\d+){0,4}|[A-Z]\.\d+(?:\.\d+){0,4}|[IVXLCDM]{1,6})\s*(?:[)\.:\-])?\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"^(?:req(?:uirement)?)[\s\-_]*[A-Za-z]?\d+(?:\.\d+)*\s*[:\-]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned.split()).strip(" -\t")


def _looks_like_requirement_prompt(text: str) -> bool:
    cleaned = _clean_candidate_prompt(text)
    if not cleaned or len(cleaned) < 10:
        return False
    if cleaned.endswith(":"):
        return False

    lowered = cleaned.lower()
    if any(lowered.startswith(prefix) for prefix in _HEADING_NOISE_PREFIXES):
        return False

    words = re.findall(r"[a-zA-Z]{2,}", cleaned)
    if len(words) < 3:
        return False

    if _extract_question_limit(cleaned).type != "none":
        return True

    if cleaned.endswith("?"):
        return True

    if any(lowered.startswith(prefix) for prefix in _QUESTION_VERB_PREFIXES):
        return True

    if re.search(
        r"\b(must|shall|required|required to|is required to|are required to|please)\b",
        lowered,
    ):
        return True

    return False


def _build_question_candidate(
    *,
    raw_prompt: str,
    provenance: str,
    line_index: int,
    original_id: str | None = None,
) -> dict[str, object] | None:
    prompt = _clean_candidate_prompt(raw_prompt)
    if not _looks_like_requirement_prompt(prompt):
        return None
    candidate: dict[str, object] = {
        "prompt": prompt,
        "limit": _extract_question_limit(prompt).model_dump(),
        "provenance": provenance,
        "line_index": line_index,
    }
    normalized_original_id = _normalize_original_requirement_id(original_id)
    if normalized_original_id is not None:
        candidate["original_id"] = normalized_original_id
    return candidate


def _extract_explicit_tag_candidates(lines: list[str]) -> list[dict[str, object]]:
    pattern = re.compile(
        r"^((?:req(?:uirement)?)[\s\-_]*[A-Za-z]?\d+(?:\.\d+)*)\s*[:\-]\s+(.+)$",
        flags=re.IGNORECASE,
    )
    results: list[dict[str, object]] = []
    for line_index, line in enumerate(lines):
        match = pattern.match(line.strip(" -*\t"))
        if not match:
            continue
        candidate = _build_question_candidate(
            raw_prompt=match.group(2),
            provenance="explicit_tag",
            line_index=line_index,
            original_id=match.group(1),
        )
        if candidate is not None:
            results.append(candidate)
    return results


def _extract_structured_outline_candidates(lines: list[str]) -> list[dict[str, object]]:
    pattern = re.compile(
        r"^((?:\d+(?:\.\d+){1,4}|[A-Z]\.\d+(?:\.\d+){0,4}|[IVXLCDM]{1,6}))\s*(?:[)\.:\-])?\s+(.+)$",
        flags=re.IGNORECASE,
    )
    results: list[dict[str, object]] = []
    for line_index, line in enumerate(lines):
        match = pattern.match(line.strip(" -*\t"))
        if not match:
            continue

        marker = match.group(1)
        marker_upper = marker.upper()
        is_numeric_outline = "." in marker and marker[0].isdigit()
        is_letter_outline = bool(re.match(r"^[A-Z]\.\d+", marker_upper))
        is_roman_outline = bool(re.fullmatch(r"[IVXLCDM]{1,6}", marker_upper))
        if not (is_numeric_outline or is_letter_outline or is_roman_outline):
            continue

        candidate = _build_question_candidate(
            raw_prompt=match.group(2),
            provenance="structured_outline",
            line_index=line_index,
            original_id=marker,
        )
        if candidate is not None:
            results.append(candidate)
    return results


def _extract_inline_requirement_candidates(lines: list[str]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for line_index, line in enumerate(lines):
        stripped = line.strip(" -*\t")
        if not stripped:
            continue

        matched_prompt: str | None = None

        subject_pattern = re.search(
            r"\b(?:applicants?|organizations?|proposals?|responses?|grantees?)\b.+\b(?:must|shall|required)\b[:\s\-]*(.+)$",
            stripped,
            flags=re.IGNORECASE,
        )
        if subject_pattern:
            matched_prompt = subject_pattern.group(1)

        if matched_prompt is None:
            requirement_pattern = re.search(
                r"\b(?:must|shall|required to|is required to|are required to)\b[:\s\-]*(.+)$",
                stripped,
                flags=re.IGNORECASE,
            )
            if requirement_pattern:
                matched_prompt = requirement_pattern.group(1)

        if matched_prompt is None and ":" in stripped:
            heading, _, tail = stripped.partition(":")
            heading_lower = heading.lower()
            if any(
                token in heading_lower
                for token in ("requirement", "narrative", "prompt", "response")
            ):
                matched_prompt = tail

        if matched_prompt is None and _extract_question_limit(stripped).type != "none":
            matched_prompt = stripped

        if matched_prompt is None:
            continue

        candidate = _build_question_candidate(
            raw_prompt=matched_prompt,
            provenance="inline_indicator",
            line_index=line_index,
        )
        if candidate is not None:
            results.append(candidate)
    return results


def _extract_fallback_question_candidates(lines: list[str]) -> list[dict[str, object]]:
    question_pattern = re.compile(
        r"^(?:q(?:uestion)?\s*(\d+)\s*[:\).-]?\s*|(\d+)[\).:]\s+)(.+)$",
        flags=re.IGNORECASE,
    )
    results: list[dict[str, object]] = []
    for line_index, line in enumerate(lines):
        stripped = line.strip(" -*\t")
        if not stripped:
            continue

        prompt_text: str | None = None
        original_id: str | None = None
        question_match = question_pattern.match(stripped)
        if question_match:
            prompt_text = question_match.group(3)
            question_number = question_match.group(1) or question_match.group(2)
            if question_number:
                original_id = f"Question {question_number}"
        elif stripped.endswith("?") and _looks_like_requirement_prompt(stripped):
            prompt_text = stripped

        if prompt_text is None:
            continue

        candidate = _build_question_candidate(
            raw_prompt=prompt_text,
            provenance="fallback_question",
            line_index=line_index,
            original_id=original_id,
        )
        if candidate is not None:
            results.append(candidate)
    return results


def _candidate_score(candidate: dict[str, object]) -> int:
    prompt = str(candidate.get("prompt") or "")
    provenance = str(candidate.get("provenance") or "")
    priority = _QUESTION_PASS_PRIORITY.get(provenance, 0)
    return (priority * 1000) + _question_prompt_rank(prompt)


def _extract_questions(lines: list[str]) -> list[dict[str, object]]:
    ordered_candidates: list[dict[str, object]] = []
    ordered_candidates.extend(_extract_explicit_tag_candidates(lines))
    ordered_candidates.extend(_extract_structured_outline_candidates(lines))
    ordered_candidates.extend(_extract_inline_requirement_candidates(lines))
    ordered_candidates.extend(_extract_fallback_question_candidates(lines))

    selected: list[dict[str, object]] = []
    seen_prompt_keys: set[str] = set()
    base_question_index: dict[str, int] = {}
    for candidate in ordered_candidates:
        prompt = str(candidate.get("prompt", "")).strip()
        if not prompt:
            continue
        prompt_key = _normalize_question_key(prompt)
        if prompt_key in seen_prompt_keys:
            continue

        base_key = _normalize_question_base_key(prompt)
        score = _candidate_score(candidate)
        if base_key and base_key in base_question_index:
            existing_index = base_question_index[base_key]
            existing = selected[existing_index]
            existing_prompt_key = _normalize_question_key(str(existing.get("prompt", "")))
            existing_score = _candidate_score(existing)
            if score > existing_score:
                if existing_prompt_key:
                    seen_prompt_keys.discard(existing_prompt_key)
                selected[existing_index] = candidate
                seen_prompt_keys.add(prompt_key)
            continue

        selected.append(candidate)
        seen_prompt_keys.add(prompt_key)
        if base_key:
            base_question_index[base_key] = len(selected) - 1

    questions: list[dict[str, object]] = []
    for index, candidate in enumerate(selected, start=1):
        internal_id, original_id = _coerce_question_identifiers(
            raw_internal_id=f"Q{index}",
            raw_original_id=candidate.get("original_id"),
            fallback_index=index,
        )
        question = {
            "id": internal_id,
            "internal_id": internal_id,
            "prompt": str(candidate.get("prompt", "")),
            "limit": candidate.get("limit", QuestionLimit(type="none").model_dump()),
        }
        if original_id is not None:
            question["original_id"] = original_id
        provenance = str(candidate.get("provenance") or "").strip()
        if provenance:
            question["provenance"] = provenance
        questions.append(question)
    return questions


def extract_requirements_payload(chunks: list[dict[str, object]]) -> dict[str, object]:
    lines: list[str] = []
    for chunk in chunks:
        chunk_text = str(chunk["text"])
        lines.extend([line.strip() for line in chunk_text.splitlines() if line.strip()])

    funder: str | None = None
    deadline: str | None = None
    eligibility: list[str] = []
    required_attachments: list[str] = []
    rubric: list[str] = []
    disallowed_costs: list[str] = []
    active_section: str | None = None

    for line in lines:
        if _is_section_heading(line):
            active_section = _section_from_heading(line)
            if active_section is not None:
                continue

        if funder is None:
            funder_match = re.search(
                r"(?:funder|grantor|funding organization)\s*[:\-]\s*(.+)",
                line,
                flags=re.IGNORECASE,
            )
            if funder_match:
                funder = funder_match.group(1).strip()
            else:
                opportunity_match = re.search(
                    r"(?:funding opportunity|opportunity)\s*[:\-]\s*(.+)",
                    line,
                    flags=re.IGNORECASE,
                )
                if opportunity_match:
                    opportunity_text = opportunity_match.group(1).strip()
                    local_authority_match = re.search(
                        r"((?:city|county)\s+of\s+.+)",
                        opportunity_text,
                        flags=re.IGNORECASE,
                    )
                    if local_authority_match:
                        candidate = local_authority_match.group(1).strip()
                        candidate = re.split(
                            r"\b(?:grant|fund|programme|program|initiative|competition|call|youth|workforce|innovation)\b",
                            candidate,
                            maxsplit=1,
                            flags=re.IGNORECASE,
                        )[0].strip()
                        funder = candidate or opportunity_text
                    else:
                        funder = opportunity_text

        if deadline is None:
            deadline_match = re.search(
                r"(?:deadline|due date|submission date)\s*[:\-]\s*(.+)",
                line,
                flags=re.IGNORECASE,
            )
            if deadline_match:
                deadline = deadline_match.group(1).strip()

        if active_section == "eligibility":
            eligibility.append(line)
            continue
        if active_section == "required_attachments":
            required_attachments.append(line)
            continue
        if active_section == "rubric":
            rubric.append(line)
            continue
        if active_section == "disallowed_costs":
            disallowed_costs.append(line)
            continue

        lowered = line.lower()
        if "eligib" in lowered:
            eligibility.append(line)
        if "attachment" in lowered or "appendix" in lowered:
            required_attachments.append(line)
        normalized = lowered.lstrip("-* \t")
        if normalized.startswith("include ") and (
            "timeline" in normalized or "letter" in normalized or "budget" in normalized
        ):
            required_attachments.append(line)
        if "rubric" in lowered or "scoring" in lowered or "criteria" in lowered:
            rubric.append(line)
        if "disallowed" in lowered or "ineligible cost" in lowered or "unallowable" in lowered:
            disallowed_costs.append(line)
        if "not allowed" in lowered and "cost" in lowered:
            disallowed_costs.append(line)

    payload = {
        "funder": funder,
        "deadline": deadline,
        "eligibility": _dedupe(eligibility),
        "questions": _extract_questions(lines),
        "required_attachments": _dedupe(required_attachments),
        "rubric": _dedupe(rubric),
        "disallowed_costs": _dedupe(disallowed_costs),
    }
    return _clean_requirements_lists(payload)


def merge_requirements_payload(
    deterministic_payload: dict[str, object], nova_payload: dict[str, object]
) -> dict[str, object]:
    left = repair_requirements_payload(deterministic_payload)
    right = repair_requirements_payload(nova_payload)

    merged_questions: list[dict[str, object]] = []
    seen_prompt_keys: set[str] = set()
    question_index_by_prompt_key: dict[str, int] = {}
    base_question_index: dict[str, int] = {}
    for source in (left, right):
        for question in source.get("questions", []):
            if not isinstance(question, dict):
                continue
            prompt = str(question.get("prompt", "")).strip()
            if not prompt:
                continue
            prompt_key = _normalize_question_key(prompt)
            if prompt_key in seen_prompt_keys:
                existing_index = question_index_by_prompt_key.get(prompt_key)
                if existing_index is not None:
                    incoming_original_id = _normalize_original_requirement_id(question.get("original_id"))
                    existing_original_id = _normalize_original_requirement_id(
                        merged_questions[existing_index].get("original_id")
                    )
                    if incoming_original_id is not None and existing_original_id is None:
                        merged_questions[existing_index]["original_id"] = incoming_original_id
                continue
            question_id, original_id = _coerce_question_identifiers(
                raw_internal_id=question.get("internal_id") or question.get("id"),
                raw_original_id=question.get("original_id"),
                fallback_index=len(merged_questions) + 1,
            )
            limit = question.get("limit", {"type": "none", "value": None})
            if not isinstance(limit, dict):
                limit = {"type": "none", "value": None}
            provenance = question.get("provenance")
            provenance_value: str | None = None
            if isinstance(provenance, str):
                cleaned_provenance = provenance.strip()
                if cleaned_provenance:
                    provenance_value = cleaned_provenance

            candidate = {"id": question_id, "internal_id": question_id, "prompt": prompt, "limit": limit}
            if original_id is not None:
                candidate["original_id"] = original_id
            if provenance_value is not None:
                candidate["provenance"] = provenance_value

            base_key = _normalize_question_base_key(prompt)
            if base_key and base_key in base_question_index:
                existing_index = base_question_index[base_key]
                existing_prompt = str(merged_questions[existing_index].get("prompt", ""))
                if _question_prompt_rank(prompt) > _question_prompt_rank(existing_prompt):
                    existing_internal_id = str(
                        merged_questions[existing_index].get("internal_id")
                        or merged_questions[existing_index].get("id")
                        or ""
                    ).strip()
                    if existing_internal_id:
                        candidate["id"] = existing_internal_id
                        candidate["internal_id"] = existing_internal_id
                    if "original_id" not in candidate:
                        existing_original_id = _normalize_original_requirement_id(
                            merged_questions[existing_index].get("original_id")
                        )
                        if existing_original_id is not None:
                            candidate["original_id"] = existing_original_id
                    existing_prompt_key = _normalize_question_key(existing_prompt)
                    if existing_prompt_key:
                        question_index_by_prompt_key.pop(existing_prompt_key, None)
                    merged_questions[existing_index] = candidate
                    seen_prompt_keys.add(prompt_key)
                    question_index_by_prompt_key[prompt_key] = existing_index
                continue

            merged_questions.append(candidate)
            seen_prompt_keys.add(prompt_key)
            question_index_by_prompt_key[prompt_key] = len(merged_questions) - 1
            if base_key:
                base_question_index[base_key] = len(merged_questions) - 1

    attachments: list[str] = [*left.get("required_attachments", []), *right.get("required_attachments", [])]
    merged_attachments: list[str] = []
    seen_attachment_keys: set[str] = set()
    for item in attachments:
        key = _normalize_attachment_key(str(item))
        if not key or key in seen_attachment_keys:
            continue
        seen_attachment_keys.add(key)
        merged_attachments.append(str(item))

    merged = {
        "funder": left.get("funder") or right.get("funder"),
        "deadline": left.get("deadline") or right.get("deadline"),
        "eligibility": _dedupe([*left.get("eligibility", []), *right.get("eligibility", [])]),
        "questions": merged_questions,
        "required_attachments": _dedupe(merged_attachments),
        "rubric": _dedupe([*left.get("rubric", []), *right.get("rubric", [])]),
        "disallowed_costs": _dedupe([*left.get("disallowed_costs", []), *right.get("disallowed_costs", [])]),
    }
    return _clean_requirements_lists(merged)


def repair_requirements_payload(payload: dict[str, object]) -> dict[str, object]:
    repaired = dict(payload)
    for field in ("eligibility", "questions", "required_attachments", "rubric", "disallowed_costs"):
        value = repaired.get(field)
        if not isinstance(value, list):
            repaired[field] = []

    repaired_questions: list[dict[str, object]] = []
    for index, question in enumerate(repaired["questions"], start=1):
        if isinstance(question, str):
            internal_id, original_id = _coerce_question_identifiers(
                raw_internal_id=f"Q{index}",
                raw_original_id=None,
                fallback_index=index,
            )
            repaired_questions.append(
                {
                    "id": internal_id,
                    "internal_id": internal_id,
                    "prompt": question,
                    "limit": QuestionLimit(type="none").model_dump(),
                    **({"original_id": original_id} if original_id is not None else {}),
                }
            )
            continue
        if not isinstance(question, dict):
            continue
        prompt = str(question.get("prompt", "")).strip()
        if not prompt:
            continue
        internal_id, original_id = _coerce_question_identifiers(
            raw_internal_id=question.get("internal_id") or question.get("id"),
            raw_original_id=question.get("original_id"),
            fallback_index=index,
        )
        limit = question.get("limit", {"type": "none"})
        if isinstance(limit, str):
            limit = {"type": limit, "value": None}
        if not isinstance(limit, dict):
            limit = {"type": "none", "value": None}
        provenance = question.get("provenance")
        normalized_provenance: str | None = None
        if isinstance(provenance, str):
            stripped_provenance = provenance.strip()
            if stripped_provenance:
                normalized_provenance = stripped_provenance
        repaired_questions.append(
            {
                "id": internal_id,
                "internal_id": internal_id,
                "prompt": prompt,
                "limit": limit,
                **({"original_id": original_id} if original_id is not None else {}),
                **({"provenance": normalized_provenance} if normalized_provenance is not None else {}),
            }
        )

    repaired["questions"] = repaired_questions
    if repaired.get("funder") is not None:
        repaired["funder"] = str(repaired["funder"]).strip() or None
    if repaired.get("deadline") is not None:
        repaired["deadline"] = str(repaired["deadline"]).strip() or None
    return _clean_requirements_lists(repaired)


def validate_with_repair(payload: dict[str, object]) -> tuple[RequirementsArtifact | None, bool, list[str]]:
    try:
        return RequirementsArtifact.model_validate(payload), False, []
    except ValidationError as err:
        initial_errors = [issue["msg"] for issue in err.errors()]

    repaired_payload = repair_requirements_payload(payload)
    try:
        return RequirementsArtifact.model_validate(repaired_payload), True, initial_errors
    except ValidationError as repaired_err:
        final_errors = [issue["msg"] for issue in repaired_err.errors()]
        return None, True, initial_errors + final_errors
