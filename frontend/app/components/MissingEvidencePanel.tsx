"use client";

import type { MissingEvidenceGroup } from "../lib/traceability";

type MissingEvidencePanelProps = {
  groups: MissingEvidenceGroup[];
  status: "idle" | "loading" | "success" | "error";
  errorMessage?: string | null;
};

export default function MissingEvidencePanel({
  groups,
  status,
  errorMessage,
}: MissingEvidencePanelProps) {
  return (
    <section className="missing-evidence-shell" aria-label="Missing evidence panel">
      <h4>Missing Evidence</h4>

      {status === "loading" ? (
        <p className="traceability-empty">Analyzing missing evidence...</p>
      ) : null}

      {status === "error" ? (
        <p className="error-text">{errorMessage ?? "Unable to compute missing evidence."}</p>
      ) : null}

      {status === "success" && groups.length === 0 ? (
        <p className="traceability-empty">No missing evidence flagged in this run.</p>
      ) : null}

      {status === "success" && groups.length > 0 ? (
        <div className="missing-evidence-groups">
          {groups.map((group) => (
            <details key={group.sectionKey} className="missing-evidence-group" open>
              <summary>
                <span>{group.sectionKey}</span>
                <small>{group.items.length} item(s)</small>
              </summary>

              <div className="missing-evidence-items">
                {group.items.map((item, index) => (
                  <article
                    key={`${group.sectionKey}-${index}`}
                    className="missing-evidence-item"
                  >
                    <p className="missing-evidence-claim">{item.claim}</p>
                    <p className="missing-evidence-guidance">Upload guidance: {item.suggestedUpload}</p>
                  </article>
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : null}
    </section>
  );
}
