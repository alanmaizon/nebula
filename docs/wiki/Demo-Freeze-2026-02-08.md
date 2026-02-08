# Demo Freeze Evidence - 2026-02-08

## Objective
Validate the end-to-end MVP demo flow twice from clean startup before release tagging.

## Execution Method
- Runtime stack command: `scripts/run_docker_env.sh restart`
- Demo runner: `scripts/run_demo_freeze.sh <run-label>`
- Flow covered per run:
  - `POST /projects`
  - `POST /projects/{id}/upload`
  - `POST /projects/{id}/extract-requirements`
  - `POST /projects/{id}/generate-section`
  - `POST /projects/{id}/coverage`
  - `GET /projects/{id}/export?format=json`
  - `GET /projects/{id}/export?format=markdown`

## Run Results
- Run 1:
  - `run_label=run-1`
  - `project_id=88eaebdc-9afd-4fa3-86dd-07bcc05afb2f`
  - Statuses: upload/extract/generate/coverage/export-json/export-md = `200`
  - Artifacts: `/tmp/nebula-demo-freeze/run-1`
- Run 2:
  - `run_label=run-2`
  - `project_id=e1c491a7-cae1-4788-b70c-2487d70c3ad5`
  - Statuses: upload/extract/generate/coverage/export-json/export-md = `200`
  - Artifacts: `/tmp/nebula-demo-freeze/run-2`

## Outcome
- Demo flow passed twice from clean startup.
- No blocking defects found in freeze path.
