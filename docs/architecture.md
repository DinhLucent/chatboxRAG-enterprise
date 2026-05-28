# System Architecture

This product is a governed internal knowledge chatbot for company procedures. The core rule is strict:

```text
Only approved active documents can be used for user answers.
```

## Runtime Architecture

```mermaid
flowchart LR
    U["Internal user"] --> WEB["Chatbot dashboard<br/>FastAPI (Port :8088) + static UI"]
    WEB --> APP["poc_workflow API<br/>policy, logs, feedback"]
    APP --> RET["Retrieval layer"]
    RET --> LOCAL["Local JSONL index<br/>(ragflow_index/ fallback)"]
    RET --> RAG["RAGFlow technical_active<br/>(Port :9380)"]
    APP --> LLM["OpenAI-compatible LLM endpoint"]
    LLM --> FREE["LLM Gateway proxy<br/>(Port :3001)"]
    FREE --> P1["LLM7 / Pollinations<br/>anonymous or free tier"]
    FREE --> P2["Google / Groq / OpenRouter<br/>bring free-tier keys"]
    APP --> QDB["SQLite quality DB<br/>(data/poc_quality.db)"]
    APP --> UI["Answer with citations"]
    UI --> U
```

## Document Lifecycle

```mermaid
flowchart TD
    A["User uploads or drops files into inbox"] --> B["AI agent prepares inbox"]
    B --> C["source/technical/category"]
    C --> D["MinerU OCR (Port :8010)<br/>or text converter"]
    D --> E["normalized Markdown/JSON"]
    E --> F["Validate metadata, taxonomy, version, content"]
    F --> G["pending_review"]
    G --> H{"Human approval"}
    H -->|approve| I["active"]
    H -->|reject| J["failed_review"]
    I --> K["technical_active index<br/>(ragflow_index/)"]
    I --> L["RAGFlow sync (Port :9380)"]
    J --> B
    I --> M["archived or retired when superseded"]
```

## Source Of Truth

The durable source of truth is:

- `manifest/records.json`
- `normalized/`
- `source/`
- `eval/regression_cases.json`
- `data/poc_quality.db`

RAGFlow and the local JSONL index are rebuildable caches. Do not edit an index directly without updating the manifest.

## Main Components

- `poc_workflow.pipeline`: workspace init, conversion, validation, lifecycle, rebuild.
- `poc_workflow.intake`: inbox upload/drop workflow and draft metadata generation.
- `poc_workflow.ragflow_http`: RAGFlow dataset/chat bootstrap, sync, search/chat.
- `poc_workflow.chatbot`: retrieval policy, optional LLM answering, feedback gap creation.
- `poc_workflow.llm`: OpenAI-compatible chat completions client.
- `poc_workflow.webapp`: dashboard API and static UI.
- `poc_workflow.evaluation`: regression test harness and KPI reporting.

## Answer Flow

```text
User question
-> provider policy
-> RAGFlow if configured, otherwise local dev index
-> active-only retrieval
-> optional LLM answer generation from retrieved chunks
-> citation payload
-> query log
-> feedback / knowledge gap loop
```

If no valid source exists, the expected answer is:

```text
Không tìm thấy căn cứ trong tài liệu hiện hành.
```

## POC Taxonomy

```text
company
└── department
    └── technical
        ├── procedure
        ├── vendor_document
        ├── form_checklist
        └── faq_troubleshooting
```

## Production Intent

- RAGFlow is the production RAG engine candidate.
- MinerU is the document normalization engine.
- FreeLLMAPI is an optional OpenAI-compatible LLM proxy for free-tier testing.
- The owned app remains the governance, dashboard, quality loop, and integration layer.
