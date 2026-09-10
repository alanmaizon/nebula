# Operations Runbook

## Daily
- Review open blockers and failed workflows.
- Confirm project board reflects current work.

## Weekly
- Run full demo flow from clean startup.
- Update `docs/status.yml`.
- Run `python scripts/sync_docs.py`.
- Triage dependency and CodeQL findings.
- Run AWS deployment readiness check before planned production releases:
  - `bash scripts/aws/check_deploy_readiness.sh ...`
- Verify parser dependencies remain pinned and installed in runtime image:
  - `pypdf`
  - `python-docx`
  - `striprtf`

## Incident Template
- `Time detected`:
- `Impact`:
- `Systems affected`:
- `Immediate mitigation`:
- `Root cause`:
- `Permanent fix`:
- `Follow-up actions`:

## Backup and Restore (MVP)
### Scope
- Metadata database: `backend/nebula.db` (or the SQLite path derived from `DATABASE_URL`).
- Uploaded source documents: `backend/data/uploads/` (or the configured `STORAGE_ROOT`).
- Artifact payloads are stored in the same SQLite database.

### Backup Procedure
1. Pause writes to avoid inconsistent snapshots (`docker compose stop backend` or stop local backend process).
2. Create a SQLite backup file:
   `sqlite3 backend/nebula.db ".backup '/tmp/nebula.db.bak'"`
3. Archive uploads:
   `tar -czf /tmp/nebula-uploads-$(date +%F).tgz -C backend data/uploads`
4. Record checksums:
   `shasum -a 256 /tmp/nebula.db.bak /tmp/nebula-uploads-$(date +%F).tgz`
5. Copy backup artifacts to approved storage and retain checksum output with timestamp.

### Restore Procedure
1. Stop backend services before restore.
2. Restore database file to configured path:
   `cp /tmp/nebula.db.bak backend/nebula.db`
3. Restore uploads archive:
   `tar -xzf /tmp/nebula-uploads-YYYY-MM-DD.tgz -C backend`
4. Start backend and validate:
   - `GET /health` returns `200`.
   - `GET /ready` returns `200`.
5. Run smoke path:
   - Create project.
   - Upload one text file.
   - Execute retrieval (`POST /projects/{id}/retrieve`).
6. Record restore verification in operations notes with date, operator, and outcome.

### Restore Test Cadence
- Run one restore drill per milestone.
- Treat failed restore drill as a release blocker.

### Restore Drill Evidence
- `docs/wiki/Restore-Drill-2026-02-07.md`

## AWS Backup Automation
### Workflow
- GitHub Actions workflow: `.github/workflows/backup-aws.yml`
- Runtime script: `scripts/aws/run_backup.sh`

### What It Does
1. Reads the deployed backend task definition from ECS.
2. Resolves the active storage settings and database target.
3. Ensures RDS automated backups are retained for at least `7` days by default.
4. Creates a manual RDS snapshot for the current run.
5. Enables S3 versioning for the uploads bucket when `STORAGE_BACKEND=s3`.
6. Copies the uploads prefix to a dated backup prefix (default: `nebula-backups/uploads/<timestamp>`).
7. If the DB was stopped before the run, starts it for backup and stops it again afterward by default.

### Required GitHub Secrets
- Reuses deploy secrets:
  - `AWS_REGION`
  - `AWS_ROLE_TO_ASSUME`
  - `ECS_CLUSTER`
  - `ECS_BACKEND_SERVICE`
- Optional overrides:
  - `ECS_BACKEND_CONTAINER_NAME`
  - `DB_INSTANCE_ID`
  - `BACKUP_S3_BUCKET`
  - `BACKUP_S3_PREFIX`
  - `RDS_BACKUP_RETENTION_DAYS`

### Restore Notes
- Restore the RDS database from the selected manual snapshot.
- Restore uploads from the dated S3 backup prefix or earlier object versions if versioning is enabled.
- If `DATABASE_URL` is injected through Secrets Manager or SSM Parameter Store, the GitHub OIDC role also needs read access to that source.
