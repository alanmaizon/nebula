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

## Quick Start
1. Make sure environmental variables are imported

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
