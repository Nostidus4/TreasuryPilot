# M05 · Hóa đơn, yêu cầu chi & duyệt

**Nguồn chuẩn:** `docs/modules/invoices/README.md` · **Trạng thái:** Chi tiết (grilling M05, 11/10/2026) · **ADR:** ADR-003, ADR-014

## 1. Mục đích và ranh giới

M05 biến một hóa đơn thành **yêu cầu chi** được người duyệt ký bằng ví trên đúng các trường mà contract sẽ kiểm. M05 phụ trách nhận hóa đơn (nhập tay, upload, CSV), các phiên bản sửa, fingerprint, cờ rủi ro có quy tắc cố định, typed data của bản duyệt và việc kiểm chữ ký, hủy (off-chain và on-chain), và máy trạng thái của request.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Nhập tay, upload tài liệu, nhập CSV | Trích xuất bằng LLM và phát hiện câu lệnh chèn (M09, ta dùng kết quả) |
| Phiên bản sửa và hủy hiệu lực bản duyệt | Đăng ký payee on-chain, cooling (M03) |
| Fingerprint, chặn trùng chính xác, cờ gần trùng | Trả tiền, lập lịch (M07, M10) |
| Cờ có quy tắc (địa chỉ, số tiền bất thường, ngày, tiền tệ/chain, lần trả đầu) | Nhà cung cấp sàng lọc (M14) |
| Typed data `PaymentApproval`, kiểm chữ ký, maker-checker | Ngoại lệ (M03 + Owner) |
| Máy trạng thái và lịch sử trạng thái | Hộp thư email, API nhận hóa đơn, định kỳ, tiền pháp định (Later) |
| Hủy, kể cả `cancelRequest` on-chain (M05-D4) | |

**Ai quyết định gì:** Operator nhập dữ liệu; AI gợi ý trường (M09); **Approver quyết định có trả hay không** bằng chữ ký; engine và agent quyết định trả thế nào, khi nào; contract thi hành.

## 2. Feature, yêu cầu, luật

| Feature | FR | BR |
|---|---|---|
| F-030 Nhập tay | FR-301, FR-302 | BR-073 |
| F-031 Upload (phần không AI) | FR-303–305 | BR-072, BR-074, BR-075 |
| F-032 Nhập CSV | FR-306, FR-307 | |
| F-035 Xác nhận điều khoản | FR-310, FR-311 | BR-075 |
| F-036 Cờ có quy tắc | FR-312, FR-313, **FR-323 (mới)** | BR-066, BR-072, **BR-076 (mới)** |
| F-037 Fingerprint | FR-314, FR-315 | BR-071 |
| F-038 Duyệt | FR-316–318 | BR-001, **BR-007 (mới)**, BR-003–006 |
| F-039 Máy trạng thái | FR-319, FR-320, **FR-324 (mới)** | BR-060, **BR-077 (mới)** |

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Vendor** | Công ty được trả tiền (tên, mã số thuế, mã chuẩn hóa). Có 1..n địa chỉ payee (M03). Lịch sử số tiền và địa chỉ tính **theo vendor** (M05-D2). |
| **Yêu cầu chi** | Một hóa đơn trả một lần, đủ số tiền, từ một ví trả cho một payee (M05-D9). |
| **Trường bị ràng buộc** | Các trường ký trong `PaymentApproval` (BR-003): requestId, invoiceHash, fingerprint, treasury, payingWallet, asset, payee, amount, deadline, termsHash, expiry. Sửa dữ liệu gốc của các trường này tạo phiên bản mới và hủy hiệu lực bản duyệt. |
| **Trường tự do** | Ghi chú nội bộ, tag, cost center, tệp đính kèm khác hóa đơn. Sửa lúc nào cũng được (trước Paid) mà không hủy bản duyệt. |
| **requestId on-chain** | `keccak256("TP_REQ_V1", orgId, uuid của request)`. Giữ nguyên qua các phiên bản nên `requestPaid` chặn trả lần hai cho mọi phiên bản. |
| **invoiceHash** | `keccak256(vendorRef chuẩn hóa, số hóa đơn chuẩn hóa, amount, asset, ngày phát hành, ngày đến hạn, sha256 tài liệu hoặc 0x0)` (M05-D3). |
| **fingerprint** | M07 §8.5: `keccak256(vendorRef, số hóa đơn, amount, asset)` đã chuẩn hóa. |
| **Cờ** | Tín hiệu rủi ro theo quy tắc (ở đây) hoặc từ AI (M09) gắn với **một phiên bản**, mức LOW hoặc HIGH. HIGH cần Approver xác nhận kèm ghi chú; xác nhận chỉ có hiệu lực cho phiên bản đó. |

## 4. Mô hình dữ liệu

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `vendors` | id, org_id, name, **normalized_ref** (duy nhất trong tổ chức), **tax_id**, contact (mã hóa), notes | M05-D2 |
| `payees` | + `vendor_id` bắt buộc | payee luôn thuộc một vendor |
| `payment_requests` | vendor, payee, invoice_no, **issue_date**, due_at, amount, asset, paying_wallet, terms, terms_hash, người xác nhận điều khoản, fingerprint, **invoice_hash**, **onchain_request_id**, **source** (MANUAL, UPLOAD, CSV), người xác nhận trích xuất, status, current_revision, created_by, last_edited_by, note, tags, cost_center, **cancel_onchain** (NotNeeded, Pending, Confirmed), cancel_tx_hash, version | duy nhất (treasury, fingerprint) khi trạng thái ∉ Rejected/Cancelled/Expired |
| `request_revisions` | request, revision, snapshot (mọi trường ràng buộc), người sửa, lý do | append-only |
| `documents` | storage_key, sha256, mime, size, pages | bucket riêng tư |
| `flags` | request, **revision**, code, severity, evidence, source (DETERMINISTIC, AI), status (Open, Acknowledged, Superseded), người xác nhận, ghi chú | tính lại mỗi phiên bản |
| `approvals` | request, revision, approver, typed_data, signature, **acknowledged_flag_ids**, **solo_mode**, expires_at, status (Valid, Invalidated, Expired, Cancelled) | bất biến trừ status |
| `csv_imports` | file_sha256, tổng dòng, dòng đã tạo, lỗi | |
| `request_status_events` | from, to, actor, lý do, thời điểm | append-only |

## 5. Máy trạng thái (F-039)

`Draft → AwaitingApproval` (submit, OPR) · `AwaitingApproval → Draft` (rút lại / yêu cầu sửa) · `→ Approved` (APR, chữ ký hợp lệ) · `→ Rejected` (APR) · `Approved → Draft` (sửa trường ràng buộc, bản duyệt Invalidated) · `Approved → Scheduled → Planning → Preparing → Paying → Paid` (hệ thống) · `Planning → AwaitingAuthority` (NEEDS_APPROVAL) `→ Scheduled` (ngoại lệ được cấp) · `Planning/Preparing/Paying → NeedsReview` `→ Scheduled` (đã xử lý) · `Approved/Scheduled/AwaitingAuthority/NeedsReview → Expired` (bản duyệt hết hạn) `→ Draft` (renew) · hủy được từ mọi trạng thái trước Paying. `Paid`, `Rejected`, `Cancelled` là trạng thái cuối. Không có trạng thái "Failed" chung.

**Điều kiện chặn**

| Chuyển | Ai | Điều kiện (lỗi) |
|---|---|---|
| submit | OPR, ADM | payee tồn tại, chưa ngừng (`PAYEE_UNKNOWN`); asset là stablecoin của treasury (`ASSET_NOT_PAYMENT_STABLECOIN`); không request đang hoạt động nào trùng fingerprint (`DUPLICATE_FINGERPRINT`); đã xác nhận trường trích xuất nếu nguồn UPLOAD (`EXTRACTION_UNCONFIRMED`); đã xác nhận điều khoản trích xuất hoặc không có (`TERMS_UNCONFIRMED`) |
| approve | APR có ví liên kết | §8.6 |
| sửa trường ràng buộc | OPR, ADM | không có thao tác đang bay (`PAYMENT_IN_FLIGHT`); `If-Match` (412) |
| hủy | OPR (nháp của mình), OWN, ADM | không có PAY đang NotSubmitted/Submitted/Pending/Unknown (`PAYMENT_IN_FLIGHT`, BR-060) |
| renew | OPR | tạo phiên bản mới với hạn mới; cần duyệt lại |

**Hủy (M05-D4, BR-077):** hủy có hiệu lực off-chain ngay (validator trả `REQUEST_CANCELLED`, signer từ chối). Nếu request từng có bản duyệt Valid thì `cancel_onchain = Pending` và giao diện hiện nút **"Hủy on-chain"**: Approver bất kỳ ký giao dịch `module.cancelRequest(requestId)` từ ví của mình, hoặc Owner gửi qua Safe T. Thấy event `RequestCancelled` thì chuyển `Confirmed`. Việc hủy on-chain còn treo hiện thành việc cần làm trên dashboard.

## 6. API (API_SPEC §4, đã sửa)

| Method | Endpoint | Quyền | Lỗi chính |
|---|---|---|---|
| GET/POST/PATCH | `/orgs/{o}/vendors` | thành viên / OPR, ADM | `VENDOR_REF_EXISTS` |
| POST | `/orgs/{o}/requests` | OPR, ADM | `ASSET_NOT_PAYMENT_STABLECOIN`, `PAYEE_UNKNOWN`, `PAYEE_NOT_OF_VENDOR`, `AMOUNT_PRECISION`, `AMOUNT_NOT_POSITIVE`, `DATE_INVALID` |
| POST | `/requests/upload` | OPR | 413, 415, `MULTI_INVOICE_DOCUMENT` |
| POST | `/requests/{r}/extraction/confirm` | OPR | `EXTRACTION_PENDING` |
| POST | `/requests/import-csv` (`dryRun`) | OPR | `CSV_HEADER_INVALID`, `CSV_ENCODING` |
| PATCH | `/requests/{r}` | OPR | `NOT_EDITABLE`, `PAYMENT_IN_FLIGHT`, 412 |
| POST | `/terms/confirm`, `/submit`, `/withdraw`, `/request-changes` | OPR / APR | `TERMS_INVALID`, `DUPLICATE_FINGERPRINT` (+ id request cũ), `TERMS_UNCONFIRMED`, `EXTRACTION_UNCONFIRMED` |
| POST | `/flags/{f}/ack` (ghi chú ≥ 10 ký tự) | APR | `FLAG_SUPERSEDED`, `MAKER_CHECKER` |
| GET | `/approval-typed-data` | APR | `MAKER_CHECKER`, `HIGH_FLAGS_UNACKED`, `NOT_AWAITING_APPROVAL` |
| POST | `/approve` `{signature, revision}` | APR | `SIGNATURE_INVALID`, `NOT_IN_APPROVER_SET`, `WALLET_NOT_LINKED`, `MAKER_CHECKER`, `REVISION_CHANGED`, `HIGH_FLAGS_UNACKED` |
| POST | `/reject`, `/cancel`, `/renew` | APR / OPR, OWN, ADM / OPR | `PAYMENT_IN_FLIGHT`, `NOT_EXPIRED` |
| GET | `/cancel-tx` | APR, OWN | `CANCEL_NOT_NEEDED` |

Typed data `PaymentApproval` đã sửa: **11 trường**, bỏ `overrideDuplicate` (M04-D3).

## 7. Luồng

**Upload → duyệt:** Operator upload PDF → lưu riêng tư (sha256), request Draft (UPLOAD) → job trích xuất (M09) trả trường + nguồn + điều khoản nháp + cờ AI → py-core tính cờ có quy tắc → Operator sửa trường, xác nhận trích xuất và điều khoản → submit → AwaitingApproval → Approver xem tài liệu, so lịch sử vendor, cờ → xác nhận cờ HIGH (ghi chú) → lấy typed data → ký EIP-712 bằng ví → approve → server kiểm (§8.6) → Approved.

**CSV:** cột mẫu `vendor_ref, payee_address, invoice_no, issue_date, due_date, amount, terms_text?, note?, cost_center?`. UTF-8 (cho phép BOM) → header đúng → mỗi dòng: tìm vendor theo `normalized_ref`, địa chỉ payee phải thuộc vendor đó (không tự tạo), số tiền đúng số lẻ, ngày ISO → fingerprint so với DB **và** các dòng trước trong file → cờ → Draft. `dryRun=true` trả báo cáo mà không ghi. File báo lỗi chặn công thức bằng cách thêm `'` trước ô bắt đầu bằng `= + - @`.

## 8. Thuật toán

**8.1 Chuẩn hóa:** `NFKC → trim → casefold`, bỏ khoảng trắng và `- _ / . # :`; giữ số 0 đầu (`0012` ≠ `12`).

**8.2 Trùng chính xác:** khi tạo, sửa, submit: tìm fingerprint trong các request của treasury (trừ Rejected/Cancelled/Expired). Có → `DUPLICATE_FINGERPRINT` kèm id request cũ, chặn submit (BR-071). Lặp hợp lệ thì dùng số hóa đơn khác, hoặc Owner gọi `allowDuplicate` cho đúng request đó.

**8.3 Gần trùng (M05-D5, BR-076):** ứng viên = cùng vendor, **cùng số tiền**, ngày phát hành cách ≤ **45 ngày**, chưa Rejected/Cancelled, khác fingerprint. Tính khoảng cách Damerau-Levenshtein `d` giữa hai số hóa đơn đã chuẩn hóa: `d ≤ 2` → `POSSIBLE_DUPLICATE` **HIGH**; `d > 2` → LOW (thường là hóa đơn định kỳ). Ví dụ: `INV-2026-0412` và `INV-2026-0421` → đảo hai chữ số, d = 1 → HIGH. `RENT-SEP` và `RENT-OCT` (cùng 3.000) → d = 3 → LOW.

**8.4 Số tiền bất thường (OQ-10):** lịch sử = các request Paid của vendor trong 12 tháng, cần ≥ 5 điểm (thiếu → `NO_BASELINE` LOW). `med = trung vị`, `MAD = trung vị |h − med|`, `s = max(1,4826·MAD, 2 % med)`; gắn `AMOUNT_OUTLIER` HIGH nếu `|x − med| > 3·s`. Ví dụ: lịch sử [1.000, 1.020, 980, 1.010, 990] → med 1.000, MAD 10, s = max(14,83; 20) = 20, dải 940–1.060. x = 1.100 → HIGH; x = 1.050 → không gắn. Sàn 2 % giúp khoản định kỳ lệch vài xu không bị gắn cờ.

**8.5 Các cờ khác**

| Mã | Mức | Quy tắc |
|---|---|---|
| `ADDRESS_CHANGED` | HIGH | địa chỉ payee khác địa chỉ dùng trong lần trả Paid gần nhất của vendor (BR-072) |
| `ADDRESS_NOT_REGISTERED` | HIGH | địa chỉ in trên tài liệu không thuộc danh sách payee của vendor; request vẫn chỉ trả cho payee đã đăng ký được chọn |
| `FIRST_PAYMENT_TO_PAYEE` | LOW | chưa từng trả cho payee này |
| `NO_BASELINE` | LOW | < 5 điểm lịch sử |
| `CURRENCY_MISMATCH` / `CHAIN_MISMATCH` | HIGH | tài liệu ghi tiền tệ / mạng khác |
| `DUE_DATE_PAST` / `DUE_DATE_FAR` | LOW | hạn đã qua lúc tạo / hạn > 120 ngày sau ngày phát hành |
| `DUE_BEFORE_ISSUE` | HIGH | hạn trước ngày phát hành |
| `POSSIBLE_DUPLICATE` | HIGH/LOW | §8.3 |
| `AI_UNAVAILABLE` | LOW | M09 không chạy được, chỉ có cờ quy tắc |

Cờ không bao giờ tự sửa trường hay đổi trạng thái.

**8.6 Kiểm khi duyệt:** (1) request đang AwaitingApproval và `revision` gửi lên = phiên bản hiện tại (`REVISION_CHANGED`) · (2) người gọi có vai trò Approver và ví liên kết (`WALLET_NOT_LINKED`) · (3) maker-checker: khác người tạo và người sửa cuối, trừ solo mode (khi đó ghi `solo_mode = true`) · (4) mọi cờ HIGH đang mở của phiên bản đã được xác nhận (`HIGH_FLAGS_UNACKED`) · (5) server tự dựng lại typed data từ phiên bản hiện tại (không tin message từ client); `expiry = min(deadline + 14 ngày, now + approvalMaxAge)` · (6) khôi phục người ký (ECDSA) hoặc gọi `isValidSignature` (ERC-1271) (`SIGNATURE_INVALID`) · (7) người ký thuộc danh sách approver **on-chain** (`NOT_IN_APPROVER_SET`) · (8) lưu bản duyệt kèm danh sách cờ đã xác nhận, chuyển Approved, ghi audit, gửi thông báo. M1 chỉ cần **một** chữ ký Approver hợp lệ (M05-D1, BR-007).

**8.7 Hủy hiệu lực và hết hạn:** sửa trường ràng buộc → phiên bản mới → mọi bản duyệt Valid thành Invalidated, cờ cũ Superseded và tính lại, trạng thái về Draft. Job mỗi 5 phút: bản duyệt quá `expires_at` → Expired; request chưa Paid có bản duyệt cuối hết hạn → Expired. **Rủi ro còn lại:** sau khi sửa, chữ ký cũ vẫn hợp lệ on-chain tới khi hết hạn cho các trường *cũ*. Nó chỉ dùng được tối đa một lần (`requestPaid` theo request), trong hạn mức, và chỉ qua plan có attestation. Muốn chắc chắn thì hủy on-chain rồi tạo request mới.

## 9. Cấu hình

| Tham số | Mặc định |
|---|---|
| Upload | PDF, PNG, JPG ≤ 10 MB; ≤ 20 trang |
| CSV | tối đa 1.000 dòng mỗi file |
| Gần trùng | 45 ngày, khoảng cách ≤ 2 |
| Số tiền bất thường | k = 3, ≥ 5 điểm, sàn 2 % |
| Hạn quá xa | 120 ngày |
| Hạn bản duyệt | deadline + 14 ngày, không vượt `approvalMaxAge` |
| Ghi chú xác nhận cờ | ≥ 10 ký tự |
| Quét hết hạn | mỗi 5 phút |

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Test |
|---|---|---|
| Sửa sau khi duyệt | trường ràng buộc nằm trong chữ ký; sửa → Invalidated; contract kiểm | test sửa sau duyệt; PAY bị sửa trường → revert |
| BEC: vendor cũ, địa chỉ mới | `ADDRESS_CHANGED` / `ADDRESS_NOT_REGISTERED` HIGH + xác nhận; payee chỉ qua Owner + cooling | AT-09 |
| Hóa đơn trùng / gần trùng | chặn fingerprint (DB + contract), cờ gần trùng HIGH | ví dụ §8.3 |
| Client gửi typed data giả | server dựng lại và kiểm chữ ký theo bản server | test message bị sửa |
| Backend bị chiếm trả request đã hủy | `cancelRequest` on-chain (BR-077) | SC-022 |
| Chèn công thức CSV | chặn khi đọc và khi xuất | INV-005 |
| File độc hại | kiểm magic bytes, giới hạn kích thước/trang, không render phía server ngoài trích văn bản trong sandbox `worker-ai` | test upload |
| Văn bản hóa đơn không tin được | chỉ là dữ liệu (BR-070); không bao giờ đổi payee | AD-01 |
| Tự duyệt | maker-checker; solo mode gắn cờ | test MAKER_CHECKER |

## 11. Tình huống lỗi

Trích xuất lỗi/hết giờ → Draft giữ nguyên, hiện tài liệu, nhập tay (FR-304), cờ `AI_UNAVAILABLE` · sửa đồng thời → 412 · danh sách approver đổi giữa lúc lấy typed data và lúc duyệt → bước 7 lỗi `NOT_IN_APPROVER_SET` · RPC lỗi lúc duyệt → 503, không lưu gì · chưa gửi hủy on-chain → việc cần làm trên dashboard; validator/signer vẫn từ chối · hủy khi PAY đang Unknown → từ chối cho tới khi phục hồi xong (M12).

## 12. Kế hoạch test

Unit: ma trận chuyển trạng thái (mọi cặp hợp lệ và không hợp lệ), chuẩn hóa, ví dụ gần trùng và bất thường, luật cờ (INV-002, INV-007, INV-012). Integration: tạo/sửa/submit/duyệt/từ chối/hủy/renew; chữ ký EOA + ERC-1271 mô phỏng; maker-checker; tranh chấp phiên bản (INV-003…011). Contract: `cancelRequest` bởi approver, Safe T, người lạ (revert); pay/refill sau khi hủy revert (SC-022). Hiệu năng: CSV 500 dòng < 10 giây. E2E: upload → xác nhận → duyệt → trả (WEB-023).

## 13. Ticket theo thứ tự

INV-001 schema → INV-002 máy trạng thái → INV-003 nhập tay → INV-004 upload → INV-006 fingerprint → INV-007 cờ → **INV-012 gần trùng (mới)** → INV-008 điều khoản → INV-009 submit & xác nhận cờ → INV-010 duyệt → INV-011 từ chối/hủy/hết hạn (+ hủy on-chain) → INV-005 CSV. Liên quan: MDT-004 (vendor), **SC-022 `cancelRequest` (mới)**, POL-002 (`REQUEST_CANCELLED`), WEB-007/WEB-009.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M05-D1 | M1 mỗi request một chữ ký Approver (contract kiểm một). Duyệt nhiều bậc: Later. |
| M05-D2 | Bảng `vendors` riêng, mỗi vendor 1..n địa chỉ payee; lịch sử theo vendor. |
| M05-D3 | `invoiceHash` = keccak của bản ghi hóa đơn chuẩn hóa kèm sha256 tài liệu. |
| M05-D4 | Hủy off-chain ngay; nếu từng có bản duyệt Valid thì đề xuất và theo dõi `cancelRequest(requestId)` on-chain do Approver hoặc Safe T gọi. |
| M05-D5 | Cờ gần trùng: cùng vendor + cùng số tiền trong 45 ngày; HIGH nếu số hóa đơn khác ≤ 2 ký tự, còn lại LOW. |
| M05-D6 | Phân biệt trường ràng buộc và trường tự do; chỉ sửa trường ràng buộc mới hủy bản duyệt. |
| M05-D7 | `requestId` on-chain giữ nguyên qua các phiên bản. |
| M05-D8 | Operator chọn ví trả; mặc định là ví vận hành mặc định. |
| M05-D9 | Một request = một lần trả đủ; không trả từng phần. |
| M05-D10 | Xác nhận trích xuất một lần cho cả form; điều khoản xác nhận riêng. PDF nhiều hóa đơn bị từ chối. |
| M05-D11 | "Yêu cầu sửa" → Draft; "Từ chối" là trạng thái cuối. |
| M05-D12 | Hạn bản duyệt = min(deadline + 14 ngày, now + approvalMaxAge); hết hạn thì renew và duyệt lại. |
| M05-D13 | Bất thường: trung vị ± 3·max(1,4826·MAD, 2 % trung vị), cần ≥ 5 điểm. |
| M05-D14 | Giao diện M1 ký bằng EOA và smart wallet ký ngay; luồng ký message qua Safe để Later (contract và backend đã nhận ERC-1271). |
