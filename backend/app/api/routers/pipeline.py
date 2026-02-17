from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.contracts import CoverageComputeRequest, GenerateFullDraftRequest, GenerateSectionRequest
from app.api.services.exporting import (
    append_export_warning,
    assemble_export_bundle_for_project,
    build_hackathon_markdown_report,
    collect_export_context,
    collect_missing_evidence,
    collect_unresolved_coverage_items,
    extract_draft_paragraphs,
    extract_markdown_files,
    looks_like_export_bundle,
    write_hackathon_report,
)
from app.api.services.runtime import (
    EmbeddingServiceGetter,
    NovaOrchestratorGetter,
    build_section_targets_from_requirements,
    compute_validated_coverage_payload,
    generate_validated_section_draft,
    parse_requested_sections,
    resolve_project_upload_batch,
    run_requirements_extraction_for_batch,
    serialize_artifact_reference,
)
from app.config import settings
from app.db import (
    create_coverage_artifact,
    create_draft_artifact,
    get_latest_coverage_artifact,
    get_latest_draft_artifact,
    get_latest_requirements_artifact,
)
from app.export import ExportCompositionError
from app.export_bundle import combine_markdown_files


def build_pipeline_router(
    *,
    get_nova_orchestrator: NovaOrchestratorGetter,
    get_embedding_service: EmbeddingServiceGetter,
) -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/extract-requirements")
    def extract_requirements(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        extraction_result = run_requirements_extraction_for_batch(
            project_id=project_id,
            selected_batch_id=selected_batch_id,
            get_nova_orchestrator=get_nova_orchestrator,
        )
        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "requirements": extraction_result["requirements"],
            "artifact": extraction_result["artifact"],
            "validation": extraction_result["validation"],
            "extraction": extraction_result["extraction"],
        }

    @router.post("/projects/{project_id}/generate-section")
    def generate_section(
        project_id: str,
        payload: GenerateSectionRequest,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
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
            get_nova_orchestrator=get_nova_orchestrator,
            get_embedding_service=get_embedding_service,
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
            "warnings": draft_result["warnings"],
        }

    @router.get("/projects/{project_id}/drafts/{section_key}/latest")
    def get_latest_draft(
        project_id: str,
        section_key: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
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
            "artifact": serialize_artifact_reference(latest),
        }

    @router.post("/projects/{project_id}/coverage")
    def compute_coverage(
        project_id: str,
        payload: CoverageComputeRequest,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
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
            get_nova_orchestrator=get_nova_orchestrator,
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

    @router.get("/projects/{project_id}/coverage/latest")
    def get_latest_coverage(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
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
            "artifact": serialize_artifact_reference(latest),
        }

    @router.post("/projects/{project_id}/generate-full-draft")
    def generate_full_draft(
        request: Request,
        project_id: str,
        payload: GenerateFullDraftRequest,
        profile: str = Query(default="submission", pattern="^(hackathon|submission|internal)$"),
        include_debug: bool = Query(default=False),
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        total_started = time.perf_counter()
        project, selected_batch_id = resolve_project_upload_batch(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        runner = get_nova_orchestrator()

        extraction_started = time.perf_counter()
        extraction_result = run_requirements_extraction_for_batch(
            project_id=project_id,
            selected_batch_id=selected_batch_id,
            get_nova_orchestrator=get_nova_orchestrator,
            orchestrator=runner,
        )
        extraction_ms = round((time.perf_counter() - extraction_started) * 1000, 2)
        requirements_payload = extraction_result["requirements"]
        context_brief = payload.context_brief.strip() if payload.context_brief else None
        section_targets = build_section_targets_from_requirements(requirements_payload)
        indexed_chunks = extraction_result["chunks"]

        section_runs: list[dict[str, object]] = []
        combined_paragraphs: list[dict[str, object]] = []
        draft_payloads_by_section: dict[str, dict[str, object]] = {}
        run_warnings: list[dict[str, object]] = []
        ranked_cache: dict[tuple[str, int], tuple[list[dict[str, object]], list[dict[str, object]]]] = {}
        drafting_ms_total = 0.0
        section_coverage_ms_total = 0.0

        for target in section_targets:
            section_started = time.perf_counter()
            section_key = str(target["section_key"])
            prompt = str(target["prompt"])
            requirement_id = str(target["requirement_id"])

            draft_started = time.perf_counter()
            draft_result = generate_validated_section_draft(
                project_id=project_id,
                selected_batch_id=selected_batch_id,
                section_key=section_key,
                query_text=prompt,
                requested_top_k=payload.top_k,
                max_revision_rounds=payload.max_revision_rounds,
                force_retry=True,
                context_brief=context_brief,
                chunks_override=indexed_chunks,
                ranked_cache=ranked_cache,
                get_nova_orchestrator=get_nova_orchestrator,
                get_embedding_service=get_embedding_service,
                orchestrator=runner,
            )
            draft_ms = round((time.perf_counter() - draft_started) * 1000, 2)
            drafting_ms_total += draft_ms
            draft_payload = draft_result["draft"]
            draft_payloads_by_section[section_key] = draft_payload
            section_warnings = draft_result.get("warnings")
            if isinstance(section_warnings, list):
                run_warnings.extend([warning for warning in section_warnings if isinstance(warning, dict)])

            artifact_meta = create_draft_artifact(
                project_id=project_id,
                section_key=section_key,
                payload=draft_payload,
                source="nova-agents-v1",
                upload_batch_id=selected_batch_id,
            )

            section_coverage_started = time.perf_counter()
            section_coverage, section_repaired, section_validation_errors = compute_validated_coverage_payload(
                requirements_payload=requirements_payload,
                draft_payload=draft_payload,
                get_nova_orchestrator=get_nova_orchestrator,
                orchestrator=runner,
            )
            section_coverage_ms = round((time.perf_counter() - section_coverage_started) * 1000, 2)
            section_coverage_ms_total += section_coverage_ms

            combined_paragraphs.extend(extract_draft_paragraphs(draft_payload))

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
                    "warnings": draft_result["warnings"],
                    "timings_ms": {
                        "draft": draft_ms,
                        "coverage": section_coverage_ms,
                        "total": round((time.perf_counter() - section_started) * 1000, 2),
                    },
                }
            )

        combined_missing_evidence = collect_missing_evidence(draft_payloads_by_section)
        combined_draft_payload = {
            "section_key": "Draft Application",
            "paragraphs": combined_paragraphs,
            "missing_evidence": combined_missing_evidence,
        }
        coverage_started = time.perf_counter()
        final_coverage_payload, coverage_repaired, coverage_validation_errors = compute_validated_coverage_payload(
            requirements_payload=requirements_payload,
            draft_payload=combined_draft_payload,
            get_nova_orchestrator=get_nova_orchestrator,
            orchestrator=runner,
        )
        final_coverage_ms = round((time.perf_counter() - coverage_started) * 1000, 2)
        coverage_ms_total = round(section_coverage_ms_total + final_coverage_ms, 2)
        coverage_artifact = create_coverage_artifact(
            project_id=project_id,
            payload=final_coverage_payload,
            source="nova-agents-v1",
            upload_batch_id=selected_batch_id,
        )

        requested_sections = [str(target["section_key"]) for target in section_targets]
        export_started = time.perf_counter()
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
            get_nova_orchestrator=get_nova_orchestrator,
        )
        export_ms = round((time.perf_counter() - export_started) * 1000, 2)
        total_ms = round((time.perf_counter() - total_started) * 1000, 2)

        unresolved = collect_unresolved_coverage_items(final_coverage_payload)
        deduped_run_warnings: list[dict[str, object]] = []
        seen_warning_keys: set[str] = set()
        for warning in run_warnings:
            key = str(warning)
            if key in seen_warning_keys:
                continue
            seen_warning_keys.add(key)
            deduped_run_warnings.append(warning)

        response: dict[str, object] = {
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
                "timings_ms": {
                    "extraction": extraction_ms,
                    "drafting": round(drafting_ms_total, 2),
                    "coverage": coverage_ms_total,
                    "export": export_ms,
                    "total": total_ms,
                },
            },
        }
        if deduped_run_warnings:
            response["warnings"] = deduped_run_warnings
        return response

    @router.get("/projects/{project_id}/export")
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
        project, selected_batch_id = resolve_project_upload_batch(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        requested_format = format

        requested_sections = parse_requested_sections(sections, section_key)

        if requested_format == "markdown" and profile == "hackathon":
            context = collect_export_context(
                project_id=project_id,
                selected_batch_id=selected_batch_id,
                requested_sections=requested_sections,
            )
            drafts = context["drafts"]
            requirements_payload = context["requirements_payload"]
            coverage_payload = context["coverage_payload"]
            documents_payload = context["documents_payload"]
            requirements_dict = requirements_payload if isinstance(requirements_payload, dict) else None
            coverage_dict = coverage_payload if isinstance(coverage_payload, dict) else None

            try:
                markdown_report = build_hackathon_markdown_report(
                    project_name=str(project.get("name") or ""),
                    documents_payload=documents_payload,
                    requirements_payload=requirements_dict,
                    coverage_payload=coverage_dict,
                    drafts=drafts,
                )
            except ExportCompositionError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Export quality gates failed.",
                        "errors": exc.errors,
                    },
                ) from exc

            report_path = write_hackathon_report(project_id, markdown_report, request)

            return PlainTextResponse(
                markdown_report,
                media_type="text/markdown",
                headers={"X-Export-Report-Path": str(report_path)},
            )

        export_bundle = assemble_export_bundle_for_project(
            request=request,
            project_id=project_id,
            project=project,
            selected_batch_id=selected_batch_id,
            requested_sections=requested_sections,
            profile=profile,
            include_debug=include_debug,
            output_filename_base=output_filename_base,
            use_agent=use_agent,
            get_nova_orchestrator=get_nova_orchestrator,
        )
        markdown_files = extract_markdown_files(export_bundle)

        if requested_format == "markdown":
            markdown_content = combine_markdown_files(markdown_files)
            return PlainTextResponse(markdown_content, media_type="text/markdown")
        return export_bundle

    @router.get("/projects/{project_id}/requirements/latest")
    def get_latest_requirements(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
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
            "artifact": serialize_artifact_reference(latest),
        }

    return router
