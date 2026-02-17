from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from app.config import settings
from app.db import create_run_trace_event
from app.observability import sanitize_for_logging


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _bounded_float(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _coverage_status_counts(coverage_payload: dict[str, object]) -> dict[str, int]:
    counts = {"met": 0, "partial": 0, "missing": 0}
    for item in _coerce_dict_list(coverage_payload.get("items")):
        status = str(item.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    return counts


def _parse_judge_threshold(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return _bounded_float(parsed)


@dataclass
class RunTraceRecorder:
    project_id: str
    run_id: str
    upload_batch_id: str | None
    _sequence_no: int = 0

    @property
    def sequence_no(self) -> int:
        return self._sequence_no

    def emit(self, *, phase: str, event_type: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        next_payload = payload if isinstance(payload, dict) else {}
        sanitized_payload = sanitize_for_logging(next_payload, max_string_length=480)
        canonical = json.dumps(
            sanitized_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        self._sequence_no += 1
        return create_run_trace_event(
            project_id=self.project_id,
            run_id=self.run_id,
            upload_batch_id=self.upload_batch_id,
            sequence_no=self._sequence_no,
            phase=phase,
            event_type=event_type,
            payload=sanitized_payload,
            payload_sha256=payload_sha256,
        )


def evaluate_full_draft_run(
    *,
    requirements_payload: dict[str, object],
    extraction_metadata: dict[str, object],
    extraction_validation: dict[str, object],
    section_runs: list[dict[str, object]],
    coverage_payload: dict[str, object],
    coverage_validation: dict[str, object],
    missing_evidence: list[dict[str, object]],
    unresolved_items: list[dict[str, object]],
    export_bundle: dict[str, object],
) -> dict[str, object]:
    questions = _coerce_dict_list(requirements_payload.get("questions"))
    question_prompts = [str(question.get("prompt") or "").strip() for question in questions]
    populated_prompts = [prompt for prompt in question_prompts if prompt]
    deterministic_question_count = int(extraction_metadata.get("deterministic_question_count") or 0)
    expected_questions = max(deterministic_question_count, len(populated_prompts), 1)

    extraction_errors = extraction_validation.get("errors")
    extraction_error_count = len(extraction_errors) if isinstance(extraction_errors, list) else 0
    extraction_repaired = _coerce_bool(extraction_validation.get("repaired"))
    extraction_rfp = _coerce_dict(extraction_metadata.get("rfp_selection"))
    rfp_ambiguous = _coerce_bool(extraction_rfp.get("ambiguous"))

    extraction_completeness = len(populated_prompts) / expected_questions
    extraction_completeness = extraction_completeness * 0.85 + (0.15 if not rfp_ambiguous else 0.0)
    extraction_completeness -= min(0.3, extraction_error_count * 0.06)
    if extraction_repaired:
        extraction_completeness -= 0.08

    paragraph_count = 0
    grounded_paragraph_count = 0
    unsupported_paragraph_count = 0
    for section in section_runs:
        draft_payload = _coerce_dict(section.get("draft"))
        paragraphs = _coerce_dict_list(draft_payload.get("paragraphs"))
        for paragraph in paragraphs:
            text = str(paragraph.get("text") or "").strip()
            if not text:
                continue
            paragraph_count += 1
            citations = paragraph.get("citations")
            citation_count = len(citations) if isinstance(citations, list) else 0
            unsupported = _coerce_bool(paragraph.get("unsupported"))
            if citation_count > 0 and not unsupported:
                grounded_paragraph_count += 1
            if unsupported:
                unsupported_paragraph_count += 1

    export_summary = _coerce_dict(export_bundle.get("summary"))
    export_uncertainty = _coerce_dict(export_summary.get("uncertainty"))
    citation_mismatch_count = int(export_uncertainty.get("citation_mismatch_count") or 0)

    citation_integrity = grounded_paragraph_count / max(paragraph_count, 1)
    citation_integrity -= min(0.45, citation_mismatch_count / max(paragraph_count, 1) * 0.45)

    coverage_counts = _coverage_status_counts(coverage_payload)
    coverage_total = coverage_counts["met"] + coverage_counts["partial"] + coverage_counts["missing"]
    coverage_confidence = (
        (coverage_counts["met"] + 0.5 * coverage_counts["partial"]) / coverage_total
        if coverage_total > 0
        else 0.0
    )
    coverage_errors = coverage_validation.get("errors")
    coverage_error_count = len(coverage_errors) if isinstance(coverage_errors, list) else 0
    coverage_confidence -= min(0.25, coverage_error_count * 0.05)
    if _coerce_bool(coverage_validation.get("repaired")):
        coverage_confidence -= 0.05

    missing_count = len(missing_evidence)
    unresolved_count = len(unresolved_items)
    actionable_missing_count = 0
    for item in missing_evidence:
        suggested_upload = str(item.get("suggested_upload") or "").strip()
        suggested_doc_types = item.get("suggested_doc_types")
        has_doc_types = isinstance(suggested_doc_types, list) and len(suggested_doc_types) > 0
        if suggested_upload or has_doc_types:
            actionable_missing_count += 1

    if missing_count == 0 and unresolved_count == 0:
        missing_precision = 1.0
    elif missing_count == 0:
        missing_precision = 0.0
    else:
        aligned = min(unresolved_count, missing_count) / missing_count
        actionable_ratio = actionable_missing_count / missing_count
        missing_precision = aligned * 0.8 + actionable_ratio * 0.2
        if unresolved_count > missing_count:
            missing_precision -= min(0.3, (unresolved_count - missing_count) * 0.05)

    dimensions = {
        "extraction_completeness": _bounded_float(extraction_completeness),
        "citation_integrity": _bounded_float(citation_integrity),
        "coverage_confidence": _bounded_float(coverage_confidence),
        "missing_evidence_precision": _bounded_float(missing_precision),
    }

    overall_score = _bounded_float(
        dimensions["extraction_completeness"] * 0.2
        + dimensions["citation_integrity"] * 0.3
        + dimensions["coverage_confidence"] * 0.3
        + dimensions["missing_evidence_precision"] * 0.2
    )

    min_dimension_score = _parse_judge_threshold(
        getattr(settings, "judge_eval_min_dimension_score", 0.55),
        fallback=0.55,
    )
    min_overall_score = _parse_judge_threshold(
        getattr(settings, "judge_eval_min_overall_score", 0.65),
        fallback=0.65,
    )
    block_on_fail = _coerce_bool(getattr(settings, "judge_eval_block_on_fail", False))

    reasons: list[str] = []
    if overall_score < min_overall_score:
        reasons.append(
            f"overall_score {overall_score:.3f} below threshold {min_overall_score:.3f}"
        )
    for dimension_key, score in dimensions.items():
        if score < min_dimension_score:
            reasons.append(
                f"{dimension_key} {score:.3f} below threshold {min_dimension_score:.3f}"
            )

    passed = len(reasons) == 0
    blocked = (not passed) and block_on_fail

    return {
        "rubric_version": "judge.v1",
        "scored_at": _utc_now_iso(),
        "dimensions": {
            "extraction_completeness": {
                "score": dimensions["extraction_completeness"],
                "signals": {
                    "questions_expected": expected_questions,
                    "questions_with_prompt": len(populated_prompts),
                    "rfp_selection_ambiguous": rfp_ambiguous,
                    "validation_error_count": extraction_error_count,
                    "validation_repaired": extraction_repaired,
                },
            },
            "citation_integrity": {
                "score": dimensions["citation_integrity"],
                "signals": {
                    "paragraph_count": paragraph_count,
                    "grounded_paragraph_count": grounded_paragraph_count,
                    "unsupported_paragraph_count": unsupported_paragraph_count,
                    "citation_mismatch_count": citation_mismatch_count,
                },
            },
            "coverage_confidence": {
                "score": dimensions["coverage_confidence"],
                "signals": {
                    "met": coverage_counts["met"],
                    "partial": coverage_counts["partial"],
                    "missing": coverage_counts["missing"],
                    "coverage_validation_error_count": coverage_error_count,
                    "coverage_validation_repaired": _coerce_bool(coverage_validation.get("repaired")),
                },
            },
            "missing_evidence_precision": {
                "score": dimensions["missing_evidence_precision"],
                "signals": {
                    "missing_evidence_count": missing_count,
                    "unresolved_count": unresolved_count,
                    "actionable_missing_count": actionable_missing_count,
                },
            },
        },
        "overall_score": overall_score,
        "thresholds": {
            "min_overall_score": min_overall_score,
            "min_dimension_score": min_dimension_score,
            "block_on_fail": block_on_fail,
        },
        "gate": {
            "passed": passed,
            "flagged": not passed,
            "blocked": blocked,
            "reasons": reasons,
        },
    }
