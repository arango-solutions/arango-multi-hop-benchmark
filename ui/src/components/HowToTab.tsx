export function HowToTab() {
  return (
    <div className="panel howto">
      <h2>How-To</h2>
      <p className="howto-lead">
        Multi-Hop Eval generates, validates, and scores multi-hop QA pairs against your
        Arango graph corpus, then lets you evaluate external RAG systems against the
        golden set. Follow the tabs left to right for the full workflow.
      </p>

      <section className="howto-section">
        <h3>What it does</h3>
        <ol className="howto-steps">
          <li>
            <strong>Generates</strong> multi-hop QA pairs whose answers require combining
            evidence from multiple documents — not answerable by vector RAG over a single
            chunk.
          </li>
          <li>
            <strong>Validates</strong> each candidate with a strict multi-hop check and a
            proof-verification loop.
          </li>
          <li>
            <strong>Scores</strong> accepted pairs against a user-defined rubric
            (factuality, faithfulness, conciseness, multi-hop genuineness, persona-fit by
            default).
          </li>
          <li>
            <strong>Persists</strong> results to an Arango collection and exports Excel /
            JSON.
          </li>
          <li>
            <strong>Evaluates</strong> external RAG systems against the golden set with
            deterministic retrieval and generation metrics.
          </li>
        </ol>
      </section>

      <section className="howto-section">
        <h3>Quick start</h3>
        <ol className="howto-steps">
          <li>
            Open <strong>Configure</strong> and connect to Arango — either via AMP
            auto-detect (when deployed on the Arango Managed Platform) or by entering
            host, database, username, and password manually.
          </li>
          <li>
            Map each collection role (sources, similarity, relations, domains, RAGs, QA
            output), select target cluster IDs, set LLM provider and evaluation knobs,
            and edit personas and rubric fields as needed. Click <strong>Save</strong> to
            persist the session config.
          </li>
          <li>
            Open <strong>Run</strong> and click <strong>Run</strong> to start generation.
            Watch the live log and progress bar; use <strong>Stop</strong> to cancel early.
          </li>
          <li>
            Open <strong>Dashboard</strong> to review KPIs, distribution charts, and the
            filterable QA table. Export results as Excel or JSON.
          </li>
        </ol>
      </section>

      <section className="howto-section">
        <h3>Configure</h3>
        <ul className="howto-list">
          <li>
            <strong>Connection</strong> — test connectivity, pick a database from the live
            list, and refresh when credentials rotate (AMP JWT path).
          </li>
          <li>
            <strong>Collections</strong> — assign each graph role to a collection; doc-count
            hints help you pick the right one.
          </li>
          <li>
            <strong>Target clusters</strong> — multi-select cluster IDs from the domains
            collection to scope generation.
          </li>
          <li>
            <strong>LLM settings</strong> — any OpenAI-compatible endpoint; used for
            generation, verification, and rubric scoring.
          </li>
          <li>
            <strong>Personas &amp; rubric</strong> — editable tables; defaults are a good
            starting point. Save persists into the session; <strong>Load from env</strong>{" "}
            reads <code>.env</code>.
          </li>
        </ul>
      </section>

      <section className="howto-section">
        <h3>Run</h3>
        <p>
          Requires a live Arango connection and a saved configuration. Generation runs in a
          background thread; events stream to the live log (cluster start, seed, accepted,
          rejected, pass done). The progress bar tracks <code>accepted / target</code> for
          the current cluster. When complete, a summary banner shows accept rate and
          duration.
        </p>
      </section>

      <section className="howto-section">
        <h3>Dashboard</h3>
        <p>
          Switch between <strong>this session&apos;s run</strong> and the{" "}
          <strong>persisted Arango collection</strong>. Review KPIs (total accepted,
          accept rate, average hops, weighted rubric score), hop/persona/cluster
          distributions, and a filterable QA table. Download Excel or JSON exports for
          offline analysis.
        </p>
      </section>

      <section className="howto-section">
        <h3>Ad-hoc</h3>
        <p>
          Validate a single question / answer / proof against pasted source documents
          without running the full pipeline. Paste your Q/A, reasoning chain, proof points
          (with source IDs), and source document content. Optionally score with the
          configured rubric. Useful for spot-checking a candidate QA pair before adding it
          to a dataset.
        </p>
      </section>

      <section className="howto-section">
        <h3>RAG Eval</h3>
        <ol className="howto-steps">
          <li>
            Download the golden set as JSONL (<strong>Download goldens JSONL</strong>) and
            hand the keys to your RAG team.
          </li>
          <li>
            Collect RAG responses — one JSON object per line, one line per (system,
            question). Each line needs <code>system_name</code>, <code>qa_pair_key</code>{" "}
            (must match a golden <code>_key</code>), <code>question</code>,{" "}
            <code>answer</code>, and <code>retrieved_chunks</code>.
          </li>
          <li>
            Upload the JSONL or point at an Arango sink collection, configure relevance
            grading (binary or graded) and K cut-offs, then run evaluation.
          </li>
          <li>
            Compare two or more <code>system_name</code>s side-by-side. Metrics include
            Precision@K, Recall@K, MRR, NDCG@K, HitRate@K, Groundedness, Source Diversity,
            Citation Coverage, ROUGE-L, and more — all deterministic, no LLM-as-judge.
          </li>
        </ol>
        <pre className="howto-code">{`{
  "system_name": "rag_v2",
  "qa_pair_key": "1234567",
  "question": "...",
  "answer": "Foo bar [sources/abc].",
  "retrieved_chunks": [
    {"doc_id": "sources/abc", "rank": 1, "score": 0.92, "text": "..."},
    {"doc_id": "sources/xyz", "rank": 2, "score": 0.81, "text": "..."}
  ],
  "metadata": {"latency_ms": 1200}
}`}</pre>
      </section>

      <section className="howto-section">
        <h3>Tips</h3>
        <ul className="howto-list">
          <li>
            Save configuration on <strong>Configure</strong> before switching to{" "}
            <strong>Run</strong> — the Run tab checks for both connection and saved config.
          </li>
          <li>
            Enable <strong>Save to Arango</strong> during configuration so results persist
            across sessions and appear in the Dashboard&apos;s collection view.
          </li>
          <li>
            When deployed on AMP, connection is automatic; switching databases refreshes
            collection pickers and cluster IDs from the live database.
          </li>
          <li>
            For local development, copy <code>.env.example</code> to <code>.env</code> and
            fill in <code>ARANGO_HOST</code>, <code>ARANGO_DB</code>,{" "}
            <code>ARANGO_PASSWORD</code>, and <code>LLM_API_KEY</code> at minimum.
          </li>
        </ul>
      </section>
    </div>
  );
}
