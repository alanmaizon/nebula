"use client";

import { useMemo, useState } from "react";

import type { TraceCitation, TraceSection } from "../lib/traceability";

type TraceabilityPanelProps = {
  sections: TraceSection[];
};

export default function TraceabilityPanel({ sections }: TraceabilityPanelProps) {
  const allCitations = useMemo(
    () =>
      sections.flatMap((section) =>
        section.paragraphs.flatMap((paragraph) => paragraph.citations)
      ),
    [sections]
  );

  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(
    null
  );

  const selectedCitation =
    allCitations.find((citation) => citation.id === selectedCitationId) ??
    allCitations[0] ??
    null;

  if (sections.length === 0) {
    return (
      <section className="traceability-shell" aria-label="Citation traceability panel">
        <h4>Citation Traceability</h4>
        <p className="traceability-empty">No draft sections with citations available yet.</p>
      </section>
    );
  }

  return (
    <section className="traceability-shell" aria-label="Citation traceability panel">
      <h4>Citation Traceability</h4>
      <div className="traceability-grid">
        <div className="traceability-list" role="list">
          {sections.map((section) => (
            <details key={section.sectionKey} className="traceability-section" open>
              <summary>
                <span>{section.sectionKey}</span>
                <small>
                  {section.paragraphs.reduce((acc, paragraph) => acc + paragraph.citations.length, 0)} citation(s)
                </small>
              </summary>

              <div className="traceability-section-body">
                {section.paragraphs.map((paragraph, paragraphIndex) => (
                  <article
                    key={`${section.sectionKey}-paragraph-${paragraphIndex + 1}`}
                    className="trace-paragraph"
                    role="listitem"
                  >
                    <p>{paragraph.text || "No paragraph text."}</p>
                    {paragraph.citations.length > 0 ? (
                      <div className="trace-citations-row">
                        {paragraph.citations.map((citation) => (
                          <button
                            key={citation.id}
                            type="button"
                            className={`trace-citation-chip ${
                              citation.id === selectedCitation?.id ? "is-active" : ""
                            }`}
                            onClick={() => setSelectedCitationId(citation.id)}
                            aria-label={`Open citation ${citation.docId} page ${citation.page}`}
                          >
                            {citation.docId} p.{citation.page}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="traceability-empty inline">No citations for this paragraph.</p>
                    )}
                  </article>
                ))}
              </div>
            </details>
          ))}
        </div>

        <aside className="traceability-detail" aria-live="polite">
          {selectedCitation ? (
            <CitationDetailCard citation={selectedCitation} />
          ) : (
            <p className="traceability-empty">Select a citation to view evidence context.</p>
          )}
        </aside>
      </div>
    </section>
  );
}

function CitationDetailCard({ citation }: { citation: TraceCitation }) {
  return (
    <article className="citation-detail-card">
      <h5>Evidence Context</h5>
      <dl>
        <div>
          <dt>Section</dt>
          <dd>{citation.sectionKey}</dd>
        </div>
        <div>
          <dt>Paragraph</dt>
          <dd>{citation.paragraphIndex}</dd>
        </div>
        <div>
          <dt>Document</dt>
          <dd>
            <code>{citation.docId}</code>
          </dd>
        </div>
        <div>
          <dt>Page</dt>
          <dd>{citation.page}</dd>
        </div>
      </dl>
      <p className="citation-snippet">{citation.snippet}</p>
      <p className="citation-paragraph-preview">{citation.paragraphText}</p>
    </article>
  );
}
