# Goal Prompt: LLM Block Answer Orchestration

Use this as a long-run Codex `/goal` prompt. It is intentionally outcome-driven and bounded: the agent should finish the chatbot orchestration capability, prove it with replay/eval, and stop when the evidence is complete.

```text
/goal Make demo-chatbot-engineerworkflow run a GPT-5.4-powered user-chat answer orchestration workflow on branch codex/rebuild-ragflow-ingestion, with RAGFlow-grounded retrieval, safe scope/clarification handling, renderable visual answer blocks, bounded LLM self-check/repair loops, legacy API compatibility, replayable handoff evidence, and pytest/render-smoke verification through docs/superpowers/plans/2026-05-28-llm-block-answer-orchestration.md.

Onboard into D:\MyProject\demo-chatbot-engineerworkflow as the User Chat Answer Orchestration Super-Agent.

You are running under this active /goal:
Make demo-chatbot-engineerworkflow run a GPT-5.4-powered user-chat answer orchestration workflow on branch codex/rebuild-ragflow-ingestion, with RAGFlow-grounded retrieval, safe scope/clarification handling, renderable visual answer blocks, bounded LLM self-check/repair loops, legacy API compatibility, replayable handoff evidence, and pytest/render-smoke verification through docs/superpowers/plans/2026-05-28-llm-block-answer-orchestration.md.

Branch and Git Safety:
- Work on branch codex/rebuild-ragflow-ingestion unless the user explicitly redirects.
- The worktree may already be dirty. Inspect `git status --short` before edits.
- Preserve existing changes in poc_workflow/chatbot.py, poc_workflow/llm.py, poc_workflow/ragflow_http.py, scripts/start-app.ps1, tests/test_webapp.py, refs/ragflow/docker/service_conf.yaml.template, and docs/superpowers/** unless you understand and intentionally build on them.
- Do not run destructive git commands such as reset, checkout --, or clean.
- Do not commit or push unless the user explicitly asks.

Required Boot / Read Order:
1. Read the thread-provided AGENTS.md instructions if present in context; if an AGENTS.md file exists in the repo, read it.
2. Read docs/superpowers/plans/2026-05-28-llm-block-answer-orchestration.md.
3. Use CodeGraph first for architecture context around:
   - poc_workflow/qa_agent_workflow.py
   - poc_workflow/user_chat.py
   - poc_workflow/static/user/user-chat.js
   - poc_workflow/user_chat_render_smoke.py
   - tests/test_webapp.py
4. Use `rg` only for literal text search such as field names, test IDs, API routes, and renderer class names.
5. Do not broad-read refs/ragflow, generated output folders, caches, or unrelated docs.

Source of Truth:
- Current code and tests are authoritative.
- The implementation plan in docs/superpowers/plans/2026-05-28-llm-block-answer-orchestration.md is the phase contract.
- RAGFlow remains the knowledge retrieval engine; the app remains the workflow, QA, and render contract orchestrator.
- GPT-5.4 is the intended primary LLM runtime, but tests must not require a live external LLM unless explicitly marked as live smoke.
- Do not trust chat summaries over current files and fresh command output.

Target End State:
After this phase, the system must prove:
1. `/api/user/chat` can return natural chat answers plus `response_contract_version="answer_blocks.v1"`.
2. Answers include legacy fields (`answer`, `format_plan`, `structured_answer`, `citations`, `trace_steps`) and new fields (`blocks`, `block_plan`, `handoff` when applicable) without breaking existing UI/tests.
3. The question analyzer can classify answerable, ambiguous, follow-up, out-of-scope, jailbreak-mixed, and no-evidence questions.
4. The block planner returns true/false decisions with reasons for block types: summary, clarification, scope_reject, steps, checklist, workflow, table, form, listing, decision_matrix, warnings, sources.
5. Factual answer blocks are grounded in citations/source anchors, or the workflow returns clarification/no-answer/scope-reject blocks.
6. The LLM QA loop is bounded: at most two retrieval rounds and one repair round.
7. The frontend can render new answer blocks directly and falls back to the existing structured answer renderer.
8. Replay/eval scenarios cover known procedure answers, workflow rendering, form lookup, indecision/comparison, vague questions, out-of-scope questions, unknown vendor questions, jailbreak-mixed questions, and multi-turn follow-up.
9. Verification commands pass or produce a clear handoff explaining the remaining blocker.

Non-Goals and Hard Boundaries:
- Do not replace RAGFlow retrieval with a new vector database in this phase.
- Do not promote RAGFlow Chat Assistant as the main workflow engine.
- Do not build a full multi-agent runtime for every user turn.
- Do not remove or rename existing public API fields.
- Do not require network/live model access for normal unit tests.
- Do not expose API keys, runtime tokens, hidden prompts, local secrets, or private config values in answers, logs, or replay files.
- Do not fabricate answers for out-of-scope or no-evidence questions.

Implementation Sequence:
Checkpoint 1 - Contract and tests:
- Add tests for `answer_blocks.v1`, `block_plan`, and `blocks`.
- Add backend helpers for block types, block plan normalization, and block normalization.
- Verification: targeted pytest for new contract tests.

Checkpoint 2 - Analyzer and block planner:
- Extend deterministic and LLM-assisted question analysis for scope, ambiguity, structured query, retrieval queries, and user-facing clarifying questions.
- Add deterministic block planner with true/false decisions and reasons.
- Keep sources enabled for factual answer cases.
- Verification: analyzer/block planner tests pass.

Checkpoint 3 - Draft, verify, repair:
- Update structured answer drafting to include `blocks`.
- Update verifier rules so every factual block must be source-backed.
- Add bounded retrieval/repair loop counters.
- Return `handoff` diagnostics when the loop exhausts.
- Verification: QA loop tests pass.

Checkpoint 4 - API compatibility:
- Expose `response_contract_version`, `blocks`, `block_plan`, and `handoff` through `user_chat_response()` and `/api/user/chat`.
- Preserve existing public fields and existing tests.
- Verification: targeted webapp tests pass.

Checkpoint 5 - Frontend rendering:
- Render `blocks` first in `poc_workflow/static/user/user-chat.js`.
- Keep fallback to existing `structured_answer`.
- Add CSS for summary, clarification, scope reject, steps/checklist, workflow, table, form, listing, decision matrix, warnings, and sources.
- Verification: render smoke passes or skips only if no browser exists.

Checkpoint 6 - Replay/eval and tuning:
- Create `eval/user_chat_orchestration_cases.json`.
- Create `poc_workflow/user_chat_replay.py`.
- Replay scenarios and write `.runtime/user-chat-replay.json`.
- Group failures as analysis_failure, retrieval_failure, block_plan_failure, draft_failure, verify_failure, render_failure.
- Tune only the failing layer.
- Verification: replay passes blocker scenarios.

Verification Matrix:
- `python -m pytest tests/test_user_chat_orchestration.py -q`
- `python -m pytest tests/test_webapp.py -q`
- `python -m compileall poc_workflow`
- `python -m poc_workflow.user_chat_replay --cases eval/user_chat_orchestration_cases.json`
- `python -m poc_workflow.user_chat_render_smoke`
- If RAGFlow/local services are running, optionally smoke `/api/user/chat` with one answerable procedure question and one vague question.

Checkpoint / Self-Check Loop:
After each checkpoint:
1. Run the scoped verification command.
2. Inspect failures and classify the layer that failed.
3. Fix only that layer.
4. Update or create a short handoff note in `.runtime/user-chat-orchestration-handoff.md` with:
   - completed checkpoint
   - files changed
   - commands run
   - failing tests or blockers
   - next exact step

Resumable Execution Rule:
- Do not wait until final closeout to create durable progress evidence.
- After each major checkpoint, update `.runtime/user-chat-orchestration-handoff.md`.
- If context compaction, app interruption, model quota, or time limit blocks progress, stop after preserving the latest handoff and report the exact resume point.
- If a live GPT-5.4 or RAGFlow service is unavailable, keep unit tests deterministic and mark live checks as skipped/blocked with exact reason.

Stop Conditions:
Stop when all required verification commands pass or when the same external blocker prevents progress after preserving a handoff.
Do not stop after only implementing code; stop only after verification evidence exists.

Final Answer Contract:
Report:
- outcome status
- files changed
- verification commands and pass/fail/skip results
- replay summary by scenario category
- whether `/api/user/chat` is backward compatible
- any remaining handoff or live-service blocker
- exact local URL if a web server is running
```

## SMART Check

- Specific: targets `/api/user/chat`, block schema, QA loop, replay, and renderer.
- Measurable: explicit verification matrix and scenario pass criteria.
- Achievable: extends existing `qa_agent_workflow.py` and `user-chat.js` instead of rebuilding the stack.
- Relevant: directly supports natural chatbot answers with visual block rendering.
- Time-bound/Bounded: checkpointed implementation with stop conditions and loop budgets.

