from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import Settings

logger = logging.getLogger("nebula.nova")


class NovaRuntimeError(RuntimeError):
    """Raised when Nova invocation fails or returns invalid output."""


class BedrockNovaOrchestrator:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or self._create_bedrock_client()

    def extract_requirements(self, chunks: list[dict[str, object]]) -> dict[str, object]:
        context = self._render_chunk_context(
            chunks,
            max_chunks=20,
            max_chars_per_chunk=600,
            max_total_chars=4200,
        )
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

    def plan_section_generation(
        self,
        section_key: str,
        requested_top_k: int,
        available_chunk_count: int,
    ) -> dict[str, object]:
        system_prompt = (
            "You are a planning agent for retrieval-augmented drafting. "
            "Return strict JSON only."
        )
        user_prompt = (
            "Return a JSON object with keys retrieval_top_k (int), retry_on_missing_evidence (bool), rationale (string). "
            "Choose retrieval_top_k between 1 and 10. "
            "Prefer conservative values for deterministic behavior.\n\n"
            f"Section key: {section_key}\n"
            f"Requested top_k: {requested_top_k}\n"
            f"Available chunks: {available_chunk_count}"
        )
        payload = self._invoke_json_model(
            self._settings.bedrock_lite_model_id,
            system_prompt,
            user_prompt,
        )
        retrieval_top_k = payload.get("retrieval_top_k", requested_top_k)
        retry_on_missing = payload.get("retry_on_missing_evidence", True)
        rationale = str(payload.get("rationale", "")).strip()

        try:
            parsed_top_k = int(retrieval_top_k)
        except (TypeError, ValueError):
            parsed_top_k = requested_top_k

        bounded_top_k = max(1, min(10, available_chunk_count, parsed_top_k))
        return {
            "retrieval_top_k": bounded_top_k,
            "retry_on_missing_evidence": bool(retry_on_missing),
            "rationale": rationale,
        }

    def generate_section(
        self,
        section_key: str,
        ranked_chunks: list[dict[str, object]],
        *,
        prompt_context: dict[str, str] | None = None,
    ) -> dict[str, object]:
        context = self._render_ranked_context(
            ranked_chunks,
            max_chunks=8,
            max_chars_per_chunk=700,
            max_total_chars=3600,
        )
        system_prompt = (
            "You are a grant writer. Produce strict JSON only. "
            "Every paragraph must include at least one citation grounded in provided evidence."
        )
        context_block = (
            f"Application context:\n{json.dumps(prompt_context, ensure_ascii=True)}\n\n"
            if prompt_context
            else ""
        )
        user_prompt = (
            "Return a JSON object with keys: section_key, paragraphs, missing_evidence. "
            "paragraphs must be an array of objects with keys text, citations, confidence. "
            "citations must be objects with keys doc_id, page, snippet. "
            "If evidence is insufficient, return an empty paragraphs array and one missing_evidence item.\n\n"
            f"Target section: {section_key}\n\n"
            f"{context_block}"
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

    def package_export_bundle(self, export_input: dict[str, object]) -> dict[str, object]:
        system_prompt = (
            "You are NebulaExportAgent, the final-stage export/packaging agent. "
            "Return strict JSON only. "
            "Cite-first, no hallucinations, deterministic output, redact secrets, and enforce traceability. "
            "Output must match schema keys exactly: export_version, generated_at, project, bundle, summary, "
            "quality_gates, provenance."
        )
        user_prompt = (
            "Build a deterministic submission-ready export bundle from INPUT.\n\n"
            "Rules:\n"
            "- Any factual claim in draft text must have citations or be marked unsupported.\n"
            "- Do not invent evidence.\n"
            "- Respect requirement limits if known.\n"
            "- Include profile-based markdown file outputs.\n"
            "- quality_gates.passed must be false when critical checks fail.\n"
            "- provenance.run_metadata must redact secrets.\n\n"
            f"INPUT:\n{json.dumps(export_input, ensure_ascii=True)}\n\n"
            "Now produce the final export bundle JSON object only."
        )
        return self._invoke_json_model(self._settings.bedrock_model_id, system_prompt, user_prompt)

    def _create_bedrock_client(self) -> Any:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise NovaRuntimeError("boto3 is required for Bedrock Nova runtime.") from exc

        return boto3.client("bedrock-runtime", region_name=self._settings.aws_region)

    def _invoke_json_model(self, model_id: str, system_prompt: str, user_prompt: str) -> dict[str, object]:
        if not model_id:
            raise NovaRuntimeError("Bedrock model ID is not configured.")

        started = time.perf_counter()
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
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.warning(
                "nova_invoke_failed",
                extra={
                    "event": "nova_invoke_failed",
                    "model_id": model_id,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            raise NovaRuntimeError(f"Bedrock invocation failed for model '{model_id}': {exc}") from exc

        text = self._extract_text(response)
        try:
            payload = self._parse_json_object(text)
        except Exception as exc:
            raise NovaRuntimeError(f"Nova response parsing failed for model '{model_id}': {exc}") from exc
        if not isinstance(payload, dict):
            raise NovaRuntimeError("Nova response must be a JSON object.")
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "nova_invoke_completed",
            extra={
                "event": "nova_invoke_completed",
                "model_id": model_id,
                "duration_ms": duration_ms,
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
                "response_chars": len(text),
            },
        )
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
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError as exc:
                raise NovaRuntimeError("Nova response contained malformed JSON content.") from exc

        raise NovaRuntimeError("Nova response was not valid JSON.")

    @staticmethod
    def _render_chunk_context(
        chunks: list[dict[str, object]],
        *,
        max_chunks: int,
        max_chars_per_chunk: int,
        max_total_chars: int,
    ) -> str:
        lines: list[str] = []
        used_chars = 0
        seen_text: set[str] = set()
        for chunk in chunks[:max_chunks]:
            available = max_total_chars - used_chars
            if available < 80:
                break
            chunk_limit = min(max_chars_per_chunk, max(40, available - 40))
            text = BedrockNovaOrchestrator._truncate(str(chunk.get("text", "")), chunk_limit)
            text_key = " ".join(text.lower().split())
            if text_key in seen_text:
                continue
            line = f"- doc={chunk.get('file_name')} page={chunk.get('page')} text={text}"
            lines.append(line)
            used_chars += len(line)
            seen_text.add(text_key)
        return "\n".join(lines)

    @staticmethod
    def _render_ranked_context(
        ranked_chunks: list[dict[str, object]],
        *,
        max_chunks: int,
        max_chars_per_chunk: int,
        max_total_chars: int,
    ) -> str:
        lines: list[str] = []
        used_chars = 0
        seen_locations: set[str] = set()
        seen_text: set[str] = set()
        for chunk in ranked_chunks:
            if len(lines) >= max_chunks:
                break
            location_key = f"{chunk.get('file_name')}::{chunk.get('page')}"
            if location_key in seen_locations:
                continue
            available = max_total_chars - used_chars
            if available < 80:
                break
            chunk_limit = min(max_chars_per_chunk, max(40, available - 60))
            text = BedrockNovaOrchestrator._truncate(str(chunk.get("text", "")), chunk_limit)
            text_key = " ".join(text.lower().split())
            if text_key in seen_text:
                continue
            line = (
                f"- doc={chunk.get('file_name')} page={chunk.get('page')} score={chunk.get('score')} "
                f"text={text}"
            )
            lines.append(line)
            used_chars += len(line)
            seen_locations.add(location_key)
            seen_text.add(text_key)
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        clean = " ".join(text.split())
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3] + "..."
