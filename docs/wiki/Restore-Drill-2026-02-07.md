# Restore Drill Evidence - 2026-02-07

## Objective
Validate the backup and restore runbook for metadata (`nebula.db`) and uploaded files.

## Environment
- Runtime stack: `scripts/run_docker_env.sh restart`
- Backend container: `nebula-backend`
- Frontend container: `nebula-frontend`

## Drill Steps
1. Confirmed backend and frontend health endpoints were reachable.
2. Created a project and uploaded `sample.txt`.
3. Verified retrieval worked before failure simulation.
4. Backed up:
   - `/app/nebula.db` -> `/tmp/nebula-restore-drill/nebula.db.bak`
   - `/app/data/uploads` -> `/tmp/nebula-restore-drill/uploads.bak`
5. Generated checksums:
   - `1fe238cfaf58cb57b2325fa3a1a1a30cac0d05e6aec2dcdcd070398e590ce103  /tmp/nebula-restore-drill/nebula.db.bak`
   - `adba693d5d32405af2656b08fdc1b4e748dcb5cb931da9473d04f784090f5e7b  /tmp/nebula-restore-drill/uploads.bak.tgz`
6. Simulated loss by deleting `/app/nebula.db` and `/app/data/uploads`.
7. Confirmed retrieval failure during loss window (`HTTP 500`).
8. Restored both backups into the container.
9. Re-ran health and retrieval checks; retrieval returned `HTTP 200` with the same result payload.

## Validation Results
- Before simulated loss: `retrieve` = `200`
- During simulated loss: `retrieve` = `500`
- After restore: `retrieve` = `200`
- Restored retrieval payload matched the pre-loss payload for the drill query (`restore drill`).

## Artifacts
- `/tmp/nebula-restore-drill/precheck.txt`
- `/tmp/nebula-restore-drill/postcheck.txt`
- `/tmp/nebula-restore-drill/checksums.txt`
- `/tmp/nebula-restore-drill/retrieve_before.json`
- `/tmp/nebula-restore-drill/retrieve_during_loss.json`
- `/tmp/nebula-restore-drill/retrieve_after_restore.json`
