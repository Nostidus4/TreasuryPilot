# TreasuryPilot: Business Rules (Luật nghiệp vụ)

**Nguồn chuẩn:** `docs/BUSINESS_RULES.md` · **Trạng thái:** Đã qua cổng G1

Luật nghiệp vụ là **bất biến của doanh nghiệp**, không phụ thuộc giao diện hay cách cài đặt. Cột "Thực thi" cho biết luật được thực thi ở đâu:

- **C** = smart contract (cưỡng chế cứng, backend không vượt qua được)
- **B** = backend / policy engine (xác định)
- **U** = UI (chỉ hướng dẫn)

**Không luật quan trọng nào chỉ được thực thi bằng LLM hay prompt.** Các giá trị đánh dấu *(mặc định)* lấy từ phương án đề xuất trong tài liệu gốc, đã chấp nhận theo quyết định Q8.

## 1. Thẩm quyền & duyệt

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-001 | Không thanh toán khi chưa có bản duyệt hợp lệ của người duyệt có thẩm quyền trên đúng các trường thanh toán. | C, B | R1, D1 |
| BR-002 | Agent không bao giờ: tạo nghĩa vụ chi, đổi payee hoặc số tiền, nâng hạn mức, sửa chính sách, thêm payee, hay duyệt hóa đơn. | C, B | D1 |
| BR-003 | Bản duyệt gắn các trường: request_id, hash hóa đơn, fingerprint, chainId, contract, treasury, ví trả, tài sản, payee, số tiền, deadline, hash điều khoản đã xác nhận, hạn dùng. Đổi bất kỳ trường nào → bản duyệt mất hiệu lực. | C, B | UC-01, R1 |
| BR-004 | Contract kiểm tra bản duyệt bằng mật mã (EIP-712, gắn domain chain và contract). Cờ "approved" trong backend không bao giờ đủ. | C | R1 |
| BR-005 | Maker-checker: người tạo hoặc người sửa cuối không được duyệt. Nếu bật solo mode thì phải gắn cờ rõ và audit. | B (C: danh sách approver) | Q13 |
| BR-006 | Vai trò ký (Owner, Approver, Guardian) chỉ hành động qua ví đã liên kết. Đăng nhập app không có nghĩa là có quyền on-chain. | C, B | GA p.11 |

## 2. Mandate & cấu trúc quyền

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-010 | Quyền thực thi = **bản duyệt hợp lệ VÀ mandate đang hiệu lực VÀ bước hiện tại thỏa mọi ràng buộc**. Ba điều kiện riêng biệt, không cái nào thay cho cái nào. | C, B | Domain §4 |
| BR-011 | Hành động của agent chỉ gồm `REFILL`, `PAY`, `SWAP` (theo mandate). Cấm: lời gọi tùy ý, `approve` vô hạn, `delegatecall`, đổi owner/module/guard/fallback, calldata router không kiểm tra. | C | Domain §4.1 |
| BR-012 | M1 chỉ refill theo đường trong mandate, từ `T` sang ví vận hành. Refill giữa các ví vận hành là `Later` và cần khai báo đường rõ ràng. | C | D4 |
| BR-013 | Chỉ PAY cho payee nằm trong allowlist on-chain và đã hết thời gian chờ. Payee lạ hoặc đang chờ → BLOCK, kể cả khi có ngoại lệ. | C | D3, S2 |
| BR-014 | Mandate thiếu trường bắt buộc không được kích hoạt. Trường bắt buộc gồm: trần gas, buffer/mục tiêu từng ví, tham số router và quote nếu bật SWAP, thời hạn. | B, C | Domain §4.2 |
| BR-015 | Tạo, sửa, tạm dừng, thu hồi mandate chỉ có hiệu lực sau khi được xác nhận on-chain. Trước đó, trạng thái cũ vẫn áp dụng. | C, B | UC-01, UC-05 |
| BR-016 | Phiên bản mandate mới làm mất hiệu lực các ngoại lệ còn tồn và **không reset bộ đếm**. | C | Domain §6.2 |
| BR-017 | Thời gian chờ payee mặc định: 24 giờ trên production, 5 phút khi demo. Đổi địa chỉ = tạo mục payee mới và bắt đầu lại thời gian chờ. | C | S2 *(mặc định)* |
| BR-018 | Chế độ được bảo vệ yêu cầu bao phủ module đầy đủ. Nếu có module khác chuyển được tiền, tạm ngưng tự thực thi cho đến khi Owner xác nhận rõ. | B | GA p.20 |

## 3. Hạn mức & bộ đếm

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-020 | Hạn mức tính theo **lượng token ở đơn vị nhỏ nhất**, không theo USD. Không mặc định 1 stablecoin = 1 USD. | C | D2 |
| BR-021 | Cửa sổ ngày là **ngày lịch UTC**: `day = floor(block.timestamp / 86400)`. Không phải 24 giờ trượt. | C | O3 *(mặc định)* |
| BR-022 | Bộ đếm theo khóa `(treasury, hành động, tài sản, ngày)`, dùng chung mọi ví và mọi phiên bản mandate. Đổi ví hay đổi phiên bản không reset. | C | R3 |
| BR-023 | Ngân sách PAY, REFILL và đầu vào SWAP tách riêng. Refill không dùng ngân sách trả nhà cung cấp, nhưng dùng ngân sách refill. | C | R3 |
| BR-024 | Trả đủ số tiền đã duyệt trong một lần PAY. Cấm chia nhỏ để né trần và cấm trả một phần hóa đơn. | C, B | Domain §4.1, §3.3 |
| BR-025 | Giao dịch revert không làm tăng bộ đếm; phí gas vẫn được ghi và báo. | C, B | Domain §5.1, §5.4 |
| BR-026 | Bước pending qua nửa đêm UTC được kiểm tra theo ngân sách của ngày thực thi; không mang quyền chi của ngày cũ sang ngày mới. | C | Domain §5.1 |

## 4. Thanh khoản

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-030 | Không giao dịch nào qua đường agent được làm ví xuống dưới buffer tối thiểu (`F`), kể cả ví nguồn `T` (`F_T`). | C | R4 |
| BR-031 | Số dư mục tiêu (`H ≥ F`) là mục tiêu mềm. Không refill chỉ để đạt mục tiêu khi không thiếu hụt. | B | Domain §3.2 |
| BR-032 | `Shortage = max(0, ProtectedOther + D + F − B)`; `PreferredRefill = max(0, ProtectedOther + D + H − B)`; `Cap = min(SourceCapacity, RemainingRefillBudget, PerRefillLimit)`. Nếu Cap ≥ Preferred → refill Preferred. Nếu Shortage ≤ Cap < Preferred → refill Shortage và báo chưa đạt mục tiêu. | B | Domain §3 |
| BR-033 | Nếu `Cap < Shortage` → DỪNG và báo. Không refill một phần, không trả một phần. | B | Domain §3.3 |
| BR-034 | Mọi số tiền dùng để thực thi đều do bộ tính xác định tính ra. LLM không bao giờ tính hoặc khẳng định số tiền, số dư hay quyền. | B | Autonomy §2–3 |
| BR-035 | Tiền đã giữ chỗ cho nghĩa vụ khác (`R_other`) và tiền đang khóa (`L_other`) được bảo vệ khi lập kế hoạch. M1 thực thi ở backend; Later thực thi on-chain. | B (Later: C) | Domain §3.1, §5.2 |

## 5. Ngoại lệ

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-040 | Ngoại lệ một lần **chỉ** nâng trần mỗi khoản. Không nâng trần ngày, buffer, allowlist/thời gian chờ payee, tài sản, chain hay thời hạn. | C | O2 *(mặc định)* |
| BR-041 | Ngoại lệ gắn: request_id, mandate id và phiên bản, treasury, chain, contract, ví trả, payee, tài sản, đúng số tiền, hạn dùng, nonce. Được dùng hết cùng lúc với thanh toán, chỉ một lần. | C | Domain §6.1 |
| BR-042 | Toàn bộ số tiền của khoản trả bằng ngoại lệ vẫn tính vào ngân sách PAY trong ngày. | C | Domain §6.1 |
| BR-043 | Chỉ Owner được cấp ngoại lệ. AI chỉ được soạn yêu cầu, không bao giờ cấp. | C, B | D3 |

## 6. Lập kế hoạch & thực thi

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-050 | Thực thi tuần tự: tại một thời điểm, mỗi treasury chỉ có tối đa một chuỗi bước của một yêu cầu đang chạy. | B | Use-Case §3 |
| BR-051 | Đọc lại trạng thái (số dư, mandate, bộ đếm, trạng thái payee) trước mỗi bước. Không dựa vào snapshot chụp trước khi bước trước làm trạng thái thay đổi. | B | Use-Case §3 |
| BR-052 | Hàm mục tiêu lập lịch, theo thứ tự ưu tiên tuyệt đối: (1) không vi phạm luật cứng; (2) đạt mọi deadline có thể đạt; (3) tối đa chiết khấu đã xác nhận trừ phí phạt; (4) tối thiểu số giao dịch và phí. Bằng điểm thì theo thứ tự duyệt. Baseline B1 là deadline sớm trước. | B | N2, O8 *(mặc định)* |
| BR-053 | Yêu cầu chỉ là `Paid` khi giao dịch PAY đạt đủ độ sâu xác nhận đã cấu hình. `Paid` khác `Matched`. | B | UC-03 |
| BR-054 | Kế hoạch nhiều bước không có tính nguyên tử. Bước đã xong được ghi là đã xong; không bao giờ âm thầm hoàn tác hay làm lại. | B | Domain §3.3 |
| BR-055 | Fallback rule-based chỉ dùng khi **đủ cả năm điều kiện**: AI không phản hồi, dữ liệu đầy đủ, có mẫu đã kiểm thử khớp, không có giao dịch Unknown, không có cảnh báo an toàn. Ghi là `RULE_BASED`. | B | D6 |
| BR-056 | Kế hoạch AI sai hoặc vượt mandate bị loại và chuyển NeedsReview. Không bao giờ sửa bằng cách nới chính sách, và không che bằng fallback. | B | Autonomy §5 |
| BR-057 | Lý do cho phép hay chặn hiển thị cho người dùng phải lấy từ validator. Văn bản của AI hiển thị riêng, có nhãn "giải thích". | B, U | Autonomy §5 |
| BR-058 | Không dùng điểm tự tin của AI làm điều kiện cấp quyền. | B | Autonomy §6 |
| BR-059 | Thực thi phải có attestation trên đúng kế hoạch (planHash, phiên bản chính sách, nonce, hạn dùng). Bước khác với kế hoạch đã ký xác nhận thì bị từ chối. | B (C nếu kiểm on-chain) | GA p.21–22 |

## 7. Phục hồi & khẩn cấp

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-060 | Pending, timeout hay mất kết nối **không** có nghĩa là thất bại. Không tạo yêu cầu mới, không trả lần hai cho đến khi biết kết quả lần trước. Còn thao tác Unknown thì treasury bị chặn thực thi. | B, C (chống replay) | R8 |
| BR-061 | Thử lại phải dùng lại đúng request_id, step_id, operation id và idempotency key. | B, C | UC-04 |
| BR-062 | Pause/revoke chặn thực thi mới kể từ khi có hiệu lực on-chain. Giao dịch đã xác nhận không bao giờ bị đảo ngược, và sản phẩm không bao giờ hứa đảo ngược. | C | R9 |
| BR-063 | Khi có yêu cầu tạm dừng, backend ngừng lập kế hoạch và ngừng gửi ngay lập tức, kể cả trước khi lệnh dừng được xác nhận on-chain. | B | R9 |
| BR-064 | Chỉ Owner được chạy lại. Guardian chỉ được tạm dừng. | C | GA p.23 |
| BR-065 | Circuit breaker mặc định tự dừng backend và báo Owner khi có một trong các dấu hiệu: ít nhất 3 lần contract từ chối trong 10 phút; AI đề xuất kế hoạch vượt mandate; mức bao phủ giảm; hậu điều kiện bị lệch. | B | S7 *(mặc định)* |

## 8. Hóa đơn & dữ liệu

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-070 | Nội dung hóa đơn và nhà cung cấp là **dữ liệu** không tin cậy, không bao giờ là chỉ thị cho agent. | B | Use-Case §2 |
| BR-071 | Trùng fingerprint (nhà cung cấp, số hóa đơn, số tiền, tài sản) → backend chặn gửi duyệt, contract chặn PAY lần hai. Muốn ghi đè phải có cờ do Owner ký nằm trong bản duyệt. | C, B | S3 |
| BR-072 | Địa chỉ trong hóa đơn khác payee đã đăng ký hoặc khác lịch sử → cờ mức cao. Đổi địa chỉ payee phải do Owner cập nhật và chờ lại từ đầu. Hóa đơn không bao giờ đổi được payee. | B, C | N1, S2 |
| BR-073 | Hóa đơn M1 phải tính bằng đúng stablecoin thanh toán của treasury. | B | Q20 |
| BR-074 | Chỉ lưu hash/commitment trên chain. Tài liệu hóa đơn và dữ liệu cá nhân ở off-chain, lưu riêng tư. | B | Use-Case §2 |
| BR-075 | Trường và điều khoản AI trích xuất chỉ là bản nháp cho đến khi người xác nhận. Chỉ điều khoản đã xác nhận mới ảnh hưởng lịch trả. | B | N1 |

## 9. Gas, swap & tài sản

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-080 | Gas của executor được nạp trước. Cấp gas từ ví treasury có trần riêng. Gas native không bao giờ là tài sản dùng để PAY cho nhà cung cấp. Trần cấp gas không phải trần của phí mạng thực tế. | C, B | Domain §5.4, O6 *(mặc định)* |
| BR-081 | Swap chỉ qua adapter, router và cặp tài sản trong allowlist, trong ngân sách swap, với quote mới từ nguồn đã cấu hình. `minOut = ceil(quoteOut × (10000 − maxSlippageBps) / 10000)` do engine tính; agent không hạ được. | C, B | R5 |
| BR-082 | Allowance cho swap đúng bằng lượng vào và đặt về 0 trong cùng giao dịch. | C | GA p.22 |
| BR-083 | Tài sản định danh bằng `(chainId, địa chỉ)`. Decimals kiểm tra on-chain. Mọi phép tính dùng số nguyên ở đơn vị nhỏ nhất. | B, C | Domain §2 |

## 10. Tuân thủ & nền tảng

| ID | Luật | Thực thi | Nguồn |
|---|---|---|---|
| BR-085 | Payee trúng danh sách trừng phạt hoặc chặn thì không đăng ký và không trả được. Dịch vụ sàng lọc lỗi khi đăng ký → không cho đăng ký. Khi PAY được dùng kết quả sạch còn trong TTL, nếu không có thì chặn. | B | S6 |
| BR-090 | Không có: giao dịch đầu cơ, lợi suất, cho vay, staking, quản lý danh mục. Contract không có hành động nào kiểu này. | C | D5 |
| BR-091 | TreasuryPilot không bao giờ giữ tiền của khách. Tiền nằm trong Safe do khách sở hữu. | C (kiến trúc) | D5 |
| BR-092 | Khóa owner không bao giờ đi vào TreasuryPilot. Khóa executor nằm trong signer service riêng. Tiến trình LLM không nhận bất kỳ bí mật nào. | Kiến trúc | Domain §6.2 |
| BR-093 | Dữ liệu tổ chức này không bao giờ truy cập được từ tổ chức khác. | B | Q3 |
| BR-094 | PlatformAdmin không có khả năng ký hay chuyển tiền của khách. | Kiến trúc | Q13 |
| BR-095 | Tài sản, router và dữ liệu test luôn được ghi nhãn. Công cụ kịch bản từ chối chain không nằm trong allowlist (mainnet). Bằng chứng không bao giờ chứa tx hash bịa. | B | AT §6 |
| BR-096 | Phân loại khi đối soát: refill = chuyển nội bộ; swap = chuyển đổi; pay = chi phí bên ngoài. `Matched` chỉ khi bằng chứng khớp. | B | UC-03 |
| BR-097 | Mọi thao tác ảnh hưởng tiền hoặc quyền đều ghi audit. Ghi audit lỗi → thao tác tài chính thất bại an toàn. | B | S6 |
