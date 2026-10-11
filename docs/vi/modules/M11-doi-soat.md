# M11 · Xác minh & đối soát

**Nguồn chuẩn:** `docs/modules/reconciliation/README.md` · **Trạng thái:** Chi tiết, đã review với trưởng nhóm (11/10/2026) · **ADR:** ADR-018 (biên nhận EAS)

## 1. Mục đích và ranh giới

Sau khi tiền chuyển, M11 trả lời hai câu: **chain có ra đúng như plan dự kiến không?** (hậu điều kiện, theo từng bước) và **Finance có chốt sổ được khoản này chưa?** (đối soát, theo từng request). M11 cũng phát hành biên nhận EAS và file xuất cho kế toán.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Kiểm hậu điều kiện từng bước đã xác nhận (PASSED / DISCREPANCY / UNKNOWN) | Theo dõi receipt (M06) |
| Bản ghi đối soát có dòng được phân loại (BR-096) | Thực thi hay thử lại (M10, M12) |
| Khớp / chênh lệch / tự khớp (cài đặt tổ chức, mặc định tắt) | Đồng bộ phần mềm kế toán (Later) |
| Xuất CSV + bút toán, ánh xạ tài khoản chung và theo tổ chức | |
| Biên nhận EAS (REC-005, ADR-018) | |
| Kiểm finality trước khi cho Matched | |

## 2. Feature, yêu cầu, luật

F-071 hậu điều kiện (FR-603, FR-604; BR-065) · F-072 đối soát (FR-605, FR-606; BR-053, BR-096) · F-073 xuất file (FR-607, FR-307) · F-074 biên nhận on-chain (FR-608; BR-074) · F-075 ERP (Later; FR-609).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Hiệu ứng dự kiến** | Với mỗi loại bước, đúng những thay đổi trạng thái mà plan ngụ ý (§8.1). |
| **Xác minh** | So dự kiến với quan sát tại block xác nhận (và block trước) → PASSED / DISCREPANCY / UNKNOWN. |
| **Đối soát** | Theo request: các dòng (refill, swap, pay, gas) có phân loại, bằng chứng, trạng thái `NotReady → Pending → Matched | Discrepancy`. |
| **Bộ bằng chứng** | Bản duyệt, attestation, operation, giao dịch (đã finalized), xác minh, hash tài liệu hóa đơn, EAS UID. |
| **Finalized** | Block ở hoặc dưới tag `finalized` của chain (Sepolia ~2 epoch). Matched cần finalized (M11-D2). |

## 4. Mô hình dữ liệu

`verifications` (operation, block, expected, observed, diffs, result) · `reconciliations` (một mỗi request; status, matched_by USER/AUTO, người khớp, thời điểm, ghi chú, finalized_at, eas_uid) · `reconciliation_lines` (class: INTERNAL_TRANSFER, CONVERSION, EXTERNAL_EXPENSE, FEE; operation, tx_hash, from, to, asset, amount, fee_wei, block, ngày) · `account_mappings` (class → mã tài khoản; có dòng mặc định chung, OQ-12) · `exports` (kỳ, định dạng CSV/JOURNAL, storage_key, sha256, tổng) · `chain_attestations` (schema_uid, attestation_uid, tx_hash, status Queued/Sent/Confirmed/Failed, số lần thử).

## 5. Trạng thái

Đối soát: `NotReady` (request chưa Paid) → `Pending` (Paid, đã dựng dòng) → `Matched` (người hoặc tự động; cần finalized + đủ bằng chứng) hoặc `Discrepancy` (người đánh dấu, hoặc xác minh ra DISCREPANCY) → `Matched` sau khi Finance ghi giải trình và Owner xác nhận.

## 6. Giao diện

GET `/reconciliations` (FIN, OWN, ADM; lọc trạng thái, thời gian) · GET `/reconciliations/{id}` (dòng + bằng chứng) · POST `/match` (FIN; lỗi `EVIDENCE_INCOMPLETE{missing}`, `NOT_FINALIZED`) · POST `/discrepancy` (FIN, có ghi chú) · POST `/resolve` (FIN + Owner xác nhận) · POST `/exports` (FIN; kỳ, định dạng) · GET `/exports/{id}` (link ký sẵn) · GET/PUT `/account-mappings` (FIN, ADM). Nội bộ: `verify(operation_id)` (M10 gọi trước bước sau), `build_reconciliation(request_id)`, `publish_receipt(request_id)`.

## 7. Luồng

Bước Confirmed (M06) → `verify(op)` → PASSED: M10 đi tiếp · DISCREPANCY: dừng plan, review (M12), tín hiệu circuit breaker · UNKNOWN (đọc lỗi): thử 3 lần rồi review. PAY Verified → request Paid → dựng đối soát (Pending). Tới finalized → đưa biên nhận EAS vào hàng (M11-D8) → tự khớp nếu bật và đủ bằng chứng → Matched.

## 8. Thuật toán

**8.1 Hiệu ứng dự kiến (block B so với B−1):** REFILL(T→Oi, a): T −a, Oi +a, bộ đếm REFILL ngày +a, `stepUsed`, `refilledFor`. PAY(Oi→payee, a): Oi −a, payee +a, bộ đếm PAY ngày +a, `requestPaid`, `stepUsed`, `fingerprintPaid`; có ngoại lệ thì ngoại lệ chuyển `used`. SWAP (P2): đầu vào −x, đầu ra ≥ minOut, allowance về 0. Quan sát = giá trị tại B trừ tại B−1, đọc bằng Multicall3 ghim block. Các lần chuyển khác trong cùng block chạm cùng ví được trừ ra theo `token_movements` của block B (để tiền vào cùng lúc không gây DISCREPANCY giả). Còn lệch → DISCREPANCY kèm `diffs`.

**8.2 Phân loại (BR-096):** REFILL → INTERNAL_TRANSFER; SWAP → CONVERSION; PAY → EXTERNAL_EXPENSE; phí mỗi giao dịch → FEE (ETH; chỉ quy đổi theo giá tham chiếu khi xuất, có nhãn). Refill mà PAY chưa thành công vẫn thuộc request chưa trả và không tạo chi phí.

**8.3 Tự khớp (OQ-09, mặc định tắt):** cần đủ: PAY PASSED, block PAY đã finalized, bản duyệt Valid lúc thực thi, có attestation, hash tài liệu bằng `invoiceHash` của bản duyệt (nếu có tài liệu), số tiền bằng số trên hóa đơn. Thiếu thì để Pending chờ người khớp.

**8.4 Xuất file:** kỳ theo ngày UTC thực thi. CSV: ngày, request id, vendor, số hóa đơn, phân loại, số tiền, asset, tx hash, phí (ETH), trạng thái, người khớp. Bút toán: theo ánh xạ (mặc định chung: EXTERNAL_EXPENSE → Nợ Chi phí / Có Ví O_i; INTERNAL_TRANSFER → Nợ Ví O_i / Có Ví T; FEE → Nợ Phí ngân hàng / Có Gas executor). Tổng theo phân loại phải bằng tổng on-chain của kỳ; lệch thì hủy xuất. Chặn công thức trong ô (FR-307).

## 9. Cấu hình

Tự khớp tắt (cài đặt tổ chức) · Matched cần finalized · thử đọc khi xác minh 3 lần rồi UNKNOWN · biên nhận EAS phát ngay khi Paid và block PAY đã finalized (không chờ khớp) · định dạng CSV và CSV bút toán.

## 10. Bảo mật

Khớp khi thiếu bằng chứng → server kiểm danh sách bằng chứng, thiếu thì từ chối · reorg sau Paid → Matched chờ finalized, M06 hạ trạng thái khi reorg · file xuất bị sửa → lưu sha256, kiểm tổng · PII lên chain → schema EAS chỉ có hash và địa chỉ · chèn công thức → chặn ô.

## 11. Tình huống lỗi

Đọc trạng thái sau lỗi → UNKNOWN sau 3 lần, plan dừng, review · có lần chuyển lạ trong cùng block → trừ theo dòng tiền đã index; không giải thích được → DISCREPANCY · EAS lỗi → biên nhận Failed, thử lại có backoff, thanh toán không ảnh hưởng · tổng xuất lệch → hủy xuất kèm các dòng lệch.

## 12. Kế hoạch test

Unit: dựng hiệu ứng dự kiến từng loại bước; phân loại; ánh xạ bút toán; kiểm tổng. Integration (Anvil): trả bình thường PASSED; chèn tiền ra lạ → DISCREPANCY; tiền vào cùng lúc không phải chênh lệch; tự khớp bật/tắt; tổng xuất. Testnet: biên nhận EAS mở được trên easscan.

## 13. Ticket

REC-001 xác minh → REC-002 bản ghi đối soát → REC-003 khớp/tự khớp → REC-005 biên nhận EAS → REC-004 xuất file. Later: REC-L01…L03.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M11-D1 | Hậu điều kiện so block B với B−1, trừ các dòng tiền đồng thời. (đã review) |
| M11-D2 | Matched cần block PAY đã finalized. (đã review) |
| M11-D3 | Tự khớp là cài đặt tổ chức, mặc định tắt (OQ-09). |
| M11-D4 | DISCREPANCY dừng plan và báo circuit breaker. |
| M11-D5 | Phân loại theo BR-096; phí là dòng riêng tính bằng ETH. |
| M11-D6 | Ánh xạ tài khoản chung + bảng theo tổ chức (OQ-12). |
| M11-D7 | Hủy xuất khi tổng theo phân loại khác tổng on-chain. |
| M11-D8 | Biên nhận EAS phát ngay khi Paid và block PAY đã finalized, không chờ Finance khớp. (đã review, đã đổi) |
| M11-D9 | Giải quyết Discrepancy cần ghi chú của Finance và xác nhận của Owner. (đã review) |
| M11-D10 | Xác minh UNKNOWN sau 3 lần đọc lỗi. |
