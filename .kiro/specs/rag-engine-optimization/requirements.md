# Requirements Document

## Introduction

Tài liệu này mô tả yêu cầu cho spec **`rag-engine-optimization`** — một bước tối ưu hóa tiếp theo cho hệ thống RAG chatbot của phòng kỹ thuật, xây dựng *trên nền* spec `001-improve-rag-end-to-end` (đã cam kết: Qdrant hybrid + cross-encoder rerank + hierarchical chunking + lớp thử nghiệm `m_flow` + nới lỏng gating + LLM failover).

Mục tiêu của spec này **không phải** xây lại pipeline, mà là **đánh giá (evaluate) và áp dụng (adopt) các tùy chọn bổ sung** rút ra từ nghiên cứu các dự án tham chiếu trong thư mục `/refs`, nhằm tối ưu thêm hệ thống hiện có. Pipeline mục tiêu vẫn giữ nguyên:

```
MinerU → normalized Markdown/JSON → hierarchical chunking → Qdrant hybrid index
       → reranker → parent-context expansion → context composer
       → LLM answer with citation → QA guardrails
```

Các nhóm tùy chọn được nghiên cứu và đưa vào diện đánh giá:

1. **Retrieval / vector backend** — `turbovec` (Rust vector index in-process, nén 16x, hybrid filtered search trong SIMD kernel) như một fallback mạnh hơn so với `LocalRagIndex` thuần lexical, hoặc như một backend thay thế Qdrant cho triển khai air-gapped.
2. **Reasoning-based retrieval (vectorless)** — `OpenKB / PageIndex` biên dịch tài liệu thành wiki + cây phân cấp để LLM suy luận trên cấu trúc thay vì trên chunk; ứng viên cho lớp thử nghiệm phục vụ câu hỏi multi-hop/điều kiện/phụ thuộc (bổ sung/thay thế lớp `m_flow`).
3. **OCR fallback** — `PaddleOCR` (PP-Structure) làm phương án dự phòng cho tài liệu scan/chất lượng thấp khi MinerU OCR không đạt; vai trò thứ cấp, MinerU vẫn là parser chính.
4. **Answer-workflow observability & test harness** — mẫu hình từ `FastGPT` (test truy hồi đơn điểm, log toàn bộ chuỗi gọi, phản hồi citation trong hội thoại) và `MaxKB` (workflow engine, model-agnostic).
5. **LLM-layer robustness** — mẫu hình từ `freellmapi` (sticky session ~30 phút, sổ theo dõi rate per-key RPM/RPD/TPM/TPD, một endpoint failover hợp nhất) gập vào chuỗi failover hiện có trong `llm.py`.

**Nguyên tắc xuyên suốt:** nhiều hạng mục là *đánh giá tùy chọn / benchmark* (ví dụ turbovec vs Qdrant, PageIndex vs m_flow). Mọi tùy chọn đưa vào phải nằm sau cờ cấu hình (feature flag), **degrade gracefully**, và **không được làm mất ổn định lõi sản xuất** (Qdrant hybrid + rerank). Tier miễn phí của LLM không có model frontier và chất lượng suy giảm trong ngày, nên primary trả phí vẫn được giữ cho chất lượng.

## Glossary

- **RAG_Engine**: Toàn bộ hệ thống truy hồi + sinh câu trả lời của chatbot phòng kỹ thuật.
- **Retriever_Selector**: Thành phần chọn backend truy hồi tại runtime dựa trên cấu hình và tình trạng khả dụng (Qdrant / turbovec / lexical fallback).
- **Qdrant_Retriever**: Backend truy hồi hybrid (dense + sparse) trên Qdrant — lõi sản xuất đã cam kết ở spec 001.
- **Turbovec_Retriever**: Backend truy hồi vector in-process dựa trên thư viện `turbovec` (refs/turbovec), có Python bindings, hỗ trợ filtered/hybrid search qua id allowlist trong SIMD kernel.
- **Lexical_Fallback**: Bộ truy hồi lexical hiện có (`LocalRagIndex` trong `poc_workflow/rag_index.py`), giữ làm fallback offline.
- **Reasoning_Retrieval_Layer**: Lớp truy hồi thử nghiệm dựa trên suy luận, vectorless, theo mẫu `OpenKB / PageIndex` (refs/OpenKB).
- **PageIndex_Builder**: Thành phần biên dịch tài liệu thành wiki bền vững (tóm tắt + trang khái niệm liên kết chéo) và cây chỉ mục phân cấp.
- **OCR_Fallback**: Bộ OCR dự phòng dựa trên `PaddleOCR` PP-Structure (refs/PaddleOCR).
- **MinerU_Parser**: Parser chính của pipeline (giữ nguyên, không thay đổi).
- **Answer_Workflow**: Chuỗi xử lý retrieve → rerank → compose → answer trong `chatbot.py`.
- **Retrieval_Test_Harness**: Công cụ kiểm thử truy hồi đơn điểm (chạy một truy vấn qua từng stage và xem kết quả) theo mẫu FastGPT.
- **Call_Chain_Logger**: Thành phần ghi log per-stage cho toàn bộ chuỗi gọi (truy hồi → rerank → compose → LLM).
- **LLM_Router**: Lớp định tuyến LLM trong `poc_workflow/llm.py` (OpenAICompatibleClient + chuỗi failover).
- **Session_Manager**: Thành phần giữ "sticky session" — ghim một model cho một phiên hội thoại trong khoảng thời gian cấu hình để tránh đổi model giữa chừng.
- **Rate_Ledger**: Sổ theo dõi mức sử dụng per-key (RPM/RPD/TPM/TPD) để định tuyến và làm nguội (cooldown) khi vượt hạn mức.
- **Benchmark_Harness**: Bộ chạy benchmark so sánh các tùy chọn trên tập câu hỏi vàng và tập câu hỏi khó.
- **Feature_Flag_Manager**: Cơ chế cấu hình (`.env` / `config.py`) bật/tắt từng tùy chọn đang đánh giá.
- **Golden_Query_Set**: Tập truy vấn chuẩn có đáp án/nguồn kỳ vọng, dùng để đo chất lượng truy hồi và câu trả lời.
- **Hard_Question_Set**: Tập câu hỏi khó (multi-hop, điều kiện, ngoại lệ, phụ thuộc chéo thủ tục) dùng đánh giá các lớp suy luận thử nghiệm.
- **Production_Core**: Đường dẫn truy hồi sản xuất mặc định = Qdrant_Retriever + reranker + hierarchical schema.

## Requirements

### Requirement 1: Đánh giá và áp dụng backend truy hồi turbovec (P1)

**User Story:** As a backend engineer, I want to evaluate `turbovec` as a stronger local retrieval backend and as a Qdrant-free option for air-gapped deployment, so that the system has a faster local fallback than the lexical index and a viable no-service deployment path — without destabilizing the Qdrant production core.

#### Acceptance Criteria

1. THE Retriever_Selector SHALL hỗ trợ ba backend truy hồi có thể chọn qua cấu hình: Qdrant_Retriever, Turbovec_Retriever, và Lexical_Fallback.
2. WHERE Turbovec_Retriever được bật qua Feature_Flag_Manager, THE Turbovec_Retriever SHALL phục vụ truy hồi vector top-k (mặc định k=10) cho cùng tập chunk schema phân cấp đã định nghĩa ở spec 001.
3. WHERE Turbovec_Retriever được bật, WHEN một truy vấn kèm bộ lọc metadata (department, version, procedure, access group) được thực thi, THE Turbovec_Retriever SHALL trả về chỉ các chunk khớp toàn bộ giá trị metadata được chỉ định thông qua cơ chế id allowlist.
4. WHEN Qdrant_Retriever không phản hồi trong ngưỡng thời gian cấu hình (mặc định 5 giây) hoặc thất bại sau số lần thử lại cấu hình (mặc định 2) VÀ Turbovec_Retriever được cấu hình làm fallback, THE Retriever_Selector SHALL chuyển sang Turbovec_Retriever trước khi xuống Lexical_Fallback.
5. IF cả Qdrant_Retriever và Turbovec_Retriever đều không khả dụng, THEN THE Retriever_Selector SHALL chuyển sang Lexical_Fallback để phục vụ truy vấn.
6. WHEN Retriever_Selector chọn một backend cho một truy vấn, THE Retriever_Selector SHALL ghi nhận backend đã chọn và lý do chọn (mặc định / fallback) vào log.
7. THE Benchmark_Harness SHALL đo và báo cáo trên toàn bộ Golden_Query_Set: recall@10, độ trễ truy hồi server-side ở mức p50 và p95, và mức tiêu thụ bộ nhớ đỉnh của Turbovec_Retriever so với Qdrant_Retriever.
8. WHERE chế độ triển khai air-gapped được cấu hình, THE RAG_Engine SHALL phục vụ 100% truy vấn trong Golden_Query_Set chỉ với Turbovec_Retriever và Lexical_Fallback, và SHALL KHÔNG thực hiện bất kỳ lời gọi nào tới dịch vụ Qdrant.

### Requirement 2: Lớp truy hồi suy luận thử nghiệm theo PageIndex/OpenKB (P3 - thử nghiệm)

**User Story:** As a knowledge engineer, I want an experimental vectorless reasoning-based retrieval layer (PageIndex/OpenKB) for hard multi-hop, conditional, and dependency questions, so that the system can answer questions that chunk similarity alone serves poorly — while keeping it isolated behind a flag and benchmarked separately.

#### Acceptance Criteria

1. WHERE Reasoning_Retrieval_Layer được bật qua Feature_Flag_Manager, WHEN một tài liệu nguồn được nạp hoặc cập nhật, THE PageIndex_Builder SHALL biên dịch tài liệu đó thành chỉ mục cây phân cấp bền vững gồm: (a) một trang tóm tắt cho mỗi nút của cây, (b) liên kết chéo khái niệm giữa các nút, và (c) tham chiếu ngược về trang/đoạn nguồn để phục vụ truy vết trích dẫn.
2. WHERE Reasoning_Retrieval_Layer bị tắt qua Feature_Flag_Manager, THE Answer_Workflow SHALL KHÔNG khởi tạo hoặc gọi Reasoning_Retrieval_Layer và SHALL trả về câu trả lời giống hệt Production_Core.
3. WHERE Reasoning_Retrieval_Layer được bật qua Feature_Flag_Manager, WHEN Answer_Workflow phân loại một truy vấn thuộc ít nhất một loại của Hard_Question_Set (multi-hop, điều kiện, ngoại lệ, hoặc phụ thuộc chéo thủ tục), THE Answer_Workflow SHALL gọi Reasoning_Retrieval_Layer để thu thập bằng chứng đi theo cấu trúc cây của chỉ mục.
4. IF PageIndex_Builder hoặc Reasoning_Retrieval_Layer gặp lỗi tại runtime hoặc không trả về kết quả trong ngưỡng thời gian cấu hình (mặc định 30 giây), THEN THE Answer_Workflow SHALL quay về Production_Core, trả về câu trả lời từ luồng truy hồi mặc định mà không để lỗi lan ra người dùng, và ghi nhận sự kiện fallback kèm trace id vào log.
5. THE Benchmark_Harness SHALL chạy Reasoning_Retrieval_Layer, lớp thử nghiệm m_flow, và Production_Core trên cùng một Hard_Question_Set và SHALL báo cáo cho từng tùy chọn: (a) độ chính xác câu trả lời = tỉ lệ phần trăm câu trả lời khớp đáp án kỳ vọng, (b) độ phủ trích dẫn = tỉ lệ phần trăm câu trả lời có trích dẫn đúng nguồn kỳ vọng, và (c) chênh lệch điểm phần trăm của (a) và (b) so với Production_Core baseline.
6. THE PageIndex_Builder SHALL lưu chỉ mục đã biên dịch ở dạng bền vững giữa các lần khởi động và SHALL tái sử dụng chỉ mục đã lưu mà không biên dịch lại khi tài liệu nguồn không thay đổi kể từ lần biên dịch gần nhất.

### Requirement 3: OCR dự phòng bằng PaddleOCR cho tài liệu scan (P2)

**User Story:** As an administrator, I want a PaddleOCR-based OCR fallback for scanned or low-quality documents, so that documents MinerU cannot OCR well are still ingested with usable text — while MinerU remains the primary parser.

#### Acceptance Criteria

1. THE MinerU_Parser SHALL là parser chính và SHALL xử lý đầu tiên mọi tài liệu được nạp vào trước khi bất kỳ OCR dự phòng nào được kích hoạt.
2. WHERE OCR_Fallback được bật qua Feature_Flag_Manager, WHEN MinerU_Parser tạo ra cho một trang văn bản OCR có độ tin cậy dưới ngưỡng cấu hình (mặc định 0.80 trên thang 0.0–1.0) HOẶC độ phủ ký tự dưới ngưỡng cấu hình (mặc định 90%), THE OCR_Fallback SHALL OCR lại trang đó bằng PaddleOCR PP-Structure.
3. WHEN OCR_Fallback hoàn tất OCR lại một trang, THE RAG_Engine SHALL hợp nhất kết quả OCR dự phòng của trang đó vào Markdown chuẩn hóa, giữ nguyên thứ tự đọc và liên kết trang/bbox của tài liệu.
4. IF OCR_Fallback không khả dụng, trả về lỗi, hoặc vượt thời gian xử lý cấu hình cho một trang (mặc định 30 giây), THEN THE RAG_Engine SHALL giữ lại kết quả của MinerU_Parser cho trang đó và ghi nhận một cảnh báo chất lượng cho tài liệu đó.
5. WHERE OCR_Fallback bị tắt qua Feature_Flag_Manager, THE RAG_Engine SHALL chỉ sử dụng kết quả của MinerU_Parser và SHALL KHÔNG gọi PaddleOCR cho bất kỳ trang nào.
6. THE RAG_Engine SHALL ghi lại nguồn OCR (MinerU_Parser hoặc PaddleOCR) cho mỗi trang của tài liệu để phục vụ truy vết.

### Requirement 4: Quan sát được (observability) và bộ kiểm thử truy hồi đơn điểm (P1)

**User Story:** As a developer optimizing the pipeline, I want per-stage call-chain logging and an isolated retrieval test harness (patterns from FastGPT/MaxKB), so that I can inspect and debug each stage (retrieve → rerank → compose → LLM) independently and measure where quality is lost.

#### Acceptance Criteria

1. WHERE Call_Chain_Logger được bật, WHEN một truy vấn được xử lý, THE Call_Chain_Logger SHALL ghi lại đầu vào, đầu ra, điểm số liên quan, và độ trễ tính bằng mili-giây cho từng stage trong số: retrieval, rerank, parent-context expansion, context composer, và lời gọi LLM.
2. THE Retrieval_Test_Harness SHALL cho phép chạy một truy vấn đơn lẻ qua chỉ riêng các stage truy hồi (retrieval → rerank → parent-context expansion → context composer, không gọi LLM) và SHALL trả về danh sách chunk ứng viên kèm điểm số của từng stage trong dưới 1 giây cho corpus hiện tại.
3. THE Retrieval_Test_Harness SHALL cho phép cấu hình backend truy hồi đang kiểm thử (Qdrant_Retriever, Turbovec_Retriever, hoặc Lexical_Fallback) cho từng lần chạy.
4. WHERE Call_Chain_Logger được bật, THE RAG_Engine SHALL gắn cho mỗi truy vấn một định danh truy vết (trace id) duy nhất, không trùng lặp với bất kỳ truy vấn nào khác, và SHALL đính kèm trace id này vào mọi bản ghi của tất cả stage để liên kết chúng.
5. THE Call_Chain_Logger SHALL che (redact) mọi nội dung bí mật — bao gồm khóa API và thông tin xác thực — bằng giá trị thay thế trong mọi bản ghi, sao cho không có giá trị bí mật nguyên bản nào xuất hiện trong bất kỳ bản ghi nào.
6. WHILE Call_Chain_Logger ở chế độ tắt, THE RAG_Engine SHALL tiếp tục phục vụ truy vấn và SHALL KHÔNG sinh bất kỳ bản ghi per-stage hay trace id nào của Call_Chain_Logger.
7. IF Call_Chain_Logger không ghi được một bản ghi stage tại runtime, THEN THE RAG_Engine SHALL tiếp tục xử lý và trả về câu trả lời cho truy vấn mà không gián đoạn, và SHALL ghi nhận một cảnh báo cho biết việc ghi log đã thất bại.
8. IF backend truy hồi được chọn cho một lần chạy của Retrieval_Test_Harness không khả dụng, THEN THE Retrieval_Test_Harness SHALL trả về thông báo lỗi cho biết backend nào thất bại và SHALL KHÔNG tự động chuyển sang backend truy hồi khác.

### Requirement 5: Tăng cường độ bền vững lớp LLM theo freellmapi (P1)

**User Story:** As a developer, I want sticky sessions, a per-key rate ledger, and a unified failover endpoint (patterns from freellmapi) folded into the existing failover chain, so that conversations stay on one model to avoid mid-conversation hallucination and the router respects provider rate limits — while a paid primary is kept for quality.

#### Acceptance Criteria

1. WHILE một phiên hội thoại đang hoạt động VÀ Session_Manager được bật, THE LLM_Router SHALL ghim cùng một model cho phiên đó trong khoảng thời gian cấu hình (mặc định ~30 phút).
2. WHEN model đang ghim cho một phiên thất bại hoặc hết hạn mức, THE LLM_Router SHALL chuyển sang model kế tiếp trong chuỗi failover và cập nhật model ghim của phiên.
3. THE Rate_Ledger SHALL theo dõi mức sử dụng per-key theo RPM, RPD, TPM, và TPD.
4. IF một key đạt bất kỳ hạn mức nào trong RPM/RPD/TPM/TPD, THEN THE LLM_Router SHALL đưa key đó vào trạng thái cooldown và định tuyến sang key hoặc model kế tiếp khả dụng.
5. WHEN một nhà cung cấp trả về lỗi 429, lỗi 5xx, hoặc timeout, THE LLM_Router SHALL áp dụng cooldown cho mục tiêu đó rồi thử mục tiêu kế tiếp trong chuỗi failover.
6. THE LLM_Router SHALL giữ một primary trả phí ở đầu chuỗi failover làm mặc định chất lượng, với các nhà cung cấp tier miễn phí ở phía dưới.
7. THE LLM_Router SHALL phơi bày một điểm vào (endpoint) OpenAI-compatible hợp nhất để gọi failover, tương thích với `OpenAICompatibleClient` hiện có.
8. THE Rate_Ledger SHALL lưu trữ khóa nhà cung cấp ở dạng mã hóa và SHALL KHÔNG ghi giá trị khóa ra log hoặc phản hồi.

### Requirement 6: Quản trị đánh giá tùy chọn và degrade gracefully (P1 - xuyên suốt)

**User Story:** As a system owner, I want every evaluated option to be flag-gated, benchmarked against the production baseline, and to degrade gracefully, so that experiments never destabilize the production core and adoption decisions are evidence-based.

#### Acceptance Criteria

1. THE Feature_Flag_Manager SHALL cung cấp một cờ cấu hình độc lập cho mỗi tùy chọn đang đánh giá: Turbovec_Retriever, Reasoning_Retrieval_Layer, OCR_Fallback, Call_Chain_Logger, và các mẫu hình freellmapi (Session_Manager, Rate_Ledger).
2. WHERE tất cả cờ tùy chọn ở trạng thái tắt, THE RAG_Engine SHALL vận hành giống hệt Production_Core đã định nghĩa ở spec 001.
3. IF một thành phần tùy chọn thất bại tại runtime, THEN THE RAG_Engine SHALL quay về hành vi của Production_Core và tiếp tục phục vụ truy vấn.
4. THE Benchmark_Harness SHALL tạo báo cáo so sánh mỗi tùy chọn với Production_Core baseline trên Golden_Query_Set hoặc Hard_Question_Set tương ứng trước khi tùy chọn được đề xuất làm mặc định.
5. WHEN một tùy chọn được đề xuất chuyển thành mặc định sản xuất, THE Benchmark_Harness SHALL cung cấp số liệu cho thấy tùy chọn đó không làm giảm độ chính xác câu trả lời, độ phủ trích dẫn, hoặc độ trễ so với baseline.

## Success Criteria

- **SC-001**: Turbovec_Retriever đạt recall@10 không thấp hơn Qdrant_Retriever quá 5 điểm phần trăm trên Golden_Query_Set, với độ trễ truy hồi server-side dưới mức của Qdrant_Retriever trong chế độ in-process.
- **SC-002**: Ở chế độ air-gapped (chỉ Turbovec_Retriever + Lexical_Fallback), RAG_Engine phục vụ được 100% Golden_Query_Set mà không cần dịch vụ Qdrant.
- **SC-003**: Reasoning_Retrieval_Layer (PageIndex/OpenKB) cải thiện độ chính xác câu trả lời trên Hard_Question_Set ít nhất 15% so với Production_Core baseline để đủ điều kiện áp dụng tiếp.
- **SC-004**: OCR_Fallback nâng độ phủ ký tự văn bản trích xuất lên ≥ 90% cho tập tài liệu scan/chất lượng thấp mà MinerU OCR xử lý dưới ngưỡng.
- **SC-005**: Retrieval_Test_Harness chạy một truy vấn qua các stage truy hồi (không gọi LLM) và trả về kết quả per-stage trong dưới 1 giây cho corpus hiện tại.
- **SC-006**: Sau khi bật Session_Manager, tỉ lệ đổi model giữa chừng trong một phiên hội thoại giảm xuống 0 trong cửa sổ thời gian ghim, đo trên log Call_Chain_Logger.
- **SC-007**: Khi tất cả cờ tùy chọn tắt, bộ kiểm thử hồi quy (pytest + smoke + QA eval) của Production_Core đạt kết quả giống baseline spec 001 (không hồi quy).
- **SC-008**: Mọi thành phần tùy chọn đều có đường degrade gracefully đã được kiểm chứng: mô phỏng lỗi từng thành phần vẫn cho RAG_Engine trả lời thành công qua Production_Core.
