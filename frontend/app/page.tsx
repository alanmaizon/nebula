"use client";

import { useMemo, useState, type DragEvent, type ReactNode } from "react";
import SegmentedToggle from "./components/SegmentedToggle";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;
type ViewMode = "summary" | "json";
type ExportViewMode = "preview" | "markdown" | "json";
type RunStatus = "idle" | "loading" | "success" | "error";
type StageId = "upload" | "extract" | "retrieve" | "draft" | "coverage" | "export";
type StageState = "pending" | "running" | "done" | "error";
type ResultPane = "requirements" | "retrieval" | "draft" | "coverage" | "export";

type StageInfo = {
  state: StageState;
  note: string;
};

type IntakeContext = {
  country: string;
  organization_type: string;
  funder_track: string;
  funding_goal: string;
  sector_focus: string;
};

type CoverageMatrixStatus = "met" | "partial" | "missing" | "na";
type CoverageDetailItem = {
  requirementId: string;
  label: string;
  status: CoverageMatrixStatus;
  notes: string;
};

type SectionRunResult = {
  sectionKey: string;
  prompt: string;
  retrieval: JsonValue;
  draft: JsonValue;
  coverage: JsonValue;
  grounding: JsonValue | null;
};

type PipelineRunResult = {
  projectId: string;
  sectionKey: string;
  documentsIndexed: number;
  requirements: JsonValue;
  extraction: JsonValue | null;
  sectionRuns: SectionRunResult[];
  retrieval: JsonValue;
  draft: JsonValue;
  coverage: JsonValue;
  exportJson: JsonValue;
  exportMarkdown: string;
};

const workflowSteps: Array<{ id: StageId; label: string }> = [
  { id: "upload", label: "Upload documents" },
  { id: "extract", label: "Extract requirements" },
  { id: "retrieve", label: "Retrieve evidence" },
  { id: "draft", label: "Draft with citations" },
  { id: "coverage", label: "Coverage matrix" },
  { id: "export", label: "Export artifacts" },
];
const workflowStepLabelSet = new Set(workflowSteps.map((step) => step.label));

const paneForStage: Record<StageId, ResultPane> = {
  upload: "requirements",
  extract: "requirements",
  retrieve: "retrieval",
  draft: "draft",
  coverage: "coverage",
  export: "export",
};

const paneTabs: Array<{ key: ResultPane; label: string }> = [
  { key: "requirements", label: "Requirements" },
  { key: "retrieval", label: "Retrieval" },
  { key: "draft", label: "Draft" },
  { key: "coverage", label: "Coverage" },
  { key: "export", label: "Export" },
];

function emptyPipelineStages(): Record<StageId, StageInfo> {
  return {
    upload: { state: "pending", note: "Waiting for documents" },
    extract: { state: "pending", note: "Waiting for extraction" },
    retrieve: { state: "pending", note: "Waiting for section selection" },
    draft: { state: "pending", note: "Waiting for draft generation" },
    coverage: { state: "pending", note: "Waiting for coverage" },
    export: { state: "pending", note: "Waiting for export" },
  };
}

function asRecord(value: JsonValue): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeLooseText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function dedupeStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const value of values) {
    const normalized = normalizeLooseText(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    deduped.push(value.trim());
  }
  return deduped;
}

function cleanListEntries(entries: unknown, headingAliases: string[]): string[] {
  if (!Array.isArray(entries)) {
    return [];
  }
  const normalizedAliases = new Set(
    headingAliases.map((alias) => normalizeLooseText(alias.replace(/:$/, ""))).filter(Boolean)
  );
  const cleaned: string[] = [];
  for (const entry of entries) {
    const text = asString(entry);
    if (!text) {
      continue;
    }
    const normalized = normalizeLooseText(text.replace(/:$/, ""));
    if (normalizedAliases.has(normalized)) {
      continue;
    }
    cleaned.push(text);
  }
  return dedupeStrings(cleaned);
}

function questionPromptKey(prompt: string): string {
  const firstClause = prompt.split(":")[0] ?? prompt;
  return normalizeLooseText(firstClause.replace(/\([^)]*\)/g, " "));
}

function questionPromptScore(prompt: string): number {
  let score = prompt.trim().length;
  if (prompt.includes(":")) {
    score += 50;
  }
  if (/\b\d+\s*(?:words?|chars?|characters?)\b/i.test(prompt)) {
    score += 25;
  }
  return score;
}

function readQuestionPrompts(requirements: JsonValue | null): string[] {
  const record = asRecord(requirements);
  const maybeQuestions = record?.questions;
  if (!Array.isArray(maybeQuestions)) {
    return [];
  }

  const selected = new Map<string, { prompt: string; score: number; index: number }>();
  for (const [index, item] of maybeQuestions.entries()) {
    let prompt: string | null = null;
    if (typeof item === "string") {
      prompt = asString(item);
    } else if (item && typeof item === "object") {
      prompt = asString((item as Record<string, unknown>).prompt);
    }
    if (!prompt) {
      continue;
    }
    const key = questionPromptKey(prompt) || normalizeLooseText(prompt);
    const score = questionPromptScore(prompt);
    const existing = selected.get(key);
    if (!existing || score > existing.score) {
      selected.set(key, { prompt, score, index: existing?.index ?? index });
    }
  }
  return Array.from(selected.values())
    .sort((left, right) => left.index - right.index)
    .map((item) => item.prompt);
}

function questionLimitLabel(question: Record<string, unknown>): string | null {
  const limit = question.limit;
  if (!limit || typeof limit !== "object" || Array.isArray(limit)) {
    return null;
  }
  const limitRecord = limit as Record<string, unknown>;
  const type = asString(limitRecord.type);
  const value = limitRecord.value;
  if (!type || type === "none") {
    return null;
  }
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return `${value} ${type}`;
  }
  return type;
}

function humanizeRequirementId(requirementId: string): string {
  const compact = requirementId.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!compact) {
    return "Unknown requirement";
  }
  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

function buildCoverageRequirementLabelLookup(requirements: JsonValue | null): Record<string, string> {
  const lookup: Record<string, string> = {};
  const requirementsRecord = asRecord(requirements);
  if (!requirementsRecord) {
    return lookup;
  }

  const questions = Array.isArray(requirementsRecord.questions) ? requirementsRecord.questions : [];
  for (const [index, question] of questions.entries()) {
    if (!question || typeof question !== "object") {
      continue;
    }
    const row = question as Record<string, unknown>;
    const prompt = asString(row.prompt);
    if (!prompt) {
      continue;
    }
    const id = asString(row.id) ?? `Q${index + 1}`;
    lookup[id] = prompt;
    lookup[id.toUpperCase()] = prompt;
    lookup[normalizeLooseText(id)] = prompt;
  }

  const attachments = Array.isArray(requirementsRecord.required_attachments)
    ? requirementsRecord.required_attachments
    : [];
  let attachmentIndex = 1;
  for (const attachment of attachments) {
    const text = asString(attachment);
    if (!text) {
      continue;
    }
    const id = `A${attachmentIndex}`;
    attachmentIndex += 1;
    lookup[id] = text;
    lookup[id.toUpperCase()] = text;
    lookup[normalizeLooseText(id)] = text;
  }

  return lookup;
}

function resolveCoverageRequirementLabel(requirementId: string, lookup: Record<string, string>): string {
  if (!requirementId) {
    return "Unknown requirement";
  }
  return (
    lookup[requirementId] ??
    lookup[requirementId.toUpperCase()] ??
    lookup[normalizeLooseText(requirementId)] ??
    humanizeRequirementId(requirementId)
  );
}

function deriveSectionKey(questionPrompt: string): string {
  const trimmed = questionPrompt.trim();
  if (!trimmed) {
    return "Need Statement";
  }
  const head = trimmed.split(":")[0]?.trim() || trimmed;
  const withoutTrailingLimit = head.replace(/\s*\([^)]*\)\s*$/, "").trim();
  const candidate = withoutTrailingLimit || head || trimmed;
  return candidate.slice(0, 120).trim();
}

function buildSectionTargets(questionPrompts: string[]): Array<{ prompt: string; sectionKey: string }> {
  const prompts = questionPrompts.length > 0 ? questionPrompts : ["Need Statement"];
  const targets: Array<{ prompt: string; sectionKey: string }> = [];
  const seen: Record<string, number> = {};
  for (const prompt of prompts) {
    const normalizedPrompt = prompt.trim();
    if (!normalizedPrompt) {
      continue;
    }
    const baseKey = deriveSectionKey(normalizedPrompt);
    const existing = seen[baseKey] ?? 0;
    seen[baseKey] = existing + 1;
    const sectionKey =
      existing === 0 ? baseKey : `${baseKey.slice(0, Math.max(1, 118 - String(existing + 1).length))} ${existing + 1}`;
    targets.push({ prompt: normalizedPrompt, sectionKey });
  }
  return targets;
}

function combineMarkdownFilesFromExport(exportPayload: JsonValue | null): string {
  const exportRecord = asRecord(exportPayload);
  const projectRecord = exportRecord ? asRecord((exportRecord.project as JsonValue) ?? null) : null;
  const bundleRecord = exportRecord ? asRecord((exportRecord.bundle as JsonValue) ?? null) : null;
  const bundleJsonRecord = bundleRecord ? asRecord((bundleRecord.json as JsonValue) ?? null) : null;
  const markdownRecord = bundleRecord ? asRecord((bundleRecord.markdown as JsonValue) ?? null) : null;
  const intakeRecord = bundleJsonRecord ? asRecord((bundleJsonRecord.intake as JsonValue) ?? null) : null;
  const files = Array.isArray(markdownRecord?.files) ? markdownRecord.files : [];

  const projectName = asString(projectRecord?.name) ?? "Project";
  const country = asString(intakeRecord?.country) ?? "Unknown country";
  const organizationType = asString(intakeRecord?.organization_type);
  const funderTrack = asString(intakeRecord?.funder_track);
  const fundingGoal = asString(intakeRecord?.funding_goal);
  const sectorFocus = asString(intakeRecord?.sector_focus);

  const cleanBlock = (content: string): string => {
    let cleaned = content;
    cleaned = cleaned.replace(/\n### Unsupported \/ Missing\s*\n- None\s*(?=\n|$)/g, "\n");
    cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
    return cleaned.trim();
  };

  const isIrrelevantMissingEvidenceFile = (path: string, content: string): boolean => {
    if (!path.toLowerCase().endsWith("missing_evidence.md")) {
      return false;
    }
    return /\|\s*n\/a\s*\|\s*none\s*\|\s*none\s*\|\s*none\s*\|/i.test(content);
  };

  const blocks: string[] = [];
  for (const file of files) {
    if (!file || typeof file !== "object") {
      continue;
    }
    const row = file as Record<string, unknown>;
    const path = asString(row.path) ?? "";
    const content = asString(row.content) ?? "";
    if (!content) {
      continue;
    }
    if (isIrrelevantMissingEvidenceFile(path, content)) {
      continue;
    }
    const cleaned = cleanBlock(content);
    if (!cleaned) {
      continue;
    }
    blocks.push(cleaned);
  }

  const introDetails: string[] = [];
  if (organizationType) {
    introDetails.push(`organization type: ${organizationType}`);
  }
  if (funderTrack) {
    introDetails.push(`funder track: ${funderTrack}`);
  }
  if (fundingGoal) {
    introDetails.push(`funding goal: ${fundingGoal}`);
  }
  if (sectorFocus) {
    introDetails.push(`sector focus: ${sectorFocus}`);
  }

  const intro =
    introDetails.length > 0
      ? `This report consolidates generated draft and compliance outputs with intake context (${introDetails.join("; ")}).`
      : "This report consolidates generated draft and compliance outputs.";

  const preface = [`# ${projectName}`, `## ${country}`, "", intro].join("\n").trim();
  const body = blocks.join("\n\n---\n\n").trim();
  return body ? `${preface}\n\n---\n\n${body}` : preface;
}

function toCoverageStatus(value: unknown): CoverageMatrixStatus {
  if (value === "met" || value === "partial" || value === "missing") {
    return value;
  }
  return "na";
}

function parseInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const pattern = /(\[[^\]]+\]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  const fragments = text.split(pattern).filter((fragment) => fragment.length > 0);
  return fragments.map((fragment, index) => {
    const key = `${keyPrefix}-${index}`;
    const linkMatch = fragment.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      return (
        <a key={key} href={linkMatch[2]} target="_blank" rel="noreferrer">
          {linkMatch[1]}
        </a>
      );
    }
    if (fragment.startsWith("`") && fragment.endsWith("`") && fragment.length >= 2) {
      return <code key={key}>{fragment.slice(1, -1)}</code>;
    }
    if (fragment.startsWith("**") && fragment.endsWith("**") && fragment.length >= 4) {
      return <strong key={key}>{fragment.slice(2, -2)}</strong>;
    }
    if (fragment.startsWith("*") && fragment.endsWith("*") && fragment.length >= 2) {
      return <em key={key}>{fragment.slice(1, -1)}</em>;
    }
    return <span key={key}>{fragment}</span>;
  });
}

function isListLine(line: string): boolean {
  return /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line);
}

function splitTableCells(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) {
    return [];
  }
  let body = trimmed;
  if (body.startsWith("|")) {
    body = body.slice(1);
  }
  if (body.endsWith("|")) {
    body = body.slice(0, -1);
  }
  return body.split("|").map((cell) => cell.trim());
}

function isTableSeparatorLine(line: string): boolean {
  const cells = splitTableCells(line);
  if (cells.length < 2) {
    return false;
  }
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function looksLikeTableHeader(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length) {
    return false;
  }
  const headerCells = splitTableCells(lines[index]);
  if (headerCells.length < 2) {
    return false;
  }
  return isTableSeparatorLine(lines[index + 1]);
}

function isBlockBoundary(line: string): boolean {
  return (
    /^#{1,6}\s+/.test(line) ||
    /^>\s?/.test(line) ||
    /^```/.test(line) ||
    /^(-{3,}|\*{3,}|_{3,})$/.test(line) ||
    isListLine(line)
  );
}

function MarkdownViewer({ content, emptyMessage }: { content: string; emptyMessage: string }) {
  const normalized = content.replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return (
      <div className="markdown-viewer is-empty">
        <p>{emptyMessage}</p>
      </div>
    );
  }

  const lines = normalized.split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const text = headingMatch[2];
      const inline = parseInlineMarkdown(text, `heading-${index}`);
      switch (level) {
        case 1:
          blocks.push(<h1 key={`h-${index}`}>{inline}</h1>);
          break;
        case 2:
          blocks.push(<h2 key={`h-${index}`}>{inline}</h2>);
          break;
        case 3:
          blocks.push(<h3 key={`h-${index}`}>{inline}</h3>);
          break;
        case 4:
          blocks.push(<h4 key={`h-${index}`}>{inline}</h4>);
          break;
        case 5:
          blocks.push(<h5 key={`h-${index}`}>{inline}</h5>);
          break;
        default:
          blocks.push(<h6 key={`h-${index}`}>{inline}</h6>);
          break;
      }
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${index}`} className="markdown-divider" />);
      index += 1;
      continue;
    }

    if (/^```/.test(trimmed)) {
      const language = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length && /^```/.test(lines[index].trim())) {
        index += 1;
      }
      blocks.push(
        <pre key={`code-${index}`} className="markdown-code">
          <code>{language ? `${language}\n${codeLines.join("\n")}` : codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (unorderedMatch) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        const match = current.match(/^[-*]\s+(.*)$/);
        if (!match) {
          break;
        }
        items.push(<li key={`ul-${index}`}>{parseInlineMarkdown(match[1], `ul-${index}`)}</li>);
        index += 1;
      }
      blocks.push(<ul key={`ul-group-${index}`}>{items}</ul>);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        const match = current.match(/^\d+\.\s+(.*)$/);
        if (!match) {
          break;
        }
        items.push(<li key={`ol-${index}`}>{parseInlineMarkdown(match[1], `ol-${index}`)}</li>);
        index += 1;
      }
      blocks.push(<ol key={`ol-group-${index}`}>{items}</ol>);
      continue;
    }

    const blockQuoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (blockQuoteMatch) {
      const quoteLines: string[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        const match = current.match(/^>\s?(.*)$/);
        if (!match) {
          break;
        }
        quoteLines.push(match[1]);
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${index}`}>{quoteLines.join(" ")}</blockquote>);
      continue;
    }

    if (looksLikeTableHeader(lines, index)) {
      const headerCellsRaw = splitTableCells(lines[index]);
      const columnCount = headerCellsRaw.length;
      index += 2;

      const bodyRows: string[][] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        if (!current) {
          break;
        }
        const rowCellsRaw = splitTableCells(current);
        if (rowCellsRaw.length === 0) {
          break;
        }
        if (isTableSeparatorLine(current)) {
          index += 1;
          continue;
        }
        const rowCells = rowCellsRaw.slice(0, columnCount);
        if (rowCellsRaw.length > columnCount) {
          rowCells[columnCount - 1] = rowCellsRaw.slice(columnCount - 1).join(" | ");
        }
        while (rowCells.length < columnCount) {
          rowCells.push("");
        }
        bodyRows.push(rowCells);
        index += 1;
      }

      blocks.push(
        <div key={`table-wrap-${index}`} className="markdown-table-wrap">
          <table className="markdown-table">
            <thead>
              <tr>
                {headerCellsRaw.map((cell, headerIndex) => (
                  <th key={`th-${index}-${headerIndex}`}>{parseInlineMarkdown(cell, `th-${index}-${headerIndex}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((row, rowIndex) => (
                <tr key={`tr-${index}-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`td-${index}-${rowIndex}-${cellIndex}`}>
                      {parseInlineMarkdown(cell, `td-${index}-${rowIndex}-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const current = lines[index];
      if (!current.trim()) {
        break;
      }
      if (isBlockBoundary(current.trim()) && paragraphLines.length > 0) {
        break;
      }
      paragraphLines.push(current.trim());
      index += 1;
    }
    blocks.push(
      <p key={`p-${index}`}>{parseInlineMarkdown(paragraphLines.join(" "), `p-${index}`)}</p>
    );
  }

  return <div className="markdown-viewer">{blocks}</div>;
}

export default function HomePage() {
  const [showWorkspace, setShowWorkspace] = useState(false);

  const [projectName, setProjectName] = useState("Portland Community Resilience 2026 Demo");
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);
  const [activityFeed, setActivityFeed] = useState<string[]>([]);

  const [intake, setIntake] = useState<IntakeContext>({
    country: "United States",
    organization_type: "Non-profit (501(c)(3))",
    funder_track: "city-community-resilience",
    funding_goal: "housing-stability-program",
    sector_focus: "housing stability and family support",
  });

  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [, setStages] = useState<Record<StageId, StageInfo>>(emptyPipelineStages());
  const [result, setResult] = useState<PipelineRunResult | null>(null);
  const [activePane, setActivePane] = useState<ResultPane>("requirements");
  const [activeSectionKey, setActiveSectionKey] = useState<string>("");

  const [requirementsView, setRequirementsView] = useState<ViewMode>("summary");
  const [retrievalView, setRetrievalView] = useState<ViewMode>("summary");
  const [draftView, setDraftView] = useState<ViewMode>("summary");
  const [coverageView, setCoverageView] = useState<ViewMode>("summary");
  const [exportView, setExportView] = useState<ExportViewMode>("preview");

  const isRunning = runStatus === "loading";

  function appendFeed(message: string) {
    setActivityFeed((prev) => [...prev, message]);
  }

  function setStage(id: StageId, state: StageState, note: string) {
    setStages((prev) => ({ ...prev, [id]: { state, note } }));
    const stepLabel = workflowSteps.find((step) => step.id === id)?.label ?? id;
    if (state === "running") {
      appendFeed(stepLabel);
      return;
    }
    if (state === "done" || state === "error") {
      appendFeed(note);
    }
  }

  function resetStages() {
    setStages(emptyPipelineStages());
  }

  async function parseJsonResponse(response: Response): Promise<Record<string, unknown>> {
    const payload = (await response.json()) as Record<string, unknown>;
    if (!response.ok) {
      const detail = payload.detail;
      if (typeof detail === "string") {
        throw new Error(detail);
      }
      if (detail !== undefined) {
        throw new Error(JSON.stringify(detail));
      }
      throw new Error(`Request failed (${response.status})`);
    }
    return payload;
  }

  async function ensureProject(): Promise<string> {
    if (projectId.trim()) {
      return projectId;
    }

    const response = await fetch(`${apiBase}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: projectName || "Nebula Project" }),
    });
    const payload = await parseJsonResponse(response);
    const created = String(payload.id);
    setProjectId(created);
    return created;
  }

  async function saveIntakeContext(currentProjectId: string) {
    const response = await fetch(`${apiBase}/projects/${currentProjectId}/intake`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(intake),
    });
    await parseJsonResponse(response);
  }

  async function ensureIndexedDocuments(currentProjectId: string): Promise<number> {
    if (files.length > 0) {
      setStage("upload", "running", "Uploading selected documents...");
      const formData = new FormData();
      for (const file of files) {
        formData.append("files", file);
      }
      const response = await fetch(`${apiBase}/projects/${currentProjectId}/upload`, {
        method: "POST",
        body: formData,
      });
      const payload = await parseJsonResponse(response);
      const uploadedDocs = Array.isArray(payload.documents)
        ? payload.documents.filter((item) => !!item && typeof item === "object")
        : [];
      setStage("upload", "done", `Indexed ${uploadedDocs.length} uploaded file(s).`);
      return uploadedDocs.length;
    }

    setStage("upload", "running", "Checking existing indexed documents...");
    const docsResponse = await fetch(`${apiBase}/projects/${currentProjectId}/documents`);
    const docsPayload = await parseJsonResponse(docsResponse);
    const docs = Array.isArray(docsPayload.documents)
      ? docsPayload.documents.filter((item) => !!item && typeof item === "object")
      : [];
    if (docs.length === 0) {
      throw new Error("Select files to upload, or reuse a project that already has indexed documents.");
    }
    setStage("upload", "done", `Using ${docs.length} previously indexed document(s).`);
    return docs.length;
  }

  async function runWorkspacePipeline() {
    setRunStatus("loading");
    setRunError(null);
    setResult(null);
    setActivePane("requirements");
    setActiveSectionKey("");
    setActivityFeed([]);
    setExportView("preview");
    resetStages();

    let failedStage: StageId = "upload";

    try {
      const currentProjectId = await ensureProject();
      await saveIntakeContext(currentProjectId);
      const documentsIndexed = await ensureIndexedDocuments(currentProjectId);

      failedStage = "extract";
      setActivePane("requirements");
      setStage("extract", "running", "Extracting requirements...");
      const requirementsResponse = await fetch(`${apiBase}/projects/${currentProjectId}/extract-requirements`, {
        method: "POST",
      });
      const requirementsPayload = await parseJsonResponse(requirementsResponse);
      const requirements = (requirementsPayload.requirements as JsonValue) ?? null;
      const extraction = (requirementsPayload.extraction as JsonValue) ?? null;
      const questionPrompts = readQuestionPrompts(requirements);
      setStage("extract", "done", `Extracted ${questionPrompts.length} question(s).`);
      const sectionTargets = buildSectionTargets(questionPrompts);
      appendFeed(`Orchestrating ${sectionTargets.length} section(s).`);

      const sectionRuns: SectionRunResult[] = [];
      for (const [index, target] of sectionTargets.entries()) {
        const ordinal = `${index + 1}/${sectionTargets.length}`;
        appendFeed(`Section ${ordinal}: ${target.sectionKey}`);

        failedStage = "retrieve";
        setActivePane("retrieval");
        setStage("retrieve", "running", `Retrieving evidence for "${target.sectionKey}" (${ordinal})...`);
        const retrievalResponse = await fetch(`${apiBase}/projects/${currentProjectId}/retrieve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: target.prompt, top_k: 6 }),
        });
        const retrievalPayload = await parseJsonResponse(retrievalResponse);
        const retrieval = retrievalPayload as JsonValue;
        const retrievalCount = Array.isArray(retrievalPayload.results) ? retrievalPayload.results.length : 0;
        setStage("retrieve", "done", `Retrieved ${retrievalCount} evidence chunk(s) for ${target.sectionKey}.`);

        failedStage = "draft";
        setActivePane("draft");
        setStage("draft", "running", `Generating cited draft for "${target.sectionKey}" (${ordinal})...`);
        const draftResponse = await fetch(`${apiBase}/projects/${currentProjectId}/generate-section`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ section_key: target.sectionKey }),
        });
        const draftPayload = await parseJsonResponse(draftResponse);
        const draft = draftPayload.draft as JsonValue;
        const grounding = (draftPayload.grounding as JsonValue) ?? null;
        const draftRecord = asRecord(draft);
        const paragraphs = Array.isArray(draftRecord?.paragraphs) ? draftRecord.paragraphs.length : 0;
        setStage("draft", "done", `${target.sectionKey}: ${paragraphs} paragraph(s).`);

        failedStage = "coverage";
        setActivePane("coverage");
        setStage("coverage", "running", `Computing coverage for "${target.sectionKey}" (${ordinal})...`);
        const coverageResponse = await fetch(`${apiBase}/projects/${currentProjectId}/coverage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ section_key: target.sectionKey }),
        });
        const coveragePayload = await parseJsonResponse(coverageResponse);
        const coverage = coveragePayload.coverage as JsonValue;

        sectionRuns.push({
          sectionKey: target.sectionKey,
          prompt: target.prompt,
          retrieval,
          draft,
          coverage,
          grounding,
        });
      }

      failedStage = "export";
      setActivePane("export");
      setStage("export", "running", `Generating consolidated export for ${sectionRuns.length} section(s)...`);
      const exportResponse = await fetch(
        `${apiBase}/projects/${currentProjectId}/export?format=both&profile=submission&use_agent=false`
      );
      if (!exportResponse.ok) {
        const fallback = await exportResponse.text();
        throw new Error(fallback || `Export failed (${exportResponse.status})`);
      }
      const exportJson = (await exportResponse.json()) as JsonValue;
      const exportMarkdown = combineMarkdownFilesFromExport(exportJson);
      setStage("export", "done", `JSON + Markdown exports ready for all sections.`);

      const primarySection = sectionRuns[0];
      setResult({
        projectId: currentProjectId,
        sectionKey: primarySection?.sectionKey ?? "Need Statement",
        documentsIndexed,
        requirements,
        extraction,
        sectionRuns,
        retrieval: primarySection?.retrieval ?? null,
        draft: primarySection?.draft ?? null,
        coverage: primarySection?.coverage ?? null,
        exportJson,
        exportMarkdown,
      });
      setActiveSectionKey(primarySection?.sectionKey ?? "");
      setFiles([]);
      appendFeed("Run complete.");
      setRunStatus("success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Pipeline failed.";
      setStage(failedStage, "error", message);
      setRunError(message);
      setRunStatus("error");
      setActivePane(paneForStage[failedStage]);
    }
  }

  function addFiles(newFiles: File[]) {
    if (newFiles.length === 0) {
      return;
    }
    setFiles((prev) => [...prev, ...newFiles]);
    appendFeed(`Queued ${newFiles.length} file(s) for upload.`);
  }

  function handleFileSelection(fileList: FileList | null) {
    if (!fileList) {
      return;
    }
    addFiles(Array.from(fileList));
  }

  function handleFileDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragActive(false);
    addFiles(Array.from(event.dataTransfer.files));
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragActive(false);
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, current) => current !== index));
  }

  function downloadJson() {
    if (!result || !result.exportJson) {
      return;
    }
    const blob = new Blob([JSON.stringify(result.exportJson, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nebula-${result.projectId}-all-sections-export.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function downloadMarkdown() {
    if (!result || !result.exportMarkdown) {
      return;
    }
    const blob = new Blob([result.exportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nebula-${result.projectId}-all-sections-export.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  const sectionOptions = useMemo(() => {
    if (!result) {
      return [];
    }
    return result.sectionRuns.map((section) => section.sectionKey);
  }, [result]);

  const currentSectionRun = useMemo(() => {
    if (!result || result.sectionRuns.length === 0) {
      return null;
    }
    if (!activeSectionKey) {
      return result.sectionRuns[0];
    }
    return result.sectionRuns.find((section) => section.sectionKey === activeSectionKey) ?? result.sectionRuns[0];
  }, [result, activeSectionKey]);

  const coverageRequirementLabels = useMemo(
    () => buildCoverageRequirementLabelLookup(result?.requirements ?? null),
    [result]
  );

  const aggregatedCoverageRecord = useMemo(() => {
    if (!result) {
      return null;
    }
    const exportRecord = asRecord(result.exportJson);
    const bundleRecord = exportRecord ? asRecord((exportRecord.bundle as JsonValue) ?? null) : null;
    const bundleJsonRecord = bundleRecord ? asRecord((bundleRecord.json as JsonValue) ?? null) : null;
    return bundleJsonRecord ? asRecord((bundleJsonRecord.coverage as JsonValue) ?? null) : null;
  }, [result]);

  const activeCoverageRecord = aggregatedCoverageRecord ?? (currentSectionRun ? asRecord(currentSectionRun.coverage) : null);
  const coverageScopeLabel = aggregatedCoverageRecord ? "All generated sections" : currentSectionRun?.sectionKey ?? "Unknown";
  const coverageScopeRequirementNote = aggregatedCoverageRecord
    ? "extracted questions + required attachments (across all generated sections)"
    : "extracted questions + required attachments (for this section)";

  const requirementsSummary = useMemo(() => {
    if (!result) {
      return "";
    }
    const requirementsRecord = asRecord(result.requirements);
    const extractionRecord = asRecord(result.extraction);
    if (!requirementsRecord) {
      return "";
    }

    const funder = asString(requirementsRecord.funder) ?? "Unknown";
    const deadline = asString(requirementsRecord.deadline) ?? "Not specified";

    const questionEntries = Array.isArray(requirementsRecord.questions) ? requirementsRecord.questions : [];
    const questionMap = new Map<string, { prompt: string; limit: string | null; order: number; score: number }>();
    for (const [index, question] of questionEntries.entries()) {
      let prompt: string | null = null;
      let limit: string | null = null;
      if (typeof question === "string") {
        prompt = asString(question);
      } else if (question && typeof question === "object") {
        const record = question as Record<string, unknown>;
        prompt = asString(record.prompt);
        limit = questionLimitLabel(record);
      }
      if (!prompt) {
        continue;
      }
      const key = questionPromptKey(prompt) || normalizeLooseText(prompt);
      const score = questionPromptScore(prompt);
      const existing = questionMap.get(key);
      if (!existing || score > existing.score) {
        questionMap.set(key, { prompt, limit, order: existing?.order ?? index, score });
      }
    }
    const questions = Array.from(questionMap.values())
      .sort((left, right) => left.order - right.order)
      .map((item) => item);

    const eligibility = cleanListEntries(requirementsRecord.eligibility, ["eligibility"]);
    const requiredAttachments = cleanListEntries(requirementsRecord.required_attachments, [
      "required attachments",
      "attachments",
    ]);
    const rubric = cleanListEntries(requirementsRecord.rubric, ["rubric", "rubric and scoring criteria"]);
    const disallowedCosts = cleanListEntries(requirementsRecord.disallowed_costs, ["disallowed costs", "ineligible costs"]);

    const lines: string[] = [];
    lines.push("## Requirements");
    lines.push(`- **Funder:** ${funder}`);
    lines.push(`- **Deadline:** ${deadline}`);
    if (asString(extractionRecord?.mode)) {
      lines.push(`- **Extraction mode:** ${asString(extractionRecord?.mode)}`);
    }
    lines.push(`- **Questions extracted:** ${questions.length}`);

    lines.push("");
    lines.push("### Questions");
    if (questions.length === 0) {
      lines.push("- No questions extracted.");
    } else {
      for (const [index, question] of questions.entries()) {
        const suffix = question.limit ? ` _(limit: ${question.limit})_` : "";
        lines.push(`${index + 1}. ${question.prompt}${suffix}`);
      }
    }

    lines.push("");
    lines.push("### Eligibility");
    if (eligibility.length === 0) {
      lines.push("- Not specified.");
    } else {
      for (const item of eligibility) {
        lines.push(`- ${item}`);
      }
    }

    lines.push("");
    lines.push("### Required Attachments");
    if (requiredAttachments.length === 0) {
      lines.push("- Not specified.");
    } else {
      for (const item of requiredAttachments) {
        lines.push(`- ${item}`);
      }
    }

    lines.push("");
    lines.push("### Disallowed Costs");
    if (disallowedCosts.length === 0) {
      lines.push("- Not specified.");
    } else {
      for (const item of disallowedCosts) {
        lines.push(`- ${item}`);
      }
    }

    lines.push("");
    lines.push("### Rubric");
    if (rubric.length === 0) {
      lines.push("- Not specified.");
    } else {
      for (const item of rubric) {
        lines.push(`- ${item}`);
      }
    }

    return lines.join("\n");
  }, [result]);

  const retrievalSummary = useMemo(() => {
    if (!result) {
      return "";
    }
    const retrievalRecord = currentSectionRun ? asRecord(currentSectionRun.retrieval) : null;
    if (!retrievalRecord) {
      return "";
    }

    const query = asString(retrievalRecord.query) ?? "Unknown";
    const results = Array.isArray(retrievalRecord.results) ? retrievalRecord.results : [];
    const lines: string[] = [];

    lines.push("## Retrieval");
    lines.push(`- **Section:** ${currentSectionRun?.sectionKey ?? "Unknown"}`);
    lines.push(`- **Query:** ${query}`);
    lines.push(`- **Evidence chunks:** ${results.length}`);
    lines.push("");
    lines.push("### Evidence");

    if (results.length === 0) {
      lines.push("- No retrieval results.");
      return lines.join("\n");
    }

    for (const [index, item] of results.entries()) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const row = item as Record<string, unknown>;
      const fileName = asString(row.file_name) ?? "unknown";
      const page = typeof row.page === "number" ? String(row.page) : "?";
      const score = typeof row.score === "number" ? row.score.toFixed(3) : "n/a";
      const snippet = asString(row.snippet);
      lines.push(`${index + 1}. **${fileName}** (page ${page}, score ${score})`);
      if (snippet) {
        lines.push(snippet.length > 220 ? `${snippet.slice(0, 217)}...` : snippet);
      }
    }
    return lines.join("\n");
  }, [result, currentSectionRun]);

  const draftSummary = useMemo(() => {
    if (!result) {
      return "";
    }
    const draftRecord = currentSectionRun ? asRecord(currentSectionRun.draft) : null;
    if (!draftRecord) {
      return "";
    }

    const section = asString(draftRecord.section_key) ?? "Unknown";
    const paragraphs = Array.isArray(draftRecord.paragraphs) ? draftRecord.paragraphs : [];
    const missingEvidence = Array.isArray(draftRecord.missing_evidence) ? draftRecord.missing_evidence : [];
    const groundingRecord = currentSectionRun ? asRecord(currentSectionRun.grounding) : null;

    let citations = 0;
    let paragraphsWithCitations = 0;
    const lines: string[] = [];
    lines.push("## Draft");
    lines.push(`- **Section:** ${section}`);
    lines.push(`- **Paragraphs:** ${paragraphs.length}`);

    for (const paragraph of paragraphs) {
      if (!paragraph || typeof paragraph !== "object") {
        continue;
      }
      const citationsList = (paragraph as Record<string, unknown>).citations;
      const count = Array.isArray(citationsList) ? citationsList.length : 0;
      citations += count;
      if (count > 0) {
        paragraphsWithCitations += 1;
      }
    }
    lines.push(`- **Citations:** ${citations}`);
    lines.push(`- **Paragraphs with citations:** ${paragraphsWithCitations}/${paragraphs.length}`);
    if (groundingRecord) {
      const inlineParsed =
        typeof groundingRecord.inline_citations_parsed === "number" ? groundingRecord.inline_citations_parsed : 0;
      const fallbackAdded =
        typeof groundingRecord.fallback_citations_added === "number" ? groundingRecord.fallback_citations_added : 0;
      lines.push(`- **Grounding parser citations:** ${inlineParsed}`);
      lines.push(`- **Fallback citations added:** ${fallbackAdded}`);
    }
    lines.push(`- **Missing evidence items:** ${missingEvidence.length}`);
    lines.push("");
    lines.push("### Paragraph previews");

    if (paragraphs.length === 0) {
      lines.push("- No generated paragraphs.");
      return lines.join("\n");
    }

    for (const [index, paragraph] of paragraphs.entries()) {
      if (!paragraph || typeof paragraph !== "object") {
        continue;
      }
      const row = paragraph as Record<string, unknown>;
      const text = asString(row.text) ?? "";
      const preview = text.length > 320 ? `${text.slice(0, 317)}...` : text;
      const citationsList = Array.isArray(row.citations) ? row.citations : [];
      lines.push(`- **Paragraph ${index + 1}** (${citationsList.length} citation${citationsList.length === 1 ? "" : "s"})`);
      if (preview) {
        lines.push(preview);
      }
    }

    if (missingEvidence.length > 0) {
      lines.push("");
      lines.push("### Missing evidence notes");
      for (const entry of missingEvidence) {
        const text = asString(entry);
        if (text) {
          lines.push(`- ${text}`);
        }
      }
    }

    return lines.join("\n");
  }, [result, currentSectionRun]);

  const coverageSummary = useMemo(() => {
    if (!result) {
      return "";
    }
    if (!activeCoverageRecord) {
      return "";
    }

    const items = Array.isArray(activeCoverageRecord.items) ? activeCoverageRecord.items : [];
    let met = 0;
    let partial = 0;
    let missing = 0;
    const lines: string[] = [];

    for (const item of items) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const status = toCoverageStatus((item as Record<string, unknown>).status);
      if (status === "met") {
        met += 1;
      } else if (status === "partial") {
        partial += 1;
      } else if (status === "missing") {
        missing += 1;
      }
    }

    lines.push("## Coverage");
    lines.push(`- **Scope:** ${coverageScopeLabel}`);
    lines.push(`- **Coverage items:** ${items.length}`);
    lines.push(`- **Requirement scope:** ${coverageScopeRequirementNote}`);
    lines.push(`- **Met:** ${met}`);
    lines.push(`- **Partial:** ${partial}`);
    lines.push(`- **Missing:** ${missing}`);
    lines.push("- **Detailed notes:** see grouped requirement details below.");

    return lines.join("\n");
  }, [result, activeCoverageRecord, coverageScopeLabel, coverageScopeRequirementNote]);

  const coverageScore = useMemo(() => {
    if (!activeCoverageRecord) {
      return null;
    }
    const items = Array.isArray(activeCoverageRecord.items) ? activeCoverageRecord.items : [];
    let total = 0;
    let met = 0;
    let partial = 0;
    let missing = 0;

    let questionTotal = 0;
    let questionMet = 0;
    let attachmentTotal = 0;
    let attachmentMet = 0;

    for (const item of items) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const row = item as Record<string, unknown>;
      const status = toCoverageStatus(row.status);
      if (status === "na") {
        continue;
      }
      const requirementId = asString(row.requirement_id) ?? "";
      const isQuestion = /^Q\d+$/i.test(requirementId);
      const isAttachment = /^A\d+$/i.test(requirementId);

      total += 1;
      if (status === "met") {
        met += 1;
      } else if (status === "partial") {
        partial += 1;
      } else {
        missing += 1;
      }

      if (isQuestion) {
        questionTotal += 1;
        if (status === "met") {
          questionMet += 1;
        }
      } else if (isAttachment) {
        attachmentTotal += 1;
        if (status === "met") {
          attachmentMet += 1;
        }
      }
    }

    const readinessPct = total > 0 ? ((met + partial * 0.5) / total) * 100 : 0;
    const completionPct = total > 0 ? (met / total) * 100 : 0;
    const questionPct = questionTotal > 0 ? (questionMet / questionTotal) * 100 : 0;
    const attachmentPct = attachmentTotal > 0 ? (attachmentMet / attachmentTotal) * 100 : 0;

    return {
      total,
      met,
      partial,
      missing,
      readinessPct,
      completionPct,
      questionTotal,
      questionMet,
      questionPct,
      attachmentTotal,
      attachmentMet,
      attachmentPct,
    };
  }, [activeCoverageRecord]);

  const coverageDetails = useMemo(() => {
    if (!activeCoverageRecord) {
      return [];
    }
    const items = Array.isArray(activeCoverageRecord.items) ? activeCoverageRecord.items : [];

    const grouped: Record<"questions" | "attachments" | "other", CoverageDetailItem[]> = {
      questions: [],
      attachments: [],
      other: [],
    };

    for (const item of items) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const row = item as Record<string, unknown>;
      const requirementId = asString(row.requirement_id) ?? "";
      const label = asString(row.requirement) ?? resolveCoverageRequirementLabel(requirementId, coverageRequirementLabels);
      const status = toCoverageStatus(row.status);
      if (status === "na") {
        continue;
      }
      const detail: CoverageDetailItem = {
        requirementId,
        label,
        status,
        notes: asString(row.notes) ?? "No coverage note available.",
      };
      if (/^Q\d+$/i.test(requirementId)) {
        grouped.questions.push(detail);
      } else if (/^A\d+$/i.test(requirementId)) {
        grouped.attachments.push(detail);
      } else {
        grouped.other.push(detail);
      }
    }

    const describeGroup = (key: "questions" | "attachments" | "other", title: string) => {
      const detailItems = grouped[key].sort((left, right) => left.requirementId.localeCompare(right.requirementId));
      const met = detailItems.filter((item) => item.status === "met").length;
      const partial = detailItems.filter((item) => item.status === "partial").length;
      const missing = detailItems.filter((item) => item.status === "missing").length;
      return { key, title, items: detailItems, met, partial, missing };
    };

    return [
      describeGroup("questions", "Questions"),
      describeGroup("attachments", "Attachments"),
      describeGroup("other", "Other Requirement IDs"),
    ].filter((group) => group.items.length > 0);
  }, [activeCoverageRecord, coverageRequirementLabels]);

  const exportHeading = useMemo(() => {
    if (!result) {
      return { title: "Export", subtitle: "" };
    }
    const exportRecord = asRecord(result.exportJson);
    const projectRecord = exportRecord ? asRecord((exportRecord.project as JsonValue) ?? null) : null;
    const bundleRecord = exportRecord ? asRecord((exportRecord.bundle as JsonValue) ?? null) : null;
    const bundleJsonRecord = bundleRecord ? asRecord((bundleRecord.json as JsonValue) ?? null) : null;
    const intakeRecord = bundleJsonRecord ? asRecord((bundleJsonRecord.intake as JsonValue) ?? null) : null;

    const title = asString(projectRecord?.name) ?? projectName ?? "Export";
    const country = asString(intakeRecord?.country) ?? asString(intake.country) ?? "";
    return {
      title,
      subtitle: country ? `Country: ${country}` : "",
    };
  }, [result, projectName, intake.country]);

  if (!showWorkspace) {
    return (
      <main className="nebula-landing">
        <div className="landing-grid" aria-hidden="true" />
        <section className="landing-shell">
          <article className="landing-hero">
            <div className="landing-gradient" aria-hidden="true" />
            <div className="landing-brand-inline">
              <img src="/icon.svg" alt="Nebula icon" className="landing-logo" />
              <h1 className="brand-wordmark">Nebula</h1>
            </div>
            <p>Automated grant drafting workspace powered by Amazon Nova.</p>
            <button type="button" className="workspace-enter" onClick={() => setShowWorkspace(true)}>
              Enter Workspace
            </button>
          </article>
        </section>
      </main>
    );
  }

  return (
    <main className="workspace-main">
      <section className="workspace-header-line">
        <img src="/icon.svg" alt="Nebula icon" className="title-icon" />
        <div className="workspace-heading-inline">
          <h1 className="brand-wordmark">Nebula</h1>
          <span className="workspace-tagline">AI-Powered Draft Generation Workspace</span>
        </div>
      </section>

      <div className="workspace-grid">
        <aside className="workspace-left">
          <section className="control-panel">
            <div className="field">
              <label htmlFor="project-name">Project Name</label>
              <input
                id="project-name"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="Project name"
                className="input"
              />
            </div>

            <div className="form-grid">
              <div className="field">
                <label htmlFor="country">Country</label>
                <input
                  id="country"
                  value={intake.country}
                  onChange={(e) => setIntake((prev) => ({ ...prev, country: e.target.value }))}
                  placeholder="e.g., Ireland"
                  className="input"
                />
              </div>
              <div className="field">
                <label htmlFor="org-type">Organization Type</label>
                <input
                  id="org-type"
                  value={intake.organization_type}
                  onChange={(e) => setIntake((prev) => ({ ...prev, organization_type: e.target.value }))}
                  placeholder="e.g., Non-profit"
                  className="input"
                />
              </div>
              <div className="field">
                <label htmlFor="funder-track">Funder Track</label>
                <input
                  id="funder-track"
                  value={intake.funder_track}
                  onChange={(e) => setIntake((prev) => ({ ...prev, funder_track: e.target.value }))}
                  placeholder="e.g., community-foundation"
                  className="input"
                />
              </div>
              <div className="field">
                <label htmlFor="funding-goal">Funding Goal</label>
                <input
                  id="funding-goal"
                  value={intake.funding_goal}
                  onChange={(e) => setIntake((prev) => ({ ...prev, funding_goal: e.target.value }))}
                  placeholder="e.g., project"
                  className="input"
                />
              </div>
              <div className="field">
                <label htmlFor="sector-focus">Sector Focus</label>
                <input
                  id="sector-focus"
                  value={intake.sector_focus}
                  onChange={(e) => setIntake((prev) => ({ ...prev, sector_focus: e.target.value }))}
                  placeholder="e.g., youth employment"
                  className="input"
                />
              </div>
            </div>

            <div className="field">
              <label htmlFor="docs-upload">Documents</label>
              <div
                className={`dropzone ${isDragActive ? "active" : ""}`}
                onDrop={handleFileDrop}
                onDragOver={handleDragOver}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
              >
                <input
                  id="docs-upload"
                  type="file"
                  multiple
                  onChange={(e) => handleFileSelection(e.target.files)}
                  className="dropzone-input"
                />
                <label htmlFor="docs-upload" className="dropzone-content">
                  <strong>Drop documents here</strong>
                  <span>or click to browse files</span>
                </label>
              </div>
            </div>

            {files.length > 0 ? (
              <div className="file-list">
                {files.map((file, index) => (
                  <div key={`${file.name}-${index}`} className="file-item">
                    <span>{file.name}</span>
                    <button type="button" className="chip-button" onClick={() => removeFile(index)} disabled={isRunning}>
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="hint">No new files selected. Nebula will reuse indexed files if this project already has them.</p>
            )}

            <button type="button" className="primary-button" onClick={runWorkspacePipeline} disabled={isRunning}>
              {isRunning ? "Generating..." : "Generate All Sections"}
            </button>

            <div className="meta-row">
              <span>Current Project ID:</span>
              <code>{projectId || "not created yet"}</code>
            </div>
            {result ? (
              <div className="meta-row">
                <span>Last Run:</span>
                <code>{result.projectId}</code>
              </div>
            ) : null}
          </section>
        </aside>

        <section className="workspace-right">
          <section className="workspace-output">
            {isRunning ? (
              <section className="thinking-stream">
                <div className="chat-lines">
                  {activityFeed.map((line, index) => (
                    <p key={`${line}-${index}`} className={`chat-line ${workflowStepLabelSet.has(line) ? "thinking" : ""}`}>
                      {line}
                    </p>
                  ))}
                  <p className="chat-line thinking live">
                    <span className="typing-dot" />
                    Nebulating...
                  </p>
                </div>
              </section>
            ) : null}

            {!isRunning && !result && runStatus !== "error" ? (
              <section className="idle-state">
                <svg
                  className="idle-icon"
                  viewBox="0 0 24 24"
                  role="img"
                  aria-label="Magnifier icon"
                >
                  <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
                  <path d="M16.5 16.5L21 21" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
                <p>Waiting for input data...</p>
              </section>
            ) : null}

            {!isRunning && result ? (
              <div className="result-shell">
                <section className="pane-tabs">
                  {paneTabs.map((tab) => {
                    const active = activePane === tab.key;
                    return (
                      <button
                        key={tab.key}
                        type="button"
                        className={`pane-tab ${active ? "active" : ""}`}
                        onClick={() => setActivePane(tab.key)}
                      >
                        {tab.label}
                      </button>
                    );
                  })}
                </section>

                <section className="pane-body">
                  {activePane === "requirements" ? (
                    <>
                      <h3>Requirements</h3>
                      <SegmentedToggle
                        label="View mode"
                        value={requirementsView}
                        onChange={(value) => setRequirementsView(value as ViewMode)}
                        options={[
                          { value: "summary", label: "Summary" },
                          { value: "json", label: "JSON" },
                        ]}
                      />
                      {requirementsView === "summary" ? (
                        <MarkdownViewer content={requirementsSummary} emptyMessage="No requirements generated." />
                      ) : (
                        <pre className="code-block">{JSON.stringify(result.requirements, null, 2)}</pre>
                      )}
                    </>
                  ) : null}

                  {activePane === "retrieval" ? (
                    <>
                      <h3>Retrieval</h3>
                      {sectionOptions.length > 1 ? (
                        <div className="field">
                          <label htmlFor="section-picker-retrieval">Section</label>
                          <select
                            id="section-picker-retrieval"
                            className="input"
                            value={currentSectionRun?.sectionKey ?? ""}
                            onChange={(e) => setActiveSectionKey(e.target.value)}
                          >
                            {sectionOptions.map((sectionKey) => (
                              <option key={sectionKey} value={sectionKey}>
                                {sectionKey}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                      <SegmentedToggle
                        label="View mode"
                        value={retrievalView}
                        onChange={(value) => setRetrievalView(value as ViewMode)}
                        options={[
                          { value: "summary", label: "Summary" },
                          { value: "json", label: "JSON" },
                        ]}
                      />
                      {retrievalView === "summary" ? (
                        <MarkdownViewer content={retrievalSummary} emptyMessage="No retrieval results." />
                      ) : (
                        <pre className="code-block">{JSON.stringify(currentSectionRun?.retrieval ?? null, null, 2)}</pre>
                      )}
                    </>
                  ) : null}

                  {activePane === "draft" ? (
                    <>
                      <h3>Draft</h3>
                      {sectionOptions.length > 1 ? (
                        <div className="field">
                          <label htmlFor="section-picker-draft">Section</label>
                          <select
                            id="section-picker-draft"
                            className="input"
                            value={currentSectionRun?.sectionKey ?? ""}
                            onChange={(e) => setActiveSectionKey(e.target.value)}
                          >
                            {sectionOptions.map((sectionKey) => (
                              <option key={sectionKey} value={sectionKey}>
                                {sectionKey}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                      <SegmentedToggle
                        label="View mode"
                        value={draftView}
                        onChange={(value) => setDraftView(value as ViewMode)}
                        options={[
                          { value: "summary", label: "Summary" },
                          { value: "json", label: "JSON" },
                        ]}
                      />
                      {draftView === "summary" ? (
                        <MarkdownViewer content={draftSummary} emptyMessage="No draft generated." />
                      ) : (
                        <pre className="code-block">{JSON.stringify(currentSectionRun?.draft ?? null, null, 2)}</pre>
                      )}
                    </>
                  ) : null}

                  {activePane === "coverage" ? (
                    <>
                      <h3>Coverage</h3>
                      {sectionOptions.length > 1 ? (
                        <div className="field">
                          <label htmlFor="section-picker-coverage">Section</label>
                          <select
                            id="section-picker-coverage"
                            className="input"
                            value={currentSectionRun?.sectionKey ?? ""}
                            onChange={(e) => setActiveSectionKey(e.target.value)}
                          >
                            {sectionOptions.map((sectionKey) => (
                              <option key={sectionKey} value={sectionKey}>
                                {sectionKey}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                      <SegmentedToggle
                        label="View mode"
                        value={coverageView}
                        onChange={(value) => setCoverageView(value as ViewMode)}
                        options={[
                          { value: "summary", label: "Summary" },
                          { value: "json", label: "JSON" },
                        ]}
                      />
                      {coverageView === "summary" ? (
                        <>
                          {coverageScore ? (
                            <section className="coverage-score-block">
                              <h4>Coverage Score</h4>
                              <p className="hint">
                                Evaluates this selected section against extracted question and required attachment requirements.
                              </p>
                              <div className="coverage-score-grid">
                                <article className="coverage-score-card">
                                  <span>Readiness</span>
                                  <strong>{coverageScore.readinessPct.toFixed(1)}%</strong>
                                  <small>met + 0.5*partial</small>
                                </article>
                                <article className="coverage-score-card">
                                  <span>Completion</span>
                                  <strong>{coverageScore.completionPct.toFixed(1)}%</strong>
                                  <small>met only</small>
                                </article>
                                <article className="coverage-score-card">
                                  <span>Questions met</span>
                                  <strong>
                                    {coverageScore.questionMet}/{coverageScore.questionTotal}
                                  </strong>
                                  <small>{coverageScore.questionPct.toFixed(1)}%</small>
                                </article>
                                <article className="coverage-score-card">
                                  <span>Attachments met</span>
                                  <strong>
                                    {coverageScore.attachmentMet}/{coverageScore.attachmentTotal}
                                  </strong>
                                  <small>{coverageScore.attachmentPct.toFixed(1)}%</small>
                                </article>
                              </div>
                              <div className="coverage-status-bar" role="img" aria-label="Coverage status distribution">
                                <span
                                  className="segment status-met"
                                  style={{
                                    width: `${coverageScore.total > 0 ? (coverageScore.met / coverageScore.total) * 100 : 0}%`,
                                  }}
                                  title={`Met: ${coverageScore.met}`}
                                />
                                <span
                                  className="segment status-partial"
                                  style={{
                                    width: `${coverageScore.total > 0 ? (coverageScore.partial / coverageScore.total) * 100 : 0}%`,
                                  }}
                                  title={`Partial: ${coverageScore.partial}`}
                                />
                                <span
                                  className="segment status-missing"
                                  style={{
                                    width: `${coverageScore.total > 0 ? (coverageScore.missing / coverageScore.total) * 100 : 0}%`,
                                  }}
                                  title={`Missing: ${coverageScore.missing}`}
                                />
                              </div>
                              <div className="coverage-status-legend">
                                <span>
                                  <i className="dot status-met" /> Met ({coverageScore.met})
                                </span>
                                <span>
                                  <i className="dot status-partial" /> Partial ({coverageScore.partial})
                                </span>
                                <span>
                                  <i className="dot status-missing" /> Missing ({coverageScore.missing})
                                </span>
                              </div>
                            </section>
                          ) : null}
                          <MarkdownViewer content={coverageSummary} emptyMessage="No coverage generated." />
                          {coverageDetails.length > 0 ? (
                            <section className="coverage-details-block">
                              <h4>Requirement Details</h4>
                              {coverageDetails.map((group, index) => (
                                <details key={group.key} className="coverage-detail-group" open={index === 0}>
                                  <summary>
                                    {group.title} ({group.items.length}) · Met {group.met} · Partial {group.partial} · Missing{" "}
                                    {group.missing}
                                  </summary>
                                  <div className="coverage-detail-list">
                                    {group.items.map((item) => (
                                      <article key={`${group.key}-${item.requirementId}-${item.label}`} className="coverage-detail-item">
                                        <p className="coverage-detail-title">
                                          <span className={`coverage-status-pill status-${item.status}`}>
                                            {item.status.toUpperCase()}
                                          </span>
                                          <span>{item.label}</span>
                                          {item.requirementId ? <code>{item.requirementId}</code> : null}
                                        </p>
                                        <p className="coverage-detail-notes">{item.notes}</p>
                                      </article>
                                    ))}
                                  </div>
                                </details>
                              ))}
                            </section>
                          ) : null}
                        </>
                      ) : (
                        <pre className="code-block">
                          {JSON.stringify(activeCoverageRecord ?? currentSectionRun?.coverage ?? null, null, 2)}
                        </pre>
                      )}
                    </>
                  ) : null}

                  {activePane === "export" ? (
                    <>
                      <h3>Export</h3>
                      <section className="export-heading-inline">
                        <h4>{exportHeading.title}</h4>
                        {exportHeading.subtitle ? <p>{exportHeading.subtitle}</p> : null}
                      </section>
                      <div className="action-row">
                        <button type="button" className="primary-button" onClick={downloadJson}>
                          Download JSON
                        </button>
                        <button type="button" className="secondary-button" onClick={downloadMarkdown}>
                          Download Markdown
                        </button>
                      </div>
                      <SegmentedToggle
                        label="Export view"
                        value={exportView}
                        onChange={(value) => setExportView(value as ExportViewMode)}
                        options={[
                          { value: "preview", label: "Markdown Preview" },
                          { value: "markdown", label: "Raw Markdown" },
                          { value: "json", label: "JSON" },
                        ]}
                      />
                      {exportView === "preview" ? (
                        <MarkdownViewer
                          content={result?.exportMarkdown ?? ""}
                          emptyMessage="No markdown export available."
                        />
                      ) : null}
                      {exportView === "markdown" ? (
                        <pre className="code-block">{result?.exportMarkdown ?? ""}</pre>
                      ) : null}
                      {exportView === "json" ? (
                        <pre className="code-block">{JSON.stringify(result?.exportJson ?? null, null, 2)}</pre>
                      ) : null}
                    </>
                  ) : null}
                </section>
              </div>
            ) : null}

            {runStatus === "error" ? <p className="error-text">{runError ?? "Pipeline failed."}</p> : null}
          </section>
        </section>
      </div>
    </main>
  );
}
