from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint() -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_create_project_and_upload(tmp_path: Path) -> None:
    settings.database_url = f"sqlite:///{tmp_path}/test.db"
    settings.storage_root = str(tmp_path / "uploads")

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

        list_response = scoped_client.get(f"/projects/{project_id}/documents")
        assert list_response.status_code == 200
        assert len(list_response.json()["documents"]) == 1

