from __future__ import annotations

import json

from .export_bundle_common import (
    _AWS_ACCESS_KEY_PATTERN,
    _AWS_SECRET_INLINE_PATTERN,
    _INLINE_CITATION_HINT_PATTERN,
    _MIN_CONFIDENCE_FOR_SUPPORTED,
    _PRIVATE_KEY_PATTERN,
    _append_unique,
    _as_dict_list,
    _as_optional_dict,
    _as_str_list,
    _coerce_confidence,
    _coerce_positive_int,
)


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

                if not doc_id:
                    citation_mismatch_count += 1
                    warnings.append(
                        f"Citation mismatch in section '{section_key}': missing doc_id."
                    )
                    continue

                if doc_id not in valid_doc_ids:
                    invalid_doc_ids.add(doc_id)
                    citation_mismatch_count += 1
                    warnings.append(
                        f"Citation mismatch in section '{section_key}': doc_id '{doc_id}' not in document registry."
                    )
                if page is not None:
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


def _extract_inline_citation_pairs(paragraph_text: str) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for match in _INLINE_CITATION_HINT_PATTERN.finditer(paragraph_text):
        doc_id = str(match.group(1) or "").strip()
        page = _coerce_positive_int(match.group(2))
        if doc_id and page is not None:
            pairs.append((doc_id, page))
    return pairs


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
