# Operations Runbook

## Daily
- Review open blockers and failed workflows.
- Confirm project board reflects current work.

## Weekly
- Run full demo flow from clean startup.
- Update `docs/status.yml`.
- Run `python scripts/sync_docs.py`.
- Triage dependency and CodeQL findings.

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
