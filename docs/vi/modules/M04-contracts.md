# M04 · Smart contract

**Nguồn chuẩn:** `docs/modules/contracts/README.md` · **Trạng thái:** Chi tiết (grilling M04, 11/10/2026) · **ADR:** ADR-002, ADR-003 (đã sửa), ADR-014 · **Code:** `contracts/`

## 1. Mục đích và ranh giới

Contract là **bên quyết định cuối cùng về tiền** (AP-1). Mọi luật đánh dấu **C** trong Business Rules đều được kiểm ở đây, nên backend, signer hay AI có bị chiếm quyền cũng không chuyển được tiền ra ngoài mandate.

| Trong phạm vi (M1) | Ngoài phạm vi (M1) |
|---|---|
| `TreasuryPilotModule` (mỗi treasury một clone) bật trên Safe T, O1, O2 | Thực thi tùy ý, `delegatecall`, đổi owner/module |
| `TreasuryPilotModuleFactory` (clone EIP-1167) | Nâng cấp contract (thay = tắt module cũ + bật module mới) |
| Chuyển stablecoin: `refill` T→Ox, `pay` Ox→payee | Chuyển token gốc (gas): **không có** ở M1 (M04-D10) |
| Mandate, approver, payee (có cooling), hạn mức, buffer, target, bộ đếm, chống lặp, ngoại lệ, cho phép trùng, pause/revoke, hủy request | Dự trữ/giữ chỗ on-chain (F-028), duyệt k-trên-n (F-029), quote có chữ ký (F-065), attestation on-chain (SC-L04): Later |
| `TestUSDC` (nhãn TEST) cho local/CI | Tích hợp DEX thật |
| `TestRouter` + `swapForGas`: **P2, tùy chọn** | Bridge |

**Các bên nhìn từ contract**

| Bên | Danh tính on-chain | Được gọi |
|---|---|---|
| Owner | Chính **Safe T** (owner ký giao dịch Safe, áp ngưỡng Safe) | mọi hàm quản trị |
| Guardian | **Guardian Safe** (1-trên-N: guardian người + sentinel, ADR-017) ghi trong mandate | chỉ `pause()` |
| Executor | Một EOA (khóa nằm trong `signer`) | `refill`, `pay`, (`swapForGas`) |
| Approver | Địa chỉ trong danh sách approver (EOA hoặc ví ERC-1271) | `cancelRequest`; **chữ ký** của họ được kiểm trong `refill`/`pay` |
| Bất kỳ ai | — | các hàm view |

## 2. Feature, yêu cầu, luật

| Feature | Yêu cầu | Luật |
|---|---|---|
| F-012 Bật module & coverage | FR-106 | BR-018 |
| F-021 Kích hoạt mandate | FR-204–207 | BR-014, BR-015, BR-016 |
| F-022 Payee & cooling | FR-208–210 | BR-013, BR-017 |
| F-023 Hạn mức & bộ đếm UTC | FR-212–214 | BR-020–BR-026 |
| F-024 Buffer & target | FR-215 | BR-030, BR-036 |
| F-025 Ngoại lệ một lần | FR-216–217 | BR-040–BR-043 |
| F-026 Pause / resume / revoke | FR-219–220 | BR-062, BR-064 |
| F-037 Fingerprint trùng | FR-315 | BR-071 |
| F-038 Chữ ký duyệt | FR-316–318 | BR-001, BR-003, BR-004 |
| F-039 Hủy request on-chain | FR-324 | BR-077 |
| F-062 REFILL | FR-508 | BR-010, BR-012, BR-023, BR-036 |
| F-063 PAY | FR-509–510 | BR-001, BR-010, BR-019, BR-024 |
| F-064 SWAP (P2) | FR-511–512 | BR-081, BR-082 |
| F-163 Bộ test bảo mật | FR-930, NFR-SEC-01/02/07 | mọi luật C |

## 3. Khái niệm

| Thuật ngữ | Nghĩa on-chain |
|---|---|
| **Treasury** | Một module clone. Địa chỉ của nó là id `treasury` dùng trong chữ ký và event. |
| **Vai trò ví** | `safeT` (nguồn), `operational[]` = {O1, O2}. Chỉ trả tiền từ ví vận hành (M04-D6). |
| **Mandate** | Struct luật có phiên bản; `version` tăng mỗi lần `configureMandate`. |
| **Request** | Một khoản trả hóa đơn đã duyệt, định danh bằng `requestId` (bytes32, tạo off-chain, duy nhất). |
| **Step** | Một hành động đã thực thi (REFILL hoặc PAY), định danh `stepId = keccak256("TP_STEP_V1", requestId, action, wallet)` (M08-D10). |
| **Fingerprint** | `keccak256(normalize(vendorId), normalize(invoiceNo), amount, asset)` tính off-chain (ENG-009), nằm trong bản duyệt đã ký. |
| **Ngày** | `block.timestamp / 86400` (ngày UTC). |

## 4. Mô hình dữ liệu (storage)

```solidity
// cấu hình (đặt lúc initialize, không đổi)
address public safeT; address public asset;
mapping(address => bool) public isOperational; address[] public operationalList;

// mandate
struct Limits { uint128 perRequest; uint128 daily; }
struct Mandate { uint64 version; uint64 validFrom; uint64 expiresAt; uint32 payeeCoolingSeconds;
                 address executor; address guardian; Limits pay; Limits refill; uint32 approvalMaxAge; }
Mandate public mandate;
mapping(address => uint256) public bufferOf; mapping(address => uint256) public targetOf;
mapping(address => bool) public isApprover; uint256 public approverCount;
enum Status { Active, Paused, Revoked } Status public status;

// payee
struct Payee { uint64 activeFrom; bool active; } mapping(address => Payee) public payees;

// bộ đếm (BR-022: toàn treasury, không reset khi đổi version); key = keccak256(action, day)
mapping(bytes32 => uint256) public usedOn;

// chống lặp
mapping(bytes32 => bool) public requestPaid; mapping(bytes32 => bool) public requestCancelled;
mapping(bytes32 => bool) public stepUsed; mapping(bytes32 => bool) public fingerprintPaid;
mapping(bytes32 => mapping(address => bool)) public refilledFor;

// quyền Owner cấp (M04-D3)
struct Exception { uint128 amount; uint64 expiry; uint64 mandateVersion; address payee; bool used; }
mapping(bytes32 => Exception) public exceptions; mapping(bytes32 => bytes32) public duplicateAllowedFor;
```

**Bất biến storage:** `approverCount ≥ 1` khi Active · `bufferOf[w] ≤ targetOf[w]` cho ví vận hành · `expiresAt > validFrom` · bộ đếm chỉ tăng.

## 5. Máy trạng thái

`Uninitialized → Active` (factory.create → initialize) · `Active → Paused` (pause do safeT hoặc guardian) · `Paused → Active` (resume do safeT) · `Active/Paused → Revoked` (revoke do safeT, vĩnh viễn). Lệnh của executor còn yêu cầu `validFrom ≤ now ≤ expiresAt`.

Payee: `chưa có → Cooling (active, now < activeFrom) → Active (now ≥ activeFrom) → Deactivated`. Thêm lại địa chỉ đã ngừng thì cooling tính lại.

## 6. Giao diện

**6.1 Factory:** `create(asset, operational[], MandateInit, approvers[], BufferInit[])` **phải do Safe T gọi** (msg.sender thành safeT, M04-D9); `implementation()`; event `TreasuryModuleCreated(safeT, module, asset)`. `initialize` của implementation bị khóa trong constructor; clone được initialize trong cùng giao dịch `create`. Sau đó Owner gọi `enableModule(module)` trên T, O1, O2.

**6.2 Quản trị (chỉ `msg.sender == safeT`)**

| Hàm | Tác dụng | Lỗi |
|---|---|---|
| `configureMandate(m)` | Thay trường mandate, `version++`; không đụng bộ đếm, payee, approver, buffer; ngoại lệ chưa dùng của version cũ tự mất hiệu lực | `NotOwner`, `InvalidMandate(field)` |
| `setApprovers(add[], remove[])` | Cập nhật danh sách, luôn ≥ 1 | `NoApprovers` |
| `setBuffer(wallet, buffer, target)` | Ví phải là safeT hoặc vận hành; `buffer ≤ target` | `UnknownWallet`, `TargetBelowBuffer` |
| `addPayee(payee)` | `activeFrom = now + payeeCoolingSeconds`; không được là ví treasury | `InvalidPayee` |
| `deactivatePayee(payee)` | `active = false` | `UnknownPayee` |
| `grantException(requestId, amount, payee, expiry)` | Lưu ngoại lệ gắn version hiện tại | `ExpiryInPast`, `AlreadyPaid` |
| `revokeException(requestId)` | Xóa ngoại lệ | |
| `allowDuplicate(fingerprint, requestId)` | Cho đúng request này trả lại fingerprint đã trả một lần | |
| `resume()` / `revoke()` | Paused → Active / → Revoked | `NotPaused`, `AlreadyRevoked` |

**6.3 Khẩn cấp:** `pause()` (safeT hoặc guardian; idempotent; lỗi `NotGuardianOrOwner`, `Revoked`). `cancelRequest(requestId)` *(thêm ở M05)*: safeT **hoặc bất kỳ approver hiện tại** gọi; đặt `requestCancelled = true`, phát `RequestCancelled`; chạy cả khi Paused; lỗi `NotOwnerOrApprover`, `AlreadyPaid`; hủy là vĩnh viễn.

**6.4 Executor** (chỉ executor, trạng thái Active, trong thời hạn mandate)

```solidity
struct PaymentApproval { bytes32 requestId; bytes32 invoiceHash; bytes32 fingerprint; address treasury;
  address payingWallet; address asset; address payee; uint256 amount; uint64 deadline; bytes32 termsHash; uint64 expiry; }
function refill(PaymentApproval ap, bytes approverSig, bytes32 stepId, address toWallet, uint256 amount);
function pay(PaymentApproval ap, bytes approverSig, bytes32 stepId);
```

**`refill` kiểm theo thứ tự:**

| # | Kiểm | Lỗi | Luật |
|---|---|---|---|
| 1 | người gọi là executor, Active, trong thời hạn | `NotExecutor` / `NotActive` / `MandateExpired` | BR-062 |
| 2 | bản duyệt hợp lệ: domain, `treasury == this`, đúng asset, `now ≤ expiry`, người ký là approver **hiện tại** (ECDSA hoặc ERC-1271) | `ApprovalInvalid` / `ApprovalExpired` / `NotApprover` | BR-001/003/004 |
| 3 | chưa trả, chưa hủy | `RequestAlreadyPaid` / `RequestCancelled` | BR-061, BR-077 |
| 4 | step chưa dùng | `StepAlreadyExecuted` | BR-061 |
| 5 | `toWallet == ap.payingWallet` và là ví vận hành | `WrongRefillTarget` | BR-012 |
| 6 | chưa refill cho request này vào ví này | `AlreadyRefilledForRequest` | BR-036 |
| 7 | trong hạn mức refill mỗi lần và mỗi ngày | `OverRefillPerRequest` / `OverRefillDaily` | BR-023 |
| 8 | T sau khi chuyển vẫn ≥ buffer | `SourceBufferBreach` | BR-030 |
| 9 | `số dư(toWallet) + amount ≤ ap.amount + target(toWallet)` | `RefillExceedsNeed` | BR-036 |
| 10–13 | ghi trạng thái → chuyển token qua Safe T → kiểm số dư tăng đúng `amount` → phát `RefillExecuted` | `TransferFailed`, `BalanceDeltaMismatch` | M04-D8 |

**`pay` kiểm theo thứ tự:** (1) người gọi/trạng thái/thời hạn · (2) bản duyệt hợp lệ · (3) ví trả là ví vận hành (`NotOperationalWallet`, BR-019) · (4) payee Active và hết cooling (`PayeeUnknown` / `PayeeCooling`) · (5) chưa trả, chưa hủy, step chưa dùng · (6) fingerprint chưa trả, hoặc `duplicateAllowedFor[fp] == requestId` (`DuplicateFingerprint`) · (7) trong trần mỗi khoản, **hoặc** có ngoại lệ hợp lệ khớp amount, payee, chưa dùng, còn hạn, đúng version (`OverPerRequestLimit` / `ExceptionInvalid`) · (8) trần ngày, tính cả khoản dùng ngoại lệ (`OverDailyLimit`) · (9) ví trả sau khi chuyển ≥ buffer (`BufferBreach`) · (10–13) ghi trạng thái → chuyển token → kiểm số dư payee tăng đúng → phát `PaymentExecuted`.

Mọi hàm ghi đều có chống reentrancy và theo thứ tự kiểm–ghi–gọi.

**6.5 View:** `mandate()`, `status()`, `payeeStatus()`, `usedToday()`, `remainingToday()`, `requestPaid()`, `requestCancelled()`, `stepUsed()`, `fingerprintPaid()`, `exceptions()`, `isApprover()`, `bufferOf()`, `targetOf()`, `operationalList()`, `domainSeparator()`, `hashApproval()`.

**6.6 Event:** `MandateConfigured`, `ApproversChanged`, `BufferSet`, `PayeeAdded`, `PayeeDeactivated`, `ExceptionGranted`, `ExceptionRevoked`, `DuplicateAllowed`, `Paused`, `RequestCancelled`, `Resumed`, `Revoked`, `RefillExecuted`, `PaymentExecuted`. Event chỉ mang id, không mang văn bản tự do.

**6.7 EIP-712:** domain `{name: "TreasuryPilot", version: "1", chainId, verifyingContract: module}`; on-chain chỉ còn **một** struct `PaymentApproval` (11 trường). Vector chuẩn `contracts/test/vectors/payment-approval.json` (SC-017) dùng chung cho Python và TypeScript.

## 7. Luồng chính

**Thiết lập (J1):** Owner ký giao dịch Safe T gọi `factory.create(...)` → clone + initialize → event TreasuryModuleCreated → bật module trên T, O1, O2 → `addPayee` (bắt đầu cooling).

**Refill rồi pay (J4):** signer gọi `refill(ap, sig, step1, O1, 90)` → kiểm 1–9 → Safe T chuyển 90 sang O1 → `RefillExecuted`; signer gọi `pay(ap, sig, step2)` → kiểm 1–9 → O1 chuyển 100 cho payee → `PaymentExecuted`.

**Vượt trần có ngoại lệ (J5):** validator trả NEEDS_APPROVAL (2.500 > 2.000) → Owner ký giao dịch `grantException(requestId, 2500, payee, now + 3 ngày)` → `pay` dùng ngoại lệ ở bước 7, vẫn áp trần ngày ở bước 8.

**Đường lỗi:** gửi lặp → `RequestAlreadyPaid`/`StepAlreadyExecuted`, không đổi trạng thái · pause giữa refill và pay → `pay` lỗi `NotActive`, refill vẫn giữ (BR-054) · approver bị gỡ sau khi ký → `NotApprover` · payee bị ngừng → `PayeeUnknown` · token trả false / có phí chuyển → `TransferFailed` / `BalanceDeltaMismatch` · Owner rút từ O1 giữa hai bước → `BufferBreach`, backend lập lại kế hoạch.

## 8. Ví dụ số

Dùng `TestUSDC` (6 số lẻ), số dưới đây là đơn vị nguyên; contract dùng base unit (×10⁶). Mandate demo: pay 2.000/10.000 · refill 2.500/12.000 · buffer T 1.000, O1/O2 10 · target O1/O2 150 · cooling 300 giây.

| Tình huống | Đầu vào | Kết quả |
|---|---|---|
| UC-02 | O1 = 20, hóa đơn 100 | refill ≤ `100 + 150 − 20 = 230`; engine refill `min(Preferred, Bound)` (M07 §8.1); trả 100; O1 còn ≥ 10 |
| Lạm dụng refill | bản duyệt 10, executor thử refill 2.000 vào O1 (O1 = 0) | `0 + 2000 > 10 + 150` → `RefillExceedsNeed` |
| Trần ngày | đã dùng 8.000, trả 2.500 có ngoại lệ | `8.000 + 2.500 > 10.000` → `OverDailyLimit` |
| Buffer | O1 = 105, buffer 10, trả 100 | `105 − 100 = 5 < 10` → `BufferBreach` |
| Nửa đêm | 23:59:59 UTC dùng ngày N; 00:00:00 dùng ngày N+1 | bộ đếm riêng |

## 9. Cấu hình

| Tham số | Demo | Production | Đặt ở |
|---|---|---|---|
| `payeeCoolingSeconds` | 300 | 86.400 | mandate |
| hạn bản duyệt | deadline + 14 ngày | như demo | off-chain khi tạo bản duyệt |
| `approvalMaxAge` | 14 ngày | 14 ngày | mandate |
| hạn mức pay / refill | 2.000/10.000 · 2.500/12.000 | theo khách | mandate |
| buffer / target | T 1.000; O1/O2 10 / 150 | theo khách | `setBuffer` |
| Safe | v1.4.1 (ghim) | như demo | manifest |
| Solidity | 0.8.24, optimizer 200 runs | như demo | `foundry.toml` |

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Test |
|---|---|---|
| Executor bị chiếm, trả cho kẻ tấn công | Cần chữ ký approver trên đúng payee/số tiền + danh sách payee + cooling | SC-020; bất biến I1, I2 |
| Executor rút cạn T bằng refill | Refill chỉ vào ví trả của bản duyệt; một lần mỗi request mỗi ví; số dư sau ≤ amount + target; trần ngày | SC-009; I10 |
| Chia nhỏ khoản để né trần | Trả đủ số tiền trong một PAY; bộ đếm ngày toàn treasury | I3 |
| Dùng lại chữ ký ở chain/module khác | Domain EIP-712 (chainId, verifyingContract) + trường `treasury` | SC-005 |
| Lặp request/step | `requestPaid`, `stepUsed`, `fingerprintPaid` | I5 |
| Chiếm quyền initialize | Factory chỉ Safe T gọi; implementation khóa init | test factory |
| Guardian lạm quyền | Chỉ pause, không resume, không đổi cấu hình | ma trận vai trò |
| Token lạ | Kiểm return data + kiểm số dư thay đổi chính xác | stub token |
| Reentrancy | `nonReentrant` + kiểm–ghi–gọi | stub reentrancy |
| Module khác vượt mandate | Ngoài phạm vi contract; backend kiểm coverage (TRS-007) | test integration |
| Chữ ký biến dạng | OpenZeppelin `ECDSA`/`SignatureChecker` | unit |
| Owner cấu hình sai | Kiểm trong `configureMandate` | unit |

**Bất biến (SC-014, 10k lượt):** I1 không PAY nếu thiếu chữ ký approver hiện tại trên đúng trường · I2 chỉ PAY cho payee Active hết cooling · I3 Σ PAY mỗi ngày ≤ trần ngày · I4 không hành động nào của agent làm ví xuống dưới buffer · I5 mỗi requestId/stepId/fingerprint chạy tối đa một lần (trừ một lần cho phép trùng) · I6 ngoại lệ chỉ nâng trần mỗi khoản và dùng một lần · I7 Paused/Revoked ⇒ lệnh executor bị từ chối · I8 đổi version không reset bộ đếm · I9 chỉ safeT đổi quản trị; guardian chỉ pause · **I10** refill không bao giờ làm `số dư(toWallet) > approval.amount + target` · **I11** requestId đã hủy không bao giờ refill hay trả.

## 11. Lỗi và phục hồi

| Lỗi | Phát hiện | Phục hồi |
|---|---|---|
| Revert giữa plan | receipt status 0 + selector lỗi | backend đổi selector thành mã lý do (POL-001), tạo review item |
| Giao dịch treo/không rõ | tracker (CHR-003) | đọc lại `requestPaid/stepUsed` trước khi gửi lại (RCV-002) |
| Deploy sai module / cấu hình sai | coverage lỗi hoặc `MandateConfigured` lệch | Owner revoke, tắt module, tạo clone mới |
| Phát hiện bug sau deploy | audit/test | pause → revoke → deploy implementation đã sửa → clone mới → bật lại |
| Mất khóa executor | vận hành | Owner `configureMandate` với executor mới |

## 12. Kế hoạch test

| Mức | Nội dung | Ticket |
|---|---|---|
| Unit | mọi đường lỗi §6.4, ma trận vai trò quản trị, băm EIP-712 so vector | SC-003…SC-012, SC-017, SC-021, SC-022 |
| Kịch bản | AT-01, 02, 05, 06, 07, 08, 10, 11, 12 | SC-013 |
| Fuzz + bất biến | I1–I11, 10k lượt trên main, 1k trên PR | SC-014 |
| Vượt rào | gọi trực tiếp với trường bị sửa, không phải executor, đang pause, payee đang cooling | SC-020 |
| Phân tích tĩnh | Slither, bảng phân loại trong `docs/security/static-analysis.md` | SC-015 |
| So sánh | validator vs contract trên cùng tình huống | POL-004 |
| Gas | `forge test --gas-report` làm bằng chứng | SC-013 |

## 13. Ticket theo thứ tự

SC-001 (Foundry, Safe v1.4.1, OZ, TestUSDC) → SC-002 (storage, struct, EIP-712, lỗi, event) → **SC-021** (factory + clone) → SC-003 (quản trị mandate) → SC-004 (payee + cooling) → SC-005 (kiểm chữ ký ECDSA + ERC-1271) → SC-006 (`pay`) → SC-007 (hạn mức, bộ đếm UTC) → SC-008 (buffer) → SC-009 (`refill`) → SC-010 (pause/resume/revoke) → SC-012 (fingerprint + `allowDuplicate`) → SC-011 (ngoại lệ qua `grantException`) → SC-017 (vector) → SC-013 → SC-014 → SC-020 → SC-015 → SC-016 (script deploy + manifest, CREATE2) → **SC-022** (`cancelRequest`). P1: SC-019 (schema EAS, ADR-018). P2: SC-018 (TestRouter + swapForGas).

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M04-D1 | Safe **v1.4.1**, ghim commit; triển khai chính thức trên Ethereum Sepolia được kiểm ở DOM-001 (ADR-012). |
| M04-D2 | **Factory + clone EIP-1167**; implementation khóa `initialize`; coverage = clone trỏ đúng implementation. |
| M04-D3 | Owner cấp ngoại lệ và cho phép trùng bằng **giao dịch quản trị** (`grantException`, `allowDuplicate`), không dùng chữ ký EIP-712. |
| M04-D4 | Giới hạn refill: sau refill `số dư(to) ≤ approval.amount + target(to)`; mỗi request mỗi ví một lần (BR-036). |
| M04-D5 | Payee **theo treasury**; cooling là một tham số mandate `payeeCoolingSeconds` (≥ 1). |
| M04-D6 | **Chỉ trả từ ví vận hành**; T chỉ refill (BR-019). |
| M04-D7 | Approver có thể là EOA hoặc ví **ERC-1271**. |
| M04-D8 | **Kiểm chính xác số dư thay đổi** sau mỗi lần chuyển. |
| M04-D9 | `create` của factory do **chính Safe T** gọi; tạo và initialize module trong một giao dịch. |
| M04-D10 | M1 **không chuyển token gốc**; gas executor nạp tay, có cảnh báo. |
| M04-D11 | Contract chỉ áp **`expiry`** của bản duyệt; `deadline` của hóa đơn chỉ để thông tin (vẫn trả muộn được). |
| M05-D4 *(bổ sung)* | `cancelRequest(requestId)` do Safe T hoặc approver gọi chặn vĩnh viễn refill và pay của request đó (BR-077). Lộ khóa approver chỉ gây hủy (DoS), không chi được tiền. |

Đã giải: ADR-012 (Ethereum Sepolia, tUSDC + một lượt Circle USDC); M04-Q1 (guardian là Guardian Safe 1-trên-N nên có nhiều guardian mà không sửa contract).

## 15. Thay đổi theo v0.3 (ADR-019), thay thế các mục trên nếu khác

**Bản duyệt hai mức tiền.** `PaymentApproval` có 13 trường: thêm `earlyAmount` (mức trả sớm, 0 = không có) và `earlyPayBy` (hạn trả sớm). Trong `pay`, số tiền chuyển = `earlyAmount` nếu có và chưa quá `earlyPayBy`, ngược lại = `amount` (mức chuẩn). Kiểm 7–9 và bộ đếm dùng số tiền này; `earlyAmount > amount` thì lỗi `WrongPaymentOption`. Event `PaymentExecuted` thêm cờ `early`.

**Aave V3.** Storage thêm `aavePool`, `aToken` (đặt một lần lúc initialize, kiểm bằng `getReserveData(asset)`); mandate thêm hạn mức `supply` (mỗi lần, mỗi ngày). **Sàn của Safe = `bufferOf[safeT]`.**

| Hàm | Kiểm | Lỗi |
|---|---|---|
| `supply(stepId, amount)` | executor/trạng thái/thời hạn · step chưa dùng · trong hạn mức supply · sau khi supply Safe T vẫn ≥ sàn · Safe T `approve` đúng số rồi `pool.supply` · sau đó USDC giảm đúng, aToken tăng, allowance về 0 | `OverSupplyPerTx`, `OverSupplyDaily`, `SupplyFloorBreach`, `AllowanceNotCleared`, `BalanceDeltaMismatch` |
| `withdraw(stepId, amount)` | executor/trạng thái/thời hạn · step chưa dùng · `amount ≤` số aToken · `pool.withdraw` về Safe T · USDC tăng đúng | `InsufficientAToken`, `BalanceDeltaMismatch` |
| `borrow` / `repay` (P2) | chỉ khi Safe T đã cấp quyền một lần (`authorizeBorrow` / `authorizeRepay`); kiểm health factor trước và sau | `BorrowNotAuthorized`, `HealthFactorTooLow` |

Withdraw không cần hạn mức vì tiền chỉ quay về Safe T. Module chỉ gọi đúng `asset`, `aavePool` và Safe; không gọi tùy ý, không delegatecall.

**Bất biến mới:** I12 supply không làm Safe T xuống dưới sàn · I13 chỉ chạm asset/pool/aToken, allowance luôn về 0 · I14 PAY chuyển đúng mức sớm hoặc mức chuẩn · I15 (P2) không vay nếu chưa có quyền của Owner.

**Test:** MockAavePool cho unit; fork Sepolia ở block cố định cho integration; demo trên Sepolia (D2, D3). **Ticket:** SC-023, SC-024, SC-025, SC-026 (P2); sửa SC-002/005/006/014/017/021.
