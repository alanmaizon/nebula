# Nova Agent Performance Plan (2026-02-14)

## Objective
Improve end-to-end draft quality, latency, and cost for Nebula's Nova-based agent pipeline without breaking deterministic behavior and citation grounding.

## Current Issues
- Repeated Nova client construction during multi-stage runs.
- Repeated chunk loading/ranking work across section generation in full-draft runs.
- Limited stage-level telemetry for diagnosing slow or expensive runs.
- Prompt context can include redundant chunk text, increasing token cost and response latency.

## Fixes Implemented Today
- Cached Nova orchestrator instance for runtime reuse.
- Reused extracted chunk set across full-draft section generation.
- Added ranking cache reuse for repeated query/chunk pairs in the same run.
- Added per-section and full-run timing telemetry in `generate-full-draft` response.
- Added Nova invocation latency/size logging (`nova_invoke_completed`, `nova_invoke_failed`).
- Added duplicate context suppression in Nova evidence rendering.

## KPI Targets
- Full-draft latency (p50): reduce by 25%.
- Full-draft latency (p95): reduce by 30%.
- Missing-evidence items per run: reduce by 20%.
- Cost per full-draft run (input+output tokens): reduce by 20%.
- Citation grounding pass rate: keep >= current baseline (no regression).

## Execution Plan
1. Baseline and Instrumentation (Day 0-2)
- Capture 30+ runs of `POST /projects/{id}/generate-full-draft` on fixed fixtures.
- Store run metrics: section count, `run_summary.timings_ms`, Nova model latency logs, missing-evidence counts.
- Produce baseline table (p50/p95 latency + cost estimate + quality metrics).

2. Retrieval Quality Upgrades (Day 2-5)
- Add hybrid ranking (semantic + lexical overlap) behind a feature flag.
- Add retrieval diversity guardrails (prevent near-duplicate chunks in top-k).
- Tune `top_k` bounds by section type (need statement, design, budget, timeline).

3. Model Routing and Prompt Efficiency (Day 5-8)
- Route lower-risk tasks (planner/coverage) to Lite where quality is stable.
- Add prompt budget controls (hard cap per context block + section-aware truncation).
- Add fallback policy for Bedrock throttling and transient failures.

4. Quality/Cost Optimization Loop (Day 8-12)
- Run A/B comparisons on fixed eval set:
  - A: current settings
  - B: hybrid retrieval
  - C: hybrid retrieval + routing changes
- Compare latency, cost, and quality metrics before rollout.

5. Production Hardening (Day 12-14)
- Add CloudWatch dashboards/alerts for Nova latency, 5xx rates, and token growth.
- Define rollback criteria for each feature flag.
- Publish runbook update with tuning defaults and troubleshooting steps.

## Experiment Gate Criteria
- Promote only if all are true:
  - Latency improves by >= 15%.
  - Cost improves by >= 10%.
  - Missing-evidence does not increase.
  - No increase in schema-validation failure rate.

## Immediate Next Actions
1. Add benchmark script to replay a fixed multi-document dataset and capture JSON metrics.
2. Implement hybrid retrieval flag and run A/B benchmark.
3. Add model-routing toggle for section coverage and planner stages.
