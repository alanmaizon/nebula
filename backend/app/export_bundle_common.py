from __future__ import annotations

from datetime import datetime, timezone
import re


_NARRATIVE_REQUIREMENT_SECTION_MAP = {
    "Q1": "Need Statement",
    "Q2": "Program Design",
    "Q3": "Outcomes and Evaluation",
}
_COVERAGE_STATUS_ORDER = {"missing": 0, "partial": 1, "met": 2}
_INLINE_CITATION_HINT_PATTERN = re.compile(
    r"\(\s*(?:doc(?:_id)?|source)\s*[:=]\s*([^,)\n]+)\s*,\s*page\s*[:=]\s*(\d+)\s*\)",
    flags=re.IGNORECASE,
)
_ATTACHMENT_NOISE_TOKENS = {
    "a",
    "an",
    "and",
    "attachment",
    "appendix",
    "by",
    "for",
    "of",
    "required",
    "the",
    "to",
}
_MIN_CONFIDENCE_FOR_SUPPORTED = 0.35

_AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    flags=re.IGNORECASE,
)
_AWS_SECRET_INLINE_PATTERN = re.compile(r"(aws_secret_access_key\s*[:=]\s*)([^\s,;]+)", flags=re.IGNORECASE)


def _append_unique(values: list[str], item: str) -> list[str]:
    if item in values:
        return values
    return [*values, item]


def _coerce_sections(value: object) -> list[str]:
    if isinstance(value, list):
        return _dedupe_preserve_order([str(item).strip() for item in value if str(item).strip()])
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return _dedupe_preserve_order([part for part in parts if part])
    return []


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _as_optional_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_optional_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    return normalized


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _coerce_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return None
    return parsed


def _coerce_confidence(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return round(parsed, 3)


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value))


def _token_set(value: str) -> set[str]:
    normalized = _normalize_key(value)
    if not normalized:
        return set()
    return set(normalized.split())


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left:
        return 0.0
    return len(left & right) / len(left)
