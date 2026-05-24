# Documentation Map

Use these docs as the operational source for the current POC.

## Architecture And Workflow

- `architecture.md`: end-to-end architecture, lifecycle diagrams, source-of-truth rules.
- `demo-end-to-end-architecture.md`: Mermaid diagrams for the Vercel demo, local backend, document workflow, and security boundaries.
- `document-intake-procedure.md`: how users provide documents and how agents process inbox files.
- `acceptance-loop-check-2026-05-23.md`: latest 69-case loop-check report and production gaps.
- `quality-gate-latest.md`: latest deterministic quality gate report for release acceptance.
- `operations-observability.md`: incidents, diagnostics, alerts, and AI-agent debug procedure.
- `mineru-agent-tool.md`: MinerU background service, WebUI, and AI-agent usage.

## Runtime And Integrations

- `freellmapi-integration.md`: local FreeLLMAPI setup, chatbot LLM configuration, smoke tests, caveats.
- `local-runtime-status.md`: current local service URLs and last verified smoke-test state.
- `production-runbook.md`: local app, container run, RAGFlow sync, FreeLLMAPI proxy, recovery.
- `vercel-demo.md`: Vercel demo UI with local backend through a secure tunnel.

## Governance

- `security-production-checklist.md`: auth, provider, network, and production controls.
- `oss-compliance.md`: upstream projects, license notes, and reuse boundaries.

## Current Local URLs

```text
Chatbot dashboard:  http://127.0.0.1:8088
FreeLLMAPI proxy:   http://127.0.0.1:3001
```
