# Nebula

Nebula is an Amazon Nova-powered agentic grant development and governance workspace that turns an RFP plus a nonprofit's source documents into a compliant draft with **traceable citations** for every claim. It generates structured sections, a requirements coverage matrix, and flags missing evidence before you submit.

**Hackathon track fit:** Primary `Agentic AI`; Secondary `Multimodal Understanding`  
**Core differentiator:** *Cite-first drafting* — every paragraph is backed by page/snippet references.

## Documentation
- Architecture: `ARCHITECTURE.md`
- Development plan: `DEVELOPMENT_PLAN.md`
- AWS alignment: `AWS_ALIGNMENT.md`
- Category strategy: `docs/wiki/Category-Strategy.md`
- Submission checklist: `docs/wiki/Nova-Submission-Checklist.md`
- Contributor guide: `CONTRIBUTING.md`
- Status source: `docs/status.yml` (sync with `python scripts/sync_docs.py`)

## Current Delivery Status
<!-- AUTO-GEN:README_STATUS:START -->
- Last updated: `2026-02-09`
- Overall completion: `92%`
- Current milestone: `Step 7 - Export and UX (active polish)`

### Done This Week
- Removed required intake step and replaced it with optional advanced context briefing
- Removed template-gated pipeline friction and kept summary/json toggles across artifacts

### Next Up
- Final polish of landing and navigation ergonomics
- Produce and publish the 3-minute demo video with #AmazonNova and functional footage

### Current Blockers
- No blockers recorded.
<!-- AUTO-GEN:README_STATUS:END -->

## Demo in 30 seconds
1. Upload an RFP PDF + org docs (impact report, budget, program plan).
2. Nebula extracts requirements (questions, limits, attachments, eligibility).
3. Generate a section (e.g., Need Statement) with sentence-level citations.
4. Review missing evidence flags + coverage matrix.
5. Export JSON + Markdown artifacts.

---

## Features
### MVP (hackathon scope)
- **RFP Requirements Extractor** → deterministic parser baseline + Nova merge into structured JSON (questions, limits, attachments, deadlines, rubric cues)
- **Evidence Indexing** → chunking + embeddings for retrieval
- **Cited Drafting** → sections generated with citations (doc_id, page, snippet)
- **Coverage Matrix** → requirement status: met / partial / missing, with pointers
- **Validation** → JSON schema validation + basic numeric consistency checks
- **Optional Context Brief** → optional advanced guidance to steer drafting tone/focus
- **Context-Aware Drafting** → optional context brief is passed into section drafting prompts

### Stretch goals
- **Reviewer Mode** → rubric-aligned critique + score estimate
- **Portal Autofill (Nova Act)** → auto-complete application forms in-browser
- **Redaction / PII guardrails** → detect & mask sensitive info before model calls

---

## Architecture (high level)
- **Frontend:** Next.js (landing, workflow controls, artifact review)
- **Backend:** FastAPI (ingestion, parsing, orchestration)
- **Storage (current default):** local filesystem + SQLite
- **Storage (target options):** S3 for uploads, managed metadata store
- **Retrieval:** local embedding similarity over indexed chunks (MVP baseline)
- **Model:** Amazon Nova via Amazon Bedrock (requirements extraction + drafting + review)

### Data flow
1. Upload documents → store originals (local filesystem by default) + parse to text
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

If you use AWS SSO, refresh credentials and export temporary env vars before
starting Docker:

```bash
aws sso login --profile <your_profile>
eval "$(aws configure export-credentials --profile <your_profile> --format env)"
aws sts get-caller-identity
```

Backend example:
```env
APP_ENV=development
CORS_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
REQUEST_ID_HEADER=X-Request-ID
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
BEDROCK_LITE_MODEL_ID=us.amazon.nova-lite-v1:0
AGENT_TEMPERATURE=0.1
AGENT_MAX_TOKENS=2048
ENABLE_AGENTIC_ORCHESTRATION_PILOT=false
S3_BUCKET=nebula-dev
VECTOR_STORE=local
DATABASE_URL=sqlite:///./nebula.db
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

Production-style local stack:
```bash
scripts/run_docker_env.sh restart
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

## CI/CD (Docker-first)

- CI workflow: `.github/workflows/ci.yml`
  - backend tests (`pytest`)
  - deterministic submission-critical backend gate (`backend-deterministic-reliability`, 3-run matrix)
  - frontend typecheck/build
  - dockerized smoke test using `scripts/run_docker_env.sh`

Reliability evidence:
- `docs/wiki/CI-Reliability-2026-02-08.md`
- `docs/wiki/Impact-Metrics-Baseline-2026-02-08.md`
- `docs/wiki/Agentic-Orchestration-Pilot-2026-02-08.md`
- `docs/wiki/Devpost-Narrative-Draft-2026-02-08.md`
- `docs/wiki/Devpost-Testing-Instructions-2026-02-08.md`

- CD workflow: `.github/workflows/deploy-aws.yml`
  - builds backend/frontend images
  - pushes images to Amazon ECR
  - rolls out backend/frontend ECS services

Required GitHub secrets for deploy:
- `AWS_ROLE_TO_ASSUME`
- `AWS_REGION`
- `ECR_BACKEND_REPOSITORY`
- `ECR_FRONTEND_REPOSITORY`
- `ECS_CLUSTER`
- `ECS_BACKEND_SERVICE`
- `ECS_FRONTEND_SERVICE`
- `NEXT_PUBLIC_API_BASE`

Deployment note:
- Current ECS rollout uses `--force-new-deployment` after pushing `:latest`; task definitions should reference `:latest` for both services.

---

## Key endpoints (current baseline)

* `GET /health` → backend health check
* `GET /ready` → backend readiness check
* `GET /api/health` → frontend health check
* `POST /projects` → create a project
* `POST /projects/{id}/upload` → upload one or more source files
* `GET /projects/{id}/documents` → list uploaded document metadata
* `POST /projects/{id}/retrieve` → semantic retrieval over indexed chunks
* `POST /projects/{id}/extract-requirements` → generate validated `requirements` artifact
* `GET /projects/{id}/requirements/latest` → fetch latest requirements artifact
* `POST /projects/{id}/generate-section` → generate cited section draft artifact
* `GET /projects/{id}/drafts/{section_key}/latest` → fetch latest section draft artifact
* `POST /projects/{id}/coverage` → compute coverage matrix from latest requirements + draft
* `GET /projects/{id}/coverage/latest` → fetch latest coverage artifact
* `GET /projects/{id}/export` → export combined artifacts in `json` or `markdown`

All backend responses include a request correlation header (`X-Request-ID` by default).

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

If a claim cannot be supported, Nebula must:

* mark it as **unsupported**
* add an item to `missing_evidence[]` with suggested uploads

---

## Safety & privacy

* Only the minimum necessary text is sent to the model.
* Original files remain in your controlled storage (local filesystem by default; S3 optional).
* Optional redaction hooks can mask PII before LLM calls.
* Structured logs include correlation IDs and redact sensitive fields/patterns.

---

## Hackathon notes

* Demo video target: ~3 minutes
* Include: requirements extraction → cited drafting → missing evidence → export
* Highlight: structured outputs, validation, traceability, and real-world impact
