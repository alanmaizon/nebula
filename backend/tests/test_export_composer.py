from __future__ import annotations

import re

from app.export.composer import compose_markdown_report


def _requirements() -> dict[str, object]:
    return {
        "funder": "City of Portland Community Resilience Microgrant 2026",
        "questions": [
            {
                "id": "Q1",
                "prompt": "Need Statement (350 words max): Describe the specific community need your program addresses.",
                "limit": {"type": "words", "value": 350},
            },
            {
                "id": "Q2",
                "prompt": "Program Design (400 words max): Explain your activities and implementation timeline.",
                "limit": {"type": "words", "value": 400},
            },
            {
                "id": "Q3",
                "prompt": "Outcomes and Evaluation (300 words max): Identify measurable outcomes.",
                "limit": {"type": "words", "value": 300},
            },
        ],
        "required_attachments": ["Attachment A: Project Budget"],
        "eligibility": ["Applicants must be nonprofit organizations with active 501(c)(3) status."],
        "rubric": ["Need alignment and urgency (30 points)"],
        "disallowed_costs": ["Purchase of real estate"],
    }


def _documents() -> list[dict[str, object]]:
    return [{"id": "doc-1", "file_name": "org_impact_report_2025.txt"}]


def _supporting_paragraph(seed: str, count: int = 45) -> str:
    return " ".join([seed] * count)


def _section_with_two_supported_paragraphs(section_key: str) -> dict[str, object]:
    return {
        "section_key": section_key,
        "paragraphs": [
            {
                "text": _supporting_paragraph("households", 45),
                "citations": [
                    {
                        "doc_id": "org_impact_report_2025.txt",
                        "page": 1,
                        "snippet": "Evidence snippet A",
                    }
                ],
                "confidence": 0.9,
            },
            {
                "text": _supporting_paragraph("stability", 45),
                "citations": [
                    {
                        "doc_id": "org_impact_report_2025.txt",
                        "page": 1,
                        "snippet": "Evidence snippet B",
                    }
                ],
                "confidence": 0.9,
            },
        ],
        "missing_evidence": [],
    }


def test_empty_missing_evidence_omits_missing_evidence_section() -> None:
    report = compose_markdown_report(
        project_name="Nebula Demo",
        documents=_documents(),
        requirements=_requirements(),
        drafts={"Need Statement": _section_with_two_supported_paragraphs("Need Statement")},
        coverage={"items": [{"requirement_id": "Q1", "status": "met", "notes": "Covered", "evidence_refs": []}]},
        missing_evidence=[],
        validations={},
    )
    assert "## Missing Evidence" not in report
    assert "## Draft Application" in report
    assert "## Requirements Matrix" in report
    assert "## Coverage" in report


def test_q1_reconciliation_sets_status_not_missing_when_need_statement_exists() -> None:
    report = compose_markdown_report(
        project_name="Nebula Demo",
        documents=_documents(),
        requirements=_requirements(),
        drafts={"Need Statement": _section_with_two_supported_paragraphs("Need Statement")},
        coverage={
            "items": [
                {
                    "requirement_id": "Q1",
                    "status": "missing",
                    "notes": "No need statement provided in the draft artifact.",
                    "evidence_refs": [],
                }
            ]
        },
        missing_evidence=[],
        validations={},
    )

    assert "| Q1 | Need Statement (350 words max): Describe the specific community need your program addresses. | missing |" not in report
    assert re.search(r"\| Q1 \| Need Statement \(350 words max\): Describe the specific community need your program addresses\. \| (partial|met) \|", report)
    assert re.search(r"\| Q1 \| (partial|met) \|", report)


def test_boilerplate_paragraph_without_citations_is_removed() -> None:
    drafts = {
        "Program Design": {
            "section_key": "Program Design",
            "paragraphs": [
                {
                    "text": (
                        "The program design is structured to address local challenges using "
                        "evidence-based practices and comprehensive service delivery for participants."
                    ),
                    "citations": [],
                    "confidence": 0.8,
                },
                {
                    "text": _supporting_paragraph("implementation", 45),
                    "citations": [{"doc_id": "org_impact_report_2025.txt", "page": 1, "snippet": "Design evidence A"}],
                    "confidence": 0.9,
                },
                {
                    "text": _supporting_paragraph("timeline", 45),
                    "citations": [{"doc_id": "org_impact_report_2025.txt", "page": 1, "snippet": "Design evidence B"}],
                    "confidence": 0.9,
                },
            ],
            "missing_evidence": [],
        }
    }

    report = compose_markdown_report(
        project_name="Nebula Demo",
        documents=_documents(),
        requirements=_requirements(),
        drafts=drafts,
        coverage={"items": [{"requirement_id": "Q2", "status": "met", "notes": "Covered", "evidence_refs": []}]},
        missing_evidence=[],
        validations={},
    )
    assert "structured to address local challenges" not in report
    assert "### Program Design" in report


def test_word_limit_trimming_applies_for_q1_350_words_max() -> None:
    long_need_statement = {
        "section_key": "Need Statement",
        "paragraphs": [
            {
                "text": _supporting_paragraph("housing", 150),
                "citations": [{"doc_id": "org_impact_report_2025.txt", "page": 1, "snippet": "Need evidence 1"}],
                "confidence": 0.9,
            },
            {
                "text": _supporting_paragraph("families", 150),
                "citations": [{"doc_id": "org_impact_report_2025.txt", "page": 1, "snippet": "Need evidence 2"}],
                "confidence": 0.9,
            },
            {
                "text": _supporting_paragraph("eviction", 150),
                "citations": [{"doc_id": "org_impact_report_2025.txt", "page": 1, "snippet": "Need evidence 3"}],
                "confidence": 0.9,
            },
        ],
        "missing_evidence": [],
    }

    report = compose_markdown_report(
        project_name="Nebula Demo",
        documents=_documents(),
        requirements=_requirements(),
        drafts={"Need Statement": long_need_statement},
        coverage={"items": [{"requirement_id": "Q1", "status": "met", "notes": "Covered", "evidence_refs": []}]},
        missing_evidence=[],
        validations={},
    )

    start = report.index("### Need Statement")
    end = report.index("## Requirements Matrix")
    need_statement_block = report[start:end]
    paragraph_lines = [line for line in need_statement_block.splitlines() if re.match(r"^\d+\.\s+", line)]
    paragraph_word_count = sum(len(re.findall(r"\b[\w'-]+\b", line)) for line in paragraph_lines)

    assert paragraph_word_count <= 350
    assert len(paragraph_lines) >= 2
