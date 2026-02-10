from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import re
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
    create_intake_artifact,
    create_project,
    create_requirements_artifact,
    get_latest_coverage_artifact,
    get_latest_draft_artifact,
    get_latest_intake_artifact,
    get_latest_requirements_artifact,
    get_latest_upload_batch_id,
    get_project,
    init_db,
    list_latest_draft_artifacts,
    list_chunks,
    list_documents,
    upload_batch_exists,
)
from app.drafting import (
    build_draft_payload,
    ground_draft_payload,
    normalize_draft_section_key,
    validate_with_repair as validate_draft_with_repair,
)
from app.export import ExportCompositionError, compose_markdown_report
from app.export.policy import derive_section_title_from_prompt
from app.intake import IntakePayload, build_intake_context
from app.observability import (
    configure_logging,
    normalize_request_id,
    reset_request_id,
    sanitize_for_logging,
    set_request_id,
)
from app.nova_runtime import BedrockNovaOrchestrator, NovaRuntimeError
from app.export_bundle import EXPORT_VERSION, build_export_bundle, combine_markdown_files
from app.requirements import validate_with_repair as validate_requirements_with_repair
from app.requirements import extract_requirements_payload, merge_requirements_payload
from app.retrieval import build_parse_report, chunk_pages, cosine_similarity, embed_text, extract_text_pages

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


class GenerateFullDraftRequest(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    max_revision_rounds: int = Field(default=1, ge=0, le=3)


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

    def select_requirement_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
        pattern = re.compile(r"(rfp|grant|funding|guideline|solicitation|notice)", re.IGNORECASE)
        preferred: list[dict[str, object]] = []
        for chunk in chunks:
            file_name = chunk.get("file_name")
            if isinstance(file_name, str) and pattern.search(file_name):
                preferred.append(chunk)
        return preferred or chunks

    def dedupe_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            key = value.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def parse_requested_sections(sections_csv: str | None, section_key: str | None) -> list[str]:
        requested: list[str] = []
        if sections_csv:
            requested.extend(part.strip() for part in sections_csv.split(",") if part.strip())
        if section_key:
            requested.append(section_key.strip())
        return dedupe_strings(requested)

    def resolve_upload_batch_scope(
        *,
        project_id: str,
        document_scope: str,
        upload_batch_id: str | None,
    ) -> str | None:
        if upload_batch_id:
            batch_value = upload_batch_id.strip()
            if not batch_value:
                return None
            if not upload_batch_exists(project_id, batch_value):
                raise HTTPException(status_code=404, detail="Requested upload batch not found for project")
            return batch_value

        if document_scope == "all":
            return None

        latest_batch_id = get_latest_upload_batch_id(project_id)
        return latest_batch_id

    def select_primary_rfp_document(chunks: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
        docs: dict[str, dict[str, object]] = {}
        for chunk in chunks:
            doc_id = str(chunk.get("document_id") or "").strip()
            file_name = str(chunk.get("file_name") or "").strip()
            text = str(chunk.get("text") or "")
            if not doc_id:
                continue
            current = docs.get(doc_id)
            if current is None:
                current = {"document_id": doc_id, "file_name": file_name, "texts": []}
                docs[doc_id] = current
            current["texts"].append(text)

        if not docs:
            return chunks, {"selected_document_id": None, "selected_file_name": None, "ambiguous": False, "candidates": []}

        scored: list[tuple[int, dict[str, object]]] = []
        for doc in docs.values():
            file_name = str(doc.get("file_name") or "")
            texts = doc.get("texts")
            joined = "\n".join(texts if isinstance(texts, list) else [])
            lowered_name = file_name.lower()
            lowered_text = joined.lower()
            score = 0

            if re.search(r"(rfp|solicitation|notice|guideline|grant|opportunity)", lowered_name):
                score += 6
            if "funding opportunity" in lowered_text:
                score += 3
            if re.search(r"(required narrative questions|questions?:)", lowered_text):
                score += 3
            if re.search(r"(scoring rubric|rubric|scoring criteria)", lowered_text):
                score += 2
            if re.search(r"(required attachments?|submission requirements?)", lowered_text):
                score += 2
            if re.search(r"(disallowed costs?|restrictions?|ineligible costs?)", lowered_text):
                score += 2
            if re.search(r"\b(deadline|due date)\b", lowered_text):
                score += 1

            scored.append((score, doc))

        scored.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("file_name") or "").lower(),
            ),
            reverse=True,
        )
        best_score = scored[0][0]
        candidates = [doc for score, doc in scored if score == best_score and score > 0]

        if best_score <= 0:
            return chunks, {"selected_document_id": None, "selected_file_name": None, "ambiguous": False, "candidates": []}

        selected = candidates[0]
        selected_document_id = str(selected.get("document_id") or "")
        selected_file_name = str(selected.get("file_name") or "")
        selected_chunks = [chunk for chunk in chunks if str(chunk.get("document_id") or "") == selected_document_id]
        metadata = {
            "selected_document_id": selected_document_id,
            "selected_file_name": selected_file_name,
            "ambiguous": len(candidates) > 1,
            "candidates": [
                {
                    "document_id": str(doc.get("document_id") or ""),
                    "file_name": str(doc.get("file_name") or ""),
                    "score": best_score,
                }
                for doc in candidates
            ],
        }
        return selected_chunks, metadata

    def build_section_targets_from_requirements(requirements_payload: dict[str, object]) -> list[dict[str, str]]:
        questions = requirements_payload.get("questions")
        if not isinstance(questions, list):
            return [{"requirement_id": "Q1", "prompt": "Need Statement", "section_key": "Need Statement"}]

        targets: list[dict[str, str]] = []
        seen_section_keys: dict[str, int] = {}
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            prompt = str(question.get("prompt") or "").strip()
            if not prompt:
                continue
            requirement_id = str(question.get("id") or f"Q{index}").strip() or f"Q{index}"
            base_section_key = derive_section_title_from_prompt(prompt).strip() or f"Section {index}"
            count = seen_section_keys.get(base_section_key, 0) + 1
            seen_section_keys[base_section_key] = count
            if count == 1:
                section_key = base_section_key
            else:
                section_key = f"{base_section_key} {count}"
            section_key = section_key[:120].strip() or f"Section {index}"
            targets.append(
                {
                    "requirement_id": requirement_id,
                    "prompt": prompt,
                    "section_key": section_key,
                }
            )

        return targets or [{"requirement_id": "Q1", "prompt": "Need Statement", "section_key": "Need Statement"}]

    def run_requirements_extraction_for_batch(
        *,
        project_id: str,
        selected_batch_id: str | None,
    ) -> dict[str, object]:
        chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
        if not chunks:
            raise HTTPException(
                status_code=400,
                detail="No indexed chunks found. Upload text documents before extracting requirements.",
            )

        requirement_candidates = select_requirement_chunks(chunks)
        requirement_chunks, rfp_selection = select_primary_rfp_document(requirement_candidates)
        deterministic_payload = extract_requirements_payload(requirement_chunks)
        extracted_payload = deterministic_payload
        extraction_mode = "deterministic-only"
        nova_error: str | None = None
        nova_question_count = 0
        try:
            nova_payload = get_nova_orchestrator().extract_requirements(requirement_chunks)
            nova_question_count = len(nova_payload.get("questions", [])) if isinstance(nova_payload, dict) else 0
            if isinstance(nova_payload, dict):
                extracted_payload = merge_requirements_payload(deterministic_payload, nova_payload)
                extraction_mode = "deterministic+nova"
        except NovaRuntimeError as exc:
            nova_error = str(exc)

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
            upload_batch_id=selected_batch_id,
        )
        return {
            "requirements": validated.model_dump(),
            "artifact": artifact_meta,
            "validation": {
                "repaired": repaired,
                "errors": validation_errors,
            },
            "extraction": {
                "mode": extraction_mode,
                "chunks_total": len(chunks),
                "chunks_considered": len(requirement_chunks),
                "deterministic_question_count": len(deterministic_payload.get("questions", [])),
                "nova_question_count": nova_question_count,
                "nova_error": nova_error,
                "rfp_selection": rfp_selection,
            },
            "chunks": chunks,
        }

    def compute_validated_coverage_payload(
        *,
        requirements_payload: dict[str, object],
        draft_payload: dict[str, object],
    ) -> tuple[dict[str, object], bool, list[str]]:
        try:
            coverage_payload = get_nova_orchestrator().compute_coverage(
                requirements=requirements_payload,
                draft=draft_payload,
            )
        except NovaRuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"message": "Nova coverage computation failed.", "error": str(exc)},
            ) from exc
        coverage_payload = normalize_coverage_payload(
            requirements=requirements_payload,
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
        return validated.model_dump(), repaired, validation_errors

    def generate_validated_section_draft(
        *,
        project_id: str,
        selected_batch_id: str | None,
        section_key: str,
        query_text: str,
        requested_top_k: int | None,
        max_revision_rounds: int,
        force_retry: bool,
    ) -> dict[str, object]:
        chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
        intake_context: dict[str, str] | None = None
        latest_intake = get_latest_intake_artifact(project_id)
        if latest_intake is not None and isinstance(latest_intake.get("payload"), dict):
            intake_payload = IntakePayload.model_validate(latest_intake["payload"])
            intake_context = build_intake_context(intake_payload)

        default_top_k = requested_top_k or settings.retrieval_top_k_default
        ranked_all = rank_chunks_by_query(chunks, query_text, min(20, len(chunks))) if chunks else []

        top_k = default_top_k
        retry_on_missing = False
        if settings.enable_agentic_orchestration_pilot and ranked_all:
            try:
                plan = get_nova_orchestrator().plan_section_generation(
                    section_key=section_key,
                    requested_top_k=default_top_k,
                    available_chunk_count=len(ranked_all),
                )
                top_k = int(plan["retrieval_top_k"])
                retry_on_missing = bool(plan.get("retry_on_missing_evidence", False))
            except (NovaRuntimeError, KeyError, TypeError, ValueError):
                top_k = default_top_k

        if ranked_all:
            top_k = max(1, min(len(ranked_all), top_k))
        else:
            top_k = max(1, top_k)

        retries_allowed = max_revision_rounds if force_retry else 0
        if not force_retry and settings.enable_agentic_orchestration_pilot and retry_on_missing:
            retries_allowed = max(retries_allowed, 1)
        if not force_retry and not settings.enable_agentic_orchestration_pilot:
            retries_allowed = 0

        best_result: dict[str, object] | None = None
        attempts = 0
        current_top_k = top_k

        while True:
            attempts += 1
            ranked_chunks = ranked_all[:current_top_k] if ranked_all else []
            if ranked_chunks:
                try:
                    draft_payload = get_nova_orchestrator().generate_section(
                        section_key,
                        ranked_chunks,
                        intake_context=intake_context,
                    )
                except NovaRuntimeError as exc:
                    raise HTTPException(
                        status_code=502,
                        detail={"message": "Nova draft generation failed.", "error": str(exc)},
                    ) from exc
            else:
                draft_payload = build_draft_payload(section_key, ranked_chunks)

            if isinstance(draft_payload, dict):
                draft_payload = normalize_draft_section_key(draft_payload, section_key)
            draft_payload, grounding_stats = ground_draft_payload(draft_payload, ranked_chunks)
            validated, repaired, validation_errors = validate_draft_with_repair(draft_payload)
            if validated is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Draft generation failed validation.",
                        "errors": validation_errors,
                    },
                )

            missing_count = len(validated.missing_evidence)
            if best_result is None or missing_count < int(best_result["missing_count"]):
                best_result = {
                    "draft": validated.model_dump(),
                    "validation": {
                        "repaired": repaired,
                        "errors": validation_errors,
                    },
                    "grounding": grounding_stats,
                    "retrieval": ranked_chunks,
                    "top_k_used": current_top_k,
                    "missing_count": missing_count,
                }

            can_retry = (
                attempts <= retries_allowed
                and missing_count > 0
                and bool(ranked_all)
                and current_top_k < len(ranked_all)
            )
            if not can_retry:
                break
            current_top_k = min(len(ranked_all), current_top_k + 2)

        if best_result is None:
            raise HTTPException(
                status_code=422,
                detail={"message": "Draft generation failed validation.", "errors": ["Unable to produce draft payload."]},
            )
        return {
            **best_result,
            "attempts": attempts,
        }

    def build_export_documents(
        project_id: str,
        documents: list[dict[str, object]],
        upload_batch_id: str | None = None,
    ) -> list[dict[str, object]]:
        chunks = list_chunks(project_id, upload_batch_id=upload_batch_id)
        pages_by_doc: dict[str, set[int]] = {}
        for chunk in chunks:
            document_id = str(chunk.get("document_id", "")).strip()
            page = chunk.get("page")
            if not document_id or not isinstance(page, int):
                continue
            pages_by_doc.setdefault(document_id, set()).add(page)

        exported: list[dict[str, object]] = []
        for document in documents:
            doc_id = str(document.get("id", "")).strip()
            file_name = str(document.get("file_name", "")).strip()
            pages = pages_by_doc.get(doc_id, set())
            page_count = len(pages)
            exported.append(
                {
                    **document,
                    "doc_id": file_name or doc_id,
                    "page_count": page_count if page_count > 0 else None,
                    "parsed_status": "parsed" if page_count > 0 else "unknown",
                }
            )
        return exported

    def looks_like_export_bundle(
        payload: object,
        *,
        require_json_bundle: bool,
        require_markdown_bundle: bool,
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        required = {"export_version", "generated_at", "project", "bundle", "summary", "quality_gates", "provenance"}
        if not required.issubset(payload.keys()):
            return False
        if payload.get("export_version") != EXPORT_VERSION:
            return False
        bundle = payload.get("bundle")
        if not isinstance(bundle, dict):
            return False
        if require_json_bundle and bundle.get("json") is None:
            return False
        if require_markdown_bundle:
            markdown = bundle.get("markdown")
            if not isinstance(markdown, dict):
                return False
            files = markdown.get("files")
            if not isinstance(files, list):
                return False
        return True

    def extract_markdown_files(payload: object) -> list[dict[str, str]]:
        if not isinstance(payload, dict):
            return []
        bundle = payload.get("bundle")
        if not isinstance(bundle, dict):
            return []
        markdown = bundle.get("markdown")
        if not isinstance(markdown, dict):
            return []
        files = markdown.get("files")
        if not isinstance(files, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            content = str(item.get("content") or "")
            if not path or not content:
                continue
            normalized.append({"path": path, "content": content})
        return normalized

    def append_export_warning(export_bundle: object, message: str) -> None:
        if not isinstance(export_bundle, dict):
            return
        quality_gates = export_bundle.get("quality_gates")
        if not isinstance(quality_gates, dict):
            return
        warnings = quality_gates.get("warnings")
        if isinstance(warnings, list):
            warnings.append(message)

    def sanitize_relative_export_path(path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return Path(candidate.name or "export.md")
        cleaned_parts: list[str] = []
        for part in candidate.parts:
            if not part or part in {".", os.sep}:
                continue
            if part == "..":
                continue
            cleaned_parts.append(part)
        safe = Path(*cleaned_parts) if cleaned_parts else Path("export.md")
        if safe.name in {"", ".", ".."}:
            return Path("export.md")
        return safe

    def write_markdown_export_files(project_id: str, markdown_files: list[dict[str, str]]) -> list[str]:
        if not markdown_files:
            return []

        exports_root = Path(settings.storage_root).parent / "exports" / project_id
        exports_root.mkdir(parents=True, exist_ok=True)
        written_files: list[str] = []

        for item in markdown_files:
            raw_path = str(item.get("path") or "").strip()
            content = str(item.get("content") or "")
            if not raw_path or not content:
                continue
            relative_path = sanitize_relative_export_path(raw_path)
            destination = exports_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            written_files.append(str(relative_path))

        return written_files

    def assemble_export_bundle_for_project(
        *,
        request: Request,
        project_id: str,
        project: dict[str, object],
        selected_batch_id: str | None,
        requested_sections: list[str],
        profile: str,
        include_debug: bool,
        output_filename_base: str | None,
        use_agent: bool,
    ) -> dict[str, object]:
        requirements_artifact = get_latest_requirements_artifact(project_id, upload_batch_id=selected_batch_id)
        draft_artifacts = list_latest_draft_artifacts(project_id, upload_batch_id=selected_batch_id)
        coverage_artifact = get_latest_coverage_artifact(project_id, upload_batch_id=selected_batch_id)
        intake_artifact = get_latest_intake_artifact(project_id)
        documents = list_documents(project_id, upload_batch_id=selected_batch_id)

        drafts: dict[str, dict[str, object]] = {}
        artifacts_used: list[dict[str, object]] = []
        artifact_timestamps: list[str] = []
        for artifact in draft_artifacts:
            section_name = str(artifact.get("section_key", "")).strip()
            if requested_sections and section_name not in requested_sections:
                continue
            drafts[section_name] = {
                "draft": artifact["payload"],
                "artifact": {
                    "id": artifact["id"],
                    "source": artifact["source"],
                    "updated_at": artifact["created_at"],
                },
            }
            artifacts_used.append(
                {
                    "type": "draft",
                    "id": artifact["id"],
                    "updated_at": artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(artifact["created_at"]))

        requirements_payload = requirements_artifact["payload"] if requirements_artifact else None
        coverage_payload = coverage_artifact["payload"] if coverage_artifact else None
        intake_payload = intake_artifact["payload"] if intake_artifact else None
        documents_payload = build_export_documents(project_id, documents, upload_batch_id=selected_batch_id)

        if requirements_artifact:
            artifacts_used.append(
                {
                    "type": "requirements",
                    "id": requirements_artifact["id"],
                    "updated_at": requirements_artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(requirements_artifact["created_at"]))
        if coverage_artifact:
            artifacts_used.append(
                {
                    "type": "coverage",
                    "id": coverage_artifact["id"],
                    "updated_at": coverage_artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(coverage_artifact["created_at"]))
        if intake_artifact:
            artifacts_used.append(
                {
                    "type": "intake",
                    "id": intake_artifact["id"],
                    "updated_at": intake_artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(intake_artifact["created_at"]))

        project_updated_at = project.get("created_at")
        if artifact_timestamps:
            project_updated_at = max([str(project.get("created_at", "")), *artifact_timestamps])

        validations: dict[str, object] = {
            "requirements": {"present": requirements_payload is not None},
            "drafts": {"sections": len(drafts)},
            "coverage": {"present": coverage_payload is not None},
        }

        missing_evidence: list[dict[str, object]] = []
        for section_name, entry in drafts.items():
            payload = entry.get("draft")
            if not isinstance(payload, dict):
                continue
            items = payload.get("missing_evidence")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    missing_evidence.append(
                        {
                            **item,
                            "affected_sections": [section_name],
                        }
                    )

        source_selection: dict[str, object] = {
            "selected_document_id": None,
            "selected_file_name": None,
            "ambiguous": False,
            "candidates": [],
        }
        requirement_chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
        if requirement_chunks:
            _, source_selection = select_primary_rfp_document(select_requirement_chunks(requirement_chunks))

        export_input = {
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
                "created_at": project.get("created_at"),
                "updated_at": project_updated_at,
            },
            "export_request": {
                "format": "both",
                "profile": profile,
                "include_debug": include_debug,
                "sections": requested_sections or None,
                "output_filename_base": output_filename_base,
                "upload_batch_id": selected_batch_id,
            },
            "intake": intake_payload,
            "documents": documents_payload,
            "requirements": requirements_payload,
            "drafts": drafts,
            "coverage": coverage_payload,
            "validations": validations,
            "missing_evidence": missing_evidence,
            "source_selection": source_selection,
            "run_metadata": {
                "model_ids": {
                    "primary": settings.bedrock_model_id,
                    "lite": settings.bedrock_lite_model_id,
                },
                "temperatures": {"agent_temperature": settings.agent_temperature},
                "max_tokens": settings.agent_max_tokens,
                "retrieval_top_k": settings.retrieval_top_k_default,
                "chunking": {
                    "chunk_size_chars": settings.chunk_size_chars,
                    "chunk_overlap_chars": settings.chunk_overlap_chars,
                },
                "request_ids": [getattr(request.state, "request_id", None)],
            },
            "artifacts_used": artifacts_used,
        }

        export_bundle = build_export_bundle(export_input)

        if use_agent:
            orchestrator = get_nova_orchestrator()
            package_export_bundle = getattr(orchestrator, "package_export_bundle", None)
            if callable(package_export_bundle):
                try:
                    candidate_bundle = package_export_bundle(export_input)
                    if looks_like_export_bundle(
                        candidate_bundle,
                        require_json_bundle=True,
                        require_markdown_bundle=True,
                    ):
                        export_bundle = candidate_bundle
                    else:
                        append_export_warning(
                            export_bundle,
                            "Fell back to deterministic export: model output schema invalid.",
                        )
                except Exception as exc:  # pragma: no cover - depends on runtime integration
                    append_export_warning(
                        export_bundle,
                        f"Fell back to deterministic export: final-stage agent unavailable ({exc}).",
                    )

        markdown_files = extract_markdown_files(export_bundle)
        try:
            written_files = write_markdown_export_files(project_id, markdown_files)
            logger.info(
                "export_files_written",
                extra={
                    "event": "export_files_written",
                    "request_id": getattr(request.state, "request_id", None),
                    "project_id": project_id,
                    "files_written": len(written_files),
                },
            )
            if markdown_files and not written_files:
                append_export_warning(
                    export_bundle,
                    "Markdown bundle existed but no files were written to disk.",
                )
        except OSError as exc:
            append_export_warning(
                export_bundle,
                f"Automatic markdown file write failed: {exc}",
            )

        return export_bundle

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

        upload_batch_id = str(uuid4())
        saved_documents: list[dict[str, object]] = []
        quality_counts: dict[str, int] = {"good": 0, "low": 0, "none": 0}
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
                upload_batch_id=upload_batch_id,
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
            parse_report = build_parse_report(
                content=content,
                content_type=str(document["content_type"]),
                file_name=safe_name,
                pages=pages,
                chunks=chunks,
            )
            quality = str(parse_report.get("quality", "none"))
            if quality not in quality_counts:
                quality = "none"
            quality_counts[quality] += 1
            create_chunks(
                project_id=project_id,
                document_id=str(document["id"]),
                upload_batch_id=upload_batch_id,
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
                    "parse_report": parse_report,
                }
            )

        return {
            "project_id": project_id,
            "upload_batch_id": upload_batch_id,
            "documents": saved_documents,
            "parse_report": {
                "documents_total": len(saved_documents),
                "quality_counts": quality_counts,
            },
        }

    @app.get("/projects/{project_id}/documents")
    def list_project_documents(
        project_id: str,
        document_scope: str = Query(default="all", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "documents": list_documents(project_id, upload_batch_id=selected_batch_id),
        }

    @app.post("/projects/{project_id}/intake")
    def save_intake(project_id: str, payload: IntakePayload) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        artifact_meta = create_intake_artifact(
            project_id=project_id,
            payload=payload.model_dump(),
            source="ui-intake-v1",
        )
        return {
            "project_id": project_id,
            "intake": payload.model_dump(),
            "artifact": artifact_meta,
        }

    @app.get("/projects/{project_id}/intake")
    def get_latest_intake(project_id: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        latest = get_latest_intake_artifact(project_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="No intake artifact found for project")

        return {
            "project_id": project_id,
            "intake": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    @app.post("/projects/{project_id}/retrieve")
    def retrieve_project_chunks(
        project_id: str,
        payload: RetrievalRequest,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
        if not chunks:
            return {"project_id": project_id, "upload_batch_id": selected_batch_id, "query": payload.query, "results": []}

        top_k = payload.top_k or settings.retrieval_top_k_default
        results = rank_chunks_by_query(chunks, payload.query, top_k)
        return {"project_id": project_id, "upload_batch_id": selected_batch_id, "query": payload.query, "results": results}

    @app.post("/projects/{project_id}/extract-requirements")
    def extract_requirements(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        extraction_result = run_requirements_extraction_for_batch(
            project_id=project_id,
            selected_batch_id=selected_batch_id,
        )
        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "requirements": extraction_result["requirements"],
            "artifact": extraction_result["artifact"],
            "validation": extraction_result["validation"],
            "extraction": extraction_result["extraction"],
        }

    @app.post("/projects/{project_id}/generate-section")
    def generate_section(
        project_id: str,
        payload: GenerateSectionRequest,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        draft_result = generate_validated_section_draft(
            project_id=project_id,
            selected_batch_id=selected_batch_id,
            section_key=payload.section_key,
            query_text=payload.section_key,
            requested_top_k=payload.top_k,
            max_revision_rounds=1,
            force_retry=False,
        )

        artifact_meta = create_draft_artifact(
            project_id=project_id,
            section_key=payload.section_key,
            payload=draft_result["draft"],
            source="nova-agents-v1",
            upload_batch_id=selected_batch_id,
        )
        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "draft": draft_result["draft"],
            "artifact": artifact_meta,
            "validation": draft_result["validation"],
            "grounding": draft_result["grounding"],
        }

    @app.get("/projects/{project_id}/drafts/{section_key}/latest")
    def get_latest_draft(
        project_id: str,
        section_key: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        latest = get_latest_draft_artifact(project_id, section_key, upload_batch_id=selected_batch_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="No draft artifact found for project/section")

        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "section_key": section_key,
            "draft": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    @app.post("/projects/{project_id}/coverage")
    def compute_coverage(
        project_id: str,
        payload: CoverageComputeRequest,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )

        requirements_artifact = get_latest_requirements_artifact(project_id, upload_batch_id=selected_batch_id)
        if requirements_artifact is None:
            raise HTTPException(status_code=404, detail="No requirements artifact found for project")

        draft_artifact = get_latest_draft_artifact(
            project_id,
            payload.section_key,
            upload_batch_id=selected_batch_id,
        )
        if draft_artifact is None:
            raise HTTPException(status_code=404, detail="No draft artifact found for project/section")

        coverage_payload, repaired, validation_errors = compute_validated_coverage_payload(
            requirements_payload=requirements_artifact["payload"],
            draft_payload=draft_artifact["payload"],
        )

        artifact_meta = create_coverage_artifact(
            project_id=project_id,
            payload=coverage_payload,
            source="nova-agents-v1",
            upload_batch_id=selected_batch_id,
        )
        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "section_key": payload.section_key,
            "coverage": coverage_payload,
            "artifact": artifact_meta,
            "validation": {
                "repaired": repaired,
                "errors": validation_errors,
            },
        }

    @app.get("/projects/{project_id}/coverage/latest")
    def get_latest_coverage(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        latest = get_latest_coverage_artifact(project_id, upload_batch_id=selected_batch_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="No coverage artifact found for project")

        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "coverage": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    @app.post("/projects/{project_id}/generate-full-draft")
    def generate_full_draft(
        request: Request,
        project_id: str,
        payload: GenerateFullDraftRequest,
        profile: str = Query(default="submission", pattern="^(hackathon|submission|internal)$"),
        include_debug: bool = Query(default=False),
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )

        extraction_result = run_requirements_extraction_for_batch(
            project_id=project_id,
            selected_batch_id=selected_batch_id,
        )
        requirements_payload = extraction_result["requirements"]
        section_targets = build_section_targets_from_requirements(requirements_payload)

        section_runs: list[dict[str, object]] = []
        combined_paragraphs: list[dict[str, object]] = []
        combined_missing_evidence: list[dict[str, object]] = []

        for target in section_targets:
            section_key = str(target["section_key"])
            prompt = str(target["prompt"])
            requirement_id = str(target["requirement_id"])

            draft_result = generate_validated_section_draft(
                project_id=project_id,
                selected_batch_id=selected_batch_id,
                section_key=section_key,
                query_text=prompt,
                requested_top_k=payload.top_k,
                max_revision_rounds=payload.max_revision_rounds,
                force_retry=True,
            )
            draft_payload = draft_result["draft"]

            artifact_meta = create_draft_artifact(
                project_id=project_id,
                section_key=section_key,
                payload=draft_payload,
                source="nova-agents-v1",
                upload_batch_id=selected_batch_id,
            )

            section_coverage, section_repaired, section_validation_errors = compute_validated_coverage_payload(
                requirements_payload=requirements_payload,
                draft_payload=draft_payload,
            )

            paragraphs = draft_payload.get("paragraphs")
            if isinstance(paragraphs, list):
                for paragraph in paragraphs:
                    if isinstance(paragraph, dict):
                        combined_paragraphs.append(paragraph)
            missing_items = draft_payload.get("missing_evidence")
            if isinstance(missing_items, list):
                for item in missing_items:
                    if isinstance(item, dict):
                        combined_missing_evidence.append(
                            {
                                **item,
                                "affected_sections": [section_key],
                            }
                        )

            section_runs.append(
                {
                    "requirement_id": requirement_id,
                    "section_key": section_key,
                    "prompt": prompt,
                    "retrieval": draft_result["retrieval"],
                    "draft": draft_payload,
                    "draft_artifact": artifact_meta,
                    "grounding": draft_result["grounding"],
                    "coverage": section_coverage,
                    "coverage_validation": {
                        "repaired": section_repaired,
                        "errors": section_validation_errors,
                    },
                    "attempts": draft_result["attempts"],
                    "top_k_used": draft_result["top_k_used"],
                }
            )

        combined_draft_payload = {
            "section_key": "Draft Application",
            "paragraphs": combined_paragraphs,
            "missing_evidence": combined_missing_evidence,
        }
        final_coverage_payload, coverage_repaired, coverage_validation_errors = compute_validated_coverage_payload(
            requirements_payload=requirements_payload,
            draft_payload=combined_draft_payload,
        )
        coverage_artifact = create_coverage_artifact(
            project_id=project_id,
            payload=final_coverage_payload,
            source="nova-agents-v1",
            upload_batch_id=selected_batch_id,
        )

        requested_sections = [str(target["section_key"]) for target in section_targets]
        export_bundle = assemble_export_bundle_for_project(
            request=request,
            project_id=project_id,
            project=project,
            selected_batch_id=selected_batch_id,
            requested_sections=requested_sections,
            profile=profile,
            include_debug=include_debug,
            output_filename_base=None,
            use_agent=False,
        )

        unresolved: list[dict[str, object]] = []
        coverage_items = final_coverage_payload.get("items")
        if isinstance(coverage_items, list):
            for item in coverage_items:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").strip().lower()
                if status in {"partial", "missing"}:
                    unresolved.append(item)

        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "requirements": requirements_payload,
            "requirements_artifact": extraction_result["artifact"],
            "requirements_validation": extraction_result["validation"],
            "extraction": extraction_result["extraction"],
            "section_runs": section_runs,
            "coverage": final_coverage_payload,
            "coverage_artifact": coverage_artifact,
            "coverage_validation": {
                "repaired": coverage_repaired,
                "errors": coverage_validation_errors,
            },
            "unresolved_gaps": unresolved,
            "export": export_bundle,
            "run_summary": {
                "status": "complete",
                "sections_total": len(section_targets),
                "sections_completed": len(section_runs),
                "max_revision_rounds": payload.max_revision_rounds,
                "unresolved_count": len(unresolved),
            },
        }

    @app.get("/projects/{project_id}/export")
    def export_project(
        request: Request,
        project_id: str,
        format: str = Query(default="json", pattern="^(json|markdown|both)$"),
        profile: str = Query(default="submission", pattern="^(hackathon|submission|internal)$"),
        include_debug: bool = Query(default=False),
        sections: str | None = Query(default=None),
        section_key: str | None = Query(default=None),
        output_filename_base: str | None = Query(default=None, min_length=1, max_length=120),
        use_agent: bool = Query(default=True),
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ):
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        requested_format = format

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )

        requirements_artifact = get_latest_requirements_artifact(project_id, upload_batch_id=selected_batch_id)
        draft_artifacts = list_latest_draft_artifacts(project_id, upload_batch_id=selected_batch_id)
        coverage_artifact = get_latest_coverage_artifact(project_id, upload_batch_id=selected_batch_id)
        intake_artifact = get_latest_intake_artifact(project_id)
        documents = list_documents(project_id, upload_batch_id=selected_batch_id)

        requested_sections = parse_requested_sections(sections, section_key)
        drafts: dict[str, dict[str, object]] = {}
        artifacts_used: list[dict[str, object]] = []
        artifact_timestamps: list[str] = []

        for artifact in draft_artifacts:
            this_section = str(artifact.get("section_key", "")).strip()
            if requested_sections and this_section not in requested_sections:
                continue
            drafts[this_section] = {
                "draft": artifact["payload"],
                "artifact": {
                    "id": artifact["id"],
                    "source": artifact["source"],
                    "updated_at": artifact["created_at"],
                },
            }
            artifacts_used.append(
                {
                    "type": "draft",
                    "id": artifact["id"],
                    "updated_at": artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(artifact["created_at"]))

        requirements_payload = requirements_artifact["payload"] if requirements_artifact else None
        coverage_payload = coverage_artifact["payload"] if coverage_artifact else None
        intake_payload = intake_artifact["payload"] if intake_artifact else None
        documents_payload = build_export_documents(project_id, documents, upload_batch_id=selected_batch_id)

        if requirements_artifact:
            artifacts_used.append(
                {
                    "type": "requirements",
                    "id": requirements_artifact["id"],
                    "updated_at": requirements_artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(requirements_artifact["created_at"]))
        if coverage_artifact:
            artifacts_used.append(
                {
                    "type": "coverage",
                    "id": coverage_artifact["id"],
                    "updated_at": coverage_artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(coverage_artifact["created_at"]))
        if intake_artifact:
            artifacts_used.append(
                {
                    "type": "intake",
                    "id": intake_artifact["id"],
                    "updated_at": intake_artifact["created_at"],
                }
            )
            artifact_timestamps.append(str(intake_artifact["created_at"]))

        if requested_format == "markdown" and profile == "hackathon":
            draft_payloads: dict[str, dict[str, object]] = {}
            for section_name, entry in drafts.items():
                payload = entry.get("draft")
                if isinstance(payload, dict):
                    draft_payloads[section_name] = payload

            missing_evidence_for_report: list[dict[str, object]] = []
            for section_name, draft_payload in draft_payloads.items():
                section_missing = draft_payload.get("missing_evidence")
                if not isinstance(section_missing, list):
                    continue
                for item in section_missing:
                    if isinstance(item, dict):
                        missing_evidence_for_report.append(
                            {
                                **item,
                                "affected_sections": [section_name],
                            }
                        )

            try:
                markdown_report = compose_markdown_report(
                    project_name=str(project.get("name") or ""),
                    intake=intake_payload if isinstance(intake_payload, dict) else None,
                    documents=documents_payload,
                    requirements=requirements_payload if isinstance(requirements_payload, dict) else None,
                    drafts=draft_payloads,
                    coverage=coverage_payload if isinstance(coverage_payload, dict) else None,
                    missing_evidence=missing_evidence_for_report,
                    validations={},
                )
            except ExportCompositionError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Export quality gates failed.",
                        "errors": exc.errors,
                    },
                ) from exc

            report_path = Path("docs/exports") / project_id / "report.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(markdown_report, encoding="utf-8")

            logger.info(
                "export_report_written",
                extra={
                    "event": "export_report_written",
                    "request_id": getattr(request.state, "request_id", None),
                    "project_id": project_id,
                    "path": str(report_path),
                },
            )

            return PlainTextResponse(
                markdown_report,
                media_type="text/markdown",
                headers={"X-Export-Report-Path": str(report_path)},
            )

        project_updated_at = project.get("created_at")
        if artifact_timestamps:
            project_updated_at = max([str(project.get("created_at", "")), *artifact_timestamps])

        validations: dict[str, object] = {
            "requirements": {"present": requirements_payload is not None},
            "drafts": {"sections": len(drafts)},
            "coverage": {"present": coverage_payload is not None},
        }

        missing_evidence: list[dict[str, object]] = []
        for section_name, entry in drafts.items():
            payload = entry.get("draft")
            if not isinstance(payload, dict):
                continue
            items = payload.get("missing_evidence")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    missing_evidence.append(
                        {
                            **item,
                            "affected_sections": [section_name],
                        }
                    )

        source_selection: dict[str, object] = {
            "selected_document_id": None,
            "selected_file_name": None,
            "ambiguous": False,
            "candidates": [],
        }
        requirement_chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
        if requirement_chunks:
            _, source_selection = select_primary_rfp_document(select_requirement_chunks(requirement_chunks))

        export_input = {
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
                "created_at": project.get("created_at"),
                "updated_at": project_updated_at,
            },
            "export_request": {
                "format": "both",
                "profile": profile,
                "include_debug": include_debug,
                "sections": requested_sections or None,
                "output_filename_base": output_filename_base,
                "upload_batch_id": selected_batch_id,
            },
            "intake": intake_payload,
            "documents": documents_payload,
            "requirements": requirements_payload,
            "drafts": drafts,
            "coverage": coverage_payload,
            "validations": validations,
            "missing_evidence": missing_evidence,
            "source_selection": source_selection,
            "run_metadata": {
                "model_ids": {
                    "primary": settings.bedrock_model_id,
                    "lite": settings.bedrock_lite_model_id,
                },
                "temperatures": {"agent_temperature": settings.agent_temperature},
                "max_tokens": settings.agent_max_tokens,
                "retrieval_top_k": settings.retrieval_top_k_default,
                "chunking": {
                    "chunk_size_chars": settings.chunk_size_chars,
                    "chunk_overlap_chars": settings.chunk_overlap_chars,
                },
                "request_ids": [getattr(request.state, "request_id", None)],
            },
            "artifacts_used": artifacts_used,
        }

        export_bundle = build_export_bundle(export_input)

        if use_agent:
            orchestrator = get_nova_orchestrator()
            package_export_bundle = getattr(orchestrator, "package_export_bundle", None)
            if callable(package_export_bundle):
                try:
                    candidate_bundle = package_export_bundle(export_input)
                    if looks_like_export_bundle(
                        candidate_bundle,
                        require_json_bundle=True,
                        require_markdown_bundle=True,
                    ):
                        export_bundle = candidate_bundle
                    else:
                        append_export_warning(
                            export_bundle,
                            "Fell back to deterministic export: model output schema invalid.",
                        )
                except Exception as exc:  # pragma: no cover - depends on runtime integration
                    append_export_warning(
                        export_bundle,
                        f"Fell back to deterministic export: final-stage agent unavailable ({exc}).",
                    )

        markdown_files = extract_markdown_files(export_bundle)
        try:
            written_files = write_markdown_export_files(project_id, markdown_files)
            logger.info(
                "export_files_written",
                extra={
                    "event": "export_files_written",
                    "request_id": getattr(request.state, "request_id", None),
                    "project_id": project_id,
                    "files_written": len(written_files),
                },
            )
            if markdown_files and not written_files:
                append_export_warning(
                    export_bundle,
                    "Markdown bundle existed but no files were written to disk.",
                )
        except OSError as exc:
            append_export_warning(
                export_bundle,
                f"Automatic markdown file write failed: {exc}",
            )

        if requested_format == "markdown":
            markdown_content = combine_markdown_files(markdown_files)
            return PlainTextResponse(markdown_content, media_type="text/markdown")
        return export_bundle

    @app.get("/projects/{project_id}/requirements/latest")
    def get_latest_requirements(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        selected_batch_id = resolve_upload_batch_scope(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        latest = get_latest_requirements_artifact(project_id, upload_batch_id=selected_batch_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="No requirements artifact found for project")

        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "requirements": latest["payload"],
            "artifact": {
                "id": latest["id"],
                "source": latest["source"],
                "created_at": latest["created_at"],
            },
        }

    return app


app = create_app()
