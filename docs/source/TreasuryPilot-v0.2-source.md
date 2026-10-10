# TreasuryPilot — Bộ Tài Liệu Tổng Hợp

**Bộ tài liệu:** 0.2 | Gộp từ 7 file MD (PDF memo là bản sinh từ Decision Memo nên không lặp lại).

## Mục lục

1. [TreasuryPilot: Mục Lục & Quyết Định Chung](#documentation-index)
2. [TreasuryPilot Project Decision Memo](#project-decision-memo)
3. [TreasuryPilot: Problem Validation & Current-State Workflow](#problem-validation-and-icp)
4. [TreasuryPilot: Problem Statement + Value Proposition](#problem-statement-and-value-proposition)
5. [TreasuryPilot: Use-Case Specification](#use-case-specification)
6. [TreasuryPilot: Treasury Domain & Delegated Mandate Specification](#treasury-domain-and-mandate-specification)
7. [TreasuryPilot: Autonomy & Decision Policy](#autonomy-and-decision-policy)

---

<a id="documentation-index"></a>

## TreasuryPilot: Mục Lục & Quyết Định Chung

**Bộ tài liệu:** 0.2 | **Ngày:** 09/10/2026 | **Trạng thái:** Bản nháp đã đồng bộ, chưa phải đặc tả đã duyệt để triển khai tiền thật.

> TreasuryPilot điều phối quỹ vận hành và trả khoản chi đã được người có thẩm quyền duyệt, bằng quyền thực thi on-chain có giới hạn. Định hướng sản phẩm đã rõ; nhu cầu khách hàng và một số quy tắc nghiệp vụ vẫn cần xác nhận.

### 1. Thứ tự đọc và nguồn quyết định

| Thứ tự | Tài liệu | Nội dung làm căn cứ |
| --- | --- | --- |
| 1 | [Project Decision Memo](#project-decision-memo) | Tóm tắt định hướng, người dùng và phạm vi MVP. |
| 2 | [Problem Validation & ICP](#problem-validation-and-icp) | Nguồn bằng chứng, giả thuyết và workflow hiện tại; không suy dữ liệu khách hàng từ đặc tả. |
| 3 | [Problem Statement + Value Proposition](#problem-statement-and-value-proposition) | Vấn đề cần giải, giá trị cần đo và ranh giới sản phẩm. |
| 4 | [Use-Case Specification](#use-case-specification) | Luồng thực hiện, ngoại lệ, trạng thái và kịch bản nghiệm thu. |
| 5 | [Treasury Domain + Mandate](#treasury-domain-and-mandate-specification) | Định nghĩa, công thức, quyền và constraint cần enforce. |
| 6 | [Autonomy & Decision Policy](#autonomy-and-decision-policy) | Phân định AI/policy engine/executor/contract; mức tự chủ, fallback và lý do dừng. |

**Bản gửi nhanh:** [Decision Memo PDF một trang](#project-decision-memo), sinh từ bản MD cùng phiên bản.

**Phân công:** Product/Finance xác nhận nghiệp vụ; Dev xác nhận khả năng enforce. Memo là bản tóm tắt, không thay công thức hoặc quyền trong bản domain. Khi hai bản khác nhau, ghi vấn đề và cập nhật cùng nhau; không mặc định bản mới hơn hoặc chi tiết hơn tự động là quyết định đã duyệt.

### 2. Những điều đã thống nhất

| ID | Quyết định | Trạng thái |
| --- | --- | --- |
| D1 | Agent tự refill và trả khoản chi đã được người có thẩm quyền duyệt trước; không tự duyệt hoặc tạo nghĩa vụ chi. | Chủ dự án xác nhận. |
| D2 | Một stablecoin; hạn mức theo lượng token, gas có giới hạn riêng; không dùng hạn mức USD tổng qua oracle trong MVP. | Chủ dự án xác nhận. |
| D3 | Khoản vượt trần có thể được cấp quyền ngoại lệ một lần cho đúng request; không tự sửa mandate chung; payee chưa đăng ký vẫn bị chặn. | Chủ dự án xác nhận. |
| D4 | Một chain EVM, một ví quỹ `T`, hai ví vận hành `O1/O2`; `SWAP`, `REFILL`, `PAY`; nguồn refill là `T`. | Phạm vi MVP thống nhất trong bộ tài liệu. |
| D5 | Không bridge/multi-chain, đầu tư/lợi suất, vay, tự tạo kỳ chi từ recurring schedule hoặc trả invoice chưa duyệt. | Ngoài phạm vi MVP. |
| D6 | Khi AI không phản hồi, có thể dùng template rule-based đã kiểm thử nếu dữ liệu đầy đủ và mọi kiểm tra vẫn đạt; kết quả giao dịch chưa rõ hoặc cảnh báo an toàn vẫn phải dừng. | Chủ dự án xác nhận. |

**Từ dùng chung:** “Khoản chi đã duyệt” luôn là duyệt bởi người có thẩm quyền, không chỉ kiểm tra invoice đúng dữ liệu. `Policy` là các quy tắc nghiệp vụ; `Mandate` là quyền agent được cấp để thực hiện trong các quy tắc đó. Có bản duyệt và có mandate là hai điều kiện riêng.

### 3. Những điều chưa được chốt

| ID | Điểm mở | Phương án đề xuất | Ai xác nhận |
| --- | --- | --- | --- |
| O1 | Công thức refill và mức buffer/target | Công thức ở domain mục 3; chỉ refill theo khoản chi đã duyệt, target là mục tiêu mềm. | Finance/Product. |
| O2 | Phạm vi ngoại lệ | Chỉ vượt trần mỗi khoản; không vượt ngân sách ngày, reserve/buffer hay allowlist. | Finance/Product/chủ dự án. |
| O3 | Cửa sổ ngân sách ngày | Ngày UTC, không phải 24 giờ trượt; counter tổng treasury không reset khi đổi ví/version. | Finance/Product. |
| O4 | Các con số hạn mức | Số trong YAML/ví dụ chỉ dùng thảo luận và test; phải duyệt giá trị cấu hình trước kích hoạt. | Owner/Finance. |
| O5 | Chain, token, smart account, router và nguồn quote | Một EVM testnet trước; định danh asset cụ thể, adapter kiểm tra lời gọi, quote có bằng chứng xác minh. | Product/Dev; ban tổ chức xác nhận testnet. |
| O6 | Gas payer, gas funding cap, confirmation và retry | Gas khởi động có sẵn; trần cấp gas tách khỏi phí mạng thực tế; không retry payment khi kết quả cũ chưa rõ. | Finance/Dev. |
| O7 | Pain, adoption và giá trị thêm của AI | Kiểm chứng H1–H7; so với rule-based workflow và công cụ hiện có. | Product/research. |
| O8 | Quy tắc chọn kế hoạch và vận hành fallback | Deadline sớm trước, hòa thì theo thứ tự duyệt; chốt timeout AI và template/route fallback đã kiểm thử. | Product/Finance/Dev. |

### 4. Nguyên tắc xuyên suốt

- **Giả thuyết, không phải kết luận thị trường:** `Fragmented liquidity → manual treasury operations → need for bounded execution`. “Unsafe delegation to AI” là rào cản cần xử lý, chưa phải sự cố đã quan sát ở khách hàng.
- **Hard rule và mục tiêu mềm:** Quyền, ngân sách, buffer và nghĩa vụ đã đăng ký là ràng buộc; target không được dùng để phá chúng. Chi tiết đang đề xuất chỉ trở thành cấu hình thực thi sau duyệt.
- **On-chain thật:** Contract chuyển tài sản và kiểm tra quyền; backend/prompt không thay thế enforcement. Receipt/tx hash chứng minh từng bước; `Paid` khác `Matched` đối soát.
- **Giới hạn bảo vệ:** Chặn lặp request không tự nhận biết invoice trùng dưới ID khác; pause/revoke không đảo giao dịch đã xong; cấp gas có trần không bảo đảm chính xác mọi phí thực tế.
- **Research khác MVP:** Có thể nghiên cứu 8 ví/3 chain và bridge trong workflow cũ; MVP vẫn chỉ xử lý một chain và ba ví đã nêu.

### 5. Khi nào giao Dev triển khai?

Chỉ coi đặc tả là **đã duyệt triển khai** khi các quyết định ảnh hưởng quyền chi/công thức được ký duyệt, cấu hình bắt buộc đủ và Dev xác nhận đường enforce cùng bộ test. Có thể làm prototype/testnet có ghi rõ giả định; không coi prototype là bằng chứng nhu cầu hoặc giấy phép triển khai tiền thật.

Hiện chưa có phỏng vấn trực tiếp, chưa xác nhận product–market fit, khả năng triển khai tiền thật tại Trung Quốc đại lục hoặc điểm thi. Cập nhật một quyết định phải sửa tài liệu gốc, use case/test liên quan và memo nếu ảnh hưởng phạm vi; PDF memo luôn sinh từ bản MD hiện hành.

---

<a id="project-decision-memo"></a>

## TreasuryPilot Project Decision Memo

**Bản 0.2 | 09/10/2026 | Định hướng sản phẩm, chưa phải đặc tả đã duyệt triển khai.** Xây agent điều phối quỹ vận hành và thanh toán on-chain có giới hạn quyền cho doanh nghiệp đã dùng stablecoin. Trạng thái quyết định xem [Mục lục bộ tài liệu](#documentation-index).

### 1 Người dùng là ai

Finance/treasury operator hoặc founder tại stablecoin-native SME và Web3 business, đã có khoản chi on-chain lặp lại. MVP xử lý nhiều ví trên cùng một chain. Doanh nghiệp sở hữu tài sản; agent chỉ được cấp quyền thực thi. ICP cụ thể vẫn cần kiểm chứng.

### 2 Vấn đề cần giải quyết là gì

**Giả thuyết: Fragmented liquidity → manual treasury operations → need for bounded execution.** Tổng quỹ có thể đủ nhưng ví chi thiếu đúng asset/gas, buộc operator điều chuyển thủ công. “Unsafe delegation to AI” là rào cản tự động hóa, chưa phải sự cố khách hàng đã được quan sát.

### 3 Vì sao vấn đề đáng giải

Mục tiêu là giảm công sức xử lý thiếu hụt cục bộ và thanh toán trễ mà vẫn giữ quyền kiểm soát quỹ. Chưa có phỏng vấn trực tiếp hoặc số liệu lợi ích; phải đo pain và so với cảnh báo, multisig, script refill trước khi kết luận cần agent.

### 4 TreasuryPilot làm gì

Đọc số dư và khoản chi đã được người có thẩm quyền duyệt; lập kế hoạch giữ phần tiền được bảo vệ, refill từ ví quỹ, swap khi cần và pay on-chain trong quyền được cấp. Chỉ ghi đã trả sau xác nhận phù hợp; đối soát là trạng thái riêng. Thiếu quyền/nguồn hoặc chưa rõ kết quả thì dừng.

### 5 AI quyết định gì

AI đề xuất thứ tự và kế hoạch trong quyền cho phép, giải thích lựa chọn và chuyển ngoại lệ cho con người. Bộ tính toán xác định lượng tiền; contract kiểm tra quyền. AI không tự duyệt invoice, đổi người nhận/số tiền, nâng hạn mức hoặc sửa policy.

### 6 Blockchain làm gì

Contract ràng buộc mandate, bản duyệt, asset, payee, hạn mức, phần tiền bảo vệ và điều kiện quote; thực sự chuyển tài sản và chặn lặp request/bước. Receipt và tx hash phục vụ kiểm chứng. Trần cấp gas không phải bảo đảm mọi phí mạng thực tế; cơ chế enforce phải được Dev xác nhận.

### 7 Người dùng còn giữ quyền gì

Owner giữ quyền ví, duyệt nghĩa vụ chi, đặt/sửa policy, cấp quyền ngoại lệ một lần, pause hoặc revoke. Agent không cần chữ ký lại cho từng bước hợp lệ. Khóa owner không đưa vào LLM; revoke chặn quyền cũ sau hiệu lực on-chain, không đảo giao dịch đã xong. Phạm vi ngoại lệ chi tiết còn cần duyệt.

### 8 MVP phải chứng minh điều gì

Một chain EVM, một stablecoin và gas token, một ví quỹ và hai ví vận hành; hạn mức theo token, không phải USD. Chứng minh tự refill/swap/pay khoản đã duyệt, chặn vượt quyền/chống lặp và đối soát; đo hoàn thành, phí, can thiệp. Không bridge/đầu tư. Testnet cần ban tổ chức xác nhận; chưa bao gồm triển khai tiền thật tại Trung Quốc đại lục.

---

<a id="problem-validation-and-icp"></a>

## TreasuryPilot: Problem Validation & Current-State Workflow

**Bản:** 0.2 | **Ngày:** 09/10/2026 | **Trạng thái:** Research sơ bộ, chưa xác nhận pain/adoption.  
**Phương pháp:** Nguồn sơ cấp công khai | **Phỏng vấn trực tiếp:** 0. [Mục lục & quyết định chung](#documentation-index).

> **Kết luận hiện tại:** Có bằng chứng về thanh toán stablecoin, xử lý thủ công, phê duyệt và đối soát. Chưa đủ bằng chứng để kết luận phân mảnh thanh khoản là pain lớn của khách hàng mục tiêu, hoặc họ sẽ chấp nhận agent tự thực hiện giao dịch.

### 1. Vấn đề cần kiểm chứng

**Giả thuyết trung tâm:**

`Fragmented liquidity → manual treasury operations → need for bounded execution`

Diễn giải: doanh nghiệp có đủ tiền tổng thể nhưng tiền không nằm ở đúng ví, đúng chain hoặc đúng tài sản cần thanh toán. Operator phải kiểm tra, chọn nguồn tiền, chuyển đổi, xin phê duyệt và đối soát. Tự động hóa có thể giảm công việc này, nhưng chủ quỹ có thể không chấp nhận giao quyền chi nếu không kiểm soát được phạm vi hành động.

**Ba điều phải chứng minh riêng:** Vấn đề xảy ra thật; hậu quả đủ lớn để đáng giải; ủy quyền có giới hạn được chấp nhận. “Unsafe delegation to AI” là rào cản giải pháp, chưa phải sự cố đã quan sát. Có nhiều ví không tự động đồng nghĩa với có pain hoặc cần AI.

#### Quy ước bằng chứng

| Nhãn | Cách sử dụng |
| --- | --- |
| **Fact** | Thông tin có thể truy nguyên, chỉ phát biểu trong phạm vi nguồn hoặc trường hợp được quan sát. |
| **Evidence** | Nguồn, log, giao dịch, tài liệu hoặc lời kể cụ thể hỗ trợ Fact; ghi rõ nguồn và giới hạn. |
| **Assumption** | Giả định của team về ICP, nguyên nhân, mức độ pain hoặc giá trị giải pháp; chưa phải kết quả research. |
| **Still unverified** | Câu hỏi chưa có dữ liệu đủ để trả lời, kể cả khi đã có bằng chứng gián tiếp. |

### 2. Bằng chứng hiện có

| ID | Fact trong phạm vi nguồn | Evidence | Still unverified / giới hạn |
| --- | --- | --- | --- |
| E1 | Request Finance mô tả Whatever Digital, một agency châu Âu trả hơn 40 contractor mỗi tháng. Trước khi dùng giải pháp của họ, xử lý và đối soát mất hàng giờ, có thanh toán trễ hoặc thất bại. | [Case study Whatever Digital](https://www.requestfinance.com/customers/whatever-digital-influencer-payments), công bố 09/08/2026. | Case do nhà cung cấp công bố, chưa kiểm chứng độc lập. Không công bố số ví/chain; không chứng minh nguyên nhân là phân mảnh thanh khoản hay nhu cầu AI. |
| E2 | Circle mô tả quy trình treasury của chính mình có kiểm tra số dư, chuyển USDC, phê duyệt và đối chiếu với hệ thống kế toán. | [Circle Treasury Management](https://www.circle.com/case-studies/circle-treasury-management). | Doanh nghiệp lớn, không đại diện SME. Case nói về 8 pháp nhân, **không phải 8 ví**; chưa cung cấp thời gian đối soát của ICP. |
| E3 | Tài liệu Acurast hướng dẫn thanh toán dịch vụ bằng USDC trên Base và nêu lỗi thiếu tiền khi ví đủ USDC nhưng thiếu Base ETH cho gas. | [Acurast Deploy Agent: Troubleshooting](https://docs.acurast.com/developers/tools/deploy-agent/#troubleshooting). | Xác nhận một tình huống kỹ thuật có thật trong hệ thống này; không cho biết tần suất, tổn thất hoặc mức phổ biến trong doanh nghiệp. |
| E4 | Safe đã có spending limits cho phép spender chuyển token trong hạn mức mà không xin chữ ký owner mỗi lần. Proposer chỉ chuẩn bị giao dịch, không tự chuyển tài sản. | [Safe: Spending Limits and the Proposer Role](https://help.safe.global/articles/9640607537-spending-limits-and-the-proposer-role). | Spending limits này không giới hạn địa chỉ nhận và tính theo lượng token. Công cụ hiện có là phương án thay thế; chưa chứng minh khách hàng cần thêm TreasuryPilot. |

**Đánh giá:** E1–E2 hỗ trợ sự tồn tại của công việc treasury/payment; E3 hỗ trợ khả năng thiếu đúng tài sản; E4 hỗ trợ tính khả thi của ủy quyền có giới hạn. Chưa nguồn nào kiểm chứng đầy đủ chuỗi giả thuyết ở mục 1. Tài liệu kỹ thuật không phải bằng chứng về nhu cầu mua sản phẩm.

### 3. ICP ban đầu

#### ICP-01: Web3 SaaS có treasury vận hành bằng stablecoin

**Đây là hồ sơ giả định để tuyển người phỏng vấn, không phải khách hàng đã được xác minh.** Whatever Digital là trường hợp thực có tài liệu công khai gần với bài toán chi trả, nhưng không được coi là doanh nghiệp Web3 SaaS hay khách hàng của TreasuryPilot.

| Thuộc tính | Hồ sơ mục tiêu (Assumption) |
| --- | --- |
| Doanh nghiệp | Web3 SaaS nhận một phần doanh thu bằng USDC; đã có khoản chi on-chain lặp lại. |
| Người sử dụng | Finance/treasury operator; founder có thể kiêm nhiệm ở team nhỏ. |
| Người quyết định | Founder hoặc finance lead; người giữ quyền ký quyết định phạm vi ủy quyền. |
| Cấu trúc tiền | Ưu tiên nhiều ví trên cùng một chain để khớp MVP. Có thể khảo sát trường hợp 8 ví trên Base/Ethereum/Solana để hiểu bối cảnh rộng; số này chỉ minh họa, không phải yêu cầu sản phẩm. |
| Nhu cầu chi | Trả contractor/vendor định kỳ; chỉ tính API/dịch vụ hàng ngày nếu nhà cung cấp thực sự nhận thanh toán on-chain. |
| Công cụ hiện tại | Ví/multisig, explorer, bảng theo dõi khoản chi và phần mềm kế toán; phải xác nhận công cụ thực tế. |
| Sự kiện kích hoạt pain | Ví trả tiền thiếu tài sản trong khi ví khác còn tiền; operator phải xử lý trước hạn thanh toán. |

**Điều kiện tuyển:** Đã trực tiếp xử lý thanh toán on-chain trong 30 ngày gần nhất và có thể kể lại ít nhất một lần vận hành cụ thể, kể cả lần không gặp sự cố. Không tuyển chỉ vì họ quan tâm AI hoặc crypto.

**Ngoài ICP ban đầu:** SME chỉ dùng fiat; nhà đầu tư cá nhân; đơn vị chủ yếu đầu cơ/lợi suất; người chưa có workflow thanh toán thực tế.

**Ranh giới phạm vi:** Research có thể khảo sát nhiều chain để hiểu nguyên nhân. Điều đó không mở rộng MVP: trước mắt vẫn kiểm chứng một chain, một ví quỹ và hai ví vận hành theo [Project Decision Memo](#project-decision-memo).

### 4. Workflow hiện tại: Không có TreasuryPilot

**Workflow giả định, cần xác nhận bằng một lần vận hành gần nhất:**

`Check balances → detect shortage → choose source wallet → swap/bridge → wait approval → refill → pay → reconcile`

**Lưu ý thứ tự:** Swap/bridge chỉ xuất hiện khi cần. Phê duyệt phải diễn ra **trước mỗi giao dịch chi tiền** mà chính sách hiện tại yêu cầu, kể cả swap/bridge; bước “wait approval” trong sơ đồ là nút thắt tổng quát, không có nghĩa được chi trước rồi xin phép sau. Phê duyệt của con người khác với ERC-20 `approve` cấp quyền cho contract.

Thời gian chưa được đo. Với mỗi bước, ghi riêng **thời gian thao tác** và **thời gian chờ**; không dùng thời gian xác nhận blockchain làm đại diện cho công sức operator.

| Bước | Actor dự kiến | Time cần đo | Manual effort cần ghi | Risk | Failure mode cần kiểm chứng |
| --- | --- | --- | --- | --- | --- |
| 1. Check balances | Operator | Thao tác tra cứu | Số ví/chain phải mở; số lần nhập bảng | Dữ liệu thiếu hoặc cũ | Bỏ sót ví, đọc nhầm chain/token. |
| 2. Detect shortage | Operator | So khớp khoản chi | Tính số tiền thiếu, gas và dự phòng | Tổng tiền che khuất thiếu hụt cục bộ | Đủ tổng quỹ nhưng ví chi không thực hiện được. |
| 3. Choose source wallet | Operator / finance lead | Chọn nguồn; hỏi nội bộ | So sánh số dư và quyền dùng tiền | Dùng nhầm tiền đã dành cho nghĩa vụ khác | Ví nguồn xuống dưới dự phòng. |
| 4. Swap/bridge, nếu cần | Operator + signer | Chuẩn bị; chờ ký và xác nhận | Lấy báo giá, kiểm tra route, allowance | Phí, slippage, rủi ro bridge | Không đủ gas; chuyển sai mạng; route lỗi. |
| 5. Wait approval | Signer / owner | Chờ đủ chữ ký | Nhắc người ký; giải thích mục đích | Nút thắt phê duyệt | Người ký vắng; đề xuất bị từ chối hoặc hết hiệu lực. |
| 6. Refill | Operator + signer | Chuẩn bị; chờ xác nhận | Kiểm tra địa chỉ, số tiền và số dư đến | Sai địa chỉ hoặc lượng tiền | Ví nhận chưa được nạp; nạp trùng khi thử lại. |
| 7. Pay | Operator + signer | Thao tác; chờ kết quả | So invoice, người nhận và trạng thái | Sai người nhận hoặc trả trùng | Thanh toán thất bại; gửi lại khi giao dịch cũ còn pending. |
| 8. Reconcile | Finance / accountant | Đối chiếu; xử lý ngoại lệ | Ghép invoice với tx hash, phí và sổ kế toán | Sai hạch toán, thiếu bằng chứng | Chuyển nội bộ bị ghi thành chi phí; không khớp khoản chi. |

Tất cả actor, rủi ro và failure mode trên là mô hình nghiên cứu, chưa phải mô tả một khách hàng đã phỏng vấn. Giữ nguyên các bước được công cụ hiện tại tự động xử lý; không mặc định toàn bộ workflow đều thủ công.

### 5. Kế hoạch kiểm chứng và câu hỏi phỏng vấn

**Mẫu đề xuất:** 5–8 operator độc lập thuộc ICP; cố gắng có cả người dùng multisig và người đã tự động hóa. Đây là nghiên cứu định tính ban đầu, không đại diện thống kê cho toàn thị trường. Xin phép xem bằng chứng đã che thông tin nhạy cảm; không yêu cầu private key/seed phrase.

Mở đầu: **“Anh/chị hãy kể lại lần thanh toán on-chain gần nhất, từ lúc nhận yêu cầu đến lúc ghi nhận xong. Có thể dùng một lần diễn ra hoàn toàn bình thường.”** Sau đó đi theo các câu hỏi dưới đây, chưa giới thiệu giải pháp để tránh dẫn dắt.

| ID | Giả thuyết (Assumption) | Câu hỏi về hành vi thực tế | Evidence cần thu / Still unverified |
| --- | --- | --- | --- |
| H1 | Phân mảnh tiền gây thiếu hụt cục bộ | Lần đó dùng ví, chain và token nào? Tiền nằm ở đâu? Trong 30 ngày qua, bao nhiêu ví thực sự hoạt động? Vì sao cần tách ví? | Danh sách ví hoạt động theo mục đích; số dư tại thời điểm thiếu; phân biệt thiếu cục bộ với thiếu tiền toàn quỹ. |
| H2 | Kiểm tra số dư tốn công lặp lại | Lần gần nhất anh/chị kiểm tra lúc nào, do lịch hay do khoản chi? Tuần vừa rồi kiểm tra bao nhiêu lần? Công cụ nào tự cảnh báo? | Lịch sử/cảnh báo hoặc nhật ký một tuần; tần suất và số phút thao tác. |
| H3 | Refill/rebalance/swap xảy ra đủ thường xuyên | Cho xem lần gần nhất phải chuyển tiền giữa ví hoặc đổi tài sản. Trong 30 ngày qua có bao nhiêu lần, vì lý do gì? | Tx hash/log đã ẩn danh; đếm riêng refill, swap, bridge và payment, tránh tính một sự kiện thành nhiều pain độc lập. |
| H4 | Approval là nút thắt | Giao dịch đó cần ai ký, bao nhiêu chữ ký? Chờ từ lúc gửi đề xuất đến đủ chữ ký bao lâu? Có lần nào bỏ lỡ hạn vì chờ không? | Timestamp đề xuất/chữ ký; thời gian chờ; chính sách và ngoại lệ thật. |
| H5 | Reconciliation đáng kể | Lần gần nhất ghép một khoản chi với invoice/sổ kế toán mất bao lâu? Phải làm lại gì? Công cụ hiện tại đã xử lý phần nào? | Invoice, tx hash và bản ghi kế toán; phút thao tác, số ngoại lệ, phần đã tự động hóa. |
| H6 | Thiếu đúng tài sản gây hậu quả đáng giải | Kể lần gần nhất ví không trả được vì thiếu token/gas hoặc sai chain. Sau đó điều gì xảy ra? Có bằng chứng về trễ hạn, gián đoạn hay phí phát sinh không? | Log lỗi và hậu quả; nguyên nhân gốc, chi phí thực tế hoặc xác nhận chưa có thiệt hại. |
| H7 | Khách hàng chấp nhận ủy quyền có giới hạn | Hiện đã cho ai/công cụ nào tự chi? Lần gần nhất cấp hoặc từ chối quyền vì điều gì? Với workflow vừa kể, bước nào bắt buộc giữ chữ ký người? | Quyền đang dùng; điều kiện bắt buộc về hạn mức, người nhận, dự phòng và thu hồi. Ý kiến “có vẻ hữu ích” chưa xác nhận adoption. |

**Chỉ sau khi hiểu workflow:** Đề nghị operator tự đặt hard spending limits và phạm vi người nhận, rồi đánh giá các kế hoạch trên dữ liệu lịch sử, **không chuyển tiền**. Hỏi kế hoạch nào họ chấp nhận/từ chối và tại sao. Đồng ý thử nghiệm không đồng nghĩa với sẵn sàng cho chạy tự động bằng tiền thật hoặc sẵn sàng trả phí.

#### Phiếu ghi nhận một trường hợp

`Case ID | vai trò | ngày xảy ra | wallet/chain/asset | khoản chi | bước thực tế | phút thao tác | phút chờ | số lần phê duyệt | sự cố/nguyên nhân | hậu quả | công cụ thay thế | evidence | điều kiện ủy quyền`

- Gắn từng kết luận với Evidence ID; phân biệt **quan sát/log** với **lời kể chưa đối chiếu**.
- Một invoice có thể gắn nhiều giao dịch; chuyển nội bộ không phải chi trả bên ngoài. Đối chiếu theo sự kiện để tránh đếm trùng.
- Tính riêng tổng công sức, thời gian hoàn tất và phí. Không tự quy đổi thời gian thành tiền nếu chưa có cơ sở.
- Thu cả trường hợp không có pain và trường hợp công cụ hiện tại đã giải quyết tốt; không chỉ chọn câu chuyện ủng hộ sản phẩm.

### 6. Tiêu chí quyết định trước khi thiết kế

Các ngưỡng dưới đây là **quy tắc nội bộ đề xuất**, không phải kết quả nghiên cứu hoặc tiêu chuẩn cuộc thi.

| Quyết định | Điều kiện |
| --- | --- |
| **Tiếp tục discovery** | Hiện có bằng chứng gián tiếp, nhưng chưa có đủ dữ liệu operator để chốt sản phẩm. |
| **Đủ cơ sở thiết kế MVP hẹp** | Hoàn thành ít nhất 5 phỏng vấn; ít nhất 3 operator độc lập đưa được trường hợp gần đây về thiếu hụt cục bộ và thao tác xử lý lặp lại, có bằng chứng cùng công sức/hậu quả đáng giải theo họ; ít nhất 2 người đồng ý đánh giá kế hoạch trên dữ liệu lịch sử và nêu được phạm vi ủy quyền cụ thể. |
| **Thu hẹp hoặc đổi hướng** | Pain chính là kế toán/approval chứ không phải phân bổ tiền; khách hàng chỉ cần cảnh báo hoặc quy tắc refill cố định; Safe, phần mềm chi trả hoặc script hiện tại đã giải quyết đủ tốt. |
| **Không chốt autonomous execution** | Operator vẫn yêu cầu ký từng giao dịch, chưa chấp nhận chính sách ủy quyền hoặc thử nghiệm có kiểm soát. Khi đó chưa xác nhận giả thuyết adoption. |

Trước khi chốt MVP, trả lời thêm: **“Vì sao không dùng công cụ hiện tại hoặc quy tắc cố định?”** Chỉ giữ vai trò AI nếu dữ liệu cho thấy cần lựa chọn/ngữ cảnh mà phương án đơn giản hơn chưa đáp ứng tốt.

### 7. Kết luận theo trạng thái bằng chứng

- **Fact:** Nguồn công khai mô tả nghiệp vụ stablecoin treasury/payment, công việc thủ công và cơ chế ủy quyền có giới hạn trong những hệ thống cụ thể.
- **Evidence:** E1–E4; chưa có dữ liệu vận hành hoặc phỏng vấn khách hàng trực tiếp của TreasuryPilot.
- **Assumption:** ICP-01, cấu trúc 8 ví/3 chain và chuỗi phân mảnh tiền → thao tác thủ công → nhu cầu ủy quyền an toàn.
- **Still unverified:** Số ví/chain/asset điển hình, tần suất kiểm tra và điều chuyển, thời gian approval/đối soát, hậu quả thiếu tài sản, khả năng chấp nhận agent và mức sẵn sàng trả phí.

**Quyết định hiện tại:** Tiếp tục kiểm chứng ICP và pain. Các đặc tả sản phẩm là bản nháp có điều kiện, không thay thế research hoặc chứng minh problem–solution fit. Nguồn quốc tế không xác nhận khả năng triển khai tiền thật tại Trung Quốc đại lục.

**Đầu ra cho tài liệu tiếp theo:** Dùng H1–H7 để kiểm chứng [Problem Statement + Value Proposition](#problem-statement-and-value-proposition); cập nhật giả thuyết/giá trị khi có bằng chứng mới, không biến các số ví dụ trong đặc tả thành Fact.

---

<a id="problem-statement-and-value-proposition"></a>

## TreasuryPilot: Problem Statement + Value Proposition

**Bản:** 0.2 | **Ngày:** 09/10/2026 | **Trạng thái:** Định hướng sản phẩm, giá trị chưa được xác nhận với khách hàng. [Mục lục & quyết định chung](#documentation-index).

**Đã xác nhận với chủ dự án:** Agent tự nạp tiền và thanh toán khoản chi đã được người có thẩm quyền duyệt trước. Agent không tự tạo nghĩa vụ chi hoặc trả khoản chi chưa duyệt.

### 1. Problem Statement

> Người phụ trách quỹ vận hành tại doanh nghiệp Web3 đã thu và chi bằng stablecoin có thể phải điều chuyển tiền thủ công để thanh toán một khoản chi đã duyệt: tổng quỹ đủ, nhưng ví chi thiếu đúng token hoặc gas. Công việc kiểm tra, chọn nguồn, chuyển đổi, nạp tiền và xác nhận kết quả có thể gây chậm thanh toán và tăng công sức vận hành. Muốn tự động hóa, doanh nghiệp còn phải giải quyết việc giao quyền thực thi mà không mất quyền kiểm soát người nhận, ngân sách và dự phòng.

**Đây là problem statement cần kiểm chứng với operator, không phải kết luận về toàn thị trường.**

| Thành phần | Phạm vi cụ thể |
| --- | --- |
| Người gặp vấn đề | Finance/treasury operator hoặc founder kiêm vận hành quỹ tại stablecoin-native SME / Web3 business. |
| Bối cảnh | Có nhiều ví vận hành và khoản chi on-chain lặp lại; khoản chi đã được duyệt về người nhận, tài sản và số tiền. |
| Sự kiện kích hoạt | Đến lúc trả tiền, ví chi không đủ stablecoin hoặc gas, dù doanh nghiệp có nguồn tiền được phép dùng ở ví khác. |
| Công việc hiện tại | Kiểm tra số dư, tính thiếu hụt, chọn nguồn, đổi/chuyển tài sản, xin chữ ký theo chính sách và đối soát. |
| Hậu quả cần đo | Phút thao tác, thời gian chờ, thanh toán trễ, phí phát sinh và số lần cần can thiệp. Chưa có số liệu khách hàng trực tiếp. |
| Rào cản tự động hóa | Owner cần giới hạn quyền chi và biết điều gì đã xảy ra; chỉ có lời nhắc trong prompt không đủ để kiểm soát tài sản. |

**Chuỗi giả thuyết chung:** `Fragmented liquidity → manual treasury operations → need for bounded execution`: phân mảnh thanh khoản dẫn đến thao tác thủ công và nhu cầu thực thi có giới hạn.

“Unsafe delegation to AI” là **rào cản của giải pháp**, không mặc định là sự cố mà mọi khách hàng hiện đang gặp. TreasuryPilot phải chứng minh pain vận hành trước, rồi mới kiểm chứng khả năng chấp nhận agent.

### 2. Công việc khách hàng muốn hoàn thành

> Khi một khoản chi đã được duyệt đến hạn, tôi muốn tiền có mặt ở đúng ví và thanh toán đúng người, đúng số tiền, trong giới hạn được cấp, để không phải tự xử lý từng bước mà vẫn giữ quyền kiểm soát quỹ.

**Ưu tiên:** Tuân thủ quyền chi và giữ dự phòng trước; hoàn thành khoản chi hợp lệ tiếp theo; giảm giao dịch và thao tác không cần thiết sau đó. Không trả bằng mọi giá để đạt tỷ lệ hoàn thành cao.

### 3. Value Proposition

> **TreasuryPilot là agent điều phối quỹ vận hành on-chain: tự chuẩn bị thanh khoản và trả khoản chi đã duyệt, trong chính sách do chủ quỹ đặt, rồi cung cấp kết quả có thể kiểm chứng bằng giao dịch on-chain.**

| Giá trị đề xuất | Sản phẩm thực hiện | Cách kiểm chứng |
| --- | --- | --- |
| Ít thao tác thủ công hơn | Đọc khoản chi đã duyệt và số dư; lập kế hoạch nạp tiền/đổi tài sản khi cần; thực thi trong quyền được cấp. | So số phút thao tác và số lần can thiệp với workflow hiện tại trên cùng tập khoản chi. |
| Duy trì khả năng thanh toán | Phát hiện thiếu hụt tại ví chi và dùng nguồn được phép, không chỉ nhìn tổng số dư. | Tỷ lệ khoản chi hợp lệ hoàn thành trước deadline; số trường hợp dừng và nguyên nhân. |
| Ủy quyền có kiểm soát | Contract ràng buộc mandate và khoản chi đã duyệt; owner đặt hạn mức, phần tiền bảo vệ và thu hồi quyền. Ngoại lệ một lần phải được cấp riêng. | Test vượt quyền, replay ngoại lệ và quyền cũ sau revoke bị từ chối. |
| Kết quả dễ đối chiếu | Gắn request với các giao dịch nạp tiền, swap và payment; chỉ ghi paid sau xác nhận phù hợp. | Đối chiếu request, tx hash, receipt và số dư; tách chuyển nội bộ khỏi chi bên ngoài. |

**Chưa cam kết:** Tiết kiệm bao nhiêu phần trăm, không bao giờ thanh toán trễ, không có rủi ro, hoặc tăng lợi nhuận. Các giá trị trên là mục tiêu phải đo, không phải kết quả đã đạt.

### 4. Phân định vai trò

| Vai trò | Được quyết định gì | Không được quyết định gì |
| --- | --- | --- |
| Owner / người duyệt | Duyệt nghĩa vụ chi; đặt chính sách, dự phòng, quyền agent; sửa hoặc thu hồi quyền. | Không coi việc thu hồi là khả năng đảo ngược giao dịch đã xác nhận. |
| AI agent | Đề xuất thứ tự và kế hoạch thực hiện khoản chi hợp lệ; chọn giữa hành động được phép; giải thích và chuyển ngoại lệ cho người phụ trách. | Không thêm người nhận, sửa số tiền đã duyệt, nâng hạn mức, bỏ dự phòng hoặc tự duyệt invoice. |
| Bộ tính toán và kiểm tra xác định | Tính thiếu hụt, phí dự kiến, lượng nạp; kiểm tra kế hoạch và báo giá. | Không dựa vào suy luận tự do của LLM để tính số tiền hoặc xác nhận quyền chi. |
| Smart account / contract | Kiểm tra quyền tại thời điểm thực thi; chuyển tài sản; chặn thực thi lặp cùng request. | Không xác minh invoice phản ánh một dịch vụ có thật, bảo đảm RPC luôn hoạt động hoặc xóa rủi ro smart contract. |

**Tự động có giới hạn:** Người duyệt quyết định *có chi hay không*; agent quyết định *thực hiện như thế nào* trong mandate. Khoản đã duyệt nhưng vượt trần vẫn cần quyền ngoại lệ một lần. Phương án đang đề xuất chỉ cho vượt trần mỗi khoản, không bỏ ngân sách ngày hoặc buffer; chi tiết xem bản domain. Không yêu cầu ký lại từng bước hợp lệ.

### 5. Phạm vi sản phẩm ban đầu

**Trong MVP:** Một chain EVM; một stablecoin và native gas token; ví quỹ `T` và hai ví vận hành `O1/O2`. Hạn mức theo token, không phải USD. Refill từ `T`, swap khi cần, pay khoản đã duyệt và đối soát; không tự lấy tiền từ ví vận hành khác. Target là mục tiêu mềm; công thức/ngoại lệ phải được Finance/Product duyệt theo bản domain.

**Ngoài MVP:** Bridge/multi-chain; giao dịch đầu cơ; tối ưu lợi suất; lending; quản lý danh mục đầu tư; tự quyết định mua dịch vụ mới; nhận giữ tiền của khách hàng; trả invoice chưa duyệt; tích hợp ERP đầy đủ.

**Đề xuất môi trường:** Demo trên một EVM testnet bằng tài sản thử nghiệm, ghi rõ không phải USDC tiền thật. Chain, router và mức hạn cụ thể còn cần chốt trước khi lập đặc tả kỹ thuật. Việc testnet có được cuộc thi chấp nhận cần xác nhận với ban tổ chức.

**Giới hạn bảo vệ gas:** Contract kiểm soát tiền cấp gas và hành động được phép; không mặc định kiểm soát chính xác mọi phí mạng thực tế. Phải chốt gas payer và dự toán trước triển khai, báo phí sau xác nhận.

### 6. Vì sao không chỉ dùng công cụ đơn giản hơn?

| Phương án | Điều cần so sánh với TreasuryPilot |
| --- | --- |
| Dashboard/cảnh báo | Nếu operator chỉ cần biết số dư thấp và ít thao tác xử lý, chưa cần agent thực thi. |
| Multisig hoặc spending limits | Là nền tảng kiểm soát quyền; cần kiểm tra chúng đã đáp ứng đủ workflow thực tế chưa. |
| Script refill theo ngưỡng | Nếu nguồn tiền và hành động luôn cố định, script có thể là lựa chọn tốt hơn AI. |
| Agent lập kế hoạch | Chỉ có giá trị thêm nếu cần phối hợp khoản chi, dự phòng, nguồn tiền và ngoại lệ thay đổi; phải so với baseline rule-based. |

**Không lấy “có AI” làm khác biệt mặc định.** Nếu research cho thấy quy tắc cố định giải quyết đủ tốt, giữ cơ chế kiểm soát và thực thi nhưng thu hẹp vai trò AI.

### 7. Trạng thái và điều kiện giữ hướng

**Nguồn nền:** [Decision Memo](#project-decision-memo) và [Problem Validation & ICP](#problem-validation-and-icp), đặc biệt E1–E4 và H1–H7.

- **Fact / Evidence:** Có nguồn công khai về nghiệp vụ treasury/payment và các cơ chế kiểm soát; chưa có phỏng vấn khách hàng trực tiếp của dự án.
- **Assumption:** ICP có thiếu hụt cục bộ lặp lại, công sức đáng giải và nhu cầu phối hợp vượt quá script đơn giản.
- **Still unverified:** Mức độ pain, chấp nhận ủy quyền, willingness to pay và lợi ích thêm của AI.
- **Đã xác nhận về phạm vi:** Agent được tự nạp tiền và trả khoản chi đã duyệt trước. Đây là quyết định sản phẩm, không phải bằng chứng khách hàng chấp nhận.

**Giữ hướng khi:** Research chứng minh pain và điều kiện ủy quyền; MVP thực sự thay đổi tài sản on-chain, giữ chính sách và có bằng chứng thực thi. Không bảo đảm điểm thi hoặc mặc định đủ điều kiện triển khai tiền thật tại Trung Quốc đại lục.

**Tài liệu triển khai nghiệp vụ:** [Use-Case Specification](#use-case-specification) mô tả luồng và test; [Treasury Domain + Mandate](#treasury-domain-and-mandate-specification) định nghĩa công thức và quyền. Không lặp công thức trong tài liệu này để tránh lệch phiên bản.

---

<a id="use-case-specification"></a>

## TreasuryPilot: Use-Case Specification

**Bản:** 0.2 | **Ngày:** 09/10/2026 | **Trạng thái:** Đặc tả nháp, chưa duyệt triển khai. [Mục lục & quyết định chung](#documentation-index).

**Quyết định đã xác nhận:** Agent tự nạp tiền và trả khoản chi đã duyệt trước; khoản chi chưa duyệt không được thực hiện. Trong quyền đã cấp, không cần người ký lại từng thao tác.

### 1. Phạm vi và thuật ngữ

| Mục | Đặc tả |
| --- | --- |
| Hệ thống | Một chain tương thích EVM; ví quỹ `T`, hai ví vận hành `O1/O2`, một stablecoin và native gas token. Các ví thuộc quyền kiểm soát của doanh nghiệp. |
| Khoản chi đã duyệt | Bản ghi được người có thẩm quyền xác nhận: mã yêu cầu, chain, ví chi, token, địa chỉ nhận, số tiền và deadline. Thay đổi trường chi tiền phải duyệt lại. |
| Policy / Mandate | Policy là quy tắc nghiệp vụ; mandate là quyền agent được cấp trong các quy tắc đó. Duyệt invoice không thay thế mandate. |
| Refill | Chuyển tiền giữa ví doanh nghiệp được phép để phục vụ khoản chi đã duyệt; không phải thanh toán vendor. |
| Swap | Đổi stablecoin/gas token qua route được cho phép; không phải đầu tư hay bridge. |
| Paid | Payment thành công trên chain và đạt tiêu chí xác nhận đã cấu hình; không đồng nghĩa kế toán hoặc vendor đã hoàn tất đối soát. |

**Môi trường đề xuất, chưa chốt:** EVM testnet và tài sản thử nghiệm; router phải hỗ trợ đúng mạng và token của demo. Nếu dùng router mô phỏng, phải ghi rõ, không trình bày như swap trên thị trường thật.

**Nguồn công thức và quyền:** [Treasury Domain + Mandate](#treasury-domain-and-mandate-specification), mục 3 cho refill, mục 5 cho counter/gas/quote, mục 6 cho ngoại lệ. Các quy tắc nghiệp vụ đang đề xuất phải được Finance/Product duyệt trước cấu hình thực thi.

### 2. Actor và đầu vào

| Actor | Trách nhiệm |
| --- | --- |
| Owner / người duyệt | Cấp quyền, duyệt khoản chi, thay đổi chính sách và thu hồi quyền. |
| Operator | Đưa khoản chi vào hệ thống, theo dõi kết quả và xử lý ngoại lệ; không tự có quyền ký nếu chưa được cấp. |
| Agent + executor | Lập kế hoạch, kiểm tra và gửi giao dịch bằng quyền thực thi giới hạn; khóa chủ ví không đưa vào LLM. |
| Contract kiểm soát quyền | Kiểm tra quyền và request tại thời điểm chuyển tài sản; ghi nhận thao tác đã thực hiện. |
| Finance / accountant | Kiểm tra báo cáo đối soát; xác nhận nghiệp vụ kế toán ngoài hệ thống MVP. |

**Request tối thiểu:** `request_id`, `invoice_reference`, `chain_id`, `paying_wallet`, asset ID, `recipient`, `amount`, `deadline`, bằng chứng duyệt hợp lệ và trạng thái. Authorization thực thi tham chiếu treasury, contract, mandate/version và định danh dùng một lần; không đưa version vào invoice như quyền sửa mandate của operator.

**Nguyên tắc đầu vào:** Invoice hoặc nội dung vendor là dữ liệu không đáng tin, không phải chỉ thị cho agent. Việc phê duyệt là của doanh nghiệp; agent không xác minh thay doanh nghiệp tính có thật của nghĩa vụ chi. Không đưa nội dung invoice nhạy cảm lên chain nếu chỉ cần commitment/hash.

### 3. Quy tắc chung

| ID | Quy tắc nghiệm thu |
| --- | --- |
| R1 | Chỉ trả request được duyệt hợp lệ, còn hiệu lực, chưa trả; token/người nhận/số tiền/ví chi phải khớp bản đã duyệt. Contract phải xác minh sự cho phép bằng bản đăng ký on-chain hoặc chữ ký có ràng buộc chain và contract, không chỉ tin cờ `approved` từ backend. |
| R2 | Ví, người nhận, token, contract và loại hành động phải nằm trong quyền được cấp. AI không sửa policy; contract kiểm tra policy hiện hành khi thực thi. |
| R3 | Hạn mức theo lượng token, không phải USD. Phương án đề xuất: ngày UTC, counter tổng treasury không reset khi đổi ví/version; ngân sách pay/refill/swap tách riêng, không đếm refill thêm vào ngân sách vendor. |
| R4 | Bảo vệ reservation/hold của việc khác và buffer đã đăng ký; target là mục tiêu mềm. Contract enforce phần tiền qua đường kiểm soát; gas funding cap khác phí mạng thực tế. Phải chốt gas payer và dự toán, không cam kết tuyệt đối buffer native token khi chưa kiểm soát được phí. |
| R5 | Swap kiểm tra route/cặp asset/input, quote có bằng chứng từ nguồn đã cấu hình, freshness và minimum output. Agent không tự khai quote hoặc hạ minOut; nguồn quote là trust assumption, không bảo đảm giá tốt nhất. |
| R6 | Payment dùng `request_id` một lần; đánh dấu đã thực hiện và chuyển tiền trong cùng giao dịch. Mỗi bước refill/swap có định danh chống lặp, gắn với request và kế hoạch đã được kiểm tra. |
| R7 | Không đủ nguồn tiền, gas khởi động, quyền hoặc thời gian thì dừng/báo ngoại lệ. Nếu mọi ví/executor cần gửi giao dịch đều hết gas, agent không thể tự swap để khởi động; cần nguồn gas đã có hoặc cơ chế tài trợ riêng ngoài MVP. |
| R8 | Pending, timeout hoặc mất kết nối không đồng nghĩa giao dịch thất bại. Không tạo request mới hoặc gửi khoản trả thứ hai khi chưa xác định trạng thái giao dịch cũ. |
| R9 | Pause/thu hồi quyền ngăn thực thi mới sau khi có hiệu lực on-chain; giao dịch đã hoàn tất không bị đảo ngược. Backend phải dừng lập/gửi kế hoạch mới ngay khi nhận lệnh pause. |
| R10 | Khoản đã duyệt vượt trần mỗi khoản nhưng chưa có ngoại lệ hợp lệ chuyển UC-06 trước chuẩn bị tiền. Ngoại lệ hợp lệ cho phép quay về UC-02; phương án chỉ vượt trần mỗi khoản, các hard rule khác vẫn phải đạt. |

**Đơn giản hóa MVP:** Xử lý tuần tự, mỗi lần chỉ một request có chuỗi giao dịch đang thực thi. Đọc lại số dư và quyền trước mỗi bước; không dựa vào snapshot ban đầu sau khi trạng thái đã thay đổi.

**Lập kế hoạch và fallback:** Theo [Autonomy & Decision Policy](#autonomy-and-decision-policy). Khi AI không phản hồi, chỉ dùng template đã kiểm thử với đầy đủ dữ liệu và cùng kiểm tra quyền; không dùng khi pending/unknown hoặc có cảnh báo an toàn. AI đề xuất kế hoạch nguy hiểm thì loại và chuyển UC-04, không che bằng fallback.

### 4. Các use case

#### UC-01: Thiết lập quyền và duyệt khoản chi

**Actor:** Owner, operator. **Trigger:** Khởi tạo hoặc thay đổi quyền/khoản chi.  
**Tiền điều kiện:** Owner kiểm soát ví; thông tin người nhận và nghĩa vụ chi đã được doanh nghiệp kiểm tra.

1. Owner cấu hình ví, tài sản, hành động, hạn mức, dự phòng và thời hạn quyền.
2. Hệ thống chỉ coi quyền hoạt động sau khi thay đổi on-chain được xác nhận.
3. Operator tạo request; người có thẩm quyền duyệt chính xác các trường chi tiền.
4. Request hợp lệ vào hàng đợi; request chưa duyệt chỉ ở trạng thái chờ duyệt.

**Hậu điều kiện:** Có quyền thực thi giới hạn và request được duyệt; chưa phát sinh payment.  
**Ngoại lệ:** Địa chỉ/token/chain không khớp hoặc dữ liệu thiếu thì không đưa vào hàng đợi thực thi.  
**Nghiệm thu:** Đổi người nhận hoặc số tiền sau duyệt làm mất hiệu lực bản duyệt; chỉ tạo invoice không kích hoạt chi tiền.

#### UC-02: Tự chuẩn bị thanh khoản và thanh toán

**Actor:** Agent, executor, contract. **Trigger:** Có request đã duyệt đến thời điểm xử lý.  
**Tiền điều kiện:** R1–R10 được đáp ứng; có quyền và nguồn tiền cho kế hoạch, gas khởi động ở tài khoản thực sự chịu phí. Pay chỉ dùng stablecoin của MVP.

1. Đọc request, mandate hiện hành, số dư và phần tiền bảo vệ; tính thiếu hụt/lượng refill theo domain mục 3. Nếu cần ngoại lệ, chuyển UC-06 trước khi chi cho kế hoạch.
2. Agent chọn kế hoạch hợp lệ: trả trực tiếp nếu đủ; refill nếu thiếu; thêm swap khi cần và được phép. Trong MVP, nguồn tiền chỉ là `T` và ví chi, không tự lấy tiền từ ví vận hành khác.
3. Kiểm tra toàn kế hoạch: dự phòng sau xử lý, các trần riêng, phí dự kiến, báo giá và deadline. Không hợp lệ thì chuyển UC-04.
4. Thực hiện từng bước chuẩn bị được phép. Sau mỗi bước, chờ xác nhận, đọc lại số dư và điều kiện; không coi cả chuỗi giao dịch là atomic.
5. Trước payment, kiểm tra lại bản duyệt, quyền hiện hành và trạng thái chưa trả; contract thực thi khoản tiền đúng người nhận.
6. Sau xác nhận phù hợp, ghi `Paid`, liên kết receipt/tx hash và tạo báo cáo đối soát theo UC-03.

**Hậu điều kiện:** Khoản chi được trả một lần trên trạng thái chain được xác nhận; có dấu vết các bước; không vi phạm chính sách.  
**Luồng thay thế:** Đủ tiền thì bỏ refill/swap; chỉ thiếu gas thì chuẩn bị gas ở đúng gas payer. Thiếu asset mà không có nguồn/route hợp lệ thì dừng theo UC-04, không bỏ bước cần thiết rồi cố pay.  
**Hoàn thành một phần:** Nếu refill thành công nhưng payment bị chặn, giữ tiền và bằng chứng refill, báo ngoại lệ; không tự hoàn tác hoặc nạp lại toàn bộ khi retry.

**Ví dụ tương ứng công thức domain:** `B=20`, `P=100`, `F=H=10`, `R_other=L_other=G=0` cho stablecoin; gas đã sẵn sàng ở gas payer. `Shortage=PreferredRefill=90`. Nếu nguồn/hạn mức đủ, nạp 90 rồi trả 100, ví còn 10. Đây là dữ liệu test, không phải workflow đã quan sát.

#### UC-03: Theo dõi kết quả và đối soát

**Actor:** Hệ thống, operator, finance. **Trigger:** Đã gửi giao dịch hoặc có thay đổi trạng thái.  
**Tiền điều kiện:** Có định danh request/bước thực thi và thông tin giao dịch hoặc trạng thái gửi chưa rõ.

1. Theo dõi receipt, trạng thái contract và số dư; áp dụng tiêu chí xác nhận theo chain đã chọn.
2. Gắn mọi bước với request; phân loại refill là chuyển nội bộ, swap là chuyển đổi và payment là chi bên ngoài.
3. Ghi phí thực tế khi có dữ liệu; báo phần còn chưa khớp thay vì tự suy đoán đã thanh toán.
4. Cung cấp báo cáo: khoản chi, người nhận, số tiền, trạng thái, tx hash, phí và ngoại lệ. Chỉ đánh dấu đối soát xong khi các bằng chứng cần thiết khớp.

**Hậu điều kiện:** Có báo cáo truy nguyên được; `Paid` và trạng thái đối soát được phân biệt.  
**Ngoại lệ:** Receipt thiếu, kết quả không khớp hoặc reorg thì giữ trạng thái chưa chắc chắn/kiểm tra lại, không tự phát sinh payment mới.  
**Nghiệm thu:** Một request có thể gắn nhiều tx; không ghi refill thành chi phí vendor; không ghi tx vừa broadcast là `Paid`.

#### UC-04: Dừng khi vượt quyền hoặc chưa rõ kết quả

**Actor:** Hệ thống, owner/operator. **Trigger:** Kiểm tra không đạt, giao dịch lỗi hoặc trạng thái chưa rõ.

1. Phân biệt lỗi policy/dữ liệu, lỗi có thể thử lại và giao dịch chưa rõ kết quả.
2. Dừng các bước tiếp theo; báo nguyên nhân, bước đã hoàn tất và hành động cần con người quyết định.
3. Chỉ tính lại/retry sau khi biết trạng thái bước cũ, dữ liệu mới hợp lệ và quyền còn hiệu lực. Giữ cùng request và định danh bước; không coi retry là khoản chi mới.
4. Nếu chỉ vượt trần mỗi khoản, dùng UC-06; thay ngân sách/người nhận cần owner sửa policy, thay amount/payee của nghĩa vụ cần duyệt lại. Agent không tự “sửa lỗi” bằng thay quyền.

**Hậu điều kiện:** Không thực hiện ngoài phạm vi; không trả trùng khi phục hồi.  
**Nghiệm thu:** Timeout sau broadcast không dẫn đến khoản trả thứ hai; retry sau refill không nạp trùng; prompt injection trong invoice không đổi địa chỉ nhận.

**Giới hạn chống trùng:** Chặn lặp `request_id` không tự ngăn cùng một invoice bị người dùng nhập dưới hai ID khác nhau. Backend phải cảnh báo trùng theo invoice/vendor reference trước duyệt; người duyệt chịu trách nhiệm xác nhận nghĩa vụ chi.

#### UC-05: Tạm dừng hoặc thu hồi quyền

**Actor:** Owner. **Trigger:** Owner yêu cầu pause/revoke, quyền hết hạn hoặc có sự cố.

1. Backend dừng gửi hành động mới; hiển thị các giao dịch đang pending.
2. Owner gửi thay đổi quyền on-chain khi cần; phân biệt “đã yêu cầu thu hồi” với “đã có hiệu lực”.
3. Sau hiệu lực, contract từ chối hành động mới sử dụng quyền cũ. Khi chạy lại, kiểm tra quyền và trạng thái từng request trước khi tiếp tục.

**Hậu điều kiện:** Agent không còn thực thi bằng quyền đã bị thu hồi.  
**Ngoại lệ:** Giao dịch có thể được thực thi trước giao dịch revoke; không hứa pause tức thời đảo ngược hoặc chặn mọi giao dịch đã broadcast.  
**Nghiệm thu:** Quyền hết hạn/bị thu hồi không thực hiện được payment mới, dù kế hoạch đã tạo trước đó.

#### UC-06: Cấp và sử dụng quyền ngoại lệ một lần

**Actor:** Owner, agent, contract. **Trigger:** Request đã duyệt vượt trần mỗi khoản, chưa có ngoại lệ hợp lệ.  
**Tiền điều kiện:** Payee đã đăng ký, request/mandate còn hiệu lực; các hard rule khác đạt. Phương án chỉ vượt trần mỗi khoản đang chờ Finance/Product duyệt.

1. Agent dừng trước swap/refill/pay và báo `NEEDS_APPROVAL`; request ở `AwaitingAuthority`, không phải chờ duyệt invoice lần đầu.
2. Owner cấp ngoại lệ ràng buộc exact request/amount/payee/asset/ví chi, chain/contract, mandate/version, expiry và nonce; hoặc từ chối.
3. Sau quyền có hiệu lực, hệ thống kiểm tra lại nguồn, policy và ngân sách ngày, rồi quay về UC-02. Quyền không sửa mandate chung.
4. Contract consume ngoại lệ một lần cùng payment; full amount vẫn tính vào ngân sách ngày. Revert không ghi đã trả; retry phải tra trạng thái cũ trước.

**Hậu điều kiện:** Đúng request được trả một lần, hoặc giữ nguyên trạng thái chưa chi.  
**Ngoại lệ:** Sai request/version, hết hạn, payee lạ, thiếu nguồn hoặc vượt ngân sách ngày thì chặn; thay amount/payee cần duyệt lại.  
**Nghiệm thu:** Không tái dùng quyền cho request khác; revoke/thay version vô hiệu ngoại lệ cũ; không bypass daily limit/buffer.

### 5. Trạng thái nghiệp vụ

**Trạng thái request:** `Draft → AwaitingApproval → Approved → Planning → Preparing → Paying → Paid`.

**Nhánh ngoại lệ:** `AwaitingAuthority` khi chờ ngoại lệ UC-06; `NeedsReview` khi thiếu nguồn/quyền hoặc phải đổi kế hoạch; `Expired` khi quá deadline; `Cancelled` khi hủy nghĩa vụ chưa trả. Có payment pending thì chưa được ghi hủy xong nếu payment vẫn có thể hoàn tất.

**Trạng thái từng giao dịch, tách khỏi request:** `NotSubmitted / Submitted / Pending / Confirmed / Reverted / Unknown`.

**Trạng thái đối soát riêng:** `NotReady / Pending / Matched / Discrepancy`.

`Unknown` cần tra cứu trạng thái chain, receipt và định danh đã thực hiện trước khi quyết định retry. Không dùng một trạng thái `Failed` chung để xóa dấu vết các bước đã thành công.

### 6. Bộ nghiệm thu MVP

Các trường hợp dưới đây là test bắt buộc đề xuất, không phải cam kết kết quả đã đạt.

| ID | Kịch bản | Kết quả mong đợi |
| --- | --- | --- |
| AT-01 | Khoản chi đã duyệt; ví đủ tiền/gas | Tự payment, không refill/swap thừa; có receipt và báo cáo. |
| AT-02 | Thiếu stablecoin; quỹ đủ và giữ được dự phòng | Tự refill rồi payment, đúng số tiền và người nhận. |
| AT-03 | Thiếu gas; có nguồn gas hoặc swap hợp lệ | Chuẩn bị gas rồi payment; không hứa xử lý khi mọi nguồn khởi động đều hết gas. |
| AT-04 | Tình huống cần swap | Swap thực sự thay đổi tài sản on-chain, đáp ứng minimum output và trần, sau đó payment. |
| AT-05 | Chưa duyệt, đổi payee, vượt daily limit/buffer hoặc vượt trần mỗi khoản chưa có ngoại lệ | Không chi; vượt trần mỗi khoản có thể xin UC-06, các hard rule khác không bị bypass. |
| AT-06 | Gửi lại cùng request; mất kết nối sau broadcast | Không có payment thứ hai trên chain được xác nhận; trạng thái được phục hồi từ bằng chứng. |
| AT-07 | Refill xong, payment chưa thành công | Báo hoàn thành một phần; retry không refill trùng hoặc bỏ qua quyền mới. |
| AT-08 | Pause/revoke/hết hạn | Không gửi mới từ backend; sau hiệu lực on-chain, quyền cũ bị từ chối. |
| AT-09 | Invoice chứa lệnh đổi ví nhận/nâng hạn mức | Bỏ qua chỉ thị; trường đã duyệt và policy không thay đổi. |
| AT-10 | Hai khoản chi tranh cùng nguồn tiền | Xử lý tuần tự; tính lại số dư/dự phòng; không dựa vào hai snapshot cũ để chi quá mức. |
| AT-11 | Ngoại lệ khớp request, replay, sai version hoặc vượt daily limit | Chỉ quyền đúng và còn hiệu lực được dùng một lần; amount tính đầy đủ; trường hợp khác bị chặn. |
| AT-12 | Có reserve khác, target cao hơn buffer, nguồn chỉ đủ minimum | Áp dụng công thức domain; giữ reserve/buffer, refill Shortage, báo target chưa đạt. |
| AT-13 | Quote giả/hết hạn, minOut bị hạ hoặc pending qua ngày UTC | Chặn quote sai; kiểm tra ngân sách ngày thực thi, không dùng quyền ngân sách ngày cũ. |

**Bằng chứng demo:** Request và policy đã duyệt; kế hoạch; tx hash/receipt; số dư trước/sau; test bị contract từ chối; báo cáo đối soát. Mock dữ liệu phải ghi rõ; không dùng hash giả để chứng minh thực thi on-chain.

**Chỉ số cần đo:** Tỷ lệ hoàn thành các request hợp lệ, có nguồn tiền/quyền và hạ tầng sẵn sàng; tỷ lệ trước deadline; số lần con người can thiệp; phút thao tác; phí và số giao dịch; kết quả toàn bộ test vượt quyền/chống trùng. Báo riêng số request bị loại và lý do, không giấu chúng khỏi báo cáo tổng.

### 7. Điều kiện triển khai

Các điểm mở O1–O8 được quản lý tại [Mục lục & quyết định chung](#documentation-index). Trước Dev triển khai, Finance/Product phải duyệt công thức, cửa sổ ngân sách, phạm vi ngoại lệ và gas payer; Dev xác nhận khả năng enforce/cấu hình mạng, quote, confirmation, retry và fallback.

**Nguồn yêu cầu:** [Problem Statement + Value Proposition](#problem-statement-and-value-proposition). **Bằng chứng khách hàng:** [Problem Validation & ICP](#problem-validation-and-icp); đặc tả và test chưa chứng minh nhu cầu hoặc product–market fit.

**Ranh giới:** MVP minh họa quản lý tài sản vận hành, thực thi giao dịch và kiểm soát rủi ro on-chain; không bảo đảm điểm thi, an toàn tuyệt đối hoặc tính hợp pháp của triển khai tiền thật tại Trung Quốc đại lục.

---

<a id="treasury-domain-and-mandate-specification"></a>

## TreasuryPilot: Treasury Domain & Delegated Mandate Specification

**Bản:** 0.2 | **Ngày:** 09/10/2026 | **Owner:** Finance/Product | **Trạng thái:** Đặc tả nháp, chưa duyệt triển khai.  
**Vai trò:** Nguồn định nghĩa, công thức và quyền cho [Use-Case Specification](#use-case-specification). Trạng thái quyết định xem [Mục lục chung](#documentation-index); không thay chuẩn kế toán hoặc thẩm định pháp lý.

### 1. Quyết định và phạm vi

**Đã xác nhận:** Agent tự refill/pay khoản đã được người có thẩm quyền duyệt; một stablecoin, hạn mức theo token và gas riêng; owner có thể cấp ngoại lệ một lần, payee chưa đăng ký vẫn bị chặn. Không mặc định 1 token stablecoin bằng 1 USD.

**Phạm vi:** Một chain tương thích EVM, một ví quỹ `T`, hai ví vận hành `O1/O2`; `SWAP`, `REFILL`, `PAY`. Không bridge, đầu tư/lợi suất, vay hoặc tự lấy tiền từ ví vận hành khác.

**Nguyên tắc:** AI lập kế hoạch, bộ tính toán xác định lượng tiền, contract kiểm tra quyền. Công thức, ngày UTC, phạm vi ngoại lệ và các số hạn mức dưới đây là **phương án đề xuất chờ duyệt**, không tự trở thành cấu hình thực thi. Prompt không bảo vệ tài sản.

### 2. Từ điển nghiệp vụ

| Thuật ngữ | Định nghĩa dùng trong TreasuryPilot |
| --- | --- |
| **Asset** | Tài sản được nhận diện bằng chain và địa chỉ contract; native token dùng định danh riêng. Tên “USDC” không đủ để xác định đúng tài sản. |
| **Chain** | Mạng blockchain có `chain_id` cụ thể. Testnet và mainnet là hai mạng khác nhau; cùng tên token không có nghĩa cùng tài sản. |
| **Treasury Wallet** | Ví quỹ `T`, nguồn tiền được phép cấp cho ví vận hành; thuộc quyền kiểm soát của doanh nghiệp. |
| **Operational Wallet** | Ví `O1/O2` dùng cho nghiệp vụ chi đã duyệt; có người nhận, ngân sách và dự phòng được cấu hình. |
| **Treasury Balance** | Tổng số dư đã xác nhận của một asset trên tập ví doanh nghiệp được quản lý, tính theo từng chain. Không bao gồm tiền bridge đang chờ hoặc tiền chưa nhận. |
| **Wallet Balance** | Số dư đã xác nhận của một asset tại một ví cụ thể. Không đồng nghĩa tiền có thể tự do sử dụng. |
| **Reserved Funds** | Lượng tiền cam kết dành cho nghĩa vụ đã đăng ký còn hiệu lực; không phải tiền cộng thêm. Có thể chưa đủ số dư để tài trợ, khi đó phải báo FundingDeficit. |
| **Execution Hold** | Tiền tạm giữ cho bước đã được cấp quyền nhưng chưa xác định kết quả. Không cho kế hoạch khác dùng lại khi pending/unknown. |
| **Minimum Buffer** | Mức tiền tối thiểu không được xâm phạm bởi hành động agent, sau khi bảo vệ reservation của nghĩa vụ khác. Owner đặt theo ví/asset. |
| **Available Balance** | Tiền còn có thể phân bổ sau khi trừ reserved funds, execution holds và minimum buffer; tính riêng từng ví/asset. |
| **Target Balance** | Phần số dư mong muốn sau khoản chi, ngoài reservation/hold của việc khác, **đã bao gồm buffer**. Mục tiêu mềm để refill, không phải trần chi. |
| **Liquidity Shortage** | Ví thiếu đúng asset để thực hiện nghĩa vụ hiện tại mà vẫn bảo vệ phần tiền khác và minimum buffer; không chỉ là tổng quỹ thấp. |
| **Gas** | Phí mạng bằng native token để thực hiện giao dịch. Phí dự kiến khác phí thực tế; xác định rõ tài khoản nào thực sự chịu phí. |
| **Swap** | Đổi asset qua adapter/router được phép trên cùng chain; kiểm soát lượng đầu vào, asset đầu ra và minimum output. |
| **Slippage** | Mức giảm đầu ra cho phép so với báo giá tham chiếu hợp lệ của cùng giao dịch. Không phải bảo đảm mức giá thị trường công bằng. |
| **Bridge** | Chuyển tài sản/giá trị giữa chain, có bước chờ và rủi ro riêng; ngoài MVP và bị chặn bởi mandate. |
| **Payee** | Bên nhận đã được đăng ký bằng địa chỉ trên chain. “Vendor A” chỉ là nhãn hiển thị, không phải quyền nhận tiền. |
| **Recurring Payment** | Chuỗi nghĩa vụ chi lặp theo lịch. Trong MVP, mỗi kỳ là request riêng, được duyệt riêng; chưa có quyền tự tạo khoản chi từ lịch. |
| **Policy** | Các quy tắc nghiệp vụ do owner đặt: ngân sách, phần tiền bảo vệ, người nhận và điều kiện thực hiện. |
| **Mandate** | Quyền thực thi có phạm vi, hạn mức và thời hạn do owner cấp cho agent, được contract kiểm tra; không thay quyền duyệt invoice. |
| **One-Time Exception** | Quyền riêng cho đúng một request vượt trần mỗi khoản, có số tiền và thời hạn cụ thể; không sửa quyền chung. |

**Đơn vị:** Số nguyên ở đơn vị nhỏ nhất, decimals xác nhận khi cấu hình; UI mới chuyển sang số dễ đọc. Không dùng số thực cho hạn mức hoặc cộng ETH và stablecoin thành một số dư chung.

### 3. Công thức thanh khoản và refill

#### 3.1. Số dư có thể dùng

Với một ví `w`, một asset `a`, tại snapshot đã xác nhận:

| Ký hiệu | Ý nghĩa |
| --- | --- |
| `B` | Wallet Balance. |
| `R` | Tổng Reserved Funds còn hiệu lực, chưa được chuyển sang execution hold. |
| `L` | Tổng Execution Hold chưa giải phóng. |
| `F` | Minimum Buffer. |
| `H` | Target Balance; bắt buộc `H >= F`. |

```text
TreasuryBalance[a, chain] = sum(B[w, a, chain]) trên các ví được quản lý
Available[w, a] = max(0, B - R - L - F)
FundingDeficit[w, a] = max(0, R + L + F - B)
```

Tiền ở ví khác có thể bị reserve hoặc không được phép dùng. `Available = 0` vẫn phải báo deficit. Mỗi phần nghĩa vụ chỉ reserve tại một ví; chuyển từ `R` sang `L` không giữ cả hai cho cùng phần tiền. Timeout không release hold; chỉ cập nhật khi đã xác định kết quả.

#### 3.2. Khi xử lý request hiện tại

Đánh giá riêng từng asset, trong đó:

- `P`: lượng asset phải trả theo request; với gas token, thường `P = 0`.
- `G`: phí dự kiến có biên an toàn **do chính ví đang xét chịu**; bằng 0 nếu phí do executor/ví khác trả.
- `R_other`, `L_other`: reservation/hold của việc khác, loại phần thuộc request đang xét để không trừ khoản chi hiện tại hai lần.
- `D = P + G`: nhu cầu của request với asset này. Gas khởi động của executor được kiểm tra riêng, không gán cùng một phí cho nhiều ví.

```text
ProtectedOther = R_other + L_other
Shortage = max(0, ProtectedOther + D + F - B)

Nếu Shortage = 0: không refill chỉ để đạt target.
Nếu Shortage > 0:
    PreferredRefill = max(0, ProtectedOther + D + H - B)
```

**Phương án đề xuất:** Refill theo khoản đã duyệt, không tự đổ đầy ví chỉ vì dưới target. `H` gồm `F`, không cộng buffer lần nữa. Use case chỉ tham chiếu công thức này, không hard-code lượng refill.

#### 3.3. Nguồn tiền và lượng thực hiện

Nguồn refill trong MVP là `T`. Tính tiền nguồn sau khi bảo vệ reserve/buffer và phí riêng của nguồn:

```text
SourceCapacity = max(0, B_T - R_T_other - L_T_other - F_T - G_T)
Cap = min(SourceCapacity, RemainingRefillBudget, PerRefillLimit)
```

Nếu nguồn phải swap, tính lại trạng thái dự kiến sau swap và kiểm tra riêng ngân sách swap; không coi báo giá đầu ra là số dư đã có.

| Điều kiện | Quyết định |
| --- | --- |
| `Cap >= PreferredRefill` | Refill `PreferredRefill`, rồi kiểm tra lại và pay. |
| `Shortage <= Cap < PreferredRefill` | Refill đúng `Shortage`; báo target chưa đạt. Vẫn giữ buffer, không phá hard rule để đạt target. |
| `Cap < Shortage` | Dừng và báo thiếu nguồn/hạn mức; không tự trả một phần invoice hoặc nạp một phần không đủ hoàn thành. |

Kiểm tra nguồn/quyền cho cả kế hoạch trước khi bắt đầu, đọc lại sau mỗi bước. Chuỗi swap/refill/pay không atomic; bước trước đã xong nhưng bước sau bị chặn thì ghi hoàn thành một phần, không giả định rollback.

#### 3.4. Ví dụ để Finance và Dev kiểm tra cùng nhau

Ví dụ chỉ xét stablecoin; gas đã có ở đúng tài khoản chịu phí:

```text
O1: B = 300; R_other = 100; L_other = 0
Request: P = 400; G = 0; F = 50; H = 150

Shortage = 100 + 400 + 50 - 300 = 250
PreferredRefill = 100 + 400 + 150 - 300 = 350
```

- Nguồn/hạn mức cho phép 350: nạp 350, trả 400; `O1` còn 250 = reserved 100 + target 150.
- Chỉ cho phép 300: nạp đúng 250, trả 400; `O1` còn 150 = reserved 100 + buffer 50; target chưa đạt.
- Chỉ cho phép 200: dừng; không lấy reserved 100 để cố trả hoặc chia invoice thành các khoản nhỏ.

### 4. Cấu trúc quyền: Ba điều kiện đồng thời

```text
Quyền thực hiện = Khoản chi được duyệt
                 AND Mandate còn hiệu lực
                 AND Kế hoạch/bước hiện tại thỏa constraint
```

**Bản duyệt** ràng buộc request, chain, ví chi, asset, payee, amount và deadline; **mandate** ràng buộc quyền thực thi. Không thay thế nhau. Điểm nhấn là `ALLOW / NEEDS_APPROVAL / BLOCK` có lý do và enforcement, không tuyên bố spending limits tự thân là phát minh mới.

#### 4.1. Các trường mandate bắt buộc

| Nhóm | Trường / quy tắc |
| --- | --- |
| Định danh | `mandate_id`, `version`, `treasury_id`, `agent_executor`, `chain_id`, contract kiểm soát quyền. |
| Hiệu lực | `valid_from`, `expires_at`, `status`; chỉ owner có quyền cấp, sửa, pause/revoke. |
| Phạm vi | `allowed_actions`, asset IDs, wallet IDs, cặp nguồn/đích refill, địa chỉ payee, adapter/router và loại lời gọi được phép. |
| Chi trả | `pay_per_request_limit[asset]`, `pay_daily_limit[asset]`; trả toàn bộ amount đã duyệt, không split để né trần. |
| Chuẩn bị tiền | Trần refill theo lần/ngày/asset; trần swap đầu vào theo lần/ngày/asset; các bước phải phục vụ request hợp lệ. |
| Bảo vệ số dư | `minimum_buffer[wallet, asset]`, reservation/hold đã đăng ký; `target_balance` là mục tiêu mềm và mức refill phải nằm trong quyền cho request/kế hoạch. |
| Giá | Cặp swap, nguồn báo giá, tuổi tối đa của quote, `max_slippage_bps`, lượng vào và minimum output. |
| Chống lặp | Request đã trả, step đã thực hiện và nonce/định danh authorization; không tái sử dụng ở chain/contract khác. |

Agent không có lời gọi tùy ý: chặn `approve` vô hạn, đổi owner/cài module, `delegatecall`, calldata router không kiểm tra. Allowance swap giới hạn theo input; chỉ allowlist router chưa đủ.

#### 4.2. Ví dụ policy đọc được bởi Finance

Ví dụ cấu hình để thảo luận, **không phải authorization có thể triển khai nguyên trạng**:

```yaml
actions: [SWAP, REFILL, PAY]
chain_id: <mang-EVM-da-chot>
stablecoin: <dia-chi-token-da-xac-minh>
gas_asset: NATIVE
wallets: [T, O1, O2]
refill_paths: [T_to_O1, T_to_O2]
payees: [<dia-chi-Vendor-A>, <dia-chi-Vendor-B>]
pay_per_request: 2000  # don vi token stablecoin, khong phai USD
pay_daily: 10000
refill_per_step: 2500
refill_daily: 12000
swap_stablecoin_input_per_step: 100
swap_stablecoin_input_daily: 500
max_slippage_bps: 50  # 0.5%
validity_hours: 24
over_per_request: REQUIRE_ONE_TIME_EXCEPTION
unknown_payee: BLOCK
bridge: BLOCK
```

Các trường gas funding cap, buffer/target từng ví, router/quote source và thời hạn quote phải được điền trước kích hoạt; thiếu trường bắt buộc thì **không cấp quyền**. Các lượng hiển thị trên phải đổi sang đơn vị nguyên nhỏ nhất; expiry triển khai thành timestamp cụ thể, không giữ chuỗi “24h”.

### 5. Cách enforce và hạch toán hạn mức

#### 5.1. Counter và thời điểm tính

```text
Day = floor(block_timestamp / 86400)  # ngay UTC, khong phai 24h truot
Used[action, asset, Day] + HeldBudget[action, asset, Day] + NewAmount <= DailyLimit
```

- Counter tổng dùng phạm vi treasury/action/asset/ngày, không riêng từng ví. Chia payment giữa `O1/O2`, sửa version hoặc cấp mandate mới không tự reset ngân sách treasury đã dùng.
- Reserve **tiền** và reserve **ngân sách** là hai kiểm tra khác nhau; phải đủ cả hai. Mức tổng treasury và mức mandate đang dùng đều phải thỏa.
- `NewAmount` chỉ là phần chưa có budget hold. Khi thực thi lệnh đã được hold, chuyển hold tương ứng sang used, không cộng lại toàn bộ amount như một lệnh mới.
- Khi thực thi thành công, chuyển budget hold sang used trong cùng giao dịch, không tính cả hold và used. Giao dịch revert không tăng used; không giải phóng hold chỉ vì RPC timeout.
- Request pending qua nửa đêm: tính theo ngày thực thi on-chain và kiểm tra/đặt lại budget hold cho ngày đó trước chi; không mang quyền chi ngày cũ sang ngày mới. Ngày UTC cho phép chi sát hai phía nửa đêm, không phải trần cho mọi cửa sổ 24 giờ.
- Refill tính vào ngân sách refill; swap tính theo đầu vào thực tế vào ngân sách swap; payment tính vào ngân sách pay. Một khoản 400 được refill rồi trả không thành 800 ngân sách vendor, nhưng vẫn tiêu thụ cả hai trần hành động tương ứng.

#### 5.2. Dự phòng và hold phải có dữ liệu enforce được

Contract lưu/kiểm chứng reserve/hold gắn request/kế hoạch; kiểm tra phần bảo vệ của việc khác và buffer, cập nhật cùng counter/chống lặp nhất quán trong từng giao dịch. Hold chỉ ở database không phải hard protection on-chain; agent không tự sửa reserve/buffer.

Chỉ bảo vệ nghĩa vụ đã đăng ký và đường thực thi agent. Invoice chưa nhập hoặc owner tự chuyển tiền ngoài đường này có thể làm thiếu quỹ; agent phải đọc lại và dừng, không hứa bảo vệ trước mọi hành động owner.

#### 5.3. Slippage không chỉ là con số trong prompt

```text
minOut = ceil(quoteOut * (10000 - maxSlippageBps) / 10000)
actualOutput >= minOut
```

Quote phải gắn chain/router/cặp asset/input/expiry từ nguồn đã cấu hình. Đề xuất nguồn ký quote để contract xác minh; adapter kiểm tra input/output/ví nhận. `amountOutMin` do agent tự khai chưa chứng minh slippage được enforce. Nguồn quote là trust assumption, không bảo đảm giá tốt nhất hay ngăn mọi quote sai/depeg.

#### 5.4. Gas: Giới hạn phải nói đúng bản chất

Gas token dùng cho chuẩn bị/thực thi, không mặc định được `PAY` cho vendor. Đề xuất executor có gas khởi động nạp trước và đường cấp gas có trần native token riêng. Gas payer/ví nhận gas phải đăng ký trong cấu hình; không tự coi đó là payee được phép. Nếu executor dùng ví hạ tầng riêng, khai báo role riêng, không đổi số ví nghiệp vụ `T/O1/O2` của MVP.

Contract có thể enforce lượng native token cấp ra và lượng đầu vào swap; trần **gas funding** không phải trần chính xác mọi phí mạng thực tế. Bộ gửi giao dịch kiểm tra fee envelope và dự toán; báo phí thực tế sau xác nhận. Gas mất cho giao dịch revert vẫn phải báo, dù không tăng counter payment. Không tuyên bố buffer native token luôn được bảo toàn nếu ví đó trực tiếp trả phí nhưng thiết kế chưa kiểm soát được phí ấy.

### 6. Ngoại lệ và vòng đời quyền

#### 6.1. Quyền ngoại lệ một lần

**Phương án đề xuất O2:** Chỉ vượt `pay_per_request_limit`; không vượt ngân sách ngày, reserve/buffer, payee, asset, chain hoặc expiry. Cần Finance/Product duyệt phạm vi này; việc có ngoại lệ một lần đã được chủ dự án xác nhận. Luồng thực hiện: UC-06 trong Use-Case Specification.

Authorization phải ràng buộc `request_id`, mandate/version, treasury, chain, contract, ví chi, payee, asset, exact amount, deadline và nonce; được owner đăng ký/xác nhận on-chain. Consume một lần cùng giao dịch payment; nếu revert thì không được ghi là đã trả.

| Trường hợp | Kết quả |
| --- | --- |
| Đúng request và trong mọi giới hạn | `ALLOW`. |
| Vượt trần mỗi khoản, chưa có ngoại lệ, vẫn đủ ngân sách ngày | `NEEDS_APPROVAL`; chưa chi. |
| Có ngoại lệ khớp request, còn hiệu lực và các hard rule đều đạt | `ALLOW` một lần; amount vẫn tính đầy đủ vào ngân sách ngày. |
| Vượt ngân sách ngày, xâm phạm reserve hoặc người nhận chưa đăng ký | `BLOCK`, dù có ngoại lệ vượt trần mỗi khoản. |
| Chưa duyệt hoặc đổi amount/payee sau duyệt | `BLOCK`; phải duyệt lại nghĩa vụ, không sửa bản cũ bằng prompt. |

Ví dụ: request 2.500 token vượt trần 2.000; owner cấp ngoại lệ cho đúng request. Nếu đã chi 8.000 trong ngày với trần 10.000, vẫn chặn vì `8.000 + 2.500 > 10.000`. Owner muốn thay ngân sách/người nhận phải thay cấu hình bằng quyền owner, không dùng ngoại lệ mơ hồ.

#### 6.2. Vòng đời và chống bypass

`Draft → Active → Expired / Revoked`; trạng thái pause chặn thực thi cho đến khi owner cho phép hoạt động lại. Kích hoạt, sửa hoặc revoke chỉ có hiệu lực bảo vệ on-chain sau xác nhận phù hợp.

Mọi bước dùng version hiện hành. Thay version vô hiệu quyền ngoại lệ cũ, không xóa counter đã dùng; pending được kiểm tra lại theo trạng thái tại thời điểm thực thi. Owner vẫn có quyền kiểm soát ví ngoài mandate, nhưng hành động trực tiếp đó phải được báo riêng, không giả là agent đã tuân thủ mandate để chi.

**Điều kiện kiến trúc bắt buộc:** Agent chỉ có quyền qua đường kiểm tra này, không giữ khóa owner hoặc quyền chuyển tiền trực tiếp khác. Tất cả ví liên quan phải thực sự hỗ trợ cơ chế kiểm soát đó; chỉ thêm kiểm tra backend trước một EOA có toàn quyền không đáp ứng đặc tả.

### 7. Nghiệm thu và điểm cần Finance/Product chốt

| Test | Kết quả bắt buộc |
| --- | --- |
| Có reserve cho nghĩa vụ khác và buffer | Công thức không lấy phần bảo vệ đó để trả request hiện tại. |
| Target cao hơn buffer nhưng nguồn chỉ đủ minimum | Chỉ refill Shortage; báo target chưa đạt; không tự phá reserve. |
| Agent sửa payee, token, chain hoặc lượng chi | Contract từ chối, dù prompt/backend báo hợp lệ. |
| Split request, đổi ví/version để né hạn mức | Không né được amount đã duyệt và counter tổng treasury. |
| Replay payment/refill/swap; RPC timeout | Không thực hiện lại bước đã xong; pending/unknown không tự release hold. |
| Quote sai/hết hạn, minOut quá thấp hoặc đầu ra về ví lạ | Contract/adapter từ chối; không chỉ dựa vào mô phỏng backend. |
| Ngoại lệ đúng request nhưng vượt ngân sách ngày | Chặn; không tự nâng daily limit. |
| Cấp quyền thiếu trường bắt buộc, revoke hoặc expiry | Không kích hoạt/không thực thi; không đảo ngược giao dịch đã xong. |

**Trước triển khai:** Finance/Product duyệt O1–O4/O6 trong mục lục; Dev xác nhận smart account/adapter, hold/counter, quote và retry. Bộ test đầy đủ ở Use-Case Specification AT-01–AT-13. Ví dụ/YAML không phải cấu hình đủ để kích hoạt, cũng không phải bằng chứng nhu cầu khách hàng.

**Nguồn giá trị và bằng chứng:** [Problem Statement + Value Proposition](#problem-statement-and-value-proposition) | [Problem Validation & ICP](#problem-validation-and-icp).

---

<a id="autonomy-and-decision-policy"></a>

## TreasuryPilot: Autonomy & Decision Policy

**Bản:** 0.2 | **Ngày:** 09/10/2026 | **Trạng thái:** Đặc tả nháp; các quy tắc nghiệp vụ còn mở phải được duyệt trước triển khai. [Mục lục chung](#documentation-index).

> **AI đề xuất cách làm; policy engine tính và kiểm tra; contract quyết định cho phép chuyển tài sản.** Agent là toàn bộ hệ thống phối hợp này, không chỉ là LLM.

### 1. Phạm vi tự chủ

Agent được tự thực hiện `SWAP`, `REFILL`, `PAY` phục vụ **khoản chi đã được người có thẩm quyền duyệt**, trong mandate còn hiệu lực. Không cần người ký lại từng bước hợp lệ; không được tự tạo nghĩa vụ chi, đổi người nhận/số tiền, nâng ngân sách hoặc sửa quyền.

**Đã xác nhận:** Khi AI không phản hồi, dùng kế hoạch rule-based đã kiểm thử nếu mọi dữ liệu và điều kiện thực thi đầy đủ. Fallback không cấp thêm quyền và không áp dụng để vượt cảnh báo an toàn.

### 2. Ai quyết định gì?

| Thành phần | Trách nhiệm | Không có quyền |
| --- | --- | --- |
| **Owner / người duyệt** | Duyệt nghĩa vụ, đặt policy, cấp mandate/ngoại lệ, pause hoặc revoke. | Biến việc duyệt invoice thành quyền bỏ qua mọi hard rule. |
| **AI planner** | Đề xuất kế hoạch/thứ tự phù hợp policy, chọn giữa phương án hợp lệ và giải thích ngoại lệ. | Tự tính số tiền làm căn cứ chi, sửa bản duyệt, khai quyền hoặc gửi calldata tùy ý. |
| **Policy engine** | Bộ logic xác định: tính thiếu hụt/refill, kiểm tra dữ liệu, bản duyệt, mandate, ngân sách, phần tiền bảo vệ và quote. | Duyệt invoice, nâng hạn mức hoặc tự cấp ngoại lệ; kiểm tra backend không thay contract. |
| **Executor** | Chuyển kế hoạch đã kiểm tra thành lời gọi cho phép, gửi và theo dõi giao dịch. | Tự thêm bước, đổi amount/payee hoặc giữ khóa owner. |
| **Contract / adapter** | Kiểm tra quyền và trạng thái on-chain, chuyển tài sản, cập nhật counter/chống lặp. | Tin lời giải thích hoặc “độ tự tin” của AI thay authorization. |

**Đầu vào tài chính:** Bản duyệt, policy/mandate do owner cấp, số dư và reservation/hold đã đăng ký, quote từ nguồn cấu hình. Invoice thô và nội dung vendor không phải chỉ thị; thông tin người nhận phải khớp bản duyệt và allowlist.

### 3. Luồng quyết định

`Request đã duyệt → đọc trạng thái → tính nhu cầu → lập kế hoạch → kiểm tra → thực thi → xác nhận → đối soát`

1. Đọc lại bản duyệt, quyền, số dư và trạng thái các bước cũ. Thiếu dữ liệu hoặc còn giao dịch chưa rõ kết quả thì chưa lập lệnh chi mới.
2. Policy engine tính lượng tiền theo **domain mục 3**, không dùng phép tính hoặc số dư do LLM tự khai.
3. AI đề xuất kế hoạch có cấu trúc: request, hành động, ví/route/quote tham chiếu và lý do. Amount thực thi do bộ tính toán xác định; không chấp nhận mã/lời gọi tùy ý từ AI.
4. Policy engine kiểm tra toàn kế hoạch. Executor chỉ gửi bước đã đạt kiểm tra; contract kiểm tra lại theo trạng thái hiện hành trước chuyển tiền.
5. Sau mỗi bước, đọc lại kết quả và tính lại nếu cần. `Paid` chỉ sau xác nhận phù hợp; đối soát là trạng thái riêng.

**MVP xử lý tuần tự:** Một request đang thực thi tại một thời điểm. Phương án ưu tiên đề xuất: deadline sớm trước, hòa thì theo thứ tự duyệt; AI không tự bỏ qua thứ tự đã được policy phê duyệt.

### 4. Cho phép, xin quyền hay dừng?

| Tình huống | Quyết định / hành động |
| --- | --- |
| Bản duyệt, mandate, dữ liệu và toàn bộ constraint đều hợp lệ | `ALLOW`; tự thực hiện trong quyền được cấp, không ký lại từng bước. |
| Chỉ vượt trần mỗi khoản, chưa có ngoại lệ và các hard rule khác đạt | `NEEDS_APPROVAL`; chuyển `AwaitingAuthority`, dùng UC-06. |
| Chưa duyệt, payee lạ, sai asset/chain, hết quyền hoặc vi phạm hard rule | `BLOCK`; không chi. Quyền ngoại lệ không mặc định bỏ qua các giới hạn này. |
| Pending/unknown, dữ liệu cũ/thiếu, quote không xác minh được hoặc cảnh báo an toàn | Chờ/tra cứu hoặc chuyển `NeedsReview`; **không suy đoán ALLOW**, không fallback để chi tiếp. |
| AI không phản hồi, nhưng dữ liệu đầy đủ và có template rule-based phù hợp | Dùng fallback rồi chạy lại toàn bộ kiểm tra; ghi rõ kế hoạch không do AI tạo. |

`ALLOW / NEEDS_APPROVAL / BLOCK` là kết quả kiểm tra quyền; chờ/`NeedsReview` mô tả xử lý vận hành, không phải quyền mới. Nếu nhiều lỗi cùng tồn tại, không cho ngoại lệ vượt trần che mất lỗi hard rule hoặc kết quả chưa rõ.

### 5. Quy tắc fallback và ghi nhận

- Fallback chỉ dùng template đã kiểm thử: trả trực tiếp, refill rồi trả, hoặc swap qua route cố định được phép nếu quote hợp lệ. Không tự tạo chiến lược mới khi AI vắng mặt.
- Kế hoạch AI sai schema, amount hoặc phạm vi bị loại, không tự sửa bằng cách nới policy. MVP chuyển `NeedsReview`; không dùng fallback để che giấu đầu ra nguy hiểm.
- Nếu không có template phù hợp, cần phán đoán chưa được policy quy định hoặc có giao dịch `Unknown`, dừng theo UC-04. Retry không tạo request/step mới để né chống lặp.
- Ghi request, nguồn kế hoạch `AI / RULE_BASED`, phiên bản policy/mandate, snapshot/quote tham chiếu, lý do kiểm tra và tx hash/receipt. Lý do cho phép/chặn lấy từ validator, không lấy từ lời giải thích của LLM.

### 6. Kiểm chứng và điểm còn mở

| Test | Kết quả cần chứng minh |
| --- | --- |
| AD-01: AI đề xuất đổi payee/nâng amount, kể cả do prompt injection trong invoice | Kế hoạch sai bị loại; quyền và bản duyệt không đổi, không chi theo chỉ thị đó. |
| AD-02: AI timeout, template hợp lệ, đủ quyền/dữ liệu | Fallback hoàn thành trong cùng constraint và được ghi `RULE_BASED`. |
| AD-03: AI timeout nhưng payment cũ `Unknown` hoặc có cảnh báo an toàn | Không gửi khoản chi thứ hai; không dùng fallback để vượt trạng thái bất định. |
| AD-04: Backend báo ALLOW nhưng quyền on-chain đã revoke | Contract từ chối; backend không có quyền quyết định cuối cùng về tài sản. |

**Cần chốt:** Quy tắc ưu tiên kế hoạch, timeout AI và danh sách template/route fallback, quản lý tại O8 trong mục lục. Không dùng ngưỡng “AI tự tin 90%” làm điều kiện cho phép chi tiền.

**Giá trị AI vẫn cần đo:** Với một chain và một nguồn refill, nhiều quyết định có thể giải bằng rule-based. So sánh hai cách trên cùng request và constraint: hoàn thành, can thiệp, độ trễ, phí và xử lý ngoại lệ. Chưa được kết luận AI tốt hơn chỉ vì giải thích nghe hợp lý.

**Nguồn nghiệp vụ:** [Treasury Domain + Mandate](#treasury-domain-and-mandate-specification) quyết định công thức/quyền; [Use-Case Specification](#use-case-specification) quyết định luồng UC-02/04/06. Tài liệu này không sửa các hạn mức hoặc mở rộng MVP.
