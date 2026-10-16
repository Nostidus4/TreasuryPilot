# TreasuryPilot: Kịch bản dựng và quay demo 7 phút 30 giây

**Ngày:** 16/10/2026. **Thời lượng video:** 450 giây. Hướng dẫn team bằng tiếng Việt; nhãn UI và lời thu âm bằng tiếng Anh. Dữ liệu đi kèm: TreasuryPilot_Demo_7m30_Fixture.json (cùng thư mục).

> Đây là runbook sản xuất video, không phải xác nhận sản phẩm đã production-ready.

## 1. Câu chuyện

Doanh nghiệp có invoice 1.000 USDC, được trả 980 nếu thanh toán sớm. O1 thiếu tiền, T không được dùng tiền payroll. Agent chọn phương án trong quyền, rút 210 từ Aave, nạp 980 vào O1, trả 980, xác minh và đối soát. Ngày hôm sau, revenue mới về; agent chỉ supply phần dư sau khi giữ đủ các nghĩa vụ. Kết thúc bằng kiểm tra người nhận ngoài quyền và pause.

Định vị: Quản lý thanh khoản theo nghĩa vụ đã duyệt trên các Safe doanh nghiệp đang có. Không phải chatbot chuyển tiền.

## 3. Dữ liệu và trạng thái

### 3.1 Quy ước hiển thị
- UI tiếng Anh dùng `1,180 USDC`, `18.05 USDC`.
- Code giữ amount bằng integer base units, USDC 6 decimals (980 USDC = "980000000"). Không dùng số thực để cộng/trừ tiền.
- D = 16/10/2026 theo scenario UTC; clock đầu 2026-10-16T10:04:00Z, giờ thực thi 10:05:00Z.
- Header mọi màn: workspace, role đang dùng, `SIMULATION / SYNTHETIC DATA`, scenario time UTC. Không sinh hash `0x...` giả rồi mở explorer thật.

### 3.2 Nhân vật, ví, quyền
| Đối tượng | Dữ liệu |
|---|---|
| Company | Northstar API, Web3 SaaS đã dùng USDC |
| Finance | Linh, tạo/review invoice, không tự duyệt khoản mình tạo |
| Approver | An, duyệt invoice A, không được chỉnh mandate |
| Owner | Minh, quyền quản trị/pause |
| T | Safe quỹ; 1.180 USDC; floor 100; payroll reserve 300 |
| O1 | Safe trả vendor; 100 USDC; buffer = target = 100 |
| O2 | Safe payroll; 0 USDC; buffer/target 0 |
| Pool | Supply 2.000; exposure cap 3.500; không có khoản vay |
| Gas | Native token đủ; cap/counter ETH riêng |
| Mandate | Active v7, còn hạn, một asset/chain/pool |

Limits: PAY 2.000/tx, 10.000/ngày; REFILL 2.000/lần, 10.000/ngày; SUPPLY 2.000/lần/ngày, exposure cap 3.500 USDC. Counter riêng. Người nhận phải Active. BORROW cần quyền owner riêng; không thực thi.

### 3.3 Invoices
| Mã | Đầu video | Diễn biến |
|---|---|---|
| A: INV-CLOUD-042 | Chỉ có file invoice để upload; chưa có request trong list | 1.000; early 980 trước D 17:00 UTC; standard due D+7; vendor Active; paying wallet O1. Tạo đúng một request, Finance Linh, Approver An, revision 1. |
| B: PAYROLL-017 | Approved/Scheduled | 300, due D+2, qua O2; reserve tại T. Không trả trong video. |
| C: INV-DATA-018 | Chưa có | D+1 mới xuất hiện, đã duyệt riêng, 700 due D+3; reserve tại T. |
| X: INV-CLOUD-043 | Chưa có | Cảnh security; 250, recipient lạ, chưa approved; không tạo reserve/plan/payment. |

Dashboard đầu video không được nói A đã Approved hoặc đã reserve 980. Có thể hiện task "Review cloud bill" (document/task, chưa phải quyền chi). Mock extraction dùng recorded fixture (badge `Recorded extraction`). Upload chỉ nhận file mẫu INV-CLOUD-042.pdf; file khác báo unsupported trong demo mode.

### 3.4 Ledger
| State | Sự kiện | T | O1 | O2 | Aave | Tổng |
|---|---|---:|---:|---:|---:|---:|
| S0 | Trước approval A | 1.180 | 100 | 0 | 2.000 | 3.280 |
| S1 | WITHDRAW 210 | 1.390 | 100 | 0 | 1.790 | 3.280 |
| S2 | REFILL 980 | 410 | 1.080 | 0 | 1.790 | 3.280 |
| S3 | PAY 980 verified | 410 | 100 | 0 | 1.790 | 2.300 |
| S4 | D+1 revenue +2.000; C approved | 2.410 | 100 | 0 | 1.790 | 4.300 |
| S5 | SUPPLY 1.310 | 1.100 | 100 | 0 | 3.100 | 4.300 |

PAY UNKNOWN: hiện last verified balance S2 gắn `Refresh pending`; không đổi thành S3 hoặc release hold cho tới khi verify.

### 3.5 Reserve/hold
| Mốc | Breakdown |
|---|---|
| S0 | T: payroll 300 + floor 100 + free 780. O1: buffer 100 + free 0. |
| Sau approval, plan EARLY | A cần 980; T capacity cho A (sau nghĩa vụ khác/floor) 780; thiếu 200. |
| S1 | T: payroll 300 + floor 100 + funding hold A 980 + uncommitted 10 = 1.390. |
| S2 và PAY UNKNOWN | T giữ 300 + 100 + dư 10; O1 execution hold 980 + buffer 100. |
| S3 | Hold A release sau verification; T bảo vệ 400, O1 bảo vệ 100; B chưa paid. |
| S4 | T giữ B 300 + C 700 + floor 100 = 1.100; uncommitted 1.310. |
| S5 | T giữ 1.100; uncommitted 0. |

## 4. UI cần dựng

| Màn | Tab/nút | Nội dung |
|---|---|---|
| Overview | T row → `View breakdown`; O1 row | Balances, protected/free, B và thời hạn; snapshot UTC |
| Controls | `Mandate`, `Agent controls` | Rule summary v7 Active; owner `Pause agent` |
| Invoices | `Upload invoice`, document preview, `Submit for approval` | List B, sau đó A; X chỉ ở security scene |
| Invoice A detail | `Review`, `Plan`, `Execution`, `Evidence` | Cùng invoice number/request ID |
| Liquidity | `View allocation`, `View supply plan` | Revenue/C/B, reserve, surplus; supply cycle status |
| Audit | `Security test evidence`, `View report` | App block khác contract rejection; report có nhãn simulated |

Có thể gắn các tab vào màn tương đương trong app hiện có.

Thành phần:
- Invoice Review: source bên trái, field trích bên phải; badge `Recorded extraction`; checkbox `I verified the invoice fields`; payee registry match.
- Approval dialog: standard/early amount, recipient, O1, token, deadlines/revision; nút `Confirm demo approval`, ghi `Simulated signature`.
- Plan: bảng Standard/Early/Borrow proposal; net estimate; shortage waterfall; ba step; `Ready - waiting for approved window`. Không có nút `Run payment`.
- Execution: ba hàng step; `Planned`, `Submitted`, `Confirmed`, `Outcome unknown`; view transaction detail; unknown không có `Retry payment`.
- Evidence drawer: invoice → approval → plan → payment → receipt → reconciliation; `SIM-TX-PAY-001`, không link explorer.
- Liquidity allocation: `2,410 - 300 - 700 - 100 = 1,310`.
- Agent controls: `Active → Pausing → Paused`.

Test IDs: treasury-t-breakdown, invoice-upload, invoice-reviewed, submit-invoice, approval-confirm, plan-alternatives, liquidity-shortage, execution-timeline, pay-outcome-unknown, payment-evidence, liquidity-allocation, security-block, agent-pause, agent-status.

### 4.3 Director panel (ngoài khung quay) và role switch
| Control | Khi nào | Không được |
|---|---|---|
| RESET_DAY_D | Trước mỗi take; về S0, Linh, A/C/X chưa có | Reset giữa flow |
| RELEASE_EXECUTION_WINDOW | Cảnh 6 | Thay approval/bỏ preflight |
| HOLD_PAY_UNKNOWN / RELEASE_PAY_VERIFICATION | Giữ UNKNOWN rồi verify cùng reference | Sinh tx thứ hai |
| LOAD_DAY_D_PLUS_ONE | Sau transition D+1 | Chỉ tăng balance mà không có revenue event/approval C |
| RELEASE_SURPLUS_CYCLE | Cảnh 8 sau khi xem allocation | Supply bất kể reserve |
| LOAD_SECURITY_INBOX | Trước cảnh 9 | Đổi A hoặc reserve B/C |

Mock đổi role qua menu `Demo role → Linh / An / Minh`, luôn có chữ `Demo role`.

## 5. Run of show

Cảnh 1 (00:00–00:15): Linh ở Overview; không có invoice A trong list; task `Review cloud bill`.
Cảnh 2 (00:15–00:50): Click row T → `View breakdown`: Balance 1,180; Payroll reserve 300; Floor 100; Free before A 780. Click O1: Balance 100; buffer 100; spendable 0. Aave supplied 2,000; cash on wallets 1,280 vs total 3,280. B Scheduled/Reserved; O2 = 0.
Cảnh 3 (00:50–01:15): `Controls` → `Mandate`: v7 Active; WITHDRAW/REFILL/PAY/SUPPLY; caps 2,000/10,000; unknown payee BLOCK; Borrow requires separate authorization; Finance không có nút sửa quyền.
Cảnh 4 (01:15–02:05): `Invoices` → `Upload invoice` → INV-CLOUD-042.pdf → `Extracting` → Review (Draft; source + recorded fields) → tick `I verified the invoice fields` → `Submit for approval` → `Awaiting approval`; Finance không tự approve → `Demo role → An` → `Review & approve` dialog → `Confirm demo approval` → approval reference SIM-APPROVAL-A-001; A `Approved`; plan `Ready - waiting for approved window`.
Cảnh 5 (02:05–03:10): tab `Plan`: plan-a-001; Selected EARLY; `Compare options`: Standard 1,000 D+7; Early 980 selected; Borrow requires authorization/not selected. `Estimated benefit`: Discount 20; cash cost ≈0.75; fee allowance 1.20; estimate ≈18.05 USDC; synthetic assumptions badge. `View funding breakdown`: O1 needs 980; T funding capacity for A 780 ("capacity for this invoice, excluding other obligations"); deficit 200; withdraw margin 5%; withdraw 210. Plan WITHDRAW 210 → REFILL 980 → PAY 980; no action executed yet. Source `Deterministic scenario model`.
Cảnh 6 (03:10–04:30): Director release window (10:05 UTC). Tab `Execution`: preflight checks pass (approval/payee/policy/snapshot/pool/gas); WITHDRAW submitted→confirmed (S1); REFILL confirmed (S2, hold at O1); PAY submitted → `Outcome unknown` (lost RPC ack); `View transaction status`: same reference SIM-TX-PAY-001; `Verification pending`; no Retry payment; last verified balance stale. Director release verification → same tx verified; S3; A `Paid`; payment count = 1; recon `Matching`. UNKNOWN phải giữ được 8–12 giây (Director HOLD).
Cảnh 7 (04:30–05:05): `Evidence` → `View payment evidence`: chain invoice/approval/plan/payment/transaction; `Receipt checks`: recipient/asset/amount 980 match, verification source SIMULATED; `Reconciliation`: `Matched` (do hệ thống), paid 980; discount 20; estimated net ≈18.05 tách riêng. Balance summary S3: T 410; O1 100; B Reserved.
Cảnh 8 (05:05–05:55): transition `Next day / Scenario time advanced`; Director LOAD_DAY_D_PLUS_ONE (revenue + C approved atomically). `Liquidity`: S4 T 2,410; Aave 1,790; revenue +2,000 confirmed; C 700 approved. `View allocation`: B 300 + C 700 + floor 100 = 1,100; surplus 1,310. `View supply plan`: SUPPLY 1,310; exposure after 3,100/3,500; checks pass. Director RELEASE_SURPLUS_CYCLE → supply submitted→confirmed; S5: T 1,100; Aave 3,100. No profit realized counter.
Cảnh 9 (05:55–06:45): Director LOAD_SECURITY_INBOX. `Demo role → Linh` → X INV-CLOUD-043: unknown recipient; 250; chưa approved. `Submit for approval` → BLOCKED_UNKNOWN_RECIPIENT; không tạo approval/reserve/plan/payment; ledger S5 không đổi. `View security evidence` → report có badge simulated (SIM-TEST-AUTHORITY-001), tách app block vs contract-negative test. `Demo role → Minh` → `Controls → Agent controls` → `Pause agent` → `Confirm pause` → `Pausing` → `Paused`. Activity: `Next agent cycle skipped: AGENT_PAUSED`; balance S5 không đổi. Finance/Approver không có nút Pause.
Cảnh 10 (06:45–07:10): overlay `How the agent works` (sơ đồ: Reviewed invoice + approved obligations + observations → Agent observe/plan/act/verify → AI draft/explain | Financial engine | Policy checks → Signer → Safe/module → Pool/recipient → Verify/reconcile).
Cảnh 11 (07:10–07:30): outcome frame từ S5: `Invoice A: paid 980 / matched`; `Payroll and upcoming bill reserves preserved`; `One payment / unknown outcome verified before completion`; `Only 1,310 surplus supplied / agent now paused`. Footer: `Synthetic business scenario. Execution/evidence mode labeled throughout. No guaranteed yield.`

## 6. State machine
Invoice A: ABSENT → EXTRACTING → DRAFT → AWAITING_APPROVAL → APPROVED → READY_WAITING_WINDOW → EXECUTING → PAYMENT_SUBMITTED → OUTCOME_UNKNOWN → PAID → reconciliation MATCHED. Giữ invoice.status, execution.status, reconciliation.status riêng. Recon lúc UNKNOWN = `Pending verification`.

Reducers (apply theo event ID, idempotent): WITHDRAW_CONFIRMED (T +210, Aave -210); REFILL_CONFIRMED (T -980, O1 +980); PAY_SUBMITTED/ACK_TIMEOUT (không đổi ledger); PAY_VERIFIED (O1 -980, vendor paid +980, một lần); RECON_MATCHED; REVENUE_CONFIRMED (T +2.000); C_APPROVED (reserve +700 tại T); SUPPLY_CONFIRMED (T -1.310, Aave +1.310); UNKNOWN_RECIPIENT_BLOCKED (không đổi); AGENT_PAUSED (không đổi). Refresh không reset về S0; role switch không xóa dữ liệu; reload khôi phục snapshot. Mỗi reset tăng runId; callback cũ bị bỏ. Load event lặp lại phải idempotent.

Derived values (tính, không hard-code):
S0_T_free = T - B - floor = 780; O1_need = 980 + 100 - 100 = 980; gap = max(0, 980 - 780) = 200; withdraw = ceil(200 × 105/100) = 210; cash cost = 980 × 0.04 × 7/365 ≈ 0.75; net ≈ 20 - 0.75 - 1.20 ≈ 18.05; S4 protected = 300 + 700 + 100 = 1,100; surplus = 2,410 - 1,100 = 1,310; exposure = 1,790 + 1,310 = 3,100.

## 8. Checklist
- RESET_DAY_D, checkpoint, scenario UTC, runId; reload/role switch không reset.
- A tạo một lần, B có từ đầu, C chỉ D+1, X chỉ security.
- Finance không tự duyệt A; 1.000/980 nhất quán; selected 980.
- UNKNOWN giữ reference, không Retry, không Paid/Matched sớm.
- SIM references không phải fake hash; explorer disabled.
- X block và pause không đổi S5; pause có pending state.
