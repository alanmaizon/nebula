# Nova Evidence Run - 2026-02-08

## Objective
Record reproducible evidence that Nebula's core extraction, drafting, and coverage paths execute through the Nova orchestrator path with explicit model IDs and `nova-agents-v1` artifact sources.

## Evidence Commands
- Runtime and endpoint tests:
  - `cd backend && PYTHONPATH=. .venv/bin/pytest -q`

## Results
- Test status: `14 passed`
- Verified invocation path:
  - `backend/app/main.py` endpoints call `get_nova_orchestrator()`
  - `backend/app/nova_runtime.py` calls Bedrock `converse` with:
    - `BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0` for extraction and drafting
    - `BEDROCK_LITE_MODEL_ID=us.amazon.nova-lite-v1:0` for coverage
- Verified artifact provenance in API tests:
  - requirements latest source = `nova-agents-v1`
  - draft latest source = `nova-agents-v1`
  - coverage latest source = `nova-agents-v1`

## Notes
- CI/unit evidence uses mocked Bedrock client behavior for deterministic testing.
- Production runtime still requires valid AWS credentials and Bedrock model access in the target region.
