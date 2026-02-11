# Release Notes - v0.1.1 (2026-02-11)

## Summary
Nebula `v0.1.1` is a patch release focused on documentation reliability and wiki consistency.

## Included Changes
- Restored the required `README_STATUS` auto-generated block in `README.md` so `python scripts/sync_docs.py --check` succeeds.
- Updated wiki navigation and stale references after documentation cleanup.
- Removed superseded demo-freeze evidence page:
  - `docs/wiki/Demo-Freeze-2026-02-08.md`
- Kept current freeze evidence anchored to:
  - `docs/wiki/Demo-Freeze-2026-02-11.md`

## Validation
- `python scripts/sync_docs.py --check` passes.
- Changes pushed with release tag `v0.1.1`.
