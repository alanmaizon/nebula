# Demo Freeze Evidence - 2026-02-11

## Objective
Re-run demo-freeze evidence against the **current full implementation workflow** (full-draft orchestration), replacing the earlier freeze path that used legacy step-by-step endpoints.

## Execution Method
- Runtime stack command: `scripts/run_docker_env.sh restart`
- Demo runner: `scripts/run_demo_freeze.sh judge-run`
- Flow covered in run:
  - `POST /projects`
  - `POST /projects/{id}/upload`
  - `POST /projects/{id}/generate-full-draft?profile=submission`
  - `GET /projects/{id}/export?format=json&profile=submission`
  - `GET /projects/{id}/export?format=markdown&profile=submission`

## Run Results
- Run label: `judge-run`
- Project ID: `0f76846e-07f2-48b7-bd88-03ba80274be8`
- Statuses:
  - `upload_status=200`
  - `full_draft_status=200`
  - `export_json_status=200`
  - `export_md_status=200`
- Artifacts: `/tmp/nebula-demo-freeze/judge-run`
- Export generated_at: `2026-02-11T14:46:35.914855+00:00`

## Evidence Notes
- `full_draft.json` shows complete run summary:
  - `sections_total=4`
  - `sections_completed=4`
  - `status=complete`
- `export.json` is current bundle schema (`nebula.export.v1`) and includes:
  - `bundle.json.requirements`
  - `bundle.json.drafts`
  - `bundle.json.coverage`
  - `bundle.markdown.files`

## Outcome
- Current full workflow is passing in local demo-freeze execution.
- This run supersedes older freeze evidence that was captured before full-draft workflow adoption.
