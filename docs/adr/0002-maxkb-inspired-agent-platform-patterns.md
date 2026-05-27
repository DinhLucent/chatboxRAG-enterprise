# ADR-0002: Adopt Selected MaxKB Agent Platform Patterns

## Status

Accepted

## Context

MaxKB v2 was reviewed as a reference implementation for enterprise RAG and
agent orchestration. It is broader than this project: Django/DRF backend,
PostgreSQL + pgvector retrieval, Vue workflow builder, model provider registry,
tool/MCP layer, triggers, workflow versioning, and detailed runtime traces.

This project should not copy MaxKB wholesale. The current advantage is a smaller
FastAPI governance and quality layer around RAGFlow/MinerU with strict document
lifecycle controls: uploaded documents stop at review, only approved latest
active records can answer user questions, and quality gates are deterministic.

## Decision

Adopt four MaxKB-inspired patterns incrementally:

1. **Workflow JSON DAG**
   - Move `qa_agent_workflow` from hardcoded procedural orchestration toward a
     versioned JSON DAG with explicit nodes, edges, contracts, retry policy, and
     feature flag binding.
   - Keep code-owned nodes first; do not build a visual editor yet.

2. **Runtime Node Trace**
   - Standardize trace events as node records with `node_id`, `type`, `status`,
     `runtime_ms`, sanitized inputs/outputs, citation counts, token/model data
     when available, and error branch.
   - Do not expose raw prompts or hidden chain-of-thought.

3. **Model Provider Registry**
   - Evolve env/runtime LLM config into a provider registry with profiles,
     capabilities (`chat`, `embedding`, `rerank`, `vision`, `stt`, `tts`), and
     a credential boundary.
   - Keep the current OpenAI-compatible client as the first adapter.

4. **Workflow Version / Publish**
   - Version workflow DAG, prompts, evidence contracts, and checker thresholds.
   - Support active/draft workflow versions and rollback independently from code
     deploys once the runtime is stable.

## Rejected For V1

- **Visual workflow builder**: useful later, but high UI scope and easy to
  overfit before backend DAG contracts stabilize.
- **Arbitrary custom-code tools**: too risky for the current governance surface.
  Only approved internal tools with schemas, timeout, and audit logs should be
  considered.
- **Long-term user memory**: deferred until retention, consent, and PII policy
  are explicit. Session memory with TTL remains sufficient for now.
- **Replacing RAGFlow with pgvector**: MaxKB's native retrieval is strong, but
  the current system already centers RAGFlow as the evidence backend. The
  orchestration layer should remain retrieval-engine agnostic.

## Rationale

The four accepted patterns solve current pain points without changing the whole
product shape:

- DAG and versioning make the QA workflow inspectable, testable, and rollbackable.
- Runtime trace improves audit, debugging, and user trust.
- Model registry reduces env-only coupling and prepares for reranker/embedding
  adapters.
- Keeping governance in this project preserves the strongest current boundary:
  no pending/archived/retired/supporting-only source should answer users unless
  a policy explicitly permits it.

## Team / Ownership Implications

V1 can be implemented by a small product engineering team:

- **Backend/orchestration owner**: DAG schema, node runner, trace contracts,
  version loading, RAGFlow/model adapters.
- **AI quality owner**: prompts, evidence contract, checker thresholds,
  regression eval set, failure taxonomy.
- **Frontend owner**: trace drawer, structured answer renderer, future workflow
  version inspection UI.
- **Ops/governance owner**: feature flags, rollout, secrets boundary, audit log,
  rollback procedure.

Do not split into services yet. This remains a modular monolith until scaling or
team boundaries justify extraction.

## Rollout Plan

1. Normalize current trace events into node trace schema.
2. Introduce static JSON DAG for the existing QA Agent V1 stages.
3. Add workflow version metadata to `answer_run`.
4. Move prompt/checker parameters into versioned config.
5. Add model provider registry profiles.
6. Add publish/rollback controls after tests and runtime traces are stable.

## Revisit Triggers

- More than one active workflow is needed for different departments.
- Non-engineers need to edit workflow structure safely.
- Tool/MCP invocation becomes a core user workflow.
- RAGFlow retrieval quality cannot meet evaluation targets even after reranker
  and evidence planning improvements.
