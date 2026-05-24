# Demo End-To-End Architecture

This document describes the current demo architecture: Vercel is only the public interface, while data, retrieval, AI orchestration, logs, and document processing stay on the local/internal machine.

## Executive View

```mermaid
flowchart LR
    A["Ban Giám Đốc / Người dùng demo"] --> B["Trang web demo"]
    B --> C["Cửa trung gian bảo vệ"]
    C --> D["Máy xử lý nội bộ"]
    D --> E["Kho tài liệu đã duyệt"]
    D --> F["Bộ não AI"]
    D --> G["Nhật ký & phản hồi"]
    D --> H["Câu trả lời có nguồn"]
    H --> B
    B --> A

    I["Người cung cấp tài liệu"] --> J["Hộp nhận tài liệu"]
    J --> K["AI agent chuẩn hóa"]
    K --> L["Người phụ trách duyệt"]
    L --> E
```

Meaning:

- Public web only shows the demo interface.
- Internal machine owns the real processing.
- Only approved active documents are used for answers.
- Feedback creates improvement signals for the knowledge base.

## Technical Runtime View

```mermaid
flowchart LR
    subgraph PUBLIC["Public demo layer"]
        U["Browser<br/>Ban Giám Đốc"] --> VUI["Vercel static UI<br/>vercel-demo/index.html"]
        VUI --> VAPI["Vercel API proxy<br/>/api/chat, /api/health, /api/feedback"]
    end

    subgraph BRIDGE["Temporary secure bridge"]
        VAPI --> TUN["HTTPS tunnel<br/>localtunnel/ngrok/Cloudflare Tunnel"]
    end

    subgraph LOCAL["Local/internal computer"]
        TUN --> AUTH["Backend auth<br/>X-KB-Token"]
        AUTH --> API["Chatbot backend<br/>FastAPI on :8088"]

        API --> POLICY["Runtime policy<br/>active-only, citation required"]
        POLICY --> RET["Retrieval layer"]
        RET --> LIDX["Local active index<br/>POC fallback"]
        RET -. "future production" .-> RAG["RAG engine<br/>technical_active"]

        API --> LLM["LLM answer client<br/>OpenAI-compatible"]
        LLM --> FLLM["Local LLM proxy<br/>FreeLLMAPI on :3001"]
        FLLM --> EXT["External AI providers<br/>free-tier or paid"]

        API --> QDB["Quality database<br/>query logs, feedback, gaps"]
        API --> RESP["Answer payload<br/>answer + citations + log id"]
    end

    RESP --> TUN
    TUN --> VAPI
    VAPI --> VUI
    VUI --> U
```

## Document Processing View

```mermaid
flowchart TD
    A["User provides documents"] --> B["inbox/ or dashboard upload"]
    B --> C["AI agent prepares inbox"]
    C --> D["Draft metadata<br/>doc_id, category, version"]
    D --> E["source/technical/category"]
    E --> F["Document converter<br/>PDF, Excel, image, Word to Markdown/JSON"]
    F --> G["normalized/"]
    G --> H["Validation<br/>metadata, taxonomy, content, version"]
    H --> I["pending_review"]
    I --> J{"Human approval"}
    J -->|approve| K["active"]
    J -->|reject| L["failed_review"]
    K --> M["active retrieval index"]
    K -. "sync when configured" .-> N["Production RAG dataset"]
    L --> B
```

## Query Flow

```mermaid
sequenceDiagram
    participant User as User demo
    participant UI as Vercel UI
    participant Proxy as Vercel API proxy
    participant Tunnel as Secure tunnel
    participant Backend as Local chatbot backend
    participant Docs as Active documents
    participant Brain as AI brain
    participant Log as Quality log

    User->>UI: Ask a procedure question
    UI->>Proxy: POST /api/chat with demo token
    Proxy->>Tunnel: Forward with backend token
    Tunnel->>Backend: POST /api/chat
    Backend->>Docs: Retrieve approved active sources
    Backend->>Brain: Send question + selected context only
    Brain-->>Backend: Draft answer
    Backend->>Log: Store query, citations, latency
    Backend-->>Tunnel: Answer + citations + log id
    Tunnel-->>Proxy: Response
    Proxy-->>UI: Response
    UI-->>User: Display answer and source
```

## Security Boundaries

```mermaid
flowchart LR
    A["Browser"] -->|"Demo token only"| B["Vercel API proxy"]
    B -->|"Backend token from Vercel env"| C["Tunnel"]
    C --> D["Local backend"]
    D --> E["Internal files and logs"]

    A -. "No direct access" .- E
    B -. "No document storage" .- E
```

Key controls:

- Browser never receives the local backend token.
- Vercel demo does not store company documents.
- Local backend enforces operator token when auth is enabled.
- Only active approved documents are retrieved.
- Full document repository is not sent to the AI provider.

## Current Temporary Demo

```text
Vercel UI: https://vercel-demo-nu-gold.vercel.app
Backend tunnel: https://petite-islands-love.loca.lt
Local backend: http://127.0.0.1:8088
Local LLM proxy: http://127.0.0.1:3001
```

This is a temporary demo path. For production, replace the temporary tunnel with a controlled internal deployment or approved secure gateway.
