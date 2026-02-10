from __future__ import annotations

import re

BOILERPLATE_PHRASES = [
    "structured to address",
    "evidence-based practices",
    "comprehensive service delivery",
    "robust understanding",
    "ensures a seamless",
    "aligned with funder's guidelines",
]

NARRATIVE_REQUIREMENT_SECTION_MAP: dict[str, str] = {
    "Q1": "Need Statement",
    "Q2": "Program Design",
    "Q3": "Outcomes and Evaluation",
}


def normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def normalize_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value))


def parse_word_limit(prompt: str) -> int | None:
    prompt_match = re.search(r"\((\d+)\s*words?\s*max\)", prompt, flags=re.IGNORECASE)
    if prompt_match:
        return int(prompt_match.group(1))
    inline_match = re.search(r"\b(\d+)\s*words?\s*max\b", prompt, flags=re.IGNORECASE)
    if inline_match:
        return int(inline_match.group(1))
    return None


def derive_section_title_from_prompt(prompt: str) -> str:
    head = prompt.split(":", 1)[0].strip()
    head = re.sub(r"\s*\([^)]*\)\s*$", "", head).strip()
    return head or prompt.strip()


def expected_section_for_requirement(requirement_id: str) -> str | None:
    return NARRATIVE_REQUIREMENT_SECTION_MAP.get(requirement_id.upper().strip())


def is_boilerplate_paragraph(text: str, citation_count: int) -> bool:
    lowered = text.lower()
    conditions = 0

    if any(phrase in lowered for phrase in BOILERPLATE_PHRASES):
        conditions += 1

    has_numbers = bool(re.search(r"\d", text))
    has_named_entities = bool(re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text))
    if not has_numbers and not has_named_entities and citation_count == 0:
        conditions += 1

    generic_term_hits = len(re.findall(r"\b(program|services?|community|approach|participants?|delivery)\b", lowered))
    if generic_term_hits >= 3 and citation_count == 0:
        conditions += 1

    return conditions >= 2

