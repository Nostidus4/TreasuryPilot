# TreasuryPilot: Đặc tả API (v1)

**Nguồn chuẩn:** `docs/API_SPEC.md` (có đủ request, response và mã lỗi cho từng endpoint) · **Kiểu:** REST + JSON, OpenAPI 3.1 do FastAPI sinh ra

## 1. Quy ước chung

| Mục | Quy tắc |
|---|---|
| Base URL | `/v1` |
| Xác thực | Cookie phiên `tp_session`; các lệnh thay đổi dữ liệu cần thêm header `X-CSRF-Token` |
| Đa tổ chức | Route theo tổ chức bắt đầu bằng `/v1/orgs/{orgId}`. Không phải thành viên thì nhận 404 |
| Phân quyền | Ghi theo vai trò: `OWN` Owner, `APR` Approver, `OPR` Operator, `FIN` Finance, `GRD` Guardian, `ADM` OrgAdmin, `AUD` Auditor, `ANY` mọi thành viên |
| Số tiền | **Chuỗi** số nguyên ở đơn vị nhỏ nhất, ví dụ `"25000000"` |
| Idempotency | Header `Idempotency-Key` bắt buộc với các POST tài chính (đánh dấu 🔁) |
| Phân trang | `?cursor=&limit=` → `{items, nextCursor}` |
| Lỗi | Định dạng problem+json; trường `code` có giá trị cố định |
| Đồng thời | Tài nguyên sửa được trả về `ETag`; khi sửa phải gửi `If-Match`, sai thì nhận 412 |

## 2. Định danh & tổ chức (M01)

| Method | Endpoint | Mục đích | Quyền |
|---|---|---|---|
| POST | `/auth/magic-link` | Gửi link đăng nhập | công khai |
| POST | `/auth/magic-link/verify` | Đổi token lấy phiên | công khai |
| POST | `/auth/logout` | Đăng xuất | đã đăng nhập |
| GET | `/me` | User hiện tại, tổ chức, ví đã liên kết | đã đăng nhập |
| GET | `/auth/siwe/nonce` | Lấy nonce SIWE | đã đăng nhập |
| POST | `/me/wallets` | Liên kết ví bằng SIWE | đã đăng nhập |
| DELETE | `/me/wallets/{address}` | Hủy liên kết ví | đã đăng nhập |
| POST | `/orgs` | Tạo tổ chức | đã đăng nhập |
| GET | `/orgs/{orgId}` | Thông tin tổ chức và checklist | ANY |
| PATCH | `/orgs/{orgId}/settings` | Solo mode, tự đối soát… | ADM (solo mode: OWN) |
| GET / POST | `/orgs/{orgId}/members`, `/invites` | Xem thành viên, mời | ANY / ADM |
| PATCH / DELETE | `/orgs/{orgId}/members/{userId}` | Đổi vai trò, xóa | ADM |

## 3. Treasury & chain (M02)

| Method | Endpoint | Mục đích | Quyền |
|---|---|---|---|
| GET | `/chains` | Chain và tài sản được hỗ trợ | đã đăng nhập |
| POST | `/orgs/{o}/treasuries` | Tạo treasury | OWN, ADM |
| GET | `/orgs/{o}/treasuries/{t}` | Trạng thái treasury: số dư, bao phủ, mandate, ngân sách hôm nay | ANY |
| POST | `…/module/deploy-tx` | Tạo giao dịch Safe để triển khai và bật module | OWN |
| POST | `…/coverage/refresh` | Đọc lại cấu hình Safe | OWN, ADM |
| POST | `…/coverage/acknowledge` | Chấp nhận bao phủ một phần | OWN |

## 4. Mandate, payee, ngoại lệ, tạm dừng (M03)

| Method | Endpoint | Mục đích | Quyền |
|---|---|---|---|
| GET | `…/mandates` | Lịch sử phiên bản | ANY |
| POST | `…/mandates` | Tạo bản nháp; trả về tóm tắt và so sánh | OWN |
| POST | `…/mandates/{v}/activation-tx` | Tạo giao dịch Safe kích hoạt | OWN |
| POST 🔁 | `…/mandates/{v}/activation` | Báo tx hash; hệ thống theo dõi đến khi Active | OWN |
| GET | `…/payees` | Danh sách payee | ANY |
| POST | `…/payees` | Đề xuất hoặc thêm payee (chạy sàng lọc) | OPR, ADM, OWN |
| POST | `…/payees/{id}/registration-tx` | Tạo giao dịch đăng ký payee | OWN |
| POST | `…/payees/{id}/deactivation-tx` | Tạo giao dịch vô hiệu payee | OWN |
| POST 🔁 | `…/pause` | Dừng backend ngay và tạo giao dịch dừng on-chain | OWN, GRD |
| POST | `…/resume-tx` | Tạo giao dịch chạy lại | OWN |
| GET | `/orgs/{o}/requests/{r}/exception` | Xem yêu cầu ngoại lệ (bản AI soạn + số liệu) | OWN, OPR, FIN |
| POST 🔁 | `/orgs/{o}/requests/{r}/exception` | Gửi chữ ký EIP-712 của Owner | OWN |
| POST | `…/exception/reject` | Từ chối | OWN |

## 5. Hóa đơn & yêu cầu chi (M05)

| Method | Endpoint | Mục đích | Quyền |
|---|---|---|---|
| POST 🔁 | `/orgs/{o}/requests` | Tạo bản nháp thủ công | OPR, ADM |
| POST 🔁 | `…/requests/upload` | Upload PDF/ảnh → job trích xuất | OPR |
| POST 🔁 | `…/requests/import-csv` | Nhập CSV | OPR |
| GET | `…/requests`, `…/requests/{r}` | Danh sách, chi tiết | ANY |
| PATCH | `…/requests/{r}` | Sửa bản nháp (tạo revision mới) | OPR |
| POST | `…/requests/{r}/terms/confirm` | Xác nhận điều khoản | OPR |
| POST | `…/requests/{r}/submit` | Gửi duyệt | OPR |
| POST | `…/requests/{r}/flags/{f}/ack` | Xác nhận đã đọc cờ | APR |
| GET | `…/requests/{r}/approval-typed-data` | Lấy dữ liệu EIP-712 để ký | APR |
| POST 🔁 | `…/requests/{r}/approve` | Gửi chữ ký duyệt | APR |
| POST | `…/requests/{r}/reject`, `…/cancel` | Từ chối, hủy | APR / OPR, OWN |

## 6. Lập kế hoạch, thực thi, xem xét (M07–M10, M12)

| Method | Endpoint | Mục đích | Quyền |
|---|---|---|---|
| GET | `…/treasuries/{t}/plans`, `/orgs/{o}/plans/{p}` | Kế hoạch, các bước, kết quả kiểm tra, giải thích AI | ANY |
| POST 🔁 | `…/treasuries/{t}/run-now` | Operator kích hoạt ngay (vẫn qua các cổng an toàn) | OPR |
| GET | `/orgs/{o}/operations/{id}` | Thao tác, giao dịch, kết quả xác minh | ANY |
| GET | `…/treasuries/{t}/forecast` | Runway 7 ngày | ANY |
| GET | `/orgs/{o}/review-items` | Hàng đợi cần xem xét | ANY (lọc theo vai trò) |
| POST 🔁 | `…/review-items/{id}/actions` | Thử lại, hủy, đánh dấu xong | theo loại mục |
| GET | `/orgs/{o}/events` | Luồng SSE | ANY |

## 7. Đối soát, bằng chứng, chỉ số (M11, M15, M17)

| Method | Endpoint | Mục đích | Quyền |
|---|---|---|---|
| GET | `/orgs/{o}/reconciliations` | Danh sách | FIN, AUD |
| POST | `…/reconciliations/{id}/match`, `…/discrepancy` | Đánh dấu khớp, ghi chênh lệch | FIN |
| GET | `/orgs/{o}/exports/reconciliation.csv` | Xuất CSV hoặc bút toán | FIN, AUD |
| GET | `/orgs/{o}/requests/{r}/evidence` | Gói bằng chứng | FIN, AUD, ADM |
| GET | `/orgs/{o}/audit-log`, `…/verify` | Đọc audit, kiểm tra chuỗi hash | AUD, ADM |
| GET | `/orgs/{o}/metrics/operations`, `…/savings` | Chỉ số vận hành, báo cáo tiết kiệm | OWN, FIN, AUD |

## 8. Copilot, thông báo

| Method | Endpoint | Mục đích |
|---|---|---|
| POST | `/orgs/{o}/copilot/threads`, `…/threads/{id}/messages` | Tạo hội thoại, đặt câu hỏi (trả lời dạng stream) |
| GET | `/orgs/{o}/notifications`; POST `…/{id}/read` | Hộp thông báo |
| POST | `/me/channels/telegram/link` | Liên kết Telegram |

## 9. API nội bộ của signer (không công khai)

| Method | Endpoint | Ai gọi | Mục đích |
|---|---|---|---|
| POST | `/sign-and-send` | worker (mạng nội bộ + bí mật dùng chung) | Kiểm tra attestation, so khớp payload, mô phỏng, ký và gửi. Trả về txHash |
| GET | `/health` | compose | Địa chỉ executor và số dư gas |

## 10. Mã lỗi cố định

Mã lỗi của API khớp với mã lý do của validator và với lỗi revert của contract.

| Nhóm | Mã |
|---|---|
| Duyệt | `NOT_APPROVED`, `APPROVAL_INVALID`, `APPROVAL_EXPIRED`, `NOT_IN_APPROVER_SET`, `MAKER_CHECKER` |
| Payee | `PAYEE_UNKNOWN`, `PAYEE_COOLING`, `SCREENING_HIT` |
| Hạn mức | `OVER_PER_REQUEST_LIMIT` (→ cần ngoại lệ), `OVER_DAILY_LIMIT` |
| Thanh khoản | `BUFFER_BREACH`, `SOURCE_INSUFFICIENT` |
| Chống lặp | `DUPLICATE_FINGERPRINT`, `REQUEST_ALREADY_PAID`, `STEP_ALREADY_EXECUTED` |
| Vòng đời mandate | `MANDATE_PAUSED`, `MANDATE_EXPIRED`, `MANDATE_NOT_ACTIVE` |
| Cổng an toàn | `COVERAGE_INCOMPLETE`, `SNAPSHOT_STALE`, `UNKNOWN_OPERATION_PENDING` |
| AI | `AI_PLAN_REJECTED`, `AI_UNAVAILABLE` |
| Signer | `ATTESTATION_INVALID`, `PAYLOAD_MISMATCH` |
