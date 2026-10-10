# TreasuryPilot: Kiến trúc AI agent

**Nguồn chuẩn:** `docs/AI_AGENT_ARCHITECTURE.md` · **Trạng thái:** Đã qua cổng G2

> **Luật gốc:** LLM không bao giờ tự quyết định bất cứ điều gì làm tiền di chuyển. Nó **quan sát** qua tool chỉ đọc, **suy luận** và **đề xuất** theo schema chặt, và chỉ được **chọn trong các phương án mà code xác định đã kiểm tra hợp lệ**. Quyền chỉ đến từ ba nguồn:
> - policy engine (xác định);
> - chữ ký EIP-712 của con người (duyệt, ngoại lệ);
> - smart contract (kiểm tra cuối).

## 1. Các lớp

| Lớp | Phụ trách | Không bao giờ làm |
|---|---|---|
| **Suy luận LLM** | Trích xuất hóa đơn, đọc điều khoản, phát hiện văn bản bất thường, đề xuất thứ tự kế hoạch, viết lý do, soạn yêu cầu ngoại lệ, trả lời Copilot | Tính số tiền; khẳng định số dư hay quyền; viết calldata; gọi API ghi; nhìn thấy bí mật |
| **Logic nghiệp vụ xác định** (`py-core`) | Công thức thiếu hụt/refill, hàm mục tiêu lập lịch, tính khả thi, minOut, fingerprint | Lấy con số từ đầu ra LLM |
| **Policy engine** | ALLOW / NEEDS_APPROVAL / BLOCK kèm mã lý do; dựng attestation | Cấp ngoại lệ, nâng hạn mức |
| **Lớp tool** | 6 tool chỉ đọc, có kiểu, giới hạn theo tổ chức, có ngân sách gọi | Bất kỳ tác dụng phụ nào |
| **Lớp phân quyền** | RBAC, maker-checker, danh sách approver, mandate | Dựa vào độ tự tin của AI |
| **Lớp kiểm tra** | Schema Pydantic cho mọi đầu ra LLM; kiểm tra ID có tồn tại; chấm điểm theo hàm mục tiêu | Tự "sửa" đầu ra xấu của AI bằng cách nới chính sách |
| **Phê duyệt của con người** | Có trả hay không (duyệt); vượt trần (ngoại lệ); chính sách, payee, tạm dừng | — |
| **Dấu vết audit** | `ai_calls`, `validations`, `audit_log`, gói bằng chứng | — |

## 2. Năm hành động có AI và vòng kiểm soát

Mỗi hành động đi theo chuỗi **Quan sát → Suy luận → Kiểm tra chính sách → Quyết định → Hành động → Xác minh → Phục hồi**.

### A1. Đọc hóa đơn (F-031, F-035, F-036)

| Bước | Diễn ra thế nào | Ai làm |
|---|---|---|
| Quan sát | Lưu tài liệu; nội dung gửi đi dưới dạng khối "tài liệu không tin cậy" có nhãn; lịch sử nhà cung cấp lấy bằng code | Hệ thống |
| Suy luận | Trích trường, điều khoản và các câu lệnh đáng ngờ theo schema, kèm vị trí trong tài liệu | LLM (model nhỏ) |
| Kiểm tra | Schema hợp lệ; số tiền đúng độ chính xác; tài sản đúng stablecoin; địa chỉ so với danh bạ bằng **so sánh checksum**; tính fingerprint; kiểm tra số tiền bất thường | Code xác định |
| Quyết định | Tạo bản nháp và các cờ. **Không quyết định gì về thanh toán** | — |
| Hành động | Tạo Draft (chưa có tiền nào di chuyển) | Hệ thống |
| Xác minh | Operator xác nhận từng trường và điều khoản; Approver xác nhận đã đọc cờ mức cao | Con người |
| Phục hồi | Quá thời gian hoặc lỗi → nhập tay, tài liệu hiển thị bên cạnh; chỉ còn cờ xác định, kèm ghi chú mức bao phủ | Hệ thống |

Hệ quả tài chính: **không có trực tiếp.** Tiền chỉ di chuyển sau chữ ký duyệt của con người.

### A2. Đề xuất kế hoạch (F-052, F-053, F-054)

| Bước | Diễn ra thế nào | Ai làm |
|---|---|---|
| Quan sát | Snapshot mới; các yêu cầu đã duyệt kèm điều khoản đã xác nhận; ngân sách; mandate | Code + tool |
| Suy luận | Đề xuất thứ tự, khoản hoãn, khoản cần ngoại lệ, kèm lý do có trích ID bằng chứng | LLM (model mạnh) |
| Kiểm tra | Bộ lập lịch chấm điểm đề xuất AI và kế hoạch xác định theo BR-052; validator kiểm tra từng ứng viên | Code xác định |
| Quyết định | Chọn kế hoạch **khả thi, hợp lệ** tốt nhất; ghi nguồn và lý do chọn | Code xác định (kế hoạch AI chỉ thắng khi hợp lệ và tốt hơn) |
| Hành động | Ký attestation → signer → gọi module | Policy engine, signer, contract |
| Xác minh | Receipt, hậu điều kiện, đọc lại trạng thái sau mỗi bước | Code xác định |
| Phục hồi | AI quá thời gian → mẫu rule-based; kế hoạch AI sai → NeedsReview; giao dịch chưa rõ → quy trình phục hồi | Hệ thống |

Hệ quả tài chính: **có.** Các lớp kiểm soát:

| Kiểm soát | Cách thực hiện |
|---|---|
| Mandate | Phiên bản mandate on-chain đang hiệu lực |
| Hạn mức | Trần mỗi khoản, bộ đếm ngày UTC, buffer |
| Chính sách duyệt | Mỗi PAY cần chữ ký Approver; vượt trần cần ngoại lệ của Owner |
| Bằng chứng audit | `ai_calls` + `validations` + `attestations` + `operations` + `transactions` → gói bằng chứng |

### A3. Soạn yêu cầu ngoại lệ (F-057)

- **Quan sát:** validator báo NEEDS_APPROVAL vì vượt trần mỗi khoản; ngân sách ngày còn lại; điều khoản và deadline.
- **Suy luận:** LLM viết lý do và các phương án thay thế. Con số được chèn từ engine, không do LLM sinh.
- **Kiểm tra:** bước hậu kiểm so mọi con số trong văn bản với giá trị của engine.
- **Quyết định:** không có (AI không quyết).
- **Hành động:** tạo mục xem xét cho Owner.
- **Xác minh:** Owner ký hoặc từ chối; contract thực thi BR-040/041/042.
- **Phục hồi:** LLM lỗi → dùng văn bản mẫu.

### A4. Copilot (F-090)

- **Quan sát:** câu hỏi và bối cảnh theo vai trò.
- **Suy luận:** vòng gọi tool (tối đa 6 lần), dùng `simulate_schedule` cho câu hỏi "nếu… thì sao".
- **Kiểm tra:** schema `{answer, citations[]}`; mọi con số phải có trong kết quả tool được trích dẫn.
- **Quyết định / Hành động:** không có. Không có tool ghi. Yêu cầu "trả tiền" bị từ chối, kèm link sang luồng duyệt.
- **Xác minh:** audit log cho thấy không có tác dụng phụ.
- **Phục hồi:** quá thời gian → báo "AI không khả dụng", hiển thị dashboard xác định.

### A5. Giải thích bất thường và tóm tắt chênh lệch (F-071, F-072)

Chỉ là văn bản đề xuất đính kèm mục xem xét, có nhãn "Giải thích của AI".

## 3. Hợp đồng tool

| Tool | Đầu vào | Đầu ra |
|---|---|---|
| `get_snapshot` | treasuryId | Số dư, bộ đếm, buffer, tóm tắt mandate, mức bao phủ, số block |
| `list_requests` | treasuryId, trạng thái | Yêu cầu kèm điều khoản đã xác nhận, deadline, số tiền (không có tài liệu gốc) |
| `get_policy_summary` | treasuryId | Hạn mức, đường refill, payee ở dạng dễ đọc |
| `simulate_schedule` | treasuryId, thay đổi giả định | Kết quả engine: lịch khả thi, tiết kiệm, ràng buộc đang chặn |
| `get_evidence` | evidenceId | Bản ghi bằng chứng (phải thuộc tổ chức) |
| `explain_decision` | planId hoặc validationId | Mã lý do và các kiểm tra của validator |

Ngân sách: tối đa 8 lần gọi tool mỗi chu kỳ lập kế hoạch, 6 lần mỗi lượt Copilot; giới hạn kích thước payload; ngân sách token theo ngày cho từng tổ chức.

## 4. Phòng chống prompt injection

1. **Tách biệt:** system prompt cố định, có phiên bản; văn bản không tin cậy được bọc trong thẻ, có nhãn nguồn và giới hạn độ dài; loại bỏ nội dung chủ động (link, script).
2. **Quyền tối thiểu:** chỉ có tool đọc; không tải URL; không có calldata tự do.
3. **Đầu ra khóa bằng schema:** model Pydantic cấm trường lạ; hành động là enum; ID được kiểm với DB.
4. **Kiểm tra bằng code:** địa chỉ, số tiền, payee do code so sánh, không do LLM; validator và contract kiểm lại.
5. **Phát hiện là tín hiệu:** văn bản giống mệnh lệnh trở thành cờ, không bao giờ thành hành động.
6. **Bộ red-team:** hơn 20 hóa đơn tấn công (đổi địa chỉ, "đã duyệt sẵn", nâng hạn mức, địa chỉ ký tự giống, văn bản ẩn). Kỳ vọng: 0 lần đổi được trường hoặc chính sách.

## 5. Chọn model và vận hành

| Tác vụ | Loại model | Timeout | Khi lỗi |
|---|---|---|---|
| Trích xuất / điều khoản / văn bản bất thường | Claude nhỏ, nhanh | 20 giây | Nhập tay |
| Đề xuất kế hoạch / lý do | Claude mạnh nhất hiện có | 20 giây | Mẫu rule-based (BR-055) |
| Soạn ngoại lệ | Mạnh | 15 giây | Văn bản mẫu |
| Copilot | Mạnh | 30 giây (stream) | Báo "AI không khả dụng" |

ID model, phiên bản prompt và ngân sách nằm trong file cấu hình. Mọi lời gọi đều ghi vào `ai_calls`; ghi không được thì hành động thất bại an toàn.

## 6. Đánh giá

| Bộ | Kích thước | Chỉ số | Ngưỡng (M1) |
|---|---|---|---|
| Độ chính xác trích xuất | 30 hóa đơn có nhãn | Khớp chính xác từng trường; F1 cho điều khoản | Báo cáo (mục tiêu ≥ 90% trường chính) |
| Benchmark lập kế hoạch B1 và B2 | Ít nhất 30 kịch bản (tách bộ phát triển và bộ giữ lại) | Stablecoin tiết kiệm, tỷ lệ đúng hạn, số ngoại lệ, số giao dịch, phí, **vi phạm = 0**, độ trễ, chi phí | Vi phạm phải bằng 0; tiết kiệm báo trung thực |
| Red-team | 20 hóa đơn | Số lần thao túng thành công | 0 |
| Độ đúng số liệu của Copilot | 20 câu hỏi | Số liệu khớp engine | 100% |

Bộ dữ liệu và đáp án do các thành viên cố vấn soạn (epic "Domain & Evidence"), lưu trong `evals/`.
