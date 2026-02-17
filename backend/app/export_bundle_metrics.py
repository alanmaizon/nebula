from __future__ import annotations

import re

from .export_bundle_common import (
    _coerce_positive_int,
    _dedupe_preserve_order,
    _normalize_key,
)


def _extract_constraints(requirements: dict[str, object] | None) -> tuple[list[str], list[str]]:
    known: list[str] = []
    unknown: list[str] = []

    if requirements is None:
        unknown.append("requirements unavailable")
        return known, unknown

    deadline = str(requirements.get("deadline") or "").strip()
    if deadline:
        known.append(f"deadline: {deadline}")
    else:
        unknown.append("deadline constraint missing")

    questions = requirements.get("questions")
    if not isinstance(questions, list) or len(questions) == 0:
        unknown.append("question constraints missing")
        return known, unknown

    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or f"Q{index}")
        limit = question.get("limit")
        if not isinstance(limit, dict):
            unknown.append(f"{question_id}: limit not specified")
            continue
        limit_type = str(limit.get("type") or "none").strip().lower()
        limit_value = _coerce_positive_int(limit.get("value"))
        if limit_type in {"words", "chars"} and limit_value is not None:
            known.append(f"{question_id}: {limit_value} {limit_type}")
        elif limit_type == "none":
            unknown.append(f"{question_id}: limit not specified")
        else:
            unknown.append(f"{question_id}: constraint_unknown")

    return known, unknown


def _compute_completion(
    coverage_counts: dict[str, int],
    *,
    unsupported_claims_count: int = 0,
    citation_mismatch_count: int = 0,
    empty_required_sections_count: int = 0,
) -> float | None:
    total = coverage_counts.get("met", 0) + coverage_counts.get("partial", 0) + coverage_counts.get("missing", 0)
    if total <= 0:
        return None
    score = coverage_counts.get("met", 0) + 0.5 * coverage_counts.get("partial", 0)
    base = (score / total) * 100
    penalty = _uncertainty_penalty_factor(
        total=total,
        unsupported_claims_count=unsupported_claims_count,
        citation_mismatch_count=citation_mismatch_count,
        empty_required_sections_count=empty_required_sections_count,
    )
    return base * (1.0 - penalty)


def _coverage_counts(coverage_items: list[dict[str, object]]) -> dict[str, int]:
    counts = {"met": 0, "partial": 0, "missing": 0}
    for item in coverage_items:
        status = str(item.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    return counts


def _uncertainty_penalty_factor(
    *,
    total: int,
    unsupported_claims_count: int,
    citation_mismatch_count: int,
    empty_required_sections_count: int,
) -> float:
    denominator = max(total, 1)
    weighted = (
        unsupported_claims_count * 1.0
        + citation_mismatch_count * 1.25
        + empty_required_sections_count * 1.5
    )
    return min(0.6, (weighted / denominator) * 0.12)


def _resolve_section_order(
    *,
    requirements: dict[str, object] | None,
    available_sections: list[str],
    requested_sections: list[str],
) -> list[str]:
    if requested_sections:
        return _dedupe_preserve_order(requested_sections)

    if not available_sections:
        return []

    remaining = {key: key for key in available_sections}
    ordered: list[str] = []

    if requirements:
        questions = requirements.get("questions")
        if isinstance(questions, list):
            normalized_lookup = {_normalize_key(name): name for name in available_sections}
            for question in questions:
                if not isinstance(question, dict):
                    continue
                prompt = str(question.get("prompt") or "").strip()
                if not prompt:
                    continue
                for candidate in _section_candidates_from_prompt(prompt):
                    section = normalized_lookup.get(_normalize_key(candidate))
                    if section and section in remaining:
                        ordered.append(section)
                        remaining.pop(section, None)
                        break

    ordered.extend(sorted(remaining.keys(), key=lambda value: value.lower()))
    return ordered


def _section_candidates_from_prompt(prompt: str) -> list[str]:
    trimmed = prompt.strip()
    first_clause = trimmed.split(":")[0].strip() if ":" in trimmed else trimmed
    without_parens = re.sub(r"\s*\([^)]*\)\s*$", "", first_clause).strip()
    candidates = [trimmed, first_clause, without_parens]
    return [candidate for candidate in candidates if candidate]
