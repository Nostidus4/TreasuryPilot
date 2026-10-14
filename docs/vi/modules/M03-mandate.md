# M03 · Mandate, payee, ngoại lệ, tạm dừng & giao dịch quản trị

**Nguồn chuẩn:** `docs/modules/mandate/README.md` · **Trạng thái:** Chi tiết (grilling M03 + vòng chain với anh Phúc, 11/10/2026) · **ADR:** ADR-002, ADR-012 (Ethereum Sepolia, đã chốt), ADR-017 (ký giao dịch Safe trong app + sentinel)

## 1. Mục đích và ranh giới

M03 là **phòng điều khiển của Owner**. Nó biến điều Owner muốn (hạn mức, buffer, payee, ngoại lệ, tạm dừng) thành **giao dịch Safe trên Safe T**, gom chữ ký các owner ngay trong app, theo dõi on-chain, và giữ trạng thái backend khớp với contract. M03 cũng phụ trách **sentinel của guardian** (tự pause on-chain) và **chính sách phí** theo treasury (agent được tiêu bao nhiêu gas mà không cần hỏi).

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Bản nháp mandate, kiểm tra, tóm tắt, diff, kích hoạt, lịch sử phiên bản, hết hạn | Logic contract (M04) |
| Gom thay đổi thành một giao dịch (MultiSend) + gom chữ ký Safe trong app + owner thực thi | Đọc chain nói chung (M06, ta chỉ nhận event) |
| Vendor (M05-D2) và payee: đề xuất → sàng lọc → Owner đăng ký → cooling → Active → ngừng | Nhà cung cấp sàng lọc (M14) |
| Yêu cầu ngoại lệ một lần, giao dịch `grantException` / `revokeException` | Văn bản ngoại lệ do AI soạn (M09) |
| Giao dịch cho phép trùng `allowDuplicate` | Phát hiện trùng chính xác (M05) |
| Pause (backend + on-chain qua sentinel hoặc người), resume, revoke | Luật circuit breaker (M12, RCV-006 gọi sentinel của ta) |
| Guardian Safe (1-trên-N) có sentinel key | Khóa executor (M10) |
| Chính sách phí (ngưỡng mỗi plan, ngân sách ngày, chấp nhận phí) | Ước tính phí và gửi giao dịch (M10 dùng chính sách này) |

## 2. Feature, yêu cầu, luật

| Feature | FR | BR |
|---|---|---|
| F-020 Cấu hình mandate | FR-201–203 | BR-014, BR-020–024, BR-030 |
| F-021 Kích hoạt & phiên bản | FR-204–207 | BR-015, BR-016, BR-022 |
| F-022 Danh bạ payee | FR-208–211 | BR-013, BR-017, BR-072, BR-085 |
| F-023/F-024 Hạn mức, buffer (phía cấu hình) | FR-212–215 | BR-020–026, BR-030, BR-036 |
| F-025 Ngoại lệ một lần | FR-216, FR-217 | BR-040–043 |
| F-026 Pause, resume, revoke | FR-218–221 | BR-062–064, **BR-068 (mới)** |
| F-027 Circuit breaker (phần on-chain) | FR-222 | BR-065 |
| F-066 Gas (phần chính sách) | **FR-517, FR-518 (mới)** | BR-080, **BR-084 (mới)** |
| Ký giao dịch quản trị | **FR-225 (mới)** | BR-015, **BR-008 (mới)** |

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Trạng thái quản trị** | Mọi thứ chỉ Safe T đổi được: trường mandate, approver, buffer/target, payee, ngoại lệ, cho phép trùng, trạng thái (pause/resume/revoke). |
| **Phiên bản mandate (off-chain)** | Ảnh chụp bất biến của *toàn bộ* cấu hình quản trị (mandate + approver + buffer/target) kèm `config_hash`. `onchain_version` là `mandate.version` của contract sau khi kích hoạt. |
| **Gói quản trị** | Một giao dịch Safe trên T (MultiSend nếu > 1 lệnh) áp dụng một thay đổi, ví dụ `configureMandate` + `setBuffer(O1)` + `setApprovers`. Chỉ gọi `configureMandate` **khi trường mandate thực sự đổi**, nên đổi buffer không làm tăng version và không làm mất ngoại lệ (M03-D3). |
| **SafeTx** | Struct EIP-712 của Safe `{to, value, data, operation, safeTxGas, baseGas, gasPrice, gasToken, refundReceiver, nonce}`. Owner ký hash; đủ ngưỡng thì một owner gọi `execTransaction`. |
| **Guardian Safe** | Safe ngưỡng **1** gồm (các) Guardian người thật và địa chỉ **sentinel**. `mandate.guardian` = Safe này. Chỉ gọi được `module.pause()`. |
| **Sentinel** | Khóa riêng nằm trong `signer`, chỉ tạo được giao dịch Guardian Safe gọi `pause()` cho module của treasury này. |
| **Chính sách phí** | Cài đặt off-chain theo treasury: mức tốc độ, **ngưỡng phí mỗi plan**, **ngân sách phí mỗi ngày**; hệ thống đề xuất, Owner chấp nhận (FEE-1). |

## 4. Mô hình dữ liệu

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `mandate_versions` | id, treasury_id, version, onchain_version, status (Draft, PendingActivation, Active, Superseded, Expired, Revoked, Discrepancy), config, config_hash, governance_tx_id, valid_from, expires_at, created_by, activated_at | bất biến trừ trạng thái |
| `mandate_status_events` | id, mandate_version_id, from, to, tx_hash, at, by | append-only |
| `governance_txs` *(mới)* | id, treasury_id, safe_address, purpose (MODULE_SETUP, MANDATE, PAYEE_ADD, PAYEE_DEACTIVATE, EXCEPTION_GRANT, EXCEPTION_REVOKE, ALLOW_DUPLICATE, CANCEL_REQUEST, PAUSE, RESUME, REVOKE, GUARDIAN_SETUP), calls (đã giải mã), to, value, data, operation, safe_nonce, safe_tx_hash, threshold, owners_snapshot, status (Collecting, Ready, Submitted, Executed, Failed, Superseded, Cancelled), exec_tx_hash | mỗi Safe nonce chỉ một giao dịch mở |
| `governance_signatures` *(mới)* | id, governance_tx_id, owner_address, signature, signed_by_user, at | |
| `payees` | id, treasury_id, vendor_id, label, address, status (Proposed, Screening, ScreeningFailed, AwaitingOwner, Cooling, Active, Deactivated), active_from, oob_verified_by/at, oob_method (PHONE, IN_PERSON, SIGNED_LETTER, OTHER), oob_note, registration_tx_id | |
| `screenings` | payee/address, provider, result (CLEAR, HIT, ERROR), checked_at, ttl_until | |
| `exceptions` | id, request_id, mandate_onchain_version, amount, payee, expiry, status (Requested, Proposed, Granted, Consumed, Expired, Invalidated, Rejected, Revoked), governance_tx_id, draft_ai_call_id | |
| `guardian_setups` *(mới)* | treasury_id, guardian_safe, human_owners, sentinel_address, threshold = 1 | |
| `treasury_fee_policies` *(mới)* | preset (ECONOMY, NORMAL, FAST), hệ số maxFee, phân vị tip, resend_after, bump, ngưỡng mỗi plan, ngân sách ngày, giá ETH tham chiếu, người chấp nhận | |
| `fee_acceptances` *(mới)* | plan_id, phí ước tính, trần chấp nhận, người chấp nhận, lý do | |
| `backend_pause` | treasury_id, paused, reason, by, at, onchain_status (NotRequested, Requested, Effective) | |

## 5. Máy trạng thái

**Phiên bản mandate:** `Draft → PendingActivation` (gói đã thực thi on-chain) `→ Active` (đọc lại khớp `config_hash`) hoặc `→ Discrepancy` (lệch); `Active → Superseded | Expired | Revoked`. Pause là trạng thái của treasury, không phải của phiên bản. Khi bản mới còn PendingActivation thì bản cũ vẫn Active (BR-015).

**Giao dịch quản trị:** `Collecting` (đã tạo, nonce = nonce Safe trống kế tiếp) → `Ready` (đủ chữ ký) → `Submitted` (owner gửi `execTransaction`) → `Executed` hoặc `Failed`; `Collecting/Ready → Superseded` khi nonce bị giao dịch khác dùng; `Collecting → Cancelled`.

**Payee:** `Proposed → Screening → AwaitingOwner` (CLEAR) hoặc `ScreeningFailed` (HIT/ERROR) → `Cooling` (addPayee đã thực thi) → `Active` (hết cooling) → `Deactivated`. Owner chỉ tạo được giao dịch `addPayee` sau khi ghi nhận **xác minh ngoài kênh** (cách thức + ghi chú) (M03-D7).

**Ngoại lệ:** `Requested` (M08 trả NEEDS_APPROVAL, số liệu từ M07) → `Proposed` (đã tạo gói grant) → `Granted` (thấy event) → `Consumed` (PAY dùng ngoại lệ); nhánh `Rejected`, `Revoked`, `Expired`, `Invalidated` (version mandate đổi).

## 6. API (API_SPEC §3, đã sửa)

**Mandate:** GET/POST `/…/treasuries/{t}/mandates` (OWN tạo; lỗi `MANDATE_INCOMPLETE`, `TARGET_BELOW_BUFFER`, `PER_REQUEST_ABOVE_DAILY`, `EXPIRY_BEFORE_START`, `MANDATE_ALREADY_EXPIRED`, `COOLING_OUT_OF_RANGE`, `NO_APPROVERS`, `AMOUNT_PRECISION`…), `/mandates/{v}/clone`, `/mandates/{v}/governance-tx`, DELETE bản nháp.

**Payee, ngoại lệ, trùng, pause:**

| Method | Endpoint | Quyền | Lỗi |
|---|---|---|---|
| POST | `/…/payees` | OPR, ADM, OWN | `PAYEE_EXISTS`, `ADDRESS_INVALID`, `ADDRESS_IS_TREASURY_WALLET`, `SCREENING_HIT` |
| POST | `/…/payees/{id}/verify-oob` | OWN | `NOT_AWAITING_OWNER` |
| POST | `/…/payees/{id}/registration-tx`, `/deactivation-tx` | OWN | `SCREENING_NOT_CLEAR`, `OOB_NOT_VERIFIED`, `SCREENING_EXPIRED` |
| GET | `/orgs/{o}/requests/{r}/exception` | OWN, OPR, FIN | trả số liệu: amount, cap, đã dùng trong ngày, còn lại sau khi trả, giá trị nếu được cấp, bản nháp AI |
| POST | `/…/exception/grant-tx` (mặc định 72 giờ), `/exception/reject`, `/exception/revoke-tx` | OWN | `NOT_OVER_CAP`, `DAILY_LIMIT_WOULD_EXCEED`, `PAYEE_NOT_ACTIVE`, `NOT_GRANTED` |
| POST | `/…/allow-duplicate-tx` | OWN | `NOT_DUPLICATE` |
| POST | `/…/treasuries/{t}/pause` | OWN, GRD | trả `{backendPaused, onchain, sentinelTxHash?, guardianSafeTx?}` |
| POST | `/…/resume-tx`, `/revoke-tx` (gõ tên treasury để xác nhận) | OWN | `NOT_PAUSED`, `CONFIRMATION_MISMATCH` |

**Giao dịch quản trị (gom chữ ký trong app, M03-D1):** GET danh sách và chi tiết (lệnh đã giải mã, tóm tắt dễ đọc, typed data SafeTx, chữ ký, ngưỡng, owner); POST `/signatures` (lỗi `SIGNATURE_INVALID`, `NOT_SAFE_OWNER`, `ALREADY_SIGNED`, `SUPERSEDED`); GET `/exec-call` (lệnh `execTransaction` cho ví của owner cuối); POST `/submitted` (báo tx hash); POST `/cancel`; GET `/safe-wallet-link` (tùy chọn: mở trong Safe{Wallet}).

**Chính sách phí:** GET `/…/fee-policy` (bản đang dùng + đề xuất kèm cơ sở: phí trung bình 7 ngày, p90, số plan/ngày); POST `/fee-policy/accept` (Owner, không gõ số tay ở M1); POST `/plans/{p}/fee/accept` và `/fee/defer` (OWN, FIN, OPR).

## 7. Luồng

**Đổi mandate (Safe T 2-trên-3):** Owner A tạo nháp → xem tóm tắt + diff → tạo gói (MultiSend: configureMandate, setBuffer O1) → A ký SafeTx (1/2) → thông báo cho Owner B → B xem lệnh đã giải mã → ký (2/2) → Ready → B gửi `execTransaction` từ ví của mình (B trả gas) → báo tx hash → M06 thấy ExecutionSuccess + MandateConfigured → đọc lại mandate, buffer, approver → khớp `config_hash` thì Active, lệch thì Discrepancy.

**Pause khẩn cấp:**
1. Owner/Guardian bấm **Pause** (hoặc RCV-006 kích hoạt). Backend bật cờ pause ngay; trigger và executor dừng (BR-063).
2. Có sentinel thì worker gọi signer `/sentinel/pause`; signer tạo `GuardianSafe.execTransaction(module, 0, pause())` và gửi từ địa chỉ sentinel (ngưỡng 1). Trạng thái on-chain: Requested.
3. Thấy event `Paused` → Effective. Không có sentinel thì giao diện đưa cho Guardian một giao dịch Guardian Safe để ký bằng ví.
4. Resume: chỉ Safe T (gói `resume()`, 2-trên-3). Sau `Resumed`, mọi request đang chờ được lập kế hoạch và kiểm tra lại.

**Thêm payee:** đề xuất (vendor, nhãn, địa chỉ) → sàng lọc (CLEAR còn hạn) → Owner gọi điện/gặp vendor và ghi `verify-oob` → gói đăng ký → owner ký → thực thi → `PayeeAdded(activeFrom)` → Cooling (demo 5 phút, production 24 giờ) → Active.

**Ngoại lệ (UC-06):** M08 trả NEEDS_APPROVAL → ngoại lệ `Requested` kèm số liệu → AI soạn (M09) → Owner chọn hạn (mặc định 72 giờ) → gói `grantException` → ký → thực thi → `Granted` → lập kế hoạch lại → PAY dùng ngoại lệ → `Consumed`.

## 8. Thuật toán

**8.1 Kiểm mandate (BR-014):** bắt buộc actions ⊆ {REFILL, PAY, SUPPLY} (SWAP chỉ khi P2 bật kèm router, cặp, trượt giá, tuổi quote); executor ≠ 0; có guardian; ≥ 1 approver; `validFrom < expiresAt`, thời hạn ≤ 365 ngày; cooling 1 giờ–7 ngày (demo 60 giây–1 giờ); mỗi action `0 ≤ perRequest ≤ daily`, trong đó SUPPLY dùng trường riêng `supplyLimits`; mỗi ví vận hành `0 ≤ buffer ≤ target`; có buffer cho Safe T; `approvalMaxAge` 1–60 ngày; mọi số tiền là chuỗi số nguyên base unit. `minSupply` bắt buộc ở production, demo mặc định 500 đơn vị token; khi bật SUPPLY, giá trị này phải dương và nằm trong cả hai hạn mức SUPPLY; `reserveHorizonDays` mặc định 30. Hạn mức 0 được phép kèm cảnh báo "action bị tắt".

**8.2 Tóm tắt và diff:** mỗi luật một dòng, hiện cả đơn vị hiển thị và base unit, ví dụ: *"Agent được trả vendor tối đa **2.000,00 tUSDC** mỗi hóa đơn và **10.000,00 tUSDC** mỗi ngày UTC (2000000000 / 10000000000 base unit)."* Diff từng trường cũ → mới, đánh dấu ▲ lỏng hơn (tăng hạn mức, giảm buffer, rút ngắn cooling, bắt đầu sớm hơn, kéo dài hạn, thêm action/approver) / ▼ chặt hơn. Thay đổi lỏng hơn có dấu đỏ và phải tick xác nhận.

**8.3 Tạo gói:** trường mandate đổi → `configureMandate`; approver thêm/bớt → `setApprovers(add, remove)`; ví nào đổi → `setBuffer`. Một lệnh → gọi thẳng; nhiều lệnh → `MultiSendCallOnly` v1.4.1 (operation = 1). `safe_nonce` = max(nonce on-chain, nonce mở cao nhất + 1).

**8.4 Đọc lại:** sau khi thực thi đủ xác nhận, đọc `mandate()`, `isApprover`, `bufferOf/targetOf`, dựng cấu hình chuẩn và băm; khớp → Active; lệch → Discrepancy (review item, báo Owner, chặn thực thi bằng `DATA_MISSING` của M08 cho tới khi xử lý).

**8.5 Kiểm trước khi cấp ngoại lệ:** `amount > pay.perRequest` (không thì `NOT_OVER_CAP`) · payee Active · `đã dùng hôm nay + amount ≤ pay.daily` (không thì `DAILY_LIMIT_WOULD_EXCEED`) · hạn ngoại lệ ≤ hạn bản duyệt · ghi version on-chain hiện tại.

**8.6 Đề xuất chính sách phí (FEE-1):** từ 7 ngày gần nhất (hoặc mặc định nếu treasury mới): `avgPlanFee` = gas trung bình mỗi plan × giá gas hiệu dụng trung bình; `p90PlanFee` tương tự ở p90. **Ngưỡng mỗi plan** = `3 × avgPlanFee` (tối thiểu `p90PlanFee`). **Ngân sách ngày** = `max(3 × số plan/ngày × avgPlanFee, 2 × ngưỡng)`. Mức tốc độ: `maxFee = k × baseFee + tip` với k = 1,5 / 2 / 3 và tip = p25 / p50 / p75 của `eth_feeHistory(20)`; gửi lại sau 90 / 60 / 30 giây, tăng 12,5 % (mặc định NORMAL). Mọi con số do hệ thống đề xuất, Owner **chấp nhận** hoặc chọn mức khác.

**8.7 Giữ plan vì phí và chờ thông minh (FEE-1, FEE-2):** trước khi ký attestation (M10): `est = estimateGas × maxFee` cho mọi bước.
- `est ≤ ngưỡng` và `đã tiêu hôm nay + est ≤ ngân sách` → chạy.
- Không thì, nếu vẫn còn trả kịp hạn (ngày an toàn cuối > hôm nay) → **hoãn** (kiểm tra lại mỗi chu kỳ), lý do `FEE_ABOVE_THRESHOLD` / `FEE_BUDGET_EXHAUSTED`, không cần người.
- Nếu hôm nay là ngày an toàn cuối → plan `AwaitingFeeAcceptance`, review item `FEE_APPROVAL` cho Finance/Operator/Owner với lựa chọn "Trả ngay với phí X" / "Hoãn".
- Kiểm tra chiết khấu (FEE-2, cùng M07): chỉ trả sớm lấy chiết khấu nếu `chiết khấu − phí quy ra tài sản > 0`, với `phí quy ra tài sản = est × giá ETH tham chiếu / 1e18` (giá tham chiếu là cài đặt có nhãn ở M1, oracle để Later).

Ví dụ (NORMAL): phí trung bình 0,0004 ETH → ngưỡng 0,0012 ETH; 10 plan/ngày → ngân sách max(0,012; 0,0024) = 0,012 ETH. Phí tăng vọt làm một plan tốn 0,002 ETH: còn 5 ngày mới tới hạn → hoãn; tới hạn hôm nay → Finance thấy "Trả ngay 0,002 ETH (≈ 6 tUSDC với giá tham chiếu 3.000) hoặc hoãn".

**8.8 Thiết lập Guardian Safe (PH-4):** sau khi có module, tạo một Safe với owner `[guardian người, sentinel]`, ngưỡng 1; `guardian` của mandate = Safe này. Địa chỉ sentinel lấy từ `signer GET /sentinel/address`. Sentinel cần ít ETH (có cảnh báo hết gas như executor).

## 9. Cấu hình

| Tham số | Demo | Production |
|---|---|---|
| Chain | Ethereum Sepolia (PH-1) | giống ở M1 |
| Tài sản | `tUSDC` (6 số lẻ, nhãn TEST) cho demo chính; một lượt chạy bằng Circle USDC với hạn mức ÷ 100 (PH-2) | |
| Hạn mức PAY | 2.000 / 10.000 tUSDC (lượt Circle: 20 / 100) | Owner đặt |
| Hạn mức REFILL | 2.500 / 12.000 tUSDC (lượt Circle: 25 / 120) | |
| Buffer / target | T 1.000; O1/O2 10 / 150 tUSDC | |
| Cooling | 300 giây | 86.400 giây (1 giờ–7 ngày) |
| Tuổi tối đa bản duyệt | 14 ngày | 14 ngày |
| Hạn ngoại lệ | 72 giờ | 72 giờ |
| Cảnh báo mandate hết hạn | 7 ngày, 48 giờ, 1 giờ | như demo |
| Owner các Safe | T, O1, O2 cùng 3 owner, ngưỡng 2 (PH-9) | |
| Guardian Safe | 1-trên-2: guardian người + sentinel | |
| Mức phí | NORMAL | |
| Hạn kết quả sàng lọc | 24 giờ | 24 giờ |

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Test |
|---|---|---|
| Người không phải Owner đổi quản trị | Contract chỉ cho Safe T gọi hàm quản trị; API yêu cầu OWN; chữ ký kiểm theo owner on-chain của Safe | ma trận vai trò; test NOT_SAFE_OWNER |
| Owner ký thứ khác với thứ giao diện hiện | Giao diện hiện lệnh giải mã + tóm tắt dựng từ cùng calldata; typed data tính lại ở server và ví | test giải mã ↔ tạo |
| Bản nháp khác on-chain | Đọc lại và so hash (§8.4) | test Discrepancy |
| Lừa đảo BEC khi thêm payee | Sàng lọc + bắt buộc xác minh ngoài kênh + cooling + multisig Owner | test OOB_NOT_VERIFIED |
| Lộ sentinel key | Chỉ pause được (DoS); Owner resume và gỡ sentinel khỏi Guardian Safe | signer từ chối mọi lệnh khác pause |
| Lạm dụng signer để ký quản trị | Endpoint sentinel chỉ tạo `pause()` cho module và Guardian Safe đã cấu hình | test calldata khác bị từ chối |
| Cờ pause backend cũ | Trigger và executor kiểm cờ trước mọi hành động; pause on-chain mới là chặn thật | AT-08 |
| Trùng nonce Safe T | Mỗi nonce một giao dịch mở; phát hiện Superseded | test tranh chấp |
| Phí tăng vọt | Ngưỡng + ngân sách + hoãn + chỉ hỏi người ở ngày an toàn cuối | test FEE |

## 11. Tình huống lỗi

| Lỗi | Hành vi |
|---|---|
| Owner không gom đủ chữ ký | Giao dịch vẫn Collecting; nhắc sau 24 giờ; trạng thái cũ vẫn hiệu lực |
| Thực thi bị revert | Failed; hiện lỗi đã giải mã (ví dụ `InvalidMandate(field)`); nháp vẫn sửa được |
| Có người dùng nonce Safe cho giao dịch khác (ví dụ trong Safe{Wallet}) | Giao dịch của ta → Superseded; tạo lại với nonce kế tiếp |
| Sentinel hết gas hoặc signer lỗi | Pause backend vẫn có hiệu lực; giao diện nhắc Guardian pause bằng ví |
| Dịch vụ sàng lọc lỗi | Chặn đăng ký (BR-085) |
| Đọc lại lệch | Discrepancy, chặn thực thi, tạo review item |
| RPC lỗi khi ước tính phí | Hoãn plan (không đoán phí); thử lại chu kỳ sau |

## 12. Kế hoạch test

| Mức | Nội dung | Ticket |
|---|---|---|
| Unit | Ma trận kiểm mandate; tóm tắt/diff có đánh dấu lỏng/chặt; tạo gói (chỉ gọi configureMandate khi cần); đề xuất phí và luật giữ plan (ví dụ §8.6–8.7) | MDT-002, MDT-009, EXE-012 |
| Integration (Anvil, Safe v1.4.1 thật) | Gom 2-trên-3 chữ ký + execTransaction; gói MultiSend; nonce Superseded; đọc lại Active/Discrepancy; vòng đời payee với tua thời gian; cấp ngoại lệ → dùng; revoke | MDT-003…MDT-009 |
| Integration | Sentinel pause qua Guardian Safe trong < 2 block; sentinel từ chối mọi lệnh khác | MDT-010, EXE-013 |
| E2E | AT-08 pause/resume; AT-11 ngoại lệ | WEB-005/006/013/019, WEB-024/025 |

## 13. Ticket theo thứ tự

MDT-001 schema → **MDT-009 gom chữ ký giao dịch quản trị (mới)** → MDT-002 nháp/tóm tắt/diff → MDT-003 kích hoạt/đọc lại → MDT-004 vendor/payee/sàng lọc (+ xác minh ngoài kênh) → MDT-005 giao dịch payee/đồng bộ → MDT-006 ngoại lệ → MDT-007 pause/resume/revoke → **MDT-010 Guardian Safe + sentinel (mới)** → **EXE-013 endpoint sentinel trong signer (mới)** → MDT-008 hết hạn → **EXE-012 chính sách phí (mới)**. Giao diện: WEB-005, WEB-006, WEB-013, WEB-019, **WEB-024 (mới)**, **WEB-025 (mới)**. Vòng chain: sửa DOM-001/002, nâng SC-019 + REC-005 (biên nhận EAS, ADR-018).

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M03-D1 | Giao dịch quản trị được ký **trong app** (mỗi owner ký hash SafeTx bằng ví), owner cuối thực thi từ ví mình; "mở trong Safe{Wallet}" là tùy chọn (ADR-017). |
| M03-D2 | Guardian = Safe 1-trên-N {guardian người, sentinel}; sentinel key trong `signer`, chỉ pause được (ADR-017). Bấm Pause trong app là gọi sentinel ngay. Giải luôn M04-Q1. |
| M03-D3 | Một thay đổi = một gói (MultiSend); chỉ gọi `configureMandate` khi trường mandate đổi, nên đổi buffer/approver không làm mất ngoại lệ. |
| M03-D4 | Phiên bản off-chain là ảnh chụp toàn bộ cấu hình quản trị; chỉ Active khi đọc lại khớp hash. |
| M03-D5 | Mỗi nonce Safe một giao dịch mở; còn lại xếp hàng; Superseded khi nonce bị dùng bên ngoài. |
| M03-D6 | Ngoại lệ mặc định hết hạn sau 72 giờ (≤ hạn bản duyệt); kiểm còn chỗ trong trần ngày trước khi tạo giao dịch. |
| M03-D7 | Đăng ký payee bắt buộc có bản ghi xác minh ngoài kênh của Owner (cách thức + ghi chú), có audit. |
| M03-D8 | Đổi cooling chỉ áp dụng cho payee thêm sau đó. |
| M03-D9 | Cảnh báo mandate hết hạn ở 7 ngày, 48 giờ, 1 giờ; gia hạn = tạo phiên bản mới. |
| M03-D10 | Resume thì lập kế hoạch và kiểm lại mọi request đang chờ. Revoke phải gõ tên treasury; đã revoke thì cần module mới. |
| M03-D11 | Diff đánh dấu thay đổi lỏng hơn và yêu cầu xác nhận. |
| M03-D12 | Khoảng hợp lệ như §8.1. |
| M03-D13 | Kết quả sàng lọc có hạn 24 giờ. |
| M03-D14 | Pause luôn bật cờ backend trước, on-chain theo sau (sentinel hoặc người). |
| M03-D15 | Chính sách phí theo treasury, hệ thống đề xuất, Owner chấp nhận (M1 không gõ số tay). |
| M03-D16 | Sentinel và executor là hai khóa riêng, ví gas riêng, cảnh báo riêng. |
| **PH-1** | Chain M1 = **Ethereum Sepolia** (ADR-012 đã chốt). |
| **PH-2** | `tUSDC` cho demo chính và test tự động; một lượt bằng chứng với **Circle USDC trên Sepolia**, hạn mức ÷ 100. |
| **PH-3** | PH-3 ghi cách hiểu public testnet của nhóm, không phải phản hồi BTC. Mục 06 yêu cầu tx hash on-chain thật và không chỉ định mạng; hỏi thêm ở DOM-003 là tùy chọn (đối chiếu 14/10/2026). |
| **PH-4** | Guardian Safe 1-trên-N có sentinel (= M03-D2). |
| **PH-5** | "Đã trả" sau **3 xác nhận** (~36 giây trên Sepolia), cấu hình được; đối soát có thể chờ thêm `finalized`. |
| **PH-6** | Đọc event bằng `eth_getLogs` mỗi 6 giây, lưu block hash, quét lại 64 block để bắt reorg (M06). |
| **PH-7** | Gas EIP-1559 theo mức tốc độ (§8.6), gửi lại +12,5 %, một hàng nonce cho executor; con số do hệ thống đề xuất, người dùng chấp nhận. |
| **PH-8** | RPC: Alchemy chính + RPC Sepolia công khai dự phòng. |
| **PH-9** | T, O1, O2 cùng owner và ngưỡng (demo 2-trên-3). |
| **PH-10** | Implementation và factory deploy bằng CREATE2 (salt cố định), verify trên Etherscan, code hash ghi vào manifest. |
| **PH-11** | Biên nhận thanh toán EAS nâng lên **P1 / Tier A** (ADR-018). |
| **FEE-1** | Tự chạy khi phí trong ngưỡng mỗi plan **và** trong ngân sách ngày (hệ thống đề xuất, Owner chấp nhận); không thì giữ lại. |
| **FEE-2** | Chờ thông minh: hoãn khi còn kịp hạn; chỉ hỏi ở ngày an toàn cuối. Bộ lập lịch tính gas là chi phí, không trả sớm nếu chiết khấu nhỏ hơn phí. |
| **FEE-3** | Owner đặt ngưỡng và ngân sách; Finance, Operator hoặc Owner chấp nhận phí cho từng plan bị giữ. |

Snapshot của M08 đổi thành **≤ 30 giây và chậm ≤ 2 block** trên Sepolia (block 12 giây).

## 15. Thay đổi theo v0.3 (ADR-019)

Mandate thêm hạn mức supply (mỗi lần, mỗi ngày); sàn Safe = buffer của Safe T; cài đặt treasury `minSupply` (demo 500 đơn vị token) và tầm dự trữ 30 ngày. Pool Aave và aToken cố định khi tạo module. P2: `authorizeBorrow` / `authorizeRepay` (MDT-011). Cấu hình demo: trả 2.000/10.000; refill 2.500/12.000; supply 5.000/20.000; sàn 1.000; minSupply 500; một ví vận hành O1.
