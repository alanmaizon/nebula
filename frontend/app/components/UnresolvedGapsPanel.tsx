"use client";

import type { UnresolvedGapSignal } from "../lib/qualitySignals";

type UnresolvedGapsPanelProps = {
  gaps: UnresolvedGapSignal[];
  status: "idle" | "loading" | "success" | "error";
};

function statusLabel(status: UnresolvedGapSignal["status"]): string {
  if (status === "missing") {
    return "missing";
  }
  if (status === "partial") {
    return "partial";
  }
  if (status === "met") {
    return "met";
  }
  return "unknown";
}

export default function UnresolvedGapsPanel({ gaps, status }: UnresolvedGapsPanelProps) {
  if (status === "loading") {
    return (
      <section className="unresolved-gaps-shell" aria-label="Unresolved gaps panel">
        <h4>Unresolved Coverage Gaps</h4>
        <p className="traceability-empty">Waiting for coverage diagnostics...</p>
      </section>
    );
  }

  if (status !== "success") {
    return (
      <section className="unresolved-gaps-shell" aria-label="Unresolved gaps panel">
        <h4>Unresolved Coverage Gaps</h4>
        <p className="traceability-empty">Run generation to inspect unresolved requirements.</p>
      </section>
    );
  }

  const unresolved = gaps.filter((gap) => gap.status === "partial" || gap.status === "missing");

  if (unresolved.length === 0) {
    return (
      <section className="unresolved-gaps-shell" aria-label="Unresolved gaps panel">
        <h4>Unresolved Coverage Gaps</h4>
        <p className="traceability-empty">No unresolved partial/missing coverage gaps in this run.</p>
      </section>
    );
  }

  return (
    <section className="unresolved-gaps-shell" aria-label="Unresolved gaps panel">
      <h4>Unresolved Coverage Gaps</h4>
      <p className="quality-section-copy">
        Review these requirement-level gaps before final export.
      </p>
      <div className="unresolved-gap-list">
        {unresolved.map((gap, index) => (
          <article key={`${gap.requirementId}-${index}`} className="unresolved-gap-item">
            <p className="unresolved-gap-title">
              <span className={`coverage-status-pill status-${statusLabel(gap.status)}`}>
                {statusLabel(gap.status)}
              </span>
              <strong>{gap.requirementId}</strong>
              {gap.originalId ? <code>original: {gap.originalId}</code> : null}
            </p>
            <p className="coverage-detail-notes">{gap.notes}</p>
            {gap.evidenceRefs.length > 0 ? (
              <p className="coverage-detail-notes">
                Evidence refs: {gap.evidenceRefs.join(", ")}
              </p>
            ) : (
              <p className="coverage-detail-notes">No evidence refs yet.</p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
