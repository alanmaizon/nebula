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


def test_merge_requirements_handles_object_rubric_entries() -> None:
    deterministic = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [],
        "questions": [],
        "required_attachments": [],
        "rubric": ["Feasibility and readiness"],
        "disallowed_costs": [],
    }
    nova = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [],
        "questions": [],
        "required_attachments": [],
        "rubric": [
            {"criterion": "Outcomes and evidence quality"},
            {"text": "Budget reasonableness"},
            {"criterion": "Feasibility and readiness"},
        ],
        "disallowed_costs": [],
    }

    merged = merge_requirements_payload(deterministic, nova)

    assert "Feasibility and readiness" in merged["rubric"]
    assert "Outcomes and evidence quality" in merged["rubric"]
    assert "Budget reasonableness" in merged["rubric"]


def test_merge_requirements_prefers_richer_prompt_for_same_section() -> None:
    deterministic = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [],
        "questions": [
            {
                "id": "Q1",
                "prompt": "Need Statement (350 words max): Describe the specific community need.",
                "limit": {"type": "words", "value": 350},
            }
        ],
        "required_attachments": [],
        "rubric": [],
        "disallowed_costs": [],
    }
    nova = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [],
        "questions": [{"id": "1", "prompt": "Need Statement", "limit": {"type": "words", "value": 350}}],
        "required_attachments": [],
        "rubric": [],
        "disallowed_costs": [],
    }

    merged = merge_requirements_payload(deterministic, nova)

    need_statement_prompts = [item["prompt"] for item in merged["questions"] if "need statement" in item["prompt"].lower()]
    assert len(need_statement_prompts) == 1
    assert need_statement_prompts[0] == "Need Statement (350 words max): Describe the specific community need."


def test_merge_requirements_omits_heading_only_list_entries() -> None:
    deterministic = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [
            "Eligibility:",
            "Applicants must be nonprofit organizations with active 501(c)(3) status.",
        ],
        "questions": [],
        "required_attachments": ["Required Attachments:", "Attachment A: Project Budget"],
        "rubric": ["Rubric and Scoring Criteria:"],
        "disallowed_costs": ["Disallowed costs:", "Political campaign activity"],
    }
    nova = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": ["Eligibility"],
        "questions": [],
        "required_attachments": [],
        "rubric": [],
        "disallowed_costs": [],
    }

    merged = merge_requirements_payload(deterministic, nova)

    assert merged["eligibility"] == ["Applicants must be nonprofit organizations with active 501(c)(3) status."]
    assert merged["required_attachments"] == ["Attachment A: Project Budget"]
    assert merged["rubric"] == []
    assert merged["disallowed_costs"] == ["Political campaign activity"]


def test_extract_requirements_payload_captures_rubric_items_from_section_block() -> None:
    rfp_text = """
Rubric and Scoring Criteria:
- Need alignment and urgency (30 points)
- Feasibility and readiness (30 points)
- Outcomes and evidence quality (25 points)
- Budget reasonableness (15 points)
"""

    payload = extract_requirements_payload([{"text": rfp_text}])

    assert payload["rubric"] == [
        "Need alignment and urgency (30 points)",
        "Feasibility and readiness (30 points)",
        "Outcomes and evidence quality (25 points)",
        "Budget reasonableness (15 points)",
    ]


def test_merge_requirements_moves_rubric_scored_items_out_of_disallowed_costs() -> None:
    deterministic = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [],
        "questions": [],
        "required_attachments": [],
        "rubric": ["Need alignment and urgency (30 points)"],
        "disallowed_costs": ["Expenses unrelated to direct program delivery"],
    }
    nova = {
        "funder": "City Grants Office",
        "deadline": "April 1, 2026",
        "eligibility": [],
        "questions": [],
        "required_attachments": [],
        "rubric": [],
        "disallowed_costs": [
            "(30 points)",
            "Outcomes and evidence quality (25 points)",
            "Budget reasonableness (15 points)",
            "Expenses unrelated to direct pr",
            "Expenses unrelated to direct program delivery",
        ],
    }

    merged = merge_requirements_payload(deterministic, nova)

    assert "Outcomes and evidence quality (25 points)" in merged["rubric"]
    assert "Budget reasonableness (15 points)" in merged["rubric"]
    assert "(30 points)" not in merged["rubric"]

    assert "Outcomes and evidence quality (25 points)" not in merged["disallowed_costs"]
    assert "Budget reasonableness (15 points)" not in merged["disallowed_costs"]
    assert "(30 points)" not in merged["disallowed_costs"]
    assert "Expenses unrelated to direct pr" not in merged["disallowed_costs"]
    assert "Expenses unrelated to direct program delivery" in merged["disallowed_costs"]


def test_merge_requirements_filters_non_cost_noise_from_disallowed() -> None:
    deterministic = {
        "funder": "City of Dublin",
        "deadline": "April 30, 2027",
        "eligibility": [],
        "questions": [],
        "required_attachments": [],
        "rubric": [],
        "disallowed_costs": [
            "Restrictions",
            "No alcohol, entertainment, or lobbying expenses.",
            "Equipment purchases above EUR 10,000 require prior approval.",
            "Indirect costs capped at 12%.",
        ],
    }
    nova = {
        "funder": "City of Dublin",
        "deadline": "April 30, 2027",
        "eligibility": [],
        "questions": [],
        "required_attachments": [],
        "rubric": [],
        "disallowed_costs": [
            "Funding Opportunity: City of Dublin Youth Workforce Innovation Grant 2026",
            "Program Overview",
            "Required Narrative Questions",
            "Describe how services continue after grant period.",
            "No alcohol, entertainment, or lobbying expenses.",
            "Indirect costs capped at 12%.",
            "ters",
        ],
    }

    merged = merge_requirements_payload(deterministic, nova)

    assert "No alcohol, entertainment, or lobbying expenses." in merged["disallowed_costs"]
    assert "Equipment purchases above EUR 10,000 require prior approval." in merged["disallowed_costs"]
    assert "Indirect costs capped at 12%." in merged["disallowed_costs"]

    assert "Funding Opportunity: City of Dublin Youth Workforce Innovation Grant 2026" not in merged["disallowed_costs"]
    assert "Program Overview" not in merged["disallowed_costs"]
    assert "Required Narrative Questions" not in merged["disallowed_costs"]
    assert "Describe how services continue after grant period." not in merged["disallowed_costs"]
    assert "ters" not in merged["disallowed_costs"]


def test_extract_questions_pass_explicit_tags_preserves_provenance() -> None:
    rfp_text = """
REQ-101: Describe the target population and unmet need. (max 300 words)
REQUIREMENT-202: Provide an implementation timeline by quarter. (max 500 words)
"""

    payload = extract_requirements_payload([{"text": rfp_text}])

    prompts = [item["prompt"] for item in payload["questions"]]
    assert "Describe the target population and unmet need. (max 300 words)" in prompts
    assert "Provide an implementation timeline by quarter. (max 500 words)" in prompts

    provenance_by_prompt = {
        item["prompt"]: item.get("provenance")
        for item in payload["questions"]
    }
    assert provenance_by_prompt["Describe the target population and unmet need. (max 300 words)"] == "explicit_tag"
    assert provenance_by_prompt["Provide an implementation timeline by quarter. (max 500 words)"] == "explicit_tag"


def test_extract_questions_pass_structured_outlines_preserves_provenance() -> None:
    rfp_text = """
1.2.3 Describe the local housing instability trend over the past 3 years.
A.1 Provide staffing plan and implementation ownership.
III. Explain risk mitigation for delivery delays.
"""

    payload = extract_requirements_payload([{"text": rfp_text}])
    provenance_by_prompt = {item["prompt"]: item.get("provenance") for item in payload["questions"]}

    assert provenance_by_prompt["Describe the local housing instability trend over the past 3 years."] == (
        "structured_outline"
    )
    assert provenance_by_prompt["Provide staffing plan and implementation ownership."] == "structured_outline"
    assert provenance_by_prompt["Explain risk mitigation for delivery delays."] == "structured_outline"


def test_extract_questions_pass_inline_indicators_preserves_provenance() -> None:
    rfp_text = """
Applicants must provide an evidence-backed staffing plan (max 250 words).
Narrative Requirement: Explain how outcomes will be measured across quarters.
"""

    payload = extract_requirements_payload([{"text": rfp_text}])
    prompts = [item["prompt"] for item in payload["questions"]]
    assert "provide an evidence-backed staffing plan (max 250 words)." in prompts
    assert "Explain how outcomes will be measured across quarters." in prompts

    provenance_by_prompt = {item["prompt"]: item.get("provenance") for item in payload["questions"]}
    assert provenance_by_prompt["provide an evidence-backed staffing plan (max 250 words)."] == "inline_indicator"
    assert provenance_by_prompt["Explain how outcomes will be measured across quarters."] == "inline_indicator"


def test_extract_questions_pass_fallback_question_preserves_provenance() -> None:
    rfp_text = """
Question 1: Describe the need statement for your service area.
Question 2: Provide two measurable annual outcomes.
"""

    payload = extract_requirements_payload([{"text": rfp_text}])
    provenance_by_prompt = {item["prompt"]: item.get("provenance") for item in payload["questions"]}

    assert provenance_by_prompt["Describe the need statement for your service area."] == "fallback_question"
    assert provenance_by_prompt["Provide two measurable annual outcomes."] == "fallback_question"
