from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.coverage import (
    normalize_coverage_payload,
    validate_with_repair as validate_coverage_with_repair,
)
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
from app.observability import (
    configure_logging,
    normalize_request_id,
    reset_request_id,
    sanitize_for_logging,
    set_request_id,
)
from app.nova_runtime import BedrockNovaOrchestrator, NovaRuntimeError
from app.requirements import validate_with_repair as validate_requirements_with_repair
from app.retrieval import chunk_pages, cosine_similarity, embed_text, extract_text_pages

logger = logging.getLogger("nebula.api")


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


def get_nova_orchestrator() -> BedrockNovaOrchestrator:
    return BedrockNovaOrchestrator(settings=settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("application_startup", extra={"event": "application_startup", "environment": settings.app_env})
    init_db()
    Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
    yield
    logger.info("application_shutdown", extra={"event": "application_shutdown"})


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = normalize_request_id(request.headers.get(settings.request_id_header))
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()

        logger.info(
            "request_started",
            extra={
                "event": "request_started",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": sanitize_for_logging(dict(request.query_params)),
                "client_ip": request.client.host if request.client else None,
            },
        )

        try:
            response = await call_next(request)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[settings.request_id_header] = request_id
            logger.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": elapsed_ms,
                },
            )
            return response
        except Exception:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": elapsed_ms,
                },
            )
            raise
        finally:
            reset_request_id(token)

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

        try:
            extracted_payload = get_nova_orchestrator().extract_requirements(chunks)
        except NovaRuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"message": "Nova requirements extraction failed.", "error": str(exc)},
            ) from exc
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
            source="nova-agents-v1",
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
        default_top_k = payload.top_k or settings.retrieval_top_k_default
        ranked_all = rank_chunks_by_query(chunks, payload.section_key, min(20, len(chunks))) if chunks else []
        top_k = default_top_k
        retry_on_missing = False
        if settings.enable_agentic_orchestration_pilot and ranked_all:
            try:
                plan = get_nova_orchestrator().plan_section_generation(
                    section_key=payload.section_key,
                    requested_top_k=default_top_k,
                    available_chunk_count=len(ranked_all),
                )
                top_k = int(plan["retrieval_top_k"])
                retry_on_missing = bool(plan.get("retry_on_missing_evidence", False))
            except (NovaRuntimeError, KeyError, ValueError):
                top_k = default_top_k
        top_k = max(1, min(len(ranked_all), top_k)) if ranked_all else top_k
        ranked_chunks = ranked_all[:top_k] if ranked_all else []
        if ranked_chunks:
            try:
                draft_payload = get_nova_orchestrator().generate_section(payload.section_key, ranked_chunks)
            except NovaRuntimeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail={"message": "Nova draft generation failed.", "error": str(exc)},
                ) from exc
        else:
            draft_payload = build_draft_payload(payload.section_key, ranked_chunks)
        validated, repaired, validation_errors = validate_draft_with_repair(draft_payload)
        if (
            settings.enable_agentic_orchestration_pilot
            and retry_on_missing
            and validated is not None
            and len(validated.missing_evidence) > 0
            and len(ranked_all) > top_k
        ):
            retry_top_k = min(len(ranked_all), top_k + 2)
            retry_chunks = ranked_all[:retry_top_k]
            try:
                retry_payload = get_nova_orchestrator().generate_section(payload.section_key, retry_chunks)
            except NovaRuntimeError:
                retry_payload = None
            if retry_payload is not None:
                retry_validated, retry_repaired, retry_errors = validate_draft_with_repair(retry_payload)
                if retry_validated is not None and len(retry_validated.missing_evidence) < len(validated.missing_evidence):
                    validated = retry_validated
                    repaired = retry_repaired
                    validation_errors = retry_errors
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
            source="nova-agents-v1",
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

        try:
            coverage_payload = get_nova_orchestrator().compute_coverage(
                requirements=requirements_artifact["payload"],
                draft=draft_artifact["payload"],
            )
        except NovaRuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"message": "Nova coverage computation failed.", "error": str(exc)},
            ) from exc
        coverage_payload = normalize_coverage_payload(
            requirements=requirements_artifact["payload"],
            payload=coverage_payload,
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
            source="nova-agents-v1",
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
