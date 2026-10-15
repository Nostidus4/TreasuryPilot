# M12 · Phục hồi & ngoại lệ vận hành

**Nguồn chuẩn:** `docs/modules/recovery/README.md` · **Trạng thái:** Chi tiết, đã review với trưởng nhóm (11/10/2026)

## 1. Mục đích và ranh giới

M12 đảm bảo **sự không chắc chắn không bao giờ biến thành lần trả thứ hai**. Nó xử lý các thao tác đang bay sau khi crash/hết giờ dựa trên bằng chứng chain, tiếp tục an toàn các plan làm dở, phân loại lỗi để thử lại, chạy circuit breaker, và biến mọi lần dừng thành đúng một việc cần xử lý cho đúng vai trò.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Quét thao tác đang bay khi khởi động và định kỳ | Phát hiện trạng thái (M06) |
| Xử lý Unknown từ receipt, nonce và cờ của module | Quyết định cho/chặn (M08) |
| Hoàn thành một phần và tiếp tục | Thực thi bước (M10) |
| Chính sách thử lại và phân loại lỗi | Gửi thông báo (M13) |
| Hàng đợi review: tạo, định tuyến, SLA, hành động | Giao diện (WEB-013) |
| Luật và hành động circuit breaker (dùng sentinel, ADR-017) | |
| Chứng minh phục hồi sau crash (RCV-007) | |

## 2. Feature, yêu cầu, luật

F-080 phục hồi crash/Unknown (FR-701, FR-702; BR-060, BR-061) · F-081 hoàn thành một phần (FR-703; BR-054) · F-082 hàng đợi review (FR-704, FR-705; BR-057) · F-083 thử lại (FR-706; BR-061) · F-027 circuit breaker (FR-222; BR-065, BR-068).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Đang bay** | Operation ở NotSubmitted, Submitted, Pending hoặc Unknown. |
| **Treasury bị khóa** | Có ≥ 1 operation Unknown → không lập kế hoạch mới (BR-060). |
| **Bằng chứng xử lý** | (1) receipt theo tx hash; (2) nonce executor đã bị giao dịch nào dùng; (3) cờ module `stepUsed`, `requestPaid`. |
| **Review item** | Mỗi (request, loại) chỉ một mục mở, có mã lý do, các bước đã xong, vai trò được giao, SLA. |
| **Luật circuit** | Điều kiện tất định trên các event gần đây, kích hoạt ALERT hoặc PAUSE. |

## 4. Mô hình dữ liệu

`review_items` (loại: POLICY_BLOCK, NEEDS_AUTHORITY, FEE_APPROVAL, UNCERTAIN_TX, DISCREPANCY, AI_REJECTED, INFRA, UNEXPECTED_OUTFLOW; mã chính, các mã, bước đã xong, vai trò, status Open/Resolved/Dismissed, hạn SLA, cách xử lý: RETRY, REPLAN, CANCEL, EDIT_REQUEST, GRANT_EXCEPTION, ACCEPT_FEE, ACKNOWLEDGE, MARK_MATCHED; ghi chú; version) · `recovery_runs` (operation, bằng chứng, kết quả: CONFIRMED, REVERTED, NEVER_BROADCAST, STILL_PENDING, ESCALATED) · `circuit_rules` (luật, ngưỡng, cửa sổ, hành động ALERT/PAUSE, thời gian nghỉ, bật/tắt) · `circuit_events`.

## 5. Trạng thái

Review: `Open → Resolved | Dismissed`; thao tác trên mục mà trạng thái gốc đã đổi → `STALE_ITEM`. Phục hồi operation: `Unknown → Confirmed | Reverted | Abandoned (chưa từng gửi, có thể lập lại) | Unknown (đã leo thang)`.

## 6. Giao diện

GET `/review-items` (lọc theo vai trò) · GET `/review-items/{id}` (mục, request, plan, bước, kết quả kiểm, bằng chứng, các hành động được phép) · POST `/review-items/{id}/actions` (vai trò được giao; lỗi `NOT_ROUTED_ROLE`, `STALE_ITEM`, `ACTION_NOT_ALLOWED`) · GET/PUT `/treasuries/{t}/circuit-rules` (OWN) · GET `/treasuries/{t}/circuit-events`.

## 7. Luồng

**Quét khi khởi động/định kỳ (mỗi 60 giây):** tải các operation đang bay → khóa treasury của chúng → `resolve(op)` từng cái (§8.1) → mở khóa khi không còn Unknown.

**Hoàn thành một phần (AT-07):** plan dừng ở bước k > 0 → `PartiallyCompleted` → review (POLICY_BLOCK hoặc DISCREPANCY) kèm các bước đã xong → hành động **REPLAN**: M10 tạo plan mới cho các bước còn lại (cùng step id) → kiểm/ký → chỉ chạy các bước đó. **CANCEL**: request Cancelled; tiền nằm yên ở chỗ refill đã đưa tới; báo cáo nói rõ (không tự refill ngược).

## 8. Thuật toán

**8.1 Xử lý Unknown (không AI, BR-060)**
1. Có tx hash: hỏi receipt (RPC chính + phụ). Status 1 → Confirmed (M11 xác minh); status 0 → Reverted.
2. Không có receipt: lấy nonce executor tại `latest`. Nếu nonce của op < nonce hiện tại → đã có giao dịch dùng nonce đó → tìm nó trong các block gần → liên kết → quay lại bước 1. Nếu ≥ và không có trong mempool → NEVER_BROADCAST → Abandoned (có thể lập lại với cùng step id).
3. Cờ module: `stepUsed[stepId]` hoặc `requestPaid[requestId]` là true → coi như Confirmed dù không có receipt của ta (ví dụ giao dịch thay thế ta chưa ghi) → đối soát.
4. Sau 30 phút vẫn chưa rõ → ESCALATED: review UNCERTAIN_TX (Operator + Owner), treasury vẫn khóa.

**8.2 Phân loại thử lại (RCV-005)**

| Lỗi | Loại | Hành động |
|---|---|---|
| RPC 5xx, hết giờ trước khi gửi, mất kết nối | thử lại được | backoff 2 giây × 2ⁿ, tối đa 6 lần |
| `nonce too low` | thử lại sau khi đồng bộ | signer đồng bộ nonce; cùng payload |
| `replacement underpriced` | thử lại được | tăng phí theo chính sách |
| Signer từ chối có kiểu (`PAYLOAD_MISMATCH`, `ATTESTATION_*`) | kết thúc | review AI_REJECTED / POLICY_BLOCK |
| `SIMULATION_REVERTED` | kết thúc plan này | review POLICY_BLOCK |
| `INSUFFICIENT_GAS` | kết thúc tới khi nạp gas | review INFRA, cảnh báo |
| Bất kỳ lỗi nào sau khi đã gửi mà chưa có receipt | **không thử lại** | đi đường tracker/Unknown |

Các id (request, step, operation, idempotency key) giữ nguyên qua mọi lần thử (BR-061).

**8.3 Bảng định tuyến**

| Loại | Vai trò | Hành động được phép |
|---|---|---|
| NEEDS_AUTHORITY (vượt trần) | Owner | GRANT_EXCEPTION (→ M03), CANCEL |
| POLICY_BLOCK do payee/hạn mức/ngân sách | Owner | REPLAN (sau khi sửa policy), CANCEL; RETRY nếu plan dở dang (có bước đã xong) |
| POLICY_BLOCK do số tiền/payee/bản duyệt | Operator → Approver | EDIT_REQUEST (duyệt lại), CANCEL; RETRY nếu plan dở dang |
| FEE_APPROVAL | Finance, Operator, Owner | ACCEPT_FEE, hoãn |
| UNCERTAIN_TX | Operator (báo Owner) | ACKNOWLEDGE chỉ sau khi đã xử lý |
| DISCREPANCY | Finance + Owner | ACKNOWLEDGE, MARK_MATCHED |
| AI_REJECTED | Operator | REPLAN (tất định), CANCEL |
| INFRA | Operator | RETRY |
| UNEXPECTED_OUTFLOW | Owner, Finance | ACKNOWLEDGE |

SLA: NEEDS_AUTHORITY 24 giờ, FEE_APPROVAL tới giờ thực thi an toàn cuối, UNCERTAIN_TX 1 giờ, còn lại 48 giờ; quá hạn thì báo Owner.

**8.4 Luật circuit (mặc định BR-065)**

| Luật | Ngưỡng | Hành động |
|---|---|---|
| Contract từ chối (revert hoặc chạy thử revert) | ≥ 3 lần trong 10 phút | PAUSE |
| Plan AI ngoài mandate (AI_PLAN_REJECTED) | ≥ 1 | PAUSE |
| Coverage giảm (COMPLETE → khác) | bất kỳ | PAUSE |
| Hậu điều kiện DISCREPANCY | bất kỳ | PAUSE |
| Tiền ra bất thường (BR-069) | bất kỳ | ALERT (PAUSE nếu > 20 % số dư ví) |

PAUSE = pause backend + sentinel pause on-chain (ADR-017) + báo Owner. Nghỉ 30 phút trước khi cùng luật cảnh báo lại. Chỉ Owner resume.

## 9. Cấu hình

Quét mỗi 60 giây; leo thang sau 30 phút; thử lại tối đa 6 lần; SLA như §8.3; luật circuit như §8.4 (Owner được siết chặt, không được tắt luật PAUSE ở M1).

## 10. Bảo mật

Trả hai lần sau crash → outbox + xử lý theo bằng chứng chain + cờ chống lặp của contract; RCV-007 · bão thử lại → backoff + giới hạn + circuit breaker · sai người xử lý → kiểm vai trò được giao; quyền cấp phép chỉ Owner · AI quyết định phục hồi → không, chỉ tất định (BR-058) · thao tác cũ → version lạc quan → STALE_ITEM.

## 11. Tình huống lỗi

Worker chết giữa chừng → quét + xử lý · RPC lỗi khi phục hồi → vẫn khóa (không đoán) · sentinel không có → pause backend vẫn hiệu lực, nhắc Guardian pause bằng ví.

## 12. Kế hoạch test

Unit: bảng phân loại; định tuyến; cửa sổ luật circuit. Integration (Anvil): xử lý Unknown qua receipt, qua nonce, qua cờ module; tiếp tục plan dở (AT-07); circuit breaker pause trong một chu kỳ qua sentinel. Chèn lỗi: RCV-007 — 20/20 lượt đúng một PAY.

## 13. Ticket

RCV-001 quét → RCV-002 xử lý Unknown → RCV-005 thử lại → RCV-003 dở dang/tiếp tục → RCV-004 hàng đợi review → RCV-006 circuit breaker → RCV-007 test crash.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M12-D1 | Thứ tự xử lý: receipt → nonce → cờ module; không bao giờ dùng AI; không gửi lại khi còn Unknown. |
| M12-D2 | Unknown quá 30 phút → UNCERTAIN_TX; treasury vẫn khóa. (đã review) |
| M12-D3 | Dở dang: REPLAN các bước còn lại với cùng step id, hoặc CANCEL để tiền nằm yên. |
| M12-D4 | Mỗi (request, loại) một mục mở; version lạc quan. |
| M12-D5 | Định tuyến và SLA như §8.3. (đã review) |
| M12-D6 | Chỉ thử lại trước khi gửi; sau khi gửi đi đường tracker. |
| M12-D7 | Luật circuit như §8.4; PAUSE dùng sentinel. |
| M12-D8 | Tiền ra bất thường: ALERT, PAUSE khi > 20 % số dư ví. (đã review) |
| M12-D9 | Luật PAUSE chỉ được siết, không được tắt ở M1. (đã review) |
| M12-D10 | Nghỉ 30 phút mỗi luật. (đã review) |
| M12-D11 | Thêm loại review FEE_APPROVAL và UNEXPECTED_OUTFLOW (từ M03, M06). |
