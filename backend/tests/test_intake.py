from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_intake_and_template_recommendation_roundtrip(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")

    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "Intake"}).json()["id"]

        intake_payload = {
            "country": "Ireland",
            "organization_type": "Charity",
            "charity_registered": True,
            "tax_registered": True,
            "has_group_bank_account": True,
            "funder_track": "community-foundation",
            "funding_goal": "project",
            "sector_focus": "heritage",
            "timeline_quarters": 4,
            "has_evidence_data": True,
        }

        save = client.post(f"/projects/{project_id}/intake", json=intake_payload)
        assert save.status_code == 200
        assert save.json()["intake"]["country"] == "Ireland"

        latest = client.get(f"/projects/{project_id}/intake")
        assert latest.status_code == 200
        assert latest.json()["intake"]["sector_focus"] == "heritage"

        recommendation = client.post(f"/projects/{project_id}/template-recommendation", json={})
        assert recommendation.status_code == 200
        payload = recommendation.json()["recommendation"]
        assert payload["template_key"] == "irish_heritage_grant"
        assert len(payload["rationale"]) >= 1
        assert len(payload["required_checklist"]) >= 1

        export_json = client.get(f"/projects/{project_id}/export?format=json&section_key=Need Statement")
        assert export_json.status_code == 200
        assert export_json.json()["intake"] is not None
        assert export_json.json()["template_recommendation"] is not None
