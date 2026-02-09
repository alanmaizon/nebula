"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import SegmentedToggle from "./components/SegmentedToggle";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;
type ViewMode = "summary" | "json";

function asRecord(value: JsonValue): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export default function HomePage() {
  const [projectName, setProjectName] = useState("Nebula Demo Project");
  const [projectId, setProjectId] = useState("");
  const [sectionKey, setSectionKey] = useState("Need Statement");
  const [selectedFiles, setSelectedFiles] = useState<FileList | null>(null);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [requirements, setRequirements] = useState<JsonValue>(null);
  const [draft, setDraft] = useState<JsonValue>(null);
  const [coverage, setCoverage] = useState<JsonValue>(null);
  const [recommendation, setRecommendation] = useState<JsonValue>(null);

  const [recommendationView, setRecommendationView] = useState<ViewMode>("summary");
  const [requirementsView, setRequirementsView] = useState<ViewMode>("summary");
  const [draftView, setDraftView] = useState<ViewMode>("summary");
  const [coverageView, setCoverageView] = useState<ViewMode>("summary");

  const [intake, setIntake] = useState({
    country: "Ireland",
    organization_type: "Non-profit",
    charity_registered: false,
    tax_registered: false,
    has_group_bank_account: false,
    funder_track: "community-foundation",
    funding_goal: "project",
    sector_focus: "general",
    timeline_quarters: 4,
    has_evidence_data: false,
  });

  const isBusy = useMemo(() => loadingAction !== null, [loadingAction]);
  const isTemplateLocked = recommendation !== null;

  const recommendationRecord = asRecord(recommendation);
  const requirementsRecord = asRecord(requirements);
  const draftRecord = asRecord(draft);
  const coverageRecord = asRecord(coverage);

  async function runAction(actionName: string, fn: () => Promise<void>) {
    setLoadingAction(actionName);
    setError(null);
    try {
      await fn();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unexpected error";
      setError(message);
    } finally {
      setLoadingAction(null);
    }
  }

  async function parseJsonResponse(response: Response): Promise<Record<string, unknown>> {
    const payload = (await response.json()) as Record<string, unknown>;
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail));
    }
    return payload;
  }

  async function createProject(e: FormEvent) {
    e.preventDefault();
    await runAction("Creating project", async () => {
      const response = await fetch(`${apiBase}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: projectName }),
      });
      const payload = await parseJsonResponse(response);
      setProjectId(String(payload.id));
      setRecommendation(null);
    });
  }

  async function uploadFiles() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }
    if (!selectedFiles || selectedFiles.length === 0) {
      throw new Error("Select one or more files before uploading.");
    }
    if (!isTemplateLocked) {
      throw new Error("Complete intake and lock a template recommendation before ingest.");
    }

    await runAction("Uploading files", async () => {
      const formData = new FormData();
      Array.from(selectedFiles).forEach((file) => formData.append("files", file));
      const response = await fetch(`${apiBase}/projects/${projectId}/upload`, {
        method: "POST",
        body: formData,
      });
      await parseJsonResponse(response);
    });
  }

  async function extractRequirements() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }
    if (!isTemplateLocked) {
      throw new Error("Complete intake and lock a template recommendation before pipeline actions.");
    }

    await runAction("Extracting requirements", async () => {
      const response = await fetch(`${apiBase}/projects/${projectId}/extract-requirements`, {
        method: "POST",
      });
      const payload = await parseJsonResponse(response);
      setRequirements(payload.requirements as JsonValue);
    });
  }

  async function generateSection() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }
    if (!isTemplateLocked) {
      throw new Error("Complete intake and lock a template recommendation before pipeline actions.");
    }

    await runAction("Generating section", async () => {
      const response = await fetch(`${apiBase}/projects/${projectId}/generate-section`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section_key: sectionKey }),
      });
      const payload = await parseJsonResponse(response);
      setDraft(payload.draft as JsonValue);
    });
  }

  async function computeCoverage() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }
    if (!isTemplateLocked) {
      throw new Error("Complete intake and lock a template recommendation before pipeline actions.");
    }

    await runAction("Computing coverage", async () => {
      const response = await fetch(`${apiBase}/projects/${projectId}/coverage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section_key: sectionKey }),
      });
      const payload = await parseJsonResponse(response);
      setCoverage(payload.coverage as JsonValue);
    });
  }

  async function exportArtifacts(format: "json" | "markdown") {
    if (!projectId) {
      throw new Error("Create a project first.");
    }
    if (!isTemplateLocked) {
      throw new Error("Complete intake and lock a template recommendation before export.");
    }

    await runAction(`Exporting ${format}`, async () => {
      const response = await fetch(
        `${apiBase}/projects/${projectId}/export?format=${format}&section_key=${encodeURIComponent(sectionKey)}`
      );
      if (!response.ok) {
        const fallback = await response.text();
        throw new Error(fallback || `Export failed (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `nebula-${projectId}.${format === "json" ? "json" : "md"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });
  }

  async function saveIntake() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }

    await runAction("Saving intake", async () => {
      const response = await fetch(`${apiBase}/projects/${projectId}/intake`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(intake),
      });
      await parseJsonResponse(response);
    });
  }

  async function generateTemplateRecommendation() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }

    await runAction("Recommending template", async () => {
      const response = await fetch(`${apiBase}/projects/${projectId}/template-recommendation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const payload = await parseJsonResponse(response);
      setRecommendation(payload.recommendation as JsonValue);
    });
  }

  async function loadLatestTemplateRecommendation(currentProjectId: string) {
    if (!currentProjectId) {
      return;
    }

    const response = await fetch(`${apiBase}/projects/${currentProjectId}/template-recommendation/latest`);
    if (!response.ok) {
      if (response.status === 404) {
        setRecommendation(null);
        return;
      }
      const fallback = await response.text();
      throw new Error(fallback || `Template recommendation lookup failed (${response.status})`);
    }
    const payload = (await response.json()) as Record<string, unknown>;
    setRecommendation(payload.recommendation as JsonValue);
  }

  useEffect(() => {
    if (!projectId) {
      setRecommendation(null);
      return;
    }

    runAction("Loading template recommendation", async () => {
      await loadLatestTemplateRecommendation(projectId);
    });
  }, [projectId]);

  const recommendationSummary = useMemo(() => {
    if (!recommendationRecord) {
      return [];
    }

    const lines: string[] = [];
    const templateName = typeof recommendationRecord.template_name === "string" ? recommendationRecord.template_name : null;
    const templateKey = typeof recommendationRecord.template_key === "string" ? recommendationRecord.template_key : null;
    const rationale = Array.isArray(recommendationRecord.rationale)
      ? recommendationRecord.rationale.filter((item): item is string => typeof item === "string")
      : [];
    const checklist = Array.isArray(recommendationRecord.required_checklist)
      ? recommendationRecord.required_checklist.filter((item): item is string => typeof item === "string")
      : [];
    const warnings = Array.isArray(recommendationRecord.warnings)
      ? recommendationRecord.warnings.filter((item): item is string => typeof item === "string")
      : [];

    if (templateName) {
      lines.push(`Template: ${templateName}${templateKey ? ` (${templateKey})` : ""}`);
    }
    if (rationale.length > 0) {
      lines.push("Why this template:");
      rationale.slice(0, 3).forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
    }
    if (checklist.length > 0) {
      lines.push("Required checklist:");
      checklist.slice(0, 5).forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
    }
    if (warnings.length > 0) {
      lines.push("Warnings:");
      warnings.slice(0, 3).forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
    }

    return lines;
  }, [recommendationRecord]);

  const requirementsSummary = useMemo(() => {
    if (!requirementsRecord) {
      return [];
    }

    const lines: string[] = [];
    const funder = typeof requirementsRecord.funder === "string" ? requirementsRecord.funder : null;
    const deadline = typeof requirementsRecord.deadline === "string" ? requirementsRecord.deadline : null;
    const questions = Array.isArray(requirementsRecord.questions)
      ? requirementsRecord.questions.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      : [];
    const attachments = Array.isArray(requirementsRecord.required_attachments)
      ? requirementsRecord.required_attachments.filter((item): item is string => typeof item === "string")
      : [];

    lines.push(`Funder: ${funder || "Unknown"}`);
    lines.push(`Deadline: ${deadline || "Not specified"}`);
    lines.push(`Questions extracted: ${questions.length}`);
    questions.slice(0, 4).forEach((question, index) => {
      const prompt = typeof question.prompt === "string" ? question.prompt : `Question ${index + 1}`;
      lines.push(`${index + 1}. ${prompt}`);
    });
    lines.push(`Required attachments: ${attachments.length}`);
    attachments.slice(0, 3).forEach((item, index) => lines.push(`${index + 1}. ${item}`));

    return lines;
  }, [requirementsRecord]);

  const draftSummary = useMemo(() => {
    if (!draftRecord) {
      return [];
    }

    const lines: string[] = [];
    const section = typeof draftRecord.section_key === "string" ? draftRecord.section_key : "Unknown";
    const paragraphs = Array.isArray(draftRecord.paragraphs)
      ? draftRecord.paragraphs.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      : [];
    const missingEvidence = Array.isArray(draftRecord.missing_evidence)
      ? draftRecord.missing_evidence.filter((item): item is string => typeof item === "string")
      : [];

    const citationCount = paragraphs.reduce((count, paragraph) => {
      const citations = paragraph.citations;
      return count + (Array.isArray(citations) ? citations.length : 0);
    }, 0);

    lines.push(`Section: ${section}`);
    lines.push(`Paragraphs: ${paragraphs.length}`);
    lines.push(`Citations: ${citationCount}`);

    const firstParagraph = paragraphs[0];
    if (firstParagraph && typeof firstParagraph.text === "string") {
      const preview = firstParagraph.text.length > 260 ? `${firstParagraph.text.slice(0, 257)}...` : firstParagraph.text;
      lines.push("Preview:");
      lines.push(preview);
    }

    if (missingEvidence.length > 0) {
      lines.push("Missing evidence:");
      missingEvidence.slice(0, 3).forEach((item, index) => lines.push(`${index + 1}. ${item}`));
    }

    return lines;
  }, [draftRecord]);

  const coverageSummary = useMemo(() => {
    if (!coverageRecord) {
      return [];
    }

    const lines: string[] = [];
    const items = Array.isArray(coverageRecord.items)
      ? coverageRecord.items.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      : [];

    let met = 0;
    let partial = 0;
    let missing = 0;
    for (const item of items) {
      const status = typeof item.status === "string" ? item.status : "";
      if (status === "met") met += 1;
      else if (status === "partial") partial += 1;
      else if (status === "missing") missing += 1;
    }

    lines.push(`Coverage items: ${items.length}`);
    lines.push(`Met: ${met}`);
    lines.push(`Partial: ${partial}`);
    lines.push(`Missing: ${missing}`);
    if (items.length > 0) {
      lines.push("Top items:");
      items.slice(0, 4).forEach((item, index) => {
        const id = typeof item.requirement_id === "string" ? item.requirement_id : `item-${index + 1}`;
        const status = typeof item.status === "string" ? item.status : "unknown";
        lines.push(`${id}: ${status}`);
      });
    }

    return lines;
  }, [coverageRecord]);

  const suggestedSectionKeys = useMemo(() => {
    const defaults = [
      "Need Statement",
      "Program Design",
      "Outcomes and Evaluation",
      "Sustainability",
      "Implementation Timeline",
      "Budget Narrative",
    ];

    const fromRequirements: string[] = [];
    const maybeQuestions = requirementsRecord?.questions;
    if (Array.isArray(maybeQuestions)) {
      for (const item of maybeQuestions) {
        if (!item || typeof item !== "object") {
          continue;
        }
        const prompt = (item as Record<string, unknown>).prompt;
        if (typeof prompt === "string" && prompt.trim()) {
          fromRequirements.push(prompt.trim());
        }
      }
    }

    return Array.from(new Set([...fromRequirements, ...defaults]));
  }, [requirementsRecord]);

  return (
    <main className="stack">
      <section className="hero-wrap">
        <div className="hero">
          <div className="arc" aria-hidden="true" />
          <div className="grain" aria-hidden="true" />
          <img src="/icon.png" alt="Nebula icon" className="hero-logo" />
          <h1 className="title">Nebula</h1>
          <button
            type="button"
            className="button hero-cta"
            onClick={() => {
              const el = document.getElementById("demo-workspace");
              el?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          >
            Start Demo
          </button>
        </div>
      </section>

      <section id="demo-workspace" className="stack">
        <h2>Nebula Demo Workspace</h2>
        <p>Follow the flow: create project, complete intake, lock template recommendation, then run pipeline actions.</p>
      </section>

      <section className="card stack">
        <h2>Project Setup</h2>
        <form className="row" onSubmit={createProject}>
          <input
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder="Project name"
            className="input"
          />
          <button type="submit" className="button" disabled={isBusy}>
            Create Project
          </button>
        </form>
        <p className="mono">Project ID: {projectId || "not created yet"}</p>
      </section>

      <section className="card stack">
        <h2>Pre-Ingest Intake Wizard</h2>
        <p>Capture grant context first so Nebula can recommend the best submission template.</p>
        <div className="row wrap">
          <input
            value={intake.country}
            onChange={(e) => setIntake((prev) => ({ ...prev, country: e.target.value }))}
            placeholder="Country"
            className="input"
          />
          <input
            value={intake.organization_type}
            onChange={(e) => setIntake((prev) => ({ ...prev, organization_type: e.target.value }))}
            placeholder="Organization type"
            className="input"
          />
          <input
            value={intake.funder_track}
            onChange={(e) => setIntake((prev) => ({ ...prev, funder_track: e.target.value }))}
            placeholder="Funder track (community-foundation, government, eu)"
            className="input"
          />
        </div>
        <div className="row wrap">
          <input
            value={intake.funding_goal}
            onChange={(e) => setIntake((prev) => ({ ...prev, funding_goal: e.target.value }))}
            placeholder="Funding goal (project/core)"
            className="input"
          />
          <input
            value={intake.sector_focus}
            onChange={(e) => setIntake((prev) => ({ ...prev, sector_focus: e.target.value }))}
            placeholder="Sector focus (general, heritage, rural)"
            className="input"
          />
          <input
            type="number"
            min={1}
            max={12}
            value={intake.timeline_quarters}
            onChange={(e) => setIntake((prev) => ({ ...prev, timeline_quarters: Number(e.target.value) || 1 }))}
            placeholder="Timeline quarters"
            className="input"
          />
        </div>
        <div className="row wrap">
          <label className="check">
            <input
              type="checkbox"
              checked={intake.charity_registered}
              onChange={(e) => setIntake((prev) => ({ ...prev, charity_registered: e.target.checked }))}
            />
            Charity registered
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={intake.tax_registered}
              onChange={(e) => setIntake((prev) => ({ ...prev, tax_registered: e.target.checked }))}
            />
            Tax registered
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={intake.has_group_bank_account}
              onChange={(e) => setIntake((prev) => ({ ...prev, has_group_bank_account: e.target.checked }))}
            />
            Group bank account
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={intake.has_evidence_data}
              onChange={(e) => setIntake((prev) => ({ ...prev, has_evidence_data: e.target.checked }))}
            />
            Evidence dataset ready
          </label>
        </div>
        <div className="row wrap">
          <button type="button" className="button" onClick={saveIntake} disabled={isBusy}>
            Save Intake
          </button>
          <button type="button" className="button ghost" onClick={generateTemplateRecommendation} disabled={isBusy}>
            Recommend Template
          </button>
        </div>
      </section>

      <section className="card stack">
        <h2>Template Recommendation</h2>
        {!isTemplateLocked ? <p className="notice">Template not locked yet.</p> : null}
        <SegmentedToggle
          label="View mode"
          value={recommendationView}
          onChange={(value) => setRecommendationView(value as ViewMode)}
          options={[
            { value: "summary", label: "Summary" },
            { value: "json", label: "JSON" },
          ]}
        />
        {recommendationView === "summary" ? (
          <pre className="code">{recommendationSummary.join("\n") || "No recommendation yet."}</pre>
        ) : (
          <pre className="code">{JSON.stringify(recommendation, null, 2)}</pre>
        )}
      </section>

      <section className="card stack">
        <h2>Documents</h2>
        {!isTemplateLocked ? (
          <p className="notice">Complete intake and click "Recommend Template" before uploading documents.</p>
        ) : null}
        <input type="file" multiple onChange={(e) => setSelectedFiles(e.target.files)} className="input" />
        <button type="button" className="button" onClick={uploadFiles} disabled={isBusy || !isTemplateLocked}>
          Upload and Index Files
        </button>
      </section>

      <section className="card stack">
        <h2>Pipeline Actions</h2>
        <p className="notice">
          Section key means the exact grant answer you want Nebula to draft and score. Default is <strong>Need
          Statement</strong> because it is usually Question 1 in grant applications.
        </p>
        <div className="row stack-on-mobile">
          <input
            list="section-key-suggestions"
            value={sectionKey}
            onChange={(e) => setSectionKey(e.target.value)}
            placeholder="Pick or type a section key"
            className="input"
          />
          <datalist id="section-key-suggestions">
            {suggestedSectionKeys.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </div>
        <div className="row wrap">
          {suggestedSectionKeys.slice(0, 6).map((item) => (
            <button
              key={item}
              type="button"
              className={`pill ${sectionKey === item ? "active" : ""}`}
              onClick={() => setSectionKey(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <div className="stack help">
          <p>Extract Requirements: parse funder rules/questions from uploaded files.</p>
          <p>Generate Section: draft only the section in the section key input above.</p>
          <p>Compute Coverage: evaluate how well the draft covers extracted requirements.</p>
          <p>Export JSON/Markdown: download full project artifacts for review/submission.</p>
        </div>
        <div className="row wrap">
          <button type="button" className="button" onClick={extractRequirements} disabled={isBusy || !isTemplateLocked}>
            Extract Requirements
          </button>
          <button type="button" className="button" onClick={generateSection} disabled={isBusy || !isTemplateLocked}>
            Generate Section
          </button>
          <button type="button" className="button" onClick={computeCoverage} disabled={isBusy || !isTemplateLocked}>
            Compute Coverage
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => exportArtifacts("json")}
            disabled={isBusy || !isTemplateLocked}
          >
            Export JSON
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => exportArtifacts("markdown")}
            disabled={isBusy || !isTemplateLocked}
          >
            Export Markdown
          </button>
        </div>
        <p className="mono">Action: {loadingAction ?? "idle"}</p>
        {error ? <p className="error">Error: {error}</p> : null}
      </section>

      <section className="card stack">
        <h2>Requirements</h2>
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
          <pre className="code">{requirementsSummary.join("\n") || "No requirements yet."}</pre>
        ) : (
          <pre className="code">{JSON.stringify(requirements, null, 2)}</pre>
        )}
      </section>

      <section className="card stack">
        <h2>Draft</h2>
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
          <pre className="code">{draftSummary.join("\n") || "No draft yet."}</pre>
        ) : (
          <pre className="code">{JSON.stringify(draft, null, 2)}</pre>
        )}
      </section>

      <section className="card stack">
        <h2>Coverage</h2>
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
          <pre className="code">{coverageSummary.join("\n") || "No coverage yet."}</pre>
        ) : (
          <pre className="code">{JSON.stringify(coverage, null, 2)}</pre>
        )}
      </section>
    </main>
  );
}
