from __future__ import annotations

import json
import re
from typing import Any

from app.config import Settings


class NovaRuntimeError(RuntimeError):
    """Raised when Nova invocation fails or returns invalid output."""


class BedrockNovaOrchestrator:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or self._create_bedrock_client()

    def extract_requirements(self, chunks: list[dict[str, object]]) -> dict[str, object]:
        context = self._render_chunk_context(chunks, max_chunks=20, max_chars_per_chunk=600)
        system_prompt = (
            "You are an RFP analyst. Extract requirements into strict JSON only. "
            "Do not include markdown or prose."
        )
        user_prompt = (
            "Return a JSON object with keys: "
            "funder, deadline, eligibility, questions, required_attachments, rubric, disallowed_costs. "
            "questions must be an array of objects with keys id, prompt, limit where limit has keys type and value. "
            "limit.type must be one of words, chars, none.\n\n"
            f"RFP context:\n{context}"
        )
        return self._invoke_json_model(self._settings.bedrock_model_id, system_prompt, user_prompt)

    def generate_section(self, section_key: str, ranked_chunks: list[dict[str, object]]) -> dict[str, object]:
        context = self._render_ranked_context(ranked_chunks, max_chunks=8, max_chars_per_chunk=700)
        system_prompt = (
            "You are a grant writer. Produce strict JSON only. "
            "Every paragraph must include at least one citation grounded in provided evidence."
        )
        user_prompt = (
            "Return a JSON object with keys: section_key, paragraphs, missing_evidence. "
            "paragraphs must be an array of objects with keys text, citations, confidence. "
            "citations must be objects with keys doc_id, page, snippet. "
            "If evidence is insufficient, return an empty paragraphs array and one missing_evidence item.\n\n"
            f"Target section: {section_key}\n\n"
            f"Evidence:\n{context}"
        )
        return self._invoke_json_model(self._settings.bedrock_model_id, system_prompt, user_prompt)

    def compute_coverage(self, requirements: dict[str, object], draft: dict[str, object]) -> dict[str, object]:
        system_prompt = (
            "You are a compliance reviewer. Return strict JSON only with requirement coverage assessment."
        )
        user_prompt = (
            "Return a JSON object with key items. "
            "items must be an array of objects with keys requirement_id, status, notes, evidence_refs. "
            "status must be one of met, partial, missing.\n\n"
            f"Requirements artifact:\n{json.dumps(requirements, ensure_ascii=True)}\n\n"
            f"Draft artifact:\n{json.dumps(draft, ensure_ascii=True)}"
        )
        return self._invoke_json_model(self._settings.bedrock_lite_model_id, system_prompt, user_prompt)

    def _create_bedrock_client(self) -> Any:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise NovaRuntimeError("boto3 is required for Bedrock Nova runtime.") from exc

        return boto3.client("bedrock-runtime", region_name=self._settings.aws_region)

    def _invoke_json_model(self, model_id: str, system_prompt: str, user_prompt: str) -> dict[str, object]:
        if not model_id:
            raise NovaRuntimeError("Bedrock model ID is not configured.")

        try:
            response = self._client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={
                    "temperature": self._settings.agent_temperature,
                    "maxTokens": self._settings.agent_max_tokens,
                },
            )
        except Exception as exc:  # pragma: no cover - exercised via runtime integration
            raise NovaRuntimeError(f"Bedrock invocation failed for model '{model_id}': {exc}") from exc

        text = self._extract_text(response)
        payload = self._parse_json_object(text)
        if not isinstance(payload, dict):
            raise NovaRuntimeError("Nova response must be a JSON object.")
        return payload

    @staticmethod
    def _extract_text(response: Any) -> str:
        outputs = response.get("output", {}).get("message", {}).get("content", [])
        parts: list[str] = []
        for item in outputs:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        if not parts:
            raise NovaRuntimeError("Nova response did not include textual output.")
        return "\n".join(parts).strip()

    @staticmethod
    def _parse_json_object(raw: str) -> Any:
        candidate = raw.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(candidate[start : end + 1])

        raise NovaRuntimeError("Nova response was not valid JSON.")

    @staticmethod
    def _render_chunk_context(
        chunks: list[dict[str, object]],
        *,
        max_chunks: int,
        max_chars_per_chunk: int,
    ) -> str:
        lines: list[str] = []
        for chunk in chunks[:max_chunks]:
            lines.append(
                (
                    f"- doc={chunk.get('file_name')} page={chunk.get('page')} "
                    f"text={BedrockNovaOrchestrator._truncate(str(chunk.get('text', '')), max_chars_per_chunk)}"
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _render_ranked_context(
        ranked_chunks: list[dict[str, object]],
        *,
        max_chunks: int,
        max_chars_per_chunk: int,
    ) -> str:
        lines: list[str] = []
        for chunk in ranked_chunks[:max_chunks]:
            lines.append(
                (
                    f"- doc={chunk.get('file_name')} page={chunk.get('page')} score={chunk.get('score')} "
                    f"text={BedrockNovaOrchestrator._truncate(str(chunk.get('text', '')), max_chars_per_chunk)}"
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        clean = " ".join(text.split())
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3] + "..."
