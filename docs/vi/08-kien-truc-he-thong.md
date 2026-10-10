# TreasuryPilot: Kiến trúc hệ thống

**Nguồn chuẩn:** `docs/SYSTEM_ARCHITECTURE.md` · **Trạng thái:** Đã qua cổng G2 (11/10/2026)

## 1. Sáu nguyên tắc kiến trúc

| # | Nguyên tắc | Hệ quả |
|---|---|---|
| AP-1 | **Contract là bên quyết định cuối cùng về tiền.** | Mọi luật đánh dấu "C" trong Business Rules đều được kiểm trong `TreasuryPilotModule`. Backend lặp lại các kiểm tra đó nhưng không bao giờ được tin một mình. |
| AP-2 | **AI đề xuất; code xác định quyết định; con người cấp quyền.** | LLM chỉ có tool đọc. Số tiền do `py-core` tính. Duyệt và ngoại lệ là chữ ký EIP-712 của người. |
| AP-3 | **Mỗi khóa chỉ nằm ở đúng một nơi.** | Khóa owner nằm trong ví người dùng. Khóa executor chỉ nằm trong `signer`. Khóa ký attestation chỉ nằm trong `worker` (core). **Mọi lời gọi LLM chạy trong `worker-ai`, nơi không có khóa ký nào.** |
| AP-4 | **Ghi trước khi làm; không đoán kết quả.** | Outbox giao dịch trong Postgres. Unknown không có nghĩa là thất bại. Phục hồi xong mới làm việc mới. |
| AP-5 | **Monolith chia module ở phần off-chain.** | Một API, một codebase worker, một package lõi dùng chung. Ranh giới do cấu trúc module đảm bảo, không qua lời gọi mạng (trừ `signer`). |
| AP-6 | **Bằng chứng có sẵn ngay từ thiết kế.** | Mọi quyết định, lời gọi AI, giao dịch và bước xác minh đều được ghi kèm ID để ghép thành gói bằng chứng. |

## 2. Bối cảnh

Người dùng và hệ thống bên ngoài tương tác với TreasuryPilot như sau:

- **Operator** gửi hóa đơn vào hệ thống.
- **Approver** ký duyệt EIP-712 bằng ví.
- **Owner / Guardian** ký các giao dịch quản trị (mandate, payee, ngoại lệ, tạm dừng) trực tiếp lên Safe bằng ví của mình.
- **Finance / Auditor** đối soát và xuất file.
- TreasuryPilot đọc trạng thái và gửi lời gọi module lên **chain EVM** (các Safe và `TreasuryPilotModule`).
- TreasuryPilot gọi **Claude API** để trích xuất, lập kế hoạch và chạy Copilot.
- Kết nối phụ: Telegram, email (Resend), dịch vụ sàng lọc (M1 dùng dữ liệu mẫu).

## 3. Các thành phần chạy (container)

| Thành phần | Công nghệ | Nhiệm vụ | Công khai? |
|---|---|---|---|
| `web` | React + wagmi | Toàn bộ giao diện; ký bằng ví của người dùng | Có |
| `api` | FastAPI | REST `/v1`, SSE, đăng nhập, phân quyền | Có |
| `worker` (hàng đợi core) | Celery | Trigger, lập kế hoạch xác định, kiểm tra chính sách, ký attestation, gọi signer, theo dõi giao dịch, phục hồi, thông báo | Không |
| `worker-ai` (hàng đợi ai) | Celery | Chỉ chạy tác vụ LLM. **Không giữ khóa ký nào**, chỉ có API key của LLM | Không |
| `beat` | Celery beat | Lịch chạy định kỳ | Không |
| `signer` | FastAPI nội bộ | Giữ khóa executor; kiểm tra attestation rồi mới ký và gửi | Không |
| `postgres` | PostgreSQL 16 | Nguồn dữ liệu chuẩn, outbox, audit | Không |
| `redis` | Redis 7 | Broker cho Celery | Không |
| `minio` / S3 | Object storage | Tệp hóa đơn (riêng tư) | Không |

Trên chain (M1 dùng testnet): `TreasuryPilotModule` (mỗi treasury một module), Safe T, Safe O1, Safe O2, token stablecoin, router test (P2), EAS (P2).

### Ranh giới tin cậy

| Ranh giới | Cái gì đi qua | Cơ chế kiểm soát |
|---|---|---|
| Trình duyệt ↔ API | Thao tác người dùng | Cookie phiên, CSRF token, RBAC, giới hạn tần suất |
| API/worker ↔ LLM | Prompt chứa dữ liệu không tin cậy đã gắn nhãn | Tool chỉ đọc, schema, validator chạy sau |
| worker ↔ signer | Payload bước đã có attestation | Mạng nội bộ + bí mật dùng chung; signer tự kiểm lại attestation; không có endpoint nào khác |
| signer ↔ chain | Giao dịch đã ký | Chỉ gọi các hàm có kiểu của `TreasuryPilotModule` |
| Module ↔ Safe | `execTransactionFromModule` | Module kiểm mọi luật "C"; không có hàm execute tùy ý |
| Ví Owner ↔ Safe | Giao dịch quản trị | Chữ ký của chính Owner, nằm ngoài TreasuryPilot |

## 4. Thiết kế on-chain

**Mỗi treasury có một `TreasuryPilotModule`**, được bật trên cả ba Safe T, O1, O2. Module lưu:
- mandate (phiên bản, trạng thái, hạn, hạn mức, buffer, đường refill, executor);
- danh sách payee kèm `activeFrom`;
- danh sách approver;
- bộ đếm theo `(hành động, tài sản, ngày)`;
- các ID yêu cầu, ID bước và fingerprint đã dùng;
- nonce của ngoại lệ.

| Hàm | Ai gọi | Kiểm tra |
|---|---|---|
| `configureMandate`, `setApprovers`, `addPayee`, `deactivatePayee`, `resume`, `revoke` | Chính Safe T (Owner ký giao dịch Safe) | Chỉ đường của owner; tăng phiên bản |
| `pause()` | Safe T hoặc địa chỉ Guardian | Gọi lặp không sao |
| `refill(approval, chữ ký, stepId, ví đích, số tiền)` | executor | Mandate đang hiệu lực, không tạm dừng; đường được phép; hạn mức refill; buffer của T; bước chưa dùng; **có chữ ký duyệt hợp lệ cho hóa đơn đang được cấp tiền**; ví đích đúng là ví trả trong bản duyệt |
| `pay(approval, chữ ký, ngoại lệ, chữ ký owner, stepId)` | executor | Chữ ký duyệt đúng và người ký thuộc danh sách approver hiện tại; payee đã hết thời gian chờ; fingerprint và yêu cầu chưa dùng; trần mỗi khoản (hoặc có ngoại lệ hợp lệ); trần ngày; buffer sau khi trả; không tạm dừng, chưa hết hạn |
| `swapForGas(...)` (P2) | executor | Router và cặp trong allowlist; ngân sách swap; minOut; allowance đúng lượng rồi về 0 |

Không có hàm `execute` tùy ý, không có `delegatecall`, module không đổi được owner hay module khác.

## 5. Các luồng chính

### 5.1 Thanh toán tự động

1. `beat` phát nhịp cho treasury.
2. `worker` lấy khóa theo treasury trong Postgres; kiểm tra: đang tạm dừng không, mức bao phủ, có thao tác Unknown không.
3. Chụp snapshot tại block N.
4. Engine tính thiếu hụt, lượng refill và lịch trả theo điều khoản.
5. `worker-ai` xin Claude đề xuất kế hoạch (tool chỉ đọc, schema chặt).
6. Engine chấm điểm đề xuất AI so với kế hoạch xác định.
7. Policy engine kiểm tra → ALLOW / NEEDS_APPROVAL / BLOCK.
8. **Nếu ALLOW:**
   - ký attestation (planHash, nonce, hạn dùng);
   - ghi thao tác vào outbox với trạng thái NotSubmitted;
   - gửi signer; signer kiểm tra attestation và payload, mô phỏng, ký, gửi lên module;
   - lưu txHash;
   - theo dõi receipt đến khi đủ số xác nhận;
   - đọc lại trạng thái, kiểm tra hậu điều kiện;
   - ghi Paid, tạo bản đối soát, ghi audit và bằng chứng.
9. **Nếu NEEDS_APPROVAL:** AI soạn yêu cầu ngoại lệ → tạo mục xem xét → báo Owner.
10. **Nếu BLOCK:** tạo mục xem xét kèm mã lý do.

### 5.2 Phục hồi khi khởi động lại

1. Tải các thao tác đang ở trạng thái NotSubmitted, Submitted, Pending, Unknown.
2. Với từng thao tác: tra receipt theo txHash, rồi nonce, rồi cờ `requestUsed`/`stepUsed` trên module.
3. Kết luận: Confirmed, Reverted, hay vẫn Pending. Nếu chưa từng broadcast thì gửi lại với **đúng các ID cũ**.
4. Treasury còn thao tác chưa rõ thì trigger bỏ qua treasury đó.

### 5.3 Duyệt hóa đơn

Web lấy dữ liệu EIP-712 `PaymentApproval` từ API → ví ký → API kiểm tra chữ ký, maker-checker và danh sách approver hiện tại → lưu → `Approved`. Contract kiểm tra lại khi PAY.

## 6. Các vấn đề xuyên suốt

| Vấn đề | Cách xử lý |
|---|---|
| Idempotency | Ba lớp: header `Idempotency-Key` ở API; ID thao tác ở backend; cờ đã dùng on-chain |
| Đồng thời | Advisory lock theo treasury; optimistic lock (cột `version`) trên yêu cầu chi |
| Thời gian | Mọi timestamp là UTC. Hạn mức ngày dùng thời gian của block. Hiển thị theo múi giờ tổ chức |
| Tiền | Số nguyên ở đơn vị nhỏ nhất: `NUMERIC(78,0)` trong DB, `int` trong Python, `bigint` trong TS |
| Cấu hình | Pydantic settings; manifest `deployments/<chain>.json` nằm trong repo |
| Bí mật | `.env` khi chạy local; Docker secrets trên VM; mật khẩu keystore của signer tách riêng |
| Realtime | Luồng SSE `/v1/orgs/{orgId}/events` |
| Lỗi | Định dạng problem+json (RFC 9457); mã `code` cố định, khớp với mã lý do của validator |

## 7. Triển khai (M1)

Docker Compose trên một máy ảo cloud. Chỉ `web` và `api` được mở ra ngoài, qua reverse proxy có TLS. `signer`, `postgres`, `redis`, `minio` chỉ nằm trong mạng nội bộ.

Ba profile: `local` (có Anvil và dữ liệu mẫu) · `testnet` · `ci`.

## 8. Hướng phát triển cho production (Later)

Signer dùng KMS · Postgres managed có khôi phục theo thời điểm · worker chia theo treasury · treasury đa chain · audit contract bên ngoài trước khi lên mainnet · nhà cung cấp KYB/KYT/Travel Rule · tích hợp ERP · email và webhook.
