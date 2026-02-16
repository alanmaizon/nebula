from __future__ import annotations

from app.export_bundle import build_export_bundle


def _base_input() -> dict[str, object]:
    return {
        "project": {
            "id": "project-123",
            "name": "Export Project",
            "created_at": "2026-02-09T00:00:00+00:00",
            "updated_at": "2026-02-09T01:00:00+00:00",
        },
        "export_request": {
            "format": "both",
            "profile": "hackathon",
            "include_debug": False,
            "sections": ["Need Statement"],
            "output_filename_base": "demo",
        },
        "documents": [
            {
                "id": "doc-db-1",
                "doc_id": "impact_report.txt",
                "file_name": "impact_report.txt",
                "page_count": 2,
            }
        ],
        "requirements": {
            "funder": "City Community Fund",
            "deadline": "March 30, 2026",
            "questions": [
                {
                    "id": "Q1",
                    "prompt": "Need Statement (350 words max): Describe need.",
                    "limit": {"type": "words", "value": 350},
                }
            ],
            "required_attachments": ["Attachment A: Budget"],
            "rubric": ["Need alignment and urgency (30 points)"],
            "disallowed_costs": ["Purchase of real estate"],
            "eligibility": ["Nonprofit status required"],
        },
        "drafts": {
            "Need Statement": {
                "draft": {
                    "section_key": "Need Statement",
                    "paragraphs": [
                        {
                            "text": "Need is documented in local data.",
                            "citations": [
                                {
                                    "doc_id": "impact_report.txt",
                                    "page": 1,
                                    "snippet": "Need and outcomes are documented.",
                                }
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "missing_evidence": [],
                },
                "artifact": {
                    "id": "draft-1",
                    "source": "nova-agents-v1",
                    "updated_at": "2026-02-09T01:00:00+00:00",
                },
            }
        },
        "coverage": {
            "items": [
                {
                    "requirement_id": "Q1",
                    "status": "met",
                    "notes": "Covered",
                    "evidence_refs": ["impact_report.txt:p1"],
                }
            ]
        },
        "validations": {"requirements": {"present": True}},
        "missing_evidence": [],
        "run_metadata": {
            "model_ids": {"primary": "us.amazon.nova-pro-v1:0"},
            "temperatures": {"agent_temperature": 0.1},
        },
        "artifacts_used": [
            {
                "type": "requirements",
                "id": "req-1",
                "updated_at": "2026-02-09T00:30:00+00:00",
            }
        ],
    }


def _substantive_section(section_key: str, token_a: str, token_b: str) -> dict[str, object]:
    return {
        "draft": {
            "section_key": section_key,
            "paragraphs": [
                {
                    "text": " ".join([token_a] * 45),
                    "citations": [
                        {
                            "doc_id": "impact_report.txt",
                            "page": 1,
                            "snippet": f"{section_key} evidence A",
                        }
                    ],
                    "confidence": 0.9,
                },
                {
                    "text": " ".join([token_b] * 45),
                    "citations": [
                        {
                            "doc_id": "impact_report.txt",
                            "page": 1,
                            "snippet": f"{section_key} evidence B",
                        }
                    ],
                    "confidence": 0.9,
                },
            ],
            "missing_evidence": [],
        },
        "artifact": {
            "id": f"draft-{section_key.lower().replace(' ', '-')}",
            "source": "nova-agents-v1",
            "updated_at": "2026-02-09T01:00:00+00:00",
        },
    }


def test_build_export_bundle_outputs_expected_schema_and_files() -> None:
    payload = build_export_bundle(_base_input())
    assert payload["export_version"] == "nebula.export.v1"
    assert payload["project"]["id"] == "project-123"

    bundle = payload["bundle"]
    assert bundle["json"] is not None
    assert "intake" not in bundle["json"]
    assert bundle["markdown"] is not None
    files = bundle["markdown"]["files"]
    paths = {file["path"] for file in files}
    assert "README_EXPORT.md" in paths
    assert "REQUIREMENTS_MATRIX.md" in paths
    assert "DRAFT_APPLICATION.md" in paths

    quality = payload["quality_gates"]
    assert quality["passed"] is True
    assert payload["summary"]["coverage_overview"]["met"] == 1


def test_build_export_bundle_omits_empty_missing_evidence_and_empty_unsupported_block() -> None:
    payload = build_export_bundle(_base_input())
    files = payload["bundle"]["markdown"]["files"]
    files_by_path = {file["path"]: file for file in files}
    assert "MISSING_EVIDENCE.md" not in files_by_path

    draft_application = files_by_path.get("DRAFT_APPLICATION.md")
    assert draft_application is not None
    assert "### Unsupported / Missing" not in draft_application["content"]


def test_build_export_bundle_fails_when_citation_doc_is_unknown() -> None:
    test_input = _base_input()
    test_input["drafts"]["Need Statement"]["draft"]["paragraphs"][0]["citations"][0]["doc_id"] = "missing.txt"

    payload = build_export_bundle(test_input)
    quality = payload["quality_gates"]
    assert quality["passed"] is False
    assert any("Citation doc_id not found in project documents" in reason for reason in quality["reasons"])


def test_build_export_bundle_reconciles_q1_when_need_statement_exists() -> None:
    test_input = _base_input()
    test_input["drafts"] = {
        "Need Statement": _substantive_section("Need Statement", "housing", "stability"),
    }
    test_input["coverage"] = {
        "items": [
            {
                "requirement_id": "Q1",
                "status": "missing",
                "notes": "No need statement provided in the draft artifact.",
                "evidence_refs": [],
            }
        ]
    }

    payload = build_export_bundle(test_input)
    coverage = payload["bundle"]["json"]["coverage"]["items"]
    q1 = next(item for item in coverage if item["requirement_id"] == "Q1")
    assert q1["status"] in {"partial", "met"}
    assert q1["status"] != "missing"


def test_build_export_bundle_reconciles_coverage_across_all_sections() -> None:
    test_input = _base_input()
    test_input["export_request"]["sections"] = None
    test_input["requirements"]["questions"] = [
        {
            "id": "Q1",
            "prompt": "Need Statement (350 words max): Describe need.",
            "limit": {"type": "words", "value": 350},
        },
        {
            "id": "Q2",
            "prompt": "Program Design (400 words max): Explain your activities and implementation timeline.",
            "limit": {"type": "words", "value": 400},
        },
    ]
    test_input["drafts"] = {
        "Need Statement": _substantive_section("Need Statement", "need", "eviction"),
        "Program Design": _substantive_section("Program Design", "timeline", "activities"),
    }
    test_input["coverage"] = {
        "items": [
            {
                "requirement_id": "Q1",
                "status": "met",
                "notes": "Need statement covered.",
                "evidence_refs": ["impact_report.txt:p1"],
            },
            {
                "requirement_id": "Q2",
                "status": "missing",
                "notes": "Program design not provided.",
                "evidence_refs": [],
            },
        ]
    }

    payload = build_export_bundle(test_input)
    coverage = payload["bundle"]["json"]["coverage"]["items"]
    q1 = next(item for item in coverage if item["requirement_id"] == "Q1")
    q2 = next(item for item in coverage if item["requirement_id"] == "Q2")

    assert q1["status"] in {"partial", "met"}
    assert q2["status"] in {"partial", "met"}


def test_build_export_bundle_flags_citation_mismatch_and_downgrades_scores() -> None:
    test_input = _base_input()
    test_input["drafts"]["Need Statement"]["draft"]["paragraphs"][0]["text"] = (
        "Need is documented. (doc: impact_report.txt, page: 2)"
    )
    test_input["drafts"]["Need Statement"]["draft"]["paragraphs"][0]["citations"] = [
        {
            "doc_id": "impact_report.txt",
            "page": 1,
            "snippet": "",
        }
    ]

    payload = build_export_bundle(test_input)
    quality = payload["quality_gates"]
    assert "citation mismatch warning" in quality["warnings"]
    assert payload["summary"]["uncertainty"]["citation_mismatch_count"] >= 1
    assert payload["summary"]["overall_completion"] != "100.0%"


def test_build_export_bundle_blank_doc_id_citation_is_unsupported() -> None:
    test_input = _base_input()
    test_input["drafts"]["Need Statement"]["draft"]["paragraphs"][0]["citations"] = [
        {
            "doc_id": "",
            "page": 1,
            "snippet": "Need and outcomes are documented.",
        }
    ]

    payload = build_export_bundle(test_input)
    draft = payload["bundle"]["json"]["drafts"]["Need Statement"]["draft"]
    paragraph = draft["paragraphs"][0]

    assert paragraph["unsupported"] is True
    assert payload["summary"]["unsupported_claims_count"] >= 1
    assert "citation mismatch warning" in payload["quality_gates"]["warnings"]


def test_build_export_bundle_attachment_requirements_need_attachment_grounded_evidence() -> None:
    test_input = _base_input()
    test_input["coverage"]["items"] = [
        {
            "requirement_id": "A1",
            "status": "met",
            "notes": "Budget covered by narrative.",
            "evidence_refs": ["section_key: Need Statement, paragraph 1, citation: impact_report.txt:p1"],
        }
    ]

    payload = build_export_bundle(test_input)
    coverage_items = payload["bundle"]["json"]["coverage"]["items"]
    attachment = next(item for item in coverage_items if item["requirement_id"] == "A1")

    assert attachment["status"] != "met"
    assert "attachment-grounded evidence" in attachment["notes"].lower()


def test_build_export_bundle_warns_for_empty_required_sections() -> None:
    test_input = _base_input()
    test_input["requirements"]["questions"] = [
        {
            "id": "Q1",
            "prompt": "Need Statement (350 words max): Describe need.",
            "limit": {"type": "words", "value": 350},
        },
        {
            "id": "Q2",
            "prompt": "Program Design (400 words max): Explain your activities and implementation timeline.",
            "limit": {"type": "words", "value": 400},
        },
    ]
    test_input["coverage"]["items"] = [
        {
            "requirement_id": "Q1",
            "status": "met",
            "notes": "Covered",
            "evidence_refs": ["impact_report.txt:p1"],
        },
        {
            "requirement_id": "Q2",
            "status": "missing",
            "notes": "No section content.",
            "evidence_refs": [],
        },
    ]

    payload = build_export_bundle(test_input)
    quality = payload["quality_gates"]
    assert "empty required section warning" in quality["warnings"]
    assert payload["summary"]["uncertainty"]["empty_required_sections_count"] >= 1


def test_build_export_bundle_surfaces_source_ambiguity_in_warnings_and_markdown() -> None:
    test_input = _base_input()
    test_input["source_selection"] = {
        "selected_document_id": "doc-1",
        "selected_file_name": "rfp-1.txt",
        "ambiguous": True,
        "candidates": [
            {"document_id": "doc-1", "file_name": "rfp-1.txt", "score": 8},
            {"document_id": "doc-2", "file_name": "rfp-2.txt", "score": 8},
        ],
    }

    payload = build_export_bundle(test_input)
    assert "source ambiguity warning" in payload["quality_gates"]["warnings"]
    assert payload["summary"]["uncertainty"]["source_ambiguity_count"] == 1

    files = payload["bundle"]["markdown"]["files"]
    coverage = next(file for file in files if file["path"] in {"COVERAGE.md", "coverage.md"})
    assert "Source ambiguity warnings: 1" in coverage["content"]


def test_build_export_bundle_preserves_internal_and_original_requirement_ids() -> None:
    test_input = _base_input()
    test_input["requirements"]["questions"][0]["internal_id"] = "Q1"
    test_input["requirements"]["questions"][0]["original_id"] = "REQ-101"
    test_input["coverage"]["items"] = [
        {
            "requirement_id": "REQ-101",
            "status": "met",
            "notes": "Covered by citation evidence.",
            "evidence_refs": ["impact_report.txt:p1"],
        }
    ]

    payload = build_export_bundle(test_input)
    bundle_json = payload["bundle"]["json"]
    assert bundle_json is not None

    question = bundle_json["requirements"]["questions"][0]
    assert question["id"] == "Q1"
    assert question["internal_id"] == "Q1"
    assert question["original_id"] == "REQ-101"

    coverage_item = next(item for item in bundle_json["coverage"]["items"] if item["requirement_id"] == "Q1")
    assert coverage_item["internal_id"] == "Q1"
    assert coverage_item["original_id"] == "REQ-101"

    files = payload["bundle"]["markdown"]["files"]
    requirements_md = next(file for file in files if file["path"] in {"REQUIREMENTS_MATRIX.md", "requirements.md"})
    assert "| internal_id | original_id | requirement | status | notes |" in requirements_md["content"]
    assert "| Q1 | REQ-101 | Need Statement (350 words max): Describe need." in requirements_md["content"]
