from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.coverage import build_coverage_payload, validate_with_repair as validate_coverage_with_repair
from app.db import (
    create_chunks,
    create_coverage_artifact,
    create_document,
    create_draft_artifact,
    create_project,
    create_requirements_artifact,
    get_latest_coverage_artifact,
    get_latest_draft_artifact,
    get_latest_requirements_artifact,
    get_project,
    init_db,
    list_chunks,
    list_documents,
)
from app.drafting import build_draft_payload, validate_with_repair as validate_draft_with_repair
from app.requirements import extract_requirements_payload, validate_with_repair as validate_requirements_with_repair
from app.retrieval import chunk_pages, cosine_similarity, embed_text, extract_text_pages


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


class GenerateSectionRequest(BaseModel):
    section_key: str = Field(..., min_length=1, max_length=120)
    top_k: int | None = Field(default=None, ge=1, le=20)


class CoverageComputeRequest(BaseModel):
    section_key: str = Field(default="Need Statement", min_length=1, max_length=120)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def rank_chunks_by_query(
        chunks: list[dict[str, object]], query: str, top_k: int
    ) -> list[dict[str, object]]:
        query_embedding = embed_text(query, settings.embedding_dim)
        scored_results: list[dict[str, object]] = []
        for chunk in chunks:
            scored_results.append(
                {
                    "chunk_id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "file_name": chunk["file_name"],
                    "page": chunk["page"],
                    "text": chunk["text"],
                    "score": cosine_similarity(query_embedding, chunk["embedding"]),
                }
            )
        scored_results.sort(key=lambda item: float(item["score"]), reverse=True)
        return scored_results[:top_k]

    def render_markdown_export(
        project_id: str,
        requirements_payload: dict[str, object] | None,
        draft_payload: dict[str, object] | None,
        coverage_payload: dict[str, object] | None,
    ) -> str:
        lines = [f"# Nebula Export", "", f"Project ID: `{project_id}`", ""]

        lines.append("## Requirements")
        if requirements_payload:
            lines.append(f"- Funder: {requirements_payload.get('funder') or 'Unknown'}")
            lines.append(f"- Deadline: {requirements_payload.get('deadline') or 'Unknown'}")
            questions = requirements_payload.get("questions", [])
            lines.append(f"- Questions extracted: {len(questions) if isinstance(questions, list) else 0}")
        else:
            lines.append("- No requirements artifact found.")
        lines.append("")

        lines.append("## Draft")
        if draft_payload:
            paragraphs = draft_payload.get("paragraphs", [])
            lines.append(f"- Section: {draft_payload.get('section_key', 'Unknown')}")
            lines.append(f"- Paragraph count: {len(paragraphs) if isinstance(paragraphs, list) else 0}")
        else:
            lines.append("- No draft artifact found.")
        lines.append("")

        lines.append("## Coverage")
        if coverage_payload:
            items = coverage_payload.get("items", [])
            lines.append(f"- Coverage items: {len(items) if isinstance(items, list) else 0}")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    lines.append(
                        f"  - {item.get('requirement_id', 'unknown')}: {item.get('status', 'unknown')} "
                        f"({item.get('notes', '')})"
                    )
        else:
            lines.append("- No coverage artifact found.")
        lines.append("")
        return "\n".join(lines)

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "nebula-backend", "status": "running"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/projects")
    def create_project_endpoint(payload: ProjectCreateRequest) -> dict[str, str]:
        return create_project(payload.name)

    @app.post("/projects/{project_id}/upload")
    async def upload_documents(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        saved_documents: list[dict[str, object]] = []
        project_folder = Path(settings.storage_root) / project_id
        project_folder.mkdir(parents=True, exist_ok=True)

        for upload in files:
            incoming_name = upload.filename or "upload.bin"
            safe_name = Path(incoming_name).name
            content = await upload.read()
            destination = project_folder / f"{uuid4()}_{safe_name}"
            destination.write_bytes(content)

            document = create_document(
                project_id=project_id,
                file_name=safe_name,
                content_type=upload.content_type or "application/octet-stream",
                storage_path=str(destination),
                size_bytes=len(content),
            )
            pages = extract_text_pages(
                content=content,
                content_type=str(document["content_type"]),
                file_name=safe_name,
            )
            chunks = chunk_pages(
                pages=pages,
                chunk_size_chars=settings.chunk_size_chars,
                chunk_overlap_chars=settings.chunk_overlap_chars,
                embedding_dim=settings.embedding_dim,
            )
            create_chunks(
                project_id=project_id,
                document_id=str(document["id"]),
                chunks=[
                    {
                        "chunk_index": chunk.chunk_index,
                        "page": chunk.page,
                        "text": chunk.text,
                        "embedding": chunk.embedding,
                    }
                    for chunk in chunks
                ],
            )
            saved_documents.append(
                {
                    **document,
                    "pages_extracted": len(pages),
                    "chunks_indexed": len(chunks),
                }
            )

        return {"project_id": project_id, "documents": saved_documents}

    @app.get("/projects/{project_id}/documents")
    def list_project_documents(project_id: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"project_id": project_id, "documents": list_documents(project_id)}

    @app.post("/projects/{project_id}/retrieve")
    def retrieve_project_chunks(project_id: str, payload: RetrievalRequest) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        chunks = list_chunks(project_id)
        if not chunks:
            return {"project_id": project_id, "query": payload.query, "results": []}

        top_k = payload.top_k or settings.retrieval_top_k_default
        results = rank_chunks_by_query(chunks, payload.query, top_k)
        return {"project_id": project_id, "query": payload.query, "results": results}

    @app.post("/projects/{project_id}/extract-requirements")
    def extract_requirements(project_id: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        chunks = list_chunks(project_id)
        if not chunks:
            raise HTTPException(
                status_code=400,
                detail="No indexed chunks found. Upload text documents before extracting requirements.",
            )

        extracted_payload = extract_requirements_payload(chunks)
        validated, repaired, validation_errors = validate_requirements_with_repair(extracted_payload)
        if validated is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Requirements extraction failed validation.",
                    "errors": validation_errors,
                },
            )

        artifact_meta = create_requirements_artifact(
            project_id=project_id,
            payload=validated.model_dump(),
            source="heuristic-v1",
        )
        return {
            "project_id": project_id,
            "requirements": validated.model_dump(),
            "artifact": artifact_meta,
            "validation": {
                "repaired": repaired,
                "errors": validation_errors,
            },
        }

    @app.post("/projects/{project_id}/generate-section")
    def generate_section(project_id: str, payload: GenerateSectionRequest) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        chunks = list_chunks(project_id)
        top_k = payload.top_k or settings.retrieval_top_k_default
        ranked_chunks = rank_chunks_by_query(chunks, payload.section_key, top_k) if chunks else []
        draft_payload = build_draft_payload(payload.section_key, ranked_chunks)
        validated, repaired, validation_errors = validate_draft_with_repair(draft_payload)
        if validated is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Draft generation failed validation.",
                    "errors": validation_errors,
                },
            )

        artifact_meta = create_draft_artifact(
            project_id=project_id,
            section_key=payload.section_key,
            payload=validated.model_dump(),
            source="heuristic-v1",
        )
        return {
            "project_id": project_id,
            "draft": validated.model_dump(),
            "artifact": artifact_meta,
            "validation": {
                "repaired": repaired,
                "errors": validation_errors,
            },
        }

    @app.get("/projects/{project_id}/drafts/{section_key}/latest")
    def get_latest_draft(project_id: str, section_key: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        latest = get_latest_draft_artifact(project_id, section_key)
        if latest is None:
            raise HTTPException(status_code=404, detail="No draft artifact found for project/section")

        return {
            "project_id": project_id,
            "section_key": section_key,
            "draft": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    @app.post("/projects/{project_id}/coverage")
    def compute_coverage(project_id: str, payload: CoverageComputeRequest) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        requirements_artifact = get_latest_requirements_artifact(project_id)
        if requirements_artifact is None:
            raise HTTPException(status_code=404, detail="No requirements artifact found for project")

        draft_artifact = get_latest_draft_artifact(project_id, payload.section_key)
        if draft_artifact is None:
            raise HTTPException(status_code=404, detail="No draft artifact found for project/section")

        coverage_payload = build_coverage_payload(
            requirements=requirements_artifact["payload"],
            draft=draft_artifact["payload"],
        )
        validated, repaired, validation_errors = validate_coverage_with_repair(coverage_payload)
        if validated is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Coverage computation failed validation.",
                    "errors": validation_errors,
                },
            )

        artifact_meta = create_coverage_artifact(
            project_id=project_id,
            payload=validated.model_dump(),
            source="heuristic-v1",
        )
        return {
            "project_id": project_id,
            "section_key": payload.section_key,
            "coverage": validated.model_dump(),
            "artifact": artifact_meta,
            "validation": {
                "repaired": repaired,
                "errors": validation_errors,
            },
        }

    @app.get("/projects/{project_id}/coverage/latest")
    def get_latest_coverage(project_id: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        latest = get_latest_coverage_artifact(project_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="No coverage artifact found for project")

        return {
            "project_id": project_id,
            "coverage": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    @app.get("/projects/{project_id}/export")
    def export_project(
        project_id: str,
        format: str = Query(default="json", pattern="^(json|markdown)$"),
        section_key: str = Query(default="Need Statement"),
    ):
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        requirements_artifact = get_latest_requirements_artifact(project_id)
        draft_artifact = get_latest_draft_artifact(project_id, section_key)
        coverage_artifact = get_latest_coverage_artifact(project_id)

        requirements_payload = requirements_artifact["payload"] if requirements_artifact else None
        draft_payload = draft_artifact["payload"] if draft_artifact else None
        coverage_payload = coverage_artifact["payload"] if coverage_artifact else None

        if format == "json":
            return {
                "project_id": project_id,
                "section_key": section_key,
                "requirements": requirements_payload,
                "draft": draft_payload,
                "coverage": coverage_payload,
            }

        markdown = render_markdown_export(
            project_id=project_id,
            requirements_payload=requirements_payload,
            draft_payload=draft_payload,
            coverage_payload=coverage_payload,
        )
        return PlainTextResponse(markdown, media_type="text/markdown")

    @app.get("/projects/{project_id}/requirements/latest")
    def get_latest_requirements(project_id: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        latest = get_latest_requirements_artifact(project_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="No requirements artifact found for project")

        return {
            "project_id": project_id,
            "requirements": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    return app


app = create_app()
