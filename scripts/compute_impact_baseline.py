#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


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


def _read_summary(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        rows[key.strip()] = value.strip()
    return rows


def _status_success_ratio(summary: dict[str, str]) -> float:
    keys = (
        "upload_status",
        "extract_status",
        "generate_status",
        "coverage_status",
        "export_json_status",
        "export_md_status",
    )
    success = sum(1 for key in keys if summary.get(key) == "200")
    return success / len(keys)


def _collect_run_metrics(run_dir: Path) -> RunMetrics:
    summary = _read_summary(run_dir / "summary.txt")
    export_payload = json.loads((run_dir / "export.json").read_text(encoding="utf-8"))

    requirements = export_payload.get("requirements", {})
    coverage = export_payload.get("coverage", {})
    draft = export_payload.get("draft", {})

    questions = requirements.get("questions", [])
    items = coverage.get("items", [])
    paragraphs = draft.get("paragraphs", [])
    missing_evidence = draft.get("missing_evidence", [])

    met_count = sum(1 for item in items if item.get("status") == "met")
    partial_count = sum(1 for item in items if item.get("status") == "partial")
    missing_count = sum(1 for item in items if item.get("status") == "missing")
    citation_count = sum(len(paragraph.get("citations", [])) for paragraph in paragraphs)

    return RunMetrics(
        run_label=summary.get("run_label", run_dir.name),
        pipeline_success_ratio=_status_success_ratio(summary),
        requirement_count=len(questions),
        met_count=met_count,
        partial_count=partial_count,
        missing_count=missing_count,
        draft_paragraph_count=len(paragraphs),
        citation_count=citation_count,
        missing_evidence_count=len(missing_evidence),
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

    runs = [_collect_run_metrics(run_dir) for run_dir in run_dirs]

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
