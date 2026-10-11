# M14 · Tuân thủ

**Nguồn chuẩn:** `docs/modules/compliance/README.md` · **Trạng thái:** Chi tiết — quyết định đã chốt (trưởng nhóm ủy quyền cho tech lead, 11/10/2026)

## 1. Mục đích và ranh giới

M14 giữ cho TreasuryPilot **không trả nhầm đối tượng** (sàng lọc danh sách trừng phạt/chặn) và **không làm lộ dữ liệu** (phân loại, mã hóa, che log). Ở M1 nhà cung cấp sàng lọc là dữ liệu mẫu có nhãn; adapter cho phép thay bằng nhà cung cấp thương mại sau này.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Adapter sàng lọc + nhà cung cấp mẫu (TEST DATA) | KYB, Travel Rule, lưu giữ/xóa dữ liệu, khu vực lưu trữ (Later) |
| Sàng lọc khi đăng ký payee và trước mỗi PAY (có hạn) | Ý kiến pháp lý (ticket DOM) |
| Phân loại dữ liệu, mã hóa trường, che log | |

## 2. Feature, yêu cầu, luật

F-110 (FR-906, BR-085, NFR-CMP-04), F-113 (FR-909, BR-074, NFR-PRIV-01–04); Later F-111, F-112, F-114.

## 3. Khái niệm — các mức dữ liệu

| Mức | Ví dụ | Cách xử lý |
|---|---|---|
| **Public** | tx hash, địa chỉ contract | không |
| **Internal** | request id, số tiền, trạng thái | cô lập theo tổ chức |
| **Confidential** | liên hệ vendor, email, chat id Telegram, tài liệu hóa đơn, ghi chú xác minh ngoài kênh | mã hóa khi lưu (AES-GCM theo trường, khóa từ Docker secret), che trong log, không bao giờ lên chain |
| **Secret** | khóa, token, bí mật của signer | không bao giờ vào DB/log; chỉ nằm trong kho bí mật |

Kết quả sàng lọc: `CLEAR | HIT | ERROR`, hạn 24 giờ.

## 4. Mô hình dữ liệu

`screenings` (M03 §4) · `screening_lists` (địa chỉ mẫu: nguồn, tên danh sách, ngày thêm; gắn TEST DATA) · `encryption_keys_meta` (key id, ngày tạo, ngày xoay; khóa thật nằm ngoài DB).

## 5. Trạng thái

Sàng lọc payee: `Screening → CLEAR | HIT | ERROR`; sàng lọc lại khi hết hạn hoặc trước PAY nếu đã cũ.

## 6. Giao diện

Nội bộ: `screen(address, chain)`, `encrypt(value, cls)` / `decrypt`, các processor che log của structlog. API: GET `/payees/{id}/screenings` (OWN, ADM, Auditor).

## 7. Luồng

Đề xuất payee → sàng lọc → CLEAR → Owner mới được đăng ký (M03). Trước mỗi PAY (validator M08): kết quả gần nhất ≤ 24 giờ? CLEAR → qua; đã cũ → làm mới đồng bộ (timeout 5 giây); HIT hoặc ERROR → BLOCK `SCREENING_HIT` / `DATA_MISSING` (đóng khi lỗi, BR-085).

## 8. Thuật toán

- Danh sách mẫu: một phần địa chỉ từ danh sách trừng phạt công khai (ghi nguồn và ngày) + địa chỉ test của team; so khớp chính xác, không phân biệt hoa thường.
- Mẫu che log: email, chữ ký 0x (≥ 130 hex), bearer token, JWT, chuỗi giống private key (64 hex), các trường văn bản tài liệu theo tên khóa. Không che địa chỉ và tx hash.

## 9. Cấu hình

Hạn sàng lọc 24 giờ; nhà cung cấp `fixture` ở M1; khóa mã hóa từ Docker secret `field_key`; che log bật ở mọi môi trường.

## 10. Bảo mật

Nhà cung cấp lỗi thì đóng; cột Confidential không đọc được trong bản dump DB; CI quét log; không PII trong biên nhận EAS hay sự kiện.

## 11. Tình huống lỗi

Nhà cung cấp lỗi → chặn đăng ký, chặn PAY trừ khi có CLEAR còn hạn; thiếu khóa khi khởi động → api không chạy.

## 12. Kế hoạch test

Địa chỉ trong danh sách → HIT; nhà cung cấp lỗi → bên gọi đóng; payee bị đưa vào danh sách sau khi đăng ký → plan kế tiếp BLOCK (CMP-002); quét log tìm email/chữ ký; dump DB thấy cột Confidential là bản mã.

## 13. Ticket

CMP-001 → CMP-003 → CMP-002. Later CMP-L01…L04.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M14-D1 | M1 dùng nhà cung cấp mẫu có nhãn TEST DATA; adapter cho nhà cung cấp thương mại. |
| M14-D2 | Sàng lọc khi đăng ký và trước mỗi PAY; hạn 24 giờ. |
| M14-D3 | Lỗi thì đóng. |
| M14-D4 | Bốn mức dữ liệu; Confidential mã hóa theo trường. |
| M14-D5 | Che log bật ở mọi môi trường. |
| M14-D6 | Dữ liệu mẫu gồm một phần địa chỉ trừng phạt công khai có nhãn. |
| M14-D7 | Làm mới đồng bộ trước PAY, timeout 5 giây. |
| M14-D8 | Không che địa chỉ và tx hash (cần cho audit). |
| M14-D9 | Khóa mã hóa từ Docker secret; xoay khóa để Later. |
