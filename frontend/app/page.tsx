"use client";

import { FormEvent, useMemo, useState } from "react";

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

  const isBusy = useMemo(() => loadingAction !== null, [loadingAction]);

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
    });
  }

  async function uploadFiles() {
    if (!projectId) {
      throw new Error("Create a project first.");
    }
    if (!selectedFiles || selectedFiles.length === 0) {
      throw new Error("Select one or more files before uploading.");
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
        <h2>Documents</h2>
        <input
          type="file"
          multiple
          onChange={(e) => setSelectedFiles(e.target.files)}
          className="input"
        />
        <button type="button" className="button" onClick={uploadFiles} disabled={isBusy}>
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
          <button type="button" className="button" onClick={extractRequirements} disabled={isBusy}>
            Extract Requirements
          </button>
          <button type="button" className="button" onClick={generateSection} disabled={isBusy}>
            Generate Section
          </button>
          <button type="button" className="button" onClick={computeCoverage} disabled={isBusy}>
            Compute Coverage
          </button>
          <button type="button" className="button ghost" onClick={() => exportArtifacts("json")} disabled={isBusy}>
            Export JSON
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => exportArtifacts("markdown")}
            disabled={isBusy}
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
    </main>
  );
}
