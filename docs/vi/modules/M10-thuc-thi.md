# M10 · Điều phối & thực thi

**Nguồn chuẩn:** `docs/modules/execution/README.md` · **Trạng thái:** Chi tiết, đã review với trưởng nhóm (11/10/2026) · **ADR:** ADR-004, ADR-006, ADR-007, ADR-016, ADR-017

## 1. Mục đích và ranh giới

M10 là **phòng máy**: quyết định *khi nào* hành động, chạy pipeline lập kế hoạch, và đưa từng bước đã có attestation qua outbox, signer và chain, mỗi treasury một request một lúc, không bao giờ trả hai lần.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Chu kỳ lập lịch và trigger thực thi (theo giờ + theo event) | Tính số tiền/lịch (M07) |
| Khóa một luồng mỗi treasury | Quyết định cho/chặn và attestation (M08) |
| Pipeline: snapshot → engine → đề xuất AI → chấm điểm → kiểm → giữ vì phí → ký attestation | Prompt AI (M09) |
| Executor outbox: ghi thao tác trước khi ký, ghi tx hash trước mọi việc khác | Theo dõi receipt (M06) |
| Chạy từng bước với PRE_STEP + SIMULATION + cổng hậu điều kiện | Luật hậu điều kiện và đối soát (M11) |
| Signer (khóa executor, kiểm attestation, hàng nonce, thay thế giao dịch) và endpoint sentinel | Phục hồi Unknown/dở dang (M12) |
| Sổ gas, cảnh báo hết gas, áp chính sách phí (EXE-012) | Contract (M04) |
| Run-now; bước swap (P2) | KMS, swap production, bridge, chia worker (Later) |

## 2. Feature, yêu cầu, luật

F-060 trigger (FR-501–504; BR-050, 060, 063) · F-061 executor & signer (FR-505–507; BR-061, 092) · F-062/063 REFILL/PAY (FR-508–510; BR-012, 019, 036, 053, 054) · F-064 swap (P2; FR-511–512; BR-081, 082, 095) · F-066 gas (FR-514, 515, 517, 518; BR-025, 080, 084) · F-052–F-056 điều phối pipeline (FR-405–413).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Chu kỳ lập lịch** | Chạy bộ lập lịch M07 cho một treasury và lưu lịch trong ngày (tham khảo). |
| **Chu kỳ thực thi** | Lấy request kế tiếp của hôm nay, lập plan, ký attestation, thực thi. |
| **Plan** | Plan thực thi của một request (M08-D1): ≤ 2 bước (REFILL nếu cần, PAY), cộng SWAP ở P2. |
| **Operation** | Dòng outbox cho một bước (`step_id` duy nhất), đơn vị mà signer, tracker và phục hồi làm việc. |
| **Hàng nonce** | Nonce giao dịch của địa chỉ executor; chỉ signer cấp phát. |
| **Lead time** | Bao lâu trước ngày đến hạn (hoặc ngày chiết khấu) request được tính là đến lượt (OQ-06: 24 giờ, demo vài phút). |

## 4. Mô hình dữ liệu

`schedules` (lịch tham khảo, append-only) · `plans` (request, schedule, snapshot, planner_source, plan_hash, chosen_reason, ai_call_ids, status: Draft, Blocked, AwaitingAuthority, AwaitingFeeAcceptance, Attested, Executing, Completed, PartiallyCompleted, Superseded, Expired; attestation, phí ước tính) · `plan_steps` (seq, step_id, action, ví nguồn/đích, asset, amount, status: Pending, Submitted, Confirmed, Verified, Reverted, Skipped) · `operations` (outbox; status: NotSubmitted, Submitted, Pending, Confirmed, Reverted, Unknown, Abandoned; `step_id` duy nhất) · `transactions` (M06) · `gas_ledger` (người trả: EXECUTOR, SENTINEL, RECEIPT; phí; revert; ngày) · `signer.nonces`, `signer.attestation_uses` (schema của signer).

## 5. Máy trạng thái

**Plan:** `Draft → Blocked | AwaitingAuthority | AwaitingFeeAcceptance | Attested`; `Attested → Executing → Completed | PartiallyCompleted`; `Attested/Executing → Expired` (attestation hết hạn trước bước kế, tạo plan mới cho bước còn lại); plan mở bị thay thì `Superseded`.

**Operation:** `NotSubmitted → Submitted` (signer trả hash) `→ Pending → Confirmed | Reverted`; `→ Unknown` (M06) → M12 xử lý thành `Confirmed | Reverted | Abandoned` (không gửi lại khi còn Unknown).

**Request (M10 điều khiển):** `Approved → Scheduled → Planning → Preparing` (đã ký attestation) `→ Paying` (đã gửi PAY) `→ Paid` (PAY Confirmed + Verified); nhánh `AwaitingAuthority`, `NeedsReview` như M05.

## 6. Giao diện

**API công khai:** POST `/treasuries/{t}/run-now` (OPR, OWN; lỗi `TREASURY_PAUSED`, `UNKNOWN_OPERATION_PENDING`, `COVERAGE_INCOMPLETE`, `MANDATE_NOT_ACTIVE`) · GET `/treasuries/{t}/schedule` · GET `/plans/{p}` (plan, bước, kết quả kiểm, attestation, lý do AI, "vì sao") · GET `/operations/{id}` · GET `/treasuries/{t}/events` (SSE).

**Signer (chỉ mạng nội bộ, shared secret + danh sách caller):**

| Endpoint | Đầu vào → kết quả | Lỗi |
|---|---|---|
| POST `/sign-and-send` | plan, attestation, chữ ký, stepSeq, payload {to, data}, phí {maxFee, tip, trần phí} → {txHash, nonce, from} | `ATTESTATION_INVALID`, `ATTESTATION_EXPIRED`, `NONCE_REUSED`, `PAYLOAD_MISMATCH`, `SIMULATION_REVERTED`, `FEE_CAP_EXCEEDED`, `CHAIN_NOT_ALLOWED`, `INSUFFICIENT_GAS` |
| POST `/replace` | {txHash, fees} → cùng nonce, cùng payload, phí cao hơn | `NOT_PENDING`, `FEE_CAP_EXCEEDED` |
| POST `/sentinel/pause` | {treasuryId} → {txHash} | `NOT_CONFIGURED` |
| GET `/sentinel/address`, `/health` | chỉ địa chỉ và số dư gas | |

## 7. Luồng

**Chu kỳ:** mỗi 15 phút và khi có event (duyệt, cấp ngoại lệ, resume, tiền vào, payee Active) → chu kỳ lập lịch. Ngay khi có sự kiện (duyệt, cấp ngoại lệ, resume, tiền vào, payee Active, chấp nhận phí) và mỗi 60 giây làm lưới an toàn → với mỗi treasury đang hoạt động: lấy khóa advisory (không chờ; bận thì bỏ qua) → kiểm cổng (cờ pause backend, mandate Active, coverage, không Unknown, không có plan đang Executing) → lấy request đầu tiên của lịch hôm nay đã tới cửa sổ → chạy pipeline.

**Pipeline (EXE-004):** snapshot PLAN → engine dựng plan tất định (quyết định refill + pay) → hỏi AI (timeout 20 giây, chỉ khi có ý nghĩa) → chấm điểm và chọn (ghi `chosen_reason`) → `validate_plan` → BLOCK/NEEDS_APPROVAL: plan Blocked/AwaitingAuthority, tạo review/đề nghị ngoại lệ → ALLOW: ước tính phí + chính sách phí (chạy / hoãn / AwaitingFeeAcceptance) → ký attestation → plan Attested, request Preparing → đưa vào hàng thực thi.

**Thực thi từng bước (EXE-007/008):**
1. Snapshot PRE_STEP + `validate_step`; SIMULATION `eth_call`. Không ALLOW → dừng.
2. Outbox: trong một transaction DB, ghi ý định Submitted cho bước và thêm operation `NotSubmitted` (nếu chưa có cho `step_id` này).
3. Gọi signer. Thành công → lưu txHash + nonce → `Submitted` → giao tracker. Bị từ chối có kiểu → dừng với mã đó.
4. Chờ (task tự hẹn lại) tới khi M06 báo `Confirmed` (hoặc `Reverted`/`Unknown`).
5. Hậu điều kiện M11 (REC-001) phải **PASSED** rồi mới sang bước sau (M10-D6). DISCREPANCY → dừng, review, tín hiệu circuit breaker.
6. PAY Verified → request `Paid`, plan `Completed`; sau đó biên nhận EAS và đối soát (M11).

Dừng ở bước k > 0 → plan `PartiallyCompleted`, request `NeedsReview`, bước đã xong giữ nguyên (BR-054).

**Thay thế giao dịch:** giao dịch Pending quá `resend_after` (NORMAL 60 giây) → gọi `/replace` với phí × 1,125, không vượt trần phí đã chấp nhận; chạm trần thì chờ, không tăng nữa.

## 8. Thuật toán

**8.1 Đủ điều kiện hôm nay:** request nằm trong lịch hôm nay **và** `now ≥ windowStart`, `windowStart = min(ngày đến hạn, ngày chiết khấu nếu lịch chọn trả sớm) − lead time` (24 giờ; demo 2 phút). Thứ tự theo lịch (BR-052).

**8.2 Khóa và idempotency:** `pg_try_advisory_xact_lock(hash('treasury', id))` quanh mỗi chu kỳ. Task Celery `acks_late` và idempotent theo `(plan_id, step_seq)`; task bị giao lại tìm operation có sẵn theo `step_id` và đi tiếp theo trạng thái, không bao giờ gọi signer cho operation đã `Submitted` (BR-061).

**8.3 Hàng nonce (signer):** `nonce = max(eth_getTransactionCount(executor, "pending"), signer.nonces.next_nonce)`; tăng trong cùng transaction ghi việc dùng attestation. Thay thế dùng lại nonce gốc. Signer tra khóa executor theo `treasury_id` (M10-D7); M1 mọi treasury dùng chung một executor nên ký tuần tự theo địa chỉ đó.

**8.4 Ví dụ (UC-02):** O1 = 20, buffer 10, target 10, hóa đơn 100. Engine: Shortage 90, Preferred 90, Bound 90 → REFILL 90 rồi PAY 100. t0 plan Attested (hạn t0 + 15 phút) → t0+5 giây REFILL: PRE_STEP ALLOW, chạy thử ổn, op#1 → Submitted (nonce 41) → t0+41 giây (3 block) Confirmed, RPC phụ khớp; hậu điều kiện O1 = 110, T −90 → PASSED → PAY: PRE_STEP ALLOW (110 − 100 = 10 ≥ 10), op#2 → Submitted (nonce 42) → Confirmed → PASSED → request Paid; đưa biên nhận EAS vào hàng.

## 9. Cấu hình

Chu kỳ lập lịch 15 phút + event · chu kỳ thực thi 60 giây · lead time 24 giờ (demo 2 phút) *(mặc định, OQ-06)* · AI 20 giây rồi dự phòng (BR-055) · attestation 15 phút · thay thế theo mức phí (NORMAL: sau 60 giây, +12,5 %, không vượt trần) · ngưỡng hết gas: executor 0,05 ETH, sentinel 0,01 ETH, khóa biên nhận 0,01 ETH (Sepolia) · Celery `acks_late`, `reject_on_worker_lost`, visibility timeout 1 giờ.

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Test |
|---|---|---|
| `worker-ai` bị chiếm, bắt signer ký | không có khóa policy, không có bí mật signer | test bí mật container |
| Worker core bị chiếm | signer vẫn đòi attestation đúng payload, chạy thử, contract thi hành mọi luật | test attestation giả |
| Trả hai lần do thử lại/giao lại | `step_id` duy nhất, outbox trước khi ký, `stepUsed`/`requestPaid` của contract | RCV-007 |
| Hai plan đồng thời trong một treasury | khóa advisory + cổng "không có plan Executing" + bộ đếm contract | test đồng thời |
| Rút cạn bằng phí | signer áp trần phí đã chấp nhận (`FEE_CAP_EXCEEDED`) | test trần phí |
| Lạm dụng endpoint signer | mạng nội bộ, shared secret, danh sách caller, chỉ 5 endpoint | test chính sách mạng |
| Lộ khóa | keystore mã hóa, Docker secret, không có khóa trong log/health | quét log |

## 11. Tình huống lỗi

Worker chết sau khi signer trả nhưng trước khi ghi DB → signer đã lưu việc dùng attestation; M12 tìm giao dịch theo (from, nonce) và khớp operation theo `step_id` · signer lỗi → operation vẫn NotSubmitted, thử lại có backoff; plan có thể hết hạn → lập lại · chạy thử trong signer revert → không gửi, lỗi có kiểu, plan Blocked/NeedsReview · giao dịch treo → thay thế tới trần phí rồi chờ; 10 phút không dữ liệu → Unknown → M12 · bước bị revert → không đổi bộ đếm (BR-025), ghi phí, dừng, review, tín hiệu circuit breaker · hết gas → `INSUFFICIENT_GAS`, dừng trước khi ký, cảnh báo · AI hết giờ → dự phòng, nguồn RULE_BASED.

## 12. Kế hoạch test

Unit: điều kiện hôm nay, khóa, vào lại idempotent, cấp nonce, tính phí thay thế · Integration (Anvil): UC-02 trọn vẹn; Owner rút tiền giữa hai bước (ví dụ 10 của M08); signer từ chối; thay thế; hết gas · Chèn lỗi: giết worker giữa signer và ghi DB; giao lại task; khởi động lại signer (RCV-007) · Bảo mật: bí mật của worker-ai; payload lệch; trần phí.

## 13. Ticket theo thứ tự

EXE-001 schema → EXE-002 Celery → EXE-003 trigger/chu kỳ → EXE-012 chính sách phí → EXE-004 pipeline → EXE-005 signer → EXE-006 keystore → EXE-013 sentinel → EXE-007 executor outbox → EXE-008 chạy từng bước → EXE-010 sổ gas → EXE-009 run-now → EXE-011 swap (P2). Later: EXE-L01…L04.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M10-D1 | Hai chu kỳ: lập lịch (15 phút + event) và thực thi (60 giây làm lưới an toàn); **có sự kiện (duyệt, cấp ngoại lệ, resume, tiền vào, payee Active, chấp nhận phí) là đưa ngay một chu kỳ thực thi vào hàng**; chỉ chạy việc của hôm nay. (đã review) |
| M10-D2 | Khóa advisory Postgres theo treasury, không chờ; thêm cổng "không có plan Executing". |
| M10-D3 | AI đề xuất có timeout 20 giây; plan tất định luôn tính trước. (đã review) |
| M10-D4 | Chính sách phí áp sau ALLOW, trước khi ký attestation (EXE-012). |
| M10-D5 | Outbox: ghi operation trước khi ký; lưu tx hash trước mọi bước khác. |
| M10-D6 | Bước sau chỉ chạy khi hậu điều kiện bước trước **PASSED** (M11). (đã review) |
| M10-D7 | Signer lưu và tra khóa **theo `treasury_id`** (bảng khóa, mỗi địa chỉ executor một hàng nonce); M1 cấu hình một executor dùng chung, nên sau này tách executor riêng cho từng treasury chỉ là đổi cấu hình. (đã review) |
| M10-D8 | Thay thế giao dịch dùng lại nonce và payload, tăng 12,5 %, không vượt trần phí. |
| M10-D9 | Lead time 24 giờ trước hạn/ngày chiết khấu, demo 2 phút (OQ-06). (đã review) |
| M10-D10 | API của signer chỉ gồm sign-and-send, replace, sentinel pause, sentinel address, health. |
| M10-D11 | Signer áp trần phí đi kèm plan đã ký. |
| M10-D12 | Hoàn thành một phần → plan PartiallyCompleted, request NeedsReview; tiếp tục bằng plan mới cho bước còn lại (M12). |
| M10-D13 | Ngưỡng hết gas riêng cho từng khóa (executor/sentinel/biên nhận). (đã review) |
| M10-D14 | Run-now dùng cùng cổng và đưa đúng một chu kỳ thực thi vào hàng. |

## 15. Thay đổi theo v0.3 (ADR-019)

Loại bước: WITHDRAW, REFILL, PAY, SUPPLY (BORROW/REPAY là P2). Mỗi chu kỳ: chạy plan của request đến hạn hôm nay (có WITHDRAW đứng đầu nếu cần), rồi nếu không còn plan nào đang chạy thì tối đa một lệnh thanh khoản. Signer cho phép thêm `module.supply`, `module.withdraw`. Demo dùng 1 ví vận hành (T + O1). **Ticket:** EXE-014 mới; sửa EXE-004/005/008.
