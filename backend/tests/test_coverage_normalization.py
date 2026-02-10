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


def test_normalize_coverage_payload_maps_prefixed_ids_to_canonical_ids() -> None:
    requirements = {
        "questions": [
            {"id": "Q1", "prompt": "Need Statement (350 words max): Describe the specific community need."},
            {"id": "Q2", "prompt": "Program Design (400 words max): Explain your activities."},
            {"id": "Q3", "prompt": "Outcomes and Evaluation (300 words max): Identify measurable outcomes."},
        ],
        "required_attachments": [
            "Attachment A: Project Budget",
            "Attachment B: Program Timeline",
            "Include two letters of community support",
        ],
    }
    coverage_payload = {
        "items": [
            {"requirement_id": "Q1_need_statement", "status": "met", "notes": "Need statement covered.", "evidence_refs": []},
            {"requirement_id": "Q2_program_design", "status": "missing", "notes": "Program design missing.", "evidence_refs": []},
            {"requirement_id": "Attachment_A_budget", "status": "met", "notes": "Budget present.", "evidence_refs": []},
            {"requirement_id": "community_support_letters", "status": "missing", "notes": "Letters missing.", "evidence_refs": []},
            {"requirement_id": "rubric_need_alignment", "status": "missing", "notes": "Rubric missing.", "evidence_refs": []},
        ]
    }

    normalized = normalize_coverage_payload(requirements=requirements, payload=coverage_payload)
    by_id = {item["requirement_id"]: item for item in normalized["items"]}

    assert by_id["Q1"]["status"] == "met"
    assert by_id["Q2"]["status"] == "missing"
    assert by_id["A1"]["status"] == "met"
    assert by_id["A3"]["status"] == "missing"
    assert "rubric_need_alignment" not in by_id
    assert by_id["Q3"]["status"] == "missing"
    assert by_id["A2"]["status"] == "missing"
