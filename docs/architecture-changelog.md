# Architecture Version History & Changelog

This document tracks changes to the system's architecture, default ports, folder structures, and key integrations.

## Architectural Version History

| Version | Date | Description of Changes | Affected Components | Author |
| :--- | :--- | :--- | :--- | :--- |
| **v1.3.0** | 2026-05-26 | Live Health Status & AI Agent Prompt Checkpoint | Dashboard UI, webapp, app.js, index.html, styles.css | AI Architect |
| **v1.2.0** | 2026-05-25 | Interactive Architecture Tab & Scroll-Safe Zoom | static/app.js, static/index.html, static/styles.css | AI Architect |
| **v1.1.0** | 2026-05-24 | FreeLLMAPI Router & Local fallback retrieval | poc_workflow.chatbot, webapp.py, LLM proxy | AI Architect |
| **v1.0.0** | 2026-05-20 | Ingestion Pipeline & Quality Governance Baseline | intake.py, pipeline.py, quality_gate.py, sqlite DB | Development Team |

---

## Detailed Release Changelog

### v1.3.0 (2026-05-26) - Live Health Status & AI Agent Prompt Checkpoint
- **Added Live Component Status**: Added live status badges on the Bento Grid components within the Architecture dashboard. Badges update automatically every reload using JSON data returned from the backend `/api/health` queries.
- **Added AI Agent Checkpoint Prompt**: Added a copy-pasteable system prompt designed with advanced prompt engineering patterns (Context -> Objective -> Instructions -> Constraints) to guide downstream AI agents when scanning codebases, updating Mermaid diagrams, and writing logs.
- **Removed Operations Tab Duplications**: Avoided duplicate operations telemetry, maintaining focus strictly on architecture.

### v1.2.0 (2026-05-25) - Interactive Architecture Tab & Scroll-Safe Zoom
- **Created Architecture View**: Added a new dashboard view displaying four distinct Mermaid diagrams:
  - Technical Runtime View (Runtime flow & API)
  - Document Ingestion View (Ingestion & Quality Gate stages)
  - Query Sequence View (Autonumbered query-answer timeline)
  - Security Boundaries (Subgraphs mapping local vs. public resources)
- **Implemented Scroll-Safe Zoom controls**: Added zoom-in, zoom-out, and zoom-reset controls. Centered SVGs inside a flex-container with `margin: auto` to prevent clipping and enable smooth scrollbar panning.

### v1.1.0 (2026-05-24) - FreeLLMAPI Router & Local Fallback
- **Introduced FreeLLMAPI**: Configured a port-forwarded LLM proxy (`:3001`) that multiplexes between free-tier APIs (Groq, OpenRouter, Pollinations).
- **Local Fallback Index**: Implemented a local JSONL index (`ragflow_index/`) to serve query contexts when RAGFlow is offline.

### v1.0.0 (2026-05-20) - Ingestion Pipeline & Quality Governance Baseline
- **Document Lifecyle**: Established the three-stage ingestion process:
  - `inbox/`: Document intake
  - `normalized/`: MinerU Markdown normalization (`:8010`)
  - `manifest/records.json`: Governance and status (pending_review, active, failed_review)
- **SQLite logs**: Set up `data/poc_quality.db` to log user questions, citations, latency, and knowledge gaps.

---

## Architecture Component Blueprint & Ports

- **FastAPI Backend Server**: runs on port `:8088` (managed by `poc_workflow.webapp`).
- **LLM Proxy**: runs on port `:3001` (managed by `refs/freellmapi` or environment vars).
- **MinerU normalizer**: runs on port `:8010` (when running as a standalone OCR service).
- **RAGFlow search endpoint**: runs on port `:9380` (production retrieval engine).
