"use client";

import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;
type RunStatus = "idle" | "loading" | "success" | "error";

type PipelineRunResult = {
  projectId: string;
  documentsIndexed: number;
  requirements: JsonValue | null;
  extraction: JsonValue | null;
  sectionRuns: JsonValue[];
  coverage: JsonValue | null;
  unresolvedGaps: JsonValue[];
  exportJson: JsonValue;
  exportMarkdown: string;
};

const outputCards = [
  "Clear Requirements",
  "Citation-Backed Draft Sections",
  "Coverage Matrix",
  "Missing Evidence Flags",
];

const trustSignals = [
  "Grounded in uploaded source files",
  "Coverage checks before final review",
  "Single export package for submission",
];

function asRecord(value: JsonValue): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function formatDisplayDate(value: string | null | undefined): string {
  const parsed = value ? new Date(value) : new Date();
  if (Number.isNaN(parsed.getTime())) {
    return new Date().toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
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

function combineMarkdownFilesFromExport(exportPayload: JsonValue | null): string {
  const exportRecord = asRecord(exportPayload);
  const projectRecord = exportRecord ? asRecord((exportRecord.project as JsonValue) ?? null) : null;
  const bundleRecord = exportRecord ? asRecord((exportRecord.bundle as JsonValue) ?? null) : null;
  const markdownRecord = bundleRecord ? asRecord((bundleRecord.markdown as JsonValue) ?? null) : null;
  const files = Array.isArray(markdownRecord?.files) ? markdownRecord.files : [];

  const cleanBlock = (content: string): string => {
    let cleaned = content;
    cleaned = cleaned.replace(/\n### Unsupported \/ Missing\s*\n- None\s*(?=\n|$)/g, "\n");
    cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
    return cleaned.trim();
  };

  const blocks: string[] = [];
  for (const file of files) {
    if (!file || typeof file !== "object") {
      continue;
    }
    const row = file as Record<string, unknown>;
    const content = asString(row.content) ?? "";
    if (!content) {
      continue;
    }
    const cleaned = cleanBlock(content);
    if (cleaned) {
      blocks.push(cleaned);
    }
  }

  const projectName = asString(projectRecord?.name) ?? "Project";
  const generatedAt = asString(exportRecord?.generated_at);
  const preface = [`# ${projectName}`, `## Date: ${formatDisplayDate(generatedAt)}`].join("\n");
  const body = blocks.join("\n\n---\n\n").trim();

  return body ? `${preface}\n\n---\n\n${body}` : preface;
}

export default function HomePage() {
  const [showWorkspace, setShowWorkspace] = useState(false);

  const [projectName, setProjectName] = useState("Nebula Grant Draft");
  const [contextBrief, setContextBrief] = useState("");
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);

  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [runLog, setRunLog] = useState<string[]>([]);
  const [result, setResult] = useState<PipelineRunResult | null>(null);
  const [copyState, setCopyState] = useState<"copy" | "copied" | "failed">("copy");

  const isRunning = runStatus === "loading";
  const storyCardRefs = useRef<Array<HTMLElement | null>>([]);
  const [visibleStoryCards, setVisibleStoryCards] = useState<Record<number, boolean>>({});

  useEffect(() => {
    if (showWorkspace) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }
          const raw = entry.target.getAttribute("data-card-index");
          const index = raw ? Number.parseInt(raw, 10) : Number.NaN;
          if (Number.isNaN(index)) {
            return;
          }
          setVisibleStoryCards((prev) => (prev[index] ? prev : { ...prev, [index]: true }));
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.55 }
    );

    storyCardRefs.current.forEach((element) => {
      if (element) {
        observer.observe(element);
      }
    });

    return () => observer.disconnect();
  }, [showWorkspace]);

  function appendLog(message: string) {
    setRunLog((prev) => [...prev, message]);
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

  async function ensureIndexedDocuments(currentProjectId: string): Promise<number> {
    if (files.length > 0) {
      appendLog("Uploading selected documents...");
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
      appendLog(`Indexed ${uploadedDocs.length} uploaded file(s).`);
      return uploadedDocs.length;
    }

    appendLog("Checking existing indexed documents...");
    const docsResponse = await fetch(`${apiBase}/projects/${currentProjectId}/documents`);
    const docsPayload = await parseJsonResponse(docsResponse);
    const docs = Array.isArray(docsPayload.documents)
      ? docsPayload.documents.filter((item) => !!item && typeof item === "object")
      : [];
    if (docs.length === 0) {
      throw new Error("Select files to upload, or reuse a project that already has indexed documents.");
    }
    appendLog(`Using ${docs.length} previously indexed document(s).`);
    return docs.length;
  }

  async function runWorkspacePipeline() {
    setRunStatus("loading");
    setRunError(null);
    setResult(null);
    setCopyState("copy");
    setRunLog([]);

    try {
      const currentProjectId = await ensureProject();
      appendLog(`Project ready: ${currentProjectId}`);

      const documentsIndexed = await ensureIndexedDocuments(currentProjectId);
      appendLog("Running complete Nova workflow...");
      const requestPayload: Record<string, unknown> = { top_k: 6, max_revision_rounds: 1 };
      const trimmedContext = contextBrief.trim();
      if (trimmedContext) {
        requestPayload.context_brief = trimmedContext;
      }

      const runResponse = await fetch(
        `${apiBase}/projects/${currentProjectId}/generate-full-draft?profile=submission`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestPayload),
        }
      );
      const runPayload = await parseJsonResponse(runResponse);

      const exportJson = (runPayload.export as JsonValue) ?? null;
      const exportMarkdown = combineMarkdownFilesFromExport(exportJson);
      const sectionRuns = Array.isArray(runPayload.section_runs)
        ? (runPayload.section_runs as JsonValue[])
        : [];
      const unresolvedGaps = Array.isArray(runPayload.unresolved_gaps)
        ? (runPayload.unresolved_gaps as JsonValue[])
        : [];

      setResult({
        projectId: currentProjectId,
        documentsIndexed,
        requirements: (runPayload.requirements as JsonValue) ?? null,
        extraction: (runPayload.extraction as JsonValue) ?? null,
        sectionRuns,
        coverage: (runPayload.coverage as JsonValue) ?? null,
        unresolvedGaps,
        exportJson,
        exportMarkdown,
      });

      setFiles([]);
      appendLog(`Completed ${sectionRuns.length} section(s).`);
      if (unresolvedGaps.length > 0) {
        appendLog(`${unresolvedGaps.length} unresolved gap(s) flagged.`);
      }
      setRunStatus("success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Pipeline failed.";
      setRunError(message);
      appendLog(message);
      setRunStatus("error");
    }
  }

  async function copyMarkdown() {
    if (!result?.exportMarkdown) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.exportMarkdown);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("copy"), 1800);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("copy"), 1800);
    }
  }

  function downloadMarkdown() {
    if (!result?.exportMarkdown) {
      return;
    }
    const blob = new Blob([result.exportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nebula-${result.projectId}-export.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function addFiles(newFiles: File[]) {
    if (newFiles.length === 0) {
      return;
    }
    setFiles((prev) => [...prev, ...newFiles]);
    appendLog(`Queued ${newFiles.length} file(s) for upload.`);
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

  const exportHeading = useMemo(() => {
    if (!result) {
      return { title: "Complete Draft Preview", date: "" };
    }

    const exportRecord = asRecord(result.exportJson);
    const projectRecord = exportRecord ? asRecord((exportRecord.project as JsonValue) ?? null) : null;
    const title = asString(projectRecord?.name) ?? projectName ?? "Complete Draft Preview";
    const generatedAt = asString(exportRecord?.generated_at);
    return {
      title,
      date: formatDisplayDate(generatedAt),
    };
  }, [result, projectName]);

  const runStats = useMemo(() => {
    if (!result) {
      return [] as Array<{ label: string; value: string }>;
    }

    const exportRecord = asRecord(result.exportJson);
    const summaryRecord = exportRecord ? asRecord((exportRecord.summary as JsonValue) ?? null) : null;
    const completion = asString(summaryRecord?.overall_completion) ?? "unknown";

    return [
      { label: "Documents", value: String(result.documentsIndexed) },
      { label: "Sections", value: String(result.sectionRuns.length) },
      { label: "Unresolved gaps", value: String(result.unresolvedGaps.length) },
      { label: "Completion", value: completion },
    ];
  }, [result]);

  if (!showWorkspace) {
    return (
      <main className="nebula-landing">
        <div className="landing-grid" aria-hidden="true" />
        <section className="landing-shell">
          <article className="landing-hero">
            <div className="landing-brand-inline">
              <img src="/icon.svg" alt="Nebula icon" className="landing-logo" />
              <h1 className="brand-wordmark">Nebula</h1>
            </div>
            <p className="landing-kicker">Amazon Nova-powered proposal workflow</p>
          </article>

          <section id="landing-story" className="landing-story">
            <article
              ref={(node) => {
                storyCardRefs.current[0] = node;
              }}
              data-card-index={0}
              className={`story-card ${visibleStoryCards[0] ? "is-visible" : ""}`}
            >
              <h2 className="story-card-title">From source files to submission-ready grant</h2>
            </article>

            <article
              ref={(node) => {
                storyCardRefs.current[1] = node;
              }}
              data-card-index={1}
              className={`story-card ${visibleStoryCards[1] ? "is-visible" : ""}`}
            >
              <h2 className="story-card-title">How Nebula Runs</h2>
              <img src="/LANDING.png" alt="Nebula workflow graph" className="landing-flow-image" />
            </article>

            <article
              ref={(node) => {
                storyCardRefs.current[2] = node;
              }}
              data-card-index={2}
              className={`story-card ${visibleStoryCards[2] ? "is-visible" : ""}`}
            >
              <h2 className="story-card-title">What You Get Back</h2>
              <div className="story-list">
                {outputCards.map((card) => (
                  <p key={card} className="story-subsection">{card}</p>
                ))}
              </div>
            </article>

            <article
              ref={(node) => {
                storyCardRefs.current[3] = node;
              }}
              data-card-index={3}
              className={`story-card ${visibleStoryCards[3] ? "is-visible" : ""}`}
            >
              <h2 className="story-card-title">Why Teams Trust It</h2>
              <div className="story-list">
                {trustSignals.map((signal) => (
                  <p key={signal} className="story-subsection">{signal}</p>
                ))}
              </div>
            </article>

            <article
              ref={(node) => {
                storyCardRefs.current[4] = node;
              }}
              data-card-index={4}
              className={`story-card final-cta ${visibleStoryCards[4] ? "is-visible" : ""}`}
            >
              <h2 className="story-card-title">Ready To Build Your Draft?</h2>
              <p className="story-card-cta-copy">Enter the workspace and run the full workflow</p>
              <button type="button" className="workspace-enter" onClick={() => setShowWorkspace(true)}>
                Enter Workspace
              </button>
            </article>

            <article
              ref={(node) => {
                storyCardRefs.current[5] = node;
              }}
              data-card-index={5}
              className={`story-card logo-divider ${visibleStoryCards[5] ? "is-visible" : ""}`}
            >
              <img src="/aws.svg" alt="AWS logo" className="logo-divider-icon" />
              <p className="story-section-note">Powered by Amazon Nova</p>
            </article>
          </section>
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
          <span className="workspace-tagline">AI grant-writing copilot</span>
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

            <details className="advanced-panel">
              <summary>Advanced</summary>
              <div className="field">
                <label htmlFor="context-brief">Context Brief (Optional)</label>
                <textarea
                  id="context-brief"
                  value={contextBrief}
                  onChange={(e) => setContextBrief(e.target.value)}
                  placeholder="Optional context to steer drafting tone/focus."
                  className="input context-textarea"
                />
              </div>
            </details>

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
                  <strong>Drop RFP and supporting documents</strong>
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
              <p className="hint">No new files selected. Nebula will reuse indexed files in this project.</p>
            )}

            <button type="button" className="primary-button" onClick={runWorkspacePipeline} disabled={isRunning}>
              {isRunning ? "Generating..." : "Generate"}
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
                  {runLog.map((line, index) => (
                    <p key={`${line}-${index}`} className="chat-line">
                      {line}
                    </p>
                  ))}
                  <p className="chat-line thinking live">
                    <span className="typing-dot" />
                    Building complete markdown preview...
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
                <p>Upload docs and generate the complete markdown output.</p>
              </section>
            ) : null}

            {!isRunning && result ? (
              <div className="result-shell">
                <section className="preview-toolbar">
                  <div className="preview-title-block">
                    <h3>{exportHeading.title}</h3>
                    {exportHeading.date ? <p>Date: {exportHeading.date}</p> : null}
                  </div>
                  <div className="preview-actions">
                    <button type="button" className="chip-button" onClick={copyMarkdown}>
                      {copyState === "copy" ? "Copy" : copyState === "copied" ? "Copied" : "Copy Failed"}
                    </button>
                    <button type="button" className="chip-button" onClick={downloadMarkdown}>
                      Download
                    </button>
                  </div>
                </section>

                {runStats.length > 0 ? (
                  <section className="preview-metrics">
                    {runStats.map((item) => (
                      <span key={item.label}>
                        <strong>{item.label}:</strong> {item.value}
                      </span>
                    ))}
                  </section>
                ) : null}

                <MarkdownViewer
                  content={result.exportMarkdown}
                  emptyMessage="No markdown export available."
                />
              </div>
            ) : null}

            {runStatus === "error" ? <p className="error-text">{runError ?? "Pipeline failed."}</p> : null}
          </section>
        </section>
      </div>
    </main>
  );
}
