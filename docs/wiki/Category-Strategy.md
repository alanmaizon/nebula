# Submission Category Strategy

## Locked Decision
- Decision date: `2026-02-08`
- Owner: `@alanmaizon`
- Primary category: `Agentic AI`
- Secondary category: `Multimodal Understanding`

## Why This Positioning
| Capability | Agentic AI fit (primary) | Multimodal fit (secondary) |
|---|---|---|
| Multi-stage workflow (`extract -> draft -> coverage`) | Staged orchestration and role separation are the core runtime value path. | Uses document understanding outputs to support each stage. |
| Evidence researcher behavior | Retrieval + ranking acts as an autonomous evidence specialist in the planned Nova path. | Parses and reasons over RFP + supporting documents. |
| Grant writer + compliance reviewer behavior | Dedicated writer/reviewer responsibilities map directly to agentic specialization. | Validates document-grounded outputs and requirement coverage. |
| Deterministic orchestration guardrails | Controlled sequencing and schema checks demonstrate production-grade agent design. | Preserves trust in text/document interpretation outputs. |

## Devpost Draft Narrative Bullets
- Nebula is an `Agentic AI` system for grant development: specialized agents handle requirements analysis, evidence research, drafting, and compliance review.
- The core architecture keeps a deterministic orchestrator so automation remains auditable and reliable under deadline conditions.
- Every generated claim remains citation-backed (`doc_id`, `page`, `snippet`) to prevent unsupported output drift.
- `Multimodal Understanding` is the secondary value driver: Nebula interprets complex RFP and supporting document sets to produce structured artifacts.
- The outcome is faster submission readiness with explicit coverage status (`met`, `partial`, `missing`) and concrete evidence gaps.

## Demo Script Outline (Category-Aware)
| Segment | Time | Category emphasis | What to show |
|---|---|---|---|
| Problem and trust requirement | `0:00-0:20` | Agentic AI | Why nonprofit teams need auditable automation, not generic text generation. |
| Upload and ingestion | `0:20-0:45` | Multimodal | RFP + supporting docs uploaded and parsed into retrievable evidence. |
| Requirements extraction | `0:45-1:20` | Agentic AI | Analyst stage producing structured requirement artifacts. |
| Section generation with citations | `1:20-2:05` | Multimodal | Draft paragraphs tied to source pages/snippets. |
| Coverage and missing evidence | `2:05-2:35` | Agentic AI | Reviewer stage showing `met/partial/missing` with actionability. |
| Export and close | `2:35-3:00` | Both | End-to-end output package and judge testing path. |

## Language Guardrails
- Always state category order as: `Agentic AI (primary), Multimodal Understanding (secondary)`.
- Avoid ambiguous wording such as "Multimodal / Agentic" without priority.
