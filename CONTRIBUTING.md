# Contributor & Agent Instructions

This repository is built for fast iteration with agents. Follow these rules to keep changes safe, reviewable, and demo-ready.

## Goals (what “done” means)
1. Nebula can ingest an RFP + nonprofit docs.
2. It produces:
   - `requirements.json` (structured extraction)
   - a cited draft section (`draft.json`)
   - a coverage matrix (met/partial/missing)
   - a list of missing evidence items
3. All model outputs are validated against schemas and are deterministic enough for a demo.

## Non-goals (don’t waste time)
- Full grant portal integration unless clearly scoped as a stretch goal
- Building a full rich-text editor (use a simple markdown editor + preview)
- Perfect PDF parsing for every edge case (optimize for demo docs)

---

## Working style
- Prefer small PR-sized changes.
- Always include:
  - what you changed
  - how to run it
  - what to click in the demo
- If you introduce new env vars, update README + `.env.example`.

## Repo conventions
- TypeScript in `frontend/`
- Python in `backend/`
- Shared JSON schemas in `docs/schemas/`
- Prompts in `docs/prompts/`

---

## Bedrock / Nova usage rules
- **Always** request structured outputs (JSON) for core flows.
- Enforce a strict schema per task:
  - requirements extraction schema
  - section draft schema (with citations)
  - review schema (optional)
- Set conservative token limits for demo stability.
- Never fabricate citations: every citation must correspond to retrieved evidence.

### “Text only” principle
Only send:
- the RFP requirement text chunks needed
- the retrieved evidence chunks used for drafting
Do **not** send raw files.

---

## Output contracts (must not break)

### 1) Requirements extraction (`requirements.json`)
Must include:
- `funder`, `deadline`, `eligibility[]`
- `questions[]` with `id`, `prompt`, `limit` (words/chars if known)
- `required_attachments[]`
- `rubric[]` (if available)
- `disallowed_costs[]` (if available)

### 2) Draft section (`draft.json`)
Each paragraph must contain:
- `text`
- `citations[]` (doc_id, page, snippet)
- `confidence` (0–1)
Also include:
- `missing_evidence[]` with `claim` + `suggested_upload`

### 3) Coverage matrix
List of requirements with:
- `status`: `met | partial | missing`
- `notes`
- `evidence_refs[]` (citations or doc pointers)

---

## Prompts (how to write them)
- Put prompts in `docs/prompts/` as files.
- Prompts must:
  - instruct “return valid JSON only”
  - include the schema (or a concise field list)
  - include grounding rules: “use only provided context”
  - require citations from retrieved evidence IDs/pages

### Example grounding rule block
- Use only the context provided below.
- If a claim cannot be supported, mark it unsupported and add it to `missing_evidence`.
- Do not invent numbers, dates, locations, outcomes, or partners.

---

## Validation & testing
- Add a schema validator on every model response.
- If validation fails:
  - retry once with a “fix JSON to match schema” prompt
  - otherwise return a clear error to the UI
- Add lightweight tests for:
  - schema validation
  - requirements parser on sample RFP
- section generation produces citations + no empty fields

## Documentation automation
- Use `docs/status.yml` as the source of truth for delivery status.
- Run `python scripts/sync_docs.py` after updating status.
- Generated blocks are maintained in:
  - `README.md`
  - `DEVELOPMENT_PLAN.md`
  - `AWS_ALIGNMENT.md`
- CI will fail if generated docs are stale (`python scripts/sync_docs.py --check`).

---

## UI demo requirements
The UI must show:
1. Uploaded documents list
2. Extracted requirements table
3. Generated section with clickable citations
4. Missing evidence list
5. Export buttons (JSON + Markdown)

Keep the UI minimal: one-page flow is fine.

---

## What Codex should do when asked to implement a feature
1. Identify the relevant schema(s) and update if needed.
2. Implement backend endpoint first.
3. Add validation + one test.
4. Wire frontend to endpoint with clear loading/error states.
5. Update README if run steps or env vars change.

---

## “Stop and ask” conditions
If any of these are unclear, propose a default and proceed (don’t stall):
- Which vector store to use → default: local FAISS for demo
- Which DB → default: SQLite for backend demo
- Which export format → default: JSON + Markdown

---

## Security / compliance notes
- Do not store secrets in git.
- Never log full document contents in production mode.
- Prefer redacting PII in logs and model payloads.

---

## Quick commands (expected to work)
```bash
docker compose up --build
````

```bash
cd backend && pytest
```

```bash
cd frontend && npm test
```

```bash
python scripts/sync_docs.py
```
