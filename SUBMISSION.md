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

Current migration path upgrades the intelligence layer from heuristic logic to a multi-agent system on AWS Strands + Amazon Nova:
- RFP Analyst (Nova Pro)
- Evidence Researcher (Nova Lite)
- Grant Writer (Nova Pro)
- Compliance Reviewer (Nova Lite)
- deterministic Orchestrator coordinating all stages

## Category strategy
- Primary category: `Agentic AI`
- Secondary category: `Multimodal Understanding`
- Rationale:
  - agent specialization + orchestration is the core product behavior and architecture focus
  - multimodal/document understanding is the supporting capability that improves evidence quality
- Reusable submission assets:
  - Devpost narrative bullets: `docs/wiki/Category-Strategy.md`
  - Demo script outline: `docs/wiki/Category-Strategy.md`
  - Submission compliance checklist: `docs/wiki/Nova-Submission-Checklist.md`
  - CI reliability summary: `docs/wiki/CI-Reliability-2026-02-08.md`

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
- Defined and sequenced a concrete `NOVA-01` to `NOVA-12` migration roadmap to reach full agentic compliance.

## What we learned
- Trust beats verbosity: grounded outputs with citations are more valuable than fluent but unsupported text.
- Schema-first design makes AI systems maintainable and testable.
- Agentic systems work best when responsibilities are narrow and orchestration is deterministic.
- Documentation and evidence quality materially affect hackathon judging outcomes.
- Security and observability need to be part of the first architecture pass, not a late add-on.

## What's next for Nebula
Near term:
- execute `NOVA-01` to `NOVA-12` to replace heuristics with Strands-orchestrated Nova agents
- preserve API/UI contracts while upgrading internal intelligence
- harden tests, error handling, and observability for agent runtime
- publish explicit Nova-on-AWS compliance evidence for submission

Post-submission:
- add richer reviewer-mode scoring and feedback loops
- expand multimodal understanding and evidence ingestion
- evaluate optional Nova Act workflows for targeted portal automation
- move from MVP local-first storage to production-grade AWS deployment controls
