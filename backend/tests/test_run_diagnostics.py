from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.coverage import build_coverage_payload
from app.drafting import build_draft_payload
from app.main import app
from app.requirements import extract_requirements_payload
from app.api.services.tracing import evaluate_full_draft_run


@pytest.fixture(autouse=True)
def mock_nova_orchestrator(monkeypatch: pytest.MonkeyPatch):
    class FakeNovaOrchestrator:
        def plan_section_generation(
            self, section_key: str, requested_top_k: int, available_chunk_count: int
        ) -> dict[str, object]:
            bounded = max(1, min(requested_top_k, available_chunk_count))
            return {
                "retrieval_top_k": bounded,
                "retry_on_missing_evidence": True,
                "rationale": "default-plan",
            }

        def extract_requirements(self, chunks: list[dict[str, object]]) -> dict[str, object]:
            return extract_requirements_payload(chunks)

        def generate_section(
            self,
            section_key: str,
            ranked_chunks: list[dict[str, object]],
            *,
            prompt_context: dict[str, str] | None = None,
        ) -> dict[str, object]:
            return build_draft_payload(section_key, ranked_chunks)

        def compute_coverage(
            self, requirements: dict[str, object], draft: dict[str, object]
        ) -> dict[str, object]:
            return build_coverage_payload(requirements, draft)

    monkeypatch.setattr("app.main.get_nova_orchestrator", lambda: FakeNovaOrchestrator())


def test_generate_full_draft_persists_traces_and_evals(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    source_text = b"""
Funder: City Community Fund
Deadline: March 30, 2026
Question 1: Describe the need statement. Limit 150 words.
Question 2: Describe the program design. Limit 150 words.
We served 1240 households with emergency support in 2024.
"""

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Tracing"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("rfp.txt", source_text, "text/plain"))],
        )
        assert upload.status_code == 200

        run = client.post(
            f"/projects/{project_id}/generate-full-draft",
            json={"top_k": 2, "max_revision_rounds": 1},
        )
        assert run.status_code == 200
        run_payload = run.json()
        run_id = run_payload["run_id"]
        assert run_id

        diagnostics = client.get(f"/projects/{project_id}/runs/{run_id}/diagnostics")
        assert diagnostics.status_code == 200
        payload = diagnostics.json()

    trace_events = payload["trace_events"]
    assert len(trace_events) >= 8
    sequence = [int(event["sequence_no"]) for event in trace_events]
    assert sequence == list(range(1, len(trace_events) + 1))

    phases = [str(event["phase"]) for event in trace_events]
    assert "run" in phases
    assert "requirements_extraction" in phases
    assert "section_drafting" in phases
    assert "section_coverage" in phases
    assert "coverage_aggregate" in phases
    assert "export" in phases
    assert "judge_eval" in phases

    judge_evals = payload["judge_evals"]
    assert judge_evals
    assert judge_evals[0]["run_id"] == run_id


def test_trace_payload_redacts_sensitive_values(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    source_text = b"""
Funder: City Community Fund
Deadline: March 30, 2026
Question 1: Describe the need statement. Limit 150 words.
We served 1240 households with emergency support in 2024.
"""

    secret_brief = "contact user@example.org aws_secret_access_key=abcd1234abcd1234abcd1234abcd1234abcd1234"

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Tracing Redaction"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("rfp.txt", source_text, "text/plain"))],
        )
        assert upload.status_code == 200

        run = client.post(
            f"/projects/{project_id}/generate-full-draft",
            json={"top_k": 2, "max_revision_rounds": 1, "context_brief": secret_brief},
        )
        assert run.status_code == 200
        run_id = run.json()["run_id"]

        diagnostics = client.get(f"/projects/{project_id}/runs/{run_id}/diagnostics")
        assert diagnostics.status_code == 200
        trace_events = diagnostics.json()["trace_events"]

    run_start = next(
        event for event in trace_events if event["phase"] == "run" and event["event_type"] == "started"
    )
    context_brief = str(run_start["payload"].get("context_brief") or "")
    assert "user@example.org" not in context_brief
    assert "abcd1234abcd1234abcd1234abcd1234abcd1234" not in context_brief
    assert "[REDACTED_EMAIL]" in context_brief
    assert "[REDACTED]" in context_brief


def test_judge_eval_flags_low_quality_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "judge_eval_min_overall_score", 0.65)
    monkeypatch.setattr(settings, "judge_eval_min_dimension_score", 0.55)
    monkeypatch.setattr(settings, "judge_eval_block_on_fail", False)

    payload = evaluate_full_draft_run(
        requirements_payload={"questions": [{"prompt": "Question 1"}]},
        extraction_metadata={"deterministic_question_count": 2, "rfp_selection": {"ambiguous": True}},
        extraction_validation={"repaired": True, "errors": ["missing deadline", "missing funder"]},
        section_runs=[
            {
                "draft": {
                    "paragraphs": [
                        {
                            "text": "No grounded citation here.",
                            "citations": [],
                            "unsupported": True,
                        }
                    ]
                }
            }
        ],
        coverage_payload={
            "items": [
                {"status": "missing"},
                {"status": "missing"},
            ]
        },
        coverage_validation={"repaired": True, "errors": ["coverage invalid"]},
        missing_evidence=[],
        unresolved_items=[{"requirement_id": "Q1"}, {"requirement_id": "Q2"}],
        export_bundle={"summary": {"uncertainty": {"citation_mismatch_count": 2}}},
    )

    gate = payload["gate"]
    assert gate["passed"] is False
    assert gate["flagged"] is True
    assert gate["blocked"] is False
    assert payload["overall_score"] < 0.65


def test_judge_eval_can_block_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "judge_eval_min_overall_score", 0.65)
    monkeypatch.setattr(settings, "judge_eval_min_dimension_score", 0.55)
    monkeypatch.setattr(settings, "judge_eval_block_on_fail", True)

    payload = evaluate_full_draft_run(
        requirements_payload={"questions": [{"prompt": "Question 1"}]},
        extraction_metadata={"deterministic_question_count": 2, "rfp_selection": {"ambiguous": True}},
        extraction_validation={"repaired": True, "errors": ["missing deadline"]},
        section_runs=[{"draft": {"paragraphs": [{"text": "Unsupported", "citations": [], "unsupported": True}]}}],
        coverage_payload={"items": [{"status": "missing"}]},
        coverage_validation={"repaired": True, "errors": ["coverage invalid"]},
        missing_evidence=[],
        unresolved_items=[{"requirement_id": "Q1"}],
        export_bundle={"summary": {"uncertainty": {"citation_mismatch_count": 1}}},
    )

    gate = payload["gate"]
    assert gate["passed"] is False
    assert gate["flagged"] is True
    assert gate["blocked"] is True
