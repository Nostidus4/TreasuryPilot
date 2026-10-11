# M18 · Quản trị nền tảng & tính phí (Later)

**Nguồn chuẩn:** `docs/modules/admin/README.md` · **Trạng thái:** Chi tiết ở mức Later — quyết định đã chốt (11/10/2026)

## 1. Mục đích và ranh giới

M18 là cách **công ty TreasuryPilot** vận hành nền tảng: quản lý tenant, truy cập hỗ trợ có đồng ý, đo mức sử dụng và tính phí thuê bao. Ở M1 chỉ có cấu hình nền tảng (file kiểm khi khởi động, M02-D8); mọi thứ khác là Later.

**Ranh giới cứng (BR-094, BR-091):** PlatformAdmin không bao giờ được ký, duyệt, chuyển tiền của khách hay trừ phí từ treasury của khách.

| M1 | Later |
|---|---|
| Cấu hình + manifest kiểm khi khởi động (TRS-002) | Bảng quản trị (ADM-L01), đo sử dụng (ADM-L02), thuê bao và hóa đơn (ADM-L03) |

## 2. Feature

F-150 (FR-924), F-151 (FR-925, M1 qua TRS-002), F-152 (FR-926).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **PlatformAdmin** | Vai trò nhân viên ngoài mọi tổ chức; chỉ thấy metadata của tenant. |
| **Truy cập hỗ trợ** | Quyền chỉ đọc có thời hạn vào một tổ chức, do OrgAdmin cấp, có audit đầy đủ. |
| **Mức sử dụng** | Số request Paid và tổng giá trị đã trả mỗi tổ chức mỗi tháng (tính từ sự kiện). |

## 4. Mô hình dữ liệu (Later)

`platform_settings`, `tenants_status` (active/suspended), `support_grants` (org, nhân viên, scope = read, hạn, người cấp), `usage_monthly` (org, tháng, số Paid, giá trị), `billing_*` (gói, thuê bao, hóa đơn — thanh toán bằng thẻ/ngân hàng, ngoài treasury của khách).

## 5. Trạng thái

Tenant `Active ⇄ Suspended` (tạm ngưng chỉ dừng lập kế hoạch, không đụng tới tiền). Quyền hỗ trợ `Requested → Granted → Expired | Revoked`.

## 6. Giao diện (Later)

`/admin/tenants`, `/admin/tenants/{id}/suspend`, `/orgs/{o}/support-grants`, `/admin/usage`, `/orgs/{o}/billing`. API admin là router riêng, đăng nhập riêng (SSO nhân viên) và giới hạn IP.

## 7–8. Luồng và thuật toán

Truy cập hỗ trợ: OrgAdmin cấp quyền chỉ đọc 24 giờ → nhân viên xem tổ chức qua API thường với cờ `support` → mọi request ghi vào audit của tổ chức. Đo sử dụng: job hằng tháng trên `request_status_events` (Paid) và `reconciliation_lines` (EXTERNAL_EXPENSE).

## 9. Cấu hình

Mô hình giá quyết định sau (Later); chính sách tạm ngưng; quyền hỗ trợ tối đa 72 giờ.

## 10. Bảo mật

Router admin tách riêng; không truy cập signer; phiên hỗ trợ chỉ đọc và có audit; tạm ngưng không pause on-chain được (chỉ Owner/Guardian làm được).

## 11. Tình huống lỗi

Cấu hình nền tảng sai → các service không khởi động (M1).

## 12. Kế hoạch test (Later)

Không endpoint admin nào gọi được signer hay bộ dựng giao dịch quản trị (test tĩnh theo route); hết hạn quyền hỗ trợ; mức sử dụng khớp kho sự kiện.

## 13. Ticket

ADM-L01 → ADM-L02 → ADM-L03 (đều Later). Cấu hình M1: TRS-002.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M18-D1 | M1 không có bảng quản trị; chỉ có file cấu hình. |
| M18-D2 | PlatformAdmin không bao giờ ký hay chuyển tiền (BR-094). |
| M18-D3 | Truy cập hỗ trợ chỉ khi OrgAdmin cấp, chỉ đọc, ≤ 72 giờ, có audit. |
| M18-D4 | Không bao giờ trừ phí từ treasury của khách (BR-091). |
| M18-D5 | Tạm ngưng chỉ dừng lập kế hoạch; pause on-chain vẫn thuộc Owner/Guardian. |
| M18-D6 | Mô hình giá là quyết định kinh doanh để Later. |
