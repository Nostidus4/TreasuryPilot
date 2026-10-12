# M09 · AI agent

**Nguồn chuẩn:** `docs/modules/agent/README.md` · **Trạng thái:** Chi tiết, đã review với trưởng nhóm (11/10/2026) · **ADR:** ADR-005 · **Xem thêm:** tab 13 Kiến trúc AI

## 1. Mục đích và ranh giới

AI giúp TreasuryPilot **nhanh hơn và thông minh hơn, nhưng không bao giờ có thêm quyền**. Nó đọc hóa đơn, tìm điều khoản và câu chữ đáng ngờ, đề xuất thứ tự trả kèm lý do, soạn đề nghị ngoại lệ và trả lời câu hỏi. Mọi thứ đều theo schema chặt, qua tool chỉ đọc, và mọi con số đều lấy từ hoặc được kiểm bằng code tất định.

| AI được | AI không bao giờ được |
|---|---|
| Trích trường và điều khoản (bản nháp để người xác nhận) | Duyệt, đổi payee/số tiền, thêm payee, nâng hạn mức, sửa policy (BR-002) |
| Gắn cờ câu chữ giống lệnh | Ghi vào DB hoặc gọi chain |
| Đề xuất thứ tự/hoãn trong các phương án engine đã kiểm | Đưa ra số tiền dùng để thực thi |
| Giải thích quyết định, soạn văn bản ngoại lệ | Dùng độ tự tin làm điều kiện cấp quyền (BR-058) |
| Trả lời câu hỏi "nếu… thì" có trích dẫn kết quả tool | Nhận bất kỳ bí mật nào (BR-092) |

## 2. Feature, yêu cầu, luật

F-031 phần AI (FR-303–305) · F-035 điều khoản (FR-310) · F-036 câu chữ giống lệnh (FR-312) · F-053 đề xuất plan + chọn (FR-406–408, BR-052, BR-056) · F-054 dự phòng theo luật (FR-409, BR-055) · F-057 soạn ngoại lệ (FR-414, BR-043) · F-090 Copilot (FR-801, FR-802) · F-091 chống prompt injection (FR-803, FR-804, BR-070) · F-092 bộ đánh giá (FR-805) · F-093 nhật ký AI (FR-806, FR-807, BR-097) · F-094 adapter nhà cung cấp (FR-808).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Task** | Một mục đích dùng AI với prompt version, schema, model, timeout và ngân sách riêng: EXTRACT, TERMS, ANOMALY, PLAN, EXCEPTION_DRAFT, COPILOT, EVAL. |
| **Khối không tin cậy** | Văn bản bên ngoài bọc trong `<untrusted source="invoice:…">…</untrusted>`, giới hạn độ dài; system prompt nói rõ nội dung bên trong chỉ là dữ liệu. |
| **Tool** | Hàm chỉ đọc, đầu vào/ra có kiểu, giới hạn trong tổ chức, chạy trong transaction DB chỉ đọc. |
| **Đề xuất** | `PlanProposal`: thứ tự và các khoản hoãn theo **request id**, không có số tiền; engine dựng thành plan cụ thể. |
| **Kiểm số sau** | Mọi con số trong văn bản AI phải có trong kết quả tool/engine đưa cho nó; sai là bỏ văn bản. |

## 4. Mô hình dữ liệu

`ai_calls` (purpose, model, prompt_version, input_refs, tool_calls, output, validation_result: OK / SCHEMA_ERROR / POSTCHECK_FAILED / REJECTED, latency, tokens, chi phí, lỗi; append-only; ghi lỗi thì bỏ kết quả) · `extractions` (trường kèm trang và đoạn văn bản, điều khoản, câu chữ đáng ngờ, người xác nhận) · `copilot_threads` / `copilot_messages` (kèm trích dẫn) · `ai_budgets` (ngân sách theo tổ chức theo tháng).

## 5. Trạng thái

Mỗi lời gọi không có trạng thái; trạng thái trích xuất nằm trên request (`Extracting → Extracted | ManualEntry`); hội thoại Copilot chỉ ghi thêm.

## 6. Giao diện

**Schema (JSON chặt, Pydantic, cấm trường thừa):** `InvoiceExtraction` (tên vendor, số hóa đơn, ngày phát hành, ngày đến hạn, số tiền dạng chữ, tiền tệ, địa chỉ payee như trên tài liệu, nguồn từng trường, số hóa đơn trong tài liệu, câu chữ đáng ngờ) · `TermsExtraction` (chiết khấu, ngày chiết khấu, net, phí trễ, ghi chú ưu tiên, `uncertain`) · `PlanProposal` (thứ tự request, hoãn, đề nghị ngoại lệ, lý do kèm evidence id) · `ExceptionDraft` (tóm tắt, lý do, phương án khác) · `CopilotAnswer` (câu trả lời, trích dẫn).

**Tool (danh sách cho phép):** `get_snapshot` (số dư, buffer, ngân sách hôm nay, trạng thái payee; không khóa, không PII) · `list_requests` · `get_policy_summary` · `simulate_schedule` (lịch của engine + mục tiêu + ràng buộc chặn) · `get_evidence` · `explain_decision` (mã lý do của M08). Ngân sách: PLAN ≤ 8 lần gọi tool, COPILOT ≤ 6; mỗi kết quả ≤ 50 KB.

**Nội bộ:** `extract(document_id)`, `propose_plan(treasury_id, request_ids)`, `draft_exception(request_id)`, `copilot.ask(thread_id, text)` (stream SSE).

## 7. Luồng

- **Trích xuất:** upload → hàng đợi ai → model đọc PDF/ảnh → kiểm schema → kiểm quy tắc (ngày, tiền tệ, so địa chỉ) → lưu + điền nháp + cờ AI → Operator xác nhận (M05). Quá 60 giây → nhập tay, không đoán.
- **Lập kế hoạch:** M10 chỉ hỏi AI đề xuất plan khi có ý nghĩa (≥ 2 request đủ điều kiện, hoặc có điều khoản/hoãn). Request đơn lẻ dùng plan tính sẵn, AI chỉ viết **lời giải thích** ngắn (task EXPLAIN, model rẻ) hiện ở panel "Vì sao" (M09-D6). Đường đề xuất đầy đủ → vòng tool → `PlanProposal` → kiểm id tồn tại và thuộc tổ chức → engine dựng plan → chấm điểm so với plan tất định → chọn bên tốt hơn (hòa → tất định) → M08 kiểm. Đề xuất ngoài mandate → review AI_PLAN_REJECTED + circuit breaker.
- **Soạn ngoại lệ:** đưa số của engine vào → soạn → kiểm số → đính kèm; lỗi → văn bản mẫu.
- **Copilot:** câu hỏi → vòng tool → trả lời + trích dẫn → kiểm số → stream; yêu cầu thực thi bị từ chối và chỉ sang luồng duyệt.

## 8. Thuật toán

**8.1 Chống injection nhiều lớp:** (1) `wrap_untrusted` (tag, nguồn, giới hạn 20 nghìn ký tự, bỏ script/link); (2) phần system prompt cố định, lint cấm chèn văn bản không tin cậy ngoài khối bọc; (3) schema đầu ra không có hành động tự do, tool chỉ đọc, không nhận số tiền; (4) `suspicious_instructions` → cờ HIGH, kèm dự phòng từ khóa (`pay to`, `instead`, `pre-approved`, `ignore previous`, `urgent change of bank`, địa chỉ 0x không có trong danh bạ); (5) bộ red-team 20 ca, 0 trường/policy bị đổi (AGT-015).

**Phần cài đặt (AGT-003).** Code nằm ở `agent/untrusted.py`, `agent/secret_scan.py` và `agent/prompts/`.

- `wrap_untrusted(source, text)` trả về `UntrustedBlock`. `source` là `UntrustedSource(kind, ref)`: `kind` thuộc `invoice`, `document`, `vendor`, `terms`, `email`; `ref` phải khớp `[A-Za-z0-9_.:-]{1,64}` để nhãn không chèn được thêm attribute. Văn bản được làm sạch theo thứ tự: bỏ ký tự vô hình (Unicode `Cc` trừ `\n`/`\t`, và `Cf`: zero-width, bidi, tag characters); bỏ khối `<script>`/`<style>` và comment HTML (thẻ mở không có thẻ đóng thì chỉ bỏ riêng thẻ mở, giữ phần còn lại); bỏ ảnh Markdown, link Markdown chỉ giữ chữ; URL (`http(s)`, `ftp`, `www.`, `javascript:`, `vbscript:`, URI `data:`) thành `[link removed]`; các tag HTML khác (tên tag, sau đó chỉ có attribute dạng `name=value`, nên `a<b and c>d` vẫn là chữ) bị bỏ, giữ chữ. Tag `<untrusted…>`/`</untrusted>` nằm trong văn bản thành `[tag removed]`, và được kiểm lại sau các bước khác vì việc xoá có thể ghép các mảnh thành tag. Địa chỉ `0x…`, email và chữ thường được giữ nguyên, không chuẩn hoá Unicode, để trích dẫn đúng từng chữ. Văn bản thô được cắt trước còn 4 lần giới hạn, và mọi mẫu đều chạy trong thời gian tuyến tính, nên input cố ý tạo ra không làm treo worker. Giới hạn 20.000 ký tự áp dụng sau khi làm sạch; khối bị cắt ở bước nào cũng có `truncated="true"`. Sau đó khối được quét bí mật.
- **Bộ quét bí mật (FR-804).** Đầu vào bị từ chối chứ không bị che, với lỗi `AiInputRejected(pattern, source)`, là một `AiError` không bao giờ mang giá trị khớp. Các mẫu: chuỗi hex từ 64 ký tự (khóa riêng EVM, chữ ký, calldata dài; vì vậy invoice có tx hash sẽ bị từ chối và chuyển sang nhập tay), cụm seed BIP39 (kể cả dạng đánh số hoặc phân cách bằng dấu phẩy) khi 12, 15, 18, 21 hoặc 24 từ đầu hay cuối của một chuỗi từ thuộc wordlist có checksum hợp lệ, khóa mở rộng BIP32, keystore JSON, khóa riêng PEM/OpenSSH/PGP; khóa `sk-` của Anthropic/OpenAI, AWS access key id, JSON service account GCP, Google API key, token GitHub, GitLab, Slack (token và webhook), Stripe, SendGrid, npm, PyPI, bot Telegram, JWT; thông tin đăng nhập trong URL, URL RPC có khóa (Alchemy, Infura, QuickNode), header `Authorization: Bearer|Basic`, và phép gán: tên chứa secret/password/passwd/private/credential/mnemonic/seed/api_key/access_key với giá trị bất kỳ từ 8 ký tự, hoặc tên chỉ chứa key/token với giá trị trông như sinh tự động (từ 16 ký tự, có cả chữ và số, không phải địa chỉ `0x`). Giá trị của các biến môi trường trong tiến trình có tên chứa KEY, SECRET, TOKEN hoặc PASSWORD nhưng không chứa PUBLIC (từ 16 ký tự) cũng được so khớp nguyên văn. Adapter quét system prompt, message, tool call và kết quả tool với `allow_bytes32`, cho phép giá trị `0x` + 64 hex (id request, step, plan, fingerprint, tx hash); khối không tin cậy được quét không có tùy chọn này trong `wrap_untrusted`. Mô tả tool và schema đầu ra là code nên không được quét. Không bắt theo entropy, chuỗi 32 hex, khóa WIF, IBAN và số thẻ, vì chúng gây báo nhầm trên invoice và IBAN là nội dung hợp lệ của invoice.
- **Template.** `PromptTemplate(version, system, instructions, slots)` chỉ nhận đối số dạng keyword; `system` và `instructions` là chuỗi literal. System prompt sau khi render là `UNTRUSTED_DATA_POLICY` cố định (đánh phiên bản bằng `POLICY_VERSION`) rồi đến `system` của template, không chèn gì vào. User message liệt kê các slot theo thứ tự rồi đến chỉ dẫn cố định (dữ liệu trước, chỉ dẫn sau). `Slot.untrusted` chỉ nhận `UntrustedBlock`. `Slot.trusted` nhận bool, int, Decimal, date, StrEnum hoặc model Pydantic, render thành `<data name="…">…</data>`, và từ chối `str` trần. Model được render thành JSON với `<` và `>` thoát thành `\u003c`/`\u003e`, nên một field chuỗi không thể đóng thẻ; dù vậy vẫn không nên chứa văn bản do vendor cung cấp. `render(**values)` trả về `RenderedPrompt`, với `prompt_version` là `<version>+policy.<POLICY_VERSION>` để ghi vào nhật ký AI. Template sai hoặc giá trị slot thiếu, thừa, sai kiểu sẽ raise `PromptTemplateError`, là `ValueError` chứ không phải `AiError`, để lỗi lập trình không bị dự phòng che mất.
- **Lint test** (`tests/agent/test_prompt_lint.py`) quét toàn bộ package worker. `RenderedPrompt` chỉ được tạo trong `prompts/template.py`, `UntrustedBlock` chỉ trong `untrusted.py`, `Message`/`TextBlock` chỉ trong `prompts/` và adapter. `PromptTemplate` nhận đối số keyword là literal. Module template không ghép chuỗi (f-string, `%`, `+`, `.format`, `.join`, `string.Template`). Cấm `dataclasses.replace` và `object.__setattr__`. Alias khi import và truy cập qua attribute được tính như tên gốc.
- Ngoài phạm vi, để các ticket sau: bọc văn bản của vendor trong kết quả tool (AGT-007), block tài liệu PDF/ảnh (AGT-004, coi toàn bộ là không tin cậy theo cùng policy), và câu hỏi Copilot (AGT-012: là chỉ dẫn của người dùng, không bọc, nhưng vẫn được adapter quét bí mật).

**8.2 Chọn plan (AGT-009):** chỉ chọn plan của AI nếu hợp lệ và điểm tốt hơn hẳn plan tất định; hòa → tất định. Ghi `planner_source` và `chosen_reason` (ví dụ "AI lấy được chiết khấu 2 % cho INV-7 bằng cách hoãn INV-9 một ngày, giá trị +20").

**8.3 Kiểm số sau:** lấy mọi số trong văn bản, chuẩn hóa, đối chiếu với tập số trong kết quả tool/đầu vào engine (khớp chính xác, cùng đơn vị). Thiếu một số → bỏ văn bản → dùng mẫu.

**8.4 Dự phòng (BR-055):** chỉ dùng plan mẫu khi AI không có/hết giờ **và** snapshot đầy đủ **và** khớp mẫu (trả thẳng / refill rồi trả / swap rồi trả P2) **và** không có Unknown **và** không có cảnh báo an toàn. Ghi RULE_BASED.

## 9. Cấu hình (`config/ai.yaml`)

| Task | Model | Timeout | Token ra tối đa |
|---|---|---|---|
| EXTRACT, TERMS, ANOMALY | `claude-sonnet-5-5` | 60 giây | 2.000 |
| PLAN | `claude-opus-5-5` | 20 giây | 1.500 |
| EXCEPTION_DRAFT | `claude-sonnet-5-5` | 20 giây | 800 |
| EXPLAIN (request đơn lẻ, plan đã cố định) | `claude-haiku-5-5` | 10 giây | 300 |
| COPILOT | `claude-sonnet-5-5` | 30 giây | 1.200 |
| EVAL | `claude-sonnet-5-5` | 60 giây | 2.000 |

Ngân sách AI mỗi tổ chức 20 USD/tháng ở M1, chỉnh được (vượt → các task chuyển sang dự phòng, có thông báo). Nhà cung cấp phụ dùng chung adapter (AGT-017), chọn sau. Bật chế độ không lưu dữ liệu nếu có; việc này cấu hình ở cấp tổ chức trên Anthropic Console, không nằm trong code.

File còn chứa giới hạn số tool call (PLAN 8, COPILOT 6), giới hạn kết quả tool (50 KB) và bảng giá theo model (USD micros cho mỗi triệu token, Haiku có bậc giá cho prompt dài). Đường dẫn là `config/ai.yaml` tính từ thư mục làm việc (`/app` trong image worker), đổi được bằng `TP_AI_CONFIG_PATH`; thiếu task hoặc thiếu giá của một model thì worker không khởi động.

**Adapter (AGT-001).** Mọi lần gọi model đều qua `AiAdapter.run(task, org_id, prompt, output, tools)`, code ở `services/worker/src/treasurypilot_worker/agent/`. `prompt` là `RenderedPrompt` sinh từ `PromptTemplate` (§8.1), phiên bản của nó được trả về trong `AiResult.prompt_version`. Trước mỗi lần gọi provider, adapter quét bí mật trên system prompt và mọi message chưa quét, kể cả tool call và kết quả tool, và raise `AiInputRejected` khi khớp. Adapter chọn model theo config, coi timeout là deadline wall-clock cho cả lần gọi (gồm các lượt tool, retry provider và retry schema), retry lỗi provider có thể retry tối đa hai lần trong deadline đó, chạy vòng lặp tool chỉ đọc, và validate output theo schema Pydantic, retry một lần kèm lỗi validation (M09-D9). Lỗi trả ra là `AiTimeout`, `AiUnavailable`, `AiSchemaError`, `AiBudgetExceeded`, `AiToolLimitExceeded` hoặc `AiInputRejected`; bên gọi chuyển chúng sang dự phòng. Budget được kiểm trước khi gọi (chặn khi đã chi ≥ hạn mức, nên một lần gọi có thể vượt chút ít) và mọi phản hồi của provider đều được ghi qua `BudgetLedger`. Ledger nằm trong bộ nhớ cho đến khi có bảng `ai_budgets`.

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Test |
|---|---|---|
| Prompt injection đổi payee/số tiền | bọc dữ liệu, schema, không tool ghi, địa chỉ trích ra chỉ để so | AGT-015 (20 ca), AD-01 |
| Lộ bí mật | `worker-ai` chỉ có khóa LLM; quét bí mật trên mọi đầu vào của model, khớp thì từ chối (§8.1) | AGT-003 |
| Lộ dữ liệu giữa tổ chức | tool giới hạn tổ chức; Copilot theo người dùng/tổ chức | AGT-007 |
| Bịa số | kiểm số sau; số tiền luôn từ engine | AGT-011, AGT-016 |
| AI ngừng | dự phòng; nhà cung cấp phụ | AD-02, AGT-017 |
| Quyết định không có nhật ký | ghi `ai_calls` lỗi thì bỏ kết quả | AGT-002 |

## 11. Tình huống lỗi

LLM hết giờ → nhập tay / plan tất định / văn bản mẫu · lỗi schema → thử lại một lần kèm thông báo lỗi, rồi dự phòng · hết ngân sách → dự phòng + thông báo · nhà cung cấp ngừng → nhà cung cấp phụ (P1), không thì dự phòng.

## 12. Kế hoạch test

Test hợp đồng schema; lint chống injection; test tool chỉ đọc; test với phản hồi đã ghi sẵn cho từng task; đánh giá: độ chính xác trích xuất (30 hóa đơn), benchmark B1 vs B2 (dev + held-out), red-team (20), độ chính xác số của Copilot (20).

## 13. Ticket theo thứ tự

AGT-001 adapter → AGT-002 nhật ký → AGT-003 bọc dữ liệu → AGT-004 trích xuất → AGT-005 điều khoản → AGT-006 câu chữ giống lệnh → AGT-007 tool → AGT-008 đề xuất → AGT-009 chọn plan → AGT-010 dự phòng → AGT-011 soạn ngoại lệ → AGT-012 Copilot → đánh giá AGT-013/014/015/016 → AGT-017 nhà cung cấp phụ.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M09-D1 | Không dùng framework agent; SDK Anthropic với structured output và tool use (ADR-005). |
| M09-D2 | Model theo task (§9): PLAN dùng Opus; trích xuất/điều khoản/Copilot/soạn thảo dùng Sonnet; EXPLAIN dùng Haiku. (đã review) |
| M09-D3 | Mọi AI chạy trong `worker-ai`, chỉ có khóa LLM. |
| M09-D4 | Đề xuất chỉ chứa id và thứ tự; số tiền luôn từ engine. |
| M09-D5 | Chỉ chọn plan AI khi tốt hơn hẳn; hòa → tất định. (đã review) |
| M09-D6 | Chỉ hỏi AI đề xuất khi ≥ 2 request đủ điều kiện hoặc có điều khoản/hoãn; còn lại AI giải thích plan tính sẵn (task EXPLAIN). (đã review) |
| M09-D7 | Kiểm số sau cho mọi văn bản. |
| M09-D8 | Trích xuất quá 60 giây → nhập tay; không đoán. |
| M09-D9 | Lỗi schema: thử lại một lần kèm lỗi, rồi dự phòng. (đã review) |
| M09-D10 | Ngân sách AI 20 USD/tổ chức/tháng ở M1, chỉnh được. (đã review) |
| M09-D11 | Giới hạn gọi tool: PLAN 8, COPILOT 6. |
| M09-D12 | Đề xuất ngoài mandate → AI_PLAN_REJECTED + circuit breaker PAUSE. |
| M09-D13 | Tài liệu nhiều hóa đơn báo qua `invoice_count_in_document` → M05 từ chối. |
| M09-D14 | Đáp án của bộ kịch bản đánh giá không bao giờ đưa vào prompt. |

## 15. Thay đổi theo v0.3 (ADR-019)

EXPLAIN giải thích cả lệnh thanh khoản ("Đã supply 3.000 vì Safe có 6.000 mà dự trữ cần 3.000") và đề xuất vay (số liệu chỉ từ M07). AI không bao giờ đề xuất số tiền SUPPLY/BORROW. Benchmark thêm **B0** (làm tay/EDF, tiền để không) trước B1, B2; đo thêm số lần thủng dự trữ và lợi ích ròng gồm lãi gửi.
