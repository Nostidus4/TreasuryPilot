# GuardianAI vs TreasuryPilot: Điểm mạnh & Điểm yếu

**Ngày:** 10/10/2026 · **Cuộc thi:** FinTechathon 2026, International Track, Topic F (Agent Wallet)
**Căn cứ:** `GuardianAI.pdf` (bản 0.1, 44 trang), `TreasuryPilot.md` (bộ 0.2), thể lệ PBCSF Appendix 2.
**Quy ước trích dẫn:** *GA p.X* là trang PDF GuardianAI. *TP [tài liệu con] §X* là mục trong TreasuryPilot.

> Cả hai dự án hiện **chỉ là tài liệu, chưa có source code**. "Điểm mạnh" dưới đây là điểm mạnh của *thiết kế*, chưa phải kết quả đã chứng minh.

---

## Tóm tắt nhanh

| | GuardianAI | TreasuryPilot |
|---|---|---|
| Một câu mô tả | Lớp bảo vệ cho ví on-chain có AI agent: chặn trước khi thực thi, quét quyền cũ, phát hiện chuỗi rủi ro nhiều bước, tự revoke/pause trong quyền được cấp | Agent điều phối quỹ vận hành: tự nạp tiền từ ví quỹ sang ví chi và trả các hóa đơn đã được người duyệt, trong mandate do smart contract enforce |
| Vai trò của AI | Người bảo vệ (risk control) | Người vận hành quỹ (asset management + execution + risk control) |
| Điểm ước tính (base) | ~70,5 / 100 | ~72 / 100 |
| Mạnh nhất ở | Security & Innovation | Task Completion |
| Yếu nhất ở | Task Completion, scope quá lớn | Innovation (vai trò AI mỏng) |

---

## 1. GuardianAI

### 1.1 Điểm mạnh

| # | Điểm mạnh | Bằng chứng |
|---|---|---|
| S1 | **Threat model sâu và trung thực.** 10 mối đe dọa đều có cột "rủi ro còn lại", không tuyên bố bảo vệ tuyệt đối | *GA p.30–31* |
| S2 | **10 invariant bảo mật rõ ràng, test được.** Ví dụ: AI không giữ khóa owner; response không được tăng allowance hay chuyển tài sản; policy đổi thì counter không reset | *GA p.31* |
| S3 | **Ba miền quyền tách biệt** (governance / business / response). Khóa response chỉ được `approve(spender, 0)` hoặc pause, không thể rút tiền. Đây là kiến trúc giới hạn thiệt hại rất tốt | *GA p.20–23* |
| S4 | **AI bị khóa chặt:** 7 tool chỉ đọc hoặc đề xuất, không có `sign_anything`, raw tx hay shell. Có đường fallback rule-based khi AI timeout | *GA p.24–25* |
| S5 | **Phòng prompt injection theo OWASP:** tách dữ liệu khỏi chỉ thị, schema đầu ra, hard validator | *GA p.25* |
| S6 | **Kết quả có ba chiều:** decision × severity × coverage. Không biến "không biết" thành "an toàn"; không dùng security score 0–100 thiếu cơ sở | *GA p.5, p.32* |
| S7 | **Attestation EIP-712** gắn `planHash`, `policyVersion`, nonce, expiry, executor, chống payload bị đổi sau khi duyệt | *GA p.21–22* |
| S8 | **Phục hồi lỗi rất chi tiết:** UNKNOWN, idempotency 3 lớp, nonce/replacement, PARTIALLY_MITIGATED, reorg | *GA p.20, p.29–30* |
| S9 | **Có ý tưởng khác biệt thật:** phát hiện rủi ro theo *vòng đời quyền* (MS01 quyền còn sót sau workflow, MS02 tín hiệu rủi ro mới, MS03 plan drift), không chỉ kiểm tra từng giao dịch | *GA p.17–18* |
| S10 | **Kỷ luật đánh giá AI tốt:** bắt buộc so sánh với B0 (stateless) và B1 (stateful rule-based); nếu AI không hơn thì thu hẹp vai trò AI | *GA p.3, p.38* |
| S11 | **Tài liệu kỹ thuật gần như sẵn sàng cho Dev:** 12 component có function signature, API endpoint, data model, cấu trúc repo, 37 acceptance test, Definition of Done | *GA p.10–14, p.26–28, p.33–37, p.41* |
| S12 | **Rủi ro pháp lý thấp:** là công cụ bảo mật, không phải dịch vụ thanh toán stablecoin | Suy luận |

### 1.2 Điểm yếu

| # | Điểm yếu | Bằng chứng / hệ quả |
|---|---|---|
| W1 | **Tác vụ tài chính chỉ là thứ yếu.** Payment dùng token fixture (không phải stablecoin) và router fixture tự viết. Dễ mất điểm ở Task Completion (40%) và chủ đề "AI as a Financial Participant" | *GA p.6, p.15* |
| W2 | **Thiếu asset management**, một trong ba năng lực mà Topic F nêu | Thể lệ p.2 |
| W3 | **Không chặn được vector tấn công lớn nhất trên thực tế** là permit ký off-chain. Scan không thấy chữ ký chưa gửi; revoke không vô hiệu permit còn hiệu lực. P0 chỉ "phân tích fixture" | *GA p.5–6* |
| W4 | **Tấn công, risk feed và workflow đều do đội tự dựng**, nên precision/recall dễ bị xem là "tự đề tự giải". Tài liệu cũng thừa nhận kết quả fixture không chứng minh hiệu quả ngoài thực tế | *GA p.39, D09 p.40* |
| W5 | **Scope rất lớn so với 10 ngày:** 12 component, 37 acceptance test, benchmark 60 ca, 7 mốc M0–M6. Tài liệu từ chối ước lượng lịch | *GA p.34* |
| W6 | **Cắt phạm vi là mất khác biệt.** Bỏ MS01–MS03 và AI thì sản phẩm gần giống Revoke.cash + spending limit (Coinbase Agentic Wallets, Zodiac Roles) | Nghiên cứu thị trường |
| W7 | **Review signer là điểm tin cậy đơn lẻ:** bị chiếm thì kẻ tấn công thực thi được mọi thứ còn trong hard limit | *GA p.22* |
| W8 | **Phụ thuộc nặng vào Safe module path** (`execTransactionFromModule`, ngữ cảnh caller khi approve). Rất dễ viết sai; nếu hỏng thì không còn enforcement | *GA p.20, p.23* |
| W9 | **Không có ICP, khách hàng hay mô hình kinh doanh.** Harpie, một firewall ví cùng hướng, đã ngừng hoạt động 03/2025 | *GA p.2*; CB Insights |
| W10 | **Đối thủ mạnh và đã có sẵn:** Blockaid (tích hợp MetaMask, gọi vốn $83M), Hypernative (200+ khách hàng), Revoke.cash, Coinbase Agentic Wallets (spending limit + KYT) | Nghiên cứu thị trường |
| W11 | **Demo cần nhiều giải thích nền** (ERC-20 allowance, permit, Safe module), khó vừa 10 phút với giám khảo là chuyên gia ngân hàng | Suy luận |
| W12 | **Tài liệu viết bằng tiếng Việt**, phải viết lại sang tiếng Anh | Thể lệ p.3 |

---

## 2. TreasuryPilot

### 2.1 Điểm mạnh

| # | Điểm mạnh | Bằng chứng |
|---|---|---|
| S1 | **Khớp chủ đề nhất:** AI thực sự làm một công việc tài chính (trả hóa đơn đúng hạn) và chạm cả ba năng lực của Topic F | *TP Memo §4*; Thể lệ p.2 |
| S2 | **Workflow end-to-end rõ ràng, nhiều tx hash:** duyệt → tính thiếu hụt → refill → pay → xác nhận → đối soát | *TP Use-Case UC-02, UC-03* |
| S3 | **Tách "có chi hay không" (con người) khỏi "chi như thế nào" (agent).** Mô hình maker-checker mà giám khảo ngân hàng hiểu ngay | *TP Problem Statement §4* |
| S4 | **Ba điều kiện cho phép chi phải thỏa đồng thời:** bản duyệt AND mandate còn hiệu lực AND ràng buộc của bước hiện tại | *TP Domain §4* |
| S5 | **Kiểm soát tài chính chặt:** trần mỗi khoản, trần ngày theo UTC tính trên toàn treasury (không reset khi đổi ví hay version, chống split), buffer tối thiểu, chống replay | *TP Domain §5.1*, R3, R6 |
| S6 | **Ngoại lệ một lần được thiết kế kỹ:** gắn đúng request, amount, payee, nonce; vẫn không vượt được trần ngày | *TP Domain §6.1*, UC-06 |
| S7 | **Blast radius nhỏ:** executor bị chiếm vẫn không trả được khoản chưa có bản duyệt (R1); tối đa chỉ refill nội bộ trong trần | *TP Use-Case R1* |
| S8 | **Công thức thanh khoản xác định, kiểm thử được:** Shortage, PreferredRefill, SourceCapacity, có ví dụ số cụ thể. LLM không tính tiền | *TP Domain §3* |
| S9 | **Phòng prompt injection trong invoice:** invoice là dữ liệu không tin cậy; có test AT-09 và AD-01 | *TP Use-Case §2*, AT-09; *Autonomy* AD-01 |
| S10 | **Xử lý trạng thái bất định đúng cách:** Pending/Unknown không bị xem là thất bại; không trả lần hai; hoàn thành một phần được ghi rõ | R8, UC-04, AT-06, AT-07 |
| S11 | **Phân biệt `Paid` và `Matched`;** refill được phân loại là chuyển nội bộ, không phải chi phí | *TP Use-Case UC-03* |
| S12 | **Scope đã thu hẹp:** 1 chain, 1 stablecoin, 3 ví, 3 action; liệt kê rõ những gì nằm ngoài MVP. 13 acceptance test vừa sức | D4–D5; *TP Use-Case §6* |
| S13 | **Trung thực về bằng chứng:** gắn nhãn Fact, Evidence, Assumption, Still-unverified; có kế hoạch phỏng vấn H1–H7 | *TP Validation* |
| S14 | **Đúng xu hướng:** Ant International dùng AI trigger để tự nạp tài khoản trên Whale; Alipay AI Pay đạt 120 triệu giao dịch/tuần. Giám khảo Trung Quốc quen với hướng này | Nghiên cứu thị trường |

### 2.2 Điểm yếu

| # | Điểm yếu | Bằng chứng / hệ quả |
|---|---|---|
| W1 | **Vai trò AI mỏng.** Chính tài liệu thừa nhận "nhiều quyết định có thể giải bằng rule-based". Giám khảo sẽ hỏi "sao không viết cron script?". Đây là điểm yếu lớn nhất ở Innovation (30%) | *TP Autonomy §6* |
| W2 | **Ý tưởng refill tự động đã tồn tại** ở cấp tập đoàn (Ant International Whale, AI programmable triggers) | Forrester |
| W3 | **Swap trong MVP gần như vô nghĩa:** chỉ có một stablecoin nên swap chỉ dùng để mua gas; DEX trên testnet lại thiếu ổn định | *TP Domain §4.2* |
| W4 | **Hai phần khó dễ làm trễ tiến độ:** enforce reserve/hold on-chain và quote swap có chữ ký | *TP Domain §5.2, §5.3* |
| W5 | **Thiếu thiết kế kỹ thuật:** chưa chọn stack, smart account, chain; chưa có contract interface, API, data model, sơ đồ kiến trúc hay cấu trúc repo | Điểm mở O5; so với *GA p.26–33* |
| W6 | **Chưa có UI hay thiết kế tương tác,** nên phần "Interaction" của tiêu chí 30% đang trống | Không đề cập |
| W7 | **0 phỏng vấn khách hàng;** pain, adoption và willingness to pay đều chưa xác nhận | *TP Validation §7* |
| W8 | **Nhạy cảm pháp lý ở Trung Quốc:** PBOC (28/11/2025) coi hoạt động kinh doanh liên quan stablecoin ở đại lục là bất hợp pháp. Tài liệu chưa có phần định vị compliance hay AML/KYT | Nguồn thứ cấp (mexc) |
| W9 | **Nhiều điểm mở (O1–O8) chưa chốt.** Nếu cứ chờ "Finance/Product duyệt" thì sẽ mất ngày | *TP Mục lục §3* |
| W10 | **Chống trùng chưa đủ:** cùng một invoice nhập dưới hai ID khác nhau thì contract không chặn được (tài liệu tự nhận) | *TP Use-Case UC-04* |
| W11 | **Demo kém kịch tính** hơn cảnh "chặn tấn công" nếu không thiết kế có chủ đích | Suy luận |
| W12 | **Tài liệu viết bằng tiếng Việt**, phải viết lại sang tiếng Anh | Thể lệ p.3 |

---

## 3. So sánh theo tiêu chí chính thức

| Tiêu chí (trọng số) | GuardianAI | TreasuryPilot | Bên mạnh hơn |
|---|---|---|---|
| Task Completion (40%) | 6,0: payment fixture + revoke | 7,5: refill → pay → đối soát | **TreasuryPilot** |
| Security & Compliance (30%) | 8,5: threat model sâu nhất | 8,0: kiểm soát tài chính chặt nhất | GuardianAI (sát nút) |
| Innovation & Interaction (30%) | 7,0: temporal detection + bounded response | 6,0: AI mỏng, chưa có UI | GuardianAI |
| **Base Score** | **70,5** | **72,0** | TreasuryPilot (sát nút) |
| Rủi ro không làm xong trong 10 ngày | Cao | Trung bình | **TreasuryPilot** |

Điểm là ước tính của hội đồng, độ tin cậy thấp đến trung bình. Ban tổ chức không công bố tiêu chí con.

## 4. Kết luận

Chọn **TreasuryPilot**. Đồng thời đưa ba cơ chế mạnh nhất của GuardianAI vào nó: attestation gắn `planHash`/nonce/expiry, nhãn `coverage`, và evidence bundle. Kế hoạch nâng điểm nằm trong file `TreasuryPilot-Ke-hoach-nang-diem-80-90.md`.
