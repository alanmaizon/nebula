# Changelog

All notable changes to this project are documented in this file.

## [Unreleased] - 2026-02-11

### Changed
- No unreleased changes yet.

## [1.0.0] - 2026-02-11

### Added
- Final release documentation set for roadmap close-out and release traceability.
- Wiki release notes for `v1.0.0` at `docs/wiki/Release-Notes-v1.0.0.md`.
- Public demo video evidence page at `docs/wiki/Demo-Video-2026-02-11.md`.

### Changed
- Roadmap updated with final release milestone and explicit remaining submission operations.
- Wiki home/release navigation updated for the final release series.
- Submission checklist and submission narrative updated with the published Vimeo demo link.

## [0.1.1] - 2026-02-11

### Changed
- Refactored `backend/app/main.py` to reduce duplicated endpoint logic and centralize project/upload-batch resolution helpers.
- Consolidated export assembly flow internals in `backend/app/main.py` with smaller helper functions and clearer typing (`TypedDict` export context).
- Hardened backend/frontend security posture and removed generated local artifacts from tracked changes (`0cb1e65`).
- Updated roadmap/wiki documentation to current date-based delivery tracking and removed stale references.

### Fixed
- Restored the required `README_STATUS` auto-generated block so `python scripts/sync_docs.py --check` passes in CI.

### Removed
- Deleted superseded demo-freeze evidence doc (`docs/wiki/Demo-Freeze-2026-02-08.md`) in favor of `docs/wiki/Demo-Freeze-2026-02-11.md`.

## [0.1.0] - 2026-02-08

### Added
- Demo-ready MVP for RFP ingestion, requirements extraction, cited drafting, coverage analysis, and artifact export.
- Project creation, document upload metadata pipeline, and retrieval baseline.
- Requirements extraction with validation/repair and Nova-assisted merge path.
- Cited section generation with missing-evidence signaling.
- Coverage matrix with `met | partial | missing` statuses.
- Export endpoints for JSON and Markdown outputs.
- Structured request logging with correlation IDs and redaction.
- Docker runtime stack and CI docker smoke test pipeline.

### Notes
- Detailed release notes: `docs/wiki/Release-Notes-v0.1.0.md`

[Unreleased]: https://github.com/alanmaizon/nebula/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/alanmaizon/nebula/compare/v0.1.1...v1.0.0
[0.1.1]: https://github.com/alanmaizon/nebula/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alanmaizon/nebula/tree/v0.1.0
