# Quality Signals Guide

The workspace now includes dedicated quality diagnostics to help teams fix weak inputs before export.

## Panels
- `Quality Signals`
  - parse quality counts (`good`, `low`, `none`)
  - extraction mode (`deterministic+nova` or `deterministic-only`)
  - adaptive context diagnostics (window count, candidate dedupe ratio)
  - RFP source ambiguity warning when multiple RFP-like files tie
  - recommended remediation actions
- `Unresolved Coverage Gaps`
  - requirement-level `partial` / `missing` coverage rows
  - requirement IDs (`requirement_id`, `original_id` when available)
  - notes and evidence refs for reviewer follow-up
- `Missing Evidence`
  - grouped upload guidance by section

## Example Interpretation
If you see:
- parse `low/none` counts above zero
- `deterministic-only` extraction mode
- `RFP source ambiguity warning`
- unresolved `missing` coverage items

Use this order of fixes:
1. Replace scanned/non-text files with text-searchable PDF/DOCX/RTF files.
2. Keep one canonical RFP file and remove duplicate solicitation versions.
3. Upload rubric and attachment requirement documents in the same batch.
4. Re-run generation and confirm unresolved coverage gaps trend toward zero.

## Release Note
This guide documents issue `#42` UX enhancements for parse/extraction confidence and remediation guidance.
