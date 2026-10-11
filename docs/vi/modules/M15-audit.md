# M15 · Audit & bằng chứng

**Nguồn chuẩn:** `docs/modules/audit/README.md` · **Trạng thái:** Chi tiết — quyết định đã chốt (trưởng nhóm ủy quyền cho tech lead, 11/10/2026) · `audit_heads` (đầu chuỗi mỗi tổ chức) · `evidence_bundles` (org, request hoặc scenario, storage_key, sha256, schema_version, created_at).

## 5. Trạng thái

Chỉ ghi thêm. Trạng thái kiểm tính khi cần: `INTACT | BROKEN_AT(seq)`.

## 6. Giao diện

GET `/audit-log?entity=&actor=&from=&to=` (Auditor, OWN, ADM) · GET `/audit-log/verify` → `{status, checked, brokenAt?}` · GET `/requests/{r}/evidence` (Auditor, OWN, FIN) · POST `/scenarios/{id}/evidence` (lượt demo/benchmark) · CLI `python -m treasurypilot.audit verify --dump file.jsonl` (offline).

## 7. Luồng

Dịch vụ thực hiện hành động → `audit.write(...)` trong cùng transaction (khóa dòng đầu chuỗi của tổ chức) → commit; lỗi → cả hành động bị hủy (BR-097). Bằng chứng: request Paid/Blocked → khi được yêu cầu, bộ xuất ghép mọi thứ → kiểm theo JSON schema → lưu kèm sha256.

## 8. Thuật toán

- **Khóa đầu chuỗi:** `SELECT … FROM audit_heads WHERE org_id = ? FOR UPDATE`, chèn với `prev_hash = head.hash`, cập nhật head. JSON chuẩn: khóa đã sắp, không khoảng trắng, số tiền là chuỗi, thời gian ISO-8601 UTC.
- **Trường của gói bằng chứng v1:** request (id, tên vendor, số tiền, fingerprint, invoiceHash), bản duyệt (typed data, địa chỉ người ký, chỉ hash chữ ký), cờ + xác nhận, plan (nguồn, plan hash, bước), kết quả kiểm (mọi giai đoạn), lời gọi AI (mục đích, model, prompt version, tóm tắt kết quả), attestation (typed data, người ký), operation/giao dịch (hash, block, phí), xác minh, đối soát, EAS UID, nhãn coverage, nhãn dữ liệu mẫu (tài sản/router TEST), thời điểm tạo, phiên bản app. **Không bao giờ bịa hash**: request bị chặn không có phần giao dịch (BR-095).
- **Nhãn coverage:** mọi DTO trạng thái có `coverage {level, missing[], snapshotBlock}`.

## 9. Cấu hình

Giữ audit vĩnh viễn ở M1; gói bằng chứng lưu ở bucket riêng tư; CLI kiểm đi kèm repo.

## 10. Bảo mật

Trigger DB chặn UPDATE/DELETE; chuỗi hash phát hiện sửa trong bản dump; gói bằng chứng chỉ lưu hash chữ ký; gói loại dữ liệu Confidential trừ tên hiển thị của vendor.

## 11. Tình huống lỗi

Ghi audit lỗi → hành động tài chính đóng; hết dung lượng → cảnh báo và chặn hành động tài chính; bộ xuất gặp tx hash không tồn tại trên chain → gói đánh dấu INVALID và không giao.

## 12. Kế hoạch test

Trigger từ chối sửa/xóa; chuỗi hợp lệ theo tổ chức; sửa tay trong DB test → kiểm báo đúng seq đầu tiên bị hỏng; ép audit lỗi làm hủy một lần duyệt; gói khớp schema; mọi tx hash có trên Anvil/Sepolia; gói của request bị chặn không có phần giao dịch.

## 13. Ticket

AUD-001 → AUD-002 → AUD-004 → AUD-003. Later AUD-L01.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M15-D1 | Chuỗi sha256 theo tổ chức, khóa dòng đầu chuỗi. |
| M15-D2 | Ghi audit cùng transaction; lỗi thì hủy hành động. |
| M15-D3 | Danh sách hành động phải audit như §3. |
| M15-D4 | Có CLI kiểm offline. |
| M15-D5 | Trường gói bằng chứng v1 như §8; không bịa hash. |
| M15-D6 | Gói lưu hash chữ ký, không lưu chữ ký gốc. |
| M15-D7 | Mọi DTO trạng thái có object coverage. |
| M15-D8 | Giữ audit vĩnh viễn ở M1. |
| M15-D9 | Gói loại dữ liệu Confidential trừ tên hiển thị vendor. |
