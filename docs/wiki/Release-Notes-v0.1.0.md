# Release Notes - v0.1.0 (2026-02-08)

## Summary
Nebula `v0.1.0` is the first demo-ready MVP release for RFP ingestion, requirements extraction, cited drafting, coverage analysis, and artifact export.

## Included Capabilities
- Project creation and document upload metadata pipeline.
- Chunking and retrieval baseline with project-scoped evidence.
- Requirements extraction with schema validation and repair path.
- Cited section generation with missing-evidence support.
- Coverage matrix computation (`met | partial | missing`).
- JSON and Markdown export endpoint.
- Structured request logging with correlation IDs and redaction.
- Backup/restore runbook and restore drill evidence.
- Docker runtime stack and CI pipeline with docker smoke tests.
- AWS-aligned deployment workflow (ECR + ECS rollout).

## Freeze Validation
- Demo flow passed twice from clean startup.
- Evidence: `docs/wiki/Demo-Freeze-2026-02-08.md`
- Restore evidence: `docs/wiki/Restore-Drill-2026-02-07.md`

## Known Limitations (Deferred)
- Frontend citation click-through and dedicated missing-evidence panel are not yet implemented.
- Dependency upgrade backlog remains open via Dependabot PRs.
- ECS deployment currently assumes task definitions use `:latest` image tags for force redeploy.

## Upgrade / Operational Notes
- Run local production-style stack: `scripts/run_docker_env.sh restart`
- CI workflow: `.github/workflows/ci.yml`
- Deploy workflow: `.github/workflows/deploy-cloud-run.yml` (AWS ECS deployment despite filename)
