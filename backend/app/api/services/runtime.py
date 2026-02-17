from __future__ import annotations

import logging
import re
from typing import Callable, Mapping

from fastapi import HTTPException

from app.config import settings
from app.coverage import (
    normalize_coverage_payload,
    validate_with_repair as validate_coverage_with_repair,
)
from app.db import (
    create_requirements_artifact,
    get_latest_upload_batch_id,
    get_project,
    list_chunks,
    upload_batch_exists,
)
from app.drafting import (
    build_draft_payload,
    ground_draft_payload,
    normalize_draft_section_key,
    validate_with_repair as validate_draft_with_repair,
)
from app.export.policy import derive_section_title_from_prompt
from app.nova_runtime import BedrockNovaOrchestrator, NovaRuntimeError
from app.requirements import (
    extract_requirements_payload,
    merge_requirements_payload,
    validate_with_repair as validate_requirements_with_repair,
)
from app.retrieval import (
    EmbeddingProviderError,
    EmbeddingService,
    cosine_similarity,
)

logger = logging.getLogger("nebula.api")

NovaOrchestratorGetter = Callable[[], BedrockNovaOrchestrator]
EmbeddingServiceGetter = Callable[[], EmbeddingService]


def rank_chunks_by_query(
    chunks: list[dict[str, object]],
    query: str,
    top_k: int,
    *,
    get_embedding_service: EmbeddingServiceGetter,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if top_k < 1 or not chunks:
        return [], []

    warnings: list[dict[str, object]] = []

    def append_warning(code: str, message: str, details: dict[str, object]) -> None:
        key = (code, message)
        existing = {
            (str(item.get("code", "")), str(item.get("message", "")))
            for item in warnings
            if isinstance(item, dict)
        }
        if key in existing:
            return
        warnings.append(
            {
                "code": code,
                "message": message,
                "details": details,
            }
        )

    dims: dict[int, int] = {}
    provider_counts: dict[str, int] = {}
    for chunk in chunks:
        embedding = chunk.get("embedding")
        if isinstance(embedding, list) and embedding:
            dims[len(embedding)] = dims.get(len(embedding), 0) + 1
        provider = str(chunk.get("embedding_provider") or "hash").strip().lower() or "hash"
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    if not dims:
        return [], []

    target_dim = settings.embedding_dim
    if target_dim not in dims:
        target_dim = max(dims.items(), key=lambda item: item[1])[0]
        logger.warning(
            "embedding_dim_mismatch_detected",
            extra={
                "event": "embedding_dim_mismatch_detected",
                "configured_dim": settings.embedding_dim,
                "target_dim": target_dim,
                "available_dims": sorted(dims.keys()),
            },
        )

    embedding_service = get_embedding_service()
    try:
        query_embedding_result = embedding_service.embed(query, target_dim)
    except EmbeddingProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "Embedding provider failed for retrieval.", "error": str(exc)},
        ) from exc

    if query_embedding_result.warning is not None:
        warnings.append(query_embedding_result.warning)

    query_provider = query_embedding_result.provider
    query_embedding = query_embedding_result.vector
    query_dim = len(query_embedding)
    if query_dim != target_dim:
        append_warning(
            "embedding_query_dim_mismatch",
            "Query embedding dimension does not match indexed chunk dimension target.",
            {
                "configured_dim": settings.embedding_dim,
                "selected_target_dim": target_dim,
                "query_dim": query_dim,
            },
        )
        target_dim = query_dim

    if provider_counts and query_provider not in provider_counts:
        append_warning(
            "embedding_mode_drift",
            "Query embedding provider differs from indexed chunk provider(s). Re-index project documents.",
            {
                "query_provider": query_provider,
                "chunk_provider_counts": provider_counts,
                "embedding_mode": settings.embedding_mode,
            },
        )
    if len(provider_counts) > 1:
        append_warning(
            "mixed_embedding_providers",
            "Project chunks contain mixed embedding providers. Re-index for consistent retrieval scoring.",
            {
                "chunk_provider_counts": provider_counts,
            },
        )

    scored_results: list[dict[str, object]] = []
    skipped_chunks = 0
    for chunk in chunks:
        embedding = chunk.get("embedding")
        if not isinstance(embedding, list) or len(embedding) != target_dim:
            skipped_chunks += 1
            continue
        scored_results.append(
            {
                "chunk_id": chunk["id"],
                "document_id": chunk["document_id"],
                "file_name": chunk["file_name"],
                "page": chunk["page"],
                "text": chunk["text"],
                "score": cosine_similarity(query_embedding, embedding),
            }
        )
    if skipped_chunks > 0:
        logger.warning(
            "embedding_dim_chunks_skipped",
            extra={
                "event": "embedding_dim_chunks_skipped",
                "target_dim": target_dim,
                "skipped_chunks": skipped_chunks,
                "total_chunks": len(chunks),
            },
        )
    if target_dim != settings.embedding_dim or skipped_chunks > 0:
        append_warning(
            "embedding_dim_drift",
            "Embedding dimension drift detected. Re-index project documents for stable retrieval.",
            {
                "configured_dim": settings.embedding_dim,
                "target_dim": target_dim,
                "available_dims": sorted(dims.keys()),
                "skipped_chunks": skipped_chunks,
                "total_chunks": len(chunks),
            },
        )
    scored_results.sort(key=lambda item: float(item["score"]), reverse=True)
    return scored_results[:top_k], warnings


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


def serialize_document_for_api(document: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(document.get("id", "")),
        "project_id": str(document.get("project_id", "")),
        "file_name": str(document.get("file_name", "")),
        "content_type": str(document.get("content_type", "")),
        "size_bytes": int(document.get("size_bytes", 0) or 0),
        "upload_batch_id": (
            str(document.get("upload_batch_id", "")).strip() if document.get("upload_batch_id") is not None else None
        ),
        "created_at": str(document.get("created_at", "")),
    }


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


def require_project(project_id: str) -> dict[str, object]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def resolve_project_upload_batch(
    *,
    project_id: str,
    document_scope: str,
    upload_batch_id: str | None,
) -> tuple[dict[str, object], str | None]:
    project = require_project(project_id)
    selected_batch_id = resolve_upload_batch_scope(
        project_id=project_id,
        document_scope=document_scope,
        upload_batch_id=upload_batch_id,
    )
    return project, selected_batch_id


def serialize_artifact_reference(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": artifact["id"],
        "source": artifact["source"],
        "created_at": artifact["created_at"],
    }


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
        requirement_id = (
            str(question.get("internal_id") or "").strip()
            or str(question.get("id") or "").strip()
            or f"Q{index}"
        )
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
    get_nova_orchestrator: NovaOrchestratorGetter,
    chunks_override: list[dict[str, object]] | None = None,
    orchestrator: BedrockNovaOrchestrator | None = None,
) -> dict[str, object]:
    chunks = chunks_override if chunks_override is not None else list_chunks(project_id, upload_batch_id=selected_batch_id)
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
    adaptive_context: dict[str, object] = {
        "mode": "deterministic-only",
        "window_count": 0,
        "raw_candidates": 0,
        "deduped_candidates": 0,
        "dropped_candidates": 0,
        "dedupe_ratio": 0.0,
    }
    runner = orchestrator or get_nova_orchestrator()
    try:
        nova_payload = runner.extract_requirements(requirement_chunks)
        if isinstance(nova_payload, dict):
            diagnostics = nova_payload.get("_extraction_diagnostics")
            if isinstance(diagnostics, dict):
                adaptive_context = diagnostics
            nova_payload = {key: value for key, value in nova_payload.items() if key != "_extraction_diagnostics"}
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
            "adaptive_context": adaptive_context,
        },
        "chunks": chunks,
    }


def compute_validated_coverage_payload(
    *,
    requirements_payload: dict[str, object],
    draft_payload: dict[str, object],
    get_nova_orchestrator: NovaOrchestratorGetter,
    orchestrator: BedrockNovaOrchestrator | None = None,
) -> tuple[dict[str, object], bool, list[str]]:
    runner = orchestrator or get_nova_orchestrator()
    try:
        coverage_payload = runner.compute_coverage(
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
    get_nova_orchestrator: NovaOrchestratorGetter,
    get_embedding_service: EmbeddingServiceGetter,
    context_brief: str | None = None,
    chunks_override: list[dict[str, object]] | None = None,
    ranked_cache: dict[tuple[str, int], tuple[list[dict[str, object]], list[dict[str, object]]]] | None = None,
    orchestrator: BedrockNovaOrchestrator | None = None,
) -> dict[str, object]:
    chunks = chunks_override if chunks_override is not None else list_chunks(project_id, upload_batch_id=selected_batch_id)
    runner = orchestrator or get_nova_orchestrator()
    prompt_context: dict[str, str] | None = None
    if context_brief:
        trimmed = context_brief.strip()
        if trimmed:
            prompt_context = {"context_brief": trimmed}

    default_top_k = requested_top_k or settings.retrieval_top_k_default
    ranking_cache_key = (query_text.strip().lower(), id(chunks))
    if chunks:
        if ranked_cache is not None and ranking_cache_key in ranked_cache:
            ranked_all, ranking_warnings = ranked_cache[ranking_cache_key]
        else:
            ranked_all, ranking_warnings = rank_chunks_by_query(
                chunks,
                query_text,
                min(20, len(chunks)),
                get_embedding_service=get_embedding_service,
            )
            if ranked_cache is not None:
                ranked_cache[ranking_cache_key] = (ranked_all, ranking_warnings)
    else:
        ranked_all, ranking_warnings = [], []

    top_k = default_top_k
    retry_on_missing = False
    if settings.enable_agentic_orchestration_pilot and ranked_all:
        try:
            plan = runner.plan_section_generation(
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
                draft_payload = runner.generate_section(
                    section_key,
                    ranked_chunks,
                    prompt_context=prompt_context,
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
        "warnings": ranking_warnings,
    }
