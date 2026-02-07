# GrantSmith Development Plan

## Assumptions
- One full-time engineer for 4 weeks (about 160 hours).
- Goal is a stable demo-ready MVP, not production hardening.
- Defaults from `CONTRIBUTING.md`: local FAISS vector store and SQLite metadata store.
- Stretch goals are out of scope unless core MVP is done early.

## MVP Scope
- Upload RFP + nonprofit source docs.
- Extract `requirements.json` from the RFP.
- Generate one cited section `draft.json` with sentence-level citations.
- Produce coverage matrix with `met | partial | missing`.
- Produce `missing_evidence[]` when support is insufficient.
- Export JSON + Markdown.
- Basic validation + tests for core contracts.

## Out of Scope
- Portal autofill integrations.
- Full rich-text editor.
- Broad PDF edge-case support.
- Enterprise auth, RBAC, or full observability stack.

## Week-by-Week Plan

| Week | Focus | Key Work | Exit Criteria |
|---|---|---|---|
| Week 1 | Foundations | Scaffold `backend/` (FastAPI), `frontend/` (Next.js), `docs/schemas/`, `docs/prompts/`; implement file upload + parse + chunk + local indexing; add sample datasets and `.env.example`. | Upload flow works end-to-end and indexed chunks are queryable by project ID. |
| Week 2 | Requirements extraction | Implement `POST /projects/{id}/extract-requirements`; add extraction prompt + strict schema validation + one retry-on-invalid-json path; build UI table for extracted requirements. | `requirements.json` is generated and displayed with valid schema for sample RFPs. |
| Week 3 | Cited drafting core | Implement retrieval + `POST /projects/{id}/generate-section`; return paragraph text, citations, confidence, and `missing_evidence[]`; compute coverage matrix from extracted requirements + cited draft. | Cited section generation works, citations map to real chunks/pages, coverage matrix appears in UI. |
| Week 4 | Hardening + demo | Implement export endpoint (`JSON + Markdown`), clickable citation UX, error/loading states, deterministic model settings, lightweight test pass, demo script and documentation cleanup. | Full demo flow completes in one run with no manual data patching. |

## Day-Level Breakdown

| Days | Deliverable |
|---|---|
| 1-2 | Repo bootstrap, Docker compose skeleton, env templates. |
| 3-4 | Upload API + storage abstraction + document metadata model. |
| 5 | Text extraction/chunking pipeline + smoke test. |
| 6-7 | Embeddings + local retrieval index + retrieval test. |
| 8-9 | Requirements schema + prompt + extraction endpoint. |
| 10 | Requirements UI table + error states. |
| 11-12 | Draft schema + prompt + generation endpoint with citations. |
| 13 | Missing evidence logic + confidence scoring heuristic. |
| 14 | Coverage matrix generation + API + UI. |
| 15 | Export JSON/Markdown + download flow. |
| 16 | End-to-end test pass on sample project. |
| 17 | Determinism tuning (temperature/limits/retries) + stability fixes. |
| 18 | Demo UX polish (loading, failure messages, citation click-through). |
| 19 | Docs and runbook finalization (`README.md`, API notes, demo script). |
| 20 | Buffer for bugs/regressions; freeze MVP branch. |

## Definition of Done
- All MVP endpoints exist and run locally via Docker.
- Core outputs match contracts in `CONTRIBUTING.md`.
- At least one test each for extraction schema validation and cited draft contract.
- Demo script succeeds from clean startup within 10 minutes.
- No fabricated citations in sample runs.

## Risks and Mitigations
- PDF extraction quality risk. Mitigation: constrain demo docs and store page anchors early.
- LLM invalid JSON risk. Mitigation: strict schema checks and one auto-repair retry.
- Citation mismatch risk. Mitigation: require evidence IDs/pages from retrieval payload only.
- Time overrun risk. Mitigation: lock out stretch goals until Day 16.

## Tracking Cadence
- Daily: 15-minute status update (done, next, blockers).
- Twice weekly: run full demo flow and log failures.
- End of each week: compare progress to exit criteria and cut scope if needed.
