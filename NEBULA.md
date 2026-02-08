# Nebula Nova Checkpoint (2026-02-08)

## Status Summary
Nebula has completed the core Nova runtime migration for submission-critical backend flows:
- requirements extraction
- section generation with citations
- coverage computation

All three persist artifacts with `source: "nova-agents-v1"` and keep the existing API contracts and schema validation/repair boundaries.

## Implemented Runtime Path
- Endpoint wiring:
  - `backend/app/main.py`:
    - `extract_requirements`
    - `generate_section`
    - `compute_coverage`
- Orchestrator:
  - `backend/app/nova_runtime.py` (`BedrockNovaOrchestrator`)
  - Bedrock `converse` calls for:
    - `BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0` (extract + draft)
    - `BEDROCK_LITE_MODEL_ID=us.amazon.nova-lite-v1:0` (coverage)

## Agentic Pilot (Controlled)
- Feature flag: `ENABLE_AGENTIC_ORCHESTRATION_PILOT` (default `false`)
- Scope: planning + one-step verification retry on `generate-section`
- Behavior when enabled:
  - planner picks retrieval depth (`top_k`) and retry intent
  - writer runs once
  - verifier triggers one bounded retry if `missing_evidence` is returned
- Safety:
  - deterministic bounds remain enforced
  - citation/schema requirements are unchanged

## Evidence and Validation
- Full backend suite:
  - `cd backend && PYTHONPATH=. .venv/bin/pytest -q`
- Nova-path end-to-end API evidence test:
  - `cd backend && PYTHONPATH=. .venv/bin/pytest -q tests/test_nova_e2e.py::test_nova_end_to_end_api_run`
- Evidence docs:
  - `docs/wiki/Nova-Evidence-Run-2026-02-08.md`
  - `docs/wiki/CI-Reliability-2026-02-08.md`
  - `docs/wiki/Impact-Metrics-Baseline-2026-02-08.md`
  - `docs/wiki/Agentic-Orchestration-Pilot-2026-02-08.md`

## Completed Roadmap Outcomes (Weeks 2-3)
- Week 2:
  - explicit Nova call path and model IDs documented
  - submission checklist and category strategy completed
- Week 3:
  - deterministic CI reliability gate added
  - reproducible impact metric baseline generated
  - feature-flagged agentic orchestration pilot implemented

## Remaining Submission Work
- Publish and validate the final ~3 minute demo video with required hashtag.
- Finalize judge testing access instructions and fallback credential path.
- Capture one credentialed Bedrock runtime artifact to complement deterministic mocked evidence.
