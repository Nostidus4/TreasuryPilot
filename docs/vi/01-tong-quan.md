# TreasuryPilot: Tổng quan dự án

**Trạng thái:** Đã qua cổng G1 · **Phiên bản:** 0.3 · **Ngày:** 10/10/2026
**Nguồn chuẩn:** repo GitHub `Nostidus4/TreasuryPilot`, file `docs/PROJECT_OVERVIEW.md` (bản tiếng Anh). Tab này là bản dịch tiếng Việt.

> **Một câu:** TreasuryPilot là AI vận hành quỹ, đảm bảo các hóa đơn *đã được duyệt* được trả đúng hạn. Nó điều chuyển tiền giữa các ví của chính công ty và thanh toán on-chain. Một mandate trên smart contract đảm bảo agent không bao giờ trả sai người, vượt ngân sách, hay chạm vào khoản dự phòng.

## 1. Dự án là gì?

**Sản phẩm.** TreasuryPilot là ứng dụng web có một lớp thực thi luật trên blockchain. Doanh nghiệp trả nhà cung cấp bằng stablecoin làm ba việc:
- kết nối các ví của công ty;
- đặt quy tắc chi một lần;
- duyệt hóa đơn.

AI agent làm phần còn lại:
- đọc hóa đơn, kể cả PDF lộn xộn, và trích điều khoản thanh toán;
- tính toán khi nào nên trả;
- chuyển tiền từ ví quỹ sang ví chi;
- trả nhà cung cấp on-chain;
- đối soát với hóa đơn.

**Ai dùng.**
- Người dùng chính: finance/treasury operator, founder và người duyệt tại các SME hoặc doanh nghiệp Web3 dùng stablecoin.
- Người dùng phụ: kế toán, kiểm toán viên, chủ sở hữu quan tâm bảo mật.

**Vì sao tồn tại.** Doanh nghiệp gặp hai vấn đề:
1. Tổng quỹ đủ nhưng ví chi lại thiếu đúng token hoặc gas, nên trước mỗi đợt chi phải có người chuyển tiền thủ công.
2. Muốn tự động hóa thì phải giao tiền cho một agent, trong khi prompt không phải là cơ chế kiểm soát.

TreasuryPilot tự động hóa công việc mà vẫn giữ quyền kiểm soát chứng minh được. **Con người quyết định *có* trả hay không. Agent quyết định *trả thế nào và khi nào*. Hợp đồng đảm bảo agent không làm được gì khác.**

**Khi nào dùng:**
- Hóa đơn nhà cung cấp đến: upload, CSV, sau này qua email hoặc API.
- Hóa đơn đã duyệt sắp đến hạn hoặc sắp hết cửa sổ chiết khấu.
- Ví chi sắp cạn trước các nghĩa vụ sắp tới.
- Có ngoại lệ: vượt trần, payee đổi địa chỉ, giao dịch bị kẹt, cần tạm dừng.
- Cuối tháng, khi kế toán cần khớp thanh toán với hóa đơn kèm bằng chứng.

## 2. Problem Statement (Người dùng → Tình huống → Vấn đề → Hậu quả)

Các phát biểu dưới đây là giả thuyết cần kiểm chứng (H1–H7 trong tài liệu gốc), trừ những chỗ ghi *(bằng chứng)*.

| # | Người dùng | Tình huống | Vấn đề | Hậu quả |
|---|---|---|---|---|
| P1 | Operator | Hóa đơn đã duyệt đến hạn; ví chi `O1` thiếu stablecoin hoặc gas, trong khi ví quỹ `T` còn nhiều | Phải kiểm tra số dư, tính thiếu hụt, chọn nguồn, chuyển tiền, chờ ký rồi mới trả, tất cả thủ công | Trả trễ, tốn giờ công mỗi đợt chi, dễ sai (sai số tiền, sai mạng, nạp trùng). *(Bằng chứng: case Request Finance – Whatever Digital trả hơn 40 contractor mỗi tháng; tài liệu Acurast ghi lỗi "có USDC nhưng thiếu gas")* |
| P2 | Founder/Owner | Muốn dùng agent hoặc script để tự động hóa thanh toán | Công cụ ủy quyền hiện có hạn chế: spending limits của Safe không giới hạn *người nhận* *(bằng chứng: tài liệu Safe)*; prompt không ngăn được agent trả cho địa chỉ độc hại | Hoặc vẫn ký từng bước (nút thắt còn nguyên), hoặc giao quyền quá rộng (rủi ro không giới hạn) |
| P3 | Người duyệt | Hóa đơn là PDF hoặc email chứa văn bản tự do | Kẻ gian đổi địa chỉ nhà cung cấp ("đã cập nhật ví"), chèn lệnh để điều khiển AI, hoặc nhập trùng hóa đơn dưới ID mới | Tiền đi sai địa chỉ và không đảo ngược được (lừa đảo đổi tài khoản nhà cung cấp/BEC) |
| P4 | Finance lead | Nhiều hóa đơn đã duyệt tranh nhau thanh khoản và ngân sách ngày; có hóa đơn chiết khấu "2/10 net 30", có hóa đơn phạt trễ | Chọn thứ tự thủ công bỏ qua điều khoản; luật "đến hạn sớm trả trước" bỏ sót tiền | Mất chiết khấu, bị phạt, phải xin ngoại lệ không cần thiết |
| P5 | Kế toán/Kiểm toán | Một khoản chi gồm refill, swap và payment | Ghép tx hash với hóa đơn thủ công; chuyển nội bộ bị hạch toán nhầm thành chi phí | Chốt sổ chậm, bằng chứng audit yếu |

**Vì sao giải pháp hiện có chưa đủ:**

| Giải pháp | Làm tốt | Khoảng trống TreasuryPilot nhắm tới |
|---|---|---|
| Request Finance | Hóa đơn, chi hàng loạt bằng crypto, kế toán | Không *chuẩn bị thanh khoản* giữa các ví; không có agent tự thực thi có giới hạn |
| Safe Spending Limits / Zodiac Roles | Giới hạn ủy quyền on-chain | Không gắn với *hóa đơn đã duyệt*; không có buffer, lập kế hoạch, đối soát |
| Coinbase Agentic Wallets | Ví cho agent, có trần chi và KYT | Không phải quy trình AP; không có maker-checker hay quyền gắn với hóa đơn |
| Fireblocks / Utila | Policy engine cho tổ chức | Đắt và phức tạp; không có AI lập kế hoạch theo điều khoản hóa đơn |
| Ant International Whale | AI tự nạp tiền cho quỹ nội bộ của Ant | Nội bộ một tập đoàn; không phải sản phẩm SME với mandate do chủ quỹ đặt |
| Script/cron | Rẻ, refill xác định | Không đọc điều khoản, không phát hiện gian lận, không giải thích, không xử lý ngoại lệ |

## 3. Tầm nhìn sản phẩm

**Hôm nay**, mọi bước đều thủ công, trải trên explorer, bảng tính và giao diện multisig: kiểm tra số dư → phát hiện thiếu → chọn nguồn → (swap/bridge) → chờ ký → refill → trả → đối soát.

**Với TreasuryPilot:**

| Bước | Ai làm |
|---|---|
| Cấu hình mandate một lần (ví, payee, hạn mức, buffer, thời hạn) | **Owner** ký on-chain |
| Nhận hóa đơn, trích trường, điều khoản và dấu hiệu bất thường | **AI** đề xuất; con người xác nhận bản so sánh |
| Duyệt *có trả* đúng hóa đơn này (số tiền, payee, tài sản, deadline) | **Approver** ký EIP-712 |
| Quyết định *khi nào, thứ tự nào*, refill bao nhiêu | **AI** đề xuất; **bộ tối ưu xác định và policy engine** tính và kiểm tra |
| Thực thi refill/swap/pay trong mandate | **Executor**; **contract** kiểm tra |
| Hóa đơn vượt trần | **AI** soạn yêu cầu; **Owner** cấp ngoại lệ một lần |
| Xác minh, đối soát, xuất file, ghi attestation | **Hệ thống**; **Finance** đánh dấu Matched |
| Tạm dừng / thu hồi | **Owner/Guardian**, bất kỳ lúc nào |

**Quyền của AI.** AI được quan sát, đề xuất, giải thích, và chọn trong các phương án *đã được kiểm tra hợp lệ*. AI **không bao giờ**:
- giữ khóa;
- tự tính số tiền dùng để chi;
- duyệt hóa đơn;
- sửa policy hoặc thêm payee;
- bỏ qua bất kỳ bước kiểm tra nào.

Mọi đầu ra của AI đi qua kiểm tra xác định, và contract là bên quyết định cuối cùng.

## 4. Người dùng mục tiêu

### Người dùng chính

| Persona | Mô tả | Mục tiêu | Nỗi sợ |
|---|---|---|---|
| **Mai, Treasury Operator** tại một Web3 SaaS 25 người | Chi lương contractor và nhà cung cấp hàng tuần bằng USDC qua 3 ví | Không trả trễ, bớt chuyển tiền thủ công | Trả trùng, trả sai địa chỉ |
| **Daniel, Founder/Owner** | Giữ khóa owner của Safe, đặt policy | Ủy quyền an toàn | Agent rút cạn quỹ |
| **Linh, Approver/Finance lead** | Duyệt hóa đơn | Duyệt nhanh mà tự tin, bắt được gian lận | Duyệt nhầm hóa đơn bị sửa |

### Người dùng phụ

Kế toán (xuất đối soát, hạch toán) · Kiểm toán viên (chỉ đọc bằng chứng) · Guardian (chỉ được tạm dừng) · OrgAdmin (quản lý thành viên).

### Doanh nghiệp / Đối tác (Later)

- PlatformAdmin của TreasuryPilot: không bao giờ chạm vào tiền khách.
- Các tích hợp: ERP/kế toán (Xero, QuickBooks, NetSuite), KYB/KYT, nền tảng thông báo, nhà phát hành stablecoin.

## 5. Các hành trình chính

1. **J1 – Onboarding & mandate:** OrgAdmin đăng ký → tạo tổ chức → mời thành viên, gán vai trò → Owner kết nối hoặc tạo Safe (T, O1, O2) → bật module TreasuryPilot → cấu hình mandate → ký kích hoạt on-chain → hệ thống chờ xác nhận, kiểm tra module (coverage) → **Active**.
2. **J2 – Thêm payee (chống gian lận):** Owner thêm địa chỉ → sàng lọc danh sách trừng phạt/chặn → bắt đầu **thời gian chờ** → hết thời gian chờ mới được trả. Đổi địa chỉ thì chu trình bắt đầu lại.
3. **J3 – Nhận hóa đơn → duyệt:** Operator upload PDF, nhập CSV hoặc nhập tay → AI trích trường và điều khoản, gắn cờ bất thường (địa chỉ khác lịch sử, số tiền lạ, trùng, lệnh chèn) → Operator xác nhận → Approver xem bản so sánh và cờ, ký EIP-712 đúng các trường → **Approved**, fingerprint được đăng ký.
4. **J4 – Agent tự lập kế hoạch và thực thi:** đến cửa sổ thực thi → đọc trạng thái mới → tính thiếu hụt → bộ lập lịch theo điều khoản và AI đề xuất thứ tự, kế hoạch kèm giải thích → policy engine kiểm tra (ALLOW / NEEDS_APPROVAL / BLOCK) → ký xác nhận kế hoạch → executor gửi từng bước REFILL → [SWAP] → PAY → contract kiểm tra lại mọi luật → sau mỗi bước xác nhận và đọc lại → **Paid** → đối soát.
5. **J5 – Ngoại lệ vượt trần:** NEEDS_APPROVAL → AI soạn yêu cầu kèm lý do → Owner ký ngoại lệ một lần gắn đúng hóa đơn → kiểm tra lại → tiếp tục J4. Trần ngày vẫn áp dụng.
6. **J6 – Phục hồi:** giao dịch pending/unknown hoặc executor bị sập → tra receipt và trạng thái contract theo *cùng* định danh → giữ nguyên hoặc tiếp tục, **không trả lần hai**. Hoàn thành một phần được báo rõ, không âm thầm hoàn tác.
7. **J7 – Dừng khẩn cấp:** Guardian/Owner tạm dừng, hoặc circuit breaker tự dừng → backend ngừng gửi ngay → có hiệu lực on-chain sau xác nhận → giao dịch đã xong không bị đảo ngược → chỉ Owner được chạy lại.
8. **J8 – Đối soát & audit:** Finance mở màn hình đối soát (hóa đơn ↔ tx ↔ phí ↔ phân loại) → đánh dấu **Matched** hoặc ghi chênh lệch → xuất CSV/bút toán và gói bằng chứng → (tùy chọn) ghi attestation on-chain.
9. **J9 – Copilot "nếu… thì sao":** Owner hỏi "Tuần này trả hết được không mà không phá buffer?" → Copilot chạy mô phỏng (chỉ đọc) → trả lời bằng số liệu, kế hoạch đề xuất và các ràng buộc đang chặn.
10. **J10 – Thông báo:** cần duyệt, có ngoại lệ, đã trả, đã tạm dừng, có bất thường → báo trong app và qua Telegram, kèm link mở app để ký.

## 6. Giá trị đề xuất

| Thay vì… | TreasuryPilot mang lại… | Bằng chứng sẽ trình bày |
|---|---|---|
| Tự chuyển tiền trước mỗi đợt chi | Refill và trả tự động trong mandate | Tx hash; số phút thao tác và số lần can thiệp mỗi đợt |
| Tin script hoặc agent mù quáng | Luật do contract thực thi: payee allowlist + thời gian chờ, trần mỗi khoản/ngày, buffer, chống replay, pause | Invariant/fuzz test; revert on-chain khi cố vượt quyền |
| "Đến hạn sớm trả trước" | Lập lịch theo điều khoản, lấy chiết khấu và tránh phạt trong giới hạn thanh khoản | So sánh B1 (rule) và B2 (AI) bằng số stablecoin tiết kiệm |
| Duyệt hóa đơn mù | Bản so sánh kèm dấu hiệu gian lận (đổi địa chỉ, trùng, lệnh chèn) | Kết quả bộ red-team |
| Đối soát bằng bảng tính | Tự liên kết hóa đơn ↔ tx ↔ phí, phân loại chuyển nội bộ, xuất file, attestation | File CSV và gói bằng chứng |

**Cam kết giới hạn thiệt hại:** dù khóa executor bị lộ, kẻ tấn công cũng không thể:
- trả bất kỳ hóa đơn nào chưa có chữ ký người duyệt;
- trả cho payee chưa đăng ký hoặc đang trong thời gian chờ;
- vượt trần ngày.

Tiền chỉ có thể di chuyển giữa các ví của chính công ty, trong giới hạn.

## 7. Phạm vi sản phẩm

Danh sách đầy đủ ở tab **2. Feature**.

- **Năng lực lõi:** thực thi trong mandate (REFILL, PAY, SWAP) · vòng đời hóa đơn đã duyệt · tính thanh khoản và refill · lập lịch theo điều khoản · ngoại lệ một lần · pause/revoke · đối soát.
- **Năng lực hỗ trợ:** nhận hóa đơn (tay, PDF, CSV; email/API sau) · danh bạ payee có thời gian chờ · fingerprint chống trùng · dự báo thanh khoản · xuất đối soát · thông báo (app, Telegram; email/webhook/chat sau).
- **Nền tảng:** đa tổ chức · mô hình nhiều treasury, sẵn sàng đa chain · danh mục tài sản · signer service · điều phối job · billing (sau) · DevEx (môi trường một lệnh, CI, scenario runner).
- **AI:** đọc hóa đơn (trích trường, điều khoản, cờ bất thường) · đề xuất và giải thích kế hoạch · soạn yêu cầu ngoại lệ · Copilot · chống prompt injection · fallback rule-based · bộ đánh giá B1/B2.
- **Quản trị:** OrgAdmin (thành viên, vai trò, maker-checker) · PlatformAdmin (tenant, cấu hình chain/RPC/tài sản) · trình sửa mandate.
- **Bảo mật / Tuân thủ:** thực thi mandate on-chain · duyệt EIP-712 và ký xác nhận kế hoạch · circuit breaker · sàng lọc trừng phạt (KYB/KYT/Travel Rule sau) · nhật ký audit nối hash · gói bằng chứng · nhãn mức bao phủ · tối thiểu hóa dữ liệu (chỉ hash lên chain).

**Không bao giờ làm (Non-goals):** đầu cơ · tối ưu lợi suất · cho vay · quản lý danh mục · giữ tiền của khách · trả hóa đơn chưa duyệt · agent tự mua dịch vụ · đảo ngược giao dịch đã xác nhận.

## 8. So sánh với FigJam board

Board đã thể hiện tốt J1, J4, J5, J6, J7. **Board chưa có:**
- nhận hóa đơn và AI đọc hóa đơn (J3);
- thời gian chờ payee (J2);
- fingerprint chống trùng;
- lập lịch theo điều khoản và chỉ số tiết kiệm;
- trigger theo deadline;
- ký xác nhận kế hoạch;
- Copilot (J9);
- thông báo (J10);
- xuất đối soát và attestation (J8);
- circuit breaker;
- sàng lọc trừng phạt;
- vai trò đa tổ chức;
- quản trị nền tảng.

Các ô "TBD" trên board (Authority Guard, RPC, Quote source, Swap router) sẽ được chốt trong ADR ở Phase 3.
