import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import QualitySignalsPanel from "./QualitySignalsPanel";

describe("QualitySignalsPanel", () => {
  it("renders diagnostics, ambiguity warning, and remediation guidance", () => {
    render(
      <QualitySignalsPanel
        status="success"
        signals={{
          parse: {
            source: "upload",
            documentsTotal: 2,
            qualityCounts: { good: 1, low: 1, none: 0 },
            documents: [
              {
                fileName: "rfp.pdf",
                quality: "low",
                reason: "low_text_density",
                parserId: "pdf",
              },
            ],
          },
          extraction: {
            mode: "deterministic+nova",
            chunksTotal: 20,
            chunksConsidered: 8,
            deterministicQuestionCount: 5,
            novaQuestionCount: 4,
            novaError: null,
            adaptiveContext: {
              mode: "multi_pass",
              windowCount: 2,
              rawCandidates: 6,
              dedupedCandidates: 4,
              droppedCandidates: 2,
              dedupeRatio: 0.33,
            },
            rfpSelection: {
              selectedFileName: "rfp.pdf",
              ambiguous: true,
              candidates: [
                { fileName: "rfp.pdf", documentId: "doc-1", score: 11 },
                { fileName: "rfp-copy.pdf", documentId: "doc-2", score: 11 },
              ],
            },
          },
          unresolvedGaps: [],
          recommendations: [
            "Replace low-quality scans with text-searchable PDFs.",
            "Resolve RFP source ambiguity by keeping one canonical RFP file.",
            "Re-run Generate after updates and confirm unresolved gaps are zero.",
          ],
        }}
      />
    );

    expect(screen.getByText("Quality Signals")).toBeInTheDocument();
    expect(screen.getByText(/RFP source ambiguity warning/i)).toBeInTheDocument();
    expect(screen.getByText("rfp-copy.pdf")).toBeInTheDocument();
    expect(screen.getByText(/text-searchable PDFs/)).toBeInTheDocument();
  });

  it("renders loading state", () => {
    render(<QualitySignalsPanel status="loading" signals={null} />);
    expect(screen.getByText("Analyzing parse and extraction quality...")).toBeInTheDocument();
  });
});
