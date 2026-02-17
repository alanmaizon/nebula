# Judge Evaluation Runbook

## Purpose
This runbook explains how to inspect run-level quality scoring produced by the backend judge-eval stage.

## Where Scores Are Produced
- Endpoint: `POST /projects/{project_id}/generate-full-draft`
- Response fields:
  - `run_id`
  - `judge_eval`
  - `judge_eval_artifact`
  - `run_summary.judge_quality_gate`

## Rubric Dimensions
Each run is scored across four dimensions in `judge_eval.dimensions`:
- `extraction_completeness`
- `citation_integrity`
- `coverage_confidence`
- `missing_evidence_precision`

Each dimension includes:
- `score` in `[0.0, 1.0]`
- `signals` with supporting metrics used to compute that score.

## Gate Interpretation
`judge_eval.gate` includes:
- `passed`: all thresholds met
- `flagged`: one or more thresholds failed
- `blocked`: failed and blocking is enabled
- `reasons`: explicit threshold failures

Threshold settings:
- `JUDGE_EVAL_MIN_OVERALL_SCORE` (default `0.65`)
- `JUDGE_EVAL_MIN_DIMENSION_SCORE` (default `0.55`)
- `JUDGE_EVAL_BLOCK_ON_FAIL` (default `false`)

## Diagnostics Retrieval
Use diagnostics endpoint for full trace + eval context:
- `GET /projects/{project_id}/runs/{run_id}/diagnostics`

Response includes:
- `trace_events` in deterministic sequence order
- `judge_evals` persisted for that run

## Common Triage Patterns
1. Low `citation_integrity`
- Check `unsupported_paragraph_count` and `citation_mismatch_count` signals.
- Action: regenerate sections with stronger evidence grounding and verify citation schema.

2. Low `coverage_confidence`
- Check coverage status counts (`met`, `partial`, `missing`).
- Action: target missing/partial requirements and regenerate with narrower prompts.

3. Low `missing_evidence_precision`
- Check mismatch between `missing_evidence_count` and `unresolved_count`.
- Action: improve missing-evidence recommendations and evidence upload guidance.

4. Low `extraction_completeness`
- Check `questions_expected`, `questions_with_prompt`, and extraction validation errors.
- Action: verify RFP selection, then rerun extraction.
