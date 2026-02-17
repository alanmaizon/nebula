import { describe, expect, it } from "vitest";

import {
  buildQualitySignals,
  createUnavailableParseDiagnostics,
  parseUploadDiagnostics,
} from "./qualitySignals";

describe("qualitySignals", () => {
  it("parses upload diagnostics payload into typed parse signals", () => {
    const diagnostics = parseUploadDiagnostics(
      {
        parse_report: {
          documents_total: 2,
          quality_counts: { good: 1, low: 0, none: 1 },
        },
        documents: [
          {
            file_name: "rfp.pdf",
            parse_report: { quality: "good", reason: "ok", parser_id: "pdf" },
          },
          {
            file_name: "appendix.bin",
            parse_report: { quality: "none", reason: "unsupported_file_type", parser_id: "none" },
          },
        ],
      },
      2
    );

    expect(diagnostics.source).toBe("upload");
    expect(diagnostics.documentsTotal).toBe(2);
    expect(diagnostics.qualityCounts).toEqual({ good: 1, low: 0, none: 1 });
    expect(diagnostics.documents[0]?.fileName).toBe("rfp.pdf");
    expect(diagnostics.documents[1]?.quality).toBe("none");
  });

  it("builds quality signals with ambiguity guidance and minimum remediation actions", () => {
    const signals = buildQualitySignals({
      parseDiagnostics: createUnavailableParseDiagnostics(3),
      extractionPayload: {
        mode: "deterministic+nova",
        deterministic_question_count: 3,
        nova_question_count: 2,
        adaptive_context: {
          mode: "multi_pass",
          window_count: 3,
          raw_candidates: 6,
          deduped_candidates: 3,
          dropped_candidates: 3,
          dedupe_ratio: 0.5,
        },
        rfp_selection: {
          selected_file_name: "rfp_a.pdf",
          ambiguous: true,
          candidates: [
            { file_name: "rfp_a.pdf", score: 11 },
            { file_name: "rfp_b.pdf", score: 11 },
          ],
        },
      },
      unresolvedGapsPayload: [
        {
          requirement_id: "Q1",
          internal_id: "Q1",
          original_id: "REQ-1",
          status: "missing",
          notes: "No evidence found.",
          evidence_refs: [],
        },
      ],
    });

    expect(signals.extraction.rfpSelection.ambiguous).toBe(true);
    expect(signals.unresolvedGaps).toHaveLength(1);
    expect(signals.recommendations.length).toBeGreaterThanOrEqual(3);
    expect(signals.recommendations.join(" ")).toMatch(/ambiguity|canonical|Resolve/i);
  });
});
