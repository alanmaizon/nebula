from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
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
                upload_batch_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                page INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                embedding_provider TEXT,
                upload_batch_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_project_id ON chunks(project_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_project_document ON chunks(project_id, document_id);

            CREATE TABLE IF NOT EXISTS requirements_artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                upload_batch_id TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE INDEX IF NOT EXISTS idx_requirements_project_id
                ON requirements_artifacts(project_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS draft_artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                section_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                upload_batch_id TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE INDEX IF NOT EXISTS idx_draft_project_section
                ON draft_artifacts(project_id, section_key, created_at DESC);

            CREATE TABLE IF NOT EXISTS coverage_artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                upload_batch_id TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE INDEX IF NOT EXISTS idx_coverage_project_id
                ON coverage_artifacts(project_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS template_recommendation_artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE INDEX IF NOT EXISTS idx_template_reco_project_id
                ON template_recommendation_artifacts(project_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS run_trace_events (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                upload_batch_id TEXT,
                run_id TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                phase TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                UNIQUE(run_id, sequence_no)
            );

            CREATE INDEX IF NOT EXISTS idx_run_trace_events_project_run
                ON run_trace_events(project_id, run_id, sequence_no ASC);
            CREATE INDEX IF NOT EXISTS idx_run_trace_events_project_batch
                ON run_trace_events(project_id, upload_batch_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS judge_eval_artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                upload_batch_id TEXT,
                run_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE INDEX IF NOT EXISTS idx_judge_eval_project_run
                ON judge_eval_artifacts(project_id, run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_judge_eval_project_batch
                ON judge_eval_artifacts(project_id, upload_batch_id, created_at DESC);
            """
        )
        _ensure_column(conn, "documents", "upload_batch_id", "TEXT")
        _ensure_column(conn, "chunks", "upload_batch_id", "TEXT")
        _ensure_column(conn, "chunks", "embedding_provider", "TEXT")
        _ensure_column(conn, "requirements_artifacts", "upload_batch_id", "TEXT")
        _ensure_column(conn, "draft_artifacts", "upload_batch_id", "TEXT")
        _ensure_column(conn, "coverage_artifacts", "upload_batch_id", "TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_project_batch ON documents(project_id, upload_batch_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_project_batch ON chunks(project_id, upload_batch_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_requirements_project_batch ON requirements_artifacts(project_id, upload_batch_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_draft_project_batch_section ON draft_artifacts(project_id, upload_batch_id, section_key, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_coverage_project_batch ON coverage_artifacts(project_id, upload_batch_id, created_at DESC)"
        )

        conn.execute(
            """
            UPDATE documents
            SET upload_batch_id = 'legacy'
            WHERE upload_batch_id IS NULL OR TRIM(upload_batch_id) = ''
            """
        )
        conn.execute(
            """
            UPDATE chunks
            SET upload_batch_id = 'legacy'
            WHERE upload_batch_id IS NULL OR TRIM(upload_batch_id) = ''
            """
        )
        conn.execute(
            """
            UPDATE chunks
            SET embedding_provider = 'hash'
            WHERE embedding_provider IS NULL OR TRIM(embedding_provider) = ''
            """
        )


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_def: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {str(row[1]) for row in rows}
    if column_name in existing_columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


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
    upload_batch_id: str,
) -> dict[str, str | int]:
    document = {
        "id": str(uuid4()),
        "project_id": project_id,
        "file_name": file_name,
        "content_type": content_type,
        "storage_path": storage_path,
        "size_bytes": size_bytes,
        "upload_batch_id": upload_batch_id,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, project_id, file_name, content_type, storage_path, size_bytes, upload_batch_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document["id"],
                document["project_id"],
                document["file_name"],
                document["content_type"],
                document["storage_path"],
                document["size_bytes"],
                document["upload_batch_id"],
                document["created_at"],
            ),
        )
    return document


def list_documents(project_id: str, upload_batch_id: str | None = None) -> list[dict[str, str | int]]:
    query = """
            SELECT id, project_id, file_name, content_type, storage_path, size_bytes, upload_batch_id, created_at
            FROM documents
            WHERE project_id = ?
    """
    params: list[object] = [project_id]
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY created_at ASC"
    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def get_latest_upload_batch_id(project_id: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT upload_batch_id
            FROM documents
            WHERE project_id = ? AND upload_batch_id IS NOT NULL AND TRIM(upload_batch_id) <> ''
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    value = str(row["upload_batch_id"]).strip()
    return value or None


def upload_batch_exists(project_id: str, upload_batch_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM documents
            WHERE project_id = ? AND upload_batch_id = ?
            LIMIT 1
            """,
            (project_id, upload_batch_id),
        ).fetchone()
    return row is not None


def create_chunks(
    project_id: str,
    document_id: str,
    chunks: list[dict[str, object]],
    upload_batch_id: str,
) -> list[dict[str, object]]:
    now = _utc_now_iso()
    rows: list[dict[str, object]] = []
    for chunk in chunks:
        rows.append(
            {
                "id": str(uuid4()),
                "project_id": project_id,
                "document_id": document_id,
                "chunk_index": int(chunk["chunk_index"]),
                "page": int(chunk["page"]),
                "text": str(chunk["text"]),
                "embedding_json": json.dumps(chunk["embedding"]),
                "embedding_provider": str(chunk.get("embedding_provider") or "hash"),
                "upload_batch_id": upload_batch_id,
                "created_at": now,
            }
        )

    if not rows:
        return []

    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO chunks (
                id, project_id, document_id, chunk_index, page, text, embedding_json, embedding_provider, upload_batch_id, created_at
            )
            VALUES (
                :id, :project_id, :document_id, :chunk_index, :page, :text, :embedding_json, :embedding_provider, :upload_batch_id, :created_at
            )
            """,
            rows,
        )
    return rows


def list_chunks(project_id: str, upload_batch_id: str | None = None) -> list[dict[str, object]]:
    query = """
            SELECT
                c.id,
                c.project_id,
                c.document_id,
                d.file_name,
                c.chunk_index,
                c.page,
                c.text,
                c.embedding_json,
                c.embedding_provider,
                c.upload_batch_id,
                c.created_at
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.project_id = ?
    """
    params: list[object] = [project_id]
    if upload_batch_id is not None:
        query += " AND d.upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY c.chunk_index ASC"
    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    parsed: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["embedding"] = json.loads(item.pop("embedding_json"))
        parsed.append(item)
    return parsed


def delete_chunks(project_id: str, upload_batch_id: str | None = None) -> int:
    with get_conn() as conn:
        if upload_batch_id is None:
            cursor = conn.execute("DELETE FROM chunks WHERE project_id = ?", (project_id,))
        else:
            cursor = conn.execute(
                "DELETE FROM chunks WHERE project_id = ? AND upload_batch_id = ?",
                (project_id, upload_batch_id),
            )
    return int(cursor.rowcount if cursor.rowcount is not None else 0)


def create_requirements_artifact(
    project_id: str,
    payload: dict[str, object],
    source: str,
    upload_batch_id: str | None = None,
) -> dict[str, object]:
    artifact = {
        "id": str(uuid4()),
        "project_id": project_id,
        "payload_json": json.dumps(payload),
        "upload_batch_id": upload_batch_id,
        "source": source,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO requirements_artifacts (id, project_id, payload_json, upload_batch_id, source, created_at)
            VALUES (:id, :project_id, :payload_json, :upload_batch_id, :source, :created_at)
            """,
            artifact,
        )
    return {
        "id": artifact["id"],
        "project_id": artifact["project_id"],
        "upload_batch_id": artifact["upload_batch_id"],
        "source": artifact["source"],
        "created_at": artifact["created_at"],
    }


def get_latest_requirements_artifact(project_id: str, upload_batch_id: str | None = None) -> dict[str, object] | None:
    query = """
            SELECT id, project_id, payload_json, upload_batch_id, source, created_at
            FROM requirements_artifacts
            WHERE project_id = ?
    """
    params: list[object] = [project_id]
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY created_at DESC LIMIT 1"
    with get_conn() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    parsed = dict(row)
    parsed["payload"] = json.loads(parsed.pop("payload_json"))
    return parsed


def create_draft_artifact(
    project_id: str,
    section_key: str,
    payload: dict[str, object],
    source: str,
    upload_batch_id: str | None = None,
) -> dict[str, object]:
    artifact = {
        "id": str(uuid4()),
        "project_id": project_id,
        "section_key": section_key,
        "payload_json": json.dumps(payload),
        "upload_batch_id": upload_batch_id,
        "source": source,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO draft_artifacts (id, project_id, section_key, payload_json, upload_batch_id, source, created_at)
            VALUES (:id, :project_id, :section_key, :payload_json, :upload_batch_id, :source, :created_at)
            """,
            artifact,
        )
    return {
        "id": artifact["id"],
        "project_id": artifact["project_id"],
        "section_key": artifact["section_key"],
        "upload_batch_id": artifact["upload_batch_id"],
        "source": artifact["source"],
        "created_at": artifact["created_at"],
    }


def get_latest_draft_artifact(
    project_id: str,
    section_key: str,
    upload_batch_id: str | None = None,
) -> dict[str, object] | None:
    query = """
            SELECT id, project_id, section_key, payload_json, upload_batch_id, source, created_at
            FROM draft_artifacts
            WHERE project_id = ? AND section_key = ?
    """
    params: list[object] = [project_id, section_key]
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY created_at DESC LIMIT 1"
    with get_conn() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    parsed = dict(row)
    parsed["payload"] = json.loads(parsed.pop("payload_json"))
    return parsed


def list_latest_draft_artifacts(project_id: str, upload_batch_id: str | None = None) -> list[dict[str, object]]:
    subquery = """
                SELECT section_key, MAX(created_at) AS max_created_at
                FROM draft_artifacts
                WHERE project_id = ?
    """
    sub_params: list[object] = [project_id]
    if upload_batch_id is not None:
        subquery += " AND upload_batch_id = ?"
        sub_params.append(upload_batch_id)
    subquery += " GROUP BY section_key"

    query = f"""
            SELECT d.id, d.project_id, d.section_key, d.payload_json, d.upload_batch_id, d.source, d.created_at
            FROM draft_artifacts d
            JOIN (
                {subquery}
            ) latest
                ON latest.section_key = d.section_key
                AND latest.max_created_at = d.created_at
            WHERE d.project_id = ?
    """
    params: list[object] = [*sub_params, project_id]
    if upload_batch_id is not None:
        query += " AND d.upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY d.section_key COLLATE NOCASE ASC"
    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        parsed = dict(row)
        parsed["payload"] = json.loads(parsed.pop("payload_json"))
        parsed_rows.append(parsed)
    return parsed_rows


def create_coverage_artifact(
    project_id: str,
    payload: dict[str, object],
    source: str,
    upload_batch_id: str | None = None,
) -> dict[str, object]:
    artifact = {
        "id": str(uuid4()),
        "project_id": project_id,
        "payload_json": json.dumps(payload),
        "upload_batch_id": upload_batch_id,
        "source": source,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO coverage_artifacts (id, project_id, payload_json, upload_batch_id, source, created_at)
            VALUES (:id, :project_id, :payload_json, :upload_batch_id, :source, :created_at)
            """,
            artifact,
        )
    return {
        "id": artifact["id"],
        "project_id": artifact["project_id"],
        "upload_batch_id": artifact["upload_batch_id"],
        "source": artifact["source"],
        "created_at": artifact["created_at"],
    }


def get_latest_coverage_artifact(project_id: str, upload_batch_id: str | None = None) -> dict[str, object] | None:
    query = """
            SELECT id, project_id, payload_json, upload_batch_id, source, created_at
            FROM coverage_artifacts
            WHERE project_id = ?
    """
    params: list[object] = [project_id]
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY created_at DESC LIMIT 1"
    with get_conn() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    parsed = dict(row)
    parsed["payload"] = json.loads(parsed.pop("payload_json"))
    return parsed


def create_template_recommendation_artifact(
    project_id: str,
    payload: dict[str, object],
    source: str,
) -> dict[str, object]:
    artifact = {
        "id": str(uuid4()),
        "project_id": project_id,
        "payload_json": json.dumps(payload),
        "source": source,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO template_recommendation_artifacts (id, project_id, payload_json, source, created_at)
            VALUES (:id, :project_id, :payload_json, :source, :created_at)
            """,
            artifact,
        )
    return {
        "id": artifact["id"],
        "project_id": artifact["project_id"],
        "source": artifact["source"],
        "created_at": artifact["created_at"],
    }


def get_latest_template_recommendation_artifact(project_id: str) -> dict[str, object] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, payload_json, source, created_at
            FROM template_recommendation_artifacts
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    parsed = dict(row)
    parsed["payload"] = json.loads(parsed.pop("payload_json"))
    return parsed


def create_run_trace_event(
    *,
    project_id: str,
    run_id: str,
    sequence_no: int,
    phase: str,
    event_type: str,
    payload: dict[str, object],
    upload_batch_id: str | None = None,
    payload_sha256: str | None = None,
) -> dict[str, object]:
    payload_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    checksum = payload_sha256 or hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    row = {
        "id": str(uuid4()),
        "project_id": project_id,
        "upload_batch_id": upload_batch_id,
        "run_id": run_id,
        "sequence_no": sequence_no,
        "phase": phase,
        "event_type": event_type,
        "payload_json": payload_json,
        "payload_sha256": checksum,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO run_trace_events (
                id,
                project_id,
                upload_batch_id,
                run_id,
                sequence_no,
                phase,
                event_type,
                payload_json,
                payload_sha256,
                created_at
            )
            VALUES (
                :id,
                :project_id,
                :upload_batch_id,
                :run_id,
                :sequence_no,
                :phase,
                :event_type,
                :payload_json,
                :payload_sha256,
                :created_at
            )
            """,
            row,
        )

    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "upload_batch_id": row["upload_batch_id"],
        "run_id": row["run_id"],
        "sequence_no": row["sequence_no"],
        "phase": row["phase"],
        "event_type": row["event_type"],
        "payload_sha256": row["payload_sha256"],
        "created_at": row["created_at"],
    }


def list_run_trace_events(
    project_id: str,
    run_id: str,
    *,
    upload_batch_id: str | None = None,
) -> list[dict[str, object]]:
    query = """
            SELECT
                id,
                project_id,
                upload_batch_id,
                run_id,
                sequence_no,
                phase,
                event_type,
                payload_json,
                payload_sha256,
                created_at
            FROM run_trace_events
            WHERE project_id = ? AND run_id = ?
    """
    params: list[object] = [project_id, run_id]
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY sequence_no ASC, created_at ASC"

    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        parsed = dict(row)
        parsed["payload"] = json.loads(parsed.pop("payload_json"))
        parsed_rows.append(parsed)
    return parsed_rows


def get_latest_run_id(project_id: str, *, upload_batch_id: str | None = None) -> str | None:
    query = """
            SELECT run_id
            FROM run_trace_events
            WHERE project_id = ?
    """
    params: list[object] = [project_id]
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY created_at DESC LIMIT 1"

    with get_conn() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    value = str(row["run_id"]).strip()
    return value or None


def create_judge_eval_artifact(
    *,
    project_id: str,
    run_id: str,
    payload: dict[str, object],
    source: str,
    upload_batch_id: str | None = None,
) -> dict[str, object]:
    artifact = {
        "id": str(uuid4()),
        "project_id": project_id,
        "upload_batch_id": upload_batch_id,
        "run_id": run_id,
        "payload_json": json.dumps(payload, ensure_ascii=True),
        "source": source,
        "created_at": _utc_now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO judge_eval_artifacts (id, project_id, upload_batch_id, run_id, payload_json, source, created_at)
            VALUES (:id, :project_id, :upload_batch_id, :run_id, :payload_json, :source, :created_at)
            """,
            artifact,
        )
    return {
        "id": artifact["id"],
        "project_id": artifact["project_id"],
        "upload_batch_id": artifact["upload_batch_id"],
        "run_id": artifact["run_id"],
        "source": artifact["source"],
        "created_at": artifact["created_at"],
    }


def list_judge_eval_artifacts(
    project_id: str,
    *,
    run_id: str | None = None,
    upload_batch_id: str | None = None,
) -> list[dict[str, object]]:
    query = """
            SELECT
                id,
                project_id,
                upload_batch_id,
                run_id,
                payload_json,
                source,
                created_at
            FROM judge_eval_artifacts
            WHERE project_id = ?
    """
    params: list[object] = [project_id]
    if run_id is not None:
        query += " AND run_id = ?"
        params.append(run_id)
    if upload_batch_id is not None:
        query += " AND upload_batch_id = ?"
        params.append(upload_batch_id)
    query += " ORDER BY created_at DESC"

    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        parsed = dict(row)
        parsed["payload"] = json.loads(parsed.pop("payload_json"))
        parsed_rows.append(parsed)
    return parsed_rows
