# M13 · Thông báo

**Nguồn chuẩn:** `docs/modules/notifications/README.md` · **Trạng thái:** Chi tiết — quyết định đã chốt (trưởng nhóm ủy quyền cho tech lead, 11/10/2026) · **ADR:** ADR-010

## 1. Mục đích và ranh giới

M13 đảm bảo **đúng người biết đúng sự kiện, nhanh, mà không lộ dữ liệu nhạy cảm**, và giao diện cập nhật trực tiếp. Thông báo không bao giờ chứa hành động chuyển tiền: mọi link đều dẫn về app, nơi áp dụng quyền và chữ ký.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Bus sự kiện miền (bảng outbox + publisher) | Email, webhook, Slack/Lark/WeCom, tùy chọn thông báo (Later NTF-L01…L04) |
| Định tuyến sự kiện → vai trò, chống trùng theo event id | |
| Thông báo trong app + luồng SSE cho trạng thái trực tiếp | |
| Kênh Telegram: liên kết, nội dung tối thiểu, bật số tiền theo lựa chọn (P2) | |

## 2. Feature, yêu cầu

F-100 (FR-901), F-101 (FR-902, OQ-17), F-132 (timeline trực tiếp qua SSE); Later F-102…F-105.

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Sự kiện miền** | `{id, org_id, treasury_id?, type, entity, payload (chỉ id), at}` ghi trong cùng transaction DB với thay đổi (outbox). |
| **Luật định tuyến** | loại sự kiện → vai trò (+ người cụ thể, ví dụ người tạo request). |
| **Sự kiện bắt buộc** | Sau này không cho tắt (an ninh: pause, tiền ra bất thường, chênh lệch, coverage giảm, circuit breaker). |

## 4. Mô hình dữ liệu

`domain_events` (org, treasury, type, entity, payload, created_at, published_at) · `notifications` (user, event, type, title, body, link, severity INFO/ACTION/CRITICAL, read_at; duy nhất (user, event)) · `notification_channels` (TELEGRAM, chat id mã hóa, verified_at, show_amounts) · `telegram_link_codes` (mã băm, user, hạn, đã dùng).

## 5. Bảng định tuyến (M1)

| Sự kiện | Vai trò | Mức |
|---|---|---|
| Cần duyệt (request được submit) | Approver | ACTION |
| Có cờ HIGH | Approver, Operator | ACTION |
| Cần ngoại lệ (NEEDS_APPROVAL) | Owner | ACTION |
| Cần chữ ký giao dịch quản trị | Owner của Safe đó | ACTION |
| Cần chấp nhận phí | Finance, Operator, Owner | ACTION |
| Đã trả (Paid) | Operator, Finance, người tạo request | INFO |
| Cần xem xét (mọi review item) | vai trò được giao (M12) | ACTION |
| Giao dịch Unknown | Operator, Owner | CRITICAL |
| Yêu cầu pause / pause có hiệu lực / resume | Owner, Guardian, Operator | CRITICAL |
| Circuit breaker kích hoạt | Owner, Guardian | CRITICAL |
| Tiền ra bất thường | Owner, Finance | CRITICAL |
| Coverage đổi (không còn COMPLETE) | Owner, OrgAdmin | CRITICAL |
| Sắp hết gas (executor/sentinel/biên nhận) | Operator, OrgAdmin | ACTION |
| Mandate sắp hết hạn (7 ngày / 48 giờ / 1 giờ) | Owner | ACTION |
| Chênh lệch đối soát | Finance, Owner | CRITICAL |

## 6. Giao diện

GET `/notifications?unread=` · POST `/notifications/read` `{ids}` · GET `/orgs/{o}/events` (SSE; tiếp nối bằng `Last-Event-ID`; nhịp 15 giây) · POST `/me/channels/telegram/link-code` → `{code, botUrl}` · POST `/integrations/telegram/webhook` (header bí mật) · PATCH `/me/channels/{id}` `{showAmounts}`. Loại sự kiện SSE: `request.status`, `plan.status`, `operation.status`, `review.created`, `notification.created`, `treasury.status`.

## 7. Luồng

Thay đổi + dòng `domain_events` trong một transaction → publisher (mỗi 1 giây, `FOR UPDATE SKIP LOCKED`) → định tuyến → `notifications` (chống trùng) → đẩy SSE qua Redis pub/sub theo tổ chức → gửi Telegram (P2) cho ACTION/CRITICAL tới người đã liên kết.

## 8. Thuật toán

- **Nội dung Telegram (OQ-17):** mặc định `"[TreasuryPilot] Cần duyệt request R-1042 · mở: <link>"`, không số tiền, địa chỉ, tên vendor; nếu bật `show_amounts` thì thêm số tiền và tên vendor. Link sâu yêu cầu đăng nhập app.
- **Chống trùng:** duy nhất (user, event). **Tần suất:** tối đa 1 tin Telegram mỗi 10 giây cho một người, tin dồn được gộp thành một dòng tóm tắt.

## 9. Cấu hình

Publisher 1 giây; nhịp SSE 15 giây; mã liên kết Telegram 10 phút; Telegram thử lại 3 lần có backoff.

## 10. Bảo mật

Luồng theo tổ chức; payload chỉ có id (giao diện tự lấy chi tiết theo quyền); webhook Telegram có header bí mật; không thể làm hành động nào từ Telegram; chat id mã hóa (Confidential).

## 11. Tình huống lỗi

Telegram lỗi → vẫn có thông báo trong app, thử lại · Redis pub/sub lỗi → client SSE chuyển sang hỏi định kỳ mỗi 10 giây · publisher chết → dòng outbox được phát lại (chống trùng ngăn lặp).

## 12. Kế hoạch test

Test bảng định tuyến; chống trùng; SSE cô lập theo tổ chức và trễ < 2 giây; nội dung Telegram có/không bật số tiền; hết hạn mã liên kết.

## 13. Ticket

NTF-001 → NTF-002 → NTF-003 (P2). Later NTF-L01…L04.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M13-D1 | Sự kiện miền qua bảng outbox, cùng transaction với thay đổi. |
| M13-D2 | Bảng định tuyến §5; định nghĩa sẵn sự kiện CRITICAL bắt buộc cho phần tùy chọn sau này. |
| M13-D3 | SSE theo tổ chức, tiếp nối bằng Last-Event-ID. |
| M13-D4 | Payload chỉ chứa id. |
| M13-D5 | Telegram mặc định tối thiểu; số tiền chỉ khi người dùng bật (OQ-17). |
| M13-D6 | Không hoàn tất được hành động nào từ kênh thông báo. |
| M13-D7 | Telegram 1 tin / 10 giây mỗi người, có gộp. |
| M13-D8 | SSE chuyển sang hỏi định kỳ 10 giây khi pub/sub lỗi. |
| M13-D9 | Sự kiện mới từ grilling: cần chữ ký quản trị, cần chấp nhận phí, tiền ra bất thường, circuit breaker kích hoạt. |
