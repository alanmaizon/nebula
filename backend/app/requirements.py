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


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = " ".join(item.split()).strip(" -\t")
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


def _normalize_attachment_key(value: str) -> str:
    lowered = value.lower().strip(" -\t")
    lowered = re.sub(r"^include\s+", "", lowered)
    lowered = re.sub(r"^attachment\s+[a-z0-9]+\s*[:\-]\s*", "", lowered)
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return " ".join(lowered.split())


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

    for line in lines:
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
    return payload


def merge_requirements_payload(
    deterministic_payload: dict[str, object], nova_payload: dict[str, object]
) -> dict[str, object]:
    left = repair_requirements_payload(deterministic_payload)
    right = repair_requirements_payload(nova_payload)

    merged_questions: list[dict[str, object]] = []
    seen_prompts: set[str] = set()
    for source in (left, right):
        for question in source.get("questions", []):
            if not isinstance(question, dict):
                continue
            prompt = str(question.get("prompt", "")).strip()
            if not prompt:
                continue
            key = _normalize_question_key(prompt)
            if key in seen_prompts:
                continue
            seen_prompts.add(key)
            question_id = str(question.get("id", "")).strip() or f"Q{len(merged_questions) + 1}"
            limit = question.get("limit", {"type": "none", "value": None})
            if not isinstance(limit, dict):
                limit = {"type": "none", "value": None}
            merged_questions.append({"id": question_id, "prompt": prompt, "limit": limit})

    attachments: list[str] = [*left.get("required_attachments", []), *right.get("required_attachments", [])]
    merged_attachments: list[str] = []
    seen_attachment_keys: set[str] = set()
    for item in attachments:
        key = _normalize_attachment_key(str(item))
        if not key or key in seen_attachment_keys:
            continue
        seen_attachment_keys.add(key)
        merged_attachments.append(str(item))

    return {
        "funder": left.get("funder") or right.get("funder"),
        "deadline": left.get("deadline") or right.get("deadline"),
        "eligibility": _dedupe([*left.get("eligibility", []), *right.get("eligibility", [])]),
        "questions": merged_questions,
        "required_attachments": _dedupe(merged_attachments),
        "rubric": _dedupe([*left.get("rubric", []), *right.get("rubric", [])]),
        "disallowed_costs": _dedupe([*left.get("disallowed_costs", []), *right.get("disallowed_costs", [])]),
    }


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
    return repaired


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
