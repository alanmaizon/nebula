# Nova Submission Checklist

Use this checklist before final Devpost submission to verify Nova compliance, deployability, and judge testing readiness.

## Checklist
| ID | Requirement | Verification evidence | Status (dry run) | Follow-up issue |
|---|---|---|---|---|
| NOVA-C01 | Production path calls Amazon Nova on AWS (not docs-only claims). | Architecture call path + backend invocation references + run evidence (`docs/wiki/Nova-Evidence-Run-2026-02-08.md`) with explicit user-supplied credential policy. | PASS | N/A |
| NOVA-C02 | Submission model IDs are explicit. | `BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0`, `BEDROCK_LITE_MODEL_ID=us.amazon.nova-lite-v1:0` in docs/config guidance. | PASS | N/A |
| NOVA-C03 | Deploy/run consistency is proven. | Full-workflow demo freeze run evidence in `docs/wiki/Demo-Freeze-2026-02-11.md`. | PASS | N/A |
| NOVA-C04 | Judges have working test access path. | Public test URL or repo-based test instructions with credentials path if private. | PASS | N/A |
| NOVA-C05 | Demo video is approximately 3 minutes and shows real functionality. | Published Vimeo demo link in `docs/wiki/Demo-Video-2026-02-11.md`. | PASS | N/A |
| NOVA-C06 | Video includes hashtag `#AmazonNova` and is publicly visible (YouTube/Vimeo/Youku). | Public Vimeo link captured in submission notes (`docs/wiki/Demo-Video-2026-02-11.md`); hashtag presence to be confirmed in final Devpost review pass. | PARTIAL | N/A |
| NOVA-C07 | Repository access is valid for judges. | Public repo or private share to `testing@devpost.com` and `Amazon-Nova-hackathon@amazon.com`. | PASS | N/A |
| NOVA-C08 | Submission materials are consistent with deployed behavior. | Devpost text, screenshots, and video match current runtime outputs. | PENDING | N/A |

## Dry-Run Record
| Date (PT) | Owner | Result | Notes |
|---|---|---|---|
| `2026-02-08` | `@alanmaizon` | Partial (`4 PASS / 1 PARTIAL / 3 PENDING`) | Nova path and deterministic evidence were implemented; credential execution policy documented for user-provided AWS access. |
| `2026-02-11` | `@alanmaizon` | Improved (`6 PASS / 1 PARTIAL / 1 PENDING`) | Demo video link published and credential-by-user policy documented; remaining partial/pending items are hashtag confirmation and final submission-material consistency check. |

## Required Submission Assets
- Devpost narrative aligned to `Agentic AI` primary and `Multimodal Understanding` secondary positioning.
- Public demo video (~3 minutes) with functional flow and `#AmazonNova`.
- Runnable project access for judges through a public URL, functioning demo build, or test instructions.
- Repository access confirmation (public, or private sharing to required judge addresses).
- Reliability evidence summary: `docs/wiki/CI-Reliability-2026-02-08.md`.
