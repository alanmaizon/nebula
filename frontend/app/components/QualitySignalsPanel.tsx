"use client";

import type { QualitySignals } from "../lib/qualitySignals";

type QualitySignalsPanelProps = {
  signals: QualitySignals | null;
  status: "idle" | "loading" | "success" | "error";
};

export default function QualitySignalsPanel({ signals, status }: QualitySignalsPanelProps) {
  if (status === "loading") {
    return (
      <section className="quality-signals-shell" aria-label="Quality signals panel">
        <h4>Quality Signals</h4>
        <p className="traceability-empty">Analyzing parse and extraction quality...</p>
      </section>
    );
  }

  if (status !== "success" || !signals) {
    return (
      <section className="quality-signals-shell" aria-label="Quality signals panel">
        <h4>Quality Signals</h4>
        <p className="traceability-empty">Run generation to view parse/extraction diagnostics and guidance.</p>
      </section>
    );
  }

  const parseLowOrNone = signals.parse.qualityCounts.low + signals.parse.qualityCounts.none;
  const unresolvedTotal = signals.unresolvedGaps.length;
  const selectedRfp = signals.extraction.rfpSelection.selectedFileName ?? "unknown";

  return (
    <section className="quality-signals-shell" aria-label="Quality signals panel">
      <h4>Quality Signals</h4>

      <div className="quality-summary-grid">
        <article className="quality-summary-card">
          <span>Parse quality</span>
          <strong>{signals.parse.documentsTotal} docs</strong>
          <small>{parseLowOrNone} low/none quality</small>
        </article>
        <article className="quality-summary-card">
          <span>Extraction mode</span>
          <strong>{signals.extraction.mode}</strong>
          <small>{signals.extraction.adaptiveContext.windowCount} window(s)</small>
        </article>
        <article className="quality-summary-card">
          <span>Unresolved gaps</span>
          <strong>{unresolvedTotal}</strong>
          <small>{signals.extraction.adaptiveContext.dedupedCandidates} deduped candidates</small>
        </article>
      </div>

      <div className="quality-section-grid">
        <article className="quality-section-card">
          <h5>Parse Quality</h5>
          <p className="quality-section-copy">
            Source: <strong>{signals.parse.source === "upload" ? "latest upload batch" : "not available"}</strong>
          </p>
          <div className="quality-count-row">
            <span>good: {signals.parse.qualityCounts.good}</span>
            <span>low: {signals.parse.qualityCounts.low}</span>
            <span>none: {signals.parse.qualityCounts.none}</span>
          </div>
          {signals.parse.documents.length > 0 ? (
            <ul className="quality-document-list">
              {signals.parse.documents.map((document) => (
                <li key={`${document.fileName}-${document.parserId ?? "unknown"}`}>
                  <strong>{document.fileName}</strong> ({document.quality})
                  {document.parserId ? ` via ${document.parserId}` : ""}
                  {document.reason ? ` - ${document.reason}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </article>

        <article className="quality-section-card">
          <h5>Extraction Diagnostics</h5>
          <div className="quality-kv-grid">
            <p>
              Deterministic questions: <strong>{signals.extraction.deterministicQuestionCount}</strong>
            </p>
            <p>
              Nova questions: <strong>{signals.extraction.novaQuestionCount}</strong>
            </p>
            <p>
              Raw candidates: <strong>{signals.extraction.adaptiveContext.rawCandidates}</strong>
            </p>
            <p>
              Deduped candidates: <strong>{signals.extraction.adaptiveContext.dedupedCandidates}</strong>
            </p>
            <p>
              Dedupe ratio: <strong>{signals.extraction.adaptiveContext.dedupeRatio}</strong>
            </p>
            <p>
              Selected RFP: <strong>{selectedRfp}</strong>
            </p>
          </div>
          {signals.extraction.novaError ? (
            <p className="error-text">{signals.extraction.novaError}</p>
          ) : null}
          {signals.extraction.rfpSelection.ambiguous ? (
            <div className="quality-ambiguity-alert">
              <p>
                <strong>RFP source ambiguity warning:</strong> multiple documents scored equally.
              </p>
              {signals.extraction.rfpSelection.candidates.length > 0 ? (
                <ul>
                  {signals.extraction.rfpSelection.candidates.map((candidate) => (
                    <li key={`${candidate.documentId ?? "unknown"}-${candidate.fileName}`}>
                      {candidate.fileName}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </article>
      </div>

      <article className="quality-section-card">
        <h5>Recommended Next Actions</h5>
        <ol className="quality-recommendations">
          {signals.recommendations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      </article>
    </section>
  );
}
