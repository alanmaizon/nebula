from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.nova_runtime import BedrockNovaOrchestrator


class FakeBedrockRuntimeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"][0]["text"]
        model_id = kwargs["modelId"]

        if "funder, deadline, eligibility, questions" in prompt:
            text = (
                '{"funder":"City Community Fund","deadline":"March 30, 2026","eligibility":[],'  # noqa: E501
                '"questions":[{"id":"Q1","prompt":"Describe program outcomes.","limit":{"type":"words","value":250}}],'  # noqa: E501
                '"required_attachments":[],"rubric":[],"disallowed_costs":[]}'
            )
        elif "section_key, paragraphs, missing_evidence" in prompt:
            text = (
                '{"section_key":"Need Statement","paragraphs":[{"text":"Need Statement: We served households with documented support.",'  # noqa: E501
                '"citations":[{"doc_id":"impact.txt","page":1,"snippet":"We served households with support."}],"confidence":0.87}],"missing_evidence":[]}'  # noqa: E501
            )
        else:
            assert model_id == settings.bedrock_lite_model_id
            text = (
                '{"items":[{"requirement_id":"Q1","status":"met","notes":"Requirement addressed with cited evidence.","evidence_refs":["impact.txt:p1"]}]}'  # noqa: E501
            )

        return {"output": {"message": {"content": [{"text": text}]}}}


def test_nova_end_to_end_api_run(tmp_path: Path, monkeypatch) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.chunk_size_chars = 220
    settings.chunk_overlap_chars = 40
    settings.embedding_dim = 64
    settings.enable_agentic_orchestration_pilot = False

    fake_client = FakeBedrockRuntimeClient()
    orchestrator = BedrockNovaOrchestrator(settings=settings, client=fake_client)
    monkeypatch.setattr("app.main.get_nova_orchestrator", lambda: orchestrator)

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Nova E2E"}).json()["id"]
        upload = client.post(
            f"/projects/{project_id}/upload",
            files=[
                (
                    "files",
                    (
                        "rfp.txt",
                        b"Funder: City Community Fund\nQuestion 1: Describe program outcomes. Limit 250 words.",
                        "text/plain",
                    ),
                ),
                (
                    "files",
                    ("impact.txt", b"We served households with documented support outcomes.", "text/plain"),
                ),
            ],
        )
        assert upload.status_code == 200

        extract = client.post(f"/projects/{project_id}/extract-requirements")
        assert extract.status_code == 200
        assert extract.json()["artifact"]["source"] == "nova-agents-v1"

        generate = client.post(
            f"/projects/{project_id}/generate-section",
            json={"section_key": "Need Statement", "top_k": 2},
        )
        assert generate.status_code == 200
        assert generate.json()["artifact"]["source"] == "nova-agents-v1"

        coverage = client.post(
            f"/projects/{project_id}/coverage",
            json={"section_key": "Need Statement"},
        )
        assert coverage.status_code == 200
        assert coverage.json()["artifact"]["source"] == "nova-agents-v1"

    assert len(fake_client.calls) == 3
