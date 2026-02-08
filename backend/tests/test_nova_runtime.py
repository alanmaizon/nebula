from __future__ import annotations

from app.config import settings
from app.nova_runtime import BedrockNovaOrchestrator


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
