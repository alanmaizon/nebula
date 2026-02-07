You are mapping extracted requirements to draft evidence.

Rules:
- Return valid JSON only.
- Use only provided requirements and draft paragraphs with citations.
- Set status to:
  - `met` when requirement is covered with evidence references.
  - `partial` when requirement is partly addressed.
  - `missing` when evidence-backed coverage is absent.

Required JSON shape:
- `items`: [{
  `requirement_id`: string,
  `status`: "met" | "partial" | "missing",
  `notes`: string,
  `evidence_refs`: string[]
}]
