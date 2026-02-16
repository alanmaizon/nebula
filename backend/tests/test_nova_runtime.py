from __future__ import annotations

import pytest

from app.config import settings
from app.nova_runtime import BedrockNovaOrchestrator, NovaRuntimeError


class FakeBedrockClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        model_id = kwargs["modelId"]
        if model_id == settings.bedrock_lite_model_id:
            text = (
                '{"items":[{"requirement_id":"Q1","status":"met","notes":"Covered","evidence_refs":["rfp.txt:p1"]}]}'
            )
        elif "Target section:" in kwargs["messages"][0]["content"][0]["text"]:
            text = (
                '{"section_key":"Need Statement","paragraphs":[{"text":"Need Statement: Supported.","citations":[{"doc_id":"rfp.txt","page":1,"snippet":"Supported"}],"confidence":0.9}],"missing_evidence":[]}'
            )
        else:
            text = (
                '{"funder":"City Community Fund","deadline":"March 30, 2026","eligibility":[],"questions":[{"id":"Q1","prompt":"Describe outcomes.","limit":{"type":"words","value":250}}],"required_attachments":[],"rubric":[],"disallowed_costs":[]}'
            )
        return {"output": {"message": {"content": [{"text": text}]}}}


def test_nova_orchestrator_uses_expected_models() -> None:
    client = FakeBedrockClient()
    orchestrator = BedrockNovaOrchestrator(settings=settings, client=client)

    requirements = orchestrator.extract_requirements(
        [
            {
                "file_name": "rfp.txt",
                "page": 1,
                "text": "Question 1: Describe outcomes. Limit 250 words.",
            }
        ]
    )
    assert requirements["funder"] == "City Community Fund"

    draft = orchestrator.generate_section(
        "Need Statement",
        [
            {
                "file_name": "rfp.txt",
                "page": 1,
                "score": 0.91,
                "text": "Evidence text",
            }
        ],
    )
    assert draft["section_key"] == "Need Statement"

    coverage = orchestrator.compute_coverage(requirements=requirements, draft=draft)
    assert coverage["items"][0]["status"] == "met"

    assert len(client.calls) == 3
    assert client.calls[0]["modelId"] == settings.bedrock_model_id
    assert client.calls[1]["modelId"] == settings.bedrock_model_id
    assert client.calls[2]["modelId"] == settings.bedrock_lite_model_id


def test_nova_orchestrator_wraps_malformed_json_parse_errors() -> None:
    class MalformedJsonClient:
        def converse(self, **kwargs):
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": "result follows {\"funder\":\"City\", this is malformed } trailing text"
                            }
                        ]
                    }
                }
            }

    orchestrator = BedrockNovaOrchestrator(settings=settings, client=MalformedJsonClient())
    with pytest.raises(NovaRuntimeError, match="parsing failed"):
        orchestrator.extract_requirements(
            [
                {
                    "file_name": "rfp.txt",
                    "page": 1,
                    "text": "Question 1: Describe outcomes. Limit 250 words.",
                }
            ]
        )


def test_nova_orchestrator_adaptive_extraction_merges_windows_and_reports_diagnostics() -> None:
    class MultiWindowClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.window_call = 0

        def converse(self, **kwargs):
            self.calls.append(kwargs)
            prompt = kwargs["messages"][0]["content"][0]["text"]
            if "Extraction window" in prompt:
                self.window_call += 1
                if self.window_call == 1:
                    text = (
                        '{"funder":"City Community Fund","deadline":"March 30, 2026","eligibility":[],'  # noqa: E501
                        '"questions":[{"id":"REQ-101","prompt":"Need Statement (250 words max): Describe local need.","limit":{"type":"words","value":250}}],'  # noqa: E501
                        '"required_attachments":[],"rubric":[],"disallowed_costs":[]}'
                    )
                elif self.window_call == 2:
                    text = (
                        '{"funder":"City Community Fund","deadline":"March 30, 2026","eligibility":[],'  # noqa: E501
                        '"questions":[{"id":"REQ-101","prompt":"Need Statement (250 words max): Describe local need.","limit":{"type":"words","value":250}},'  # noqa: E501
                        '{"id":"REQ-202","prompt":"Program Design (350 words max): Explain implementation.","limit":{"type":"words","value":350}}],'  # noqa: E501
                        '"required_attachments":[],"rubric":[],"disallowed_costs":[]}'
                    )
                else:
                    text = (
                        '{"funder":"City Community Fund","deadline":"March 30, 2026","eligibility":[],'  # noqa: E501
                        '"questions":[{"id":"REQ-202","prompt":"Program Design (350 words max): Explain implementation.","limit":{"type":"words","value":350}}],'  # noqa: E501
                        '"required_attachments":[],"rubric":[],"disallowed_costs":[]}'
                    )
                return {"output": {"message": {"content": [{"text": text}]}}}

            # non-extraction path fallback (unused in this test)
            text = '{"items":[{"requirement_id":"Q1","status":"met","notes":"Covered","evidence_refs":["rfp.txt:p1"]}]}'  # noqa: E501
            return {"output": {"message": {"content": [{"text": text}]}}}

    runtime_settings = settings.model_copy(deep=True)
    runtime_settings.extraction_context_max_chunks = 2
    runtime_settings.extraction_context_max_total_chars = 200
    runtime_settings.extraction_window_size_chunks = 2
    runtime_settings.extraction_window_overlap_chunks = 1
    runtime_settings.extraction_window_max_passes = 3

    client = MultiWindowClient()
    orchestrator = BedrockNovaOrchestrator(settings=runtime_settings, client=client)
    chunks = [
        {"file_name": "rfp.txt", "page": 1, "text": "Need Statement requirement detail one."},
        {"file_name": "rfp.txt", "page": 2, "text": "Need Statement requirement detail two."},
        {"file_name": "rfp.txt", "page": 3, "text": "Program Design requirement detail one."},
        {"file_name": "rfp.txt", "page": 4, "text": "Program Design requirement detail two."},
    ]

    payload = orchestrator.extract_requirements(chunks)
    questions = payload["questions"]
    diagnostics = payload["_extraction_diagnostics"]

    assert len(client.calls) == diagnostics["window_count"]
    assert diagnostics["mode"] == "multi_pass"
    assert diagnostics["window_count"] >= 2
    assert diagnostics["raw_candidates"] == 4
    assert diagnostics["deduped_candidates"] == 2
    assert diagnostics["dropped_candidates"] == 2
    assert diagnostics["dedupe_ratio"] == 0.5
    assert diagnostics["window_overlap_chunks"] == 1
    assert len(diagnostics["window_ranges"]) == diagnostics["window_count"]
    assert len(diagnostics["window_context_chars"]) == diagnostics["window_count"]
    assert len(diagnostics["per_window_candidates"]) == diagnostics["window_count"]

    prompts = {item["prompt"] for item in questions}
    assert "Need Statement (250 words max): Describe local need." in prompts
    assert "Program Design (350 words max): Explain implementation." in prompts
