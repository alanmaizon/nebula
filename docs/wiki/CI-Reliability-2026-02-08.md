# CI Reliability Summary - 2026-02-08

## Scope
Week 3 reliability hardening for submission-critical backend behavior.

Deterministic test set:
- `test_create_project_and_upload`
- `test_retrieve_is_project_scoped`
- `test_extract_requirements_and_read_latest`
- `test_generate_section_and_read_latest_draft`
- `test_compute_coverage_and_read_latest`
- `test_export_json_and_markdown`
- `test_nova_orchestrator_uses_expected_models`

Command:
- `scripts/run_deterministic_backend_tests.sh`

## Evidence
- Local repeated-run result:
  - Command: `ITERATIONS=3 scripts/run_deterministic_backend_tests.sh`
  - Result: `3/3` passes for the deterministic set.
- CI enforcement:
  - `.github/workflows/ci.yml` runs `backend-deterministic-reliability` as a 3-run matrix (`run_number: [1,2,3]`).
  - Any failing run fails the workflow.
- Latest `main` workflow snapshot (2026-02-08 UTC):
  - `CI`: success (`https://github.com/alanmaizon/nebula/actions/runs/21802179824`)
  - `CodeQL`: success (`https://github.com/alanmaizon/nebula/actions/runs/21802179819`)
  - `Deploy AWS`: success (`https://github.com/alanmaizon/nebula/actions/runs/21802179821`)
  - `Docs Sync Check`: failure on one run due out-of-sync generated docs (`https://github.com/alanmaizon/nebula/actions/runs/21802179820`)

## Flake Assessment
- No flaky tests were observed in the deterministic set during the repeated local run.
- No deterministic-test quarantine list is currently required.
- `Docs Sync Check` failure was a deterministic docs-drift failure, not test flakiness.
- If flake appears, quarantine criteria:
  - remove from deterministic gate
  - document root cause and owner
  - open linked issue with re-enable criteria

## Submission Relevance
- Supports Technical Implementation judging confidence via reproducible backend behavior.
- Complements Nova runtime proof in `docs/wiki/Nova-Evidence-Run-2026-02-08.md`.
