# Nova Evidence Run - 2026-02-08

## Objective
Record reproducible evidence that Nebula's core extraction, drafting, and coverage paths execute through the Nova orchestrator path with explicit model IDs and `nova-agents-v1` artifact sources.

## Evidence Commands
- Runtime and endpoint tests:
  - `cd backend && PYTHONPATH=. .venv/bin/pytest -q`
  - `cd backend && PYTHONPATH=. .venv/bin/pytest -q tests/test_nova_e2e.py::test_nova_end_to_end_api_run`

## Results
- Test status: `16 passed` (full backend suite after Nova-path changes)
- End-to-end Nova-path test status: `1 passed`
- Verified invocation path:
  - `backend/app/main.py` endpoints call `get_nova_orchestrator()`
  - `backend/app/nova_runtime.py` calls Bedrock `converse` with:
    - `BEDROCK_MODEL_ID=amazon.nova-pro-v1:0` for extraction and drafting (or inference profile, e.g. `eu.amazon.nova-pro-v1:0`)
    - `BEDROCK_LITE_MODEL_ID=amazon.nova-lite-v1:0` for coverage (or inference profile, e.g. `eu.amazon.nova-lite-v1:0`)
- Verified artifact provenance in API tests:
  - requirements latest source = `nova-agents-v1`
  - draft latest source = `nova-agents-v1`
  - coverage latest source = `nova-agents-v1`
- End-to-end evidence details:
  - API flow covered in one run: create project -> upload -> extract -> generate -> coverage
  - Nova invocation path is exercised through `BedrockNovaOrchestrator` with a mocked Bedrock `converse` client to provide deterministic reproducibility.

## Notes
- CI/unit evidence uses mocked Bedrock client behavior for deterministic testing.
- Production runtime requires valid AWS credentials and Bedrock model access in the target region.
- Credential policy: Nebula does not provide shared AWS credentials or embedded keys. Each operator/judge must run with their own AWS account credentials and Bedrock access.
