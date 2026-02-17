from __future__ import annotations

from .export_bundle_common import (
    _as_dict,
    _as_dict_list,
    _as_optional_dict,
    _coerce_sections,
    _dedupe_preserve_order,
    _utc_now_iso,
)
from .export_bundle_drafts import (
    _build_document_lookup,
    _merge_missing_evidence,
    _normalize_drafts,
    _prepare_drafts_for_export,
    _redact_value,
)
from .export_bundle_markdown import _build_markdown_files
from .export_bundle_metrics import (
    _compute_completion,
    _coverage_counts,
    _extract_constraints,
    _resolve_section_order,
)
from .export_bundle_reconciliation import (
    _build_section_stats,
    _derive_coverage_uncertainty_signals,
    _reconcile_coverage_items,
)

EXPORT_VERSION = "nebula.export.v1"


def build_export_bundle(input_payload: dict[str, object]) -> dict[str, object]:
    generated_at = _utc_now_iso()
    project = _as_dict(input_payload.get("project"))
    export_request = _as_dict(input_payload.get("export_request"))

    fmt = str(export_request.get("format") or "json").lower()
    if fmt not in {"json", "markdown", "both"}:
        fmt = "json"

    profile = str(export_request.get("profile") or "submission").lower()
    if profile not in {"hackathon", "submission", "internal"}:
        profile = "submission"
    include_debug = bool(export_request.get("include_debug", False))

    documents = _as_dict_list(input_payload.get("documents"))
    requirements = _as_optional_dict(input_payload.get("requirements"))
    coverage = _as_optional_dict(input_payload.get("coverage"))
    validations = _as_optional_dict(input_payload.get("validations")) or {}
    raw_missing_evidence = _as_dict_list(input_payload.get("missing_evidence"))
    artifacts_used = _as_dict_list(input_payload.get("artifacts_used"))
    run_metadata = _as_optional_dict(input_payload.get("run_metadata")) or {}
    source_selection = _as_optional_dict(input_payload.get("source_selection")) or {}

    requested_sections = _coerce_sections(export_request.get("sections"))
    drafts_map = _normalize_drafts(input_payload.get("drafts"))
    selected_sections = _resolve_section_order(
        requirements=requirements,
        available_sections=list(drafts_map.keys()),
        requested_sections=requested_sections,
    )

    quality_reasons: list[str] = []
    warnings: list[str] = []

    missing_requested_sections = [
        section_key for section_key in requested_sections if section_key not in drafts_map
    ]
    if missing_requested_sections:
        quality_reasons.append(
            "Requested section(s) missing entirely: " + ", ".join(sorted(missing_requested_sections))
        )

    coverage_items = _as_dict_list((coverage or {}).get("items"))
    source_ambiguity_count = 1 if bool(source_selection.get("ambiguous")) else 0
    if source_ambiguity_count > 0:
        warnings.append("source ambiguity warning")

    if requirements is not None and coverage is None:
        quality_reasons.append("Requirements artifact exists but coverage artifact is missing.")

    valid_doc_ids, doc_page_counts = _build_document_lookup(documents)
    exported_drafts, unsupported_claims_count, draft_warnings, integrity_signals = _prepare_drafts_for_export(
        drafts_map=drafts_map,
        selected_sections=selected_sections,
        valid_doc_ids=valid_doc_ids,
        doc_page_counts=doc_page_counts,
    )
    warnings.extend(draft_warnings)

    reconciled_coverage_items = _reconcile_coverage_items(
        requirements=requirements,
        coverage_items=coverage_items,
        drafts=exported_drafts,
    )
    coverage_counts = _coverage_counts(reconciled_coverage_items)

    invalid_citation_doc_ids = set(integrity_signals.get("invalid_doc_ids") or [])
    if invalid_citation_doc_ids:
        quality_reasons.append(
            "Citation doc_id not found in project documents: "
            + ", ".join(sorted(invalid_citation_doc_ids))
        )
    if int(integrity_signals.get("citation_mismatch_count") or 0) > 0:
        warnings.append("citation mismatch warning")

    merged_missing_evidence = _merge_missing_evidence(raw_missing_evidence, exported_drafts)
    missing_evidence_count = len(merged_missing_evidence)

    known_constraints, unknown_constraints = _extract_constraints(requirements)
    if unknown_constraints:
        warnings.append("constraints_unknown present")
    if unsupported_claims_count > 0:
        warnings.append("unsupported_claims_count > 0")

    coverage_uncertainty = _derive_coverage_uncertainty_signals(
        requirements=requirements,
        coverage_items=reconciled_coverage_items,
        section_stats=_build_section_stats(exported_drafts),
    )
    warnings.extend(coverage_uncertainty["warnings"])
    completion = _compute_completion(
        coverage_counts,
        unsupported_claims_count=unsupported_claims_count,
        citation_mismatch_count=int(integrity_signals.get("citation_mismatch_count") or 0),
        empty_required_sections_count=int(coverage_uncertainty.get("empty_required_sections_count") or 0),
    )
    overall_completion = (
        f"{completion:.1f}%"
        if completion is not None
        else "unknown"
    )

    summary = {
        "overall_completion": overall_completion,
        "coverage_overview": coverage_counts,
        "unsupported_claims_count": unsupported_claims_count,
        "missing_evidence_count": missing_evidence_count,
        "uncertainty": {
            "citation_mismatch_count": int(integrity_signals.get("citation_mismatch_count") or 0),
            "source_conflict_count": int(coverage_uncertainty.get("source_conflict_count") or 0),
            "source_ambiguity_count": source_ambiguity_count,
            "empty_required_sections_count": int(coverage_uncertainty.get("empty_required_sections_count") or 0),
            "unsupported_claims_count": unsupported_claims_count,
        },
        "constraints": {
            "known": known_constraints,
            "unknown": unknown_constraints,
        },
    }

    markdown_files: list[dict[str, str]] = []
    if fmt in {"markdown", "both"}:
        markdown_files = _build_markdown_files(
            profile=profile,
            include_debug=include_debug,
            project=project,
            export_request=export_request,
            documents=documents,
            requirements=requirements,
            drafts=exported_drafts,
            selected_sections=selected_sections,
            coverage_items=reconciled_coverage_items,
            coverage_counts=coverage_counts,
            uncertainty=summary["uncertainty"] if isinstance(summary.get("uncertainty"), dict) else {},
            missing_evidence=merged_missing_evidence,
            validations=validations,
            run_metadata=run_metadata,
            summary=summary,
        )
        if not markdown_files:
            quality_reasons.append("Markdown requested but no markdown files produced.")

    bundle_json: dict[str, object] | None = None
    if fmt in {"json", "both"}:
        bundle_json = {
            "project": {
                "id": str(project.get("id") or ""),
                "name": str(project.get("name") or ""),
            },
            "export_request": export_request,
            "documents": documents,
            "requirements": requirements,
            "drafts": exported_drafts,
            "coverage": {"items": reconciled_coverage_items},
            "missing_evidence": merged_missing_evidence,
            "source_selection": source_selection,
            "validations": validations,
            "summary": summary,
        }

    redaction_warnings: list[str] = []
    redacted_run_metadata = _redact_value(run_metadata, redaction_warnings)
    warnings.extend(redaction_warnings)

    quality_gates = {
        "passed": len(quality_reasons) == 0,
        "reasons": _dedupe_preserve_order(quality_reasons),
        "warnings": _dedupe_preserve_order(warnings),
    }

    return {
        "export_version": EXPORT_VERSION,
        "generated_at": generated_at,
        "project": {
            "id": str(project.get("id") or ""),
            "name": str(project.get("name") or ""),
        },
        "bundle": {
            "json": bundle_json,
            "markdown": {"files": markdown_files} if fmt in {"markdown", "both"} else None,
        },
        "summary": summary,
        "quality_gates": quality_gates,
        "provenance": {
            "artifacts_used": artifacts_used,
            "run_metadata": redacted_run_metadata,
        },
    }


def combine_markdown_files(markdown_files: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for file in markdown_files:
        path = str(file.get("path") or "").strip()
        content = str(file.get("content") or "").strip()
        if not content:
            continue
        if path:
            blocks.append(f"# {path}\n\n{content}")
        else:
            blocks.append(content)
    return "\n\n---\n\n".join(blocks).strip()
