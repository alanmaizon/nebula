# Contributing

This project is optimized for fast, reviewable changes. Use this guide to keep pull requests predictable and safe.

## Development setup

1. Copy env files:
```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```
2. Start local stack (recommended):
```bash
docker compose up --build
```
3. Or run services separately:
```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

## Pull request expectations

- Keep PRs focused and small enough to review quickly.
- Fill out `.github/PULL_REQUEST_TEMPLATE.md`.
- If behavior changes, include API/UI verification steps.
- If setup or contracts change, update docs in the same PR.

## Required local checks before opening a PR

```bash
cd backend && PYTHONPATH=. pytest
scripts/run_deterministic_backend_tests.sh
cd frontend && npm run typecheck && npm run build
python scripts/sync_docs.py --check
```

CI runs the same core gates:
- backend tests
- deterministic backend reliability checks
- frontend typecheck/build
- docker smoke validation

## Documentation sync contract

`docs/status.yml` is the source of truth for delivery status.

When status changes:
1. Update `docs/status.yml`.
2. Run `python scripts/sync_docs.py`.
3. Commit generated updates in:
   - `README.md`
   - `docs/wiki/DEVELOPMENT_PLAN.md`
   - `docs/wiki/AWS_ALIGNMENT.md`

Do not hand-edit generated `AUTO-GEN` blocks unless you also update `docs/status.yml`.

## Backend/API contracts

- Keep model outputs structured and schema-validated.
- Do not relax citation grounding requirements.
- Preserve contract semantics for:
  - requirements extraction
  - draft generation (`citations[]`, `missing_evidence[]`)
  - coverage status (`met | partial | missing`)
  - export bundle shape

If you intentionally change a contract, update:
- `README.md` key endpoints/behavior
- related schema/docs in `docs/`
- tests covering the changed behavior

## Security and secrets

- Never commit credentials, tokens, or `.env` files.
- Do not log raw sensitive document text in production paths.
- Keep log redaction behavior intact when modifying observability code.
- Review dependency additions for necessity and security impact.

## Generated and local-only files

Do not commit local runtime artifacts. Common examples:
- `nebula.db`
- `frontend/tsconfig.tsbuildinfo`
- local exports in `output/`

If a local artifact is accidentally tracked, remove it from git history/index in the PR and keep ignore rules updated.
