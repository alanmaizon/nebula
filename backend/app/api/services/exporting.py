from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Mapping

from fastapi import Request

from app.api.contracts import ExportContext
from app.api.services.runtime import (
    NovaOrchestratorGetter,
    select_primary_rfp_document,
    select_requirement_chunks,
    serialize_document_for_api,
)
from app.config import settings
from app.db import (
    get_latest_coverage_artifact,
    get_latest_draft_artifact,
    get_latest_requirements_artifact,
    list_chunks,
    list_documents,
    list_latest_draft_artifacts,
)
from app.export import compose_markdown_report
from app.export_bundle import EXPORT_VERSION, build_export_bundle

logger = logging.getLogger("nebula.api")


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
        public_document = serialize_document_for_api(document)
        exported.append(
            {
                **public_document,
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


def collect_export_context(
    *,
    project_id: str,
    selected_batch_id: str | None,
    requested_sections: list[str],
) -> ExportContext:
    requirements_artifact = get_latest_requirements_artifact(project_id, upload_batch_id=selected_batch_id)
    draft_artifacts = list_latest_draft_artifacts(project_id, upload_batch_id=selected_batch_id)
    coverage_artifact = get_latest_coverage_artifact(project_id, upload_batch_id=selected_batch_id)
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

    return {
        "drafts": drafts,
        "requirements_payload": requirements_payload,
        "coverage_payload": coverage_payload,
        "documents_payload": documents_payload,
        "artifacts_used": artifacts_used,
        "artifact_timestamps": artifact_timestamps,
    }


def extract_draft_payloads(drafts: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for section_name, entry in drafts.items():
        payload = entry.get("draft")
        if isinstance(payload, dict):
            payloads[section_name] = payload
    return payloads


def collect_missing_evidence(draft_payloads: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    missing_evidence: list[dict[str, object]] = []
    for section_name, payload in draft_payloads.items():
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
    return missing_evidence


def extract_draft_paragraphs(draft_payload: dict[str, object]) -> list[dict[str, object]]:
    paragraphs = draft_payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        return []
    return [paragraph for paragraph in paragraphs if isinstance(paragraph, dict)]


def collect_unresolved_coverage_items(coverage_payload: dict[str, object]) -> list[dict[str, object]]:
    unresolved: list[dict[str, object]] = []
    coverage_items = coverage_payload.get("items")
    if not isinstance(coverage_items, list):
        return unresolved
    for item in coverage_items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status in {"partial", "missing"}:
            unresolved.append(item)
    return unresolved


def build_source_selection(project_id: str, selected_batch_id: str | None) -> dict[str, object]:
    source_selection: dict[str, object] = {
        "selected_document_id": None,
        "selected_file_name": None,
        "ambiguous": False,
        "candidates": [],
    }
    requirement_chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
    if requirement_chunks:
        _, source_selection = select_primary_rfp_document(select_requirement_chunks(requirement_chunks))
    return source_selection


def build_run_metadata(request: Request) -> dict[str, object]:
    return {
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
    }


def build_hackathon_markdown_report(
    *,
    project_name: str,
    documents_payload: list[dict[str, object]],
    requirements_payload: dict[str, object] | None,
    coverage_payload: dict[str, object] | None,
    drafts: dict[str, dict[str, object]],
) -> str:
    draft_payloads = extract_draft_payloads(drafts)
    missing_evidence_for_report = collect_missing_evidence(draft_payloads)

    return compose_markdown_report(
        project_name=project_name,
        documents=documents_payload,
        requirements=requirements_payload,
        drafts=draft_payloads,
        coverage=coverage_payload,
        missing_evidence=missing_evidence_for_report,
        validations={},
    )


def write_hackathon_report(project_id: str, markdown_report: str, request: Request) -> Path:
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
    return report_path


def persist_export_bundle_markdown_files(
    project_id: str,
    export_bundle: dict[str, object],
    request: Request,
) -> list[dict[str, str]]:
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
    return markdown_files


def assemble_export_bundle_for_project(
    *,
    request: Request,
    project_id: str,
    project: Mapping[str, object],
    selected_batch_id: str | None,
    requested_sections: list[str],
    profile: str,
    include_debug: bool,
    output_filename_base: str | None,
    use_agent: bool,
    get_nova_orchestrator: NovaOrchestratorGetter,
) -> dict[str, object]:
    context: ExportContext = collect_export_context(
        project_id=project_id,
        selected_batch_id=selected_batch_id,
        requested_sections=requested_sections,
    )
    drafts = context["drafts"]
    requirements_payload = context["requirements_payload"]
    coverage_payload = context["coverage_payload"]
    documents_payload = context["documents_payload"]
    artifacts_used = context["artifacts_used"]
    artifact_timestamps = context["artifact_timestamps"]

    project_updated_at = project.get("created_at")
    if artifact_timestamps:
        project_updated_at = max([str(project.get("created_at", "")), *artifact_timestamps])

    validations: dict[str, object] = {
        "requirements": {"present": requirements_payload is not None},
        "drafts": {"sections": len(drafts)},
        "coverage": {"present": coverage_payload is not None},
    }

    draft_payloads = extract_draft_payloads(drafts)
    missing_evidence = collect_missing_evidence(draft_payloads)
    source_selection = build_source_selection(project_id, selected_batch_id)

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
        "documents": documents_payload,
        "requirements": requirements_payload,
        "drafts": drafts,
        "coverage": coverage_payload,
        "validations": validations,
        "missing_evidence": missing_evidence,
        "source_selection": source_selection,
        "run_metadata": build_run_metadata(request),
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

    persist_export_bundle_markdown_files(project_id, export_bundle, request)

    return export_bundle
