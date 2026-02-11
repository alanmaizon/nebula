## Inspiration
Grant teams, especially nonprofits and small organizations, lose time and confidence when translating dense RFPs into compliant proposals. The painful part is not just writing, it is proving every claim with evidence and ensuring nothing in the requirements is missed. We built Nebula to reduce that risk: a workspace that turns source documents into a citation-backed, compliance-aware draft you can trust.

## What it does
Nebula ingests an RFP and supporting organizational documents, then produces a structured proposal workflow:
- extracts requirements into a validated artifact
- generates section drafts with traceable citations (`doc_id`, `page`, `snippet`)
- computes a coverage matrix (`met | partial | missing`)
- flags missing evidence before submission
- exports results as JSON and Markdown

The result is a faster path from document pile to submission-ready narrative, with auditability built in.

## How we built it
Nebula is built with a practical, modular architecture:
- frontend: Next.js for upload, workflow controls, and artifact review
- backend: FastAPI endpoints for ingestion, retrieval, drafting, coverage, and export
- retrieval backbone: deterministic chunking + embeddings + project-scoped similarity retrieval
- artifact contracts: strict Pydantic schema validation with repair safeguards
- operations baseline: structured logs, request correlation IDs, redaction rules, Docker-first local environment

Current intelligence path uses Amazon Nova via Bedrock through a deterministic orchestrator:
- Requirements extraction stage (Nova Pro)
- Section generation stage (Nova Pro)
- Coverage evaluation stage (Nova Lite)
- feature-flagged planning/refinement pilot for section generation to reduce manual reruns

## Category strategy
- Primary category: `Agentic AI`
- Secondary category: `Multimodal Understanding`
- Rationale:
  - agent specialization + orchestration is the core product behavior and architecture focus
  - multimodal/document understanding is the supporting capability that improves evidence quality
- Reusable submission assets:
  - Devpost narrative bullets: `docs/wiki/Devpost-Narrative-Draft-2026-02-08.md`
  - Devpost narrative full draft: `docs/wiki/Devpost-Narrative-Draft-2026-02-08.md`
  - Devpost testing instructions (paste-ready): `docs/wiki/Devpost-Testing-Instructions-2026-02-08.md`
  - Demo script outline: `docs/wiki/Devpost-Testing-Instructions-2026-02-08.md`
  - Submission compliance checklist: `docs/wiki/Nova-Submission-Checklist.md`
  - CI reliability summary: `docs/wiki/CI-Reliability-2026-02-08.md`
  - Impact metrics baseline + narration bullets: `docs/wiki/Impact-Metrics-Baseline-2026-02-08.md`

## Challenges we ran into
- Balancing determinism and flexibility: we needed predictable demo behavior while still improving semantic quality.
- Schema reliability: LLM outputs are useful only if they validate cleanly against required artifact structures.
- Citation integrity: every generated claim has to map back to retrieved evidence, or be explicitly marked as unsupported.
- Scope discipline: hackathon timelines forced clear boundaries between must-have trust features and stretch features.
- Submission readiness: proving real Nova usage in the production path requires explicit technical evidence, not just claims.

## Accomplishments that we're proud of
- Delivered an end-to-end workflow from upload to export with traceable artifacts.
- Implemented citation-first drafting and explicit missing-evidence signaling.
- Enforced schema contracts for requirements, drafts, and coverage outputs.
- Built an execution backbone with health checks, reproducible local startup, and operational logging safeguards.
- Implemented Nova runtime integration with `nova-agents-v1` artifact provenance and reproducible evidence notes.

## What we learned
- Trust beats verbosity: grounded outputs with citations are more valuable than fluent but unsupported text.
- Schema-first design makes AI systems maintainable and testable.
- Agentic systems work best when responsibilities are narrow and orchestration is deterministic.
- Documentation and evidence quality materially affect hackathon judging outcomes.
- Security and observability need to be part of the first architecture pass, not a late add-on.

## What's next for Nebula
Near term:
- publish and validate the final ~3 minute demo video with required hashtag and functional footage
- finalize external judge testing access instructions and fallback credential path
- capture one credentialed Bedrock run artifact to complement deterministic mocked evidence
- lock submission package links and final narrative consistency across Devpost assets

Post-submission:
- add richer reviewer-mode scoring and feedback loops
- expand multimodal understanding and evidence ingestion
- evaluate optional Nova Act workflows for targeted portal automation
- move from MVP local-first storage to production-grade AWS deployment controls
