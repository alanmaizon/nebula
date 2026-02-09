# Happy Path Ingest Fixture Set

Use these files for a manual end-to-end run of the workspace upload -> extract -> retrieve -> draft -> coverage -> export path.

Suggested upload set:
- `rfp_community_resilience_2026.txt`
- `org_impact_report_2025.txt`
- `project_budget_attachment_a.txt`
- `program_timeline_attachment_b.txt`
- `community_support_letters_excerpt.txt`

Notes:
- Files are plain text on purpose; the current ingest indexer is text-first.
- The RFP uses numbered questions and explicit sections so deterministic extraction stays stable.
