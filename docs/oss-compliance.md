# OSS Compliance Notes

This product keeps the owned governance/dashboard layer separate from upstream RAGFlow, MinerU, and FastGPT code.

## Current Reuse Model

- RAGFlow: used as an external RAG service through HTTP API and Docker deployment.
- MinerU: used as a document conversion tool through CLI execution.
- FreeLLMAPI: used as an optional external OpenAI-compatible LLM proxy for local demo/testing.
- FastGPT: used only as product/UX reference. No FastGPT source code, UI component, logo, or console design has been copied into this app.
- MaxKB/txtai: not used in the current implementation.

## Local License Findings

- `refs/ragflow/LICENSE`: Apache License 2.0.
- `refs/MinerU/LICENSE.md`: Apache License 2.0 with additional commercial threshold and online-service attribution terms.
- `refs/FastGPT/LICENSE`: Apache License 2.0 with additional commercial conditions for similar multi-tenant SaaS use, logo/copyright restrictions, and a note that the interactive design is protected by appearance patent.
- `refs/freellmapi/LICENSE`: MIT License.

## Production Rules

- Do not copy upstream UI, logos, visual console layouts, or source files unless legal review approves the exact reuse.
- Keep integrations API/CLI based where possible.
- Preserve upstream license files in `refs/` and deployment documentation.
- If MinerU powers a third-party online service, include clear MinerU attribution in product documentation or interface.
- Keep FreeLLMAPI provider keys, SQLite data, and `.env` outside git.
- Review each upstream LLM provider's terms separately; FreeLLMAPI does not replace provider terms.
- Re-check licenses before production because upstream terms can change.
- If the product becomes multi-tenant SaaS or customer-facing, complete legal review before launch.

## Go / No-Go

Go for internal POC:

- Self-hosted internal use.
- RAGFlow and MinerU used as separate tools/services.
- Owned dashboard and workflow code.

No-go without legal review:

- Copying FastGPT console UI or components directly.
- Removing upstream branding where license terms require it.
- Offering a similar multi-tenant SaaS product using upstream code.
- Exceeding MinerU commercial thresholds without separate license.
