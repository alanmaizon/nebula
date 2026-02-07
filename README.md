![GrantSmith Logo](LOGO.png)

# Evidence-Backed Grant Writing

GrantSmith is a grant-application workspace that turns an RFP plus a nonprofit’s source documents into a compliant draft with **traceable citations** for every claim. It generates structured sections, a requirements coverage matrix, and flags missing evidence before you submit.

**Hackathon track fit:** Multimodal / Agentic (requirements extraction + evidence-linked drafting)  
**Core differentiator:** *Cite-first drafting* — every paragraph is backed by page/snippet references.

## Documentation
- Architecture: `ARCHITECTURE.md`
- Development plan: `DEVELOPMENT_PLAN.md`
- AWS alignment: `AWS_ALIGNMENT.md`
- Contributor guide: `CONTRIBUTING.md`
- Status source: `docs/status.yml` (sync with `python scripts/sync_docs.py`)

## Current Delivery Status
<!-- AUTO-GEN:README_STATUS:START -->
- Last updated: `2026-02-07`
- Overall completion: `52%`
- Current milestone: `Week 1 - Foundations (In progress)`

### Done This Week
- Repository baseline documentation created
- Architecture plan with Mermaid diagrams added
- AWS alignment draft documented
- GitHub governance bootstrap completed (labels, milestones, issues, wiki sync)
- Bootstrap automation hardened (wiki-only mode and project parser compatibility)
- Backend and frontend scaffolds created with health endpoints
- Docker Compose baseline added with service health checks
- Project creation and document upload metadata endpoints implemented
- Chunking pipeline added with configurable chunk size and overlap
- Local embedding and project-scoped retrieval endpoint implemented

### Next Up
- Create requirements extraction schema scaffold and endpoint skeleton
- Implement extraction response validation and repair retry
- Render extracted requirements table in frontend

### Current Blockers
- No blockers recorded.
<!-- AUTO-GEN:README_STATUS:END -->

## Demo in 30 seconds
1. Upload an RFP PDF + org docs (impact report, budget, program plan).
2. GrantSmith extracts requirements (questions, limits, attachments, eligibility).
3. Generate a section (e.g., Need Statement) with sentence-level citations.
4. Review missing evidence flags + coverage matrix.
5. Export JSON + Markdown/Docx draft.

---

## Features
### MVP (hackathon scope)
- **RFP Requirements Extractor** → structured JSON (questions, word/char limits, attachments, deadlines, rubric cues)
- **Evidence Indexing** → chunking + embeddings for retrieval
- **Cited Drafting** → sections generated with citations (doc_id, page, snippet)
- **Coverage Matrix** → requirement status: met / partial / missing, with pointers
- **Validation** → JSON schema validation + basic numeric consistency checks

### Stretch goals
- **Reviewer Mode** → rubric-aligned critique + score estimate
- **Portal Autofill (Nova Act)** → auto-complete application forms in-browser
- **Redaction / PII guardrails** → detect & mask sensitive info before model calls

---

## Architecture (high level)
- **Frontend:** Next.js (upload, editor, evidence sidebar, exports)
- **Backend:** FastAPI (ingestion, parsing, orchestration)
- **Storage:** S3 for uploads, Postgres/DynamoDB for metadata (choose one)
- **Retrieval:** embeddings + vector store (OpenSearch / pgvector / local FAISS)
- **Model:** Amazon Nova via Amazon Bedrock (requirements extraction + drafting + review)

### Data flow
1. Upload documents → store originals (S3) + parse to text
2. Chunk text → embed → index
3. Extract RFP requirements → `requirements.json`
4. For each section:
   - retrieve top evidence chunks
   - generate draft + citations → `draft.json`
5. Validate:
   - schema validation
   - coverage matrix update
   - missing evidence list

---

## Repo layout
```
.
├── backend/                 # FastAPI API
├── frontend/                # Next.js UI
├── docs/                    # prompts, JSON schemas, demo assets
├── scripts/                 # automation scripts
├── docker-compose.yml
├── README.md
└── CONTRIBUTING.md
```

---

## Getting started (local dev)
### Prerequisites
- Node.js 18+
- Python 3.11+
- AWS account with Bedrock access enabled for Amazon Nova
- AWS credentials configured locally (`aws configure`) or via env vars

### Environment variables
Create local env files from templates:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

Backend example:
```env
APP_ENV=development
CORS_ORIGINS=http://localhost:3000
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=<your-nova-model-id>
S3_BUCKET=grantsmith-dev
VECTOR_STORE=local
DATABASE_URL=sqlite:///./grantsmith.db
STORAGE_ROOT=data/uploads
CHUNK_SIZE_CHARS=1200
CHUNK_OVERLAP_CHARS=200
EMBEDDING_DIM=128
RETRIEVAL_TOP_K_DEFAULT=5
```

Frontend example:
```env
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

### Run with Docker (recommended)
```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Frontend health: http://localhost:3000/api/health
- Backend: http://localhost:8000
- Backend docs: http://localhost:8000/docs
- Backend health: http://localhost:8000/health

### Run without Docker

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

---

## Key endpoints (current baseline)

* `GET /health` → backend health check
* `GET /ready` → backend readiness check
* `GET /api/health` → frontend health check
* `POST /projects` → create a project
* `POST /projects/{id}/upload` → upload one or more source files
* `GET /projects/{id}/documents` → list uploaded document metadata
* `POST /projects/{id}/retrieve` → semantic retrieval over indexed chunks

Planned endpoints in next implementation steps:
* `POST /projects/{id}/extract-requirements`
* `POST /projects/{id}/generate-section`
* `GET /projects/{id}/export`

---

## Evidence + citations contract

A “citation” references *exactly where a claim comes from*:

```json
{
  "doc_id": "impact_report_2024.pdf",
  "page": 7,
  "snippet": "…served 1,240 households…"
}
```

If a claim cannot be supported, GrantSmith must:

* mark it as **unsupported**
* add an item to `missing_evidence[]` with suggested uploads

---

## Safety & privacy

* Only the minimum necessary text is sent to the model.
* Original files remain in your controlled storage (S3/local).
* Optional redaction hooks can mask PII before LLM calls.

---

## Hackathon notes

* Demo video target: ~3 minutes
* Include: requirements extraction → cited drafting → missing evidence → export
* Highlight: structured outputs, validation, traceability, and real-world impact
