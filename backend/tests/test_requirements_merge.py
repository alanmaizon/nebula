from __future__ import annotations

from app.requirements import extract_requirements_payload, merge_requirements_payload


def test_merge_requirements_keeps_deterministic_coverage_and_adds_nova_fields() -> None:
    rfp_text = """
Funding Opportunity: City of Dublin Youth Workforce Innovation Grant 2026

Required Narrative Questions
1) Need Statement (max 300 words)
2) Program Design (max 500 words)
3) Outcomes and Evaluation (max 400 words)
4) Sustainability (max 250 words)

Submission Requirements
- Attachment A: Line-item budget with justification
- Include implementation timeline by quarter
"""
    deterministic = extract_requirements_payload([{"text": rfp_text}])
    nova = {
        "funder": "City of Dublin",
        "questions": [
            {"id": "1", "prompt": "Need Statement", "limit": {"type": "words", "value": 300}},
            {"id": "2", "prompt": "Program Design", "limit": {"type": "words", "value": 500}},
        ],
        "required_attachments": ["implementation timeline by quarter"],
        "eligibility": [],
        "rubric": [],
        "disallowed_costs": [],
    }

    merged = merge_requirements_payload(deterministic, nova)

    merged_prompts = [item["prompt"] for item in merged["questions"]]
    assert len(merged["questions"]) >= len(deterministic["questions"])
    assert "Need Statement (max 300 words)" in merged_prompts
    assert "Program Design (max 500 words)" in merged_prompts
    assert "Outcomes and Evaluation (max 400 words)" in merged_prompts
    assert "Sustainability (max 250 words)" in merged_prompts

    attachments = [entry.lower() for entry in merged["required_attachments"]]
    assert any("attachment a" in entry for entry in attachments)
    assert any("timeline" in entry for entry in attachments)
    assert merged["funder"] == "City of Dublin"
