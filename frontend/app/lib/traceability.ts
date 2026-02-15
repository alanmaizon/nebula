export type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;

export type TraceCitation = {
  id: string;
  sectionKey: string;
  paragraphIndex: number;
  citationIndex: number;
  docId: string;
  page: number;
  snippet: string;
  paragraphText: string;
};

export type TraceParagraph = {
  text: string;
  citations: TraceCitation[];
};

export type TraceSection = {
  sectionKey: string;
  paragraphs: TraceParagraph[];
};

export type MissingEvidenceItem = {
  claim: string;
  suggestedUpload: string;
  affectedSections: string[];
};

export type MissingEvidenceGroup = {
  sectionKey: string;
  items: MissingEvidenceItem[];
};

export type TraceabilityData = {
  sections: TraceSection[];
  citationCount: number;
  missingEvidenceGroups: MissingEvidenceGroup[];
};

function asRecord(value: JsonValue): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function parseMissingEvidenceList(rawItems: unknown): MissingEvidenceItem[] {
  const rows = Array.isArray(rawItems) ? rawItems : [];
  const parsed: MissingEvidenceItem[] = [];

  for (const raw of rows) {
    const row = asRecord((raw as JsonValue) ?? null);
    if (!row) {
      continue;
    }

    const claim = asString(row.claim) ?? "Missing supporting evidence for this section.";
    const suggestedUpload =
      asString(row.suggested_upload) ??
      asString(row.suggestedUpload) ??
      "Upload a document with direct supporting evidence for this claim.";

    const affectedSectionsRaw = Array.isArray(row.affected_sections)
      ? row.affected_sections
      : Array.isArray(row.affectedSections)
        ? row.affectedSections
        : [];

    const affectedSections = affectedSectionsRaw
      .map((entry) => asString(entry) ?? "")
      .filter((entry) => entry.length > 0);

    if (affectedSections.length === 0) {
      const sectionFromItem = asString(row.section_key) ?? asString(row.sectionKey);
      if (sectionFromItem) {
        affectedSections.push(sectionFromItem);
      }
    }

    parsed.push({
      claim,
      suggestedUpload,
      affectedSections: affectedSections.length > 0 ? affectedSections : ["Unassigned"],
    });
  }

  return parsed;
}

export function extractTraceabilityData(exportPayload: JsonValue | null): TraceabilityData {
  const exportRecord = asRecord(exportPayload);
  const bundleRecord = exportRecord ? asRecord((exportRecord.bundle as JsonValue) ?? null) : null;
  const jsonBundle = bundleRecord ? asRecord((bundleRecord.json as JsonValue) ?? null) : null;
  const draftsRecord = jsonBundle ? asRecord((jsonBundle.drafts as JsonValue) ?? null) : null;

  const sections: TraceSection[] = [];
  const missingEvidenceAccumulator: MissingEvidenceItem[] = [];
  let citationCount = 0;

  if (draftsRecord) {
    for (const [sectionKey, sectionValue] of Object.entries(draftsRecord)) {
      const section = asRecord((sectionValue as JsonValue) ?? null);
      const draft = section ? asRecord((section.draft as JsonValue) ?? null) : null;
      const paragraphsRaw = Array.isArray(draft?.paragraphs) ? draft?.paragraphs : [];
      const sectionMissingEvidenceRaw = Array.isArray(draft?.missing_evidence) ? draft?.missing_evidence : [];
      const paragraphs: TraceParagraph[] = [];

      sectionMissingEvidenceRaw.forEach((entry) => {
        const row = asRecord((entry as JsonValue) ?? null);
        if (!row) {
          return;
        }
        missingEvidenceAccumulator.push({
          claim: asString(row.claim) ?? "Missing supporting evidence for this section.",
          suggestedUpload:
            asString(row.suggested_upload) ??
            asString(row.suggestedUpload) ??
            "Upload a document with direct supporting evidence for this claim.",
          affectedSections: [sectionKey],
        });
      });

      paragraphsRaw.forEach((paragraphValue, paragraphIndex) => {
        const paragraph = asRecord((paragraphValue as JsonValue) ?? null);
        if (!paragraph) {
          return;
        }

        const text = asString(paragraph.text) ?? "";
        const citationsRaw = Array.isArray(paragraph.citations) ? paragraph.citations : [];
        const citations: TraceCitation[] = [];

        citationsRaw.forEach((citationValue, citationIndex) => {
          const citation = asRecord((citationValue as JsonValue) ?? null);
          if (!citation) {
            return;
          }

          const docId = asString(citation.doc_id) ?? asString(citation.docId) ?? "unknown-document";
          const page = asNumber(citation.page) ?? 1;
          const snippet = asString(citation.snippet) ?? "No snippet available.";

          citationCount += 1;
          citations.push({
            id: `${sectionKey}-${paragraphIndex + 1}-${citationIndex + 1}-${docId}-${page}`,
            sectionKey,
            paragraphIndex: paragraphIndex + 1,
            citationIndex: citationIndex + 1,
            docId,
            page,
            snippet,
            paragraphText: text,
          });
        });

        paragraphs.push({ text, citations });
      });

      if (paragraphs.length > 0) {
        sections.push({ sectionKey, paragraphs });
      }
    }
  }

  missingEvidenceAccumulator.push(...parseMissingEvidenceList(jsonBundle?.missing_evidence));

  const dedupedMissingEvidence = Array.from(
    new Map(
      missingEvidenceAccumulator.map((item) => [
        JSON.stringify(
          {
            claim: item.claim,
            suggestedUpload: item.suggestedUpload,
            affectedSections: [...item.affectedSections].sort(),
          },
          null,
          0
        ),
        item,
      ])
    ).values()
  );

  const grouped = new Map<string, MissingEvidenceItem[]>();
  dedupedMissingEvidence.forEach((item) => {
    item.affectedSections.forEach((section) => {
      const key = section || "Unassigned";
      const items = grouped.get(key) ?? [];
      items.push(item);
      grouped.set(key, items);
    });
  });

  const missingEvidenceGroups: MissingEvidenceGroup[] = Array.from(grouped.entries())
    .map(([sectionKey, items]) => ({
      sectionKey,
      items,
    }))
    .sort((left, right) => left.sectionKey.localeCompare(right.sectionKey));

  return {
    sections,
    citationCount,
    missingEvidenceGroups,
  };
}
