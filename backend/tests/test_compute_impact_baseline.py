from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "compute_impact_baseline.py"


def _load_compute_module():
    spec = importlib.util.spec_from_file_location("compute_impact_baseline", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_export_payload() -> dict[str, object]:
    return {
        "export_version": "nebula.export.v1",
        "bundle": {
            "json": {
                "requirements": {
                    "questions": [
                        {"id": "Q1", "prompt": "Describe outcomes."},
                        {"id": "Q2", "prompt": "Explain timeline."},
                    ]
                },
                "coverage": {
                    "items": [
                        {"requirement_id": "Q1", "status": "met"},
                        {"requirement_id": "Q2", "status": "partial"},
                    ]
                },
                "drafts": {
                    "Need Statement": {
                        "draft": {
                            "paragraphs": [
                                {
                                    "text": "Need paragraph",
                                    "citations": [{"doc_id": "impact.txt", "page": 1, "snippet": "Need"}],
                                },
                                {
                                    "text": "Outcomes paragraph",
                                    "citations": [{"doc_id": "impact.txt", "page": 2, "snippet": "Outcomes"}],
                                },
                            ]
                        }
                    },
                    "Implementation Timeline": {
                        "draft": {
                            "paragraphs": [
                                {
                                    "text": "Timeline paragraph",
                                    "citations": [],
                                }
                            ]
                        }
                    },
                },
                "missing_evidence": [{"section_key": "Implementation Timeline", "reason": "Need citation"}],
            },
            "markdown": {"files": [{"path": "README_EXPORT.md", "content": "ok"}]},
        },
    }


def _build_full_draft_payload() -> dict[str, object]:
    return {
        "requirements": {"questions": [{"id": "Q1"}, {"id": "Q2"}]},
        "section_runs": [{"section_key": "Need Statement"}, {"section_key": "Implementation Timeline"}],
        "coverage": {"items": [{"requirement_id": "Q1", "status": "met"}]},
        "export": {
            "bundle": {
                "json": {
                    "requirements": {"questions": [{"id": "Q1"}, {"id": "Q2"}]},
                    "drafts": {
                        "Need Statement": {"draft": {"paragraphs": []}},
                        "Implementation Timeline": {"draft": {"paragraphs": []}},
                    },
                    "coverage": {"items": [{"requirement_id": "Q1", "status": "met"}]},
                }
            }
        },
        "run_summary": {"status": "complete"},
    }


def _write_run_artifacts(
    artifacts_root: Path,
    run_name: str,
    *,
    summary_overrides: dict[str, str] | None = None,
    export_payload: dict[str, object] | None = None,
    full_draft_payload: dict[str, object] | None = None,
) -> Path:
    run_dir = artifacts_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "run_label": run_name,
        "upload_status": "200",
        "full_draft_status": "200",
        "export_json_status": "200",
        "export_md_status": "200",
    }
    if summary_overrides:
        summary.update(summary_overrides)
    summary_lines = [f"{key}={value}" for key, value in summary.items()]
    (run_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    (run_dir / "export.json").write_text(
        json.dumps(export_payload or _build_export_payload(), indent=2),
        encoding="utf-8",
    )
    (run_dir / "full_draft.json").write_text(
        json.dumps(full_draft_payload or _build_full_draft_payload(), indent=2),
        encoding="utf-8",
    )
    return run_dir


def test_collect_run_metrics_reads_current_export_bundle_shape(tmp_path: Path) -> None:
    module = _load_compute_module()
    run_dir = _write_run_artifacts(tmp_path, "run-1")
    metrics = module._collect_run_metrics(run_dir)

    assert metrics.run_label == "run-1"
    assert metrics.pipeline_success_ratio == 1.0
    assert metrics.requirement_count == 2
    assert metrics.met_count == 1
    assert metrics.partial_count == 1
    assert metrics.missing_count == 0
    assert metrics.draft_paragraph_count == 3
    assert metrics.citation_count == 2
    assert metrics.missing_evidence_count == 1


def test_collect_run_metrics_fails_with_actionable_field_path(tmp_path: Path) -> None:
    module = _load_compute_module()
    export_payload = _build_export_payload()
    export_payload["bundle"]["json"]["coverage"] = {}
    run_dir = _write_run_artifacts(tmp_path, "run-1", export_payload=export_payload)

    with pytest.raises(module.ArtifactValidationError, match="bundle.json.coverage.items"):
        module._collect_run_metrics(run_dir)


def test_compute_impact_baseline_script_writes_stable_schema(tmp_path: Path) -> None:
    _write_run_artifacts(tmp_path, "run-1")

    run_2_export = copy.deepcopy(_build_export_payload())
    run_2_export["bundle"]["json"]["coverage"]["items"][1]["status"] = "missing"
    run_2_export["bundle"]["json"]["missing_evidence"].append(
        {"section_key": "Need Statement", "reason": "Second unsupported claim"}
    )
    _write_run_artifacts(
        tmp_path,
        "run-2",
        summary_overrides={"export_md_status": "500"},
        export_payload=run_2_export,
    )

    out_path = tmp_path / "impact-baseline.json"
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--artifacts-root",
        str(tmp_path),
        "--out",
        str(out_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {
        "artifacts_root",
        "run_count",
        "run_labels",
        "metrics",
        "raw_totals",
        "per_run",
    }
    assert set(payload["metrics"].keys()) == {
        "pipeline_success_rate_pct",
        "coverage_met_rate_pct",
        "coverage_partial_rate_pct",
        "coverage_missing_rate_pct",
        "citation_density_per_paragraph",
        "unsupported_claim_rate_pct",
        "requirements_per_run_avg",
    }
    assert payload["run_count"] == 2
    assert payload["metrics"]["pipeline_success_rate_pct"] == 87.5
    assert payload["metrics"]["coverage_met_rate_pct"] == 50.0
    assert payload["metrics"]["coverage_partial_rate_pct"] == 25.0
    assert payload["metrics"]["coverage_missing_rate_pct"] == 25.0
    assert payload["metrics"]["citation_density_per_paragraph"] == 0.667
    assert payload["metrics"]["unsupported_claim_rate_pct"] == 33.33
    assert payload["metrics"]["requirements_per_run_avg"] == 2.0

    assert payload["raw_totals"] == {
        "requirements": 4,
        "coverage_met": 2,
        "coverage_partial": 1,
        "coverage_missing": 1,
        "paragraphs": 6,
        "citations": 4,
        "missing_evidence_items": 3,
    }
    assert len(payload["per_run"]) == 2
    for run in payload["per_run"]:
        assert set(run.keys()) == {
            "run_label",
            "pipeline_success_ratio",
            "requirement_count",
            "met_count",
            "partial_count",
            "missing_count",
            "draft_paragraph_count",
            "citation_count",
            "missing_evidence_count",
        }


def test_compute_impact_baseline_script_fails_for_legacy_summary_keys(tmp_path: Path) -> None:
    _write_run_artifacts(
        tmp_path,
        "run-legacy",
        summary_overrides={
            "full_draft_status": "",
            "export_json_status": "",
            "export_md_status": "",
            "extract_status": "200",
            "generate_status": "200",
            "coverage_status": "200",
        },
    )

    out_path = tmp_path / "impact-baseline.json"
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--artifacts-root",
        str(tmp_path),
        "--out",
        str(out_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)

    assert completed.returncode != 0
    assert "summary.txt missing required status keys for current demo-freeze flow" in completed.stderr
    assert "full_draft_status" in completed.stderr
