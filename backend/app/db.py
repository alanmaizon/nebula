from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.config import settings


def _database_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise RuntimeError("Only sqlite:/// DATABASE_URL is supported in the MVP baseline.")
    return Path(settings.database_url[len(prefix) :])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    db_path = _database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            """
        )


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_database_path())
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_project(name: str) -> dict[str, str]:
    project = {
        "id": str(uuid4()),
        "name": name,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
            (project["id"], project["name"], project["created_at"]),
        )
    return project


def get_project(project_id: str) -> dict[str, str] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, created_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def create_document(
    project_id: str,
    file_name: str,
    content_type: str,
    storage_path: str,
    size_bytes: int,
) -> dict[str, str | int]:
    document = {
        "id": str(uuid4()),
        "project_id": project_id,
        "file_name": file_name,
        "content_type": content_type,
        "storage_path": storage_path,
        "size_bytes": size_bytes,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, project_id, file_name, content_type, storage_path, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document["id"],
                document["project_id"],
                document["file_name"],
                document["content_type"],
                document["storage_path"],
                document["size_bytes"],
                document["created_at"],
            ),
        )
    return document


def list_documents(project_id: str) -> list[dict[str, str | int]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, file_name, content_type, storage_path, size_bytes, created_at
            FROM documents
            WHERE project_id = ?
            ORDER BY created_at ASC
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]

