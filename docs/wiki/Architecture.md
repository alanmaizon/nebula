# Nebula Architecture Plan

## 1) Purpose
Nebula is an evidence-backed drafting system that turns an RFP plus nonprofit documents into:
- `requirements.json`
- cited section drafts (`draft.json`)
- coverage matrix (`met | partial | missing`)
- `missing_evidence[]`

This architecture is optimized for a 1-month MVP build with reliable demo behavior.

## 2) Architecture Principles
- Citation-first generation: every claim must map to retrievable evidence.
- Structured outputs only: model responses must validate against JSON schemas.
- Deterministic demo behavior: conservative model settings and explicit retries.
- Replaceable infrastructure: local defaults now, cloud-ready interfaces later.
- Minimal coupling: parsing, retrieval, generation, validation, and export are separate modules.

## 3) High-Level System Design
```mermaid
flowchart LR
    U[User] --> FE[Next.js Frontend]
    FE --> API[FastAPI API Layer]
    API --> ORCH[Workflow Orchestrator]

    ORCH --> PARSER[Parser and Chunker]
    PARSER --> OBJ[(Object Storage<br/>Local or S3)]
    PARSER --> DB[(Metadata DB<br/>SQLite or Postgres)]

    ORCH --> EMB[Embedding Service]
    EMB --> VDB[(Vector Store<br/>FAISS or pgvector or OpenSearch)]

    ORCH --> LLM[Bedrock Nova]
    ORCH --> VAL[Schema Validator]
    ORCH --> COV[Coverage Engine]

    VAL --> DB
    COV --> DB
    API --> EXP[Export Service]
    EXP --> DB
```

## 4) Component Responsibilities
| Component | Responsibility | Inputs | Outputs |
|---|---|---|---|
| Frontend (Next.js) | Upload, trigger workflows, display results, export downloads | user actions | API requests |
| API Layer (FastAPI) | Auth/session boundary, endpoint routing, response shaping | HTTP requests | workflow commands/results |
| Workflow Orchestrator | Coordinates parse/retrieve/generate/validate pipeline | project + section commands | normalized artifacts |
| Parser and Chunker | Extract text/page anchors, chunk documents | uploaded files | chunks + metadata |
| Embedding Service | Convert chunks to vectors | chunks | embeddings |
| Vector Store | Retrieval by semantic similarity + filters | query + project scope | ranked evidence chunks |
| Bedrock Nova | Requirements extraction + drafting with strict prompts | limited context payload | JSON model output |
| Schema Validator | Enforce output contracts; repair once when invalid | model JSON | valid typed objects or error |
| Coverage Engine | Map requirements to evidence-backed draft support | requirements + draft | coverage matrix + gaps |
| Export Service | Build JSON/Markdown export packages | stored artifacts | downloadable files |
| Metadata DB | Source of truth for project state and artifacts | all pipeline writes | queryable records |
| Object Storage | Durable raw document storage | uploads | file references |

## 5) Core Workflows

### 5.1 Ingestion and Requirements Extraction
```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as FastAPI
    participant ORCH as Orchestrator
    participant PRS as Parser/Chunker
    participant EMB as Embedding Service
    participant VDB as Vector Store
    participant LLM as Bedrock Nova
    participant VAL as Validator
    participant DB as Metadata DB

    FE->>API: POST /projects/{id}/upload
    API->>ORCH: start_ingestion(project_id, files)
    ORCH->>PRS: parse(files)
    PRS->>DB: save documents/chunks/page anchors
    ORCH->>EMB: embed(chunks)
    EMB->>VDB: index(project_id, vectors)
    ORCH->>DB: mark ingestion complete

    FE->>API: POST /projects/{id}/extract-requirements
    API->>ORCH: extract_requirements(project_id)
    ORCH->>LLM: prompt + relevant RFP context
    LLM-->>ORCH: requirements JSON
    ORCH->>VAL: validate against schema
    VAL-->>ORCH: valid object or retry signal
    ORCH->>DB: persist requirements.json
    ORCH-->>API: extraction result
    API-->>FE: requirements payload
```

### 5.2 Cited Section Generation and Coverage Update
```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as FastAPI
    participant ORCH as Orchestrator
    participant VDB as Vector Store
    participant LLM as Bedrock Nova
    participant VAL as Validator
    participant COV as Coverage Engine
    participant DB as Metadata DB

    FE->>API: POST /projects/{id}/generate-section
    API->>ORCH: generate_section(project_id, section_key)
    ORCH->>VDB: retrieve top-k evidence chunks
    VDB-->>ORCH: evidence set (doc_id/page/snippet)
    ORCH->>LLM: section prompt + retrieved evidence only
    LLM-->>ORCH: draft JSON with citations/confidence
    ORCH->>VAL: validate draft schema
    VAL-->>ORCH: valid object or retry signal
    ORCH->>COV: compute(requirements, draft)
    COV-->>ORCH: coverage matrix + missing evidence
    ORCH->>DB: persist draft.json + coverage + gaps
    ORCH-->>API: generation result
    API-->>FE: section, citations, matrix, gaps
```

## 6) Data Model (Logical)
```mermaid
erDiagram
    PROJECT ||--o{ DOCUMENT : has
    DOCUMENT ||--o{ CHUNK : splits_into
    PROJECT ||--o{ REQUIREMENT : defines
    PROJECT ||--o{ SECTION_DRAFT : contains
    SECTION_DRAFT ||--o{ PARAGRAPH : has
    PARAGRAPH ||--o{ CITATION : cites
    PROJECT ||--o{ COVERAGE_ITEM : tracks
    PROJECT ||--o{ MISSING_EVIDENCE : records

    PROJECT {
      string id
      string name
      datetime created_at
      string status
    }
    DOCUMENT {
      string id
      string project_id
      string file_name
      string file_type
      string storage_uri
    }
    CHUNK {
      string id
      string document_id
      int page
      string text
      string embedding_ref
    }
    REQUIREMENT {
      string id
      string project_id
      string prompt
      string limit_type
      int limit_value
    }
    SECTION_DRAFT {
      string id
      string project_id
      string section_key
      datetime generated_at
    }
    PARAGRAPH {
      string id
      string draft_id
      string text
      float confidence
    }
    CITATION {
      string id
      string paragraph_id
      string doc_id
      int page
      string snippet
    }
    COVERAGE_ITEM {
      string id
      string project_id
      string requirement_id
      string status
      string notes
    }
    MISSING_EVIDENCE {
      string id
      string project_id
      string claim
      string suggested_upload
    }
```

## 7) API Surface (MVP)
- `POST /projects`
- `POST /projects/{id}/upload`
- `POST /projects/{id}/extract-requirements`
- `POST /projects/{id}/generate-section`
- `GET /projects/{id}/export`

Contracts for `requirements.json`, `draft.json`, and coverage matrix follow `CONTRIBUTING.md`.

## 7.1) Runtime Intelligence Call Path (Current Submission Path)

Current backend runtime path (Nova on Bedrock):
- `POST /projects/{project_id}/extract-requirements`
  - endpoint: `backend/app/main.py` (`extract_requirements`)
  - orchestrator: `backend/app/nova_runtime.py` (`BedrockNovaOrchestrator.extract_requirements`)
  - model ID: `BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0`
  - artifact source tag: `nova-agents-v1`
- `POST /projects/{project_id}/generate-section`
  - endpoint: `backend/app/main.py` (`generate_section`)
  - orchestrator: `backend/app/nova_runtime.py` (`BedrockNovaOrchestrator.generate_section`)
  - model ID: `BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0`
  - artifact source tag: `nova-agents-v1`
- `POST /projects/{project_id}/coverage`
  - endpoint: `backend/app/main.py` (`compute_coverage`)
  - orchestrator: `backend/app/nova_runtime.py` (`BedrockNovaOrchestrator.compute_coverage`)
  - model ID: `BEDROCK_LITE_MODEL_ID=us.amazon.nova-lite-v1:0`
  - artifact source tag: `nova-agents-v1`

Execution flow:
- FastAPI endpoint -> Nova orchestrator stage -> Bedrock `converse` -> schema validation/repair -> artifact persistence
- If Nova invocation fails, endpoint returns `502` with explicit runtime failure details.

## 7.2) Agentic Orchestration Pilot (Feature-Flagged)

Pilot scope:
- workflow stage: section generation planning + verification refinement
- endpoint: `POST /projects/{project_id}/generate-section`
- feature flag: `ENABLE_AGENTIC_ORCHESTRATION_PILOT` (default `false`)

Pilot flow when enabled:
1. Planner stage (`BedrockNovaOrchestrator.plan_section_generation`) chooses retrieval `top_k` and retry policy.
2. Writer stage generates draft from planned retrieval set.
3. Verification stage checks `missing_evidence`; if present, orchestrator expands retrieval window and retries once.
4. Best validated draft is persisted with unchanged API contract and citation schema requirements.

Tradeoffs:
- Determinism preserved by default (`false`) and bounded retry policy (single retry, bounded `top_k`).
- Autonomy introduced only in controlled planning/refinement decisions.
- Citation grounding requirements are unchanged: draft schema still requires explicit citation objects and validation gate remains mandatory.

## 8) Validation and Error Strategy
- Every model response is schema-validated before persistence.
- On validation failure: one structured repair attempt, then explicit error.
- Citation guardrail: reject citations that do not match retrieved evidence IDs/pages.
- Determinism defaults: low temperature, bounded context, bounded token limits.

## 9) Security and Privacy Baseline
- No secrets in repository.
- Encrypt data in transit; encrypt storage where available.
- Limit model payloads to required text chunks only.
- Redact sensitive values in logs; never log full raw documents.
- Role-based access and tenant scoping at API boundary.

## 10) Deployment Topology
```mermaid
flowchart TB
    subgraph Local_MVP
      FE1[Next.js]
      API1[FastAPI]
      DB1[(SQLite)]
      V1[(FAISS)]
      FS1[(Local Files)]
    end

    subgraph Cloud_Target
      FE2[Next.js]
      API2[FastAPI]
      DB2[(Postgres)]
      V2[(pgvector or OpenSearch)]
      S3[(S3)]
      BR[Bedrock Nova]
    end

    FE1 --> API1
    API1 --> DB1
    API1 --> V1
    API1 --> FS1

    FE2 --> API2
    API2 --> DB2
    API2 --> V2
    API2 --> S3
    API2 --> BR
```

## 11) Build Order (Architecture-First)
1. Implement ingestion, chunking, and indexing pipeline.
2. Implement requirements extraction with strict schema validation.
3. Implement cited drafting with retrieval-constrained prompts.
4. Implement coverage and missing evidence computation.
5. Implement export and demo-safe UX states.
