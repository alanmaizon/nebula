from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.coverage import build_coverage_payload
from app.drafting import build_draft_payload
from app.main import app
from app.requirements import extract_requirements_payload


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


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_ready_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_create_project_and_upload(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 40
    settings.chunk_overlap_chars = 10
    settings.embedding_dim = 64

    with TestClient(app) as scoped_client:
        project_response = scoped_client.post("/projects", json={"name": "Sample Grant"})
        assert project_response.status_code == 200
        project_id = project_response.json()["id"]

        upload_response = scoped_client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("rfp.txt", b"RFP content", "text/plain"))],
        )
        assert upload_response.status_code == 200
        payload = upload_response.json()
        assert payload["project_id"] == project_id
        assert len(payload["documents"]) == 1
        assert payload["documents"][0]["file_name"] == "rfp.txt"
        assert "storage_path" not in payload["documents"][0]
        assert payload["documents"][0]["chunks_indexed"] >= 1
        assert payload["documents"][0]["parse_report"]["quality"] in {"good", "low", "none"}
        assert payload["parse_report"]["documents_total"] == 1

        list_response = scoped_client.get(f"/projects/{project_id}/documents")
        assert list_response.status_code == 200
        assert len(list_response.json()["documents"]) == 1
        assert "storage_path" not in list_response.json()["documents"][0]


def test_upload_parse_report_marks_unsupported_file_types(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 40
    settings.chunk_overlap_chars = 10
    settings.embedding_dim = 64

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Parse Report"}).json()["id"]

        upload_response = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("scan.pdf", b"%PDF-1.7 binary payload", "application/pdf"))],
        )
        assert upload_response.status_code == 200
        payload = upload_response.json()
        document = payload["documents"][0]
        report = document["parse_report"]
        assert report["quality"] == "none"
        assert report["reason"] == "unsupported_file_type"
        assert report["chunks_indexed"] == 0


def test_upload_rejects_oversized_file(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    previous_limit = settings.max_upload_file_bytes
    settings.max_upload_file_bytes = 8

    try:
        with TestClient(app) as client:
            project_id = client.post("/projects", json={"name": "Upload Limits"}).json()["id"]
            upload_response = client.post(
                f"/projects/{project_id}/upload",
                files=[("files", ("too-large.txt", b"123456789", "text/plain"))],
            )
            assert upload_response.status_code == 413
            assert "exceeds max size" in str(upload_response.json()["detail"])
    finally:
        settings.max_upload_file_bytes = previous_limit


def test_retrieve_is_project_scoped(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 80
    settings.chunk_overlap_chars = 20
    settings.embedding_dim = 64

    with TestClient(app) as client:
        project_a = client.post("/projects", json={"name": "Project A"}).json()["id"]
        project_b = client.post("/projects", json={"name": "Project B"}).json()["id"]

        upload_a = client.post(
            f"/projects/{project_a}/upload",
            files=[
                (
                    "files",
                    (
                        "impact.txt",
                        b"We served 1240 households with rent support in 2024.",
                        "text/plain",
                    ),
                )
            ],
        )
        assert upload_a.status_code == 200

        upload_b = client.post(
            f"/projects/{project_b}/upload",
            files=[
                (
                    "files",
                    (
                        "other.txt",
                        b"This document is about tree planting metrics.",
                        "text/plain",
                    ),
                )
            ],
        )
        assert upload_b.status_code == 200

        result = client.post(
            f"/projects/{project_a}/retrieve",
            json={"query": "households rent support", "top_k": 3},
        )
        assert result.status_code == 200
        payload = result.json()
        assert payload["project_id"] == project_a
        assert len(payload["results"]) >= 1
        top = payload["results"][0]
        assert top["file_name"] == "impact.txt"


def test_retrieve_defaults_to_latest_upload_batch(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 80
    settings.chunk_overlap_chars = 20
    settings.embedding_dim = 64

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Batch Scope"}).json()["id"]

        first_upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("old.txt", b"legacyterm legacyterm legacyterm", "text/plain"))],
        )
        assert first_upload.status_code == 200

        second_upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("new.txt", b"newterm newterm newterm", "text/plain"))],
        )
        assert second_upload.status_code == 200
        second_batch_id = second_upload.json()["upload_batch_id"]

        latest_scoped = client.post(
            f"/projects/{project_id}/retrieve",
            json={"query": "legacyterm", "top_k": 3},
        )
        assert latest_scoped.status_code == 200
        latest_payload = latest_scoped.json()
        assert latest_payload["upload_batch_id"] == second_batch_id
        assert len(latest_payload["results"]) >= 1
        assert latest_payload["results"][0]["file_name"] == "new.txt"

        all_scoped = client.post(
            f"/projects/{project_id}/retrieve?document_scope=all",
            json={"query": "legacyterm", "top_k": 3},
        )
        assert all_scoped.status_code == 200
        all_payload = all_scoped.json()
        assert all_payload["upload_batch_id"] is None
        assert len(all_payload["results"]) >= 1
        assert all_payload["results"][0]["file_name"] == "old.txt"


def test_reindex_defaults_to_latest_upload_batch(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 80
    settings.chunk_overlap_chars = 20
    settings.embedding_dim = 64
    settings.embedding_mode = "hash"

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Reindex Batch Scope"}).json()["id"]

        first_upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("old.txt", b"legacyterm legacyterm legacyterm", "text/plain"))],
        )
        assert first_upload.status_code == 200

        second_upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("new.txt", b"newterm newterm newterm", "text/plain"))],
        )
        assert second_upload.status_code == 200
        second_batch_id = second_upload.json()["upload_batch_id"]

        reindex = client.post(f"/projects/{project_id}/reindex")
        assert reindex.status_code == 200
        payload = reindex.json()
        assert payload["upload_batch_id"] == second_batch_id
        assert payload["chunks_deleted"] >= 1
        assert payload["chunks_indexed"] >= 1
        assert payload["embedding"]["mode"] == "hash"
        assert payload["documents"][0]["parse_report"]["embedding_providers"]["hash"] >= 1

        latest_scoped = client.post(
            f"/projects/{project_id}/retrieve",
            json={"query": "legacyterm", "top_k": 3},
        )
        assert latest_scoped.status_code == 200
        latest_payload = latest_scoped.json()
        assert latest_payload["upload_batch_id"] == second_batch_id
        assert len(latest_payload["results"]) >= 1
        assert latest_payload["results"][0]["file_name"] == "new.txt"


def test_retrieve_handles_embedding_dimension_drift(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 80
    settings.chunk_overlap_chars = 20
    settings.embedding_dim = 64

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Embedding Drift"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("impact.txt", b"Households received rent support.", "text/plain"))],
        )
        assert upload.status_code == 200

        previous_dim = settings.embedding_dim
        try:
            settings.embedding_dim = 128
            retrieve = client.post(
                f"/projects/{project_id}/retrieve",
                json={"query": "rent support households", "top_k": 3},
            )
            assert retrieve.status_code == 200
            payload = retrieve.json()
            assert len(payload["results"]) >= 1
            assert payload["results"][0]["file_name"] == "impact.txt"
            warnings = payload.get("warnings")
            assert isinstance(warnings, list)
            assert any(item.get("code") == "embedding_dim_drift" for item in warnings if isinstance(item, dict))
        finally:
            settings.embedding_dim = previous_dim


def test_generate_section_surfaces_embedding_dimension_drift_warning(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 120
    settings.chunk_overlap_chars = 20
    settings.embedding_dim = 64

    source_text = b"""
Question 1: Describe the need statement.
Need Statement evidence with outcomes and household counts.
"""

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Draft Drift Warning"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("impact.txt", source_text, "text/plain"))],
        )
        assert upload.status_code == 200

        previous_dim = settings.embedding_dim
        try:
            settings.embedding_dim = 128
            generate = client.post(
                f"/projects/{project_id}/generate-section",
                json={"section_key": "Need Statement", "top_k": 2},
            )
            assert generate.status_code == 200
            payload = generate.json()
            warnings = payload.get("warnings")
            assert isinstance(warnings, list)
            assert any(item.get("code") == "embedding_dim_drift" for item in warnings if isinstance(item, dict))
        finally:
            settings.embedding_dim = previous_dim


def test_extract_requirements_defaults_to_latest_upload_batch(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 250
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    first_rfp = b"Funder: Legacy Foundation\nQuestion 1: Legacy prompt. Limit 100 words."
    second_rfp = b"Funder: New Foundation\nQuestion 1: Fresh prompt. Limit 120 words."

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Batch RFP"}).json()["id"]

        assert (
            client.post(
                f"/projects/{project_id}/upload",
                files=[("files", ("rfp_legacy.txt", first_rfp, "text/plain"))],
            ).status_code
            == 200
        )
        second_upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("rfp_new.txt", second_rfp, "text/plain"))],
        )
        assert second_upload.status_code == 200
        second_batch_id = second_upload.json()["upload_batch_id"]

        extract = client.post(f"/projects/{project_id}/extract-requirements")
        assert extract.status_code == 200
        payload = extract.json()
        assert payload["upload_batch_id"] == second_batch_id
        assert payload["requirements"]["funder"] == "New Foundation"
        rfp_selection = payload["extraction"]["rfp_selection"]
        assert rfp_selection["selected_file_name"] == "rfp_new.txt"


def test_extract_requirements_and_read_latest(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 300
    settings.chunk_overlap_chars = 50
    settings.embedding_dim = 64

    rfp_text = b"""
Funder: City Community Fund
Deadline: March 30, 2026

Eligibility:
- Eligible applicants must be registered nonprofits.

Question 1: Describe program outcomes. Limit 250 words.
Question 2: Provide implementation timeline. Limit 1200 characters.

Required Attachments:
- Attachment A: Budget Narrative
- Attachment B: Board List

Rubric:
- Scoring criteria include impact and feasibility.

Disallowed costs:
- Alcohol purchases are not allowed costs.
"""

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "RFP Extraction"}).json()["id"]

        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("rfp.txt", rfp_text, "text/plain"))],
        )
        assert upload.status_code == 200

        extract = client.post(f"/projects/{project_id}/extract-requirements")
        assert extract.status_code == 200
        payload = extract.json()
        requirements = payload["requirements"]
        extraction = payload["extraction"]
        assert requirements["funder"] == "City Community Fund"
        assert requirements["deadline"] == "March 30, 2026"
        assert len(requirements["questions"]) >= 2
        assert requirements["questions"][0]["limit"]["type"] in {"words", "none", "chars"}
        assert len(requirements["required_attachments"]) >= 1
        assert len(requirements["disallowed_costs"]) >= 1
        assert extraction["mode"] in {"deterministic+nova", "deterministic-only"}
        assert extraction["deterministic_question_count"] >= 2

        latest = client.get(f"/projects/{project_id}/requirements/latest")
        assert latest.status_code == 200
        assert latest.json()["artifact"]["source"] == "nova-agents-v1"


def test_extract_requirements_without_chunks_returns_400(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "No Chunks"}).json()["id"]
        extract = client.post(f"/projects/{project_id}/extract-requirements")
        assert extract.status_code == 400


def test_generate_section_and_read_latest_draft(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 120
    settings.chunk_overlap_chars = 20
    settings.embedding_dim = 64

    source_text = b"""
Question 1: Describe the organization need statement.
We served 1240 households with emergency support in 2024.
Our outcomes improved housing stability for low-income families.
"""

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Drafting"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[("files", ("impact.txt", source_text, "text/plain"))],
        )
        assert upload.status_code == 200

        generate = client.post(
            f"/projects/{project_id}/generate-section",
            json={"section_key": "Need Statement", "top_k": 2},
        )
        assert generate.status_code == 200
        payload = generate.json()
        assert payload["draft"]["section_key"] == "Need Statement"
        assert len(payload["draft"]["paragraphs"]) >= 1
        first = payload["draft"]["paragraphs"][0]
        assert len(first["citations"]) >= 1
        assert first["citations"][0]["doc_id"] == "impact.txt"

        latest = client.get(f"/projects/{project_id}/drafts/Need Statement/latest")
        assert latest.status_code == 200
        assert latest.json()["draft"]["section_key"] == "Need Statement"
        assert latest.json()["artifact"]["source"] == "nova-agents-v1"


def test_compute_coverage_and_read_latest(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    rfp_text = b"""
Funder: City Community Fund
Question 1: Describe program outcomes. Limit 250 words.
Question 2: Explain implementation timeline. Limit 500 words.
"""
    source_text = b"""
Need Statement: We served 1240 households in 2024 with emergency housing support.
Our implementation timeline spans four quarters with milestones.
"""

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Coverage"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[
                ("files", ("rfp.txt", rfp_text, "text/plain")),
                ("files", ("impact.txt", source_text, "text/plain")),
            ],
        )
        assert upload.status_code == 200

        extract = client.post(f"/projects/{project_id}/extract-requirements")
        assert extract.status_code == 200

        generate = client.post(
            f"/projects/{project_id}/generate-section",
            json={"section_key": "Need Statement", "top_k": 3},
        )
        assert generate.status_code == 200

        coverage = client.post(
            f"/projects/{project_id}/coverage",
            json={"section_key": "Need Statement"},
        )
        assert coverage.status_code == 200
        payload = coverage.json()
        assert payload["project_id"] == project_id
        assert len(payload["coverage"]["items"]) >= 1
        assert payload["coverage"]["items"][0]["status"] in {"met", "partial", "missing"}

        latest = client.get(f"/projects/{project_id}/coverage/latest")
        assert latest.status_code == 200
        assert len(latest.json()["coverage"]["items"]) >= 1
        assert latest.json()["artifact"]["source"] == "nova-agents-v1"


def test_export_json_and_markdown(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Export"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[
                (
                    "files",
                    (
                        "rfp.txt",
                        b"Funder: City Community Fund\nQuestion 1: Describe outcomes. Limit 200 words.",
                        "text/plain",
                    ),
                ),
                (
                    "files",
                    (
                        "impact.txt",
                        b"We served 1240 households and improved housing stability outcomes.",
                        "text/plain",
                    ),
                ),
            ],
        )
        assert upload.status_code == 200

        assert client.post(f"/projects/{project_id}/extract-requirements").status_code == 200
        assert (
            client.post(
                f"/projects/{project_id}/generate-section",
                json={"section_key": "Need Statement"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/projects/{project_id}/coverage",
                json={"section_key": "Need Statement"},
            ).status_code
            == 200
        )

        export_json = client.get(f"/projects/{project_id}/export?format=json&section_key=Need Statement")
        assert export_json.status_code == 200
        payload = export_json.json()
        assert payload["export_version"] == "nebula.export.v1"
        assert payload["project"]["id"] == project_id
        assert payload["bundle"]["json"] is not None
        assert payload["bundle"]["json"]["requirements"] is not None
        assert payload["bundle"]["markdown"] is not None
        markdown_files = payload["bundle"]["markdown"]["files"]
        assert isinstance(markdown_files, list)
        assert len(markdown_files) >= 1

        exports_root = tmp_path / "exports" / project_id
        assert exports_root.exists()
        assert (exports_root / "application.md").exists()
        assert (exports_root / "requirements.md").exists()

        export_md = client.get(f"/projects/{project_id}/export?format=markdown&section_key=Need Statement")
        assert export_md.status_code == 200
        assert "Draft Application" in export_md.text


def test_agentic_orchestration_pilot_retries_missing_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class PilotOrchestrator:
        def plan_section_generation(
            self, section_key: str, requested_top_k: int, available_chunk_count: int
        ) -> dict[str, object]:
            return {
                "retrieval_top_k": 1,
                "retry_on_missing_evidence": True,
                "rationale": "pilot-retry",
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
            if len(ranked_chunks) < 2:
                return {
                    "section_key": section_key,
                    "paragraphs": [],
                    "missing_evidence": [
                        {
                            "claim": "Need additional evidence for complete draft.",
                            "suggested_upload": "Upload impact evidence.",
                        }
                    ],
                }
            return {
                "section_key": section_key,
                "paragraphs": [
                    {
                        "text": "Need Statement: Evidence-backed pilot draft.",
                        "citations": [
                            {
                                "doc_id": str(ranked_chunks[0]["file_name"]),
                                "page": int(ranked_chunks[0]["page"]),
                                "snippet": str(ranked_chunks[0]["text"])[:120],
                            }
                        ],
                        "confidence": 0.75,
                    }
                ],
                "missing_evidence": [],
            }

        def compute_coverage(
            self, requirements: dict[str, object], draft: dict[str, object]
        ) -> dict[str, object]:
            return build_coverage_payload(requirements, draft)

    monkeypatch.setattr("app.main.get_nova_orchestrator", lambda: PilotOrchestrator())

    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 70
    settings.chunk_overlap_chars = 10
    settings.embedding_dim = 64

    source_text = (
        b"Need Statement evidence paragraph one. "
        b"Need Statement evidence paragraph two with additional support. "
        b"Need Statement evidence paragraph three for refinement."
    )

    previous_flag = settings.enable_agentic_orchestration_pilot
    try:
        with TestClient(app) as client:
            project_id = client.post("/projects", json={"name": "Pilot Off"}).json()["id"]
            upload = client.post(
                f"/projects/{project_id}/upload",
                files=[("files", ("impact.txt", source_text, "text/plain"))],
            )
            assert upload.status_code == 200

            settings.enable_agentic_orchestration_pilot = False
            off_resp = client.post(
                f"/projects/{project_id}/generate-section",
                json={"section_key": "Need Statement", "top_k": 1},
            )
            assert off_resp.status_code == 200
            off_draft = off_resp.json()["draft"]
            assert len(off_draft["paragraphs"]) == 0
            assert len(off_draft["missing_evidence"]) == 1

            settings.enable_agentic_orchestration_pilot = True
            on_resp = client.post(
                f"/projects/{project_id}/generate-section",
                json={"section_key": "Need Statement", "top_k": 1},
            )
            assert on_resp.status_code == 200
            on_draft = on_resp.json()["draft"]
            assert len(on_draft["paragraphs"]) == 1
            assert len(on_draft["missing_evidence"]) == 0
            assert len(on_draft["paragraphs"][0]["citations"]) >= 1
    finally:
        settings.enable_agentic_orchestration_pilot = previous_flag


def test_export_surfaces_source_ambiguity_warning(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    rfp_a = b"""
Funding Opportunity: City Community Fund
Required Narrative Questions:
Question 1: Need Statement (300 words max): Describe need.
"""
    rfp_b = b"""
Funding Opportunity: County Community Fund
Required Narrative Questions:
Question 1: Need Statement (300 words max): Describe need.
"""
    evidence = b"Need Statement evidence about households and service outcomes."

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Ambiguous RFP Export"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[
                ("files", ("rfp_a.txt", rfp_a, "text/plain")),
                ("files", ("rfp_b.txt", rfp_b, "text/plain")),
                ("files", ("evidence.txt", evidence, "text/plain")),
            ],
        )
        assert upload.status_code == 200

        assert client.post(f"/projects/{project_id}/extract-requirements").status_code == 200
        assert (
            client.post(
                f"/projects/{project_id}/generate-section",
                json={"section_key": "Need Statement"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/projects/{project_id}/coverage",
                json={"section_key": "Need Statement"},
            ).status_code
            == 200
        )

        export_json = client.get(f"/projects/{project_id}/export?format=json&section_key=Need Statement")
        assert export_json.status_code == 200
        payload = export_json.json()

        assert "source ambiguity warning" in payload["quality_gates"]["warnings"]
        assert payload["summary"]["uncertainty"]["source_ambiguity_count"] == 1


def test_generate_full_draft_endpoint_runs_all_sections_and_exports(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    rfp_text = b"""
Funder: City Community Fund
Question 1: Need Statement (300 words max): Describe the local need.
Question 2: Program Design (400 words max): Explain activities and timeline.
"""
    evidence_text = b"""
Need Statement evidence: 1240 households served in 2024.
Program Design evidence: monthly coaching, employer partnerships, quarterly milestones.
"""

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Full Run"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[
                ("files", ("rfp.txt", rfp_text, "text/plain")),
                ("files", ("evidence.txt", evidence_text, "text/plain")),
            ],
        )
        assert upload.status_code == 200

        run_response = client.post(
            f"/projects/{project_id}/generate-full-draft",
            json={"top_k": 4, "max_revision_rounds": 1},
        )
        assert run_response.status_code == 200
        payload = run_response.json()

        assert payload["project_id"] == project_id
        assert payload["run_summary"]["status"] == "complete"
        assert payload["run_summary"]["sections_total"] >= 2
        assert payload["run_summary"]["sections_completed"] == payload["run_summary"]["sections_total"]
        assert len(payload["section_runs"]) == payload["run_summary"]["sections_total"]

        section_keys = {item["section_key"] for item in payload["section_runs"]}
        assert "Need Statement" in section_keys
        assert "Program Design" in section_keys

        assert payload["coverage"]["items"]
        assert payload["export"]["bundle"]["json"] is not None
        assert payload["export"]["bundle"]["markdown"] is not None

        latest_coverage = client.get(f"/projects/{project_id}/coverage/latest")
        assert latest_coverage.status_code == 200
        assert len(latest_coverage.json()["coverage"]["items"]) >= 1


def test_generate_full_draft_passes_optional_context_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_contexts: list[dict[str, str] | None] = []

    class ContextAwareOrchestrator:
        def plan_section_generation(
            self, section_key: str, requested_top_k: int, available_chunk_count: int
        ) -> dict[str, object]:
            bounded = max(1, min(requested_top_k, available_chunk_count))
            return {
                "retrieval_top_k": bounded,
                "retry_on_missing_evidence": True,
                "rationale": "context-brief-pass-through",
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
            captured_contexts.append(prompt_context)
            return build_draft_payload(section_key, ranked_chunks)

        def compute_coverage(
            self, requirements: dict[str, object], draft: dict[str, object]
        ) -> dict[str, object]:
            return build_coverage_payload(requirements, draft)

    monkeypatch.setattr("app.main.get_nova_orchestrator", lambda: ContextAwareOrchestrator())

    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64

    rfp_text = b"""
Question 1: Need Statement (300 words max): Describe the local need.
"""
    evidence_text = b"""
Need Statement evidence: 1240 households served in 2024.
"""
    context_brief = "Focus on outcomes for first-time job seekers."

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Context Brief Run"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[
                ("files", ("rfp.txt", rfp_text, "text/plain")),
                ("files", ("evidence.txt", evidence_text, "text/plain")),
            ],
        )
        assert upload.status_code == 200

        run_response = client.post(
            f"/projects/{project_id}/generate-full-draft",
            json={
                "top_k": 4,
                "max_revision_rounds": 1,
                "context_brief": context_brief,
            },
        )
        assert run_response.status_code == 200

    assert captured_contexts
    assert all(context == {"context_brief": context_brief} for context in captured_contexts)
