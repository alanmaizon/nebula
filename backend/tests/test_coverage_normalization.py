from __future__ import annotations

from app.coverage import normalize_coverage_payload


def test_normalize_coverage_payload_maps_text_attachment_to_canonical_id() -> None:
    requirements = {
        "questions": [
            {"id": "Q1", "prompt": "Need Statement"},
            {"id": "Q2", "prompt": "Program Design"},
        ],
        "required_attachments": ["implementation timeline by quarter"],
    }
    coverage_payload = {
        "items": [
            {"requirement_id": "1", "status": "met", "notes": "Covered", "evidence_refs": ["doc=evidence.txt, page=1"]},
            {"requirement_id": "2", "status": "missing", "notes": "Not present", "evidence_refs": []},
            {
                "requirement_id": "implementation timeline by quarter",
                "status": "missing",
                "notes": "Attachment missing",
                "evidence_refs": [],
            },
        ]
    }

    normalized = normalize_coverage_payload(requirements=requirements, payload=coverage_payload)
    items = normalized["items"]

    assert [item["requirement_id"] for item in items] == ["Q1", "Q2", "A1"]
    assert items[2]["status"] == "missing"


def test_normalize_coverage_payload_backfills_missing_requirements() -> None:
    requirements = {
        "questions": [
            {"id": "Q1", "prompt": "Need Statement"},
            {"id": "Q2", "prompt": "Program Design"},
        ],
        "required_attachments": ["Attachment A: Board List"],
    }
    coverage_payload = {
        "items": [
            {"requirement_id": "Q1", "status": "met", "notes": "Covered", "evidence_refs": ["impact.txt:p1"]},
        ]
    }

    normalized = normalize_coverage_payload(requirements=requirements, payload=coverage_payload)
    by_id = {item["requirement_id"]: item for item in normalized["items"]}

    assert by_id["Q1"]["status"] == "met"
    assert by_id["Q2"]["status"] == "missing"
    assert by_id["A1"]["status"] == "missing"
