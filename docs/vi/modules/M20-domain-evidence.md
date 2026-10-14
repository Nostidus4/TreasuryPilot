# M20 · Nghiệp vụ & bằng chứng (không code)

**Nguồn chuẩn:** `docs/modules/domain-evidence/README.md` · **Trạng thái:** Đã qua G3, chi tiết 11/10/2026 · **Ticket:** DOM-001 … DOM-017 (nhãn `non-code`)

## 1. Mục đích

Đây là phần việc của **3 thành viên cố vấn tài chính/blockchain** (cùng anh Phúc cho phần chain). Nó tạo ra mọi thứ giám khảo chấm mà không phải code:

| Tiêu chí chính thức | M20 đóng góp |
|---|---|
| Hoàn thành nhiệm vụ (40 %) | Hóa đơn và kịch bản thực tế cho demo và đo độ ổn định; kịch bản demo và video |
| Bảo mật & tuân thủ (30 %) | Hóa đơn tấn công red-team, mô hình mối đe dọa đã soát, danh sách rủi ro, bản tự đánh giá bảo mật, định vị tuân thủ |
| Đổi mới & tương tác (30 %) | Kịch bản có đáp án giúp benchmark B1 vs B2 có ý nghĩa ("vì sao cần AI?"); phỏng vấn khách hàng chứng minh vấn đề |
| Checklist nộp bài | Tài liệu kỹ thuật, deck, video, bản tự đánh giá bảo mật (mục 01, 02, 03, 05) |

Không có M20 thì benchmark AI không có gì để đo, bộ red-team không có đòn tấn công, gói nộp không có tài liệu. **Dev phụ thuộc vào các file này**, nên định dạng dưới đây là hợp đồng.

## 2. Người và vai trò

Trưởng nhóm phân người qua trường **Owner** trên GitHub Project. Gợi ý chia theo chuyên môn:

| Vai trò | Trọng tâm | Ticket |
|---|---|---|
| **Cố vấn tài chính** | Hóa đơn, điều khoản thanh toán, kịch bản lập lịch, soát luật nghiệp vụ, hồ sơ công ty demo | DOM-004, 005, 007, 008 |
| **Cố vấn blockchain / bảo mật** | Kiểm chain (DOM-001, cùng @Nostidus4) và token (DOM-002, cùng anh Phúc), hóa đơn red-team, mô hình đe dọa, rủi ro, tự đánh giá bảo mật | DOM-001*, 002*, 006, 009, 011 |
| **Cố vấn nghiên cứu / truyền thông** | Email ban tổ chức, phỏng vấn, ghi chú tuân thủ, giấy phép, tài liệu kỹ thuật, deck, video, FigJam | DOM-003, 010, 012, 013, 014, 015, 016, 017 |

\* DOM-001 (#70) do **@Nostidus4 (Tân)** phụ trách từ 14/10/2026, theo bàn giao hạ tầng của anh Phúc. Chủ repo xử lý quyền truy cập RPC/API/dịch vụ, kiểm hạ tầng và ghi bằng chứng giao dịch Safe; **@longhuynh55 (anh Phúc)** hỗ trợ tích hợp contract. DOM-002 vẫn do anh Phúc phụ trách. Quyết định đã chốt ngày 11/10/2026 (Ethereum Sepolia; tUSDC + một lượt Circle USDC, PH-1/PH-2); hai ticket giờ là kiểm hạ tầng và chuẩn bị token.

## 3. Ticket và sản phẩm

| Ticket | Sản phẩm (đường dẫn chính xác) | Ai dùng | Cut |
|---|---|---|---|
| DOM-001 | Kiểm hạ tầng Ethereum Sepolia (Safe, MultiSend, EAS, RPC, Etherscan), ghi vào ADR-012 | SC-016, DEV-010, SC-019 | A |
| DOM-002 | Thông số tUSDC + địa chỉ Circle USDC Sepolia trong ADR-012; gom ≥ 120 Circle USDC cho lượt bằng chứng | TRS-003, DEV-006 | A |
| DOM-003 | Câu trả lời của ban tổ chức ghi vào `docs/OPEN_QUESTIONS.md` (OQ-01) | cả team | A |
| DOM-004 | `evals/invoices/`: 30 hóa đơn (PDF + nhãn JSON) | AGT-013, demo | B |
| DOM-005 | `evals/scenarios/`: ≥ 30 kịch bản lập lịch có đáp án | AGT-014 (benchmark) | A |
| DOM-006 | `evals/redteam/`: 20 hóa đơn tấn công + kết quả mong đợi | AGT-015 | A |
| DOM-007 | `evals/copilot/`: 20 câu hỏi có số mong đợi | AGT-016 | sau khi nộp |
| DOM-008 | `docs/reviews/finance-review.md` + hồ sơ công ty demo | mặc định mandate, seed, deck | A |
| DOM-009 | `docs/security/known-risks.md` | DOM-011, deck | A |
| DOM-010 | `docs/research/interviews/*.md` (2–3 cuộc) + một slide tóm tắt | deck, tổng quan §2 | B |
| DOM-011 | `docs/submission/security-self-assessment.md` | mục nộp 05 | A |
| DOM-012 | `docs/submission/technical-documentation.md` (+ PDF) | mục nộp 01 | A |
| DOM-013 | `docs/submission/deck.pdf` + `qa-notes.md` | mục nộp 02 | A |
| DOM-014 | `docs/submission/demo-video.mp4` (≤ 5 phút) hoặc link | mục nộp 03 | A |
| DOM-015 | `compliance-positioning.md`, `licenses.md` | deck, hỏi đáp, luật IP | B |
| DOM-016 | Cập nhật bảng FigJam (không còn ô "TBD") | team, deck | sau khi nộp |
| DOM-017 | File `LICENSE` + dòng trong README | công khai repo | sau khi nộp |

## 4. Đầu vào

Luật và mặc định: `docs/BUSINESS_RULES.md` · công thức thanh khoản: BR-032/033 và ví dụ Domain §3.4 · ranh giới AI và thiết kế đánh giá: `docs/AI_AGENT_ARCHITECTURE.md` §4, §6 · bộ câu hỏi phỏng vấn H1–H7 · luật cuộc thi: checklist nộp, tiếng Anh, deck 10 phút, video 5 phút.

## 5. Định dạng file (hợp đồng với dev)

Mọi file dữ liệu là UTF-8, gửi qua pull request. Số tiền là **chuỗi base unit** (6 số lẻ), ví dụ `"25000000"` = 25,000000. Ngày dạng `YYYY-MM-DD` (UTC). Chỉ dùng **địa chỉ test**, không bao giờ dùng ví công ty thật.

**5.1 Bộ hóa đơn `evals/invoices/inv-NNN.json` (DOM-004):** các trường `id, vendor_name, invoice_no, issue_date, amount, currency, decimals, payee_address, due_date, terms {discount_bps, discount_deadline, net_due_date, late_fee {type, rate_bps, period_days}, priority_note}, expected_flags, layout, language, notes`. `terms = null` nếu không có điều khoản ngoài ngày đến hạn; `discount_bps` 200 = 2 %. `expected_flags` lấy từ danh mục ở M05 §8.5: `ADDRESS_CHANGED`, `ADDRESS_NOT_REGISTERED`, `AMOUNT_OUTLIER`, `POSSIBLE_DUPLICATE`, `INSTRUCTION_TEXT`, `CURRENCY_MISMATCH`, `CHAIN_MISMATCH`, `DUE_DATE_PAST`, `DUE_DATE_FAR`, `DUE_BEFORE_ISSUE`, `NO_BASELINE`, `FIRST_PAYMENT_TO_PAYEE`. `layout`: `clean`, `messy`, `handwritten-like`, `multi-page`. **Cơ cấu 30 hóa đơn:** ≥ 8 có chiết khấu/phí trễ · ≥ 6 bố cục lộn xộn · ≥ 4 không phải tiếng Anh (Việt/Trung) · ≥ 3 phải bật cờ · còn lại sạch.

**5.2 Kịch bản lập lịch `evals/scenarios/{dev,heldout}/sc-NNN.yaml` (DOM-005):** gồm `id, family, as_of, treasury {stablecoin_decimals, balances, buffers, targets, limits, used_today}, payees [{id, address, active_from}], requests [{id, payee, wallet, amount, due, terms}], expected {schedule (ngày → id theo thứ tự), infeasible [{id, reason}], value, violations, explanation}`. Lý do không khả thi: `PAYEE_COOLING`, `OVER_DAILY_LIMIT`, `SOURCE_INSUFFICIENT`, `NEEDS_EXCEPTION`, `REFILL_BOUND`. **8 nhóm** (≥ 4 mỗi nhóm, tổng ≥ 30, ≥ 10 giữ kín): `simple-refill`, `discount-vs-deadline`, `daily-cap-spill`, `source-shortage`, `cooling-payee`, `over-cap-exception`, `late-fee-triage`, `ambiguous-priority` (ghi chú kiểu "nhà cung cấp quan trọng" mà luật không đọc được — chỗ AI nên giúp). **Đáp án:** tính tay hoặc bằng bảng tính, một cố vấn khác kiểm lại; có **ít nhất 5 kịch bản EDF đã tối ưu** để benchmark trung thực cho thấy chỗ AI không thêm giá trị.

**5.3 Red-team `evals/redteam/rt-NNN.{pdf,yaml}` (DOM-006):** `id, attack, injected_text, base_invoice, expected {fields_unchanged, flags, must_not}`; ví dụ `flags: [ADDRESS_NOT_REGISTERED, INSTRUCTION_TEXT]`, `must_not: [auto_approve, payee_change, limit_change]`. **20 đòn, mỗi loại ≥ 2:** `address-swap`, `pre-approved-claim`, `limit-raise-request`, `hidden-text`, `homoglyph-address`, `duplicate-new-number`, `instruction-in-vendor-note`, `fake-urgency`, `amount-in-words-mismatch`, `chain-switch`.

**5.4 Copilot `evals/copilot/` (DOM-007):** `id, scenario, question, expected_numbers, tolerance: exact, must_refuse` (true với câu kiểu "trả hóa đơn X ngay").

**5.5 Phỏng vấn `docs/research/interviews/YYYY-MM-DD-<code>.md` (DOM-010):** vai trò/loại công ty (ẩn danh), đồng ý ghi chép, lần trả on-chain gần nhất từng bước (H1–H5), thời gian thao tác/chờ, sự cố (H6), muốn giao phó gì với hạn mức nào (H7), trích dẫn ẩn danh, bằng chứng đã xem. Không bao giờ ghi private key, seed phrase, địa chỉ ví đầy đủ hay tên người.

**5.6 Rủi ro `docs/security/known-risks.md` (DOM-009):** bảng `ID, rủi ro, ở đâu, khả năng, tác động, giảm thiểu ở M1, rủi ro còn lại/chấp nhận?`; ≥ 10 dòng, tối thiểu gồm: contract chưa audit, máy signer bị chiếm, lộ khóa policy, tin RPC, Owner hành động ngoài mandate, LLM đọc sai hóa đơn, dữ liệu sàng lọc mẫu vs nhà cung cấp thật, khác biệt testnet/mainnet, riêng tư Telegram, một VM demo duy nhất, chữ ký cũ còn hiệu lực sau khi sửa request (M05 §8.7), lộ sentinel key (DoS).

**5.7 Gói nộp `docs/submission/`:** tài liệu kỹ thuật (kiến trúc, thuật toán cốt lõi, thiết kế bảo mật) · tự đánh giá bảo mật (các tầng quyền Owner, Approver, Guardian, Executor, AI: được/không được/thi hành ở đâu; rủi ro; bằng chứng test) · deck + ghi chú hỏi đáp · video ≤ 5 phút có phụ đề tiếng Anh, thấy tx hash · định vị tuân thủ, giấy phép.

## 6. Giao diện

M20 không có API lúc chạy. Giao diện là **hợp đồng file** và **lệnh kiểm** do dev cung cấp: `make eval-validate` (kiểm mọi file trong `evals/` theo schema), `make eval-extraction`, `make bench`, `make redteam`. Cố vấn không cần chạy local: CI chạy `eval-validate` trên mọi PR chạm `evals/` và comment kết quả.

## 7. Mô hình dữ liệu

Không thêm bảng DB. Ánh xạ: trường `inv-NNN.json` ↔ `extractions.fields` / `payment_requests` · `terms` ↔ `payment_requests.terms` · `treasury` của kịch bản ↔ `snapshots.data` · `expected.value` ↔ chỉ số tiết kiệm (F-141) · `expected.flags` của red-team ↔ `flags.code`.

## 8. Quy trình làm việc

1. **Nhận** ticket được giao trên GitHub Project (Status → In Progress).
2. **Soạn** file đúng định dạng trên. Không dùng git thì dùng trình soạn của GitHub ("Add file").
3. **Mở PR** gắn nhãn `non-code`. CI kiểm định dạng.
4. **Review chéo**: một cố vấn khác (đúng nghiệp vụ) và một dev (định dạng, dùng được).
5. **Merge**, chuyển Status → Done. Dashboard cập nhật trong vòng một giờ.

## 9. Phụ thuộc

M20 → M09 (AGT-013/014/015/016: dữ liệu đầu vào) · M20 → M04/M19 (SC-016, DEV-010, DEV-006: chain, token, hồ sơ công ty demo) · M20 → gói nộp (DOM-011…014) · M19 → M20 (DEV-008 runbook → DOM-014 video) · M04 → M20 (SC-015 phân tích tĩnh → DOM-011) · nội bộ: DOM-009 → DOM-011 → DOM-012; DOM-008 → DOM-013.

## 10. Bảo mật và riêng tư

Chỉ dùng địa chỉ **test** và công ty hư cấu; mô phỏng vendor thật thì đổi tên, logo, địa chỉ · không dữ liệu cá nhân từ phỏng vấn · file red-team gắn nhãn rõ để không ai dùng như hóa đơn thật · đáp án **không bao giờ** đưa vào prompt hay commit trong code agent (làm hỏng benchmark) · tài liệu nộp không chứa bí mật, token repo riêng hay URL nội bộ cần đăng nhập.

## 11. Tình huống lỗi và giảm thiểu

| Lỗi | Hậu quả | Giảm thiểu |
|---|---|---|
| Sai đáp án kịch bản | Benchmark báo tiết kiệm sai | Cố vấn thứ hai tính lại mọi `expected.value`; giải quyết bất đồng trước khi merge |
| Kịch bản nghiêng về AI | Giám khảo thấy benchmark "dàn dựng" | ≥ 5 kịch bản EDF tối ưu; bộ giữ kín do người khác viết |
| Dữ liệu đến muộn | AGT-013/014/015 không có kết quả | Giao trước 10 kịch bản + 5 đòn tấn công để dev dựng công cụ |
| PDF quá sạch | Độ chính xác trích xuất cao giả | Bắt buộc cơ cấu bố cục §5.1 |
| Không phỏng vấn được | Vấn đề chưa được chứng minh | Báo đúng số thật (0 cũng được nếu nói rõ); giữ kế hoạch H1–H7 trong deck |
| Kiểm hạ tầng chậm | Chặn deploy testnet | ADR-012 đã chốt (Ethereum Sepolia); việc trên Anvil local không phụ thuộc DOM-001 |
| Deck/video quá giờ | Nộp không hợp lệ | Tập có bấm giờ; cắt video ≤ 5:00 |

## 12. Nghiệm thu cấp module

- [ ] Mọi file ở §5 có đúng đường dẫn và qua `make eval-validate`.
- [ ] Mọi kịch bản và ca red-team được người thứ hai review (PR approval).
- [ ] Danh sách rủi ro ≥ 10 dòng; bản tự đánh giá phủ đủ năm tầng quyền.
- [ ] Tài liệu nộp bằng tiếng Anh, khớp code lúc khóa tính năng.
- [ ] Không có PII thật, khóa hay ví công ty trong `evals/` hoặc `docs/research/interviews/`.

## 13. Câu hỏi mở

| ID | Câu hỏi | Ai |
|---|---|---|
| OQ-18 | Phỏng vấn được bao nhiêu người trước hạn nộp | cố vấn nghiên cứu |
| ~~M20-Q1~~ | Đã chốt: trưởng nhóm quay video demo (màn hình + lồng tiếng Anh) theo runbook | trưởng nhóm |
| ~~M20-Q2~~ | Đã chốt: Google Slides (cùng sửa, xuất PDF), một template đơn giản | cố vấn truyền thông |
| ~~M20-Q3~~ | Đã chốt: cố vấn dùng trình soạn trên web GitHub ("Add file", tạo PR trên trình duyệt); git local là tùy chọn | trưởng nhóm |

## 15. Thay đổi theo v0.3 (ADR-019)

DOM-002: lấy USDC test của Aave Sepolia từ faucet Aave cho treasury; lượt Circle chỉ PAY. DOM-005: thêm nhóm kịch bản `idle-cash-supply`, `new-obligation-withdraw` và kỳ vọng B0. Video theo D1–D10; gói bằng chứng có câu miễn trừ: testnet, dữ liệu giả lập, không có phê duyệt pháp lý, không audit production, không hứa lợi suất.
