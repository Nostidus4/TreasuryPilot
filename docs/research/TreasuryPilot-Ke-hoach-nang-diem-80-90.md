# TreasuryPilot: Kế hoạch nâng Base Score lên 80–90

**Ngày:** 10/10/2026 · **Deadline:** 20/10/2026, 23:59 giờ Bắc Kinh
**Điểm hiện tại (ước tính):** 72/100 = Task 7,5 · Security 8,0 · Innovation 6,0
**Mục tiêu:** ≈86/100 (vùng 80–90; trần thực tế ≈88)

> **Nói thẳng trước:** Điểm ở đây là ước tính của hội đồng mô phỏng, không phải cam kết của ban giám khảo. **≈83 là mức thực tế** nếu đội làm xong nhóm P0, **≈86** nếu xong thêm P1. **Từ 87 trở lên** đòi hỏi làm gần như toàn bộ kế hoạch, demo không lỗi và trả lời phản biện tốt. Không có hạng mục nào trong file này cộng điểm nếu chỉ *viết* mà không *chạy được và có bằng chứng*.

---

## 0. Đích đến theo từng tiêu chí

| Tiêu chí | Trọng số | Hiện tại | Mức sàn (≈83) = làm xong P0 | Mức mục tiêu (≈86) = P0 + P1 | Khoảng cách chính cần lấp |
|---|---:|---:|---:|---:|---|
| Task Completion | 40% | 7,5 → 30 | 8,5 → 34 | **8,9 → 35,6** | Tự chạy theo deadline, nhiều hóa đơn, phục hồi lỗi, số liệu độ ổn định |
| Security & Compliance | 30% | 8,0 → 24 | 8,8 → 26,4 | **9,0 → 27** | Invariant/fuzz test, chống lừa đổi tài khoản vendor, chống trùng invoice, gói compliance |
| Innovation & Interaction | 30% | 6,0 → 18 | 7,5 → 22,5 | **7,9 → 23,7** (tối đa ~8,2 → 24,6) | AI làm việc mà rule không làm tốt và có đo lường; trải nghiệm hội thoại; UI giải thích được |
| **Base Score** | | **72** | **≈83** | **≈86 (tối đa ≈88)** | |

**Nguyên tắc:** mỗi cải tiến phải (1) gắn với một tiêu chí chính thức, (2) có bằng chứng (tx hash, test, log, số liệu), (3) làm được trong 10 ngày.

---

## 1. Ý tưởng then chốt: cho AI một "việc tiền thật"

Điểm yếu lớn nhất hiện nay là câu hỏi *"Sao không viết cron script?"* (*TP Autonomy §6*). Lời giải là đổi bài toán từ "nạp tiền rồi trả" sang:

> **"Trả đúng hóa đơn, vào đúng lúc, để tối ưu tiền của doanh nghiệp, trong giới hạn thanh khoản và mandate."**

Hóa đơn thật có **điều khoản thanh toán viết bằng ngôn ngữ tự nhiên**, ví dụ:
- "2/10 net 30": trả trong 10 ngày được giảm 2%, hạn chót 30 ngày.
- "Late fee 1.5% per week after due date": phạt trễ hạn.
- "Critical supplier: hosting shutdown if unpaid": mức độ ưu tiên.

Khi nhiều hóa đơn cạnh tranh cùng nguồn tiền, trần ngày và buffer, thì quyết định *trả cái nào trước, cái nào chờ, cái nào xin ngoại lệ* không còn là chuyện một rule "deadline sớm trước" giải tốt. Đây là chỗ AI tạo giá trị **đo được bằng tiền**:

| Vai trò | Làm gì | Ai chịu trách nhiệm |
|---|---|---|
| **AI (LLM)** | Đọc invoice phi cấu trúc → trích xuất trường + điều khoản (chiết khấu, phạt, mức ưu tiên) + cờ bất thường; đề xuất lịch trả và giải thích; soạn yêu cầu ngoại lệ | Chỉ đề xuất |
| **Optimizer xác định** | Với điều khoản đã được người duyệt, tính lịch tối ưu dưới các ràng buộc (greedy hoặc ILP nhỏ) | Tính số |
| **Validator + contract** | Kiểm tra mandate, buffer, trần, bản duyệt | Quyết định cuối cùng |

**Chỉ số trình bày cho giám khảo:** "Trên 30 kịch bản, TreasuryPilot (AI) tiết kiệm X USDC chiết khấu/phí phạt và trả đúng hạn Y% so với baseline rule-based (EDF), với 0 vi phạm mandate." Số liệu phải là kết quả chạy thật, kể cả khi AI không thắng ở mọi chỉ số.

---

## 2. Danh sách cải tiến

Ưu tiên: **P0** = bắt buộc để đạt mức sàn ≈83 · **P1** = để đạt ≈86 · **P2** = để chạm ≈88 nếu còn thời gian.
Δ = mức tăng điểm ước tính *của riêng tiêu chí đó* (thang 10).

### 2.1 Task Completion (7,5 → 9,0)

| ID | Cải tiến | Bằng chứng nộp | Δ | Công | Ưu tiên |
|---|---|---|---:|---|---|
| T1 | **Agent tự chạy theo deadline:** scheduler tự kích hoạt khi hóa đơn đã duyệt đến cửa sổ xử lý. Con người chỉ duyệt invoice, không bấm "execute". Đây là "financial participant" đúng nghĩa | Log tự kích hoạt + tx hash | +0,3 | 0,5 ngày | P0 |
| T2 | **Kịch bản nhiều hóa đơn (5–8)** trên O1/O2, cạnh tranh trần ngày và nguồn T. Hoàn thành mọi khoản hợp lệ, báo rõ khoản bị chặn hoặc hoãn kèm lý do | Báo cáo batch + tx hash | +0,3 | 0,5 ngày | P0 |
| T3 | **Demo phục hồi:** tắt executor ngay sau broadcast → khởi động lại → hệ thống đọc trạng thái chain, **không trả lần hai** (AT-06), tiếp tục đúng bước | Video + log + chỉ 1 tx payment | +0,3 | 1 ngày | P0 |
| T4 | **Stablecoin testnet "thật":** dùng USDC testnet của Circle nếu faucet hỗ trợ chain đã chọn (cần kiểm tra); nếu không thì `tUSDC` tự deploy, ghi nhãn rõ | Địa chỉ token trong manifest | +0,1 | 0,2 ngày | P0 |
| T5 | **Đối soát xuất được:** CSV/bút toán nhật ký (chi phí vendor ↔ tiền; refill = chuyển nội bộ), mỗi dòng gắn invoice hash + tx hash + phí gas | File CSV mẫu | +0,1 | 0,5 ngày | P1 |
| T6 | **Số liệu độ ổn định:** chạy kịch bản tự động 30 lần trên Anvil và ≥10 lần trên testnet; báo completion %, thời gian trung vị, phí, số lần can thiệp | Bảng trong README + log | +0,2 | 0,5 ngày | P1 |
| T7 | **Tái lập một lệnh:** `docker compose up` + script deploy + seed kịch bản; CI chạy Foundry + integration test | README + badge CI | +0,1 | 0,5 ngày | P1 |
| T8 | **Dự báo thanh khoản 7 ngày:** từ các nghĩa vụ đã duyệt sắp đến hạn, tính "runway" từng ví và lên lịch refill trước | Màn hình + log | +0,1 | 0,5 ngày | P2 |

**Đích:** P0 → 8,5 · +P1 → 8,9 · +P2 → 9,0

### 2.2 Security & Compliance (8,0 → 9,0)

| ID | Cải tiến | Bằng chứng nộp | Δ | Công | Ưu tiên |
|---|---|---|---:|---|---|
| S1 | **Invariant + fuzz test (Foundry)** cho ít nhất 8 invariant: không trả khi chưa có chữ ký approver; tổng chi trong ngày ≤ trần; số dư ví sau khi agent hành động ≥ buffer; mỗi `request_id` chỉ trả một lần; ngoại lệ chỉ dùng một lần; pause thì không thực thi được; payee ngoài allowlist bị chặn; đổi version không reset counter. Thêm báo cáo Slither | Output `forge test` + Slither report | +0,3 | 1 ngày | P0 |
| S2 | **Thời gian chờ cho payee mới (cooling period):** địa chỉ nhận mới hoặc bị đổi chỉ có hiệu lực sau N giờ (demo đặt 5 phút) và phải do owner thêm. Đây là cách chặn **lừa đảo đổi tài khoản nhà cung cấp (vendor/BEC fraud)**, rủi ro thanh toán B2B phổ biến mà ngân hàng nào cũng biết. Đây là điểm security dễ "ăn điểm" nhất với giám khảo WeBank | Test + tx revert khi trả payee chưa hết thời gian chờ | +0,2 | 0,5 ngày | P0 |
| S3 | **Chống trùng invoice ở mức contract:** lưu `fingerprint = hash(vendorId, invoiceNo, amount)`. Cùng invoice dưới request ID khác bị chặn. Sửa đúng lỗ hổng tài liệu tự nhận (*UC-04*) | Test AT mới | +0,1 | 0,3 ngày | P0 |
| S4 | **Bảng permission tiers (5 tầng)** cho security self-assessment: Owner (governance) · Approver (duyệt invoice, EIP-712) · Guardian (chỉ pause) · Executor (PAY/REFILL trong mandate) · AI (không có khóa, không có quyền ghi). Mỗi tầng ghi rõ "được / không được / enforce ở đâu" | Tài liệu + mapping tới code | +0,2 | 0,3 ngày | P0 |
| S5 | **Red-team suite:** 20 invoice chứa prompt injection (đổi ví, nâng hạn mức, "đã duyệt trước", unicode lừa mắt) + 10 lần gọi thẳng contract để bypass. Công bố bảng kết quả | Bảng kết quả + test | +0,1 | 0,5 ngày | P1 |
| S6 | **Gói compliance:** sàng lọc payee với danh sách chặn (fixture mẫu từ danh sách trừng phạt công khai, ghi nhãn); chỉ đưa hash invoice lên chain, dữ liệu cá nhân giữ off-chain; audit log = event on-chain + log off-chain nối hash; slide định vị pháp lý (testnet, khách hàng ngoài Trung Quốc đại lục, kiến trúc tái dùng được cho tokenised deposit) | Tài liệu + test sàng lọc | +0,1 | 0,5 ngày | P1 |
| S7 | **Circuit breaker:** tự pause khi có bất thường (ví dụ ≥3 lần bị contract từ chối trong 10 phút, hoặc AI đề xuất vượt quyền). Chỉ owner được mở lại | Test + log | +0,1 | 0,3 ngày | P2 |
| S8 | **Tách khóa:** executor ký trong một signer service riêng, chỉ nhận plan đã qua validator. Process LLM không có khóa hay đường gọi chain trực tiếp | Sơ đồ + cấu hình | +0–0,1 | 0,3 ngày | P2 |

**Đích:** P0 → 8,8 · +P1 → 9,0 · +P2 → 9,1. Trần thực tế khoảng 9,2 vì contract chưa được audit.

### 2.3 Innovation & Interaction (6,0 → 8,0–8,5)

| ID | Cải tiến | Bằng chứng nộp | Δ | Công | Ưu tiên |
|---|---|---|---:|---|---|
| N1 | **Invoice Intelligence (AI):** đọc PDF/email → trường có cấu trúc + **điều khoản thanh toán** (chiết khấu, phạt, ưu tiên) + cờ bất thường (địa chỉ khác lịch sử vendor, số tiền lệch bất thường, nghi trùng). Mỗi cờ có bằng chứng; người duyệt thấy diff trước khi ký | Demo + bộ 30 invoice mẫu + độ chính xác trích xuất | +0,6 | 1,5 ngày | P0 |
| N2 | **Terms-aware Liquidity Scheduler:** AI đề xuất lịch trả + giải thích; optimizer xác định kiểm tra và tính số; validator chặn mọi thứ ngoài mandate. Tự soạn yêu cầu ngoại lệ có lý do | Demo + log `plannerSource` | +0,4 | 1,5 ngày | P0 |
| N3 | **Benchmark B1 vs B2:** cùng 30 kịch bản, rule-based (EDF) so với AI; đo tiền tiết kiệm (chiết khấu + tránh phạt), tỷ lệ đúng hạn, số ngoại lệ, số tx, phí, **số vi phạm = 0**. Báo cáo trung thực | Bảng + script tái chạy | +0,3 | 1 ngày | P0 |
| N4 | **Treasury Copilot hội thoại:** owner hỏi "Tuần này trả hết được không mà không phá buffer?" hoặc "Nếu hoãn invoice C thì sao?". Agent chạy mô phỏng bằng policy engine và trả lời bằng số + kế hoạch. Đây là phần **interaction** | Video | +0,4 | 1 ngày | P1 |
| N5 | **UI giải thích được:** thẻ kế hoạch (vì sao thứ tự này, tiết kiệm bao nhiêu), timeline thực thi live kèm link explorer, khung "Why blocked?" lấy reason code từ validator, ký duyệt bằng ví ngay trên UI | Ảnh chụp + video | +0,2 | 1 ngày (song song) | P0 |
| N6 | **On-chain proof of reconciliation:** đăng attestation (ví dụ EAS, nếu có trên chain đã chọn; cần kiểm tra) cho mỗi khoản đã trả và đối soát, gắn invoice hash + tx hash. Hỗ trợ cả on-chain bonus | Attestation UID | +0,2 (+bonus) | 0,5 ngày | P2 |
| N7 | **Thông báo chủ động:** bot (Telegram hoặc email) báo "Invoice B cần ngoại lệ, đây là lý do, bấm để ký" | Video | +0,1 | 0,5 ngày | P2 |

**Đích:** P0 → 7,5 · +P1 → 7,9 · +P2 → 8,2, với điều kiện B2 thực sự có lợi ích đo được. Nếu B2 không hơn B1, Innovation chỉ còn khoảng 6,5–7,0 và Base khoảng 80.

---

## 3. Những việc KHÔNG làm (tốn thời gian, không tăng điểm tương xứng)

- Swap qua DEX thật trên testnet, bridge, multi-chain.
- Enforce reserve/hold on-chain đầy đủ và quote có chữ ký (*TP Domain §5.2–5.3*). Giữ ở mức buffer + trần.
- ERC-4337 bundler/paymaster, session key chuẩn mới.
- Huấn luyện mô hình ML riêng. Dùng LLM qua API + structured output là đủ.
- Tích hợp ERP thật. Xuất CSV là đủ.

---

## 4. Kiến trúc mục tiêu (gọn)

```
[Invoice PDF/email] → AI Invoice Intelligence ─┐
                                               ├→ Approver UI (diff + ký EIP-712)
[Vendor registry + history] ───────────────────┘
                      ↓ approved requests (on-chain hash)
AI Scheduler ⇄ Deterministic Optimizer/Policy Engine → Validator
                      ↓ plan (planHash, policyVersion, nonce, expiry)
Signer service (executor key) → TreasuryPilotModule on Safe T / O1 / O2
   (allowlist + cooling period, per-request & daily UTC caps, buffer,
    request/fingerprint replay, one-time exception, pause/guardian)
                      ↓ receipts/events
Reconciler → CSV/journal + (EAS attestation) → Dashboard / Copilot chat
```

Stack gợi ý: Solidity + Foundry, Safe contracts (pin version), Node/TS + Viem, PostgreSQL hoặc SQLite, React, LLM qua adapter có structured output.

---

## 5. Lịch 10 ngày (đội 3–4 người)

Vai trò: **SC** = Smart Contract · **BE** = Backend · **AI** · **FE/PM** = Frontend + tài liệu/demo.

| Ngày | SC | BE | AI | FE/PM | Mốc / cắt phạm vi |
|---|---|---|---|---|---|
| 10/10 | Khung Safe + module trên Anvil | Repo, schema DB, chọn chain | Thu thập/viết 30 invoice mẫu có điều khoản | Email ban tổ chức về testnet; chốt O1–O8 trong 1 giờ | |
| 11/10 | PAY/REFILL, allowlist, trần, buffer, replay | Policy engine (công thức §3) | Trích xuất invoice v1 | Wireframe 3 màn hình | |
| 12/10 | Chữ ký approver EIP-712, **S2 cooling period**, **S3 fingerprint**, pause; deploy testnet | Executor + theo dõi receipt + Unknown | Cờ bất thường v1 | UI duyệt + ký | **Mốc #1:** 1 payment đúng + 3 vi phạm bị contract chặn trên testnet. Nếu chưa đạt: cắt UC-06, N4, N6, N7 |
| 13/10 | **S1** invariant/fuzz + Slither | **T1** scheduler tự kích hoạt, **T2** batch | **N2** scheduler + optimizer | UI timeline thực thi | |
| 14/10 | UC-06 ngoại lệ một lần | **T3** phục hồi sau crash | **N3** harness benchmark B1/B2 | UI "Why" + thẻ kế hoạch | |
| 15/10 | Sửa lỗi; S7 nếu kịp | **T5** CSV đối soát, **T6** chạy 30+10 lần | Chạy benchmark, ghi số | Tích hợp E2E | **Mốc #2:** E2E 3 lần liên tiếp không lỗi. Nếu chưa đạt: đóng băng tính năng |
| 16/10 | **S5** bypass tests | **T7** docker + CI | **N4** Copilot chat; **S5** injection suite | Tài liệu kỹ thuật EN (bản nháp) | Chỉ làm N4 nếu mốc #2 đạt |
| 17/10 | N6 EAS (nếu kịp) | **S6** sàng lọc payee, log nối hash | Tinh chỉnh giải thích | Security self-assessment (**S4** tiers + known risks) | **Feature freeze 23:59** |
| 18/10 | Review code + deployment manifest | Evidence bundle | Viết kết quả benchmark | Deck 10 phút | |
| 19/10 | Hỗ trợ quay | Chạy thử demo | Chuẩn bị Q&A | Quay video 5 phút (2 bản) | |
| 20/10 | — | — | — | **Nộp trước 12:00 giờ Bắc Kinh**, sau đó chỉ sửa nhỏ | |

Đội chỉ có 2 người: bỏ toàn bộ P2, N4 và T8. Mục tiêu khi đó khoảng 80–83.

---

## 6. Gói hồ sơ nộp: những gì làm tăng điểm

| Hạng mục (Thể lệ) | Nội dung để ăn điểm |
|---|---|
| 01 Technical doc | Sơ đồ kiến trúc §4; công thức thanh khoản; thuật toán scheduler (AI đề xuất + optimizer xác định); bảng invariant; kết quả benchmark B1/B2 |
| 02 Deck 10 phút | 1' vấn đề (hóa đơn + ví thiếu tiền + lừa đổi tài khoản vendor) · 1' giải pháp · 4' demo · 1,5' security (blast radius, invariant, cooling period) · 1,5' kết quả số (benchmark, độ ổn định) · 1' khác biệt + tầm nhìn |
| 03 Video 5 phút | Kịch bản §7 |
| 04 Source code | README tái lập một lệnh, CI xanh, AT-01..13 + test mới, red-team suite |
| 05 Security self-assessment | Bảng 5 tầng quyền; known risks trung thực (chưa audit, RPC trust, owner ngoài mandate, quote trust) |
| 06 Execution evidence | Danh sách tx hash theo từng kịch bản (refill, pay, revert do vi phạm, pause, ngoại lệ, attestation) + evidence bundle JSON |

---

## 7. Kịch bản demo 5 phút (bản nâng cấp)

| Thời điểm | Cảnh | Tiêu chí được chứng minh |
|---|---|---|
| 0:00 | NovaLabs: ví quỹ T có 10.000 USDC, ví chi O1 còn 20. Có 5 hóa đơn trong hộp thư | Bối cảnh |
| 0:30 | AI đọc 5 invoice: phát hiện "2/10 net 30" ở invoice A, phạt trễ ở invoice D, **invoice E đổi địa chỉ nhận so với lịch sử vendor** (cờ BEC) | Innovation |
| 1:15 | Finance lead xem diff và ký duyệt A–D. E bị giữ lại; nếu cố trả thì contract chặn do cooling period | Security |
| 1:45 | Không ai bấm gì: agent tự lên lịch (trả A sớm để lấy chiết khấu, D trước hạn phạt), refill O1, trả. Tx hash chạy live | Task |
| 2:45 | Invoice C vượt trần: agent soạn yêu cầu ngoại lệ có lý do, owner ký, khoản được trả. Trần ngày vẫn được giữ | Task + Security |
| 3:15 | Tắt executor giữa chừng, bật lại: không có khoản trả trùng | Task |
| 3:45 | Owner hỏi Copilot: "Tuần này trả hết được không mà không phá buffer?" Agent trả lời bằng số và kế hoạch | Interaction |
| 4:15 | Màn hình kết quả: tiết kiệm X USDC so với rule-based, 0 vi phạm, đối soát CSV + attestation | Innovation + Task |
| 4:45 | Câu chốt: *"Humans decide whether to pay. The agent decides how and when. The contract makes sure it can't do anything else."* | |

---

## 8. Chuẩn bị phản biện (để không mất điểm ở Q&A)

| Câu hỏi | Trả lời ngắn |
|---|---|
| "Sao không viết cron script?" | "Chúng tôi có làm: đó là baseline B1. Trên 30 kịch bản, B2 hơn ở [số liệu] vì đọc và tận dụng điều khoản thanh toán phi cấu trúc. Phần tính tiền và cho phép chi vẫn là deterministic." |
| "Ant International đã có AI tự nạp tiền?" | "Whale là hệ thống nội bộ của Ant trên tokenised deposit. Chúng tôi đem mô hình đó cho SME, với mandate do chủ quỹ tự đặt và contract enforce, gắn với từng hóa đơn đã duyệt." |
| "Stablecoin ở Trung Quốc đại lục?" | "Demo chạy testnet. Khách hàng mục tiêu ngoài đại lục. Lớp mandate và đối soát độc lập với loại tài sản, áp dụng được cho tokenised deposit hoặc chuỗi được cấp phép." |
| "Executor bị hack thì sao?" | "Không trả được khoản nào chưa có chữ ký approver; payee mới phải qua cooling period; thiệt hại tối đa là chuyển nội bộ trong trần ngày. Invariant test chứng minh." |
| "Bao nhiêu khách hàng đã xác nhận?" | Nói thật số phỏng vấn (nên cố đạt 2–3 trước 18/10) + kế hoạch H1–H7. |

---

## 9. Bảng tổng hợp đường lên điểm

| Gói làm được | Task | Security | Innovation | **Base** |
|---|---:|---:|---:|---:|
| Hiện tại (chỉ tài liệu → MVP gốc) | 7,5 | 8,0 | 6,0 | **72** |
| + P0 (T1–T4, S1–S4, N1–N3, N5) | 8,5 | 8,8 | 7,5 | **≈83** |
| + P1 (T5–T7, S5–S6, N4) | 8,9 | 9,0 | 7,9 | **≈86** |
| + P2 (T8, S7–S8, N6–N7) | 9,0 | 9,1 | 8,2 | **≈88** |
| Nếu AI không thắng baseline | 0 | 0 | −1,0 đến −1,5 | **trừ khoảng 3–4,5** |

Mức trần thực tế khoảng 88 vì contract chưa được audit, chưa có khách hàng thật và chạy trên testnet. **90+ gần như không thể nếu chỉ có 10 ngày.** Đừng đặt mục tiêu đó làm bằng mọi giá.
