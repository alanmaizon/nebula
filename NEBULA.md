# Nebula: Multi-Agent Migration Checkpoint (AWS Strands + Amazon Nova)

## Context
Nebula is a grant-writing assistant positioned for the Agentic AI track of the Amazon Nova Hackathon (deadline: **March 16, 2026**).

The MVP has a complete end-to-end workflow:
- ingest
- extract requirements
- draft with citations
- coverage
- export

Current gap: all intelligence is heuristic-based (no Bedrock/Nova calls, no agentic patterns).

Required shift: replace heuristic logic with a true multi-agent system using **AWS Strands Agents SDK** and **Amazon Nova** models.

## Decisions Made
- **Framework:** AWS Strands Agents SDK (AWS-native, explicitly referenced in hackathon rules)
- **Fallback strategy:** all-in on Nova; remove heuristic logic from the primary path
- **Architecture:** 4 specialized agents + 1 deterministic orchestrator

## Target Architecture
```text
Orchestrator (deterministic pipeline)
  ├── RFP Analyst Agent      (Nova Pro)  → RequirementsArtifact
  ├── Evidence Researcher    (Nova Lite) → Ranked evidence chunks
  ├── Grant Writer Agent     (Nova Pro)  → DraftArtifact
  └── Compliance Reviewer    (Nova Lite) → CoverageArtifact
```

## Scope Boundaries
- **Unchanged surface API:** existing Pydantic schemas, FastAPI endpoints, and frontend
- **Changed internals:** logic behind 3 endpoints swaps from heuristic functions to agent calls

## New Directory Structure
```text
backend/app/agents/
├── __init__.py
├── model.py                  # BedrockModel factory (Nova Pro + Lite)
├── rfp_analyst.py            # Agent: extract requirements from RFP
├── evidence_researcher.py    # Agent: find + rerank evidence
├── grant_writer.py           # Agent: draft sections with citations
├── compliance_reviewer.py    # Agent: evaluate requirement coverage
├── orchestrator.py           # Coordinates agents, called from main.py
└── tools/
    ├── __init__.py
    ├── chunk_tools.py        # read_chunks, search_chunks
    ├── evidence_tools.py     # fetch_evidence, build_citation
    └── artifact_tools.py     # read_requirements, read_drafts
```

## Files to Modify
| File | Change |
|---|---|
| `backend/requirements.txt` | Add `strands-agents`, `boto3` |
| `backend/app/config.py` | Add `bedrock_lite_model_id`, `agent_temperature`, `agent_max_tokens`; set `bedrock_model_id` default to `us.amazon.nova-pro-v1:0` |
| `backend/app/main.py:303` | Replace `extract_requirements_payload(chunks)` with `run_extract_requirements(chunks)` |
| `backend/app/main.py:337-338` | Replace `rank_chunks_by_query` + `build_draft_payload` with `run_generate_section(...)` |
| `backend/app/main.py:400-403` | Replace `build_coverage_payload(...)` with `run_compute_coverage(...)` |
| `backend/app/main.py:317,353,418` | Change `source` from `"heuristic-v1"` to `"nova-agents-v1"` |
| `docker-compose.yml` | Add AWS credential env vars + model config passthrough |

### Explicitly Not Changed
- `requirements.py`, `drafting.py`, `coverage.py` keep:
  - Pydantic models
  - `validate_with_repair` functions (schema safety net on agent output)
- Heuristic extraction functions may remain in-file but are no longer called from main path

## Implementation Steps
### Step 1: Dependencies + Config
- Add `strands-agents>=1.25.0` and `boto3>=1.35.0` to `requirements.txt`
- Add settings in `config.py`:
  - `bedrock_lite_model_id`
  - `agent_temperature`
  - `agent_max_tokens`
- Set `bedrock_model_id` default to `"us.amazon.nova-pro-v1:0"`
- Update `docker-compose.yml` with AWS credential passthrough

### Step 2: Model Factory
Create `backend/app/agents/model.py` with:
- `create_nova_pro_model()`
- `create_nova_lite_model()`

Both should use `strands.models.BedrockModel`.

### Step 3: Agent Tools
Create:
- `tools/chunk_tools.py`
  - `read_chunks` (formats chunks for RFP analysis)
  - `search_chunks` (cosine similarity retrieval)
- `tools/evidence_tools.py`
  - `fetch_evidence` (formats evidence for writing)
  - `build_citation` (constructs citation JSON)
- `tools/artifact_tools.py`
  - `read_requirements`
  - `read_drafts` (format artifacts for compliance review)

### Step 4: Agents (build one at a time, test each)
- **RFP Analyst (`rfp_analyst.py`)**
  - Model: Nova Pro
  - Tools: `read_chunks`
  - Prompt target: JSON extraction matching `RequirementsArtifact`
  - Use `structured_output_model=RequirementsArtifact`
- **Evidence Researcher (`evidence_researcher.py`)**
  - Model: Nova Lite
  - Tools: `search_chunks`
  - Flow: cosine pre-retrieval, then Nova semantic rerank
- **Grant Writer (`grant_writer.py`)**
  - Model: Nova Pro
  - Tools: `fetch_evidence`, `build_citation`
  - Rule: citation-first drafting, every paragraph cites evidence
  - Use `structured_output_model=DraftArtifact`
- **Compliance Reviewer (`compliance_reviewer.py`)**
  - Model: Nova Lite
  - Tools: `read_requirements`, `read_drafts`
  - Replaces token-overlap logic with semantic coverage analysis
  - Use `structured_output_model=CoverageArtifact`

### Step 5: Orchestrator
Create `orchestrator.py` with endpoint-mapped functions:
- `run_extract_requirements(chunks)` → calls RFP Analyst
- `run_generate_section(section_key, chunks, top_k)` → calls Evidence Researcher then Grant Writer
- `run_compute_coverage(requirements, draft)` → calls Compliance Reviewer

Constraint: create a fresh Agent instance per request to avoid concurrency issues.

### Step 6: Wire Into `main.py`
- Import orchestrator functions
- Swap 3 lines in extract-requirements endpoint (line 303)
- Swap 2 lines in generate-section endpoint (lines 337-338)
- Swap 4 lines in compute-coverage endpoint (lines 400-403)
- Change source tag from `"heuristic-v1"` to `"nova-agents-v1"`
- Keep `validate_with_repair` calls as schema safety net

### Step 7: Tests
- Add `tests/test_agents/` with mock-based agent tests
- Use `unittest.mock.patch` to mock `BedrockModel`
- Ensure existing `test_health.py` still passes (mock orchestrator-level agent calls)
- Add integration test for full pipeline with mocked Bedrock

## Verification
### Unit Tests
```bash
cd backend && python -m pytest tests/ -v
```

### Local Run With Bedrock
Set:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`

Then run:
```bash
uvicorn app.main:app --reload
```

Use frontend at `localhost:3000` to hit endpoints.

### Full Pipeline Validation
Run: create project → upload sample RFP → extract requirements → generate section → compute coverage → export.

Verify:
- Requirements output matches `RequirementsArtifact` schema with Nova-generated content
- Draft paragraphs include real citations (`doc_id`, `page`, `snippet`)
- Coverage items include semantic notes (not hardcoded heuristic strings)
- All artifacts show `source: "nova-agents-v1"`

### Docker
```bash
docker compose up --build
```

Expected: health checks pass on both services.

## Detailed Task Expansion (Issue-Oriented)
Use this section as the operational breakdown for GitHub issues. The sequence below is dependency-ordered.

| Issue Key | Title | Depends On |
|---|---|---|
| NOVA-01 | Add runtime dependencies and Nova config plumbing | None |
| NOVA-02 | Create agents package scaffold + model factory | NOVA-01 |
| NOVA-03 | Implement shared agent tools | NOVA-02 |
| NOVA-04 | Build RFP Analyst agent (RequirementsArtifact) | NOVA-03 |
| NOVA-05 | Build Evidence Researcher agent (rerank flow) | NOVA-03 |
| NOVA-06 | Build Grant Writer agent (citation-first) | NOVA-03, NOVA-05 |
| NOVA-07 | Build Compliance Reviewer agent (CoverageArtifact) | NOVA-03, NOVA-04, NOVA-06 |
| NOVA-08 | Build deterministic orchestrator integration layer | NOVA-04, NOVA-05, NOVA-06, NOVA-07 |
| NOVA-09 | Wire FastAPI endpoints to orchestrator | NOVA-08 |
| NOVA-10 | Add tests for agents and orchestration | NOVA-09 |
| NOVA-11 | Add observability, safeguards, and fallback policy | NOVA-09 |
| NOVA-12 | Collect submission evidence and run demo rehearsal | NOVA-10, NOVA-11 |

### NOVA-01: Add Runtime Dependencies and Nova Config Plumbing
Outcome: environment is capable of Bedrock Nova inference with explicit model configuration.

Tasks:
- Add `strands-agents>=1.25.0` and `boto3>=1.35.0` to `backend/requirements.txt`.
- Add to `backend/app/config.py`:
  - `bedrock_model_id` default `us.amazon.nova-pro-v1:0`
  - `bedrock_lite_model_id` default `us.amazon.nova-lite-v1:0`
  - `agent_temperature` default `0.1`
  - `agent_max_tokens` default `2000`
- Add env passthrough to `docker-compose.yml`:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION`
  - `BEDROCK_MODEL_ID`
  - `BEDROCK_LITE_MODEL_ID`
  - `AGENT_TEMPERATURE`
  - `AGENT_MAX_TOKENS`

Acceptance criteria:
- App starts with no config validation errors when env vars are absent (defaults work).
- App honors env overrides for both Pro and Lite model IDs.
- Local and Docker startup paths both receive AWS credentials.

Verification:
- `cd backend && python -m pytest tests/test_health.py -v`
- `docker compose config` shows passthrough vars on backend service.

### NOVA-02: Create Agents Package Scaffold + Model Factory
Outcome: a single model creation path is available for all agents.

Tasks:
- Add `backend/app/agents/__init__.py`.
- Add `backend/app/agents/model.py` with:
  - `create_nova_pro_model(settings)`
  - `create_nova_lite_model(settings)`
- Ensure shared Bedrock client setup is centralized (region, timeout, retry strategy).
- Add lightweight input validation for missing model ID strings.

Acceptance criteria:
- Both factory functions return initialized BedrockModel instances.
- Factory can be imported by all agent modules without circular import.

Verification:
- Unit test for each factory function with mocked BedrockModel constructor.

### NOVA-03: Implement Shared Agent Tools
Outcome: reusable data formatting and retrieval helpers are available as Strands tools.

Tasks:
- Add `backend/app/agents/tools/chunk_tools.py`:
  - `read_chunks(chunks)` for structured chunk context formatting
  - `search_chunks(query, chunks, top_k)` with cosine similarity ordering
- Add `backend/app/agents/tools/evidence_tools.py`:
  - `fetch_evidence(chunk_ids, chunks)` returning normalized evidence payload
  - `build_citation(doc_id, page, snippet)` returning citation object
- Add `backend/app/agents/tools/artifact_tools.py`:
  - `read_requirements(requirements)`
  - `read_drafts(draft)`
- Keep tool outputs deterministic and schema-safe (no free-form key drift).

Acceptance criteria:
- Tools produce stable output shapes for identical input.
- Search tool gracefully handles empty chunk sets and low-similarity results.

Verification:
- Unit tests for each tool with edge cases (empty input, malformed metadata, top_k bounds).

### NOVA-04: Build RFP Analyst Agent (RequirementsArtifact)
Outcome: requirements extraction is powered by Nova Pro with structured output.

Tasks:
- Implement `backend/app/agents/rfp_analyst.py`.
- Use Nova Pro model from factory.
- Register `read_chunks` tool.
- Write system prompt enforcing extraction-only behavior and no hallucinated requirements.
- Bind `structured_output_model=RequirementsArtifact`.
- Add explicit failure path when model output cannot be validated.

Acceptance criteria:
- Valid extraction returns `RequirementsArtifact` compatible dict/object.
- Invalid outputs are surfaced with actionable error context.

Verification:
- Mocked tests for: success, schema-invalid first response, and hard failure.

### NOVA-05: Build Evidence Researcher Agent (Rerank Flow)
Outcome: evidence retrieval quality improves via semantic reranking.

Tasks:
- Implement `backend/app/agents/evidence_researcher.py`.
- Use Nova Lite model from factory.
- Use `search_chunks` as candidate generation stage.
- Add Nova semantic rerank stage over top candidates.
- Return ranked chunk references with scores/reasoning hints for traceability.

Acceptance criteria:
- Agent returns top-k ranked evidence items scoped to project chunks.
- Empty or weak evidence states are explicit and machine-readable.

Verification:
- Mocked tests for rerank ordering and no-evidence case.

### NOVA-06: Build Grant Writer Agent (Citation-First)
Outcome: section drafting is grounded in selected evidence and emits `DraftArtifact`.

Tasks:
- Implement `backend/app/agents/grant_writer.py`.
- Use Nova Pro model.
- Register `fetch_evidence` and `build_citation`.
- Enforce prompt policy: every paragraph must map to at least one citation.
- Bind `structured_output_model=DraftArtifact`.
- Include `missing_evidence[]` behavior for unsupported claims.

Acceptance criteria:
- Draft output validates against `DraftArtifact`.
- All citations map to known chunk/doc/page/snippet sources.

Verification:
- Mocked tests for valid citation mapping and unsupported-claim path.

### NOVA-07: Build Compliance Reviewer Agent (CoverageArtifact)
Outcome: coverage analysis moves from heuristic overlap to semantic evaluation.

Tasks:
- Implement `backend/app/agents/compliance_reviewer.py`.
- Use Nova Lite model.
- Register `read_requirements` and `read_drafts`.
- Bind `structured_output_model=CoverageArtifact`.
- Add deterministic label normalization to `met | partial | missing`.

Acceptance criteria:
- Coverage output validates against `CoverageArtifact`.
- Semantic notes are specific to requirement/draft pairs, not boilerplate text.

Verification:
- Mocked tests for mixed-status matrix and normalization fallback.

### NOVA-08: Build Deterministic Orchestrator Integration Layer
Outcome: endpoint-facing functions coordinate agents in strict order.

Tasks:
- Implement `backend/app/agents/orchestrator.py` with:
  - `run_extract_requirements(chunks)`
  - `run_generate_section(section_key, chunks, top_k)`
  - `run_compute_coverage(requirements, draft)`
- Instantiate fresh agent objects per request.
- Add timeout and error wrapping that preserves endpoint-level error contracts.
- Keep orchestration free of heuristic fallback logic in main path.

Acceptance criteria:
- Each orchestrator function returns schema-compatible payload on success.
- Failures are traceable to the failing stage without leaking raw prompt content.

Verification:
- Unit tests with mocked agents for success/failure propagation.

### NOVA-09: Wire FastAPI Endpoints to Orchestrator
Outcome: production endpoints use agentic path while preserving API contracts.

Tasks:
- Update `backend/app/main.py`:
  - Replace extraction call at line ~303.
  - Replace drafting calls at lines ~337-338.
  - Replace coverage calls at lines ~400-403.
- Change artifact source tags to `nova-agents-v1` at lines ~317, ~353, ~418.
- Preserve `validate_with_repair` wrappers and response envelope shape.

Acceptance criteria:
- Existing frontend flow works without request/response shape changes.
- New artifacts persist with source `nova-agents-v1`.

Verification:
- Endpoint tests for extract/generate/coverage pass.
- Manual smoke flow via frontend completes upload → extract → generate → coverage.

### NOVA-10: Add Tests for Agents and Orchestration
Outcome: migration is protected by repeatable regression coverage.

Tasks:
- Add `backend/tests/test_agents/` suite.
- Mock BedrockModel and agent calls with `unittest.mock.patch`.
- Add integration-style pipeline test using mocked model responses.
- Ensure existing `test_health.py` and baseline API tests remain green.

Acceptance criteria:
- Agent-specific tests cover success, schema failure, and empty evidence branches.
- Full test suite passes in local CI command path.

Verification:
- `cd backend && python -m pytest tests/ -v`

### NOVA-11: Add Observability, Safeguards, and Fallback Policy
Outcome: agent runtime is debuggable, safe, and stable under failure.

Tasks:
- Add per-stage orchestrator logs with request correlation ID.
- Log model IDs and token settings per request (no secrets, no raw document text).
- Add guardrails for oversized chunk payloads and top_k bounds.
- Define behavior when Bedrock call fails: explicit API error + retry guidance.

Acceptance criteria:
- Logs identify failing stage (`rfp_analyst`, `evidence_researcher`, etc.).
- Error responses are user-actionable and consistent with existing API style.

Verification:
- Tests for validation errors and Bedrock exception mapping.

### NOVA-12: Collect Submission Evidence and Run Demo Rehearsal
Outcome: judging-facing proof of Nova usage and reliability is complete.

Tasks:
- Capture architecture evidence showing Nova model IDs in code/config.
- Record demo trace showing extract/generate/coverage artifacts with `nova-agents-v1`.
- Update docs with exact reproduction commands and env requirements.
- Run two clean-start rehearsals from `docker compose up --build`.

Acceptance criteria:
- Evidence package contains code proof, runtime proof, and functional proof.
- Demo completes within 10 minutes using published instructions.

Verification:
- Validate checklist against hackathon submission requirements in `RULES.md`.

## AWS Whitepaper and Documentation Reference Summary
This reference section summarizes guidance from the local AWS documentation set in:
- `pdf/nova-dg.pdf` (Amazon Nova Developer Guide)
- `pdf/bedrock-ug.pdf` (Amazon Bedrock User Guide)
- `pdf/nova-act-ug.pdf` (Amazon Nova Act User Guide)

### Key Concepts Applicable to Nebula
- Prompt engineering should be structured and explicit: separate system/user intent, define output format, and include few-shot examples where behavior is brittle.
- Grounding is mandatory for high-trust outputs: provide retrieval context, use citation markers, and avoid unsupported claims.
- Structured outputs reduce failure rates: use schema-constrained generation for requirements, drafts, and coverage artifacts.
- Tool use must be deliberate: define strict tool schemas, clear tool instructions, and predictable tool-call order.
- Agent systems should be modular: use sub-agents for specialized tasks and an orchestrator for deterministic control flow.
- Security baseline should include IAM least privilege, credential hygiene, and policy validation before deployment.
- Runtime observability is required: log stage-level flow, monitor model calls, and keep traceability without leaking sensitive content.
- Latency and cost should be managed explicitly: choose model tier by task complexity, enforce token bounds, and use caching where it preserves quality.
- Guardrails and responsible AI controls are expected in production paths: prompt-attack filtering, sensitive content controls, and contextual grounding checks.
- Evaluation should be repeatable: validate with deterministic tests, schema checks, and regression coverage for failure branches.

### Nebula Implementation Mapping
- `NOVA-01` / `NOVA-02`: Bedrock model IDs, runtime config defaults, and environment wiring for Nova Pro/Lite.
- `NOVA-03`: Tool schema quality and deterministic formatting for chunk/evidence/artifact tools.
- `NOVA-04` to `NOVA-07`: Structured-output agents aligned to role-specialized prompts and grounding behavior.
- `NOVA-08` / `NOVA-09`: Deterministic orchestrator sequencing with explicit endpoint integration and stable API contracts.
- `NOVA-10`: Mock-based validation of success and error paths across agents and orchestration.
- `NOVA-11`: Observability, guardrails, and bounded runtime behavior.
- `NOVA-12`: Evidence package proving Nova-on-AWS usage and reproducible end-to-end demo execution.

### Canonical AWS References
- https://docs.aws.amazon.com/nova/latest/userguide/prompting.html
- https://docs.aws.amazon.com/nova/latest/userguide/tool-use.html
- https://docs.aws.amazon.com/nova/latest/nova2-userguide/web-grounding.html
- https://docs.aws.amazon.com/nova/latest/userguide/responsible-use.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolConfiguration.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/security.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-create.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrieveAndGenerate.html
- https://strandsagents.com/latest/documentation/docs/user-guide/quickstart/
- https://strandsagents.com/latest/documentation/docs/user-guide/deploy/deploy_to_bedrock_agentcore/
