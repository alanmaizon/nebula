from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_DOCS_PATH = REPO_ROOT / "scripts" / "sync_docs.py"


def _load_sync_docs_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_docs_module", SYNC_DOCS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_status() -> dict:
    return {
        "project": "Nebula",
        "last_updated": "2026-02-17",
        "overall_completion_pct": 95,
        "current_phase": "phase_one",
        "phases": [
            {
                "id": "phase_one",
                "focus": "Phase One",
                "status": "in_progress",
                "done": ["Created baseline docs"],
                "next": ["Finalize release checklist"],
                "blockers": [],
            }
        ],
        "high_risks": [
            {
                "risk": "Release drift",
                "mitigation": "Run consistency checks in CI",
            }
        ],
        "aws": {
            "well_architected": [
                {
                    "pillar": "Operational Excellence",
                    "status": "partial",
                    "next_control": "Track roadmap hygiene",
                }
            ]
        },
    }


def _write_target(path: Path, block_name: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            f"Header for {path.name}\n"
            f"<!-- AUTO-GEN:{block_name}:START -->\n"
            f"{body}\n"
            f"<!-- AUTO-GEN:{block_name}:END -->\n"
        ),
        encoding="utf-8",
    )


def _seed_temp_repo(tmp_path: Path, module: ModuleType, *, stale: bool) -> tuple[Path, Path, dict]:
    repo_root = tmp_path / "repo"
    status = _base_status()
    docs_dir = repo_root / "docs"
    wiki_dir = docs_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    status_path = docs_dir / "status.yml"
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")

    if stale:
        plan_body = "- stale plan"
        aws_body = "- stale aws"
    else:
        plan_body = module.render_development_status(status)
        aws_body = module.render_aws_status(status)

    _write_target(wiki_dir / "DEVELOPMENT_PLAN.md", "DEVELOPMENT_PLAN_STATUS", plan_body)
    _write_target(wiki_dir / "AWS_ALIGNMENT.md", "AWS_STATUS", aws_body)

    return repo_root, status_path, status


def test_validate_status_schema_accepts_phase_only_payload() -> None:
    module = _load_sync_docs_module()
    validated = module.validate_status_schema(_base_status())
    assert validated["current_phase"] == "phase_one"
    assert isinstance(validated["phases"], list)


def test_validate_status_schema_rejects_legacy_week_keys() -> None:
    module = _load_sync_docs_module()
    legacy = _base_status()
    legacy["weeks"] = []
    legacy["current_week"] = 1

    with pytest.raises(SystemExit, match="Legacy keys 'weeks'/'current_week' are no longer supported"):
        module.validate_status_schema(legacy)


def test_validate_status_schema_rejects_unknown_current_phase() -> None:
    module = _load_sync_docs_module()
    invalid = _base_status()
    invalid["current_phase"] = "missing_phase"

    with pytest.raises(SystemExit, match="current_phase"):
        module.validate_status_schema(invalid)


def test_main_check_passes_when_docs_are_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_sync_docs_module()
    repo_root, status_path, _ = _seed_temp_repo(tmp_path, module, stale=False)

    monkeypatch.setattr(module, "ROOT", repo_root)
    monkeypatch.setattr(module, "STATUS_PATH", status_path)
    monkeypatch.setattr(sys, "argv", ["sync_docs.py", "--check"])

    assert module.main() == 0


def test_main_check_fails_when_docs_are_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_sync_docs_module()
    repo_root, status_path, _ = _seed_temp_repo(tmp_path, module, stale=True)

    monkeypatch.setattr(module, "ROOT", repo_root)
    monkeypatch.setattr(module, "STATUS_PATH", status_path)
    monkeypatch.setattr(sys, "argv", ["sync_docs.py", "--check"])

    exit_code = module.main()
    captured = capsys.readouterr().out

    assert exit_code == 1
    assert "Documentation is out of date" in captured
    assert "- docs/wiki/DEVELOPMENT_PLAN.md" in captured
    assert "- docs/wiki/AWS_ALIGNMENT.md" in captured


def test_main_write_mode_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_sync_docs_module()
    repo_root, status_path, _ = _seed_temp_repo(tmp_path, module, stale=True)

    monkeypatch.setattr(module, "ROOT", repo_root)
    monkeypatch.setattr(module, "STATUS_PATH", status_path)

    monkeypatch.setattr(sys, "argv", ["sync_docs.py"])
    assert module.main() == 0

    monkeypatch.setattr(sys, "argv", ["sync_docs.py", "--check"])
    assert module.main() == 0
