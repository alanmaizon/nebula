from __future__ import annotations

import re

from .export_bundle_common import (
    _ATTACHMENT_NOISE_TOKENS,
    _COVERAGE_STATUS_ORDER,
    _NARRATIVE_REQUIREMENT_SECTION_MAP,
    _as_dict_list,
    _as_optional_dict,
    _as_str_list,
    _coerce_positive_int,
    _normalize_key,
    _normalize_optional_id,
    _overlap_score,
    _token_set,
    _word_count,
)


def _reconcile_coverage_items(
    *,
    requirements: dict[str, object] | None,
    coverage_items: list[dict[str, object]],
    drafts: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    if requirements is None:
        normalized_only: list[dict[str, object]] = []
        for item in coverage_items:
            req_id = (
                str(item.get("internal_id") or "").strip()
                or str(item.get("requirement_id") or "").strip()
            )
            if not req_id:
                continue
            original_id = _normalize_optional_id(item.get("original_id"))
            refs = _as_str_list(item.get("evidence_refs"))
            normalized_only.append(
                {
                    "requirement_id": req_id,
                    "internal_id": req_id,
                    "original_id": original_id,
                    "status": _normalize_coverage_status(item.get("status")),
                    "notes": str(item.get("notes") or "").strip() or "Coverage note unavailable.",
                    "evidence_refs": refs,
                }
            )
        return normalized_only

    definitions = _build_requirement_definitions_for_reconciliation(requirements)
    coverage_lookup: dict[str, dict[str, object]] = {}
    for item in coverage_items:
        if not isinstance(item, dict):
            continue
        keys = {
            str(item.get("requirement_id") or "").strip(),
            str(item.get("internal_id") or "").strip(),
            str(item.get("original_id") or "").strip(),
        }
        normalized_keys = {key for key in keys if key}
        if not normalized_keys:
            continue
        for key in normalized_keys:
            coverage_lookup[key] = item
    section_stats = _build_section_stats(drafts)

    reconciled: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for definition in definitions:
        requirement_id = str(definition["requirement_id"])
        original_id = _normalize_optional_id(definition.get("original_id"))
        requirement_text = str(definition["requirement"])
        existing = coverage_lookup.get(requirement_id) or {}
        if not existing and original_id is not None:
            existing = coverage_lookup.get(original_id, {})
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
                "internal_id": requirement_id,
                "original_id": original_id,
                "status": status,
                "notes": notes,
                "evidence_refs": refs,
            }
        )
        seen_ids.add(requirement_id)

    for item in coverage_items:
        if not isinstance(item, dict):
            continue
        requirement_id = (
            str(item.get("internal_id") or "").strip()
            or str(item.get("requirement_id") or "").strip()
        )
        if not requirement_id or requirement_id in seen_ids:
            continue
        reconciled.append(
            {
                "requirement_id": requirement_id,
                "internal_id": requirement_id,
                "original_id": _normalize_optional_id(item.get("original_id")),
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
            requirement_id = (
                str(question.get("internal_id") or "").strip()
                or str(question.get("id") or "").strip()
                or f"Q{index}"
            )
            original_id = _normalize_optional_id(question.get("original_id"))
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
                    "internal_id": requirement_id,
                    "original_id": original_id,
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
                    "internal_id": f"A{attachment_index}",
                    "original_id": None,
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
                    "internal_id": f"{prefix}{index}",
                    "original_id": None,
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
