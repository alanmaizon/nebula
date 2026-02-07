const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function HomePage() {
  return (
    <main className="stack">
      <span className="badge">Step 1 Foundation Complete</span>
      <h1>GrantSmith Development Workspace</h1>
      <p>
        Frontend and backend baselines are scaffolded. Next implementation
        focus: ingestion pipeline, chunking, and requirements extraction.
      </p>

      <section className="card stack">
        <h2>Service Endpoints</h2>
        <p className="mono">Frontend health: /api/health</p>
        <p className="mono">Backend health: {apiBase}/health</p>
      </section>
    </main>
  );
}

