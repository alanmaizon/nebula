# Nebula Zero-to-MVP Execution Plan

This is the execution source of truth for building Nebula from zero to a demo-ready MVP with repeatable engineering practices.

## Execution Status
<!-- AUTO-GEN:DEVELOPMENT_PLAN_STATUS:START -->
| Week | Focus | Status |
|---|---|---|
| Week 1 | Foundations | Done |
| Week 2 | Nova Compliance and Category Positioning | Done |
| Week 3 | Judging Optimization (60/20/20) | Done |
| Week 4 | Submission Asset Packaging | In progress |
| Week 5 | Final QA and Deadline Buffer | Not started |
| Week 6 | Feedback Bonus and Judging Readiness | Not started |

### Current Week Priorities
- Prepare public demo/test access instructions and fallback credentials path

### Active Risks
- Submission may still under-demonstrate live credentialed Bedrock execution despite code-path evidence -> Capture one credentialed environment run artifact in addition to mocked deterministic evidence
- Demo/video and deployed runtime behavior may diverge near deadline -> Run repeatable clean-environment rehearsals and freeze non-critical changes
- Judging score may underperform if impact and innovation narrative is weak -> Map backlog items directly to 60/20/20 criteria and publish measurable outcomes
<!-- AUTO-GEN:DEVELOPMENT_PLAN_STATUS:END -->

## Execution Rules
- Every work item starts as a GitHub issue.
- Every code change lands through a pull request.
- Every merged PR updates docs when behavior, config, or operations change.
- Every milestone has explicit exit criteria and a demo checkpoint.
- No secret values in git, logs, issues, or PR comments.

## Branching and Release Strategy
- Default branch: `main` (protected).
- Feature branch naming: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`.
- PR requirements:
  - linked issue
  - test evidence (or explicit test gap)
  - docs impact note
  - security checklist acknowledgement
- Release tags: `v0.x.y` for MVP iterations.

## Submission Alignment (Hackathon)
- Core constraint: the shipped workflow must use Amazon Nova models/services on AWS (`Bedrock Nova` and/or `Nova Act`) in the production submission path.
- Strategy fit: position Nebula as `Agentic AI` primary, with `Multimodal Understanding` as a secondary differentiator.
- Architecture stance: keep deterministic RAG as backbone; layer agentic orchestration for planning/verification where it measurably improves quality.
- Evidence requirement: maintain a submission evidence pack showing model invocation path, deployed runtime behavior, and reproducible demo/test access.
- Deadline discipline: use internal freeze buffers ahead of external submission and feedback cutoffs.

## Judging Strategy (60/20/20)
| Criterion | Weight | Planning Response |
|---|---|---|
| Technical Implementation | 60% | Prioritize reliability, deterministic behavior, CI health, and clear Nova integration proof. |
| Enterprise or Community Impact | 20% | Quantify time-to-draft, coverage quality, and compliance-risk reduction outcomes. |
| Creativity and Innovation | 20% | Demonstrate agentic orchestration and multimodal evidence handling without sacrificing grounding. |

## Date Gates (Pacific Time)
- `2026-03-06 17:00`: AWS promotional credits request deadline (if needed).
- `2026-03-16 17:00`: final submission deadline; internal target is at least 2 hours earlier.
- `2026-03-18 17:00`: feedback submission deadline for bonus eligibility.

## Step-by-Step Plan

### Step 0: Governance and Project Bootstrap
Objective: establish delivery controls before feature work.

Tasks:
- Set up issue templates and PR template.
- Add `SECURITY.md`, `CODEOWNERS`, dependency update automation, and security workflows.
- Create GitHub labels, milestones, and project board.
- Seed wiki pages for onboarding and architecture navigation.

Exit criteria:
- New issues and PRs follow templates.
- Security reporting path exists and is discoverable.
- Board, labels, and milestones are usable for sprint planning.

Documentation:
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `docs/github/SETUP.md`

### Step 1: Local Development Foundation
Objective: make clean local startup reliable for contributors.

Tasks:
- Scaffold `backend/` and `frontend/` directories.
- Add `.env.example` files and local run scripts.
- Add `docker-compose.yml` for one-command startup.
- Add health endpoints and startup smoke test.

Exit criteria:
- A new contributor can run the stack locally in under 15 minutes.

Documentation:
- `README.md`
- `DEVELOPMENT_PLAN.md`

### Step 2: Ingestion and Metadata Pipeline
Objective: accept document uploads and persist document metadata.

Tasks:
- Implement `POST /projects` and `POST /projects/{id}/upload`.
- Store files with project-scoped IDs.
- Parse text with page anchors and structured metadata.
- Add basic error handling and upload limits.

Exit criteria:
- Uploaded docs are queryable by project and linked to extracted text.

Documentation:
- API docs in `README.md`
- Data model in `ARCHITECTURE.md`

### Step 3: Chunking and Retrieval Baseline
Objective: make evidence retrieval stable and deterministic.

Tasks:
- Build chunking pipeline with configurable chunk size/overlap.
- Generate embeddings and index in local vector store.
- Implement retrieval with project filters and top-k controls.
- Add retrieval quality smoke tests on sample docs.

Exit criteria:
- Retrieval returns grounded, project-scoped evidence chunks for known test prompts.

Documentation:
- `ARCHITECTURE.md`
- `DEVELOPMENT_PLAN.md`

### Step 4: Requirements Extraction
Objective: generate validated `requirements.json` from RFP content.

Tasks:
- Define strict extraction schema.
- Implement extraction endpoint with schema validation and one repair retry.
- Store artifact version + provenance metadata.
- Add endpoint tests and sample fixture tests.

Exit criteria:
- Requirements extraction passes schema validation for sample RFPs.

Documentation:
- `CONTRIBUTING.md` output contracts
- `docs/schemas/*` (when created)

### Step 5: Cited Draft Generation
Objective: generate section drafts where each claim is citation-backed.

Tasks:
- Implement `POST /projects/{id}/generate-section`.
- Retrieve evidence first, then generate with grounding-only prompt.
- Enforce citation integrity (`doc_id`, `page`, `snippet` must map to retrieval set).
- Return `missing_evidence[]` for unsupported claims.

Exit criteria:
- Generated draft sections include valid citations and no fabricated references.

Documentation:
- `README.md` demo flow
- `ARCHITECTURE.md` workflow sequence

### Step 6: Coverage Matrix and Validation
Objective: quantify requirement coverage and failure modes.

Tasks:
- Implement coverage matrix computation (`met | partial | missing`).
- Add requirement-to-evidence trace links.
- Add validation errors that are explicit and user-facing.
- Add tests for key matrix scenarios.

Exit criteria:
- Coverage output is consistent with extracted requirements and generated draft evidence.

Documentation:
- `CONTRIBUTING.md`
- `DEVELOPMENT_PLAN.md`

### Step 7: Export and UX Completion
Objective: produce usable outputs and a complete one-page demo flow.

Tasks:
- Implement JSON + Markdown exports.
- Add citation click-through in UI.
- Add loading, retry, and failure states for all key actions.
- Ensure mobile and desktop usability for demo path.

Exit criteria:
- End-to-end flow completes from upload to export without manual intervention.

Documentation:
- `README.md`
- demo runbook in wiki

### Step 8: Security and Reliability Hardening
Objective: reduce demo and early deployment risk.

Tasks:
- Add request correlation IDs and structured logs.
- Redact sensitive data from logs and model payload traces.
- Add backup/restore procedure for metadata and documents.
- Run dependency and static security scans in CI.

Exit criteria:
- Security policy controls are visible in code and CI checks.

Documentation:
- `AWS_ALIGNMENT.md`
- `SECURITY.md`
- operations wiki pages

### Step 9: Demo Freeze, Submission, and Feedback
Objective: freeze a stable submission build, deliver all required artifacts, and keep judging access reliable.

Tasks:
- Run full demo script twice from clean startup.
- Fix blocking defects only; defer stretch work to backlog.
- Prepare and validate Devpost submission content and links.
- Publish and validate the ~3 minute demo video with required hashtag and functional footage.
- Confirm repository/demo testing access path for judges until judging period ends.
- Submit actionable feedback before feedback deadline.

Exit criteria:
- Demo can be executed reliably in less than 10 minutes.
- Submission package is complete and validated before external deadline.
- Judges can access test environment/repository without manual intervention.

Documentation:
- release notes wiki page
- `README.md` final demo instructions
- submission checklist and evidence notes in wiki

### Step 10: Nova Multi-Agent Migration (Hackathon Compliance Path)
Objective: complete and harden the Nova runtime path while preserving API and UX contracts.

Tasks:
- Keep Nova model/config plumbing and endpoint wiring stable in production path.
- Maintain `nova-agents-v1` provenance across extraction/drafting/coverage artifacts.
- Preserve schema validation and repair wrappers as safety boundaries.
- Maintain integration and end-to-end tests for the Nova invocation path.
- Keep feature-flagged agentic orchestration pilot bounded and deterministic.
- Expand evidence package with one credentialed Bedrock runtime artifact.

Exit criteria:
- End-to-end flow uses `nova-agents-v1` artifact source on extraction, drafting, and coverage outputs.
- All migrated endpoints preserve existing payload shape and pass regression tests.
- Nova path tests cover schema failures, empty evidence paths, and provider failures.
- Evidence pack includes deterministic test evidence plus at least one credentialed Bedrock runtime run.

Documentation:
- `README.md` issue-level migration checklist and verification plan
- `ARCHITECTURE.md` updated agent/orchestrator flow
- `README.md` runtime config and demo execution updates
- `AWS_ALIGNMENT.md` Nova compliance evidence references

## Documentation Cadence
- Daily: update issue status and project board.
- Per PR: update docs for any behavior/config/API change.
- Weekly: update `docs/status.yml` then run `python scripts/sync_docs.py`.
- Milestone close: publish a short retrospective in wiki.

## Definition of Done (Per Issue)
- Code merged via PR with linked issue.
- Tests added or explicit test gap documented.
- Security and privacy impact considered.
- User-facing and developer-facing docs updated.
- Rollback or mitigation noted for risky changes.

## Backlog Management
- This backlog is living and updated at least weekly.
- GitHub Issues are the execution source of truth.
- `DEVELOPMENT_PLAN.md` captures plan-level backlog by step.
- `docs/status.yml` captures current-week progress snapshot.

## Step Backlog

### Step 0 Backlog: Governance and Bootstrap
- [x] Add governance templates and CODEOWNERS.
- [x] Add security policy and baseline security workflows.
- [x] Add GitHub bootstrap script for labels/milestones/issues/project.
- [x] Run bootstrap script against GitHub once `gh auth` is valid.

### Step 1 Backlog: Foundation
- [x] Scaffold `backend/` and `frontend/` directories.
- [x] Add `.env.example` files and local startup commands.
- [x] Add `docker-compose.yml` baseline and health checks.

### Step 2 Backlog: Ingestion
- [x] Implement `POST /projects`.
- [x] Implement `POST /projects/{id}/upload`.
- [x] Persist uploaded document metadata and storage paths.
- [x] Add page-anchored extracted text persistence.

### Step 3 Backlog: Retrieval
- [x] Implement chunking with configurable chunk size and overlap.
- [x] Add embeddings and local vector index pipeline.
- [x] Implement project-scoped top-k retrieval API.

### Step 4 Backlog: Requirements Extraction
- [x] Define `requirements.json` schema.
- [x] Implement extraction endpoint with schema validation and repair retry.
- [x] Add fixture-based extraction tests.

### Step 5 Backlog: Cited Drafting
- [x] Implement section generation endpoint.
- [x] Enforce citation integrity against retrieval set.
- [x] Return and test `missing_evidence[]`.

### Step 6 Backlog: Coverage
- [x] Implement `met | partial | missing` matrix computation.
- [x] Link coverage entries to requirement and evidence references.
- [x] Add matrix edge-case tests.

### Step 7 Backlog: Export and UX
- [x] Implement JSON and Markdown export endpoint.
- [ ] Add citation click-through in UI.
- [x] Add loading/error/retry states in UI flow.

### Step 8 Backlog: Hardening
- [x] Add request correlation IDs and structured logs.
- [x] Add sensitive-data redaction rules.
- [x] Document backup/restore procedure.
- [x] Execute restore drill and capture evidence.

### Step 9 Backlog: Release
- [x] Run demo script twice from clean setup.
- [x] Freeze non-critical changes and resolve blockers.
- [x] Tag MVP release and publish notes.
- [x] Add explicit Nova-on-AWS compliance evidence for submission package.
- [x] Finalize Devpost category/story with Agentic AI primary and Multimodal secondary.
- [ ] Publish and validate final 3-minute demo video.
- [ ] Finalize test access instructions and verify from clean external perspective.
- [ ] Submit actionable feedback package before deadline.

### Step 10 Backlog: Nova Multi-Agent Migration
- [x] Add Nova runtime dependencies (`boto3`) and model/config environment plumbing.
- [x] Implement `BedrockNovaOrchestrator` for extraction, drafting, and coverage.
- [x] Rewire `main.py` endpoints and artifact sources to `nova-agents-v1`.
- [x] Add deterministic tests for Nova runtime model routing and API contracts.
- [x] Add API-level end-to-end Nova-path test with mocked Bedrock `converse`.
- [x] Add feature-flagged agentic orchestration pilot for section-generation planning/verification.
- [x] Publish architecture and evidence documentation for Nova call path and reliability.
- [ ] Capture one credentialed Bedrock runtime artifact in a live AWS environment.
