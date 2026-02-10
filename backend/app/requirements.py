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
    prompt: str = Field(..., min_length=1)
    limit: QuestionLimit = Field(default_factory=QuestionLimit)


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


def _extract_questions(lines: list[str]) -> list[dict[str, object]]:
    pattern = re.compile(
        r"^(?:q(?:uestion)?\s*(\d+)\s*[:\).-]?\s*|(\d+)[\).:]\s+)(.+)$",
        flags=re.IGNORECASE,
    )
    questions: list[dict[str, object]] = []
    for line in lines:
        match = pattern.match(line.strip(" -*\t"))
        if not match:
            continue
        number = match.group(1) or match.group(2) or str(len(questions) + 1)
        prompt = match.group(3).strip()
        questions.append(
            {
                "id": f"Q{number}",
                "prompt": prompt,
                "limit": _extract_question_limit(prompt).model_dump(),
            }
        )
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
                continue
            question_id = str(question.get("id", "")).strip() or f"Q{len(merged_questions) + 1}"
            limit = question.get("limit", {"type": "none", "value": None})
            if not isinstance(limit, dict):
                limit = {"type": "none", "value": None}
            candidate = {"id": question_id, "prompt": prompt, "limit": limit}

            base_key = _normalize_question_base_key(prompt)
            if base_key and base_key in base_question_index:
                existing_index = base_question_index[base_key]
                existing_prompt = str(merged_questions[existing_index].get("prompt", ""))
                if _question_prompt_rank(prompt) > _question_prompt_rank(existing_prompt):
                    merged_questions[existing_index] = candidate
                    seen_prompt_keys.add(prompt_key)
                continue

            merged_questions.append(candidate)
            seen_prompt_keys.add(prompt_key)
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
            repaired_questions.append(
                {
                    "id": f"Q{index}",
                    "prompt": question,
                    "limit": QuestionLimit(type="none").model_dump(),
                }
            )
            continue
        if not isinstance(question, dict):
            continue
        prompt = str(question.get("prompt", "")).strip()
        if not prompt:
            continue
        identifier = str(question.get("id", "")).strip() or f"Q{index}"
        limit = question.get("limit", {"type": "none"})
        if isinstance(limit, str):
            limit = {"type": limit, "value": None}
        if not isinstance(limit, dict):
            limit = {"type": "none", "value": None}
        repaired_questions.append(
            {
                "id": identifier,
                "prompt": prompt,
                "limit": limit,
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
