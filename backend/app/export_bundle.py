from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

EXPORT_VERSION = "nebula.export.v1"

_NARRATIVE_REQUIREMENT_SECTION_MAP = {
    "Q1": "Need Statement",
    "Q2": "Program Design",
    "Q3": "Outcomes and Evaluation",
}
_COVERAGE_STATUS_ORDER = {"missing": 0, "partial": 1, "met": 2}
_INLINE_CITATION_HINT_PATTERN = re.compile(
    r"\(\s*(?:doc(?:_id)?|source)\s*[:=]\s*([^,)\n]+)\s*,\s*page\s*[:=]\s*(\d+)\s*\)",
    flags=re.IGNORECASE,
)
_ATTACHMENT_NOISE_TOKENS = {
    "a",
    "an",
    "and",
    "attachment",
    "appendix",
    "by",
    "for",
    "of",
    "required",
    "the",
    "to",
}
_MIN_CONFIDENCE_FOR_SUPPORTED = 0.35

_AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    flags=re.IGNORECASE,
)
_AWS_SECRET_INLINE_PATTERN = re.compile(r"(aws_secret_access_key\s*[:=]\s*)([^\s,;]+)", flags=re.IGNORECASE)


def build_export_bundle(input_payload: dict[str, object]) -> dict[str, object]:
    generated_at = _utc_now_iso()
    project = _as_dict(input_payload.get("project"))
    export_request = _as_dict(input_payload.get("export_request"))

    fmt = str(export_request.get("format") or "json").lower()
    if fmt not in {"json", "markdown", "both"}:
        fmt = "json"

    profile = str(export_request.get("profile") or "submission").lower()
    if profile not in {"hackathon", "submission", "internal"}:
        profile = "submission"
    include_debug = bool(export_request.get("include_debug", False))

    documents = _as_dict_list(input_payload.get("documents"))
    requirements = _as_optional_dict(input_payload.get("requirements"))
    coverage = _as_optional_dict(input_payload.get("coverage"))
    validations = _as_optional_dict(input_payload.get("validations")) or {}
    intake = _as_optional_dict(input_payload.get("intake"))
    raw_missing_evidence = _as_dict_list(input_payload.get("missing_evidence"))
    artifacts_used = _as_dict_list(input_payload.get("artifacts_used"))
    run_metadata = _as_optional_dict(input_payload.get("run_metadata")) or {}

    requested_sections = _coerce_sections(export_request.get("sections"))
    drafts_map = _normalize_drafts(input_payload.get("drafts"))
    selected_sections = _resolve_section_order(
        requirements=requirements,
        available_sections=list(drafts_map.keys()),
        requested_sections=requested_sections,
    )

    quality_reasons: list[str] = []
    warnings: list[str] = []

    missing_requested_sections = [
        section_key for section_key in requested_sections if section_key not in drafts_map
    ]
    if missing_requested_sections:
        quality_reasons.append(
            "Requested section(s) missing entirely: " + ", ".join(sorted(missing_requested_sections))
        )

    coverage_items = _as_dict_list((coverage or {}).get("items"))

    if requirements is not None and coverage is None:
        quality_reasons.append("Requirements artifact exists but coverage artifact is missing.")

    valid_doc_ids, doc_page_counts = _build_document_lookup(documents)
    exported_drafts, unsupported_claims_count, draft_warnings, integrity_signals = _prepare_drafts_for_export(
        drafts_map=drafts_map,
        selected_sections=selected_sections,
        valid_doc_ids=valid_doc_ids,
        doc_page_counts=doc_page_counts,
    )
    warnings.extend(draft_warnings)

    reconciled_coverage_items = _reconcile_coverage_items(
        requirements=requirements,
        coverage_items=coverage_items,
        drafts=exported_drafts,
    )
    coverage_counts = _coverage_counts(reconciled_coverage_items)

    invalid_citation_doc_ids = set(integrity_signals.get("invalid_doc_ids") or [])
    if invalid_citation_doc_ids:
        quality_reasons.append(
            "Citation doc_id not found in project documents: "
            + ", ".join(sorted(invalid_citation_doc_ids))
        )
    if int(integrity_signals.get("citation_mismatch_count") or 0) > 0:
        warnings.append("citation mismatch warning")

    merged_missing_evidence = _merge_missing_evidence(raw_missing_evidence, exported_drafts)
    missing_evidence_count = len(merged_missing_evidence)

    known_constraints, unknown_constraints = _extract_constraints(requirements)
    if unknown_constraints:
        warnings.append("constraints_unknown present")
    if unsupported_claims_count > 0:
        warnings.append("unsupported_claims_count > 0")

    coverage_uncertainty = _derive_coverage_uncertainty_signals(
        requirements=requirements,
        coverage_items=reconciled_coverage_items,
        section_stats=_build_section_stats(exported_drafts),
    )
    warnings.extend(coverage_uncertainty["warnings"])
    completion = _compute_completion(
        coverage_counts,
        unsupported_claims_count=unsupported_claims_count,
        citation_mismatch_count=int(integrity_signals.get("citation_mismatch_count") or 0),
        empty_required_sections_count=int(coverage_uncertainty.get("empty_required_sections_count") or 0),
    )
    overall_completion = (
        f"{completion:.1f}%"
        if completion is not None
        else "unknown"
    )

    summary = {
        "overall_completion": overall_completion,
        "coverage_overview": coverage_counts,
        "unsupported_claims_count": unsupported_claims_count,
        "missing_evidence_count": missing_evidence_count,
        "uncertainty": {
            "citation_mismatch_count": int(integrity_signals.get("citation_mismatch_count") or 0),
            "source_conflict_count": int(coverage_uncertainty.get("source_conflict_count") or 0),
            "empty_required_sections_count": int(coverage_uncertainty.get("empty_required_sections_count") or 0),
            "unsupported_claims_count": unsupported_claims_count,
        },
        "constraints": {
            "known": known_constraints,
            "unknown": unknown_constraints,
        },
    }

    markdown_files: list[dict[str, str]] = []
    if fmt in {"markdown", "both"}:
        markdown_files = _build_markdown_files(
            profile=profile,
            include_debug=include_debug,
            project=project,
            export_request=export_request,
            intake=intake,
            documents=documents,
            requirements=requirements,
            drafts=exported_drafts,
            selected_sections=selected_sections,
            coverage_items=reconciled_coverage_items,
            coverage_counts=coverage_counts,
            uncertainty=summary["uncertainty"] if isinstance(summary.get("uncertainty"), dict) else {},
            missing_evidence=merged_missing_evidence,
            validations=validations,
            run_metadata=run_metadata,
            summary=summary,
        )
        if not markdown_files:
            quality_reasons.append("Markdown requested but no markdown files produced.")

    bundle_json: dict[str, object] | None = None
    if fmt in {"json", "both"}:
        bundle_json = {
            "project": {
                "id": str(project.get("id") or ""),
                "name": str(project.get("name") or ""),
            },
            "export_request": export_request,
            "intake": intake,
            "documents": documents,
            "requirements": requirements,
            "drafts": exported_drafts,
            "coverage": {"items": reconciled_coverage_items},
            "missing_evidence": merged_missing_evidence,
            "validations": validations,
            "summary": summary,
        }

    redaction_warnings: list[str] = []
    redacted_run_metadata = _redact_value(run_metadata, redaction_warnings)
    warnings.extend(redaction_warnings)

    quality_gates = {
        "passed": len(quality_reasons) == 0,
        "reasons": _dedupe_preserve_order(quality_reasons),
        "warnings": _dedupe_preserve_order(warnings),
    }

    return {
        "export_version": EXPORT_VERSION,
        "generated_at": generated_at,
        "project": {
            "id": str(project.get("id") or ""),
            "name": str(project.get("name") or ""),
        },
        "bundle": {
            "json": bundle_json,
            "markdown": {"files": markdown_files} if fmt in {"markdown", "both"} else None,
        },
        "summary": summary,
        "quality_gates": quality_gates,
        "provenance": {
            "artifacts_used": artifacts_used,
            "run_metadata": redacted_run_metadata,
        },
    }


def combine_markdown_files(markdown_files: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for file in markdown_files:
        path = str(file.get("path") or "").strip()
        content = str(file.get("content") or "").strip()
        if not content:
            continue
        if path:
            blocks.append(f"# {path}\n\n{content}")
        else:
            blocks.append(content)
    return "\n\n---\n\n".join(blocks).strip()


def _reconcile_coverage_items(
    *,
    requirements: dict[str, object] | None,
    coverage_items: list[dict[str, object]],
    drafts: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    if requirements is None:
        normalized_only: list[dict[str, object]] = []
        for item in coverage_items:
            req_id = str(item.get("requirement_id") or "").strip()
            if not req_id:
                continue
            refs = _as_str_list(item.get("evidence_refs"))
            normalized_only.append(
                {
                    "requirement_id": req_id,
                    "status": _normalize_coverage_status(item.get("status")),
                    "notes": str(item.get("notes") or "").strip() or "Coverage note unavailable.",
                    "evidence_refs": refs,
                }
            )
        return normalized_only

    definitions = _build_requirement_definitions_for_reconciliation(requirements)
    coverage_lookup = {
        str(item.get("requirement_id") or "").strip(): item
        for item in coverage_items
        if isinstance(item, dict) and str(item.get("requirement_id") or "").strip()
    }
    section_stats = _build_section_stats(drafts)

    reconciled: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for definition in definitions:
        requirement_id = str(definition["requirement_id"])
        requirement_text = str(definition["requirement"])
        existing = coverage_lookup.get(requirement_id, {})
        existing_status = _normalize_coverage_status(existing.get("status"))
        existing_notes = str(existing.get("notes") or "").strip()
        existing_refs = _as_str_list(existing.get("evidence_refs"))

        inferred_status, inferred_notes, inferred_refs = _infer_requirement_coverage(
            requirement_id=requirement_id,
            requirement_text=requirement_text,
            expected_section=str(definition.get("expected_section") or ""),
            word_limit=definition.get("word_limit"),
            section_stats=section_stats,
        )

        status = _max_coverage_status(existing_status, inferred_status)
        notes = existing_notes or inferred_notes
        refs = existing_refs

        if inferred_refs:
            if not refs:
                refs = inferred_refs
            elif _COVERAGE_STATUS_ORDER.get(inferred_status, 0) >= _COVERAGE_STATUS_ORDER.get(existing_status, 0):
                refs = inferred_refs

        if _COVERAGE_STATUS_ORDER.get(inferred_status, 0) > _COVERAGE_STATUS_ORDER.get(existing_status, 0) and inferred_notes:
            notes = inferred_notes
        if status == "missing" and not notes:
            notes = f"No coverage item returned for requirement: {requirement_text}"
        if not notes:
            notes = "Coverage note unavailable."
        if requirement_id.upper().startswith("A"):
            if status == "met" and not _has_attachment_grounded_evidence(
                requirement_id=requirement_id,
                requirement_text=requirement_text,
                evidence_refs=refs,
            ):
                status = "partial" if refs else "missing"
                notes = (
                    "Attachment requirement needs attachment-grounded evidence; "
                    "narrative-only evidence cannot be marked met."
                )

        reconciled.append(
            {
                "requirement_id": requirement_id,
                "status": status,
                "notes": notes,
                "evidence_refs": refs,
            }
        )
        seen_ids.add(requirement_id)

    for item in coverage_items:
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id") or "").strip()
        if not requirement_id or requirement_id in seen_ids:
            continue
        reconciled.append(
            {
                "requirement_id": requirement_id,
                "status": _normalize_coverage_status(item.get("status")),
                "notes": str(item.get("notes") or "").strip() or "Coverage note unavailable.",
                "evidence_refs": _as_str_list(item.get("evidence_refs")),
            }
        )
        seen_ids.add(requirement_id)

    return reconciled


def _build_requirement_definitions_for_reconciliation(
    requirements: dict[str, object],
) -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = []

    questions = requirements.get("questions")
    if isinstance(questions, list):
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            requirement_id = str(question.get("id") or f"Q{index}").strip() or f"Q{index}"
            prompt = str(question.get("prompt") or "").strip()
            if not prompt:
                continue
            expected_section = (
                _NARRATIVE_REQUIREMENT_SECTION_MAP.get(requirement_id.upper().strip())
                or _question_section_title(prompt)
            )
            definitions.append(
                {
                    "requirement_id": requirement_id,
                    "requirement": prompt,
                    "expected_section": expected_section,
                    "word_limit": _question_word_limit(prompt, question.get("limit")),
                }
            )

    attachments = requirements.get("required_attachments")
    if isinstance(attachments, list):
        attachment_index = 1
        for attachment in attachments:
            text = str(attachment).strip()
            if not text:
                continue
            definitions.append(
                {
                    "requirement_id": f"A{attachment_index}",
                    "requirement": text,
                    "expected_section": "",
                    "word_limit": None,
                }
            )
            attachment_index += 1

    for prefix, source_key in [("E", "eligibility"), ("R", "rubric"), ("D", "disallowed_costs")]:
        entries = requirements.get(source_key)
        if not isinstance(entries, list):
            continue
        for index, value in enumerate(entries, start=1):
            text = str(value).strip()
            if not text:
                continue
            definitions.append(
                {
                    "requirement_id": f"{prefix}{index}",
                    "requirement": text,
                    "expected_section": "",
                    "word_limit": None,
                }
            )

    return definitions


def _build_section_stats(drafts: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    section_stats: dict[str, dict[str, object]] = {}

    for fallback_key, section in drafts.items():
        draft = _as_optional_dict(section.get("draft")) or {}
        title = str(draft.get("section_key") or fallback_key).strip() or fallback_key
        raw_paragraphs = _as_dict_list(draft.get("paragraphs"))
        paragraphs: list[dict[str, object]] = []
        citation_count = 0

        for index, paragraph in enumerate(raw_paragraphs, start=1):
            text = str(paragraph.get("text") or "").strip()
            if not text:
                continue
            citations = _as_dict_list(paragraph.get("citations"))
            normalized_citations: list[dict[str, object]] = []
            for citation in citations:
                doc_id = str(citation.get("doc_id") or "").strip()
                page = _coerce_positive_int(citation.get("page")) or 1
                snippet = str(citation.get("snippet") or "").strip()
                if not doc_id:
                    continue
                normalized_citations.append({"doc_id": doc_id, "page": page, "snippet": snippet})

            citation_count += len(normalized_citations)
            paragraphs.append(
                {
                    "index": index,
                    "text": text,
                    "word_count": _word_count(text),
                    "tokens": _token_set(text),
                    "citations": normalized_citations,
                }
            )

        total_words = sum(int(paragraph.get("word_count") or 0) for paragraph in paragraphs)
        section_stats[_normalize_key(title)] = {
            "title": title,
            "paragraphs": paragraphs,
            "word_count": total_words,
            "citation_count": citation_count,
            "substantive": len(paragraphs) >= 2 and total_words >= 80,
            "evidence_refs": _derive_section_evidence_refs(paragraphs, title),
        }

    return section_stats


def _infer_requirement_coverage(
    *,
    requirement_id: str,
    requirement_text: str,
    expected_section: str,
    word_limit: object,
    section_stats: dict[str, dict[str, object]],
) -> tuple[str, str, list[str]]:
    if expected_section:
        section = _match_expected_section(section_stats, expected_section)
        if section and bool(section.get("substantive")):
            has_citations = int(section.get("citation_count") or 0) > 0
            within_limit = True
            if isinstance(word_limit, int) and word_limit > 0:
                within_limit = int(section.get("word_count") or 0) <= word_limit
            status = "met" if has_citations and within_limit else "partial"
            if status == "met":
                notes = f"The draft artifact includes a substantive {expected_section.lower()} section."
            elif has_citations:
                notes = (
                    f"The draft artifact includes a substantive {expected_section.lower()} section, "
                    "but it exceeds the word limit."
                )
            else:
                notes = (
                    f"The draft artifact includes a substantive {expected_section.lower()} section "
                    "without grounded citations."
                )
            refs = _as_str_list(section.get("evidence_refs"))
            return status, notes, refs
        return (
            "missing",
            f"The draft artifact does not include a substantive {expected_section.lower()} section.",
            [],
        )

    requirement_tokens = _token_set(requirement_text)
    if not requirement_tokens:
        return "missing", "No requirement tokens available for deterministic matching.", []

    best_score = 0.0
    best_refs: list[str] = []
    best_has_citations = False
    best_title = ""
    best_paragraph_index = 0

    for section in section_stats.values():
        paragraphs = section.get("paragraphs")
        if not isinstance(paragraphs, list):
            continue
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            paragraph_tokens = paragraph.get("tokens")
            if not isinstance(paragraph_tokens, set):
                paragraph_tokens = _token_set(str(paragraph.get("text") or ""))
            score = _overlap_score(requirement_tokens, paragraph_tokens)
            if score < best_score:
                continue
            citations = paragraph.get("citations")
            citation_list = citations if isinstance(citations, list) else []
            refs = _derive_paragraph_refs(str(section.get("title") or ""), paragraph, citation_list)
            if score > best_score or (len(refs) > 0 and not best_has_citations):
                best_score = score
                best_refs = refs
                best_has_citations = len(citation_list) > 0
                best_title = str(section.get("title") or "")
                best_paragraph_index = int(paragraph.get("index") or 0)

    if best_score >= 0.2 and best_has_citations:
        notes = "Requirement is supported by cited draft evidence."
        if best_title and best_paragraph_index > 0:
            notes = (
                f"Requirement is supported by cited draft evidence in {best_title}, paragraph {best_paragraph_index}."
            )
        return "met", notes, best_refs
    if best_score >= 0.08:
        notes = "Requirement has partial draft coverage and needs stronger evidence alignment."
        if best_title and best_paragraph_index > 0:
            notes = (
                f"Requirement has partial draft coverage in {best_title}, paragraph {best_paragraph_index}."
            )
        return "partial", notes, best_refs
    return "missing", "No meaningful evidence-backed coverage found in generated drafts.", []


def _match_expected_section(
    section_stats: dict[str, dict[str, object]],
    expected_section: str,
) -> dict[str, object] | None:
    expected_key = _normalize_key(expected_section)
    if not expected_key:
        return None
    exact = section_stats.get(expected_key)
    if exact is not None:
        return exact

    fuzzy_matches: list[dict[str, object]] = []
    for key, section in section_stats.items():
        if key.startswith(expected_key) or expected_key in key:
            fuzzy_matches.append(section)
    if not fuzzy_matches:
        return None

    fuzzy_matches.sort(
        key=lambda section: (
            bool(section.get("substantive")),
            int(section.get("citation_count") or 0),
            int(section.get("word_count") or 0),
        ),
        reverse=True,
    )
    return fuzzy_matches[0]


def _derive_section_evidence_refs(paragraphs: list[dict[str, object]], section_title: str) -> list[str]:
    refs: list[str] = []
    for paragraph in paragraphs:
        refs.extend(
            _derive_paragraph_refs(
                section_title,
                paragraph,
                paragraph.get("citations") if isinstance(paragraph.get("citations"), list) else [],
            )
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def _derive_paragraph_refs(section_title: str, paragraph: dict[str, object], citations: list[object]) -> list[str]:
    refs: list[str] = []
    paragraph_index = int(paragraph.get("index") or 0)
    if citations:
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            doc_id = str(citation.get("doc_id") or "").strip()
            page = _coerce_positive_int(citation.get("page")) or 1
            if doc_id:
                refs.append(
                    f"section_key: {section_title}, paragraph {paragraph_index}, citation: {doc_id}:p{page}"
                )
    elif paragraph_index > 0:
        refs.append(f"section_key: {section_title}, paragraph {paragraph_index}")
    return refs


def _normalize_coverage_status(value: object) -> str:
    status = str(value or "").strip().lower()
    if status in {"met", "partial", "missing"}:
        return status
    return "missing"


def _max_coverage_status(left: str, right: str) -> str:
    return right if _COVERAGE_STATUS_ORDER.get(right, 0) > _COVERAGE_STATUS_ORDER.get(left, 0) else left


def _question_word_limit(prompt: str, raw_limit: object) -> int | None:
    prompt_limit = _parse_word_limit_from_prompt(prompt)
    if prompt_limit is not None:
        return prompt_limit
    if isinstance(raw_limit, dict):
        if str(raw_limit.get("type") or "").strip().lower() == "words":
            return _coerce_positive_int(raw_limit.get("value"))
    return None


def _question_section_title(prompt: str) -> str:
    first_clause = prompt.split(":", 1)[0].strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", first_clause).strip()


def _parse_word_limit_from_prompt(prompt: str) -> int | None:
    prompt_match = re.search(r"\((\d+)\s*words?\s*max\)", prompt, flags=re.IGNORECASE)
    if prompt_match:
        return int(prompt_match.group(1))
    inline_match = re.search(r"\b(\d+)\s*words?\s*max\b", prompt, flags=re.IGNORECASE)
    if inline_match:
        return int(inline_match.group(1))
    return None


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value))


def _token_set(value: str) -> set[str]:
    normalized = _normalize_key(value)
    if not normalized:
        return set()
    return set(normalized.split())


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left:
        return 0.0
    return len(left & right) / len(left)


def _build_markdown_files(
    *,
    profile: str,
    include_debug: bool,
    project: dict[str, object],
    export_request: dict[str, object],
    intake: dict[str, object] | None,
    documents: list[dict[str, object]],
    requirements: dict[str, object] | None,
    drafts: dict[str, dict[str, object]],
    selected_sections: list[str],
    coverage_items: list[dict[str, object]],
    coverage_counts: dict[str, int],
    uncertainty: dict[str, object],
    missing_evidence: list[dict[str, object]],
    validations: dict[str, object],
    run_metadata: dict[str, object],
    summary: dict[str, object],
) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []

    requirement_rows = _build_requirement_rows(requirements, coverage_items)
    draft_application = _render_draft_application_markdown(selected_sections, drafts)
    requirements_matrix = _render_requirements_matrix_markdown(requirement_rows)
    coverage_markdown = _render_coverage_markdown(coverage_items, coverage_counts, uncertainty)
    missing_evidence_markdown = _render_missing_evidence_markdown(missing_evidence)
    validation_markdown = _render_validation_markdown(validations, include_debug)

    if profile == "hackathon":
        files.append(
            {
                "path": "README_EXPORT.md",
                "content": _render_hackathon_readme(
                    project=project,
                    export_request=export_request,
                    summary=summary,
                    documents=documents,
                    intake=intake,
                ),
            }
        )
        files.append({"path": "REQUIREMENTS_MATRIX.md", "content": requirements_matrix})
        files.append({"path": "DRAFT_APPLICATION.md", "content": draft_application})
        files.append({"path": "COVERAGE.md", "content": coverage_markdown})
        files.append({"path": "MISSING_EVIDENCE.md", "content": missing_evidence_markdown})
    elif profile == "submission":
        files.append({"path": "application.md", "content": draft_application})
        files.append(
            {
                "path": "requirements.md",
                "content": requirements_matrix,
            }
        )
        files.append({"path": "coverage.md", "content": coverage_markdown})
        files.append({"path": "missing_evidence.md", "content": missing_evidence_markdown})
    else:  # internal
        files.append({"path": "application.md", "content": draft_application})
        files.append({"path": "requirements.md", "content": requirements_matrix})
        files.append({"path": "coverage.md", "content": coverage_markdown})
        files.append({"path": "missing_evidence.md", "content": missing_evidence_markdown})
        if validation_markdown:
            files.append({"path": "validation.md", "content": validation_markdown})
        if include_debug:
            files.append(
                {
                    "path": "DEBUG_RUN.json",
                    "content": json.dumps(
                        {
                            "run_metadata": run_metadata,
                            "validations": validations,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            )

    return [file for file in files if str(file.get("content") or "").strip()]


def _render_hackathon_readme(
    *,
    project: dict[str, object],
    export_request: dict[str, object],
    summary: dict[str, object],
    documents: list[dict[str, object]],
    intake: dict[str, object] | None,
) -> str:
    lines = [
        "# Nebula Export Bundle",
        "",
        "This bundle is generated by the final-stage export packager with cite-first constraints and traceability.",
        "",
        "## Project",
        f"- ID: `{project.get('id', '')}`",
        f"- Name: {project.get('name', '')}",
        f"- Profile: {export_request.get('profile', 'hackathon')}",
        "",
        "## Summary",
        f"- Overall completion: {summary.get('overall_completion', 'unknown')}",
        f"- Coverage (met/partial/missing): {summary.get('coverage_overview', {}).get('met', 0)}/"
        f"{summary.get('coverage_overview', {}).get('partial', 0)}/"
        f"{summary.get('coverage_overview', {}).get('missing', 0)}",
        f"- Unsupported claims: {summary.get('unsupported_claims_count', 0)}",
        f"- Missing evidence items: {summary.get('missing_evidence_count', 0)}",
        "",
        "## Inputs",
        f"- Documents: {len(documents)}",
        f"- Intake present: {'yes' if intake else 'no'}",
        "",
        "## Files",
        "- `REQUIREMENTS_MATRIX.md`",
        "- `DRAFT_APPLICATION.md`",
        "- `COVERAGE.md`",
        "- `MISSING_EVIDENCE.md`",
    ]
    return "\n".join(lines).strip()


def _render_requirements_matrix_markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Requirements Matrix",
        "",
        "| requirement_id | requirement | status | notes |",
        "|---|---|---|---|",
    ]
    if not rows:
        lines.append("| n/a | No requirements available | missing |  |")
    else:
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_pipe(row.get("requirement_id", "")),
                        _escape_pipe(row.get("requirement", "")),
                        _escape_pipe(row.get("status", "")),
                        _escape_pipe(row.get("notes", "")),
                    ]
                )
                + " |"
            )
    return "\n".join(lines).strip()


def _render_draft_application_markdown(
    selected_sections: list[str],
    drafts: dict[str, dict[str, object]],
) -> str:
    lines = ["# Draft Application", ""]
    if not selected_sections:
        lines.append("_No draft sections available._")
        return "\n".join(lines).strip()

    for section_key in selected_sections:
        section_entry = drafts.get(section_key) or {}
        draft = _as_optional_dict(section_entry.get("draft")) or {}
        paragraphs = _as_dict_list(draft.get("paragraphs"))
        missing = _as_dict_list(draft.get("missing_evidence"))

        lines.append(f"## {section_key}")
        lines.append("")
        if not paragraphs:
            lines.append("_No draft paragraphs available._")
            lines.append("")
        else:
            for index, paragraph in enumerate(paragraphs, start=1):
                text = str(paragraph.get("text") or "").strip()
                unsupported = bool(paragraph.get("unsupported", False))
                if unsupported and "[UNSUPPORTED]" not in text:
                    text = f"{text} [UNSUPPORTED]"
                lines.append(f"{index}. {text}")
            lines.append("")

        citations = _collect_section_citations(paragraphs)
        lines.append("### Citations")
        if citations:
            for citation in citations:
                snippet = citation.get("snippet", "")
                lines.append(
                    f"- `{citation.get('doc_id', '')}` p{citation.get('page', '?')}: {snippet}"
                )
        else:
            lines.append("- None")
        lines.append("")

        unsupported_details = _unsupported_paragraph_descriptions(paragraphs)
        if unsupported_details or missing:
            lines.append("### Unsupported / Missing")
            for detail in unsupported_details:
                lines.append(f"- {detail}")
            for item in missing:
                claim = str(item.get("claim") or "Missing evidence item").strip()
                suggestion = str(item.get("suggested_upload") or "Upload more evidence.").strip()
                lines.append(f"- {claim} (suggested upload: {suggestion})")
            lines.append("")

    return "\n".join(lines).strip()


def _render_coverage_markdown(
    coverage_items: list[dict[str, object]],
    coverage_counts: dict[str, int],
    uncertainty: dict[str, object],
) -> str:
    met = coverage_counts.get("met", 0)
    partial = coverage_counts.get("partial", 0)
    missing = coverage_counts.get("missing", 0)
    total = met + partial + missing

    unsupported_claims = _coerce_positive_int(uncertainty.get("unsupported_claims_count"))
    citation_mismatch_count = _coerce_positive_int(uncertainty.get("citation_mismatch_count"))
    empty_required_sections_count = _coerce_positive_int(uncertainty.get("empty_required_sections_count"))
    uncertainty_penalty = _uncertainty_penalty_factor(
        total=max(total, 1),
        unsupported_claims_count=unsupported_claims or 0,
        citation_mismatch_count=citation_mismatch_count or 0,
        empty_required_sections_count=empty_required_sections_count or 0,
    )
    readiness_base = ((met + 0.5 * partial) / total * 100) if total > 0 else 0.0
    completion_base = (met / total * 100) if total > 0 else 0.0
    readiness = readiness_base * (1.0 - uncertainty_penalty)
    completion = completion_base * (1.0 - uncertainty_penalty)

    lines = [
        "# Coverage Summary",
        "",
        f"- Readiness score: {readiness:.1f}%",
        f"- Completion score: {completion:.1f}%",
        f"- Met: {met}",
        f"- Partial: {partial}",
        f"- Missing: {missing}",
    ]
    source_conflict_count = _coerce_positive_int(uncertainty.get("source_conflict_count")) or 0
    if source_conflict_count > 0:
        lines.append(f"- Source conflicts detected: {source_conflict_count}")
    if citation_mismatch_count:
        lines.append(f"- Citation mismatches detected: {citation_mismatch_count}")
    if empty_required_sections_count:
        lines.append(f"- Empty required sections detected: {empty_required_sections_count}")
    if unsupported_claims:
        lines.append(f"- Unsupported claims detected: {unsupported_claims}")

    recommendations: list[str] = []
    if source_conflict_count > 0:
        recommendations.append(
            "Resolve source conflict warning: align contradictory evidence before finalizing scores."
        )
    if (citation_mismatch_count or 0) > 0:
        recommendations.append(
            "Resolve citation mismatch warning: fix doc/page/snippet integrity and inline-vs-structured citations."
        )
    if (empty_required_sections_count or 0) > 0:
        recommendations.append(
            "Address empty required section warning: add grounded content for missing required sections."
        )
    for item in coverage_items:
        status = str(item.get("status") or "").strip().lower()
        if status not in {"missing", "partial"}:
            continue
        req_id = str(item.get("requirement_id") or "").strip() or "unknown"
        notes = str(item.get("notes") or "").strip()
        if not notes:
            notes = "Needs additional supported draft coverage."
        recommendations.append(f"`{req_id}`: {notes}")

    if recommendations:
        lines.extend(["", "## Recommended Next Edits"])
        for recommendation in recommendations[:10]:
            lines.append(f"- {recommendation}")
    else:
        lines.extend(["", "## Recommended Next Edits", "- No high-priority gaps detected."])

    return "\n".join(lines).strip()


def _render_missing_evidence_markdown(missing_evidence: list[dict[str, object]]) -> str:
    if not missing_evidence:
        return ""

    lines = [
        "# Missing Evidence",
        "",
        "| item | why | suggested uploads | impacts |",
        "|---|---|---|---|",
    ]
    for item in missing_evidence:
        claim = str(item.get("claim") or item.get("item") or "Unknown").strip()
        reason = str(item.get("reason") or item.get("why") or "Evidence gap").strip()
        suggested = item.get("suggested_doc_types")
        if isinstance(suggested, list):
            suggested_text = ", ".join(str(part) for part in suggested)
        else:
            suggested_text = str(item.get("suggested_upload") or "").strip() or "Upload supporting evidence"
        impacts = item.get("affected_requirements") or item.get("affected_sections") or item.get("impacts") or []
        if isinstance(impacts, list):
            impacts_text = ", ".join(str(part) for part in impacts) or "n/a"
        else:
            impacts_text = str(impacts).strip() or "n/a"

        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_pipe(claim),
                    _escape_pipe(reason),
                    _escape_pipe(suggested_text),
                    _escape_pipe(impacts_text),
                ]
            )
            + " |"
        )
    return "\n".join(lines).strip()


def _render_validation_markdown(validations: dict[str, object], include_debug: bool) -> str:
    if not validations:
        return ""
    if include_debug:
        return "# Validation\n\n```json\n" + json.dumps(validations, ensure_ascii=False, indent=2) + "\n```"

    failures: list[str] = []
    for key, value in validations.items():
        if isinstance(value, dict):
            repaired = value.get("repaired")
            errors = value.get("errors")
            if repaired or (isinstance(errors, list) and len(errors) > 0):
                failures.append(f"- {key}: repaired={bool(repaired)}, errors={len(errors) if isinstance(errors, list) else 0}")
    if not failures:
        return ""
    return "# Validation\n\n" + "\n".join(failures)


def _build_requirement_rows(
    requirements: dict[str, object] | None,
    coverage_items: list[dict[str, object]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    coverage_lookup = {str(item.get("requirement_id") or ""): item for item in coverage_items if isinstance(item, dict)}
    seen_requirement_ids: set[str] = set()

    if requirements:
        questions = requirements.get("questions")
        if isinstance(questions, list):
            for index, question in enumerate(questions, start=1):
                if not isinstance(question, dict):
                    continue
                req_id = str(question.get("id") or f"Q{index}")
                prompt = str(question.get("prompt") or "").strip() or f"Question {index}"
                rows.append(_build_row(req_id, prompt, coverage_lookup.get(req_id)))
                seen_requirement_ids.add(req_id)

        attachments = requirements.get("required_attachments")
        if isinstance(attachments, list):
            attachment_index = 1
            for attachment in attachments:
                text = str(attachment).strip()
                if not text:
                    continue
                req_id = f"A{attachment_index}"
                rows.append(_build_row(req_id, text, coverage_lookup.get(req_id)))
                seen_requirement_ids.add(req_id)
                attachment_index += 1

        for key_prefix, source_key in [("E", "eligibility"), ("R", "rubric"), ("D", "disallowed_costs")]:
            entries = requirements.get(source_key)
            if not isinstance(entries, list):
                continue
            for index, value in enumerate(entries, start=1):
                text = str(value).strip()
                if not text:
                    continue
                req_id = f"{key_prefix}{index}"
                rows.append(_build_row(req_id, text, coverage_lookup.get(req_id)))
                seen_requirement_ids.add(req_id)

    for item in coverage_items:
        req_id = str(item.get("requirement_id") or "").strip()
        if not req_id or req_id in seen_requirement_ids:
            continue
        rows.append(_build_row(req_id, f"Unknown requirement ({req_id})", item))
        seen_requirement_ids.add(req_id)

    return rows


def _build_row(requirement_id: str, requirement: str, coverage_item: dict[str, object] | None) -> dict[str, str]:
    if not coverage_item:
        return {
            "requirement_id": requirement_id,
            "requirement": requirement,
            "status": "missing",
            "notes": "No coverage item returned.",
        }
    return {
        "requirement_id": requirement_id,
        "requirement": requirement,
        "status": str(coverage_item.get("status") or "missing"),
        "notes": str(coverage_item.get("notes") or ""),
    }


def _prepare_drafts_for_export(
    *,
    drafts_map: dict[str, dict[str, object]],
    selected_sections: list[str],
    valid_doc_ids: set[str],
    doc_page_counts: dict[str, int],
) -> tuple[dict[str, dict[str, object]], int, list[str], dict[str, object]]:
    unsupported_claims_count = 0
    warnings: list[str] = []
    invalid_doc_ids: set[str] = set()
    citation_mismatch_count = 0
    exported: dict[str, dict[str, object]] = {}

    for section_key in selected_sections:
        source_entry = drafts_map.get(section_key) or {}
        draft_payload = _as_optional_dict(source_entry.get("draft")) or {}
        artifact = _as_optional_dict(source_entry.get("artifact")) or {}
        paragraphs = _as_dict_list(draft_payload.get("paragraphs"))
        missing_evidence = _as_dict_list(draft_payload.get("missing_evidence"))
        processed_paragraphs: list[dict[str, object]] = []

        for paragraph in paragraphs:
            text = str(paragraph.get("text") or "").strip()
            confidence = _coerce_confidence(paragraph.get("confidence"))
            raw_citations = paragraph.get("citations")
            citations = _as_dict_list(raw_citations)
            normalized_citations: list[dict[str, object]] = []

            for citation in citations:
                doc_id = str(citation.get("doc_id") or "").strip()
                page = _coerce_positive_int(citation.get("page"))
                snippet = str(citation.get("snippet") or "").strip()
                if len(snippet) > 240:
                    snippet = snippet[:237].rstrip() + "..."
                    warnings.append(f"Citation snippet truncated to 240 chars in section '{section_key}'.")

                if doc_id and doc_id not in valid_doc_ids:
                    invalid_doc_ids.add(doc_id)
                    citation_mismatch_count += 1
                    warnings.append(
                        f"Citation mismatch in section '{section_key}': doc_id '{doc_id}' not in document registry."
                    )
                if doc_id and page is not None:
                    max_page = doc_page_counts.get(doc_id)
                    if max_page is not None and page > max_page:
                        citation_mismatch_count += 1
                        warnings.append(
                            f"Citation page out of bounds for doc '{doc_id}' in section '{section_key}' "
                            f"(page {page}, max {max_page})."
                        )
                if not snippet:
                    citation_mismatch_count += 1
                    warnings.append(
                        f"Citation mismatch in section '{section_key}': missing snippet for doc '{doc_id or 'unknown'}'."
                    )

                normalized_citations.append(
                    {
                        "doc_id": doc_id,
                        "page": page if page is not None else 1,
                        "snippet": snippet,
                    }
                )

            inline_hint_pairs = _extract_inline_citation_pairs(text)
            structured_pairs = {
                (str(citation.get("doc_id") or "").strip(), _coerce_positive_int(citation.get("page")) or 1)
                for citation in normalized_citations
            }
            for inline_hint in inline_hint_pairs:
                if inline_hint not in structured_pairs:
                    citation_mismatch_count += 1
                    warnings.append(
                        f"Citation mismatch in section '{section_key}': inline hint {inline_hint[0]} p{inline_hint[1]} "
                        "not represented in structured citations."
                    )

            unsupported = (
                len(normalized_citations) == 0
                or "[UNSUPPORTED]" in text
                or confidence < _MIN_CONFIDENCE_FOR_SUPPORTED
                or len(inline_hint_pairs) > 0 and any(hint not in structured_pairs for hint in inline_hint_pairs)
            )
            if unsupported:
                unsupported_claims_count += 1

            processed_paragraphs.append(
                {
                    "text": text,
                    "citations": normalized_citations,
                    "confidence": confidence,
                    "unsupported": unsupported,
                }
            )

        exported[section_key] = {
            "draft": {
                "section_key": str(draft_payload.get("section_key") or section_key),
                "paragraphs": processed_paragraphs,
                "missing_evidence": missing_evidence,
            },
            "artifact": {
                "id": str(artifact.get("id") or ""),
                "updated_at": str(artifact.get("updated_at") or artifact.get("created_at") or ""),
                "source": str(artifact.get("source") or ""),
            },
        }

    return exported, unsupported_claims_count, warnings, {
        "invalid_doc_ids": invalid_doc_ids,
        "citation_mismatch_count": citation_mismatch_count,
    }


def _merge_missing_evidence(
    base_items: list[dict[str, object]],
    drafts: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()

    for item in base_items:
        key = json.dumps(item, ensure_ascii=True, sort_keys=True)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)

    for section_key, section in drafts.items():
        draft = _as_optional_dict(section.get("draft")) or {}
        missing = _as_dict_list(draft.get("missing_evidence"))
        for item in missing:
            normalized = {
                **item,
                "affected_sections": _append_unique(_as_str_list(item.get("affected_sections")), section_key),
            }
            key = json.dumps(normalized, ensure_ascii=True, sort_keys=True)
            if key in seen:
                continue
            merged.append(normalized)
            seen.add(key)

    return merged


def _extract_constraints(requirements: dict[str, object] | None) -> tuple[list[str], list[str]]:
    known: list[str] = []
    unknown: list[str] = []

    if requirements is None:
        unknown.append("requirements unavailable")
        return known, unknown

    deadline = str(requirements.get("deadline") or "").strip()
    if deadline:
        known.append(f"deadline: {deadline}")
    else:
        unknown.append("deadline constraint missing")

    questions = requirements.get("questions")
    if not isinstance(questions, list) or len(questions) == 0:
        unknown.append("question constraints missing")
        return known, unknown

    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or f"Q{index}")
        limit = question.get("limit")
        if not isinstance(limit, dict):
            unknown.append(f"{question_id}: limit not specified")
            continue
        limit_type = str(limit.get("type") or "none").strip().lower()
        limit_value = _coerce_positive_int(limit.get("value"))
        if limit_type in {"words", "chars"} and limit_value is not None:
            known.append(f"{question_id}: {limit_value} {limit_type}")
        elif limit_type == "none":
            unknown.append(f"{question_id}: limit not specified")
        else:
            unknown.append(f"{question_id}: constraint_unknown")

    return known, unknown


def _compute_completion(
    coverage_counts: dict[str, int],
    *,
    unsupported_claims_count: int = 0,
    citation_mismatch_count: int = 0,
    empty_required_sections_count: int = 0,
) -> float | None:
    total = coverage_counts.get("met", 0) + coverage_counts.get("partial", 0) + coverage_counts.get("missing", 0)
    if total <= 0:
        return None
    score = coverage_counts.get("met", 0) + 0.5 * coverage_counts.get("partial", 0)
    base = (score / total) * 100
    penalty = _uncertainty_penalty_factor(
        total=total,
        unsupported_claims_count=unsupported_claims_count,
        citation_mismatch_count=citation_mismatch_count,
        empty_required_sections_count=empty_required_sections_count,
    )
    return base * (1.0 - penalty)


def _coverage_counts(coverage_items: list[dict[str, object]]) -> dict[str, int]:
    counts = {"met": 0, "partial": 0, "missing": 0}
    for item in coverage_items:
        status = str(item.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    return counts


def _resolve_section_order(
    *,
    requirements: dict[str, object] | None,
    available_sections: list[str],
    requested_sections: list[str],
) -> list[str]:
    if requested_sections:
        return _dedupe_preserve_order(requested_sections)

    if not available_sections:
        return []

    remaining = {key: key for key in available_sections}
    ordered: list[str] = []

    if requirements:
        questions = requirements.get("questions")
        if isinstance(questions, list):
            normalized_lookup = {_normalize_key(name): name for name in available_sections}
            for question in questions:
                if not isinstance(question, dict):
                    continue
                prompt = str(question.get("prompt") or "").strip()
                if not prompt:
                    continue
                for candidate in _section_candidates_from_prompt(prompt):
                    section = normalized_lookup.get(_normalize_key(candidate))
                    if section and section in remaining:
                        ordered.append(section)
                        remaining.pop(section, None)
                        break

    ordered.extend(sorted(remaining.keys(), key=lambda value: value.lower()))
    return ordered


def _section_candidates_from_prompt(prompt: str) -> list[str]:
    trimmed = prompt.strip()
    first_clause = trimmed.split(":")[0].strip() if ":" in trimmed else trimmed
    without_parens = re.sub(r"\s*\([^)]*\)\s*$", "", first_clause).strip()
    candidates = [trimmed, first_clause, without_parens]
    return [candidate for candidate in candidates if candidate]


def _build_document_lookup(documents: list[dict[str, object]]) -> tuple[set[str], dict[str, int]]:
    valid_doc_ids: set[str] = set()
    page_counts: dict[str, int] = {}
    for document in documents:
        doc_id = str(document.get("doc_id") or "").strip()
        file_name = str(document.get("file_name") or "").strip()
        database_id = str(document.get("id") or "").strip()
        for candidate in [doc_id, file_name, database_id]:
            if candidate:
                valid_doc_ids.add(candidate)
        max_page = _coerce_positive_int(document.get("page_count"))
        if max_page is not None:
            for candidate in [doc_id, file_name, database_id]:
                if candidate:
                    page_counts[candidate] = max_page
    return valid_doc_ids, page_counts


def _normalize_drafts(raw_drafts: object) -> dict[str, dict[str, object]]:
    normalized: dict[str, dict[str, object]] = {}
    if isinstance(raw_drafts, dict):
        for maybe_key, maybe_value in raw_drafts.items():
            key = str(maybe_key).strip()
            value = _as_optional_dict(maybe_value)
            if value is None:
                continue
            if isinstance(value.get("draft"), dict):
                draft = _as_optional_dict(value.get("draft")) or {}
                artifact = _as_optional_dict(value.get("artifact")) or {}
            elif "paragraphs" in value:
                draft = value
                artifact = {}
            else:
                draft = {}
                artifact = {}
            section_key = str(draft.get("section_key") or key).strip() or key
            if not section_key:
                continue
            normalized[section_key] = {
                "draft": draft,
                "artifact": artifact,
            }
    return normalized


def _collect_section_citations(paragraphs: list[dict[str, object]]) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        refs = paragraph.get("citations")
        if not isinstance(refs, list):
            continue
        for citation in refs:
            if not isinstance(citation, dict):
                continue
            key = (
                str(citation.get("doc_id") or "").strip(),
                str(citation.get("page") or "").strip(),
                str(citation.get("snippet") or "").strip(),
            )
            encoded = "|".join(key)
            if encoded in seen:
                continue
            seen.add(encoded)
            citations.append(
                {
                    "doc_id": key[0],
                    "page": key[1],
                    "snippet": key[2],
                }
            )
    return citations


def _extract_inline_citation_pairs(paragraph_text: str) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for match in _INLINE_CITATION_HINT_PATTERN.finditer(paragraph_text):
        doc_id = str(match.group(1) or "").strip()
        page = _coerce_positive_int(match.group(2))
        if doc_id and page is not None:
            pairs.append((doc_id, page))
    return pairs


def _uncertainty_penalty_factor(
    *,
    total: int,
    unsupported_claims_count: int,
    citation_mismatch_count: int,
    empty_required_sections_count: int,
) -> float:
    denominator = max(total, 1)
    weighted = (
        unsupported_claims_count * 1.0
        + citation_mismatch_count * 1.25
        + empty_required_sections_count * 1.5
    )
    return min(0.6, (weighted / denominator) * 0.12)


def _derive_coverage_uncertainty_signals(
    *,
    requirements: dict[str, object] | None,
    coverage_items: list[dict[str, object]],
    section_stats: dict[str, dict[str, object]],
) -> dict[str, object]:
    empty_required_sections_count = 0
    source_conflict_count = 0
    warnings: list[str] = []

    expected_sections: list[str] = []
    if requirements and isinstance(requirements.get("questions"), list):
        for index, question in enumerate(requirements["questions"], start=1):
            if not isinstance(question, dict):
                continue
            req_id = str(question.get("id") or f"Q{index}").strip() or f"Q{index}"
            prompt = str(question.get("prompt") or "").strip()
            section_title = _NARRATIVE_REQUIREMENT_SECTION_MAP.get(req_id.upper()) or _question_section_title(prompt)
            if section_title:
                expected_sections.append(section_title)

    for section_title in expected_sections:
        section = _match_expected_section(section_stats, section_title)
        if section is None or not bool(section.get("substantive")):
            empty_required_sections_count += 1

    for item in coverage_items:
        if not isinstance(item, dict):
            continue
        req_id = str(item.get("requirement_id") or "").strip()
        status = _normalize_coverage_status(item.get("status"))
        if not req_id or status == "missing":
            continue
        refs = _as_str_list(item.get("evidence_refs"))
        doc_ids = _doc_ids_from_evidence_refs(refs)
        if len(doc_ids) >= 2 and req_id.upper().startswith("Q"):
            source_conflict_count += 1

    if source_conflict_count > 0:
        warnings.append("source conflict warning")
    if empty_required_sections_count > 0:
        warnings.append("empty required section warning")
    return {
        "source_conflict_count": source_conflict_count,
        "empty_required_sections_count": empty_required_sections_count,
        "warnings": warnings,
    }


def _doc_ids_from_evidence_refs(refs: list[str]) -> set[str]:
    doc_ids: set[str] = set()
    for ref in refs:
        citation_match = re.search(r"citation:\s*([^,\s]+)", ref, flags=re.IGNORECASE)
        if citation_match:
            doc_token = citation_match.group(1).strip()
            doc_ids.add(doc_token.split(":p", 1)[0].strip())
            continue
        plain_match = re.search(r"([a-z0-9._-]+\.[a-z0-9]{2,6})(?::p\d+)?", ref, flags=re.IGNORECASE)
        if plain_match:
            doc_ids.add(plain_match.group(1).strip())
    return doc_ids


def _has_attachment_grounded_evidence(
    *,
    requirement_id: str,
    requirement_text: str,
    evidence_refs: list[str],
) -> bool:
    doc_ids = _doc_ids_from_evidence_refs(evidence_refs)
    if not doc_ids:
        return False
    attachment_number = _coerce_positive_int(re.sub(r"^[Aa]", "", requirement_id.strip()))
    requirement_tokens = {
        token for token in _token_set(requirement_text) if token and token not in _ATTACHMENT_NOISE_TOKENS
    }

    for doc_id in doc_ids:
        doc_tokens = _token_set(doc_id)
        if "attachment" in doc_tokens or "appendix" in doc_tokens:
            return True
        if attachment_number is not None and (
            f"attachment{attachment_number}" in _normalize_key(doc_id).replace(" ", "")
            or f"a{attachment_number}" in _normalize_key(doc_id).replace(" ", "")
        ):
            return True
        if requirement_tokens and len(requirement_tokens & doc_tokens) > 0:
            return True
    return False


def _unsupported_paragraph_descriptions(paragraphs: list[dict[str, object]]) -> list[str]:
    messages: list[str] = []
    for index, paragraph in enumerate(paragraphs, start=1):
        if bool(paragraph.get("unsupported", False)):
            messages.append(f"Paragraph {index} has no grounded citations.")
    return messages


def _redact_value(value: object, warnings: list[str]) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {
                "aws_secret_access_key",
                "aws_session_token",
                "session_token",
                "access_token",
                "api_key",
                "private_key",
                "secret",
                "password",
            }:
                redacted[key] = "[REDACTED]"
                warnings.append(f"Redacted sensitive key: {key}")
            else:
                redacted[key] = _redact_value(item, warnings)
        return redacted

    if isinstance(value, list):
        return [_redact_value(item, warnings) for item in value]

    if isinstance(value, str):
        text = value
        if _PRIVATE_KEY_PATTERN.search(text):
            warnings.append("Redacted private key material in run metadata.")
            text = _PRIVATE_KEY_PATTERN.sub("[REDACTED]", text)
        if _AWS_ACCESS_KEY_PATTERN.search(text):
            warnings.append("Redacted AWS access key material in run metadata.")
            text = _AWS_ACCESS_KEY_PATTERN.sub("[REDACTED]", text)
        if _AWS_SECRET_INLINE_PATTERN.search(text):
            warnings.append("Redacted AWS secret key material in run metadata.")
            text = _AWS_SECRET_INLINE_PATTERN.sub(r"\1[REDACTED]", text)
        if "secret" in text.lower() and "[REDACTED]" not in text:
            parts = text.split(":")
            if len(parts) > 1 and "secret" in parts[0].lower():
                warnings.append("Redacted secret-labeled run metadata value.")
                return f"{parts[0]}: [REDACTED]"
        return text

    return value


def _append_unique(values: list[str], item: str) -> list[str]:
    if item in values:
        return values
    return [*values, item]


def _coerce_sections(value: object) -> list[str]:
    if isinstance(value, list):
        return _dedupe_preserve_order([str(item).strip() for item in value if str(item).strip()])
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return _dedupe_preserve_order([part for part in parts if part])
    return []


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _as_optional_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _coerce_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return None
    return parsed


def _coerce_confidence(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return round(parsed, 3)


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
