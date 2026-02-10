from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.export.policy import (
    derive_section_title_from_prompt,
    expected_section_for_requirement,
    is_boilerplate_paragraph,
    normalize_key,
    normalize_text,
    parse_word_limit,
    word_count,
)

_INLINE_CITATION_HINT_PATTERN = re.compile(
    r"\(\s*(?:doc(?:_id)?|source)\s*[:=]\s*([^,)\n]+)\s*,\s*page\s*[:=]\s*(\d+)\s*\)",
    flags=re.IGNORECASE,
)
_MIN_CONFIDENCE_FOR_SUPPORTED = 0.35


@dataclass
class RequirementRow:
    requirement_id: str
    requirement: str
    status: str
    evidence_pointers: str
    notes: str
    word_limit: int | None = None


@dataclass
class CoverageRow:
    requirement_id: str
    status: str
    notes: str
    evidence_refs: str


class ExportCompositionError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def compose_markdown_report(
    *,
    project_name: str,
    intake: dict[str, object] | None,
    documents: list[dict[str, object]],
    requirements: dict[str, object] | None,
    drafts: dict[str, dict[str, object]],
    coverage: dict[str, object] | None,
    missing_evidence: list[dict[str, object]] | None,
    validations: dict[str, object] | None,
) -> str:
    del intake
    del validations

    missing_evidence = missing_evidence or []
    valid_doc_ids, page_counts = _document_registry(documents)
    section_limits = _section_word_limits(requirements)
    sections = _prepare_sections(
        drafts=drafts,
        section_limits=section_limits,
        requirements=requirements,
        valid_doc_ids=valid_doc_ids,
        page_counts=page_counts,
    )

    requirement_defs = _build_requirement_definitions(requirements)
    if requirements is not None and len(requirement_defs) == 0:
        raise ExportCompositionError(["Requirements exist but cannot be rendered as a table."])

    coverage_lookup = _coverage_lookup(coverage)
    requirement_rows = _build_requirement_rows(
        requirement_defs=requirement_defs,
        coverage_lookup=coverage_lookup,
        sections=sections,
    )
    coverage_rows = _build_coverage_rows(
        requirement_defs=requirement_defs,
        coverage_lookup=coverage_lookup,
        sections=sections,
    )

    errors = _run_quality_gates(
        sections=sections,
        valid_doc_ids=valid_doc_ids,
        requirements=requirements,
        requirement_rows=requirement_rows,
    )
    if errors:
        raise ExportCompositionError(errors)

    title_name = _resolve_title_name(requirements=requirements, project_name=project_name)
    lines: list[str] = [f"# Draft for {title_name} Demo", "", "## Draft Application", ""]

    previous_citation_signature = ""
    for section in sections:
        lines.append(f"### {section['title']}")
        lines.append("")
        for index, paragraph in enumerate(section["paragraphs"], start=1):
            lines.append(f"{index}. {paragraph['text']}")
        lines.append("")

        citation_lines = _render_citations(section["citations"])
        citation_signature = "|".join(citation_lines)
        if citation_lines and citation_signature != previous_citation_signature:
            lines.append("### Citations")
            lines.extend(citation_lines)
            lines.append("")
        previous_citation_signature = citation_signature

        unsupported = _section_unsupported_notes(section["paragraphs"])
        if unsupported:
            lines.append("### Unsupported / Missing")
            lines.extend(f"- {note}" for note in unsupported)
            lines.append("")

    lines.extend(
        [
            "## Requirements Matrix",
            "",
            "| requirement_id | requirement | status | evidence pointers | notes |",
            "|---|---|---|---|---|",
        ]
    )
    for row in requirement_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table(row.requirement_id),
                    _escape_table(row.requirement),
                    _escape_table(row.status),
                    _escape_table(row.evidence_pointers),
                    _escape_table(row.notes),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Coverage",
            "",
            "| requirement_id | status | notes | evidence_refs |",
            "|---|---|---|---|",
        ]
    )
    for row in coverage_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table(row.requirement_id),
                    _escape_table(row.status),
                    _escape_table(row.notes),
                    _escape_table(row.evidence_refs),
                ]
            )
            + " |"
        )

    if missing_evidence:
        lines.extend(["", "## Missing Evidence", ""])
        for item in missing_evidence:
            claim = str(item.get("claim") or item.get("item") or "Missing evidence").strip()
            suggestion = str(item.get("suggested_upload") or "Upload supporting document").strip()
            lines.append(f"- {claim} (suggested upload: {suggestion})")

    return "\n".join(lines).strip() + "\n"


def _resolve_title_name(requirements: dict[str, object] | None, project_name: str) -> str:
    if requirements and isinstance(requirements.get("funder"), str) and str(requirements["funder"]).strip():
        return str(requirements["funder"]).strip()
    return project_name.strip() or "Opportunity"


def _document_registry(documents: list[dict[str, object]]) -> tuple[set[str], dict[str, int]]:
    valid_ids: set[str] = set()
    page_counts: dict[str, int] = {}
    for doc in documents:
        max_page = None
        try:
            max_page = int(doc.get("page_count"))
        except (TypeError, ValueError):
            max_page = None
        for key in ("doc_id", "file_name", "id"):
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                doc_key = value.strip()
                valid_ids.add(doc_key)
                if max_page and max_page > 0:
                    page_counts[doc_key] = max_page
    return valid_ids, page_counts


def _section_word_limits(requirements: dict[str, object] | None) -> dict[str, int]:
    limits: dict[str, int] = {}
    if not requirements:
        return limits
    questions = requirements.get("questions")
    if not isinstance(questions, list):
        return limits
    for question in questions:
        if not isinstance(question, dict):
            continue
        prompt = str(question.get("prompt") or "").strip()
        if not prompt:
            continue
        section_title = derive_section_title_from_prompt(prompt)
        limit = parse_word_limit(prompt)
        raw_limit = question.get("limit")
        if limit is None and isinstance(raw_limit, dict):
            limit_type = str(raw_limit.get("type") or "").strip().lower()
            if limit_type == "words":
                try:
                    limit = int(raw_limit.get("value"))
                except (TypeError, ValueError):
                    limit = None
        if limit and limit > 0:
            limits[normalize_key(section_title)] = limit
    return limits


def _ordered_section_keys(drafts: dict[str, dict[str, object]], requirements: dict[str, object] | None) -> list[str]:
    available = {normalize_key(key): key for key in drafts.keys()}
    ordered: list[str] = []

    if requirements and isinstance(requirements.get("questions"), list):
        for question in requirements["questions"]:
            if not isinstance(question, dict):
                continue
            prompt = str(question.get("prompt") or "").strip()
            if not prompt:
                continue
            title = derive_section_title_from_prompt(prompt)
            key = available.get(normalize_key(title))
            if key and key not in ordered:
                ordered.append(key)

    for section_key in sorted(drafts.keys(), key=lambda item: item.lower()):
        if section_key not in ordered:
            ordered.append(section_key)
    return ordered


def _prepare_sections(
    *,
    drafts: dict[str, dict[str, object]],
    section_limits: dict[str, int],
    requirements: dict[str, object] | None,
    valid_doc_ids: set[str],
    page_counts: dict[str, int],
) -> list[dict[str, object]]:
    prepared: list[dict[str, object]] = []

    for section_key in _ordered_section_keys(drafts, requirements):
        payload = drafts.get(section_key) or {}
        paragraphs = payload.get("paragraphs")
        if not isinstance(paragraphs, list):
            continue

        title = str(payload.get("section_key") or section_key).strip() or section_key
        if normalize_key(title) in {"draft application"}:
            continue

        parsed_paragraphs: list[dict[str, object]] = []
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            text = normalize_text(str(paragraph.get("text") or ""))
            if not text:
                continue
            citations = _normalize_citations(paragraph.get("citations"))
            confidence = paragraph.get("confidence")
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                confidence_value = 0.0
            boilerplate = is_boilerplate_paragraph(text, len(citations))
            if boilerplate and len(citations) == 0:
                continue
            unsupported = False
            integrity_failures = _citation_integrity_issues(
                text=text,
                citations=citations,
                valid_doc_ids=valid_doc_ids,
                page_counts=page_counts,
            )
            if len(citations) == 0 or confidence_value < _MIN_CONFIDENCE_FOR_SUPPORTED or integrity_failures:
                if "[UNSUPPORTED]" not in text:
                    text = f"{text} [UNSUPPORTED]"
                unsupported = True
            parsed_paragraphs.append(
                {
                    "text": text,
                    "citations": citations,
                    "boilerplate": boilerplate,
                    "unsupported": unsupported,
                    "confidence": confidence_value,
                    "integrity_failures": integrity_failures,
                    "word_count": word_count(text),
                }
            )

        if len(parsed_paragraphs) == 0:
            continue

        limit = section_limits.get(normalize_key(title))
        if limit and _section_word_count(parsed_paragraphs) > limit:
            parsed_paragraphs = _trim_section_to_word_limit(parsed_paragraphs, limit)

        total_words = _section_word_count(parsed_paragraphs)
        non_empty = [item for item in parsed_paragraphs if item["text"].strip()]
        if len(non_empty) < 2:
            continue
        if total_words < 80:
            continue
        if all(bool(item["boilerplate"]) for item in non_empty):
            continue

        citations = _dedupe_citations(
            citation
            for paragraph in parsed_paragraphs
            for citation in paragraph["citations"]
        )

        prepared.append(
            {
                "title": title,
                "paragraphs": parsed_paragraphs,
                "citations": citations,
                "word_count": total_words,
                "word_limit": limit,
            }
        )
    return prepared


def _trim_section_to_word_limit(paragraphs: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    kept = [dict(item) for item in paragraphs]
    while len(kept) > 1 and _section_word_count(kept) > limit:
        citation_frequency: dict[tuple[str, int, str], int] = {}
        for paragraph in kept:
            for citation in paragraph["citations"]:
                key = (
                    citation["doc_id"],
                    citation["page"],
                    citation["snippet"][:60],
                )
                citation_frequency[key] = citation_frequency.get(key, 0) + 1

        scored_candidates: list[tuple[int, tuple[int, int, int, int], dict[str, object]]] = []
        for index, paragraph in enumerate(kept):
            citations = paragraph["citations"]
            has_unique_citation = False
            for citation in citations:
                key = (citation["doc_id"], citation["page"], citation["snippet"][:60])
                if citation_frequency.get(key, 0) == 1:
                    has_unique_citation = True
                    break
            priority = (
                0 if paragraph["boilerplate"] else 1,
                0 if not has_unique_citation else 1,
                len(citations),
                paragraph["word_count"],
            )
            scored_candidates.append((index, priority, paragraph))

        scored_candidates.sort(key=lambda item: item[1])
        remove_index = scored_candidates[0][0]
        kept.pop(remove_index)

    if _section_word_count(kept) > limit and kept:
        final = kept[-1]
        words = final["text"].split()
        truncated = " ".join(words[: max(1, limit)])
        if len(final["citations"]) == 0 and "[UNSUPPORTED]" not in truncated:
            truncated = f"{truncated} [UNSUPPORTED]"
        final["text"] = truncated.strip()
        final["word_count"] = word_count(final["text"])
    return kept


def _section_word_count(paragraphs: list[dict[str, object]]) -> int:
    return sum(int(item.get("word_count", 0)) for item in paragraphs)


def _extract_inline_citation_pairs(text: str) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for match in _INLINE_CITATION_HINT_PATTERN.finditer(text):
        doc_id = str(match.group(1) or "").strip()
        try:
            page = int(match.group(2))
        except (TypeError, ValueError):
            continue
        if doc_id and page > 0:
            pairs.append((doc_id, page))
    return pairs


def _citation_integrity_issues(
    *,
    text: str,
    citations: list[dict[str, object]],
    valid_doc_ids: set[str],
    page_counts: dict[str, int],
) -> list[str]:
    issues: list[str] = []
    for citation in citations:
        doc_id = str(citation.get("doc_id") or "").strip()
        page = int(citation.get("page") or 1)
        snippet = str(citation.get("snippet") or "").strip()
        if not doc_id or doc_id not in valid_doc_ids:
            issues.append("citation doc missing from registry")
        if page <= 0:
            issues.append("citation page invalid")
        max_page = page_counts.get(doc_id)
        if max_page is not None and page > max_page:
            issues.append("citation page out of bounds")
        if not snippet:
            issues.append("citation snippet missing")

    inline_pairs = _extract_inline_citation_pairs(text)
    if inline_pairs:
        structured_pairs = {
            (str(citation.get("doc_id") or "").strip(), int(citation.get("page") or 1))
            for citation in citations
        }
        for hint in inline_pairs:
            if hint not in structured_pairs:
                issues.append("inline citation hint mismatch")
    return issues


def _normalize_citations(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, object]] = []
    for citation in raw:
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id") or "").strip()
        if not doc_id:
            continue
        try:
            page = int(citation.get("page"))
        except (TypeError, ValueError):
            page = 1
        snippet = normalize_text(str(citation.get("snippet") or ""))
        normalized.append({"doc_id": doc_id, "page": page, "snippet": snippet})
    return normalized


def _dedupe_citations(citations: Any) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, int, str]] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id") or "").strip()
        page = int(citation.get("page") or 1)
        snippet = str(citation.get("snippet") or "").strip()
        key = (doc_id, page, snippet[:60])
        if not doc_id or key in seen:
            continue
        seen.add(key)
        deduped.append({"doc_id": doc_id, "page": page, "snippet": snippet})
    return deduped


def _render_citations(citations: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for citation in citations:
        lines.append(
            f"- `{citation['doc_id']}` p{citation['page']}: {citation['snippet']}"
        )
    return lines


def _section_unsupported_notes(paragraphs: list[dict[str, object]]) -> list[str]:
    notes: list[str] = []
    for index, paragraph in enumerate(paragraphs, start=1):
        if paragraph.get("unsupported"):
            notes.append(f"Paragraph {index} lacks grounded citations and is marked [UNSUPPORTED].")
    return notes


def _build_requirement_definitions(requirements: dict[str, object] | None) -> list[dict[str, object]]:
    if requirements is None:
        return []
    rows: list[dict[str, object]] = []

    questions = requirements.get("questions")
    if isinstance(questions, list):
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            req_id = str(question.get("id") or f"Q{index}")
            prompt = str(question.get("prompt") or "").strip()
            if not prompt:
                continue
            limit = parse_word_limit(prompt)
            raw_limit = question.get("limit")
            if limit is None and isinstance(raw_limit, dict):
                if str(raw_limit.get("type") or "").lower() == "words":
                    try:
                        limit = int(raw_limit.get("value"))
                    except (TypeError, ValueError):
                        limit = None
            rows.append({"requirement_id": req_id, "requirement": prompt, "word_limit": limit})

    attachments = requirements.get("required_attachments")
    if isinstance(attachments, list):
        for index, item in enumerate(attachments, start=1):
            text = str(item).strip()
            if text:
                rows.append({"requirement_id": f"A{index}", "requirement": text, "word_limit": None})

    for prefix, key in [("E", "eligibility"), ("R", "rubric"), ("D", "disallowed_costs")]:
        entries = requirements.get(key)
        if not isinstance(entries, list):
            continue
        for index, item in enumerate(entries, start=1):
            text = str(item).strip()
            if text:
                rows.append({"requirement_id": f"{prefix}{index}", "requirement": text, "word_limit": None})

    return rows


def _coverage_lookup(coverage: dict[str, object] | None) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {}
    if not coverage:
        return lookup
    items = coverage.get("items")
    if not isinstance(items, list):
        return lookup
    for item in items:
        if not isinstance(item, dict):
            continue
        req_id = str(item.get("requirement_id") or "").strip()
        if req_id:
            lookup[req_id] = item
    return lookup


def _build_requirement_rows(
    *,
    requirement_defs: list[dict[str, object]],
    coverage_lookup: dict[str, dict[str, object]],
    sections: list[dict[str, object]],
) -> list[RequirementRow]:
    rows: list[RequirementRow] = []
    sections_by_key = {normalize_key(section["title"]): section for section in sections}

    for definition in requirement_defs:
        req_id = str(definition["requirement_id"])
        req_text = str(definition["requirement"])
        word_limit = definition.get("word_limit")
        coverage_item = coverage_lookup.get(req_id)

        status = str((coverage_item or {}).get("status") or "missing").lower()
        if status not in {"met", "partial", "missing"}:
            status = "missing"
        notes = str((coverage_item or {}).get("notes") or "No coverage item returned.").strip()
        refs = (coverage_item or {}).get("evidence_refs")
        evidence_refs = [str(ref).strip() for ref in refs] if isinstance(refs, list) else []

        expected_section = expected_section_for_requirement(req_id)
        if expected_section:
            section = sections_by_key.get(normalize_key(expected_section))
            if section:
                inferred = _inferred_status_for_section(section, word_limit)
                status = _max_status(status, inferred)
                derived_refs = _derive_section_evidence_refs(section)
                if status in {"partial", "met"} and (not evidence_refs or not _refs_match_section(evidence_refs, expected_section)):
                    evidence_refs = derived_refs
                if status == "missing":
                    notes = f"The draft artifact does not include a substantive {expected_section.lower()} section."
                elif status == "partial":
                    notes = f"The draft artifact includes a substantive {expected_section.lower()} section with partial compliance."
                else:
                    notes = f"The draft artifact includes a substantive {expected_section.lower()} section."

        rows.append(
            RequirementRow(
                requirement_id=req_id,
                requirement=req_text,
                status=status,
                evidence_pointers=", ".join(evidence_refs),
                notes=notes,
                word_limit=word_limit if isinstance(word_limit, int) else None,
            )
        )

    return rows


def _build_coverage_rows(
    *,
    requirement_defs: list[dict[str, object]],
    coverage_lookup: dict[str, dict[str, object]],
    sections: list[dict[str, object]],
) -> list[CoverageRow]:
    requirement_rows = _build_requirement_rows(
        requirement_defs=requirement_defs,
        coverage_lookup=coverage_lookup,
        sections=sections,
    )
    return [
        CoverageRow(
            requirement_id=row.requirement_id,
            status=row.status,
            notes=row.notes,
            evidence_refs=row.evidence_pointers,
        )
        for row in requirement_rows
    ]


def _inferred_status_for_section(section: dict[str, object], word_limit: object) -> str:
    has_citations = len(section["citations"]) > 0
    within_limit = True
    if isinstance(word_limit, int) and word_limit > 0:
        within_limit = int(section["word_count"]) <= word_limit
    if has_citations and within_limit:
        return "met"
    return "partial"


def _derive_section_evidence_refs(section: dict[str, object]) -> list[str]:
    refs: list[str] = []
    for index, paragraph in enumerate(section["paragraphs"], start=1):
        citations = paragraph.get("citations") or []
        if citations:
            first = citations[0]
            refs.append(f"section_key: {section['title']}, paragraph {index}, citation: {first['doc_id']}")
        else:
            refs.append(f"section_key: {section['title']}, paragraph {index}")
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def _refs_match_section(refs: list[str], section_title: str) -> bool:
    expected = normalize_key(section_title)
    for ref in refs:
        if normalize_key(ref).find(expected) != -1:
            return True
    return False


def _max_status(left: str, right: str) -> str:
    order = {"missing": 0, "partial": 1, "met": 2}
    return right if order.get(right, 0) > order.get(left, 0) else left


def _run_quality_gates(
    *,
    sections: list[dict[str, object]],
    valid_doc_ids: set[str],
    requirements: dict[str, object] | None,
    requirement_rows: list[RequirementRow],
) -> list[str]:
    errors: list[str] = []

    for section in sections:
        for paragraph in section["paragraphs"]:
            citations = paragraph.get("citations") or []
            text = str(paragraph.get("text") or "")
            if len(citations) == 0 and "[UNSUPPORTED]" not in text:
                errors.append(
                    f"Section '{section['title']}' has a factual paragraph without citations and without [UNSUPPORTED]."
                )
            for citation in citations:
                doc_id = str(citation.get("doc_id") or "").strip()
                if doc_id and doc_id not in valid_doc_ids:
                    errors.append(f"Citation doc_id '{doc_id}' is not in documents registry.")

    if requirements is not None and len(requirement_rows) == 0:
        errors.append("Requirements exist but could not be rendered as a table.")

    deduped_errors: list[str] = []
    seen: set[str] = set()
    for error in errors:
        if error in seen:
            continue
        seen.add(error)
        deduped_errors.append(error)
    return deduped_errors


def _escape_table(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("|", "\\|")).strip()
