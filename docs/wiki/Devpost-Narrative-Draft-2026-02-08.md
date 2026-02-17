# Devpost Narrative Draft - 2026-02-08

Use this as the base text for the Devpost project description.

## One-line Summary
Nebula is an Amazon Nova-powered grant workflow assistant that turns RFP and program documents into citation-backed drafts, requirement coverage, and explicit evidence gaps.

## Category Positioning
- Primary category: `Agentic AI`
- Secondary category: `Multimodal Understanding`

## Problem
Nonprofit teams lose grant opportunities when requirements are missed, claims are unsupported, or compliance gaps are discovered too late in review.

## Solution
Nebula provides a trust-first workflow:
1. Ingest RFP and supporting documents.
2. Extract structured requirements.
3. Generate section drafts with citations (`doc_id`, `page`, `snippet`).
4. Compute requirement coverage (`met`, `partial`, `missing`).
5. Export artifacts for review and submission.

## Nova and AWS Architecture
- Runtime models:
  - `BEDROCK_MODEL_ID=amazon.nova-pro-v1:0`
  - `BEDROCK_LITE_MODEL_ID=amazon.nova-lite-v1:0`
- Core call path:
  - FastAPI endpoint -> `BedrockNovaOrchestrator` -> Bedrock `converse` -> schema validation/repair -> artifact persistence
- References:
  - `ARCHITECTURE.md` (runtime call path section)
  - `AWS_ALIGNMENT.md` (submission model baseline)
  - `docs/wiki/Nova-Evidence-Run-2026-02-08.md`

## Proof Points (Impact + Reliability)
- Nova-path artifacts are persisted with `source = nova-agents-v1` for extraction, drafting, and coverage flows.
- Deterministic reliability gate is enforced in CI (`backend-deterministic-reliability` matrix) and documented in `docs/wiki/CI-Reliability-2026-02-08.md`.
- Impact baseline is reproducible from artifact files with script output in `docs/artifacts/impact-baseline-2026-02-08.json`.
- Baseline metrics from demo corpus:
  - pipeline success rate: `100.0%`
  - coverage met rate: `100.0%`
  - citation density: `1.0 citations/paragraph`
  - unsupported claim rate: `0.0%`

## Implementation Status Guardrail
- The repository includes deterministic Nova-path evidence via integration and end-to-end tests.
- Live Bedrock runtime use in a deployed environment depends on valid AWS credentials and Bedrock model access in the configured region.

## Testing Instructions For Application (Devpost)
Paste-ready testing instructions are maintained in:
- `docs/wiki/Devpost-Testing-Instructions-2026-02-08.md`

## Suggested Devpost Closing Paragraph
Nebula combines deterministic engineering controls with agentic orchestration so nonprofit teams can move from document chaos to submission readiness with evidence-linked outputs they can review and defend.
