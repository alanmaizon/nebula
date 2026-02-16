#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CURRENT_STATUS_KEYS = (
    "upload_status",
    "full_draft_status",
    "export_json_status",
    "export_md_status",
)


@dataclass
class RunMetrics:
    run_label: str
    pipeline_success_ratio: float
    requirement_count: int
    met_count: int
    partial_count: int
    missing_count: int
    draft_paragraph_count: int
    citation_count: int
    missing_evidence_count: int


@dataclass
class ExportCounts:
    requirement_count: int
    met_count: int
    partial_count: int
    missing_count: int
    paragraph_count: int
    citation_count: int
    missing_evidence_count: int


class ArtifactValidationError(ValueError):
    """Raised when demo-freeze artifacts do not match the expected contract."""


def _read_summary(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ArtifactValidationError(
            f"{path.parent.name}: missing required summary file '{path.name}'"
        )

    rows: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ArtifactValidationError(
                f"{path.parent.name}: invalid summary line at {path.name}:{line_number}; "
                f"expected key=value format"
            )
        key, value = line.split("=", 1)
        if not key.strip():
            raise ArtifactValidationError(
                f"{path.parent.name}: invalid summary key at {path.name}:{line_number}"
            )
        rows[key.strip()] = value.strip()
    return rows


def _field_path(parent_path: str, field: str) -> str:
    if not parent_path:
        return field
    return f"{parent_path}.{field}"


def _require_key(mapping: dict[str, Any], key: str, parent_path: str, run_label: str) -> Any:
    if key not in mapping:
        raise ArtifactValidationError(
            f"{run_label}: missing required field '{_field_path(parent_path, key)}'"
        )
    return mapping[key]


def _expect_object(value: Any, path: str, run_label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(
            f"{run_label}: expected object at '{path}', got {type(value).__name__}"
        )
    return value


def _expect_list(value: Any, path: str, run_label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ArtifactValidationError(
            f"{run_label}: expected array at '{path}', got {type(value).__name__}"
        )
    return value


def _read_json(path: Path, run_label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ArtifactValidationError(f"{run_label}: missing required artifact file '{path.name}'")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactValidationError(
            f"{run_label}: invalid JSON in '{path.name}' at line {exc.lineno}, column {exc.colno}"
        ) from exc
    return _expect_object(payload, path.name, run_label)


def _status_success_ratio(summary: dict[str, str], run_label: str) -> float:
    missing = [key for key in CURRENT_STATUS_KEYS if not str(summary.get(key, "")).strip()]
    if missing:
        raise ArtifactValidationError(
            f"{run_label}: summary.txt missing required status keys for current demo-freeze flow: "
            f"{', '.join(missing)}"
        )
    success = sum(1 for key in CURRENT_STATUS_KEYS if str(summary[key]).strip() == "200")
    return success / len(CURRENT_STATUS_KEYS)


def _extract_export_counts(export_payload: dict[str, Any], run_label: str) -> ExportCounts:
    export_version = str(_require_key(export_payload, "export_version", "", run_label)).strip()
    if export_version != "nebula.export.v1":
        raise ArtifactValidationError(
            f"{run_label}: unsupported export_version '{export_version}' in export.json; "
            "expected 'nebula.export.v1'"
        )

    bundle = _expect_object(_require_key(export_payload, "bundle", "", run_label), "bundle", run_label)
    bundle_json = _expect_object(_require_key(bundle, "json", "bundle", run_label), "bundle.json", run_label)

    requirements = _expect_object(
        _require_key(bundle_json, "requirements", "bundle.json", run_label),
        "bundle.json.requirements",
        run_label,
    )
    questions = _expect_list(
        _require_key(requirements, "questions", "bundle.json.requirements", run_label),
        "bundle.json.requirements.questions",
        run_label,
    )

    coverage = _expect_object(
        _require_key(bundle_json, "coverage", "bundle.json", run_label),
        "bundle.json.coverage",
        run_label,
    )
    coverage_items = _expect_list(
        _require_key(coverage, "items", "bundle.json.coverage", run_label),
        "bundle.json.coverage.items",
        run_label,
    )

    drafts = _expect_object(
        _require_key(bundle_json, "drafts", "bundle.json", run_label),
        "bundle.json.drafts",
        run_label,
    )
    missing_evidence = _expect_list(
        _require_key(bundle_json, "missing_evidence", "bundle.json", run_label),
        "bundle.json.missing_evidence",
        run_label,
    )

    met_count = 0
    partial_count = 0
    missing_count = 0
    for index, raw_item in enumerate(coverage_items):
        item_path = f"bundle.json.coverage.items[{index}]"
        item = _expect_object(raw_item, item_path, run_label)
        status = str(_require_key(item, "status", item_path, run_label)).strip().lower()
        if status == "met":
            met_count += 1
        elif status == "partial":
            partial_count += 1
        elif status == "missing":
            missing_count += 1
        else:
            raise ArtifactValidationError(
                f"{run_label}: unsupported coverage status '{status}' at '{item_path}.status'"
            )

    paragraph_count = 0
    citation_count = 0
    for section_key, raw_section in drafts.items():
        section_path = f"bundle.json.drafts.{section_key}"
        section = _expect_object(raw_section, section_path, run_label)
        draft = _expect_object(
            _require_key(section, "draft", section_path, run_label),
            f"{section_path}.draft",
            run_label,
        )
        paragraphs = _expect_list(
            _require_key(draft, "paragraphs", f"{section_path}.draft", run_label),
            f"{section_path}.draft.paragraphs",
            run_label,
        )
        paragraph_count += len(paragraphs)
        for index, raw_paragraph in enumerate(paragraphs):
            paragraph_path = f"{section_path}.draft.paragraphs[{index}]"
            paragraph = _expect_object(raw_paragraph, paragraph_path, run_label)
            citations = _expect_list(
                _require_key(paragraph, "citations", paragraph_path, run_label),
                f"{paragraph_path}.citations",
                run_label,
            )
            citation_count += len(citations)

    return ExportCounts(
        requirement_count=len(questions),
        met_count=met_count,
        partial_count=partial_count,
        missing_count=missing_count,
        paragraph_count=paragraph_count,
        citation_count=citation_count,
        missing_evidence_count=len(missing_evidence),
    )


def _validate_full_draft_payload(full_draft_payload: dict[str, Any], run_label: str) -> None:
    _expect_object(
        _require_key(full_draft_payload, "requirements", "full_draft", run_label),
        "full_draft.requirements",
        run_label,
    )
    section_runs = _expect_list(
        _require_key(full_draft_payload, "section_runs", "full_draft", run_label),
        "full_draft.section_runs",
        run_label,
    )
    if not section_runs:
        raise ArtifactValidationError(
            f"{run_label}: full_draft.section_runs must contain at least one section run"
        )

    coverage = _expect_object(
        _require_key(full_draft_payload, "coverage", "full_draft", run_label),
        "full_draft.coverage",
        run_label,
    )
    _expect_list(
        _require_key(coverage, "items", "full_draft.coverage", run_label),
        "full_draft.coverage.items",
        run_label,
    )

    export = _expect_object(
        _require_key(full_draft_payload, "export", "full_draft", run_label),
        "full_draft.export",
        run_label,
    )
    export_bundle = _expect_object(
        _require_key(export, "bundle", "full_draft.export", run_label),
        "full_draft.export.bundle",
        run_label,
    )
    export_bundle_json = _expect_object(
        _require_key(export_bundle, "json", "full_draft.export.bundle", run_label),
        "full_draft.export.bundle.json",
        run_label,
    )
    _expect_object(
        _require_key(export_bundle_json, "requirements", "full_draft.export.bundle.json", run_label),
        "full_draft.export.bundle.json.requirements",
        run_label,
    )
    _expect_object(
        _require_key(export_bundle_json, "drafts", "full_draft.export.bundle.json", run_label),
        "full_draft.export.bundle.json.drafts",
        run_label,
    )
    _expect_object(
        _require_key(export_bundle_json, "coverage", "full_draft.export.bundle.json", run_label),
        "full_draft.export.bundle.json.coverage",
        run_label,
    )

    run_summary = _expect_object(
        _require_key(full_draft_payload, "run_summary", "full_draft", run_label),
        "full_draft.run_summary",
        run_label,
    )
    run_status = str(_require_key(run_summary, "status", "full_draft.run_summary", run_label)).strip()
    if run_status != "complete":
        raise ArtifactValidationError(
            f"{run_label}: full_draft.run_summary.status must be 'complete', got '{run_status}'"
        )


def _collect_run_metrics(run_dir: Path) -> RunMetrics:
    summary = _read_summary(run_dir / "summary.txt")
    run_label = summary.get("run_label", run_dir.name)
    pipeline_success_ratio = _status_success_ratio(summary, run_label)

    full_draft_payload = _read_json(run_dir / "full_draft.json", run_label)
    _validate_full_draft_payload(full_draft_payload, run_label)

    export_payload = _read_json(run_dir / "export.json", run_label)
    export_counts = _extract_export_counts(export_payload, run_label)

    return RunMetrics(
        run_label=run_label,
        pipeline_success_ratio=pipeline_success_ratio,
        requirement_count=export_counts.requirement_count,
        met_count=export_counts.met_count,
        partial_count=export_counts.partial_count,
        missing_count=export_counts.missing_count,
        draft_paragraph_count=export_counts.paragraph_count,
        citation_count=export_counts.citation_count,
        missing_evidence_count=export_counts.missing_evidence_count,
    )


def _pct(value: float) -> float:
    return round(value * 100, 2)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute reproducible impact metrics from demo-freeze artifacts."
    )
    parser.add_argument(
        "--artifacts-root",
        default="/tmp/nebula-demo-freeze",
        help="Directory containing run-* artifact folders.",
    )
    parser.add_argument(
        "--out",
        default="docs/artifacts/impact-baseline-2026-02-08.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    artifacts_root = Path(args.artifacts_root)
    run_dirs = sorted(
        [path for path in artifacts_root.glob("run-*") if path.is_dir()],
        key=lambda path: path.name,
    )
    if not run_dirs:
        raise SystemExit(f"No run directories found under {artifacts_root}")

    try:
        runs = [_collect_run_metrics(run_dir) for run_dir in run_dirs]
    except ArtifactValidationError as exc:
        raise SystemExit(f"Impact baseline computation failed: {exc}") from exc

    avg_pipeline_success = _safe_div(
        sum(run.pipeline_success_ratio for run in runs), len(runs)
    )
    total_requirements = sum(run.requirement_count for run in runs)
    total_met = sum(run.met_count for run in runs)
    total_missing = sum(run.missing_count for run in runs)
    total_partial = sum(run.partial_count for run in runs)
    total_paragraphs = sum(run.draft_paragraph_count for run in runs)
    total_citations = sum(run.citation_count for run in runs)
    total_missing_evidence = sum(run.missing_evidence_count for run in runs)

    summary = {
        "artifacts_root": str(artifacts_root),
        "run_count": len(runs),
        "run_labels": [run.run_label for run in runs],
        "metrics": {
            "pipeline_success_rate_pct": _pct(avg_pipeline_success),
            "coverage_met_rate_pct": _pct(_safe_div(total_met, total_requirements)),
            "coverage_partial_rate_pct": _pct(_safe_div(total_partial, total_requirements)),
            "coverage_missing_rate_pct": _pct(_safe_div(total_missing, total_requirements)),
            "citation_density_per_paragraph": round(
                _safe_div(total_citations, total_paragraphs), 3
            ),
            "unsupported_claim_rate_pct": _pct(
                _safe_div(total_missing_evidence, total_paragraphs + total_missing_evidence)
            ),
            "requirements_per_run_avg": round(_safe_div(total_requirements, len(runs)), 3),
        },
        "raw_totals": {
            "requirements": total_requirements,
            "coverage_met": total_met,
            "coverage_partial": total_partial,
            "coverage_missing": total_missing,
            "paragraphs": total_paragraphs,
            "citations": total_citations,
            "missing_evidence_items": total_missing_evidence,
        },
        "per_run": [run.__dict__ for run in runs],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote impact baseline metrics: {out_path}")
    print(json.dumps(summary["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
