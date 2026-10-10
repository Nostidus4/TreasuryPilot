# TreasuryPilot: Yêu cầu chức năng (FR)

**Nguồn chuẩn:** `docs/FUNCTIONAL_REQUIREMENTS.md` · **Trạng thái:** Đã qua cổng G1

Mỗi yêu cầu kiểm thử được và truy ngược về một feature (`F-xxx`) và về business rule (`BR-xxx`) khi có. Phase và độ ưu tiên của FR lấy theo feature của nó, trừ khi có ghi chú. FR đánh dấu *(Later)* thuộc giai đoạn sau M1.

## FR-0xx · Định danh & phân quyền

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-001 | Hệ thống phải cho phép đăng ký và đăng nhập bằng email, xác minh qua link một lần hoặc mật khẩu. | F-001 | |
| FR-002 | Hệ thống phải giới hạn tần suất xác thực theo IP và theo tài khoản. | F-001 | |
| FR-003 | Hệ thống phải hết hạn phiên sau thời gian không hoạt động (cấu hình được) và sau thời hạn tuyệt đối. | F-001 | |
| FR-004 | Hệ thống phải cho phép liên kết địa chỉ EVM bằng cách kiểm tra chữ ký SIWE (EIP-4361) có nonce dùng một lần, domain và chainId. | F-002 | BR-006 |
| FR-005 | Hệ thống phải kiểm tra chữ ký ERC-1271 cho ví contract. | F-002 | |
| FR-006 | Hệ thống phải từ chối liên kết địa chỉ đã thuộc user khác. | F-002 | |
| FR-007 | Hệ thống phải cho phép user đã đăng nhập tạo tổ chức và gán vai trò OrgAdmin cho user đó. | F-003 | |
| FR-008 | Hệ thống phải cô lập mọi dữ liệu theo tổ chức và từ chối truy cập chéo ở mọi endpoint. | F-003 | BR-093 |
| FR-009 | Hệ thống phải hiển thị checklist onboarding (thành viên → treasury → mandate → payee → hóa đơn đầu tiên) và lưu tiến độ. | F-003 | |
| FR-010 | Hệ thống phải cho phép OrgAdmin mời thành viên qua email, lời mời có hạn, gán một hoặc nhiều vai trò. | F-004 | |
| FR-011 | Hệ thống phải hỗ trợ 8 vai trò (Owner, Approver, Operator, Finance, Guardian, OrgAdmin, Auditor, PlatformAdmin) và kiểm tra quyền ở mọi API. | F-004 | |
| FR-012 | Vai trò ký chỉ có hiệu lực khi thành viên đã liên kết ví. | F-004 | BR-006 |
| FR-013 | Không được xóa OrgAdmin hoặc Owner cuối cùng của tổ chức. | F-004 | |
| FR-014 | Hệ thống phải từ chối việc duyệt nếu người duyệt là người tạo hoặc người sửa cuối. | F-005 | BR-005 |
| FR-015 | Hệ thống phải hỗ trợ "solo mode" do Owner bật, được ghi trên mọi bản ghi liên quan và trong audit. | F-005 | BR-005 |
| FR-016 | *(Later)* Bắt buộc yếu tố xác thực thứ hai (TOTP/WebAuthn) cho vai trò ký; yêu cầu xác thực lại khi làm thao tác nhạy cảm. | F-006 | |
| FR-017 | *(Later)* Hỗ trợ SSO OIDC/SAML, ánh xạ nhóm sang vai trò, gỡ quyền trong 5 phút. | F-007 | |

## FR-1xx · Treasury & ví

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-101 | Owner hoặc OrgAdmin tạo được treasury gồm một chain hỗ trợ, một stablecoin, một ví nguồn `T` và một hoặc nhiều ví vận hành. | F-010 | |
| FR-102 | Hệ thống phải từ chối treasury có ví trùng, ví khác chain, hoặc ví không phải Safe ở chế độ được bảo vệ. | F-010 | BR-018 |
| FR-103 | Hệ thống phải đọc owners, threshold, modules, guard của từng Safe và lưu snapshot có tham chiếu block. | F-011 | |
| FR-104 | Hệ thống nên hỗ trợ tạo Safe mới ngay trên UI bằng giao dịch do Owner ký. | F-011 | |
| FR-105 | Hệ thống phải phát hiện thay đổi cấu hình Safe trong một chu kỳ polling và phát sự kiện về mức bao phủ. | F-011, F-012 | |
| FR-106 | Hệ thống phải tính mức bao phủ (COMPLETE / PARTIAL / UNKNOWN) bằng cách so module đang bật với allowlist hash code. | F-012 | BR-018 |
| FR-107 | Hệ thống phải tạm ngưng tự thực thi của treasury có bao phủ chưa COMPLETE, trừ khi Owner đã xác nhận rõ. | F-012 | BR-018 |
| FR-108 | Hệ thống phải định danh tài sản bằng `(chainId, địa chỉ)`, kiểm tra decimals on-chain và ghi nhãn tài sản test. | F-013 | BR-083 |
| FR-109 | Mọi số tiền trong lưu trữ, API và contract phải là số nguyên không âm ở đơn vị nhỏ nhất. | F-013 | BR-083 |
| FR-110 | *(Later)* Hỗ trợ nhiều treasury mỗi tổ chức trên các chain khác nhau, bộ đếm tách biệt. | F-014 | |
| FR-111 | *(Later)* Hỗ trợ nhiều stablecoin trong một treasury, hạn mức theo tài sản. | F-015 | |

## FR-2xx · Mandate & chính sách

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-201 | Chỉ Owner tạo được bản nháp mandate. Mandate gồm: hành động, ví, đường refill, payee, trần mỗi khoản và mỗi ngày theo hành động và tài sản, buffer và mục tiêu theo ví, cấu hình swap, trần gas, thời hạn. | F-020 | BR-002 |
| FR-202 | Hệ thống phải từ chối bản nháp thiếu hoặc không nhất quán (mục tiêu < buffer; thiếu trần gas; bật SWAP mà thiếu router). | F-020 | BR-014 |
| FR-203 | Hệ thống phải hiển thị bản tóm tắt dễ đọc và so sánh với phiên bản đang Active trước khi ký. | F-020, F-134 | |
| FR-204 | Hệ thống phải tạo giao dịch Safe để Owner ký kích hoạt hoặc cập nhật, và chỉ đánh dấu Active khi trạng thái on-chain đã xác nhận khớp với bản nháp. | F-021 | BR-015 |
| FR-205 | Hệ thống phải lưu lịch sử phiên bản mandate bất biến. | F-021 | |
| FR-206 | Contract phải vô hiệu các ngoại lệ còn tồn khi đổi phiên bản và không reset bộ đếm. | F-021 | BR-016 |
| FR-207 | Contract phải từ chối thực thi sau thời hạn mandate. | F-021 | |
| FR-208 | Owner đăng ký được payee vào allowlist on-chain với `activeFrom = bây giờ + thời gian chờ`. | F-022 | BR-013, BR-017 |
| FR-209 | Contract phải từ chối PAY cho payee chưa đăng ký, đã vô hiệu, hoặc đang trong thời gian chờ. | F-022 | BR-013 |
| FR-210 | Hệ thống phải coi việc đổi địa chỉ payee là mục mới: bắt đầu lại thời gian chờ và vô hiệu mục cũ. | F-022 | BR-017 |
| FR-211 | Operator đề xuất được payee; Owner xem và ký. | F-022 | |
| FR-212 | Contract phải thực thi trần mỗi khoản và mỗi ngày theo khóa `(treasury, hành động, tài sản, ngày UTC)`. | F-023 | BR-020–022 |
| FR-213 | Contract chỉ tăng bộ đếm khi thực thi thành công, trong cùng giao dịch. | F-023 | BR-025 |
| FR-214 | Contract phải đánh giá bước pending theo ngân sách của ngày thực thi. | F-023 | BR-026 |
| FR-215 | Contract phải từ chối PAY hoặc REFILL làm ví liên quan xuống dưới buffer. | F-024 | BR-030 |
| FR-216 | Owner cấp được ngoại lệ một lần qua EIP-712, gắn các trường nêu ở BR-041. | F-025 | BR-041, BR-043 |
| FR-217 | Contract chỉ chấp nhận ngoại lệ để nâng trần mỗi khoản, dùng hết ngoại lệ cùng lúc với PAY, và tính đủ số tiền vào trần ngày. | F-025 | BR-040, BR-042 |
| FR-218 | Owner hoặc Guardian yêu cầu tạm dừng được; backend phải ngừng lập kế hoạch và ngừng gửi ngay. | F-026 | BR-063 |
| FR-219 | Contract phải từ chối thực thi khi mandate đang tạm dừng hoặc đã bị thu hồi. | F-026 | BR-062 |
| FR-220 | Contract chỉ cho Owner chạy lại hoặc thu hồi. | F-026 | BR-064 |
| FR-221 | UI phải phân biệt "đã yêu cầu dừng" và "đã dừng on-chain", và liệt kê các giao dịch đang pending. | F-026 | |
| FR-222 | Hệ thống phải tự dừng backend và báo Owner khi vượt ngưỡng circuit breaker. | F-027 | BR-065 |
| FR-223 | *(Later)* Contract lưu và thực thi tiền giữ chỗ và tiền khóa cho nghĩa vụ đã đăng ký. | F-028 | BR-035 |
| FR-224 | *(Later)* Contract thực thi ngưỡng duyệt k trên n theo khoảng số tiền. | F-029 | |

## FR-3xx · Hóa đơn & yêu cầu chi

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-301 | Operator tạo được yêu cầu chi thủ công: số hóa đơn, payee, tài sản, số tiền, ví trả, ngày đến hạn, điều khoản (tùy chọn), tệp đính kèm. | F-030 | |
| FR-302 | Hệ thống phải từ chối yêu cầu có tài sản khác stablecoin của treasury (M1). | F-030 | BR-073 |
| FR-303 | Hệ thống nhận tệp PDF, PNG, JPG tối đa 10 MB, lưu riêng tư, và tạo bản nháp có các trường do AI trích xuất, mỗi trường kèm tham chiếu nguồn. | F-031 | BR-074, BR-075 |
| FR-304 | Khi trích xuất lỗi hoặc quá thời gian, chuyển sang nhập tay và hiển thị tài liệu bên cạnh. | F-031 | |
| FR-305 | Hệ thống không bao giờ đổi địa chỉ payee đã đăng ký dựa trên nội dung trích từ hóa đơn. | F-031 | BR-072 |
| FR-306 | Hệ thống nhập CSV theo mẫu, kiểm tra từng dòng độc lập, tạo bản nháp cho dòng hợp lệ và xuất báo cáo lỗi theo dòng. | F-032 | |
| FR-307 | Hệ thống phải vô hiệu công thức bảng tính độc hại trong CSV nhập và xuất. | F-032, F-073 | |
| FR-308 | *(Later)* Mỗi tổ chức có một địa chỉ email nhận hóa đơn; email chuyển thành bản nháp, có kiểm tra người gửi. | F-033 | |
| FR-309 | *(Later)* Có API tạo bản nháp, idempotent và giới hạn theo phạm vi quyền. | F-034 | |
| FR-310 | Hệ thống trích điều khoản thanh toán (phần trăm chiết khấu, hạn chiết khấu, ngày đến hạn, lịch phạt trễ, ghi chú ưu tiên) thành dạng có cấu trúc để người xác nhận. | F-035 | BR-075 |
| FR-311 | Bộ lập lịch chỉ dùng điều khoản đã được người xác nhận. | F-035 | BR-075 |
| FR-312 | Hệ thống gắn cờ khi: địa chỉ khác danh bạ hoặc lịch sử; số tiền bất thường; trùng fingerprint; có văn bản giống mệnh lệnh; sai tiền tệ hoặc chain; ngày đến hạn bất thường. Mỗi cờ có mức độ, bằng chứng và mã lý do. | F-036 | BR-072 |
| FR-313 | Approver phải xác nhận đã đọc các cờ mức cao trước khi ký. | F-036, F-131 | |
| FR-314 | Hệ thống tính fingerprint đã chuẩn hóa và cảnh báo trùng khi nhập. | F-037 | BR-071 |
| FR-315 | Contract phải từ chối PAY có fingerprint đã được trả, trừ khi bản duyệt có cờ ghi đè do Owner ký. | F-037 | BR-071 |
| FR-316 | Approver ký được dữ liệu EIP-712 gắn các trường ở BR-003; hệ thống chỉ ghi nhận sau khi đã kiểm tra chữ ký. | F-038 | BR-003, BR-004 |
| FR-317 | Hệ thống phải vô hiệu bản duyệt khi bất kỳ trường được ký nào thay đổi. | F-038 | BR-003 |
| FR-318 | Contract kiểm tra chữ ký duyệt theo danh sách approver hiện tại tại thời điểm PAY. | F-038 | BR-004 |
| FR-319 | Hệ thống thực thi máy trạng thái của yêu cầu chi và từ chối chuyển trạng thái không hợp lệ. | F-039 | |
| FR-320 | Không được hủy yêu cầu khi giao dịch PAY đang pending hoặc unknown. | F-039 | BR-060 |
| FR-321 | *(Later)* Sinh bản nháp định kỳ, mỗi bản đều phải duyệt. | F-040 | BR-002 |
| FR-322 | *(Later)* Hỗ trợ hóa đơn fiat, có số stablecoin tối đa đã duyệt, biên tỷ giá và kiểm tra depeg. | F-041 | |

## FR-4xx · Lập kế hoạch

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-401 | Hệ thống đọc số dư, trạng thái mandate, bộ đếm, trạng thái payee, cấu hình module tại cùng một block, ghi số block, hash, thời điểm và mức bao phủ. | F-050 | BR-051 |
| FR-402 | Hệ thống từ chối lập kế hoạch hoặc thực thi trên snapshot cũ quá ngưỡng hoặc có bao phủ khác COMPLETE. | F-050 | |
| FR-403 | Hệ thống tính Available, FundingDeficit, Shortage, PreferredRefill, SourceCapacity, Cap theo công thức domain, bằng số nguyên. | F-051 | BR-032, BR-034 |
| FR-404 | Hệ thống dừng và báo khi `Cap < Shortage`. | F-051 | BR-033 |
| FR-405 | Hệ thống tính lịch khả thi tối ưu theo hàm mục tiêu BR-052, báo các ràng buộc đang chặn và các mục không khả thi kèm lý do. | F-052 | BR-052 |
| FR-406 | Hệ thống lấy đề xuất kế hoạch từ AI dưới dạng có cấu trúc (thứ tự, hoãn, yêu cầu ngoại lệ, lý do, evidence id); AI chỉ dùng tool chỉ đọc. | F-053 | BR-002 |
| FR-407 | Hệ thống chấm đề xuất AI bằng hàm mục tiêu xác định, chọn kế hoạch khả thi tốt hơn và ghi lại so sánh. | F-053 | BR-052 |
| FR-408 | Hệ thống loại kế hoạch AI sai hoặc vượt mandate và chuyển NeedsReview. | F-053 | BR-056 |
| FR-409 | Hệ thống dùng mẫu rule-based đã kiểm thử khi AI không phản hồi, chỉ trong điều kiện BR-055, và ghi `RULE_BASED`. | F-054 | BR-055 |
| FR-410 | Hệ thống kiểm tra mọi kế hoạch và từng bước, trả về ALLOW / NEEDS_APPROVAL / BLOCK kèm mã lý do. | F-055 | BR-010 |
| FR-411 | Hệ thống không bao giờ trả ALLOW khi thiếu dữ liệu bắt buộc hoặc còn thao tác Unknown. | F-055 | BR-060 |
| FR-412 | Hệ thống ký attestation EIP-712 cho kế hoạch được ALLOW, gắn planHash, ID yêu cầu và ID bước, phiên bản chính sách, executor, hạn dùng, nonce, evidence digest. | F-056 | BR-059 |
| FR-413 | Hệ thống từ chối thực thi bước khác với kế hoạch đã ký xác nhận, hoặc có attestation đã hết hạn. | F-056 | BR-059 |
| FR-414 | Hệ thống soạn yêu cầu ngoại lệ cho Owner khi NEEDS_APPROVAL, con số lấy từ engine. | F-057 | BR-043 |
| FR-415 | Hệ thống nên dự phóng runway 7 ngày cho từng ví từ các nghĩa vụ đã duyệt và gợi ý refill trước trong hạn mức. | F-058 | |
| FR-416 | *(Later)* Hỗ trợ refill giữa các ví vận hành theo mandate mà không làm thiếu nghĩa vụ của ví nguồn. | F-059 | BR-012 |

## FR-5xx · Thực thi

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-501 | Hệ thống tự kích hoạt lập kế hoạch khi yêu cầu đã duyệt vào cửa sổ thực thi hoặc khi có sự kiện liên quan, không cần người thao tác. | F-060 | |
| FR-502 | Hệ thống giữ khóa single-flight theo treasury, chỉ một chuỗi bước chạy tại một thời điểm. | F-060, F-061 | BR-050 |
| FR-503 | Hệ thống bỏ qua trigger khi treasury đang dừng, bao phủ chưa COMPLETE, hoặc còn thao tác Unknown. | F-060 | BR-060, BR-063 |
| FR-504 | Operator có nút "chạy ngay", vẫn qua cùng các kiểm tra. | F-060 | |
| FR-505 | Executor mô phỏng đúng lời gọi trước khi ký; mô phỏng revert thì không broadcast. | F-061 | |
| FR-506 | Executor lưu thao tác (nonce, txHash) trước khi broadcast (outbox); giao dịch thay thế được theo dõi như cùng một thao tác. | F-061 | BR-061 |
| FR-507 | Signer service chỉ ký payload có attestation hợp lệ của validator. | F-061 | BR-092 |
| FR-508 | Contract chỉ thực thi REFILL theo đường trong mandate, trong hạn mức refill và buffer ví nguồn, rồi đánh dấu ID bước đã dùng. | F-062 | BR-012, BR-030 |
| FR-509 | Contract chỉ thực thi PAY sau khi kiểm tra đủ: bản duyệt, trạng thái payee, fingerprint, yêu cầu chưa dùng, hạn mức hoặc ngoại lệ, buffer, không đang dừng. Sau đó đánh dấu đã dùng và cập nhật bộ đếm trong cùng giao dịch. | F-063 | BR-001, BR-010 |
| FR-510 | Contract phát event cho REFILL, PAY, SWAP, dùng ngoại lệ, tạm dừng, chạy lại, thay đổi mandate; event có ID yêu cầu và ID bước. | F-062, F-063, F-120 | |
| FR-511 | Contract chỉ thực thi SWAP qua adapter, router, cặp trong allowlist, trong ngân sách swap, với minOut do engine tính, allowance đúng lượng và đặt về 0. | F-064 | BR-081, BR-082 |
| FR-512 | Router test ở M1 phải được ghi nhãn ở mọi nơi. | F-064 | BR-095 |
| FR-513 | *(Later)* Contract kiểm tra quote có chữ ký từ nguồn trong allowlist cho swap production. | F-065 | |
| FR-514 | Hệ thống ghi phí thực tế của mọi giao dịch, kể cả revert, và cảnh báo khi gas của executor dưới ngưỡng. | F-066 | BR-025, BR-080 |
| FR-515 | Hệ thống dừng và nêu rõ lý do khi không còn nguồn gas nào. | F-066 | |
| FR-516 | *(Later)* Bridge qua bridge trong allowlist, không tính tiền đang chuyển, không gửi lại khi timeout. | F-067 | |

## FR-6xx · Xác minh & đối soát

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-601 | Hệ thống theo dõi giao dịch qua `NotSubmitted / Submitted / Pending / Confirmed / Reverted / Unknown`, độ sâu xác nhận cấu hình theo chain. | F-070 | BR-053 |
| FR-602 | Hệ thống phát hiện reorg bằng block hash và đánh giá lại các trạng thái bị ảnh hưởng. | F-070 | |
| FR-603 | Hệ thống kiểm tra hậu điều kiện của từng bước đã xác nhận (biến động số dư, cờ đã dùng, allowance bằng 0, bộ đếm) và ghi PASSED / DISCREPANCY / UNKNOWN. | F-071 | |
| FR-604 | Chênh lệch được chuyển vào NeedsReview và gửi tín hiệu tới circuit breaker. | F-071 | BR-065 |
| FR-605 | Hệ thống liên kết mỗi yêu cầu với mọi giao dịch và phí của nó, phân loại thành chuyển nội bộ, chuyển đổi hoặc chi phí bên ngoài. | F-072 | BR-096 |
| FR-606 | Hệ thống duy trì trạng thái đối soát `NotReady / Pending / Matched / Discrepancy`; Finance đánh dấu được Matched. | F-072 | BR-096 |
| FR-607 | Hệ thống xuất CSV đối soát và bút toán theo kỳ, tổng khớp với tổng on-chain. | F-073 | |
| FR-608 | Hệ thống nên ghi attestation on-chain cho mỗi yêu cầu đã trả hoặc đã khớp, không chứa dữ liệu cá nhân. | F-074 | BR-074 |
| FR-609 | *(Later)* Đồng bộ hóa đơn và thanh toán với ERP; đồng bộ không bao giờ duyệt được thanh toán. | F-075 | BR-001 |

## FR-7xx · Phục hồi

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-701 | Khi khởi động lại hoặc gặp Unknown, hệ thống xác định kết quả mọi thao tác dở dang từ outbox, chain và cờ đã dùng trên contract trước khi làm việc mới. | F-080 | BR-060 |
| FR-702 | Hệ thống chặn thực thi của treasury khi còn thao tác Unknown. | F-080 | BR-060 |
| FR-703 | Hệ thống ghi nhận hoàn thành một phần và tiếp tục từ bước chưa xong sau khi kiểm tra lại; không làm lại bước đã xong. | F-081 | BR-054 |
| FR-704 | Mỗi kết quả không phải ALLOW tạo đúng một mục NeedsReview, gồm phân loại, mã lý do, các bước đã xong và hành động theo vai trò. | F-082 | |
| FR-705 | Định tuyến: vượt trần → Owner; payee hoặc ngân sách → Owner sửa chính sách; đổi số tiền hoặc payee → duyệt lại. | F-082 | BR-002 |
| FR-706 | Lỗi thử lại được dùng backoff hàm mũ, có số lần tối đa, giữ nguyên mọi định danh. | F-083 | BR-061 |

## FR-8xx · AI

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-801 | Copilot trả lời câu hỏi về quỹ chỉ bằng tool đọc và mô phỏng; mọi con số đều trích từ kết quả tool. | F-090 | BR-034 |
| FR-802 | Copilot từ chối yêu cầu thực thi và chỉ người dùng sang luồng duyệt. | F-090 | BR-002 |
| FR-803 | Mọi nội dung bên ngoài được bọc như dữ liệu không tin cậy, có nhãn nguồn và giới hạn độ dài. Dùng schema đầu ra chặt và allowlist tool; kiểm tra đầu ra trước khi dùng. | F-091 | BR-070 |
| FR-804 | Không bao giờ đưa bí mật, khóa hay chữ ký dùng lại được vào đầu vào LLM. | F-091 | BR-092 |
| FR-805 | Có benchmark một lệnh so sánh B1 và B2 trên từ 30 kịch bản trở lên. Báo: tiết kiệm, tỷ lệ đúng hạn, số ngoại lệ, số giao dịch, phí, vi phạm, độ trễ, chi phí. | F-092 | |
| FR-806 | Mỗi lần gọi AI ghi: mục đích, model và phiên bản, phiên bản prompt, tham chiếu đầu vào, tool đã gọi, đầu ra, kết quả kiểm tra, plannerSource, độ trễ, chi phí. | F-093 | |
| FR-807 | Không ghi được nhật ký quyết định AI → lần lập kế hoạch thất bại an toàn. | F-093 | BR-097 |
| FR-808 | Lời gọi LLM đi qua adapter không phụ thuộc nhà cung cấp, chọn model theo tác vụ, có timeout và nhà cung cấp dự phòng. | F-094 | |

## FR-9xx · Thông báo, tuân thủ, audit, UX, phân tích, quản trị, DevEx

| ID | Yêu cầu | Feature | BR |
|---|---|---|---|
| FR-901 | Gửi thông báo trong app cho các sự kiện: cần duyệt, cần ngoại lệ, đã trả, cần xem xét, tạm dừng, bất thường, gas thấp. Định tuyến theo vai trò, bỏ trùng theo ID sự kiện. | F-100 | |
| FR-902 | Nên gửi cùng sự kiện qua Telegram đã liên kết kèm deep link; không cho phép hành động trong Telegram. | F-101 | |
| FR-903 | *(Later)* Thông báo email và bản tổng hợp; không hủy được sự kiện bảo mật. | F-102, F-105 | |
| FR-904 | *(Later)* Webhook ký HMAC, có thử lại và hàng đợi lỗi. | F-103 | |
| FR-905 | *(Later)* Hỗ trợ Slack, Lark, WeCom. | F-104 | |
| FR-906 | Sàng lọc địa chỉ payee khi đăng ký và trước PAY qua adapter; trúng thì BLOCK. | F-110 | BR-085 |
| FR-907 | *(Later)* Kích hoạt treasury mainnet phải qua KYB. | F-111 | |
| FR-908 | *(Later)* Trao đổi dữ liệu Travel Rule cho giao dịch thuộc diện áp dụng. | F-112 | |
| FR-909 | Chỉ lưu hash trên chain, mã hóa dữ liệu mật khi lưu, che dữ liệu trong log. | F-113 | BR-074 |
| FR-910 | *(Later)* Cấu hình thời gian lưu, quy trình xóa, chọn vùng dữ liệu. | F-114 | |
| FR-911 | Ghi audit chỉ-thêm, nối hash, cho mọi thao tác người dùng, chuyển trạng thái, quyết định kiểm tra, quyết định AI và giao dịch. | F-120 | BR-097 |
| FR-912 | Có script kiểm tra tính toàn vẹn chuỗi audit. | F-120 | |
| FR-913 | Xuất gói bằng chứng theo yêu cầu chi, hợp lệ theo JSON schema, không chứa hash bịa. | F-121 | BR-095 |
| FR-914 | Gắn nhãn mức bao phủ cho đánh giá, snapshot, trạng thái; dùng từ ngữ chính xác. | F-122 | |
| FR-915 | UI có dashboard: số dư so với buffer và mục tiêu, ngân sách đã dùng, bao phủ, trạng thái mandate, hàng đợi, runway, hoạt động. | F-130 | |
| FR-916 | UI có hộp duyệt: tài liệu, các trường đã trích, so sánh với lịch sử, cờ kèm bằng chứng, ký bằng ví. | F-131 | |
| FR-917 | UI có thẻ kế hoạch và timeline trực tiếp từng bước kèm link explorer; tách lý do của validator và giải thích của AI. | F-132 | BR-057 |
| FR-918 | UI có màn hình đối soát: bộ lọc, đánh dấu khớp, ghi chú chênh lệch, xuất file. | F-133 | |
| FR-919 | UI quản lý mandate và payee: so sánh thay đổi, đếm ngược thời gian chờ, kết quả sàng lọc, Owner ký. | F-134 | |
| FR-920 | UI có bảng điều khiển ngoại lệ, hành động theo vai trò cho từng loại mục. | F-135 | |
| FR-921 | Chỉ số vận hành tính từ sự kiện gốc, bao gồm cả yêu cầu bị chặn hoặc từ chối. | F-140 | |
| FR-922 | Báo cáo tiết kiệm so với kịch bản đối chứng B1, kèm phương pháp tính. | F-141 | |
| FR-923 | Log, metric, trace có cấu trúc, liên kết theo ID yêu cầu, kế hoạch và thao tác; có cảnh báo. | F-142 | |
| FR-924 | *(Later)* Bảng điều khiển PlatformAdmin không có bất kỳ khả năng chuyển tiền nào. | F-150 | BR-094 |
| FR-925 | Nạp và kiểm tra cấu hình chain, RPC, contract, tài sản khi khởi động; sai thì dừng ngay. | F-151 | |
| FR-926 | *(Later)* Đo lượng sử dụng và tính phí tổ chức, không trừ phí từ treasury. | F-152 | BR-091 |
| FR-927 | Repo dựng được toàn hệ thống kèm kịch bản mẫu bằng một lệnh có tài liệu. | F-160 | |
| FR-928 | CI chạy trên mỗi PR: lint, typecheck, unit, contract (gồm fuzz và invariant), phân tích tĩnh, integration, build. | F-161 | |
| FR-929 | Scenario runner chỉ chạy trên chain test trong allowlist và xuất gói bằng chứng. | F-162 | BR-095 |
| FR-930 | Bộ test bảo mật gồm ít nhất 8 invariant contract, các test vượt quyền, và 20 hóa đơn prompt injection. | F-163 | |
| FR-931 | Bộ kiểm tra độ ổn định chạy kịch bản chính 30 lần trên chain local và ít nhất 10 lần trên testnet, có báo cáo. | F-164 | |
