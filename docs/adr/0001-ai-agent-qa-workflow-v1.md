# ADR-0001: AI Agent QA Workflow V1

## Status

Accepted

## Context

The previous user chat path retrieved once and generated once. That was fast, but
it made answer quality depend too much on the first retrieved chunks and did not
give the UI enough information to explain missing context, weak evidence, or
source conflicts.

The product now needs a ChatGPT-like governed QA workflow over approved RAGFlow
knowledge, while preserving the existing upload governance rule: documents must
pass QA and human approval before they can be used for user answers.

## Decision

Use a feature-flagged AI Agent QA workflow for user chat:

- Ingestion remains governed: upload processing stops at review; only approved,
  latest active records are sync candidates for RAGFlow.
- User chat uses a multi-step pipeline: backend scope guard, conversation
  context check and follow-up rewrite, query analysis, retrieval planning,
  multi-query RAGFlow retrieval, rerank, evidence building, response format
  planning, structured answer generation, answer schema verification with one
  repair round, critic review, optional retrieve-more loop, compliance
  formatting, UI render, and logging.
- Backend remains the policy owner for scope, access/source status filters,
  active/latest citations, cache, session memory, and audit logging. LLM stages
  may propose plans and content, but they do not bypass backend gates.
- Evidence building must produce an `evidence_pack` of verified claims with
  citations, missing-evidence markers, and conflicts. Drafting and critic steps
  consume this evidence pack instead of raw chunks.
- Procedure answers must pass a dedicated procedure compliance checker after the
  general critic. This checker validates required steps, conditions, forms,
  approvers when present, citations, version/source status, and conflicts.
- Answer generation produces a structured answer schema (`summary`, `steps`,
  `responsibilities`, `forms_records`, `notes`, `sources`) plus markdown. The
  frontend can render schema blocks directly instead of relying only on free-form
  markdown.
- Conversation memory is scoped to the current session and TTL. It stores the
  active document/topic, last answer style, recent steps, and citations so
  follow-up questions can be rewritten without asking the user again.
- The new path requires an OpenAI-compatible LLM and configured RAGFlow dataset
  allowlist. If either is missing, it fails closed with the standard no-source
  answer and logs a knowledge gap.
- Each run produces an `answer_run` state summary and persists it to the local
  quality database with stage, retrieval/revision rounds, evidence status,
  quality status, and final confidence.
- The UI may stream safe trace events, including intent, query variants, filters,
  source counts, and critic decisions. It must not expose hidden chain-of-thought
  or internal prompts.
- Rollout is controlled by `KB_QA_AGENT_WORKFLOW_ENABLED`; the previous chat
  path remains available when the flag is off.

## Consequences

Positive:

- Better answer quality through retrieval planning, reranking, and critic checks.
- Safer failures for missing context, missing evidence, and unsupported claims.
- Realtime trace gives users and operators a clearer view of what happened.
- The feature flag keeps rollback simple.

Negative:

- Requires live LLM and RAGFlow configuration for the new path.
- More moving parts than the previous request/response workflow.
- Latency is higher; V1 targets a balanced 20 second budget with at most two
  retrieve-more loops.

## Implementation Notes

- Configure dataset scope with `RAGFLOW_DATASET_ALLOWLIST` or
  `RAGFLOW_ACTIVE_DATASET_IDS`; `RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID` remains a
  fallback single dataset.
- RAGFlow retrieval uses metadata filters for active approved/latest content.
- SSE trace uses `/api/user/chat/stream`; `/api/user/chat` remains compatible.
- Public citations are sanitized before display and must not expose local paths.
- Public trace and payloads may show evidence claims and compliance summaries,
  but never raw model prompts or hidden chain-of-thought.
