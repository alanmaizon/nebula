from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


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
        assert payload["documents"][0]["chunks_indexed"] >= 1

        list_response = scoped_client.get(f"/projects/{project_id}/documents")
        assert list_response.status_code == 200
        assert len(list_response.json()["documents"]) == 1


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
