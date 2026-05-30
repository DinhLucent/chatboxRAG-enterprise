# 🗺️ System Architecture Workflows — End-to-End RAG Q&A System

Tài liệu này trực quan hóa toàn bộ hoạt động của hệ thống từ lúc tiếp nhận tài liệu thô (raw sources) cho đến khi sinh kết quả trả về cho người dùng (user response). Các sơ đồ được chia thành 3 cấp độ:
- **Macro-Level System Pipeline**: Dòng chảy tổng quan của hệ thống.
- **Ingestion & Data Preparation Micro-Workflows**: Chi tiết quá trình xử lý, kiểm định QA và đóng gói dữ liệu RAG-ready.
- **Query, Retrieval & Generation Micro-Workflows**: Chi tiết quá trình định tuyến câu hỏi, chấm điểm tìm kiếm cục bộ và tạo câu trả lời (Mermaid flowcharts, checklists).

---

## 1. Macro-Level System Pipeline (Tổng Quan End-to-End)

Sơ đồ dưới đây thể hiện dòng dữ liệu từ tài liệu thô ban đầu (PDF, DOCX, XLSX) đi qua các bước chuyển đổi, kiểm định QA, phê duyệt của con người, xây dựng chỉ mục tìm kiếm và phục vụ API hội thoại.

```mermaid
flowchart TD
    subgraph INTAKE["1. Giai Đoạn Intake & Processing (pipeline.py)"]
        Raw["Thư mục nguồn:<br/>source/technical/&lt;category&gt;/"]
        Meta["Metadata đi kèm:<br/>*.metadata.json"]
        Workplace[".Workplace/processing/<br/>(Tạm thời)"]
    end

    subgraph CONVERSION["2. Giai Đoạn Chuyển Đổi & Kiểm Định"]
        MinerU["MinerU Converter / OCR"]
        Norm["normalized/technical/&lt;category&gt;/*.md"]
        QA["QA Source Quality Auditor<br/>(document_qa.py)"]
    end

    subgraph PACKAGING["3. Đóng Gói RAG-Ready & Quản Trị (data_workflow.py)"]
        RAGReady["rag_ready/technical/&lt;category&gt;/<br/>- normalized.md<br/>- schema_manifest.json<br/>- citation_manifest.json<br/>- index_manifest.json"]
        Staging["staging/technical/&lt;category&gt;/"]
        ManifestDB[("manifest/records.json<br/>(pending_review)")]
        HumanReview{{"Human Review Gate<br/>(approve_record)"}}
        ActiveDB[("manifest/records.json<br/>(active)")]
    end

    subgraph INDEXING["4. Xây Dựng Chỉ Mục Cục Bộ (rag_index.py)"]
        LocalIndex["ragflow_index/technical_active.jsonl<br/>(431 Chunks)"]
    end

    subgraph QUERY_FLOW["5. Hội Thoại & Trả Kết Quả (chatbot.py)"]
        QueryInput(["Câu hỏi của User"])
        Chatbot["Chatbot Engine / Engine Router"]
        LLM["OpenAI-Compatible LLM API"]
        LocalAnswer["Deterministic Answer Builder<br/>(build_answer)"]
        Response(["Kết quả cuối cùng<br/>(Summary + Mermaid / Checklist + Citations)"])
    end

    %% Data Flow
    Raw & Meta --> Workplace
    Workplace --> MinerU
    MinerU --> Norm
    Norm --> QA
    QA -->|Passed| RAGReady
    RAGReady --> Staging
    Staging --> ManifestDB
    ManifestDB --> HumanReview
    HumanReview -->|Approve| ActiveDB
    ActiveDB -->|rebuild_indexes| LocalIndex
    
    QueryInput --> Chatbot
    LocalIndex -.->|search| Chatbot
    Chatbot -->|use_llm=true| LLM
    Chatbot -->|use_llm=false / LLM Error| LocalAnswer
    LLM & LocalAnswer --> Response

    %% Styling
    style INTAKE fill:#f9f9f9,stroke:#333,stroke-width:1px
    style CONVERSION fill:#fff5e6,stroke:#ff9900,stroke-width:1px
    style PACKAGING fill:#e6f2ff,stroke:#0066cc,stroke-width:1px
    style INDEXING fill:#e6ffe6,stroke:#009900,stroke-width:1px
    style QUERY_FLOW fill:#fff0f5,stroke:#cc0066,stroke-width:1px
    style HumanReview fill:#ffffcc,stroke:#cccc00,stroke-width:2px
```

---

## 2. Ingestion & Data Preparation Micro-Workflows

Quy trình chuẩn bị dữ liệu chịu trách nhiệm kiểm tra cấu trúc, chuyển đổi tài liệu thô thành Markdown chuẩn hóa, kiểm định tính toàn vẹn và ánh xạ chính xác tọa độ trích xuất nguồn từ MinerU (bounding boxes) làm căn cứ trích dẫn.

### 2.1 Chi tiết Hàm `process_sources()` & Handoff Transitions

Mỗi tài liệu đi qua một chuỗi các bước được quản lý bởi Handoff Contract (`workflow/handoffs.jsonl`). Sơ đồ này mô tả chi tiết các check gates và xử lý ngoại lệ:

```mermaid
flowchart TD
    Start["Bắt đầu process_sources()"] --> Iterate["Duyệt qua từng source_file"]
    Iterate --> CheckMeta{"Có *.metadata.json?"}
    
    CheckMeta -->|Không| FailMeta["Ném lỗi ManifestError<br/>Trạng thái: failed_review"]
    CheckMeta -->|Có| ValidateMeta["validate_metadata(metadata)"]
    
    ValidateMeta --> CheckChange{"Trùng content_hash trong<br/>manifest/records.json?"}
    CheckChange -->|Trùng| SkipDoc["Bỏ qua (skipped_unchanged)<br/>Di chuyển sang inbox/category/done/"]
    CheckChange -->|Khác| Workplace["Sao chép file vào .Workplace/processing/<br/>Ghi nhận trạng thái: processing"]
    
    Workplace --> StepPlan["1. Ghi nhận Handoff step=plan<br/>next_skill=mineru-source-converter"]
    StepPlan --> ConvertDoc["2. Chạy MinerU Converter<br/>convert_with_optional_status()"]
    
    ConvertDoc --> StepConvert["3. Ghi nhận Handoff step=convert<br/>next_skill=source-output-quality-auditor"]
    StepConvert --> AuditDoc["4. Kiểm định QA chống nhiễu chữ<br/>qa_source_output()"]
    
    AuditDoc --> CheckQA{"qa_report.status == 'fail'?"}
    CheckQA -->|Có| StepAuditRepair["5. Ghi nhận Handoff step=audit<br/>status=needs_repair<br/>next_skill=rag-markdown-repairer"]
    StepAuditRepair --> FailQA["Ném lỗi ConversionError<br/>Di chuyển sang inbox/category/failed/"]
    
    CheckQA -->|Không| StepAuditPass["5. Ghi nhận Handoff step=audit<br/>status=passed<br/>next_skill=ragflow-schema-indexer"]
    StepAuditPass --> BuildPkg["6. Đóng gói build_rag_ready_package()"]
    
    BuildPkg --> StepIndex["7. Ghi nhận Handoff step=index<br/>status=passed<br/>next_skill=data-skill-evolution"]
    StepIndex --> StepEvolve["8. Ghi nhận Handoff step=evolve<br/>status=passed<br/>next_skill=None"]
    
    StepEvolve --> SaveStaged["9. Sao chép nguồn vào staging/<br/>Lưu bản ghi với status=pending_review<br/>Dọn dẹp .Workplace/processing/"]
    SaveStaged --> NextDoc["Chuyển sang file tiếp theo"]

    %% Exception Handling Connection
    FailMeta & FailQA --> Cleanup["Dọn dẹp .Workplace/processing/<br/>Di chuyển nguồn sang failed/"]
    Cleanup --> NextDoc
```

### 2.2 Micro-Workflow Đóng Gói RAG-Ready (`build_rag_ready_package`)

Khi tài liệu vượt qua vòng kiểm duyệt chất lượng QA, hệ thống thực hiện phân mảnh (chunking) và ánh xạ trích dẫn thông tin địa chỉ từ MinerU JSON hoặc PDF/XLSX:

```mermaid
flowchart TD
    StartPkg["Nhận tham số: metadata, source_path, normalized_path, qa_report"] --> CopyMD["1. Sao chép normalized_path -> normalized.md"]
    CopyMD --> ChunkMD["2. Phân mảnh Markdown thành chunks<br/>chunk_markdown_with_metadata()<br/>(Tối đa 1200 ký tự, giữ nguyên khối bảng)"]
    
    ChunkMD --> BuildSections["3. Trích xuất mục tiêu chỉ mục tiêu đầu trang<br/>build_section_index()<br/>(heading_level & line_start/line_end)"]
    
    BuildSections --> MapBlocks["4. Phân tích khối nguồn MinerU<br/>mineru_source_blocks() / source_evidence_blocks()"]
    
    MapBlocks --> LoopChunks["5. Duyệt qua từng chunk để dựng Citation Map"]
    
    LoopChunks --> BestMatch["Tìm khối nguồn trùng khớp nhất<br/>best_source_match()<br/>(Tính tỷ lệ recall/precision từ từ vựng ý nghĩa)"]
    
    BestMatch --> BuildCitation["Tạo citation record:<br/>- chunk_id & anchor_id<br/>- source_locator (page, bbox, image_ref)<br/>- locator_confidence & locator_status"]
    
    BuildCitation --> LoopNext{"Còn chunk?"}
    LoopNext -->|Có| LoopChunks
    
    LoopNext -->|Không| CalcCoverage["6. Tính toán tỷ lệ bao phủ định danh trích dẫn<br/>citation_locator_coverage()"]
    
    CalcCoverage --> WriteManifests["7. Ghi nhận file JSON vào thư mục gói:<br/>- schema_manifest.json (Taxonomy & metadata)<br/>- citation_manifest.json (Các trích dẫn liên kết)<br/>- index_manifest.json (Nội dung chunks & text_hash)"]
    
    WriteManifests --> ReturnPkg["Trả về thông tin package_root và các liên kết đường dẫn"]
```

### 2.3 Quy Trình Duyệt & Tái Tạo Chỉ Mục Tìm Kiếm (`approve_record`)

```mermaid
sequenceDiagram
    actor Reviewer as Human Reviewer
    participant pipeline as pipeline.py
    participant manifest as manifest/records.json
    participant index as rag_index.py
    participant active_index as ragflow_index/technical_active.jsonl

    Reviewer->>pipeline: Gọi approve_record(doc_id, version, approved_by)
    pipeline->>manifest: Đọc thông tin bản ghi hiện tại
    
    rect rgb(230, 245, 255)
        Note over pipeline, manifest: Quản lý phiên bản ghi đè (supersession)
        pipeline->>manifest: Tìm bản ghi cũ đã active cùng doc_id
        pipeline->>manifest: Đổi trạng thái bản ghi cũ thành 'archived'
        pipeline->>manifest: Đặt supersedes = "doc_id_v{old_version}"
    end
    
    pipeline->>manifest: Cập nhật trạng thái bản ghi mới thành 'active'
    pipeline->>pipeline: Gọi rebuild_indexes()
    pipeline->>manifest: Tải tất cả các bản ghi có trạng thái 'active'
    
    loop Với từng bản ghi active
        pipeline->>index: Gọi LocalRagIndex.rebuild()
        index->>index: chunk_markdown_with_metadata(normalized.md)
        index->>active_index: Ghi đè thông tin chunks sạch (đã lọc nhiễu văn bản)
    end
    
    pipeline-->>Reviewer: Trả về bản ghi đã phê duyệt thành công
```

---

## 3. Query, Retrieval & Generation Micro-Workflows

Quy trình này điều hướng câu hỏi người dùng, tìm kiếm nguồn tương đồng trong cơ sở tri thức cục bộ và định dạng câu trả lời theo các kịch bản trình bày trực quan.

### 3.1 Quy Trình Định Tuyến & Sinh Câu Trả Lời (`ask()`)

```mermaid
flowchart TD
    StartAsk["Nhận câu hỏi (Query) từ User"] --> InferredStyle["1. Phân tích kịch bản trả lời<br/>infer_query_answer_style()<br/>(brief / steps / checklist / workflow)"]
    InferredStyle --> InferredDept["2. Phân tích phòng ban liên quan<br/>infer_department()<br/>(Heuristics khớp từ khóa & mã tài liệu)"]
    InferredDept --> InferredCat["3. Phân tích loại tài liệu đích<br/>infer_category()<br/>(procedure / vendor_document / ...)"]
    
    InferredCat --> ScopeCheck{"4. Kiểm tra Out-of-Scope?<br/>is_out_of_scope_query()"}
    
    ScopeCheck -->|Đúng| RespNoSource["Trả về: Không tìm thấy căn cứ.<br/>Tạo bản ghi khoảng trống tri thức (knowledge_gap)"]
    
    ScopeCheck -->|Sai| CatalogCheck{"5. Hỏi danh mục quy trình?<br/>is_procedure_catalog_query()"}
    
    CatalogCheck -->|Đúng| CatalogAns["Tự động trả về danh sách quy trình<br/>build_catalog_answer()<br/>(Không cần gọi LLM)"]
    
    CatalogCheck -->|Sai| ProviderCheck{"6. Cấu hình Provider?"}
    
    ProviderCheck -->|ragflow| RAGFlowRoute["Gửi yêu cầu API đến RAGFlow HTTP<br/>answer_with_ragflow()"]
    ProviderCheck -->|local / fallback| LocalSearch["Truy vấn LocalRagIndex.search()"]
    
    RAGFlowRoute --> CheckRAGFlow{"Thành công?"}
    CheckRAGFlow -->|Có| RespRAGFlow["Trả về câu trả lời RAGFlow"]
    CheckRAGFlow -->|Không| FallbackLocal["Chuyển đổi dự phòng: Gọi Local search"]
    
    LocalSearch & FallbackLocal --> FilterHits["7. Lọc kết quả tự tin confident_hits()<br/>(Giới hạn điểm tối thiểu >= 8)<br/>8. Khớp tiêu điểm tài liệu focus_hits_for_query()"]
    
    FilterHits --> CheckHits{"Có chunk kết quả?"}
    CheckHits -->|Không| RespNoSource
    CheckHits -->|Có| LLMCheck{"9. Kích hoạt use_llm?"}
    
    LLMCheck -->|Có| CallLLM["Gửi prompt kèm chunks tới LLM<br/>OpenAICompatibleClient.answer()"]
    LLMCheck -->|Không| CallDeterministic["Tạo câu trả lời tĩnh cục bộ<br/>build_answer()"]
    
    CallLLM --> CheckDirty{"Kết quả LLM chứa mã lỗi / HTML bẩn?"}
    CheckDirty -->|Có| CallCleanLLM["Gọi LLM lần 2 với prompt làm sạch"]
    CheckDirty -->|Không| RespFinal["Trả về câu trả lời hoàn thiện"]
    
    CallCleanLLM --> CheckDirty2{"Vẫn bẩn?"}
    CheckDirty2 -->|Có| CallDeterministic
    CheckDirty2 -->|Không| RespFinal
    
    CallDeterministic --> RespFinal
```

### 3.2 Micro-Workflow Tìm Kiếm & Chấm Điểm Thô (`LocalRagIndex.search()`)

Bản chất của tìm kiếm local là quét toàn bộ tập tin `ragflow_index/*.jsonl` để chấm điểm dựa trên độ tương đồng từ vựng và 7 yếu tố hiệu chỉnh ngữ cảnh (adjustments):

```mermaid
flowchart TD
    StartSearch["Bắt đầu search(query)"] --> LoadEntries["1. Đọc dữ liệu chunks active.jsonl<br/>( meaningful_terms(query) )"]
    LoadEntries --> LoopEntries["2. Duyệt qua từng Chunk Entry"]
    
    LoopEntries --> FilterActive{"Status == active?"}
    FilterActive -->|Sai| SkipEntry["Bỏ qua"]
    FilterActive -->|Đúng| FilterDept{"Khớp Department/Category?"}
    
    FilterDept -->|Sai| SkipEntry
    FilterDept -->|Đúng| CalcOverlap["3. Tính điểm phủ từ khóa thô:<br/>score = (title_overlap * 4) + text_overlap"]
    
    CalcOverlap --> CheckDocCode{"4. Có khớp mã tài liệu rõ ràng?"}
    CheckDocCode -->|Có| BoostDocCode["Cộng điểm cực lớn +250"]
    CheckDocCode -->|Không| AdjQuality["5. Hiệu chỉnh chất lượng: quality_adjustment()"]
    BoostDocCode --> AdjQuality
    
    AdjQuality --> AdjStructured["6. Hiệu chỉnh cấu trúc: structured_procedure_section_adjustment()"]
    AdjStructured --> AdjIntent["7. Hiệu chỉnh ý đồ câu hỏi: query_intent_adjustment()"]
    AdjIntent --> AdjTopic["8. Hiệu chỉnh chủ đề: procedure_topic_adjustment()"]
    AdjTopic --> AdjSource["9. Hiệu chỉnh loại file: source_role_adjustment()"]
    
    AdjSource --> CheckScore{"Score > 0?"}
    CheckScore -->|Có| AppendHit["Đưa vào tập kết quả SearchHit"]
    CheckScore -->|Không| SkipEntry
    
    AppendHit --> LoopNext{"Còn chunk tiếp theo?"}
    LoopNext -->|Có| LoopEntries
    LoopNext -->|Không| SortHits["10. Sắp xếp giảm dần theo điểm số<br/>Lấy tối đa limit=20 kết quả"]
```

### 3.3 Công Thức Tính Điểm Chi Tiết (Heuristic Adjustments)

Để bảo đảm câu trả lời tập trung đúng phần nội dung công việc hơn là các phần thông tin hành chính, điểm số thô được hiệu chỉnh qua các logic sau:

```
[Điểm Cuối Cùng] = Điểm Thô + [Hiệu Chỉnh Chất Lượng] + [Hiệu Chỉnh Cấu Trúc] + [Hiệu Chỉnh Ý Đồ] + [Hiệu Chỉnh Chủ Đề] + [Hiệu Chỉnh Loại File] + [Mã Tài Liệu Boost]
```

| Tên Bộ Hiệu Chỉnh | Điều Kiện & Logic Chấm Điểm | Giá Trị Điểm |
| :--- | :--- | :--- |
| **Mã Tài Liệu Boost** | Khớp chính xác mã tài liệu (VD: `PD-TECH-A-01` hoặc `KT-QT-003`) | **+250** |
| **Hiệu Chỉnh Chất Lượng** | Gặp từ khóa nhiễu OCR (`low_hits`) hoặc chứa bảng lịch sử sửa đổi | **-30** |
| | Chunk thuộc trang danh mục tổng hợp tài liệu viết tắt | **-30** |
| | Câu hỏi chứa quy trình và chunk chứa bảng "Nội dung công việc" | **+18** |
| | Chunk chứa bảng biểu STT dòng số `1 \|` (điểm bắt đầu bước quy trình) | **+35** |
| **Hiệu Chỉnh Cấu Trúc** | Trích xuất các bước thủ tục: Chunks chứa tiêu đề "Quy trình thực hiện" kèm số thứ tự | **+95** |
| | Trích xuất các bước thủ tục: Chunk chỉ chứa "Tóm tắt cấu trúc phục vụ RAG" | **-90** |
| | Hỏi về hồ sơ/biểu mẫu: Chunks chứa tiêu đề "Hồ sơ / Biểu mẫu" hoặc code `BM-` | **+85** |
| | Hỏi về vai trò/trách nhiệm: Chunks chứa tiêu đề "Trách nhiệm" hoặc bảng RACI | **+85** |
| **Hiệu Chỉnh Ý Đồ** | Khớp mục đích (`+70`), phạm vi áp dụng (`+70`), trách nhiệm thực hiện (`+65`), điều kiện lắp đặt (`+65`), biên bản ký nhận dịch vụ (`+70`), yêu cầu dự trữ vật tư (`+65`), hiệu chuẩn ccdc (`+40`), chứng chỉ đào tạo (`+55`). Nếu không khớp các từ khóa chính đi kèm | **+40 đến +70**<br>*(Phạt **-25** nếu sai ý đồ)* |
| **Hiệu Chỉnh Chủ Đề** | Khớp từ khóa chủ đề trong tiêu đề tài liệu (`lắp đặt`, `bảo dưỡng`, `sửa chữa`, `đào tạo`, `hiệu chuẩn`) | **+55**<br>*(Phạt **-55** nếu lệch)* |
| **Hiệu Chỉnh Loại File** | Hỏi về bước thủ tục nghiệp vụ $\rightarrow$ Ưu tiên văn bản chính | **+18** cho PDF |
| | Hỏi về bảng biểu mẫu, cấu trúc mẫu tính toán $\rightarrow$ Ưu tiên file đính kèm | **+14** cho XLSX |
| | Hỏi về bước quy trình thực hiện nhưng trúng chunk XLSX | **-18** cho XLSX |

---

## 4. Quy Trình Chuyển Đổi Định Dạng Trả Về (Response Style Visualizer)

Khi nhận tập các chunks tốt nhất từ `LocalRagIndex`, hàm `build_answer()` hoặc `OpenAICompatibleClient` sẽ chuyển đổi các câu văn thô trong chunk thành kịch bản hiển thị đẹp mắt tương ứng với `answer_style` được yêu cầu:

```mermaid
flowchart TD
    StartBuild["Nhận hits và answer_style"] --> DetectTable{"Có chứa bảng\n'nội dung công việc'?"}
    
    DetectTable -->|Có| ExtractTable["Trích xuất hàng dọc từ bảng\nprocedure_table_points()"]
    DetectTable -->|Không| ExtractSentences["Trích xuất câu độc lập quan trọng\nrelevant_answer_points()"]
    
    ExtractTable & ExtractSentences --> FilterNoise["Lọc bỏ câu nhiễu (dòng quá ngắn, mã số STT rỗng)\nis_answer_candidate_noise()"]
    
    FilterNoise --> StyleRoute{"Lựa chọn style hiển thị"}
    
    StyleRoute -->|workflow| WorkflowStyle["Tạo sơ đồ Mermaid TD\nmermaid_flowchart()\nHiển thị danh sách bước bên dưới"]
    StyleRoute -->|steps| StepsStyle["Hiển thị danh sách đánh số dạng:\n1. Bước một...\n2. Bước hai..."]
    StyleRoute -->|checklist| ChecklistStyle["Hiển thị danh sách checkbox dạng:\n- [ ] Nội dung công việc một...\n- [ ] Nội dung công việc hai..."]
    StyleRoute -->|brief / default| BriefStyle["Hiển thị tóm tắt ngắn gọn dạng danh sách:\n- Nội dung một...\n- Nội dung hai..."]
    
    WorkflowStyle & StepsStyle & ChecklistStyle & BriefStyle --> AppendSources["Nối thông tin trích dẫn gốc (Nguồn)\nDạng: display_code / doc_id version"]
    AppendSources --> ReturnOutput["Trả về câu trả lời hoàn chỉnh dạng Markdown"]
```

### Ví dụ định dạng trả về theo từng loại Style:

````carousel
```markdown
### 1. Workflow Style (Biểu đồ + Bước thực hiện)

Tóm tắt:
PD-TECH-A-01: Quy trình lắp đặt thiết bị gồm các bước khảo sát và thi công.

Workflow:
```mermaid
flowchart TD
    S1["Khảo sát vị trí lắp đặt"]
    S2["Chuẩn bị vật tư thiết bị"]
    S3["Tiến hành thi công lắp ráp"]
    S4["Nghiệm thu và bàn giao"]
    S1 --> S2
    S2 --> S3
    S3 --> S4
```

Các bước / Nội dung chính:
1. Khảo sát vị trí lắp đặt
2. Chuẩn bị vật tư thiết bị
3. Tiến hành thi công lắp ráp
4. Nghiệm thu và bàn giao

Nguồn:
PD-TECH-A-01 / KT-QT-001 v1.0
```
<!-- slide -->
```markdown
### 2. Steps Style (Danh sách các bước có thứ tự)

Tóm tắt:
Các bước thực hiện bảo dưỡng định kỳ thiết bị kỹ thuật theo đúng tiêu chuẩn vận hành.

Các bước / Nội dung chính:
1. Tiếp nhận yêu cầu bảo dưỡng từ bộ phận dịch vụ khách hàng.
2. Lập kế hoạch bảo dưỡng định kỳ chi tiết gửi khách hàng phê duyệt.
3. Kỹ thuật viên chuẩn bị công cụ dụng cụ và vật tư thay thế.
4. Thực hiện các thao tác vệ sinh, đo đạc và căn chỉnh thiết bị.
5. Ký nghiệm thu biên bản dịch vụ kỹ thuật và cập nhật lịch sử thiết bị.

Nguồn:
PD-TECH-A-02 / KT-QT-002 v2.0
```
<!-- slide -->
```markdown
### 3. Checklist Style (Danh sách kiểm tra công việc)

Tóm tắt:
Danh sách các biểu mẫu và hồ sơ bắt buộc phải chuẩn bị đầy đủ trước khi bàn giao thiết bị.

Các bước / Nội dung chính:
- [ ] Điền thông tin khách hàng vào biên bản dịch vụ kỹ thuật (BM-012)
- [ ] Chụp ảnh hiện trạng lắp đặt tại phòng lab của khách hàng
- [ ] Ký xác nhận bàn giao thiết bị của đại diện kỹ thuật hãng
- [ ] Điền phiếu bàn giao công cụ dụng cụ kèm danh mục serial number

Nguồn:
PD-TECH-A-01 / KT-QT-001 v1.0
```
````
