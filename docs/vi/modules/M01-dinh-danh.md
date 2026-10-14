# M01 · Định danh & phân quyền

**Nguồn chuẩn:** `docs/modules/identity/README.md` · **Trạng thái:** Chi tiết — quyết định đã chốt (trưởng nhóm ủy quyền cho tech lead, 11/10/2026) · **ADR:** ADR-009

## 1. Mục đích và ranh giới

M01 trả lời: **người này là ai, đang thao tác cho tổ chức nào, được làm gì, và ví nào chứng minh quyền ký của họ**. Đăng nhập app không bao giờ cho quyền on-chain: vai trò ký chỉ hành động qua ví đã liên kết (BR-006).

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Đăng nhập magic link, phiên, CSRF, giới hạn tần suất | MFA, SSO, SCIM (Later: IDN-L01…L03) |
| Liên kết ví bằng SIWE (EOA + ERC-1271) | Khóa owner (không bao giờ giữ, BR-092) |
| Tổ chức, checklist onboarding, cài đặt (solo mode, auto-match) | Billing (M18) |
| Thành viên, 8 vai trò, lời mời, chặn xóa admin/owner cuối | |
| RBAC, cô lập tenant (trả 404 cho người ngoài tổ chức) | |
| Dịch vụ maker-checker và solo mode | |

## 2. Feature, yêu cầu, luật

F-001 (FR-001–003), F-002 (FR-004–006, BR-006), F-003 (FR-007, FR-009), F-004 (FR-008, FR-010–013, BR-093), F-005 (FR-014–015, BR-005); Later F-006/F-007 (FR-016–017).

## 3. Khái niệm và vai trò

| Vai trò | Được làm | Không được |
|---|---|---|
| **OrgAdmin** | quản lý thành viên, vai trò, cài đặt tổ chức (trừ solo mode), tạo treasury (cùng Owner) | ký duyệt/quản trị nếu không đồng thời là Owner/Approver |
| **Owner** | ký giao dịch quản trị Safe (mandate, payee, ngoại lệ, resume, revoke, hủy), bật solo mode, chính sách phí | duyệt request do chính mình tạo (maker-checker) |
| **Approver** | ký `PaymentApproval`, xác nhận cờ, từ chối/yêu cầu sửa, `cancelRequest` on-chain | tạo giao dịch quản trị |
| **Operator** | tạo/sửa request, upload, CSV, đề xuất payee, run-now, xử lý review được giao | duyệt |
| **Finance** | đối soát, xuất file, chấp nhận phí, xử lý chênh lệch | duyệt, quản trị |
| **Guardian** | tạm dừng (backend + Guardian Safe) | resume, mọi việc khác |
| **Auditor** | chỉ đọc mọi thứ kể cả audit log và gói bằng chứng | ghi bất cứ gì |
| **PlatformAdmin** | vận hành nền tảng (M18); mặc định không xem dữ liệu khách | ký hoặc chuyển tiền (BR-094) |

Một người có thể giữ nhiều vai trò. Vai trò ký (Owner, Approver, Guardian) **chưa có hiệu lực** cho đến khi liên kết ví (FR-012). Owner trong app = người có ví liên kết là owner của Safe T (kiểm tra on-chain khi liên kết và định kỳ).

## 4. Mô hình dữ liệu

`users`, `sessions` (rảnh 30 phút, tối đa 12 giờ), `magic_links` (băm, dùng 1 lần, 15 phút), `wallet_links` (một địa chỉ chỉ thuộc một người), `siwe_nonces` (dùng 1 lần, 10 phút), `organizations` (+ `settings`: solo_mode, auto_match, display_tz), `memberships` (roles[]), `invites` (token băm, 7 ngày), `role_events` (append-only).

## 5. Trạng thái

Lời mời: `Pending → Accepted | Expired | Revoked`. Phiên: `Active → Expired | Revoked`. Liên kết ví: `Linked → Unlinked` (từ chối gỡ nếu đó là ví ký duy nhất mà vai trò còn việc đang chờ).

## 6. Giao diện API (API_SPEC §1)

| Method | Endpoint | Quyền | Lỗi |
|---|---|---|---|
| POST | `/auth/magic-link` | công khai, giới hạn 5/15 phút mỗi email, 20/15 phút mỗi IP | 429 `RATE_LIMITED` |
| POST | `/auth/magic-link/verify` | công khai, giới hạn 20/15 phút mỗi IP; trả `{user, csrfToken}` | `TOKEN_INVALID`, `TOKEN_EXPIRED`, `RATE_LIMITED` |
| POST/GET | `/auth/logout`, `/me` | đã đăng nhập | |
| GET/POST/DELETE | `/auth/siwe/nonce`, `/me/wallets`, `/me/wallets/{a}` | đã đăng nhập | `SIWE_INVALID`, `ADDRESS_LINKED_ELSEWHERE`, `SIGNER_ROLE_REQUIRES_WALLET` |
| POST/GET/PATCH | `/orgs`, `/orgs/{o}`, `/orgs/{o}/settings` | đăng nhập / thành viên / ADM (solo: OWN) | 403 |
| GET/POST | `/orgs/{o}/members`, `/orgs/{o}/invites`, `/invites/{token}/accept` | ADM | `ALREADY_MEMBER`, `INVITE_EXPIRED` |
| PATCH/DELETE | `/orgs/{o}/members/{u}` | ADM | `LAST_ADMIN`, `LAST_OWNER` |

Thông điệp SIWE: domain = host của app, `chainId` = chain của treasury (11155111), nonce dùng một lần, hết hạn 10 phút, lệch giờ cho phép ± 2 phút.

## 7. Luồng chính

Đăng nhập: nhập email → nhận link (Resend; local in ra console) → xác thực → cookie phiên (httpOnly, Secure, SameSite=Lax) + token CSRF. Checklist onboarding: thành viên → liên kết ví → treasury → bật module → mandate Active → payee Active → hóa đơn đầu tiên; tính từ dữ liệu thật, không lưu cờ.

## 8. Thuật toán

- **RBAC:** dependency `require_member(org)` (không phải thành viên → **404**) và `require_role(...)` (thiếu vai trò → 403); repository luôn lọc theo `org_id`. Test tự động liệt kê mọi route thuộc tổ chức và gọi thử bằng người ngoài.
- **Maker-checker:** `assert_maker_checker(request, user_id=..., organization=...)` từ chối người duyệt ∈ {người tạo, người sửa cuối} bằng 409 `MAKER_CHECKER`, trừ khi `solo_mode` đã được bật. Chỉ Owner on-chain được đổi cài đặt này. Handler duyệt hóa đơn thuộc #123/#124 cần gọi helper và lưu kết quả vào bản duyệt cùng audit; phần nối handler chưa thuộc IDN-008.
- **Kiểm tra Owner:** khi liên kết và mỗi giờ, so địa chỉ ví với danh sách owner của Safe T; lệch thì mất quyền Owner thực tế (vai trò vẫn còn nhưng hiện "không phải owner on-chain").

## 9. Cấu hình

Phiên rảnh 30 phút / tối đa 12 giờ; magic link 15 phút; lời mời 7 ngày; nonce SIWE 10 phút; giới hạn tần suất như §6.

## 10. Bảo mật

Token được băm; nonce dùng một lần; CSRF cho mọi thao tác ghi; trả 404 cho người ngoài; audit thay đổi vai trò và ví; M1 không lưu mật khẩu (chỉ magic link); phản hồi giống nhau cho email có/không tồn tại (chống dò email).

## 11. Tình huống lỗi

Dịch vụ email lỗi → link được gửi sau khi đã trả 202, gửi lỗi thì link bị vô hiệu và ghi log; người dùng vẫn nhận 202 (không lộ email có tài khoản) và yêu cầu link mới; Redis lỗi → giới hạn tần suất "đóng" cho endpoint đăng nhập; kho nonce lỗi → từ chối liên kết ví.

## 12. Kế hoạch test

Unit: vòng đời token, xác thực SIWE (EOA + ERC-1271 mô phỏng), ma trận maker-checker. Integration: quét route chống truy cập chéo tổ chức; chặn xóa admin/owner cuối; giới hạn tần suất. Bảo mật: CSRF, cờ cookie.

## 13. Ticket theo thứ tự

IDN-001 → IDN-002 → IDN-003 → IDN-004 → IDN-005 → IDN-006 → IDN-008 → IDN-007. Later: IDN-L01…L03.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M01-D1 | M1 chỉ dùng magic link, không mật khẩu. |
| M01-D2 | Phiên phía server; rảnh 30 phút, tối đa 12 giờ. |
| M01-D3 | Người ngoài tổ chức nhận 404. |
| M01-D4 | 8 vai trò; một người nhiều vai trò; vai trò ký cần ví liên kết. |
| M01-D5 | Quyền Owner trong app yêu cầu ví liên kết là owner Safe T on-chain. |
| M01-D6 | SIWE dùng chainId của treasury; nonce 10 phút; lệch giờ ± 2 phút. |
| M01-D7 | Solo mode do Owner bật, gắn cờ và audit (OQ-07). |
| M01-D8 | Giới hạn tần suất như §6; Redis lỗi thì đóng. |
| M01-D9 | Lời mời hết hạn sau 7 ngày. |
| M01-D10 | Không để lộ email nào đã có tài khoản. |
| M01-D11 | Không cho gỡ ví ký cuối cùng khi vai trò còn việc đang chờ. |
| M01-D12 | Gửi email bằng Resend; local in ra console. |
