# Agentic Orchestration Pilot - 2026-02-08

## Objective
Introduce a minimal agentic orchestration layer over deterministic RAG for one workflow stage (section generation) without destabilizing the baseline demo path.

## Design
- Feature flag: `ENABLE_AGENTIC_ORCHESTRATION_PILOT` (default `false`)
- Stage covered: planning + verification refinement for `POST /projects/{project_id}/generate-section`
- Components:
  - planner stage: `BedrockNovaOrchestrator.plan_section_generation`
  - writer stage: `BedrockNovaOrchestrator.generate_section`
  - verification refinement: one bounded auto-retry when `missing_evidence` is returned

## Controlled Behavior
- Baseline behavior is unchanged when flag is disabled.
- When enabled:
  - planner selects retrieval `top_k` (bounded to deterministic limits)
  - generation runs once
  - if draft has `missing_evidence`, orchestrator expands retrieval window and retries once
  - only improved validated output is kept

## Operator-Efficiency Benefit Evidence
- Repro command:
  - `cd backend && PYTHONPATH=. .venv/bin/pytest -q tests/test_health.py::test_agentic_orchestration_pilot_retries_missing_evidence`
- Evidence from test:
  - with pilot OFF and `top_k=1`: draft returns `missing_evidence` and zero paragraphs
  - with pilot ON and same input: one auto-retry resolves to a cited paragraph with zero `missing_evidence`
- Benefit type:
  - reduced manual reruns for low-evidence drafts (operator-efficiency win)

## Determinism vs Autonomy Tradeoff
- Determinism controls:
  - feature flag off by default
  - bounded retrieval and single retry
  - unchanged schema validation and citation contracts
- Autonomy controls:
  - planner is allowed to adjust retrieval depth and retry intent
  - no unbounded loops or autonomous tool execution
