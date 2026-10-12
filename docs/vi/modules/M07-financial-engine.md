# M07 · Financial engine

**Nguồn chuẩn:** `docs/modules/financial-engine/README.md` · **Trạng thái:** Chi tiết (grilling M07, 11/10/2026) · **ADR:** ADR-014, ADR-015 (CP-SAT) · **Code:** `packages/py-core`

## 1. Mục đích và ranh giới

Engine là **nơi duy nhất tính số tiền và lịch trả** (BR-034). Nó thuần túy: không DB, không mạng, không chain, không LLM. API, worker, validator, tool AI (`simulate_schedule`) và benchmark đều gọi cùng các hàm này.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Kiểu tiền (số nguyên base unit), mô hình miền | Đọc chain (M06), lưu trữ (API/worker) |
| Tính thanh khoản: Available, FundingDeficit, Shortage, PreferredRefill, SourceCapacity, Cap, quyết định refill | Quyết định bước có được làm hay không (M08 làm, dùng số của engine) |
| Mô hình điều khoản và hàm giá trị (chiết khấu, phí trễ) | Trích điều khoản từ văn bản (M09) |
| Bộ lập lịch: baseline B1 (EDF), tối ưu B2 (CP-SAT) + bộ giải vét cạn để test | Gọi LLM; AI chỉ đề xuất thứ tự để engine chấm điểm |
| Chấm điểm plan, ràng buộc đang chặn, lý do không khả thi | FX/depeg, nhiều tài sản, refill Oi→Oj (Later) |
| Dự báo 7 ngày (P2) | |

## 2. Feature, yêu cầu, luật

F-051 (FR-403, FR-404; BR-030–036) · F-052 (FR-405 đã sửa; BR-052 đã sửa) · F-035 phía mô hình (FR-310, FR-311; BR-075) · F-037 (FR-314; BR-071) · F-058 (FR-415) · F-092 benchmark (FR-805).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **BaseUnits** | Số nguyên không âm theo đơn vị nhỏ nhất của tài sản. Không bao giờ dùng `float`. |
| **Ngày** | Ngày UTC `d = giây unix // 86400`. **Chuyển ngày sớm:** nếu còn ≤ 30 phút tới nửa đêm UTC thì coi "hôm nay" là ngày mai (M07-D3). |
| **Tầm nhìn** | Các ngày từ hôm nay tới `hôm nay + H`, `H = min(30, ngày đến hạn xa nhất − hôm nay + 1)`. |
| **Cửa sổ thực thi** | Chỉ việc xếp cho *hôm nay* mới chạy; các ngày sau là dự kiến, lập lại mỗi chu kỳ (rolling horizon). |
| **Giá trị** | `chiết khấu nhận được − phí trễ phải trả` khi trả vào một ngày (M07-D2: không tính chi phí vốn). |
| **Hạn khả thi** | Request có thể được xác nhận on-chain trước hoặc đúng ngày đến hạn (OQ-16), xét hạn mức, thanh khoản, cooling và ngoại lệ. |

## 4. Mô hình dữ liệu (Pydantic, bất biến)

`Asset`, `LateFee {kind: fixed | percent_per_period, amount?, rate_bps?, period_days?, cap?}`, `PaymentTerms {net_due_day, discount_bps, discount_deadline_day?, late_fee?, priority_note?}`, `WalletState {address, balance, buffer, target}`, `Limits {per_request, daily}`, `PolicyView {pay, refill, cooling_seconds}`, `Snapshot {day, source, operational, used_today, payee_active_day}`, `ApprovedRequest {id, paying_wallet, payee, amount, approved_seq, terms, exception_granted}`, `RefillDecision {kind: none | preferred | shortage | stop, amount, reason}`, `ScheduledItem`, `Infeasible`, `Schedule {items, infeasible, objective (vi phạm, hạn bị lỡ, −giá trị, số giao dịch), binding, solver: EDF | CPSAT | ORACLE, status: OPTIMAL | FEASIBLE | FALLBACK}`. Số tiền khi serialize là chuỗi thập phân (ADR-014).

## 5. Trạng thái

Engine không có trạng thái. Cùng đầu vào ⇒ đầu ra giống hệt từng byte (M07-D7).

## 6. API (Python, không HTTP)

| Hàm | Kết quả |
|---|---|
| `available(w, protected_other)` | `max(0, B − R − L − F)` |
| `funding_deficit(...)` | `max(0, R + L + F − B)` |
| `shortage(w, demand, protected_other)` | `max(0, P_o + D + F − B)` |
| `preferred_refill(...)` | `max(0, P_o + D + H − B)` |
| `source_capacity(source, ...)` | `max(0, B_T − R_T − L_T − F_T)` (gas = 0 ở M1) |
| `decide_refill(...)` | §8.1, áp giới hạn contract (M07-D4) |
| `request_value(req, pay_day)` | chiết khấu − phí trễ (§8.2) |
| `schedule_edf(...)` | baseline B1 |
| `schedule_optimal(..., time_limit_s=5)` | B2 bằng CP-SAT; lỗi/hết giờ thì dùng EDF |
| `schedule_oracle(...)` | vét cạn, N ≤ 8, **chỉ dùng trong test** |
| `score(plan, ...)` | bộ mục tiêu theo thứ tự ưu tiên, dùng so đề xuất của AI (AGT-009) |
| `binding_constraints(plan, ...)` | ràng buộc nào đang chặn và chặn bao nhiêu (panel "Vì sao") |
| `forecast(..., days=7)` | dự báo theo ngày, ngày chạm buffer, refill gợi ý (P2) |
| `fingerprint(vendor_id, invoice_no, amount, asset)` | §8.5, phải bằng giá trị contract |

Lỗi có kiểu (`InvalidTerms`, `InvalidSnapshot`, `NegativeAmount`), không bao giờ trả kết quả dở.

## 7. Luồng chính

Worker gọi `schedule_edf` (B1) → gọi `schedule_optimal` (CP-SAT, ≤ 5 giây, 1 luồng, seed cố định) → lịch B2 (OPTIMAL / FEASIBLE / FALLBACK=EDF) → gửi cho agent (worker-ai) cùng các ràng buộc đang chặn → agent đề xuất thứ tự + lý do → engine chấm điểm đề xuất và B2 → chọn bên tốt hơn; việc của hôm nay chuyển sang validator.

## 8. Thuật toán và ví dụ

### 8.1 Quyết định refill (BR-032/033/036, M07-D4)

```
D        = số tiền request (gas = 0 ở M1)
Shortage = max(0, P_o + D + F − B)
Pref     = max(0, P_o + D + H − B)
Bound    = max(0, D + H − B)            # contract: số dư sau refill ≤ amount + target
Cap      = min(SourceCapacity, refill.per_request, refill.daily − đã refill hôm nay)
Shortage == 0                → không refill
Shortage > Bound             → dừng (REFILL_BOUND)
Cap ≥ min(Pref, Bound)       → refill min(Pref, Bound)
Cap ≥ Shortage               → refill Shortage (báo TARGET_NOT_REACHED)
còn lại                      → dừng (OVER_REFILL_DAILY, rồi OVER_REFILL_PER_REQUEST, rồi SOURCE_INSUFFICIENT)
```

| Ví dụ | B | P_o | D | F | H | Shortage | Pref | Bound | Cap | Kết quả |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| UC-02 | 20 | 0 | 100 | 10 | 10 | 90 | 90 | 90 | 2.500 | refill 90 |
| Domain §3.4 a | 300 | 100 | 400 | 50 | 150 | 250 | 350 | 250 | 350 | refill **250** (bound cắt 350 → 250) |
| Domain §3.4 b | 300 | 100 | 400 | 50 | 150 | 250 | 350 | 250 | 300 | refill 250 |
| Domain §3.4 c | 300 | 100 | 400 | 50 | 150 | 250 | 350 | 250 | 200 | dừng SOURCE_INSUFFICIENT |
| Bound dừng | 0 | 300 | 50 | 40 | 60 | 390 | 410 | 110 | 2.500 | dừng REFILL_BOUND |

Ở dòng a, tài liệu gốc ghi 350; vì giới hạn của contract (M04-D4) nên engine chỉ refill 250, request còn lại trong cùng ví sẽ tự refill khi tới lượt. Golden test của ENG-002/003 dùng số mới.

### 8.2 Giá trị khi trả vào ngày p (M07-D1, D2)

```
discount(p) = floor(amount · discount_bps / 10000) nếu p ≤ hạn chiết khấu, ngược lại 0
late(p): p ≤ hạn thanh toán hoặc không có phí trễ → 0
         fixed → amount_fee
         percent_per_period → periods = ceil((p − hạn) / period_days); floor(amount · rate_bps · periods / 10000)
         có cap thì lấy min(late, cap)
value(p) = discount(p) − late(p)
```

| Hóa đơn | Điều khoản | Ngày trả | Giá trị |
|---|---|---|---|
| 1.000 | 2/10 net 30 | ngày 8 | +20 |
| 1.000 | 2/10 net 30 | ngày 12 | 0 |
| 1.000 | net 30, 1,5 %/7 ngày | ngày 31 | −15 (1 kỳ) |
| 1.000 | net 30, 1,5 %/7 ngày | ngày 45 | −45 (3 kỳ) |
| 1.000 | net 30, phí cố định 25, trần 25 | ngày 60 | −25 |

**Phí gas (FEE-2, thêm ở M03):** khi xét trả *sớm* để lấy chiết khấu, bộ tối ưu dùng `discount(p) − phí quy ra tài sản`, với `phí quy ra tài sản = phí plan ước tính (wei) × giá ETH tham chiếu / 1e18`. Nếu chiết khấu ≤ phí thì trả sớm không có lợi và request được xếp theo ngày đến hạn. Việc giữ plan vì phí của hôm nay do M10 áp trước khi ký attestation; ngày bị giữ thành không khả thi cho hôm nay.

### 8.3 Baseline B1 — EDF

Sắp theo `(ngày đến hạn, thứ tự duyệt)`. Từ hôm nay, lấy lần lượt request nếu: payee đã Active ngày đó, trong trần mỗi khoản (hoặc có ngoại lệ), trong trần ngày, refill khả thi (§8.1) với lượng rút cộng dồn từ nguồn. Request không xếp được thì dời sang ngày sau; hết tầm nhìn vẫn không xếp được thì ghi `Infeasible` với lý do chặn đầu tiên.

### 8.4 Tối ưu B2 — mô hình CP-SAT (M07-D5)

**Biến:** `x[r,d] ∈ {0,1}` request r trả ngày d; `u[r] = 1 − Σ_d x[r,d]`; `ref[r] ∈ [0, Bound_r]`.

**Ràng buộc:** (1) mỗi request tối đa một ngày; (2) cooling: `x[r,d] = 0` nếu d trước ngày payee Active; (3) vượt trần mỗi khoản mà không có ngoại lệ → không xếp (báo `NEEDS_EXCEPTION`); (4) trần PAY ngày; (5) trần REFILL ngày; (6) tổng refill cộng dồn ≤ SourceCapacity; (7) số dư mỗi ví mỗi ngày ≥ buffer; (8) refill mỗi request ≤ `amount + H − B` tại lúc trả.

**Mục tiêu theo thứ tự, giải từng tầng (M07-D6):** (1) tối đa số request trả kịp hạn; (2) tối đa tổng giá trị; (3) tối thiểu số giao dịch; (4) hòa thì ưu tiên thứ tự duyệt. Tầng sau giữ nguyên tối ưu của tầng trước. **Tất định:** `num_workers = 1`, seed cố định, đầu vào sắp theo id (M07-D7). **Dự phòng:** lỗi/hết giờ không có lời giải → trả lịch EDF với `status = FALLBACK`.

**Oracle (test):** vét cạn mọi cách xếp với N ≤ 8 request và tầm nhìn ≤ 5 ngày; CP-SAT phải cho cùng giá trị mục tiêu trên dữ liệu sinh ngẫu nhiên.

### 8.5 Fingerprint

`normalize(s) = s.strip().casefold()`, sau đó bỏ mọi khoảng trắng Unicode và `- _ / . #`; các số 0 ở đầu được giữ nguyên. `fingerprint = keccak256(abi.encode(normalize(vendor_id), normalize(invoice_no), amount, asset))`, trong đó `amount` là số nguyên base unit được mã hóa thành `uint256` và `asset` là địa chỉ EVM. Vector dùng chung với contract (SC-017) và web.

## 9. Cấu hình

Tầm nhìn tối đa 30 ngày · chuyển ngày sớm 30 phút · CP-SAT 5 giây mỗi chu kỳ (chia cho các tầng) · 1 luồng, seed 42 · oracle N ≤ 8, tầm nhìn ≤ 5 · chiết khấu làm tròn xuống · dự báo 7 ngày.

## 10. An toàn và đúng đắn

| Rủi ro | Biện pháp | Bằng chứng |
|---|---|---|
| Làm tròn số thực | `BaseUnits` từ chối float; CP-SAT chỉ dùng số nguyên | test kiểu; luật ruff cấm `float(` |
| Số do LLM đưa | Engine bỏ qua mọi số tiền từ AI; đề xuất AI chỉ là thứ tự | AGT-009 |
| Plan vi phạm luật cứng | Ràng buộc phản ánh BR-013/022/030/036; validator kiểm lại; contract thi hành | property test + POL-004 |
| Kết quả không tất định | 1 luồng, seed cố định, đầu vào đã sắp | test chạy hai lần ra giống nhau |
| Solver treo | Giới hạn thời gian + dùng EDF | test hết giờ |
| Tràn số | Kiểm biên (< 2⁶³) trước khi dựng mô hình | test |

## 11. Tình huống lỗi

Điều khoản không hợp lệ → `InvalidTerms`, loại request với `TERMS_INVALID` · snapshot cũ/thiếu → `InvalidSnapshot` (validator sẽ BLOCK) · CP-SAT lỗi → EDF, `FALLBACK`, ghi metric · mọi thứ không khả thi → lịch rỗng, từng request có lý do → review item.

## 12. Kế hoạch test

Golden (bảng §8.1, UC-02, bảng §8.2) · property (hypothesis, ≥ 1.000 ca): không vi phạm buffer, refill ≤ bound và ≤ Cap, tôn trọng trần/cooling, CP-SAT không bao giờ kém EDF · tương đương oracle (N ≤ 8) · tất định · hết giờ/dự phòng · vector fingerprint · coverage ≥ 85 %.

## 13. Ticket theo thứ tự

ENG-001 kiểu tiền & mô hình → ENG-002 tính thanh khoản → ENG-003 quyết định refill (có bound) → ENG-004 property test → ENG-005 điều khoản & giá trị (3 loại phí trễ + phí gas) → ENG-006 EDF → **ENG-012 oracle vét cạn (mới)** → ENG-007 tối ưu CP-SAT → ENG-008 chấm điểm & ràng buộc chặn → ENG-009 fingerprint → ENG-010 dựng EIP-712 → ENG-011 dự báo (P2).

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M07-D1 | Phí trễ: **cố định**, **% mỗi kỳ đã bắt đầu (lãi đơn)**, có thể có **trần tổng**. Không lãi kép. |
| M07-D2 | Giá trị = chiết khấu nhận được − phí trễ. **Không tính chi phí vốn.** |
| M07-D3 | **Rolling horizon** theo ngày UTC, tối đa 30 ngày; chỉ chạy việc của hôm nay; chuyển ngày sớm 30 phút trước nửa đêm UTC. |
| M07-D4 | Refill bị giới hạn bởi bound của contract `amount + target − balance`; nếu ngay Shortage đã vượt bound → dừng `REFILL_BOUND`. |
| M07-D5 | Bộ tối ưu: **Google OR-Tools CP-SAT**, sau interface `Solver` (ADR-015). |
| M07-D6 | Mục tiêu theo thứ tự giải từng tầng: kịp hạn → giá trị → số giao dịch → thứ tự duyệt. |
| M07-D7 | Giải tất định: 1 luồng, seed cố định, đầu vào đã sắp. |
| M07-D8 | Bộ giải **vét cạn** (N ≤ 8) chỉ dùng trong test để chứng minh tối ưu. |
| M07-D9 | Request vượt trần mỗi khoản mà chưa có ngoại lệ thì loại và báo `NEEDS_EXCEPTION`, kèm giá trị nó mang lại nếu được cấp (để AI soạn đề nghị ngoại lệ). |
| M07-D10 | Gas là chi phí khi xét trả sớm (FEE-2); không ưu tiên trả sớm nếu chiết khấu không lớn hơn phí. |

Câu hỏi mở: M07-Q1 — có đưa khoản phải thu (tiền vào dự kiến) vào dự báo không? (Later, cần nguồn dữ liệu công nợ phải thu.)

## 15. Thay đổi theo v0.3 (ADR-019), thay thế các mục trên nếu khác

**Vị thế thanh khoản:** snapshot thêm USDC trong Safe, aUSDC, thanh khoản còn trong pool, lãi suất gửi/vay, health factor, nợ.

```
PaymentReserve       = Σ số tiền sẽ trả của các request đã duyệt, chưa trả, đến hạn trong 30 ngày
RequiredSafeReserve  = PaymentReserve + sàn Safe + dự trữ trả nợ + khoản đang giữ
AvailableForSupply   = max(0, USDC trong Safe − RequiredSafeReserve)
AccessibleLiquidity  = USDC trong Safe + min(aUSDC, thanh khoản pool)
```

**decide_liquidity → không làm gì | SUPPLY x | WITHDRAW y** (mỗi chu kỳ tối đa một lệnh): thiếu dự trữ `d` → rút `min(aUSDC, thanh khoản pool, d × 1,05)`; vẫn thiếu → `INSUFFICIENT_LIQUIDITY` + đề xuất vay; dư ≥ `min_supply` → supply phần dư (trong hạn mức). Trong plan của request, bước WITHDRAW đặt trước REFILL khi refill sẽ phá dự trữ.

Ví dụ: Safe 6.000, aUSDC 0, sàn 1.000, đã duyệt chưa trả 2.000 → cần 3.000, dư 3.000 ≥ 500 → SUPPLY 3.000 (D2). Duyệt thêm hóa đơn 2.500 → cần 5.500, Safe còn 3.000 → thiếu 2.500 → WITHDRAW 2.625 (D3).

**Giá trị khi trả ngày p (thay §8.2):** tiết kiệm = mức chuẩn − số tiền thực trả (lấy từ bản duyệt) − phí trễ; chỉ ưu tiên trả sớm nếu tiết kiệm − phí gas − lãi gửi bị mất > 0. Mục tiêu CP-SAT giữ thứ tự cũ, phần giá trị nay gồm cả lãi gửi.

**Đề xuất vay (F-069):** số tiền, chi phí vay tới khi trả, chi phí rút, health factor trước/sau, lý do. Không bao giờ vào plan thực thi khi chưa có quyền (BR-044). **Ticket:** ENG-013, ENG-014; sửa ENG-001/005/007/010.
