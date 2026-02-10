# Full Coverage Fixture Set

Use these files for a manual end-to-end run where requirements extraction, drafting, and coverage should all have strong evidence across every required narrative section.

Suggested upload set:
- `rfp_county_family_stability_2027.txt`
- `org_impact_report_2026.txt`
- `project_budget_attachment_a.txt`
- `program_timeline_attachment_b.txt`
- `community_support_letters_excerpt.txt`
- `evaluation_framework_appendix_c.txt`

Recommended intake values (UI):
- Project Name: `County Family Stability 2027 Full Coverage Demo`
- Country: `United States`
- Organization Type: `Non-profit (501(c)(3))`
- Funder Track: `county-family-stability`
- Funding Goal: `eviction-prevention-and-family-support`
- Sector Focus: `housing stability, case management, and outcomes measurement`

Manual flow:
1. Create a project and submit intake.
2. Upload the full file set above.
3. Run requirement extraction.
4. Generate three sections: `Need Statement`, `Program Design`, and `Outcomes and Evaluation`.
5. Run coverage and export.

Expected signals:
- Requirements extraction includes 3 questions, 4 rubric lines, and 3 disallowed cost lines.
- Generated drafts for Q1/Q2/Q3 include citations from multiple files.
- Coverage should not mark Q1/Q2/Q3 as missing when those sections were generated.

Notes:
- Files are plain text to keep ingest deterministic.
- This set is intentionally dense with numeric indicators for easier citation grounding.
