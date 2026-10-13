# M08 · Policy engine & attestation

**Nguồn chuẩn:** `docs/modules/policy-engine/README.md` · **Trạng thái:** Chi tiết (grilling M08, 11/10/2026) · **ADR:** ADR-003, ADR-006, ADR-016 (attestation theo request + chạy thử trước khi gửi)

## 1. Mục đích và ranh giới

Policy engine trả lời một câu trước mọi hành động on-chain: **bước này, đúng như vậy, có được chạy ngay bây giờ không?** Kết quả là `ALLOW`, `NEEDS_APPROVAL` hoặc `BLOCK` kèm mã lý do. Với plan được ALLOW, nó ký một **PlanAttestation**; signer chỉ ký giao dịch khi có attestation này (BR-059, FR-507).

Đây là lớp thứ hai trong ba lớp kiểm tra:

| Lớp | Ở đâu | Để làm gì |
|---|---|---|
| 1. Validator (module này) | `py-core`, worker gọi | Giải thích *vì sao* (mã lý do cho UI, review, audit); dừng sớm; kiểm luật off-chain mà contract không thấy |
| 2. Chạy thử trước khi gửi (module này) | worker → `eth_call` từ địa chỉ executor | Bắt mọi chỗ lệch giữa validator và contract (M08-D5) |
| 3. Contract (M04) | chain | Quyết định cuối cùng. Backend "ALLOW" không bao giờ đủ (BR-004, AD-04) |

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Danh mục mã lý do và mô hình quyết định | Tính số tiền và lịch (M07) |
| Kiểm cả plan và từng bước (bản sao luật contract + cổng off-chain) | Đọc chain (M06 dựng snapshot) |
| Mã hóa plan chuẩn, `planHash`, `stepId` tất định | Ký giao dịch (signer, M10) |
| Ký PlanAttestation (EIP-712) và hàm kiểm dùng trong signer | Tính cờ (M05/M09; validator chỉ kiểm đã xác nhận chưa) |
| Chạy thử `eth_call` trước khi gửi, giải mã lỗi revert | Tạo review item (M12 dùng quyết định này) |
| Test so sánh validator ↔ contract | Kiểm attestation on-chain (SC-L04, Later) |

## 2. Feature, yêu cầu, luật

F-055 (FR-410, FR-411, FR-313, FR-505; BR-001–005, BR-010–019, BR-022–024, BR-030, BR-036, BR-040–042, BR-050–051, BR-057–058, BR-060–063, BR-071–072, BR-085, **BR-066, BR-067 mới**) · F-056 (FR-412, FR-413, FR-507; BR-059 đã sửa) · F-163 phần so sánh (NFR-SEC-01).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Plan thực thi** | Các bước theo thứ tự cho **một** request: REFILL (T → ví trả) nếu cần, rồi PAY (ví trả → payee). Tối đa 2 bước ở M1 (3 nếu có swap P2). Lịch cả ngày của M07 chỉ để tham khảo; chỉ plan thực thi mới được kiểm và ký (M08-D1). |
| **Giai đoạn** | Lúc chạy kiểm tra: `PLAN` (trước khi ký attestation), `PRE_STEP` (snapshot mới trước mỗi bước), `SIMULATION` (`eth_call` ngay trước khi ký). |
| **Lỗi cứng** | Mã có quyết định mặc định BLOCK. |
| **Lỗi mềm** | Chỉ `OVER_PER_REQUEST_LIMIT`. Ra NEEDS_APPROVAL khi đó là lỗi *duy nhất* và chưa có ngoại lệ khớp. |
| **Cảnh báo** | Được ghi và thông báo, không đổi quyết định (`DEADLINE_MISSED`, `DISCOUNT_MISSED`, `TARGET_NOT_REACHED`). |
| **Policy version** | `keccak256(abi.encode(mandateVersion, validatorVersion, offchainConfigHash))`, ghi ở mọi lần kiểm và trong mọi attestation. |
| **Cờ** | Tín hiệu rủi ro theo quy tắc (địa chỉ đổi, số tiền bất thường, câu lệnh chèn…) mức LOW/HIGH. HIGH cần người duyệt xác nhận (FR-313). |

## 4. Mô hình dữ liệu

**Python:** `PlanStep {seq, step_id, action, from_wallet, to, asset, amount}`, `ExecutionPlan {request_id, treasury, chain_id, steps, planner_source (AI, DETERMINISTIC, RULE_BASED), evidence_ids}`, `ApprovalView {typed, signature, signer, created_by, last_edited_by, approved_by_user, acknowledged_flag_ids, solo_mode}`, `FlagView`, `ExceptionView`, `ValidationContext {now, head_block, snapshot, request, approval, flags, coverage, unknown_operations, pause_requested, circuit_open, screening_hit, config}`, `Check {name, passed, code, expected, observed}`, `Decision {decision, primary, codes, warnings, checks, stage, step_seq, policy_version, snapshot_block}`.

**DB:** `validations` (plan, step_seq, stage, decision, primary_code, reason_codes, warnings, checks, policy_version, snapshot_block; append-only) · `attestations` (plan, request, plan_hash, step_ids, policy_version, executor, nonce, valid_until, evidence_digest, typed_data, signature, policy_signer; nonce duy nhất) · `signer.attestation_uses` (schema riêng của signer: nonce, plan_hash, step_id; mỗi nonce chỉ gắn một plan_hash; chỉ role DB của signer được ghi, M08-D9).

## 5. Vòng đời attestation

`Issued` (PLAN ra ALLOW → ký) → `InUse` (signer nhận bước 0, rồi các bước sau) → `Done` (ký xong mọi bước) · `Issued/InUse → Expired` khi quá `validUntil` (các bước còn lại cần kiểm PLAN + attestation mới). Lập lại sau khi hoàn thành một phần (RCV-003) tạo plan **mới** chỉ gồm các bước chưa làm (cùng `stepId`), kiểm và ký lại.

## 6. Giao diện

**6.1 Package `py-core` (thuần):** `validate_plan(plan, ctx)` (giai đoạn PLAN: mỗi bước kiểm trên trạng thái dự kiến sau các bước trước) · `validate_step(plan, seq, ctx)` (PRE_STEP) · `decide(checks)` · `plan_hash(plan)` · `step_id(request_id, action, wallet)` · `policy_version(...)` · `attestation_typed_data(...)` · `verify_attestation(typed, sig, trusted_signers, now)` (signer dùng) · `decode_revert(data)` (đổi selector lỗi module thành mã) · `REASON_CODES`.

**6.2 Worker:** `attest(plan, decision)` chỉ khi ALLOW ở giai đoạn PLAN, dùng khóa policy, lưu bản ghi trước khi trả · `simulate(step, ...)`: `eth_call` `module.refill/pay` với `from = executor`, block `latest`, đúng calldata signer sẽ gửi; revert → mã đã giải mã, BLOCK; RPC lỗi → `SIMULATION_UNAVAILABLE`, BLOCK.

**6.3 PlanAttestation (EIP-712, M08-D3)**

```
domain: { name: "TreasuryPilot Policy", version: "1", chainId, verifyingContract: <module clone> }
Step(uint32 seq,bytes32 stepId,uint8 action,address from,address to,address asset,uint256 amount)
PlanAttestation(bytes32 planHash,bytes32 requestId,bytes32[] stepIds,bytes32 policyVersion,
                address executor,uint64 validUntil,uint256 nonce,bytes32 evidenceDigest)
```

`validUntil = now + 15 phút`; nonce ngẫu nhiên 128 bit; `evidenceDigest` = keccak của snapshot id, schedule id, các ai_call id đã sắp, validation id. Domain có `name` khác domain của bản duyệt ("TreasuryPilot"), nên chữ ký duyệt không thể dùng làm attestation và ngược lại.

**Signer kiểm theo thứ tự:** người ký thuộc danh sách khóa policy tin cậy → chưa quá `validUntil` → chainId và module đúng → tính lại `planHash` từ plan worker gửi kèm và so → payload (hàm và tham số) đúng bằng bước `seq` → `(nonce, stepId)` chưa dùng cho payload khác, nonce chưa dùng với plan khác → chạy thử → ký. Ký lại **cùng** payload (tăng phí gas) được phép.

**6.4 Danh mục mã lý do** (B = BLOCK, NA = NEEDS_APPROVAL, W = cảnh báo; thứ tự nhóm = thứ tự ưu tiên chọn mã chính)

| Nhóm | Mã | QĐ | Lỗi contract | Luật |
|---|---|---|---|---|
| 1 Cổng an toàn | `PAUSE_REQUESTED`, `CIRCUIT_OPEN`, `UNKNOWN_OPERATION_PENDING`, `COVERAGE_INCOMPLETE`, `SNAPSHOT_STALE`, `DATA_MISSING`, `CHAIN_MISMATCH`, `ASSET_MISMATCH` | B | — | BR-063, 065, 060, 018, 051, FR-411, BR-014 |
| 2 Vòng đời | `MANDATE_NOT_ACTIVE`, `MANDATE_PAUSED`, `MANDATE_REVOKED` / `MANDATE_EXPIRED` / `EXECUTOR_MISMATCH` | B | `NotActive` / `MandateExpired` / `NotExecutor` | BR-015, 062, 092 |
| 3 Bản duyệt | `NOT_APPROVED`, `APPROVAL_INVALID`, `APPROVAL_EXPIRED`, `NOT_IN_APPROVER_SET`, `APPROVAL_STALE`, `MAKER_CHECKER`, `FLAG_UNACKNOWLEDGED`, `SCREENING_HIT` | B | `ApprovalInvalid`, `ApprovalExpired`, `NotApprover` | BR-001–005, BR-066, BR-085 |
| 4 Ví/đường đi | `NOT_OPERATIONAL_WALLET`, `WRONG_REFILL_TARGET` | B | cùng tên | BR-019, BR-012 |
| 5 Chống lặp | `REQUEST_ALREADY_PAID`, `STEP_ALREADY_EXECUTED`, `REQUEST_CANCELLED`, `ALREADY_REFILLED_FOR_REQUEST`, `DUPLICATE_FINGERPRINT` | B | cùng tên | BR-061, 077, 036, 071 |
| 6 Payee | `PAYEE_UNKNOWN`, `PAYEE_COOLING` | B | cùng tên | BR-013, 017 |
| 7 Hạn mức | `OVER_DAILY_LIMIT`, `OVER_REFILL_PER_REQUEST`, `OVER_REFILL_DAILY`, `EXCEPTION_INVALID` | B | cùng tên | BR-022, 023, 041 |
| 7 Hạn mức | `OVER_PER_REQUEST_LIMIT` | **NA** | `OverPerRequestLimit` | BR-040 |
| 8 Thanh khoản | `BUFFER_BREACH`, `SOURCE_BUFFER_BREACH`, `SOURCE_INSUFFICIENT`, `REFILL_EXCEEDS_NEED`, `REFILL_BOUND` | B | cùng tên | BR-030, 033, 036 |
| 9 Plan | `PLAN_MALFORMED`, `AI_PLAN_REJECTED` | B | — | BR-056 |
| 10 Chạy thử | `SIMULATION_REVERTED` (+ mã giải mã), `SIMULATION_UNAVAILABLE` | B | mọi lỗi | BR-067 |
| 11 Signer | `ATTESTATION_INVALID`, `ATTESTATION_EXPIRED`, `NONCE_REUSED`, `PAYLOAD_MISMATCH` | B | — | BR-059 |
| 12 Sau thực thi | `TRANSFER_FAILED`, `BALANCE_DELTA_MISMATCH` (chỉ từ receipt) | — | cùng tên | M04-D8 |
| Cảnh báo | `DEADLINE_MISSED`, `DISCOUNT_MISSED`, `TARGET_NOT_REACHED` | W | — | M08-D7, BR-032 |

## 7. Luồng

**Plan → ký → các bước:** worker lấy snapshot (M06) → `validate_plan` → BLOCK/NEEDS_APPROVAL thì tạo review item / đề nghị ngoại lệ; ALLOW thì ký attestation (khóa policy) → với mỗi bước: snapshot mới → `validate_step` (PRE_STEP) → `eth_call` (SIMULATION) → không ALLOW thì dừng (plan PartiallyCompleted nếu seq > 0, tạo review item); ALLOW thì gửi signer payload + plan + attestation → signer kiểm (§6.3), chạy thử, ký, gửi → chờ xác nhận (M10) trước bước sau.

**NEEDS_APPROVAL → ngoại lệ → kiểm lại:** PLAN chỉ vướng `OVER_PER_REQUEST_LIMIT` → NEEDS_APPROVAL → request `AwaitingAuthority`, M09 soạn đề nghị với số của engine → Owner gửi `grantException` qua Safe T (M03) → M06 thấy `ExceptionGranted` → lập lại plan; validator thấy ngoại lệ khớp, chưa dùng, còn hạn, đúng version → qua kiểm trần (ghi `usedException`); mọi kiểm tra khác vẫn áp dụng (BR-040).

## 8. Thuật toán

**8.1 Thứ tự kiểm mỗi bước.** *Cổng (mọi giai đoạn, trước mọi kiểm bước):* có yêu cầu pause → circuit đang mở → không có thao tác Unknown → coverage COMPLETE hoặc PARTIAL đã xác nhận → snapshot còn tươi (§9) → đủ trường dữ liệu → đúng chain id và asset. *Request/bản duyệt:* request đang Approved/Scheduled/Paying → có bản duyệt → các trường đã ký bằng request hiện tại (`APPROVAL_STALE`) → chữ ký khôi phục được / ERC-1271 → người ký thuộc approver **hiện tại** (OQ-08) → chưa hết hạn → maker-checker (trừ solo mode) → mọi cờ HIGH có **trước** khi duyệt đều nằm trong danh sách đã xác nhận, và không có cờ HIGH nào **sau** khi duyệt (M08-D4; cờ HIGH mới cần duyệt lại) → sàng lọc. *Hình dạng plan (PLAN):* bước sắp theo `seq`; tối đa một REFILL, đúng một PAY, PAY cuối cùng; số tiền, ví trả, payee của PAY khớp bản duyệt; REFILL từ safeT vào ví trả; mỗi `stepId` đúng §8.4. **REFILL** kiểm như bước 1–9 của refill trong M04 §6.4; **PAY** kiểm như bước 1–9 của pay. Ở giai đoạn PLAN, bước PAY được kiểm trên trạng thái *dự kiến* sau REFILL. *Cảnh báo hạn:* dự kiến xác nhận sau ngày đến hạn → `DEADLINE_MISSED`; sau ngày chiết khấu → `DISCOUNT_MISSED`; quyết định không đổi (M08-D7). Sau cổng, mọi kiểm tra đều chạy (không dừng giữa chừng) để review item liệt kê đủ lỗi một lần; nếu cổng lỗi thì bỏ qua kiểm bước và đánh dấu `skipped`.

**8.2 Tổng hợp:** có lỗi cứng → BLOCK; chỉ có lỗi mềm → NEEDS_APPROVAL; không lỗi → ALLOW. Mã chính = mã lỗi đứng đầu theo thứ tự nhóm §6.4. Ngoại lệ hợp lệ chỉ gỡ `OVER_PER_REQUEST_LIMIT`, không gỡ gì khác; ngoại lệ không khớp thêm `EXCEPTION_INVALID` (BLOCK).

**8.3 planHash:** `keccak256(abi.encode(PLAN_TYPEHASH, requestId, treasury, chainId, keccak256(nối các stepHash)))`, `stepHash_i = hashStruct(Step_i)`; `PLAN_TYPEHASH` là typehash EIP-712 của `Plan(bytes32 requestId,address treasury,uint256 chainId,Step[] steps)Step(…)`. `treasury` là module clone, cùng địa chỉ với `treasury` của approval và `verifyingContract` của attestation (không phải Safe T). Không bao giờ băm JSON. Python và TypeScript dùng chung vector.

**8.4 stepId:** `keccak256(abi.encode("TP_STEP_V1", requestId, uint8(action), wallet))`, `action` theo mã của module (PAY 1, REFILL 2, SWAP_IN 3, SUPPLY 4, WITHDRAW 5), `wallet` = ví nhận với REFILL, ví trả với PAY, Safe T với SUPPLY/WITHDRAW. Plan thanh khoản có `requestId = 0x0` nên stepId dùng id của cycle thanh khoản thay cho requestId, tránh `stepUsed` chặn lần SUPPLY thứ hai. `cycleId = keccak256(abi.encode("TP_LIQ_CYCLE_V1", treasury, uint64(utcDay), uint32(seq)))`: `treasury` là module clone, `utcDay = unix_seconds / 86400`, `seq` = số plan thanh khoản của treasury đã hoàn tất trong ngày đó. Thử lại một cycle chưa xong sẽ ra cùng id nên `stepUsed` vẫn chặn chạy trùng (BR-061). Thử lại và lập lại plan dùng lại cùng id (BR-061); `stepUsed` của contract khiến không thể chạy lần hai.

**8.5 Ví dụ** (mandate: pay 2.000/10.000; refill 2.500/12.000; O1 buffer 10, target 150; payee Active; bản duyệt hợp lệ; snapshot tươi)

| # | Tình huống | Mã | Quyết định |
|---|---|---|---|
| 1 | PAY 1.500 từ O1 (số dư 1.600), đã dùng 3.000 | — | ALLOW |
| 2 | PAY 3.000, không ngoại lệ, đã dùng 2.000 | OVER_PER_REQUEST_LIMIT | **NEEDS_APPROVAL** |
| 3 | PAY 3.000, đã dùng 8.000 | OVER_DAILY_LIMIT, OVER_PER_REQUEST_LIMIT | BLOCK, mã chính OVER_DAILY_LIMIT |
| 4 | PAY 3.000, có ngoại lệ {3.000, đúng payee, đúng version} | — | ALLOW (usedException) |
| 5 | PAY 3.000, ngoại lệ ghi 2.900 | EXCEPTION_INVALID | BLOCK |
| 6 | PAY 3.000, không ngoại lệ, payee đang cooling | PAYEE_COOLING, OVER_PER_REQUEST_LIMIT | BLOCK (ngoại lệ không che lỗi cứng) |
| 7 | Snapshot đọc cách đây 45 giây | SNAPSHOT_STALE | BLOCK, bỏ qua kiểm bước |
| 8 | Có thao tác khác đang Unknown | UNKNOWN_OPERATION_PENDING | BLOCK |
| 9 | Hạn là hôm qua, mọi kiểm tra đạt | cảnh báo DEADLINE_MISSED | ALLOW |
| 10 | Plan REFILL 90 + PAY 100 (O1 = 20 → 110). Owner rút 50 khỏi O1 (→ 60). PRE_STEP cho PAY: 60 − 100 < buffer 10 | BUFFER_BREACH | BLOCK ở bước 1 → PartiallyCompleted, review item; refill không bị hoàn tác (BR-054) |
| 11 | Cờ HIGH "địa chỉ khác lịch sử" chưa xác nhận | FLAG_UNACKNOWLEDGED | BLOCK |
| 12 | Validator ALLOW nhưng `eth_call` revert `NotApprover` (approver vừa bị gỡ 1 block trước) | SIMULATION_REVERTED + NOT_IN_APPROVER_SET | BLOCK |

## 9. Cấu hình

| Tham số | Mặc định |
|---|---|
| Độ tươi snapshot | ≤ 30 giây và chậm ≤ 2 block (Sepolia, block 12 giây), đọc tại `latest` |
| Hạn attestation | 15 phút |
| Nonce attestation | ngẫu nhiên 128 bit |
| Khóa policy tin cậy (cấu hình signer) | khóa hiện tại + khóa trước (cửa sổ xoay khóa) |
| Block khi chạy thử | `latest` |
| Mức cờ cần xác nhận | HIGH |
| `validatorVersion` | semver của package |

`offchainConfigHash` = keccak của JSON chuẩn của bảng này (khóa đã sắp); đây là chỗ duy nhất băm JSON vì không người dùng nào ký nó.

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Bằng chứng |
|---|---|---|
| `worker-ai` bị chiếm, bắt signer ký | `worker-ai` không có khóa policy, không có thông tin signer; signer đòi attestation | test bí mật container, test attestation giả |
| Validator lệch contract | Bộ test so sánh (POL-004) + chạy thử (BR-067) | báo cáo POL-004; ví dụ 12 |
| Plan bị sửa sau khi ký | Signer tính lại planHash, so payload từng bước | test PAYLOAD_MISMATCH |
| Dùng lại attestation cho plan/treasury/chain khác | nonce gắn một planHash; domain gồm chainId và module | test NONCE_REUSED, test domain |
| Dùng chữ ký duyệt làm attestation | tên domain EIP-712 khác nhau | test chéo domain |
| Trộm khóa policy | keystore mã hóa, mật khẩu Docker secret, chỉ nạp trong `worker` core, không log; xoay khóa: thêm địa chỉ mới vào danh sách tin cậy của signer, đổi worker, gỡ địa chỉ cũ sau 15 phút | test quét log, runbook xoay khóa |
| Văn bản LLM quyết định quyền | validator không đọc văn bản hay độ tự tin của AI (BR-057/058) | AD-01, AGT-009 |
| Thiếu dữ liệu bị coi là "không sao" | cổng DATA_MISSING; mọi kiểm tra có đầu vào rõ ràng | property test: bỏ bất kỳ đầu vào nào cũng không ra ALLOW |

Kể cả khi lộ khóa policy, contract vẫn thi hành bản duyệt, hạn mức, payee và buffer (attestation là kiểm soát phía backend ở M1).

## 11. Tình huống lỗi

RPC lỗi khi lấy snapshot/chạy thử → `SNAPSHOT_STALE` / `SIMULATION_UNAVAILABLE` → BLOCK; trigger thử lại chu kỳ sau (quá 3 chu kỳ mới tạo review INFRA) · không nạp được khóa policy → worker không chạy task ký, health đỏ, không thực thi · attestation hết hạn giữa hai bước → kiểm PLAN + ký attestation mới cho các bước còn lại · ALLOW nhưng contract revert → ghi giao dịch revert, giải mã selector, tăng bộ đếm circuit breaker (BR-065), thêm ca vào POL-004 · danh mục thiếu một lỗi contract → CI báo lỗi (POL-001).

## 12. Kế hoạch test

Unit: mỗi mã lý do một test; ma trận tổng hợp (§8.5 dòng 1–9, 11); hành vi bỏ qua khi cổng lỗi (POL-002, 003) · property: bỏ/làm cũ bất kỳ đầu vào không ra ALLOW; ngoại lệ chỉ gỡ mã trần mỗi khoản (POL-003) · vector planHash, stepId, digest PlanAttestation (POL-005, 006) · signer: từ chối attestation giả, hết hạn, nonce dùng lại, payload bị sửa; cho phép ký lại cùng payload (POL-006, EXE-005) · so sánh validator–contract trên Anvil (POL-004) · chạy thử: giải mã mọi lỗi module; RPC lỗi → BLOCK (POL-007) · E2E: ví dụ 10 và 12 (EXE-008).

## 13. Ticket theo thứ tự

POL-001 danh mục → POL-005 planHash/stepId → POL-002 kiểm request & bản duyệt (cờ, maker-checker) → POL-003 hạn mức, thanh khoản, cổng, tổng hợp → POL-006 ký/kiểm attestation → **POL-007 chạy thử trước khi gửi (mới)** → POL-004 bộ so sánh. Nơi dùng: EXE-005 (signer kiểm), EXE-008 (vòng PRE_STEP + SIMULATION), RCV-004 (định tuyến review theo mã chính).

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M08-D1 | Đơn vị kiểm và ký = plan thực thi của một request (≤ 2 bước ở M1). Lịch cả ngày chỉ để tham khảo. |
| M08-D2 | Mỗi plan một attestation, hạn 15 phút; mỗi bước kiểm lại trên snapshot mới (PRE_STEP); lỗi thì dừng chuỗi, giữ bước đã xong, tạo review item. |
| M08-D3 | PlanAttestation ký EIP-712 bằng khóa policy secp256k1 riêng, chỉ worker core giữ (ADR-016). |
| M08-D4 | Cờ HIGH phải được xác nhận trong bản duyệt; chưa xác nhận hoặc phát sinh sau khi duyệt → BLOCK `FLAG_UNACKNOWLEDGED` (BR-066). |
| M08-D5 | Chạy thử `eth_call` từ địa chỉ executor là một giai đoạn kiểm; revert → mã đã giải mã, BLOCK (BR-067). Signer cũng chạy thử trước khi gửi. |
| M08-D6 | Độ tươi snapshot: đọc tại `latest`, ≤ 30 giây và chậm ≤ 2 block (Sepolia). Mức xác nhận "đã trả" vẫn theo M10. |
| M08-D7 | Trả trễ là ALLOW kèm cảnh báo `DEADLINE_MISSED` (và `DISCOUNT_MISSED`); ghi phí trễ và báo Finance. |
| M08-D8 | Sau cổng, mọi kiểm tra đều chạy; quyết định = mức nặng nhất; mã chính theo thứ tự nhóm cố định. |
| M08-D9 | Signer có schema `signer` riêng cho việc dùng attestation; dịch vụ khác không ghi được. |
| M08-D10 | `stepId = keccak("TP_STEP_V1", requestId, action, wallet)`; thử lại và lập lại dùng cùng id. |
| M08-D11 | Policy version = keccak(mandateVersion, validatorVersion, offchainConfigHash). |
| M08-D12 | Ngoại lệ đọc từ trạng thái chain (`exceptions(requestId)`), không bao giờ chỉ từ DB backend. |

Câu hỏi mở: M08-Q1 — kiểm attestation on-chain (SC-L04), Later.

## 15. Thay đổi theo v0.3 (ADR-019)

- **Loại plan:** ngoài plan của request (WITHDRAW? → REFILL? → PAY) có **plan thanh khoản** gồm một bước SUPPLY hoặc WITHDRAW (`requestId = 0x0`), ký attestation như nhau.
- **Kiểm mới:** SUPPLY — sàn Safe, hạn mức supply, `AvailableForSupply ≥ amount`, `amount ≥ min_supply`, sau khi supply PaymentReserve vẫn đủ; WITHDRAW — không vượt aUSDC và thanh khoản pool; PAY — số tiền phải đúng mức sớm hoặc mức chuẩn theo thời điểm thực thi dự kiến.
- **Mã lý do mới:** `SUPPLY_FLOOR_BREACH`, `OVER_SUPPLY_PER_TX`, `OVER_SUPPLY_DAILY`, `RESERVE_BREACH`, `BELOW_MIN_SUPPLY` (cảnh báo), `INSUFFICIENT_POOL_LIQUIDITY`, `INSUFFICIENT_A_TOKEN`, `ALLOWANCE_NOT_CLEARED`, `WRONG_PAYMENT_OPTION`, `BORROW_NOT_AUTHORIZED`, `HEALTH_FACTOR_TOO_LOW` (P2).
- **Dự phòng khi AI lỗi:** chỉ chạy `WITHDRAW → REFILL → PAY`; không bao giờ SUPPLY, BORROW, REPAY.
