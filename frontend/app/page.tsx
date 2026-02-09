"use client";

import { useMemo, useState, type DragEvent } from "react";
import SegmentedToggle from "./components/SegmentedToggle";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;
type ViewMode = "summary" | "json";
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

type SectionRunResult = {
  sectionKey: string;
  prompt: string;
  retrieval: JsonValue;
  draft: JsonValue;
  coverage: JsonValue;
  exportJson: JsonValue;
  exportMarkdown: string;
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

function readQuestionPrompts(requirements: JsonValue | null): string[] {
  const record = asRecord(requirements);
  const maybeQuestions = record?.questions;
  if (!Array.isArray(maybeQuestions)) {
    return [];
  }

  const prompts: string[] = [];
  for (const item of maybeQuestions) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const prompt = (item as Record<string, unknown>).prompt;
    if (typeof prompt === "string" && prompt.trim()) {
      prompts.push(prompt.trim());
    }
  }
  return Array.from(new Set(prompts));
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

function fileSafeSectionKey(sectionKey: string): string {
  const cleaned = sectionKey.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || "section";
}

export default function HomePage() {
  const [showWorkspace, setShowWorkspace] = useState(false);

  const [projectName, setProjectName] = useState("Nebula Demo Project");
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);
  const [activityFeed, setActivityFeed] = useState<string[]>([]);

  const [intake, setIntake] = useState<IntakeContext>({
    country: "Ireland",
    organization_type: "Non-profit",
    funder_track: "community-foundation",
    funding_goal: "project",
    sector_focus: "general",
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

        failedStage = "export";
        setActivePane("export");
        setStage("export", "running", `Generating exports for "${target.sectionKey}" (${ordinal})...`);
        const exportJsonResponse = await fetch(
          `${apiBase}/projects/${currentProjectId}/export?format=json&section_key=${encodeURIComponent(target.sectionKey)}`
        );
        if (!exportJsonResponse.ok) {
          const fallback = await exportJsonResponse.text();
          throw new Error(fallback || `JSON export failed (${exportJsonResponse.status})`);
        }
        const exportJson = (await exportJsonResponse.json()) as JsonValue;

        const exportMarkdownResponse = await fetch(
          `${apiBase}/projects/${currentProjectId}/export?format=markdown&section_key=${encodeURIComponent(target.sectionKey)}`
        );
        if (!exportMarkdownResponse.ok) {
          const fallback = await exportMarkdownResponse.text();
          throw new Error(fallback || `Markdown export failed (${exportMarkdownResponse.status})`);
        }
        const exportMarkdown = await exportMarkdownResponse.text();

        sectionRuns.push({
          sectionKey: target.sectionKey,
          prompt: target.prompt,
          retrieval,
          draft,
          coverage,
          exportJson,
          exportMarkdown,
        });
      }
      setStage("export", "done", `JSON + Markdown exports ready for ${sectionRuns.length} section(s).`);

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
        exportJson: primarySection?.exportJson ?? null,
        exportMarkdown: primarySection?.exportMarkdown ?? "",
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
    if (!result || !currentSectionRun?.exportJson) {
      return;
    }
    const blob = new Blob([JSON.stringify(currentSectionRun.exportJson, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nebula-${result.projectId}-${fileSafeSectionKey(currentSectionRun.sectionKey)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function downloadMarkdown() {
    if (!result || !currentSectionRun?.exportMarkdown) {
      return;
    }
    const blob = new Blob([currentSectionRun.exportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nebula-${result.projectId}-${fileSafeSectionKey(currentSectionRun.sectionKey)}.md`;
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

  const requirementsSummary = useMemo(() => {
    if (!result) {
      return [];
    }
    const requirementsRecord = asRecord(result.requirements);
    const extractionRecord = asRecord(result.extraction);
    if (!requirementsRecord) {
      return [];
    }

    const lines: string[] = [];
    const funder = typeof requirementsRecord.funder === "string" ? requirementsRecord.funder : "Unknown";
    const deadline = typeof requirementsRecord.deadline === "string" ? requirementsRecord.deadline : "Not specified";
    const questions = Array.isArray(requirementsRecord.questions) ? requirementsRecord.questions : [];
    const attachments = Array.isArray(requirementsRecord.required_attachments)
      ? requirementsRecord.required_attachments
      : [];

    lines.push(`Funder: ${funder}`);
    lines.push(`Deadline: ${deadline}`);
    if (extractionRecord && typeof extractionRecord.mode === "string") {
      lines.push(`Extraction mode: ${extractionRecord.mode}`);
    }
    lines.push(`Questions extracted: ${questions.length}`);
    for (const [index, question] of questions.slice(0, 6).entries()) {
      if (!question || typeof question !== "object") {
        continue;
      }
      const prompt = (question as Record<string, unknown>).prompt;
      if (typeof prompt === "string") {
        lines.push(`${index + 1}. ${prompt}`);
      }
    }
    lines.push(`Required attachments: ${attachments.length}`);
    for (const [index, attachment] of attachments.slice(0, 6).entries()) {
      if (typeof attachment === "string") {
        lines.push(`${index + 1}. ${attachment}`);
      }
    }
    return lines;
  }, [result]);

  const retrievalSummary = useMemo(() => {
    if (!result) {
      return [];
    }
    const retrievalRecord = currentSectionRun ? asRecord(currentSectionRun.retrieval) : null;
    if (!retrievalRecord) {
      return [];
    }

    const lines: string[] = [];
    const query = typeof retrievalRecord.query === "string" ? retrievalRecord.query : "Unknown";
    const results = Array.isArray(retrievalRecord.results) ? retrievalRecord.results : [];

    lines.push(`Section: ${currentSectionRun?.sectionKey ?? "Unknown"}`);
    lines.push(`Query: ${query}`);
    lines.push(`Evidence chunks: ${results.length}`);
    for (const [index, item] of results.slice(0, 6).entries()) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const row = item as Record<string, unknown>;
      const fileName = typeof row.file_name === "string" ? row.file_name : "unknown";
      const page = typeof row.page === "number" ? `p.${row.page}` : "p.?";
      const score = typeof row.score === "number" ? row.score.toFixed(3) : "n/a";
      lines.push(`${index + 1}. ${fileName} (${page}) score=${score}`);
    }
    return lines;
  }, [result, currentSectionRun]);

  const draftSummary = useMemo(() => {
    if (!result) {
      return [];
    }
    const draftRecord = currentSectionRun ? asRecord(currentSectionRun.draft) : null;
    if (!draftRecord) {
      return [];
    }

    const lines: string[] = [];
    const section = typeof draftRecord.section_key === "string" ? draftRecord.section_key : "Unknown";
    const paragraphs = Array.isArray(draftRecord.paragraphs) ? draftRecord.paragraphs : [];
    const missingEvidence = Array.isArray(draftRecord.missing_evidence) ? draftRecord.missing_evidence : [];

    let citationCount = 0;
    for (const paragraph of paragraphs) {
      if (!paragraph || typeof paragraph !== "object") {
        continue;
      }
      const citations = (paragraph as Record<string, unknown>).citations;
      if (Array.isArray(citations)) {
        citationCount += citations.length;
      }
    }

    lines.push(`Section: ${section}`);
    lines.push(`Paragraphs: ${paragraphs.length}`);
    lines.push(`Citations: ${citationCount}`);
    if (paragraphs.length > 0) {
      const first = paragraphs[0];
      if (first && typeof first === "object") {
        const text = (first as Record<string, unknown>).text;
        if (typeof text === "string") {
          const preview = text.length > 320 ? `${text.slice(0, 317)}...` : text;
          lines.push("Preview:");
          lines.push(preview);
        }
      }
    }
    if (missingEvidence.length > 0) {
      lines.push(`Missing evidence items: ${missingEvidence.length}`);
    }
    return lines;
  }, [result, currentSectionRun]);

  const coverageSummary = useMemo(() => {
    if (!result) {
      return [];
    }
    const coverageRecord = currentSectionRun ? asRecord(currentSectionRun.coverage) : null;
    if (!coverageRecord) {
      return [];
    }

    const lines: string[] = [];
    const items = Array.isArray(coverageRecord.items) ? coverageRecord.items : [];
    let met = 0;
    let partial = 0;
    let missing = 0;

    for (const item of items) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const status = (item as Record<string, unknown>).status;
      if (status === "met") {
        met += 1;
      } else if (status === "partial") {
        partial += 1;
      } else if (status === "missing") {
        missing += 1;
      }
    }

    lines.push(`Coverage items: ${items.length}`);
    lines.push(`Met: ${met}`);
    lines.push(`Partial: ${partial}`);
    lines.push(`Missing: ${missing}`);
    return lines;
  }, [result, currentSectionRun]);

  const exportSummary = useMemo(() => {
    if (!result) {
      return [];
    }
    const exportRecord = currentSectionRun ? asRecord(currentSectionRun.exportJson) : null;
    const lines: string[] = [];
    lines.push(`Project ID: ${result.projectId}`);
    lines.push(`Sections generated: ${result.sectionRuns.length}`);
    lines.push(`Section: ${currentSectionRun?.sectionKey ?? "Unknown"}`);
    lines.push(`Documents indexed: ${result.documentsIndexed}`);
    lines.push(`Markdown length: ${currentSectionRun?.exportMarkdown.length ?? 0}`);
    if (exportRecord) {
      lines.push("JSON export includes:");
      lines.push(`- requirements: ${exportRecord.requirements !== undefined ? "yes" : "no"}`);
      lines.push(`- draft: ${exportRecord.draft !== undefined ? "yes" : "no"}`);
      lines.push(`- coverage: ${exportRecord.coverage !== undefined ? "yes" : "no"}`);
    }
    return lines;
  }, [result, currentSectionRun]);

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
                        <pre className="code-block">{requirementsSummary.join("\n") || "No requirements generated."}</pre>
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
                        <pre className="code-block">{retrievalSummary.join("\n") || "No retrieval results."}</pre>
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
                        <pre className="code-block">{draftSummary.join("\n") || "No draft generated."}</pre>
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
                        <pre className="code-block">{coverageSummary.join("\n") || "No coverage generated."}</pre>
                      ) : (
                        <pre className="code-block">{JSON.stringify(currentSectionRun?.coverage ?? null, null, 2)}</pre>
                      )}
                    </>
                  ) : null}

                  {activePane === "export" ? (
                    <>
                      <h3>Export</h3>
                      {sectionOptions.length > 1 ? (
                        <div className="field">
                          <label htmlFor="section-picker-export">Section</label>
                          <select
                            id="section-picker-export"
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
                      <pre className="code-block">{exportSummary.join("\n")}</pre>
                      <div className="action-row">
                        <button type="button" className="primary-button" onClick={downloadJson}>
                          Download JSON
                        </button>
                        <button type="button" className="secondary-button" onClick={downloadMarkdown}>
                          Download Markdown
                        </button>
                      </div>
                      <pre className="code-block">
                        {(currentSectionRun?.exportMarkdown.length ?? 0) > 1400
                          ? `${currentSectionRun?.exportMarkdown.slice(0, 1397)}...`
                          : currentSectionRun?.exportMarkdown ?? ""}
                      </pre>
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
