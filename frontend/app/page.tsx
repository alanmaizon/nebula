"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;

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

  return (
    <main className="stack">
      <section className="hero-wrap">
        <div className="hero">
          <div className="arc" aria-hidden="true" />
          <div className="grain" aria-hidden="true" />
          <img src="/logo.png" alt="Nebula logo" className="hero-logo" />
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
        <span className="badge">Step 7 In Progress: Export and UX</span>
        <h2>Nebula Development Workspace (Amazon Nova)</h2>
        <p>Run the MVP pipeline end-to-end from project creation through export.</p>
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
        <h2>Documents</h2>
        {!isTemplateLocked ? (
          <p className="notice">Complete intake and click “Recommend Template” before uploading documents.</p>
        ) : null}
        <input
          type="file"
          multiple
          onChange={(e) => setSelectedFiles(e.target.files)}
          className="input"
        />
        <button type="button" className="button" onClick={uploadFiles} disabled={isBusy || !isTemplateLocked}>
          Upload and Index Files
        </button>
      </section>

      <section className="card stack">
        <h2>Pipeline Actions</h2>
        <div className="row">
          <input
            value={sectionKey}
            onChange={(e) => setSectionKey(e.target.value)}
            placeholder="Section key"
            className="input"
          />
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
        <pre className="code">{JSON.stringify(requirements, null, 2)}</pre>
      </section>

      <section className="card stack">
        <h2>Draft</h2>
        <pre className="code">{JSON.stringify(draft, null, 2)}</pre>
      </section>

      <section className="card stack">
        <h2>Coverage</h2>
        <pre className="code">{JSON.stringify(coverage, null, 2)}</pre>
      </section>

      <section className="card stack">
        <h2>Template Recommendation</h2>
        {!isTemplateLocked ? <p className="notice">Template not locked yet.</p> : null}
        <pre className="code">{JSON.stringify(recommendation, null, 2)}</pre>
      </section>
    </main>
  );
}
