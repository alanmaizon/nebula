import type { JsonValue } from "./traceability";

export type ParseQuality = "good" | "low" | "none" | "unknown";

export type ParseQualityCounts = {
  good: number;
  low: number;
  none: number;
};

export type ParseDocumentSignal = {
  fileName: string;
  quality: ParseQuality;
  reason: string | null;
  parserId: string | null;
};

export type ParseDiagnostics = {
  source: "upload" | "unavailable";
  documentsTotal: number;
  qualityCounts: ParseQualityCounts;
  documents: ParseDocumentSignal[];
};

export type AdaptiveContextSignal = {
  mode: string;
  windowCount: number;
  rawCandidates: number;
  dedupedCandidates: number;
  droppedCandidates: number;
  dedupeRatio: number;
};

export type RfpSelectionCandidate = {
  documentId: string | null;
  fileName: string;
  score: number | null;
};

export type RfpSelectionSignal = {
  selectedFileName: string | null;
  ambiguous: boolean;
  candidates: RfpSelectionCandidate[];
};

export type ExtractionSignal = {
  mode: string;
  chunksTotal: number;
  chunksConsidered: number;
  deterministicQuestionCount: number;
  novaQuestionCount: number;
  novaError: string | null;
  adaptiveContext: AdaptiveContextSignal;
  rfpSelection: RfpSelectionSignal;
};

export type UnresolvedGapSignal = {
  requirementId: string;
  internalId: string | null;
  originalId: string | null;
  status: "partial" | "missing" | "met" | "unknown";
  notes: string;
  evidenceRefs: string[];
};

export type QualitySignals = {
  parse: ParseDiagnostics;
  extraction: ExtractionSignal;
  unresolvedGaps: UnresolvedGapSignal[];
  recommendations: string[];
};

type BuildQualitySignalsInput = {
  parseDiagnostics: ParseDiagnostics;
  extractionPayload: JsonValue | null;
  unresolvedGapsPayload: JsonValue[];
};

function asRecord(value: JsonValue | unknown): Record<string, unknown> | null {
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

function clampNonNegative(value: number | null): number {
  if (value === null) {
    return 0;
  }
  return value < 0 ? 0 : value;
}

function asParseQuality(value: unknown): ParseQuality {
  const normalized = asString(value)?.toLowerCase();
  if (normalized === "good" || normalized === "low" || normalized === "none") {
    return normalized;
  }
  return "unknown";
}

function parseCountsFromDocuments(documents: ParseDocumentSignal[]): ParseQualityCounts {
  const counts: ParseQualityCounts = { good: 0, low: 0, none: 0 };
  for (const document of documents) {
    if (document.quality === "good" || document.quality === "low" || document.quality === "none") {
      counts[document.quality] += 1;
    }
  }
  return counts;
}

function parseCountsFromRecord(value: Record<string, unknown> | null): ParseQualityCounts | null {
  if (!value) {
    return null;
  }
  const good = asNumber(value.good);
  const low = asNumber(value.low);
  const none = asNumber(value.none);
  if (good === null || low === null || none === null) {
    return null;
  }
  return {
    good: clampNonNegative(good),
    low: clampNonNegative(low),
    none: clampNonNegative(none),
  };
}

export function createUnavailableParseDiagnostics(documentsTotal: number): ParseDiagnostics {
  return {
    source: "unavailable",
    documentsTotal: Math.max(0, documentsTotal),
    qualityCounts: { good: 0, low: 0, none: 0 },
    documents: [],
  };
}

export function parseUploadDiagnostics(
  payload: Record<string, unknown>,
  fallbackDocumentsTotal: number
): ParseDiagnostics {
  const documentsRaw = Array.isArray(payload.documents) ? payload.documents : [];
  const documents: ParseDocumentSignal[] = [];

  for (const rawDocument of documentsRaw) {
    const documentRecord = asRecord(rawDocument);
    if (!documentRecord) {
      continue;
    }
    const parseReportRecord = asRecord(documentRecord.parse_report);
    documents.push({
      fileName: asString(documentRecord.file_name) ?? "unknown",
      quality: asParseQuality(parseReportRecord?.quality),
      reason: asString(parseReportRecord?.reason),
      parserId: asString(parseReportRecord?.parser_id),
    });
  }

  const responseParseReport = asRecord(payload.parse_report);
  const responseCounts = parseCountsFromRecord(
    asRecord(responseParseReport?.quality_counts)
  );
  const fallbackCounts = parseCountsFromDocuments(documents);

  return {
    source: "upload",
    documentsTotal:
      clampNonNegative(asNumber(responseParseReport?.documents_total)) || Math.max(0, fallbackDocumentsTotal),
    qualityCounts: responseCounts ?? fallbackCounts,
    documents,
  };
}

function parseAdaptiveContext(value: Record<string, unknown> | null): AdaptiveContextSignal {
  return {
    mode: asString(value?.mode) ?? "unknown",
    windowCount: clampNonNegative(asNumber(value?.window_count)),
    rawCandidates: clampNonNegative(asNumber(value?.raw_candidates)),
    dedupedCandidates: clampNonNegative(asNumber(value?.deduped_candidates)),
    droppedCandidates: clampNonNegative(asNumber(value?.dropped_candidates)),
    dedupeRatio: clampNonNegative(asNumber(value?.dedupe_ratio)),
  };
}

function parseRfpSelection(value: Record<string, unknown> | null): RfpSelectionSignal {
  const candidatesRaw = Array.isArray(value?.candidates) ? value?.candidates : [];
  const candidates: RfpSelectionCandidate[] = [];
  for (const rawCandidate of candidatesRaw) {
    const candidateRecord = asRecord(rawCandidate);
    if (!candidateRecord) {
      continue;
    }
    candidates.push({
      documentId: asString(candidateRecord.document_id),
      fileName: asString(candidateRecord.file_name) ?? "unknown",
      score: asNumber(candidateRecord.score),
    });
  }

  return {
    selectedFileName: asString(value?.selected_file_name),
    ambiguous: Boolean(value?.ambiguous),
    candidates,
  };
}

function parseExtractionSignal(extractionPayload: JsonValue | null): ExtractionSignal {
  const extractionRecord = asRecord(extractionPayload);
  const adaptiveContext = parseAdaptiveContext(asRecord(extractionRecord?.adaptive_context));
  const rfpSelection = parseRfpSelection(asRecord(extractionRecord?.rfp_selection));

  return {
    mode: asString(extractionRecord?.mode) ?? "unknown",
    chunksTotal: clampNonNegative(asNumber(extractionRecord?.chunks_total)),
    chunksConsidered: clampNonNegative(asNumber(extractionRecord?.chunks_considered)),
    deterministicQuestionCount: clampNonNegative(
      asNumber(extractionRecord?.deterministic_question_count)
    ),
    novaQuestionCount: clampNonNegative(asNumber(extractionRecord?.nova_question_count)),
    novaError: asString(extractionRecord?.nova_error),
    adaptiveContext,
    rfpSelection,
  };
}

function parseUnresolvedGapStatus(value: unknown): "partial" | "missing" | "met" | "unknown" {
  const normalized = asString(value)?.toLowerCase();
  if (normalized === "partial" || normalized === "missing" || normalized === "met") {
    return normalized;
  }
  return "unknown";
}

function parseUnresolvedGaps(items: JsonValue[]): UnresolvedGapSignal[] {
  const parsed: UnresolvedGapSignal[] = [];
  for (const raw of items) {
    const record = asRecord(raw);
    if (!record) {
      continue;
    }
    const evidenceRefsRaw = Array.isArray(record.evidence_refs) ? record.evidence_refs : [];
    const evidenceRefs = evidenceRefsRaw
      .map((entry) => asString(entry) ?? "")
      .filter((entry) => entry.length > 0);

    parsed.push({
      requirementId: asString(record.requirement_id) ?? "unknown",
      internalId: asString(record.internal_id),
      originalId: asString(record.original_id),
      status: parseUnresolvedGapStatus(record.status),
      notes: asString(record.notes) ?? "No coverage note available.",
      evidenceRefs,
    });
  }
  return parsed;
}

function buildRecommendations(signals: {
  parse: ParseDiagnostics;
  extraction: ExtractionSignal;
  unresolvedGaps: UnresolvedGapSignal[];
}): string[] {
  const items: string[] = [];
  const { parse, extraction, unresolvedGaps } = signals;

  if (parse.source === "unavailable") {
    items.push("Upload the latest RFP package in this session to refresh parse-quality diagnostics.");
  }

  if (parse.qualityCounts.none > 0) {
    items.push(
      "Replace non-parsed files with text-searchable PDF, DOCX, or RTF so requirements can be extracted."
    );
  }

  if (parse.qualityCounts.low > 0) {
    items.push(
      "For low parse quality files, upload cleaner source documents (not screenshots) and rerun extraction."
    );
  }

  if (extraction.rfpSelection.ambiguous) {
    items.push(
      "Resolve RFP source ambiguity by keeping one canonical RFP file and removing duplicate solicitation versions."
    );
  }

  if (extraction.mode === "deterministic-only" || extraction.novaError) {
    items.push(
      "Verify Bedrock credentials/region and rerun so Nova-assisted extraction can improve requirement recall."
    );
  }

  if (unresolvedGaps.length > 0) {
    items.push(
      `Resolve ${unresolvedGaps.length} unresolved requirement gap(s) by uploading targeted evidence documents.`
    );
  }

  if (
    extraction.adaptiveContext.mode === "multi_pass" &&
    extraction.adaptiveContext.dedupeRatio >= 0.35
  ) {
    items.push(
      "Long-RFP extraction had heavy overlap; split large appendices into separate files to reduce duplicate candidates."
    );
  }

  items.push(
    "Re-run Generate after document updates and confirm unresolved gaps are zero before export."
  );
  items.push(
    "Use Citation Traceability to verify each key requirement section is backed by direct source evidence."
  );
  items.push("Upload rubric and required-attachment guidance alongside the RFP to improve coverage fidelity.");

  const deduped = Array.from(new Set(items));
  return deduped.slice(0, 6);
}

export function buildQualitySignals({
  parseDiagnostics,
  extractionPayload,
  unresolvedGapsPayload,
}: BuildQualitySignalsInput): QualitySignals {
  const extraction = parseExtractionSignal(extractionPayload);
  const unresolvedGaps = parseUnresolvedGaps(unresolvedGapsPayload);
  const recommendations = buildRecommendations({
    parse: parseDiagnostics,
    extraction,
    unresolvedGaps,
  });

  return {
    parse: parseDiagnostics,
    extraction,
    unresolvedGaps,
    recommendations,
  };
}
