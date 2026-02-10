from __future__ import annotations

from app.drafting import ground_draft_payload, repair_draft_payload


def test_ground_draft_payload_parses_inline_doc_markers() -> None:
    payload = {
        "section_key": "Need Statement",
        "paragraphs": [
            {
                "text": (
                    "In 2025, 62% of households were at risk of eviction "
                    "(doc_id: org_impact_report_2025, page: 1)."
                ),
                "citations": [],
                "confidence": 0.95,
            }
        ],
        "missing_evidence": [],
    }
    ranked_chunks = [
        {
            "file_name": "org_impact_report_2025.txt",
            "page": 1,
            "text": "In 2025, 62% of households were at risk of eviction within 90 days.",
            "score": 0.92,
        }
    ]

    grounded, stats = ground_draft_payload(payload, ranked_chunks)
    paragraph = grounded["paragraphs"][0]

    assert "doc_id:" not in paragraph["text"].lower()
    assert len(paragraph["citations"]) == 1
    assert paragraph["citations"][0]["doc_id"] == "org_impact_report_2025.txt"
    assert paragraph["citations"][0]["page"] == 1
    assert stats["inline_citations_parsed"] == 1
    assert stats["fallback_citations_added"] == 0


def test_ground_draft_payload_drops_mismatched_citations_without_fallback() -> None:
    payload = {
        "section_key": "Need Statement",
        "paragraphs": [
            {
                "text": "The program addresses urgent community needs.",
                "citations": [{"doc_id": "unknown", "page": 9, "snippet": "not present"}],
                "confidence": 0.8,
            }
        ],
        "missing_evidence": [],
    }
    ranked_chunks = [
        {
            "file_name": "impact.txt",
            "page": 1,
            "text": "The program addresses urgent community needs with evidence-backed interventions.",
            "score": 0.77,
        }
    ]

    grounded, stats = ground_draft_payload(payload, ranked_chunks)
    paragraph = grounded["paragraphs"][0]

    assert len(paragraph["citations"]) == 0
    assert stats["citations_dropped"] >= 1
    assert stats["fallback_citations_added"] == 0


def test_ground_draft_payload_adds_fallback_when_no_citation_candidates_exist() -> None:
    payload = {
        "section_key": "Need Statement",
        "paragraphs": [
            {
                "text": "The program addresses urgent community needs.",
                "citations": [],
                "confidence": 0.8,
            }
        ],
        "missing_evidence": [],
    }
    ranked_chunks = [
        {
            "file_name": "impact.txt",
            "page": 1,
            "text": "The program addresses urgent community needs with evidence-backed interventions.",
            "score": 0.77,
        }
    ]

    grounded, stats = ground_draft_payload(payload, ranked_chunks)
    paragraph = grounded["paragraphs"][0]

    assert len(paragraph["citations"]) == 1
    assert paragraph["citations"][0]["doc_id"] == "impact.txt"
    assert paragraph["citations"][0]["page"] == 1
    assert stats["fallback_citations_added"] == 1


def test_repair_draft_payload_adds_missing_evidence_for_empty_section() -> None:
    repaired = repair_draft_payload(
        {
            "section_key": "Sustainability",
            "paragraphs": [],
            "missing_evidence": [],
        }
    )
    assert repaired["paragraphs"] == []
    assert len(repaired["missing_evidence"]) == 1
    assert "Sustainability" in repaired["missing_evidence"][0]["claim"]
