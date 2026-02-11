# Changelog

All notable changes to this project are documented in this file.

## [Unreleased] - 2026-02-11

### Changed
- Refactored `backend/app/main.py` to reduce duplicated endpoint logic and centralize project/upload-batch resolution helpers.
- Consolidated export assembly flow internals in `backend/app/main.py` with smaller helper functions and clearer typing (`TypedDict` export context).
- Hardened backend/frontend security posture and removed generated local artifacts from tracked changes (`0cb1e65`).

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

[Unreleased]: https://github.com/alanmaizon/nebula/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/alanmaizon/nebula/tree/v0.1.0
