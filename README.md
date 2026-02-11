# Nebula

Nebula is an Amazon Nova-powered grant drafting workspace.  
It turns source documents into cited draft sections, requirement coverage, and exportable submission artifacts.

## What It Does
- Extracts requirements from RFP-like documents
- Generates citation-backed draft sections
- Computes coverage (`met` / `partial` / `missing`)
- Flags missing evidence
- Exports JSON + Markdown bundles

## Stack
- Frontend: Next.js
- Backend: FastAPI
- Storage: SQLite + local filesystem
- Models: Amazon Nova via Bedrock

## Execution Status
<!-- AUTO-GEN:README_STATUS:START -->
- Last updated: `2026-02-11`
- Overall completion: `95%`
- Current milestone: `Week 4 - Submission Asset Packaging (In progress)`

### Done This Week
- Prepared Devpost narrative draft emphasizing Nova and AWS architecture choices
- Hardened backend/frontend security posture and local artifact hygiene
- Refactored export and endpoint assembly flow in backend main API module
- Updated README and CONTRIBUTING guidance for current developer workflow
- Published public Vimeo demo video for submission evidence
- Cut v1.0.0 final release tag with synchronized wiki release notes

### Next Up
- Prepare public demo/test access instructions and fallback credentials path

### Current Blockers
- No blockers recorded.
<!-- AUTO-GEN:README_STATUS:END -->

## Quick Start
1. Copy env files:
```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```
2. Run with Docker:
```bash
docker compose up --build
```
3. Open:
- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Backend docs: `http://localhost:8000/docs`

## Core API
- `POST /projects`
- `POST /projects/{id}/upload`
- `POST /projects/{id}/extract-requirements`
- `POST /projects/{id}/generate-section`
- `POST /projects/{id}/generate-full-draft`
- `POST /projects/{id}/coverage`
- `GET /projects/{id}/export`

## Notes
- Current parser extracts text from text-like files (`.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.yml`, `.xml`, `.html`).
- If embedding settings change after indexing, API responses may include `warnings` with `code: embedding_dim_drift`; re-index documents to resolve.
