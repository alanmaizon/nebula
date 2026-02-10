from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_intake_roundtrip_and_export_contains_context(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Intake"}).json()["id"]

        intake_payload = {
            "country": "Ireland",
            "organization_type": "Charity",
            "funder_track": "community-foundation",
            "funding_goal": "project",
            "sector_focus": "heritage",
        }

        save = client.post(f"/projects/{project_id}/intake", json=intake_payload)
        assert save.status_code == 200
        assert save.json()["intake"]["country"] == "Ireland"

        latest = client.get(f"/projects/{project_id}/intake")
        assert latest.status_code == 200
        assert latest.json()["intake"]["sector_focus"] == "heritage"

        export_json = client.get(f"/projects/{project_id}/export?format=json&section_key=Need Statement")
        assert export_json.status_code == 200
        payload = export_json.json()
        assert payload["bundle"]["json"] is not None
        assert payload["bundle"]["json"]["intake"] is not None
        assert payload["bundle"]["json"]["intake"]["sector_focus"] == "heritage"
        assert "template_recommendation" not in payload
        assert "template_metadata" not in payload
