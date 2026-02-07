# GrantSmith Zero-to-MVP Execution Plan

This is the execution source of truth for building GrantSmith from zero to a demo-ready MVP with repeatable engineering practices.

## Execution Status
<!-- AUTO-GEN:DEVELOPMENT_PLAN_STATUS:START -->
| Week | Focus | Status |
|---|---|---|
| Week 1 | Foundations | In progress |
| Week 2 | Requirements extraction | Not started |
| Week 3 | Cited drafting core | Not started |
| Week 4 | Hardening and demo | Not started |

### Current Week Priorities
- Add page-anchored text extraction to ingestion pipeline
- Add chunking and local vector indexing baseline
- Create requirements extraction schema scaffold and endpoint skeleton

### Active Risks
- PDF extraction quality on heterogeneous RFP files -> Constrain demo corpus and capture page anchors early
- Invalid JSON from model output -> Strict schema validation with one repair attempt
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

### Step 9: Demo Freeze and Release
Objective: freeze a stable MVP branch and package demo assets.

Tasks:
- Run full demo script twice from clean startup.
- Fix blocking defects only; defer stretch work to backlog.
- Tag release and publish demo checklist.
- Prepare release notes with known limitations.

Exit criteria:
- Demo can be executed reliably in less than 10 minutes.

Documentation:
- release notes wiki page
- `README.md` final demo instructions

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
- [ ] Add page-anchored extracted text persistence.

### Step 3 Backlog: Retrieval
- [ ] Implement chunking with configurable chunk size and overlap.
- [ ] Add embeddings and local vector index pipeline.
- [ ] Implement project-scoped top-k retrieval API.

### Step 4 Backlog: Requirements Extraction
- [ ] Define `requirements.json` schema.
- [ ] Implement extraction endpoint with schema validation and repair retry.
- [ ] Add fixture-based extraction tests.

### Step 5 Backlog: Cited Drafting
- [ ] Implement section generation endpoint.
- [ ] Enforce citation integrity against retrieval set.
- [ ] Return and test `missing_evidence[]`.

### Step 6 Backlog: Coverage
- [ ] Implement `met | partial | missing` matrix computation.
- [ ] Link coverage entries to requirement and evidence references.
- [ ] Add matrix edge-case tests.

### Step 7 Backlog: Export and UX
- [ ] Implement JSON and Markdown export endpoint.
- [ ] Add citation click-through in UI.
- [ ] Add loading/error/retry states in UI flow.

### Step 8 Backlog: Hardening
- [ ] Add request correlation IDs and structured logs.
- [ ] Add sensitive-data redaction rules.
- [ ] Document and test backup/restore procedure.

### Step 9 Backlog: Release
- [ ] Run demo script twice from clean setup.
- [ ] Freeze non-critical changes and resolve blockers.
- [ ] Tag MVP release and publish notes.
