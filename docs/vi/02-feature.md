# TreasuryPilot: Danh mục & đặc tả Feature

**Trạng thái:** Đã qua cổng G1 · **Nguồn chuẩn:** `docs/FEATURES.md` (tiếng Anh)

## Quy ước

| Trường | Ý nghĩa |
|---|---|
| **ID** | `F-NNN`, cố định, không tái sử dụng. |
| **Phase** | `M1` = Milestone 1 (bản thi FinTechathon). `Later` = sản phẩm đầy đủ sau M1. Không feature nào bị bỏ. |
| **Ưu tiên** | Chỉ áp dụng cho M1: `P0` bắt buộc · `P1` nên có · `P2` có thì tốt. |
| **Nguồn** | `UC/R/AT/AD/D/O` = tài liệu `TreasuryPilot.md` v0.2. `T/S/N` = kế hoạch nâng điểm. `GA` = cơ chế lấy từ GuardianAI. `FJ` = FigJam board. `Q` = quyết định lập kế hoạch. `NEW` = BA bổ sung. |
| **Module** | Module dự kiến sở hữu feature; chốt ở Phase 4. |
| **Vai trò AI** | AI làm những việc nào trong: **Quan sát / Đề xuất / Quyết định / Hành động / Xác minh / Phục hồi**. "Quyết định" luôn có nghĩa là *chọn trong các phương án đã được code xác định kiểm tra hợp lệ*. |

**Vai trò (Q13):** Owner (chủ quỹ), Approver (người duyệt), Operator, Finance (kế toán), Guardian, OrgAdmin, Auditor, PlatformAdmin.

**Tác nhân hệ thống:** Agent (AI lập kế hoạch), PolicyEngine, Executor, Contract.

## 1. Danh mục

| ID | Feature | Nhóm | Phase | Ưu tiên | Nguồn |
|---|---|---|---|---|---|
| F-001 | Đăng ký & đăng nhập tài khoản | Định danh | M1 | P0 | NEW, Q3 |
| F-002 | Liên kết ví bằng Sign-In With Ethereum | Định danh | M1 | P0 | NEW, UC-01 |
| F-003 | Tạo tổ chức & onboarding | Định danh | M1 | P0 | Q3, Q21 |
| F-004 | Mời thành viên & quản lý vai trò | Người dùng | M1 | P1 | Q13 |
| F-005 | Tách người tạo – người duyệt (maker-checker) | Người dùng | M1 | P0 | Q13 |
| F-006 | MFA & bảo mật phiên | Định danh | Later | – | NEW |
| F-007 | SSO doanh nghiệp (OIDC/SAML) | Định danh | Later | – | NEW |
| F-010 | Tạo treasury | Thiết lập quỹ | M1 | P0 | D4, Q21 |
| F-011 | Kết nối Safe smart account | Thiết lập quỹ | M1 | P0 | Domain §6.2, FJ |
| F-012 | Bật module & kiểm tra mức bao phủ | Thiết lập quỹ | M1 | P0 | GA p.20, AT35 |
| F-013 | Danh mục tài sản | Thiết lập quỹ | M1 | P0 | Domain §2 |
| F-014 | Nhiều treasury & đa chain | Thiết lập quỹ | Later | – | Q2, Q21 |
| F-015 | Nhiều stablecoin trong một treasury | Thiết lập quỹ | Later | – | Q2 |
| F-020 | Cấu hình mandate | Mandate | M1 | P0 | Domain §4.1–4.2 |
| F-021 | Kích hoạt, phiên bản & vòng đời mandate | Mandate | M1 | P0 | Domain §6.2, UC-01 |
| F-022 | Danh bạ payee có sàng lọc & thời gian chờ | Mandate | M1 | P0 | R2, S2 |
| F-023 | Hạn mức chi & bộ đếm ngày UTC toàn treasury | Mandate | M1 | P0 | R3, Domain §5.1, O3 |
| F-024 | Bảo vệ buffer tối thiểu & số dư mục tiêu | Mandate | M1 | P0 | R4, Domain §3 |
| F-025 | Ngoại lệ một lần | Mandate | M1 | P1 | D3, UC-06, Domain §6.1 |
| F-026 | Tạm dừng, chạy lại & thu hồi | Mandate | M1 | P0 | UC-05, R9 |
| F-027 | Circuit breaker (tự tạm dừng) | Bảo mật | M1 | P2 | S7 |
| F-028 | Giữ chỗ & khóa tiền on-chain | Mandate | Later | – | Domain §5.2, Q2 |
| F-029 | Duyệt nhiều cấp theo ngưỡng (n-of-m) | Mandate | Later | – | Q14 |
| F-030 | Nhập hóa đơn thủ công | Hóa đơn | M1 | P0 | UC-01, Q15 |
| F-031 | Upload PDF/ảnh & AI trích xuất | Hóa đơn / AI | M1 | P0 | N1, Q15 |
| F-032 | Nhập hàng loạt từ CSV | Hóa đơn | M1 | P1 | Q15 |
| F-033 | Hộp thư nhận hóa đơn qua email | Hóa đơn | Later | – | Q15 |
| F-034 | Nhận hóa đơn qua API/webhook | Tích hợp | Later | – | Q15 |
| F-035 | Trích xuất điều khoản thanh toán | AI | M1 | P0 | N1 |
| F-036 | Phát hiện bất thường & dấu hiệu gian lận | AI / Bảo mật | M1 | P0 | N1, AT-09 |
| F-037 | Fingerprint chống trùng hóa đơn | Hóa đơn / Bảo mật | M1 | P0 | S3, UC-04 |
| F-038 | Duyệt hóa đơn bằng chữ ký EIP-712 | Hóa đơn | M1 | P0 | R1, UC-01 |
| F-039 | Vòng đời & máy trạng thái của yêu cầu chi | Lõi | M1 | P0 | Use-Case §5 |
| F-040 | Lịch thanh toán định kỳ | Hóa đơn | Later | – | D5, Q2 |
| F-041 | Hóa đơn fiat có quy đổi tỷ giá & kiểm tra depeg | Tài chính | Later | – | Q20 |
| F-050 | Đọc trạng thái chain & snapshot mới | Dữ liệu | M1 | P0 | UC-02, Autonomy §3 |
| F-051 | Bộ tính thanh khoản | Tài chính | M1 | P0 | Domain §3 |
| F-052 | Bộ lập lịch xác định theo điều khoản | Tài chính | M1 | P0 | N2, O8 |
| F-053 | AI đề xuất & giải thích kế hoạch | AI | M1 | P0 | N2, Autonomy §2 |
| F-054 | Kế hoạch dự phòng rule-based | AI | M1 | P0 | D6, AD-02 |
| F-055 | Kiểm tra chính sách (ALLOW / NEEDS_APPROVAL / BLOCK) | Lõi | M1 | P0 | Autonomy §4, FJ |
| F-056 | Ký xác nhận kế hoạch (plan attestation) | Bảo mật | M1 | P1 | GA p.21–22 |
| F-057 | AI soạn yêu cầu ngoại lệ | AI | M1 | P1 | N2 |
| F-058 | Dự báo thanh khoản & runway | Tài chính | M1 | P2 | T8 |
| F-059 | Refill từ ví vận hành khác | Tài chính | Later | – | D5, Q2 |
| F-060 | Tự kích hoạt theo deadline | Lõi | M1 | P0 | T1 |
| F-061 | Executor tuần tự & signer service | Thực thi | M1 | P0 | UC-02, S8 |
| F-062 | Thực thi REFILL | Thực thi | M1 | P0 | D4, UC-02 |
| F-063 | Thực thi PAY | Thực thi | M1 | P0 | D4, UC-02 |
| F-064 | SWAP qua adapter được phép (router test có ghi nhãn) | Thực thi | M1 | P2 | AT-04, R5 |
| F-065 | Swap DEX/aggregator thật với quote đã xác minh | Thực thi | Later | – | Domain §5.3, Q2 |
| F-066 | Quản lý gas | Thực thi | M1 | P1 | R7, Domain §5.4, O6 |
| F-067 | Bridge liên chain | Thực thi | Later | – | D5, Q2 |
| F-070 | Theo dõi & xác nhận giao dịch | Xác minh | M1 | P0 | UC-03 |
| F-071 | Kiểm tra hậu điều kiện | Xác minh | M1 | P0 | UC-02, GA p.14 |
| F-072 | Đối soát (Paid khác Matched) | Xác minh | M1 | P0 | UC-03 |
| F-073 | Xuất đối soát (CSV / bút toán) | Xác minh | M1 | P1 | T5 |
| F-074 | Attestation thanh toán on-chain | Xác minh | M1 | P2 | N6 |
| F-075 | Tích hợp ERP / kế toán | Tích hợp | Later | – | D5, Q2 |
| F-080 | Phục hồi trạng thái Unknown (không trả trùng) | Phục hồi | M1 | P0 | R8, AT-06, T3 |
| F-081 | Xử lý hoàn thành một phần | Phục hồi | M1 | P0 | AT-07 |
| F-082 | Hàng đợi cần xem xét & định tuyến ngoại lệ | Phục hồi | M1 | P0 | UC-04, FJ |
| F-083 | Chính sách retry idempotent | Phục hồi | M1 | P0 | UC-04 |
| F-090 | Treasury Copilot (hỏi "nếu… thì sao") | AI | M1 | P1 | N4 |
| F-091 | Ranh giới dữ liệu không tin cậy & chống prompt injection | AI / Bảo mật | M1 | P0 | AT-09, AD-01, S5 |
| F-092 | Bộ đánh giá AI (B1 và B2) | AI | M1 | P0 | N3, Autonomy §6 |
| F-093 | Nhật ký quyết định AI | AI / Audit | M1 | P0 | Autonomy §5 |
| F-094 | Adapter & định tuyến model | AI | M1 | P1 | NEW |
| F-100 | Thông báo trong app | Thông báo | M1 | P1 | Q16 |
| F-101 | Thông báo Telegram kèm deep link | Thông báo | M1 | P2 | N7, Q16 |
| F-102 | Thông báo email | Thông báo | Later | – | Q16 |
| F-103 | Webhook gửi ra | Tích hợp | Later | – | Q16 |
| F-104 | Thông báo Slack / Lark / WeCom | Thông báo | Later | – | Q16 |
| F-105 | Tùy chọn nhận thông báo | Thông báo | Later | – | NEW |
| F-110 | Sàng lọc payee theo danh sách trừng phạt/chặn | Tuân thủ | M1 | P1 | S6, Q17 |
| F-111 | KYB khi onboarding | Tuân thủ | Later | – | Q17 |
| F-112 | Hỗ trợ Travel Rule | Tuân thủ | Later | – | Q17 |
| F-113 | Tối thiểu hóa dữ liệu | Tuân thủ | M1 | P0 | Use-Case §2, S6 |
| F-114 | Chính sách lưu trữ & vùng dữ liệu | Tuân thủ | Later | – | Q17 |
| F-120 | Nhật ký audit nối hash & event on-chain | Audit | M1 | P0 | S6, GA p.14 |
| F-121 | Xuất gói bằng chứng | Audit | M1 | P0 | GA p.39, AT §6 |
| F-122 | Nhãn mức bao phủ & mức chắc chắn | Audit | M1 | P1 | GA p.5 |
| F-130 | Dashboard treasury | UX | M1 | P0 | N5 |
| F-131 | Hộp duyệt có so sánh & cờ | UX | M1 | P0 | N5, N1 |
| F-132 | Thẻ kế hoạch & timeline thực thi trực tiếp | UX | M1 | P0 | N5 |
| F-133 | Màn hình đối soát | UX | M1 | P0 | UC-03 |
| F-134 | Giao diện quản lý mandate & payee | UX | M1 | P0 | UC-01 |
| F-135 | Bảng điều khiển ngoại lệ & xem xét | UX | M1 | P0 | UC-04, UC-06 |
| F-140 | Chỉ số vận hành | Phân tích | M1 | P1 | T6, AT §6 |
| F-141 | Báo cáo tiết kiệm | Phân tích | M1 | P1 | N3 |
| F-142 | Giám sát hệ thống | Giám sát | M1 | P1 | NEW |
| F-150 | Quản trị nền tảng: quản lý tenant | Quản trị | Later | – | Q13 |
| F-151 | Cấu hình nền tảng (chain, RPC, tài sản) | Quản trị | M1 | P1 | O5 |
| F-152 | Billing & gói thuê bao | Quản trị | Later | – | Q22 |
| F-160 | Môi trường local một lệnh & kịch bản mẫu | DevEx | M1 | P1 | T7 |
| F-161 | Pipeline CI | DevEx | M1 | P1 | T7 |
| F-162 | Scenario runner & kịch bản demo | DevEx | M1 | P1 | GA p.14, p.41 |
| F-163 | Bộ test bảo mật | Bảo mật | M1 | P0 | S1, S5 |
| F-164 | Bộ chạy kiểm tra độ ổn định | Chất lượng | M1 | P1 | T6 |

**Tổng:** 99 feature. M1 có 76 (P0: 51 · P1: 20 · P2: 5). Later có 23.

## 2. Những gì không bao giờ làm (thực thi bằng Business Rule)

| ID | Non-goal | Rule |
|---|---|---|
| NG-1 | Giao dịch đầu cơ / tạo lập thị trường | BR-090 |
| NG-2 | Tối ưu lợi suất, staking, cho vay/đi vay | BR-090 |
| NG-3 | Quản lý danh mục, tư vấn phân bổ tài sản | BR-090 |
| NG-4 | TreasuryPilot giữ tiền của khách | BR-091 |
| NG-5 | Trả bất kỳ nghĩa vụ nào chưa có người duyệt hợp lệ | BR-001 |
| NG-6 | Agent tự tạo nghĩa vụ chi hoặc tự mua dịch vụ | BR-002 |
| NG-7 | Đảo ngược giao dịch đã xác nhận, hoặc hứa sẽ đảo ngược | BR-062 |

## 3. Đặc tả từng feature

Mỗi feature có đủ các mục:
- **Mô tả** · **Vấn đề giải quyết** · **Người dùng**
- **Kích hoạt** · **Đầu vào** · **Logic nghiệp vụ** · **Đầu ra**
- **Luồng chính** · **Luồng thay thế** · **Tình huống biên**
- **Phân quyền** · **Vai trò AI** · **Vai trò con người** · **Tiêu chí nghiệm thu**

### 3.1 Định danh & Quản lý người dùng

#### F-001 · Đăng ký & đăng nhập tài khoản
`M1 · P0 · Nguồn: NEW, Q3 · Module: identity`
- **Mô tả:** Người dùng tạo tài khoản và đăng nhập web app bằng email (magic link hoặc mật khẩu). Tài khoản tách biệt với ví.
- **Vấn đề giải quyết:** Sản phẩm đa tổ chức cần định danh con người độc lập với khóa ví. Finance và Auditor có thể không có ví.
- **Người dùng:** Mọi vai trò.
- **Kích hoạt:** Lần đầu truy cập hoặc qua link mời.
- **Đầu vào:** Email, mật khẩu hoặc token magic link, tên hiển thị.
- **Logic:** Xác minh quyền sở hữu email → tạo user → cấp phiên. Không lưu thông tin đăng nhập dạng rõ.
- **Đầu ra:** Phiên đã xác thực; bản ghi user.
- **Luồng chính:** Nhập email → nhận link → bấm → đăng nhập → chọn tổ chức.
- **Luồng thay thế:** Người được mời đăng ký qua link mời và tự vào tổ chức (F-004).
- **Tình huống biên:** Link hết hạn → gửi lại. Email đã đăng ký → chuyển sang đăng nhập. Thử quá nhiều lần → giới hạn tần suất và khóa tạm. Dịch vụ email lỗi → báo thử lại, không tạo tài khoản dở dang.
- **Phân quyền:** Endpoint công khai, có giới hạn tần suất.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Chứng minh sở hữu email.
- **Nghiệm thu:** Đăng ký, đăng nhập, đăng xuất hoạt động. Phiên có hạn. Brute force bị chặn. Không có bí mật dạng rõ trong DB hoặc log.

#### F-002 · Liên kết ví bằng Sign-In With Ethereum (SIWE)
`M1 · P0 · Nguồn: NEW, UC-01 · Module: identity`
- **Mô tả:** Người dùng chứng minh kiểm soát một địa chỉ EVM bằng cách ký thông điệp SIWE (EIP-4361) và liên kết địa chỉ vào tài khoản. Bắt buộc với vai trò ký: Owner, Approver, Guardian.
- **Vấn đề giải quyết:** Duyệt và ngoại lệ phải được ký bằng khóa mà contract nhận diện. Đăng nhập app không phải là quyền on-chain.
- **Người dùng:** Owner, Approver, Guardian.
- **Kích hoạt:** Được gán vai trò cần khóa, hoặc tự liên kết.
- **Đầu vào:** Địa chỉ ví, chữ ký SIWE, nonce, chainId.
- **Logic:** Kiểm tra chữ ký, nonce còn mới, domain và chainId → lưu địa chỉ cho user. Mỗi địa chỉ chỉ thuộc một user.
- **Đầu ra:** Bản ghi ví đã liên kết.
- **Luồng chính:** Kết nối ví → ký SIWE → hiển thị đã liên kết.
- **Luồng thay thế:** Hủy liên kết và liên kết lại (có audit). Một user có nhiều địa chỉ.
- **Tình huống biên:** Nonce dùng lại → từ chối. Địa chỉ đã thuộc user khác → từ chối. Ví contract → kiểm tra theo ERC-1271.
- **Phân quyền:** User đã đăng nhập, chỉ cho tài khoản của mình.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Tự ký bằng khóa của mình; khóa không rời ví.
- **Nghiệm thu:** Phải có ví liên kết mới dùng được vai trò ký. Replay bị chặn. Hỗ trợ ERC-1271. Mọi lần liên kết và hủy đều được audit.

#### F-003 · Tạo tổ chức & onboarding
`M1 · P0 · Nguồn: Q3, Q21 · Module: identity`
- **Mô tả:** Người dùng tạo tổ chức (tenant) và trở thành OrgAdmin đầu tiên. Có checklist hướng dẫn: thành viên → treasury → mandate → payee → hóa đơn đầu tiên.
- **Vấn đề giải quyết:** Cô lập dữ liệu giữa các tổ chức; điểm khởi đầu rõ ràng cho J1.
- **Người dùng:** Người dùng đầu tiên (thành OrgAdmin).
- **Kích hoạt:** Lần đăng nhập đầu khi chưa thuộc tổ chức nào.
- **Đầu vào:** Tên tổ chức, tên pháp nhân (tùy chọn ở M1), quốc gia, múi giờ (chỉ để hiển thị; hạn mức dùng UTC).
- **Logic:** Tạo tổ chức → gán OrgAdmin → khởi tạo checklist.
- **Đầu ra:** Bản ghi tổ chức và trạng thái checklist.
- **Luồng chính:** Tạo → xem checklist → làm từng bước.
- **Luồng thay thế:** Vào tổ chức có sẵn qua lời mời.
- **Tình huống biên:** Trùng tên (được phép; ID là duy nhất). Bỏ dở onboarding (trạng thái được lưu).
- **Phân quyền:** Mọi user đã đăng nhập.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Cung cấp thông tin đúng.
- **Nghiệm thu:** Dữ liệu tổ chức A không bao giờ hiện với thành viên tổ chức B (có test). Tiến độ checklist được lưu.

#### F-004 · Mời thành viên & quản lý vai trò
`M1 · P1 · Nguồn: Q13 · Module: identity`
- **Mô tả:** OrgAdmin mời thành viên qua email và gán một hoặc nhiều trong 8 vai trò.
- **Vấn đề giải quyết:** Phân tách nhiệm vụ, quyền tối thiểu.
- **Người dùng:** OrgAdmin.
- **Kích hoạt:** Thao tác của admin.
- **Đầu vào:** Email, vai trò.
- **Logic:** Tạo lời mời có hạn → khi chấp nhận thì gán vai trò. Vai trò ký chưa có hiệu lực cho đến khi liên kết ví. Thay đổi vai trò được audit. Không được xóa OrgAdmin hoặc Owner cuối cùng.
- **Đầu ra:** Thành viên kèm vai trò.
- **Luồng chính:** Mời → chấp nhận → vai trò có hiệu lực.
- **Luồng thay thế:** Thu hồi lời mời, đổi vai trò, xóa thành viên.
- **Tình huống biên:** Mời người đã là thành viên → cập nhật vai trò. Lời mời hết hạn. Xóa thành viên còn bản duyệt đang chờ → chữ ký đã ký vẫn giữ, nhưng chặn duyệt mới.
- **Phân quyền:** Chỉ OrgAdmin. Gán Owner còn yêu cầu Owner liên kết đúng địa chỉ owner của Safe.
- **Vai trò AI:** Không có.
- **Vai trò con người:** OrgAdmin chọn vai trò.
- **Nghiệm thu:** Mọi API đều kiểm tra RBAC. Thay đổi vai trò được audit. Không xóa được Admin/Owner cuối cùng.

#### F-005 · Tách người tạo – người duyệt (maker-checker)
`M1 · P0 · Nguồn: Q13 · Module: identity / invoices`
- **Mô tả:** Người tạo hoặc sửa hóa đơn không được duyệt chính hóa đơn đó.
- **Vấn đề giải quyết:** Một người vừa tạo vừa duyệt khoản chi.
- **Người dùng:** Operator, Approver, Owner.
- **Kích hoạt:** Khi duyệt hoặc cấp ngoại lệ.
- **Đầu vào:** Lịch sử tạo và sửa, danh tính người duyệt.
- **Logic:** Nếu người duyệt là người tạo hoặc người sửa cuối → từ chối. Backend thực thi; contract kiểm tra người ký thuộc danh sách approver.
- **Đầu ra:** Cho phép hoặc từ chối.
- **Luồng chính:** Operator tạo, người khác duyệt.
- **Luồng thay thế:** Tổ chức một người có thể bật "solo mode", được gắn cờ rõ trên UI và audit là **không có maker-checker**.
- **Tình huống biên:** Người tạo sau đó được cấp vai trò Approver → vẫn bị chặn với hóa đơn mình đã tạo.
- **Phân quyền:** Hệ thống thực thi.
- **Vai trò AI:** Không có. Bản nháp do AI trích xuất được tính là do Operator xác nhận nó tạo.
- **Vai trò con người:** Cấu hình vai trò.
- **Nghiệm thu:** Có test người tạo tự duyệt bị từ chối. Solo mode hiển thị trên mọi bản ghi liên quan.

#### F-006 · MFA & bảo mật phiên
`Later · Nguồn: NEW · Module: identity`
- **Mô tả:** Yếu tố thứ hai (TOTP/WebAuthn), danh sách thiết bị và phiên, xác thực lại khi làm thao tác nhạy cảm.
- **Vấn đề giải quyết:** Chiếm tài khoản để duyệt hoặc sửa policy.
- **Người dùng:** Mọi người; bắt buộc với vai trò ký.
- **Kích hoạt:** Đăng nhập; thao tác nhạy cảm (duyệt, cấp ngoại lệ, sửa mandate).
- **Đầu vào:** Bằng chứng yếu tố thứ hai.
- **Logic:** Yêu cầu xác thực lại trong vòng N phút cho thao tác nhạy cảm.
- **Đầu ra:** Phiên đã xác minh.
- **Luồng chính:** Đăng nhập → yếu tố thứ hai → phiên.
- **Luồng thay thế:** Mã khôi phục.
- **Tình huống biên:** Mất thiết bị → admin hỗ trợ đặt lại, có audit.
- **Phân quyền:** Tự phục vụ; admin được đặt lại.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Giữ an toàn yếu tố xác thực.
- **Nghiệm thu:** Endpoint nhạy cảm từ chối phiên chưa xác thực lại.

#### F-007 · SSO doanh nghiệp (OIDC/SAML)
`Later · Nguồn: NEW · Module: identity`
- **Mô tả:** Đăng nhập qua nhà cung cấp định danh (IdP) của công ty, tùy chọn đồng bộ người dùng qua SCIM.
- **Vấn đề giải quyết:** Onboarding và offboarding cho doanh nghiệp.
- **Người dùng:** Tổ chức lớn.
- **Kích hoạt:** Đăng nhập.
- **Đầu vào:** Assertion từ IdP.
- **Logic:** Ánh xạ nhóm IdP sang vai trò. Vai trò ký vẫn cần liên kết ví.
- **Đầu ra:** Phiên.
- **Luồng chính:** Chuyển hướng → IdP → phiên.
- **Luồng thay thế:** Tạo user tự động khi đăng nhập lần đầu.
- **Tình huống biên:** Bị gỡ khỏi IdP → thu hồi phiên.
- **Phân quyền:** OrgAdmin cấu hình.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Quản trị IdP.
- **Nghiệm thu:** Hoạt động với ít nhất một nhà cung cấp OIDC. Gỡ quyền có hiệu lực trong 5 phút.

### 3.2 Thiết lập quỹ & ví

#### F-010 · Tạo treasury
`M1 · P0 · Nguồn: D4, Q21 · Module: treasury`
- **Mô tả:** Trong một tổ chức, tạo treasury gắn với một chain và một stablecoin thanh toán, gồm ví nguồn `T` và N ví vận hành (M1: `O1`, `O2`).
- **Vấn đề giải quyết:** Xác định phạm vi tiền mà agent quản lý.
- **Người dùng:** Owner, OrgAdmin.
- **Kích hoạt:** Bước onboarding hoặc thao tác của admin.
- **Đầu vào:** Chain (từ F-151), stablecoin (F-013), địa chỉ ví và vai trò ví, nhãn.
- **Logic:** Kiểm tra chain và tài sản được hỗ trợ → kiểm tra địa chỉ là Safe trên đúng chain (F-011) → lưu. Vai trò ví không đổi được khi đã có mandate tham chiếu; muốn đổi phải tạo phiên bản treasury mới.
- **Đầu ra:** Bản ghi treasury.
- **Luồng chính:** Chọn chain và tài sản → thêm T, O1, O2 → lưu.
- **Luồng thay thế:** Tạo Safe ngay trong app (F-011).
- **Tình huống biên:** Địa chỉ trùng → từ chối. Sai chain → từ chối. Là EOA thay vì Safe → từ chối ở chế độ được bảo vệ.
- **Phân quyền:** Owner hoặc OrgAdmin.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Chọn ví đúng.
- **Nghiệm thu:** Không tạo được treasury với chain/tài sản không hỗ trợ, ví trùng hoặc ví không phải Safe.

#### F-011 · Kết nối Safe smart account
`M1 · P0 · Nguồn: Domain §6.2, FJ · Module: treasury / contracts`
- **Mô tả:** Kết nối Safe có sẵn hoặc tạo Safe mới (owner là địa chỉ của Owner, threshold theo cấu hình). Đọc owners, threshold, modules và guard.
- **Vấn đề giải quyết:** Thực thi luật chỉ có thật khi mọi ví trong phạm vi đều đi qua đường kiểm soát. Kiểm tra ở backend trước một EOA không phải là thực thi luật.
- **Người dùng:** Owner.
- **Kích hoạt:** Khi thiết lập treasury.
- **Đầu vào:** Địa chỉ Safe, hoặc tham số triển khai.
- **Logic:** Đọc cấu hình on-chain → lưu snapshot → gắn cờ khi các lần đọc sau khác đi.
- **Đầu ra:** Bản ghi Safe kèm snapshot cấu hình.
- **Luồng chính:** Dán địa chỉ → đọc cấu hình → xác nhận.
- **Luồng thay thế:** Triển khai Safe mới bằng giao dịch Owner ký.
- **Tình huống biên:** Owner hoặc threshold đổi sau đó → cảnh báo mức bao phủ (F-012). RPC lỗi → hiển thị "chưa rõ", không phải "ổn".
- **Phân quyền:** Owner.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Owner ký triển khai và cấu hình.
- **Nghiệm thu:** Snapshot khớp với chain. Phát hiện thay đổi trong một chu kỳ polling.

#### F-012 · Bật module & kiểm tra mức bao phủ
`M1 · P0 · Nguồn: GA p.20, GA AT35 · Module: contracts / treasury`
- **Mô tả:** Owner bật `TreasuryPilotModule` trên từng Safe. Hệ thống kiểm tra toàn bộ module và guard đang bật. Nếu có module khác có thể chuyển tiền ngoài mandate, chế độ bảo vệ bị đánh dấu **bao phủ một phần** và việc tự thực thi bị tạm ngưng cho đến khi Owner xác nhận.
- **Vấn đề giải quyết:** Một module thứ hai có quyền thực thi tùy ý sẽ đi vòng qua mandate.
- **Người dùng:** Owner.
- **Kích hoạt:** Khi thiết lập và mỗi khi phát hiện cấu hình thay đổi.
- **Đầu vào:** Danh sách module, địa chỉ guard, hash bytecode của module.
- **Logic:** So với allowlist hash module đã biết → mức bao phủ là COMPLETE / PARTIAL / UNKNOWN.
- **Đầu ra:** Mức bao phủ của từng Safe.
- **Luồng chính:** Bật module → COMPLETE → cho phép thực thi.
- **Luồng thay thế:** Owner xác nhận chấp nhận PARTIAL (có audit, UI hiện banner cố định).
- **Tình huống biên:** Owner tắt module → dừng thực thi. Nâng cấp module → phải kiểm tra lại.
- **Phân quyền:** Owner ký giao dịch bật module.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Bật module, xác nhận bao phủ một phần.
- **Nghiệm thu:** Có thêm module lạ → PARTIAL và trigger tự động bị chặn (có test).

#### F-013 · Danh mục tài sản
`M1 · P0 · Nguồn: Domain §2 · Module: treasury`
- **Mô tả:** Tài sản được định danh bằng `(chainId, địa chỉ contract)`, decimals đã kiểm tra. Gas native có định danh riêng. Tên "USDC" chỉ để hiển thị.
- **Vấn đề giải quyết:** Token giả mạo, sai decimals.
- **Người dùng:** PlatformAdmin (toàn hệ thống), Owner (chọn).
- **Kích hoạt:** Khi cấu hình.
- **Đầu vào:** chainId, địa chỉ, ký hiệu, decimals, nhà phát hành, cờ "tài sản test".
- **Logic:** Decimals đọc on-chain phải khớp. Mọi số tiền là số nguyên ở đơn vị nhỏ nhất.
- **Đầu ra:** Bản ghi tài sản.
- **Luồng chính:** Admin thêm → kiểm tra → được chọn.
- **Luồng thay thế:** Tài sản test luôn có nhãn "TEST" ở mọi nơi.
- **Tình huống biên:** Token thu phí khi chuyển hoặc token rebase → không hỗ trợ.
- **Phân quyền:** PlatformAdmin ghi; người khác chỉ đọc.
- **Vai trò AI:** Không có.
- **Vai trò con người:** PlatformAdmin kiểm tra địa chỉ nhà phát hành.
- **Nghiệm thu:** Không có số thực (float) trong code tiền. Sai decimals bị từ chối. Tài sản test luôn có nhãn.

#### F-014 · Nhiều treasury & đa chain
`Later · Nguồn: Q2, Q21 · Module: treasury`
- **Mô tả:** Một tổ chức có nhiều treasury, mỗi treasury trên một chain, có màn hình tổng hợp.
- **Vấn đề giải quyết:** Doanh nghiệp thật hoạt động trên nhiều chain.
- **Người dùng:** Owner, Finance.
- **Kích hoạt:** Tạo treasury.
- **Đầu vào:** Như F-010, cho từng chain.
- **Logic:** Hạn mức và bộ đếm riêng theo treasury. Màn hình tổng hợp không cộng các tài sản khác nhau nếu không có nguồn giá.
- **Đầu ra:** Nhiều treasury.
- **Luồng chính:** Thêm treasury thứ hai trên chain khác.
- **Luồng thay thế:** —
- **Tình huống biên:** Cùng địa chỉ trên hai chain là hai ví khác nhau.
- **Phân quyền:** Owner.
- **Vai trò AI:** Quan sát, đề xuất giữa các treasury.
- **Vai trò con người:** Cấu hình từng mandate.
- **Nghiệm thu:** Hai treasury trên hai chain chạy độc lập, bộ đếm tách biệt.

#### F-015 · Nhiều stablecoin trong một treasury
`Later · Nguồn: Q2 · Module: treasury / financial`
- **Mô tả:** Treasury giữ nhiều stablecoin (ví dụ USDC, USDT), hạn mức theo từng tài sản.
- **Vấn đề giải quyết:** Nhà cung cấp yêu cầu stablecoin khác nhau.
- **Người dùng:** Owner.
- **Kích hoạt:** Cấu hình.
- **Đầu vào:** Tài sản bổ sung.
- **Logic:** Hạn mức theo tài sản. Swap giữa các stablecoin cần F-065. Không mặc định tỷ giá 1:1.
- **Đầu ra:** Treasury đa tài sản.
- **Luồng chính:** Thêm USDT → đặt hạn mức.
- **Luồng thay thế:** —
- **Tình huống biên:** Depeg → chặn swap nếu quote lệch quá ngưỡng.
- **Phân quyền:** Owner.
- **Vai trò AI:** Đề xuất tài sản dùng để trả.
- **Vai trò con người:** Duyệt danh sách tài sản.
- **Nghiệm thu:** Hạn mức được thực thi độc lập theo từng tài sản.

### 3.3 Mandate & Chính sách

#### F-020 · Cấu hình mandate
`M1 · P0 · Nguồn: Domain §4.1–4.2 · Module: mandate`
- **Mô tả:** Owner định nghĩa quyền ủy cho agent: các hành động được phép (`REFILL`, `PAY`, `SWAP`); ví; đường refill (`T→O1`, `T→O2`); payee; hạn mức mỗi khoản và mỗi ngày theo hành động và tài sản; buffer và mục tiêu theo ví; cặp swap, router, trượt giá tối đa, tuổi quote tối đa; trần cấp gas; thời hạn hiệu lực.
- **Vấn đề giải quyết:** Biến "tin agent" thành quyền ủy minh bạch, thực thi được, audit được (P2).
- **Người dùng:** Owner (Finance được xem).
- **Kích hoạt:** Khi thiết lập hoặc đổi chính sách.
- **Đầu vào:** Các trường mandate; số tiền là số nguyên ở đơn vị nhỏ nhất.
- **Logic:** Kiểm tra đủ trường (BR-014). Kiểm tra nhất quán: `mục tiêu ≥ buffer`; đường refill nằm trong ví của treasury; payee có trong danh bạ. Hiển thị bản tóm tắt dễ đọc trước khi ký, ví dụ "Agent được trả tối đa 2.000 USDC mỗi hóa đơn…".
- **Đầu ra:** Bản nháp mandate.
- **Luồng chính:** Điền form → xem tóm tắt → sang kích hoạt (F-021).
- **Luồng thay thế:** Nhân bản phiên bản trước rồi sửa.
- **Tình huống biên:** Bật SWAP mà thiếu router hoặc trần gas → không hợp lệ. Hạn mức bằng 0 → hành động coi như tắt (cho phép, kèm cảnh báo). Nhập lẻ hơn decimals cho phép → từ chối.
- **Phân quyền:** Chỉ Owner.
- **Vai trò AI:** Không tham gia tạo. Copilot có thể *giải thích* mandate nhưng không sửa được.
- **Vai trò con người:** Owner quyết định mọi giá trị.
- **Nghiệm thu:** Mandate thiếu trường không kích hoạt được. Bản tóm tắt đúng giá trị ở đơn vị nhỏ nhất. Không có API nào cho người không phải Owner ghi mandate.

#### F-021 · Kích hoạt, phiên bản & vòng đời mandate
`M1 · P0 · Nguồn: Domain §6.2, UC-01 · Module: mandate / contracts`
- **Mô tả:** Kích hoạt là ghi mandate lên chain qua giao dịch Safe do Owner ký. Vòng đời: `Draft → PendingActivation → Active → (Paused) → Expired | Revoked | Superseded`. Mỗi lần sửa tạo phiên bản mới.
- **Vấn đề giải quyết:** Chính sách phải nằm ở nơi thực thi; bản trong database chỉ là cache.
- **Người dùng:** Owner.
- **Kích hoạt:** Owner kích hoạt hoặc cập nhật.
- **Đầu vào:** Bản nháp.
- **Logic:** Tạo giao dịch Safe → Owner ký → chờ đủ số xác nhận → đọc lại on-chain → khớp thì mới Active. Phiên bản mới vô hiệu các ngoại lệ còn tồn và **không reset bộ đếm**.
- **Đầu ra:** Mandate Active (id, version, hash, tham chiếu on-chain).
- **Luồng chính:** Ký → xác nhận → Active.
- **Luồng thay thế:** Hết hạn → tự sang Expired (contract từ chối). Thu hồi → F-026.
- **Tình huống biên:** Giao dịch pending lâu → hiển thị "đang chờ kích hoạt", phiên bản cũ vẫn có hiệu lực. On-chain khác bản nháp → `Discrepancy`, không Active.
- **Phân quyền:** Owner ký.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Owner ký kích hoạt.
- **Nghiệm thu:** Không bao giờ thực thi bằng phiên bản chưa xác nhận on-chain. Lịch sử phiên bản bất biến. Bộ đếm giữ nguyên qua các phiên bản (có test).

#### F-022 · Danh bạ payee có sàng lọc & thời gian chờ
`M1 · P0 · Nguồn: R2, S2 · Module: mandate / compliance`
- **Mô tả:** Payee là mục `(nhãn, chain, địa chỉ)` trong allowlist on-chain. Địa chỉ mới hoặc vừa đổi chỉ dùng được sau **thời gian chờ** (24 giờ; demo 5 phút) và sau khi qua sàng lọc (F-110).
- **Vấn đề giải quyết:** Lừa đảo đổi tài khoản nhà cung cấp (BEC). Kẻ gian đổi địa chỉ trong hóa đơn cũng không được trả ngay, và Owner có thời gian phát hiện.
- **Người dùng:** Owner thêm hoặc đổi; Operator đề xuất; Approver xem.
- **Kích hoạt:** Nhà cung cấp mới hoặc đổi địa chỉ.
- **Đầu vào:** Nhãn, địa chỉ, thông tin nhà cung cấp (lưu off-chain).
- **Logic:** Sàng lọc → Owner ký giao dịch đăng ký với `activeFrom = bây giờ + thời gian chờ` → contract từ chối PAY trước `activeFrom`. Đổi địa chỉ = tạo mục mới và vô hiệu mục cũ.
- **Đầu ra:** Payee với trạng thái `Screening → Cooling → Active → Deactivated`.
- **Luồng chính:** Thêm → sàng lọc sạch → chờ → Active.
- **Luồng thay thế:** Operator đề xuất → Owner xem và ký.
- **Tình huống biên:** Trúng danh sách chặn → BLOCK, không đăng ký được. Dịch vụ sàng lọc lỗi → tạm ngưng đăng ký (mặc định đóng). Trùng địa chỉ → từ chối. Hóa đơn đến hạn khi còn trong thời gian chờ → hóa đơn phải đợi, bộ lập lịch báo không kịp hạn.
- **Phân quyền:** Chỉ Owner kích hoạt payee.
- **Vai trò AI:** Quan sát (so địa chỉ trong hóa đơn với lịch sử, F-036); đề xuất ("có vẻ là đổi địa chỉ").
- **Vai trò con người:** Owner xác minh địa chỉ qua kênh khác rồi ký.
- **Nghiệm thu:** PAY cho payee đang trong thời gian chờ bị revert on-chain (có test). Đổi địa chỉ luôn bắt đầu lại thời gian chờ. Mọi thay đổi được audit.

#### F-023 · Hạn mức chi & bộ đếm ngày UTC toàn treasury
`M1 · P0 · Nguồn: R3, Domain §5.1, O3 · Module: contracts / mandate`
- **Mô tả:** Hạn mức mỗi khoản và mỗi ngày theo nhóm hành động (PAY, REFILL, đầu vào SWAP) và theo tài sản, do contract thực thi. Bộ đếm theo khóa `(treasury, hành động, tài sản, ngày UTC)`.
- **Vấn đề giải quyết:** Giới hạn thiệt hại tối đa; chặn chia nhỏ để lách hạn mức.
- **Người dùng:** Owner cấu hình; hệ thống thực thi.
- **Kích hoạt:** Mỗi bước thực thi.
- **Đầu vào:** Số tiền, hành động, tài sản, timestamp của block.
- **Logic:** `Ngày = floor(block.timestamp / 86400)`. Yêu cầu `đã dùng + số tiền ≤ trần ngày` và `số tiền ≤ trần mỗi khoản` (trừ khi có ngoại lệ hợp lệ, F-025). Chỉ cộng khi thành công. Ngân sách refill và pay tách riêng.
- **Đầu ra:** Cho phép hoặc revert; bộ đếm cập nhật.
- **Luồng chính:** Trong hạn mức → thực thi → cộng bộ đếm.
- **Luồng thay thế:** Vượt trần mỗi khoản nhưng có ngoại lệ → cho phép một lần.
- **Tình huống biên:** Pending qua nửa đêm → tính theo ngày thực thi. Revert → không cộng. Chia qua O1/O2 hoặc qua phiên bản → vẫn chung một bộ đếm.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Quan sát ngân sách còn lại (chỉ đọc) để lập kế hoạch.
- **Vai trò con người:** Owner đặt hạn mức.
- **Nghiệm thu:** Fuzz/invariant test: tổng PAY thành công trong một ngày UTC không bao giờ vượt trần. Chia ví hoặc đổi phiên bản không lách được.

#### F-024 · Bảo vệ buffer tối thiểu & số dư mục tiêu
`M1 · P0 · Nguồn: R4, Domain §3 · Module: contracts / financial`
- **Mô tả:** Mỗi ví vận hành có buffer tối thiểu mà agent không bao giờ được xâm phạm. Số dư mục tiêu là mục tiêu mềm khi refill.
- **Vấn đề giải quyết:** Giữ ví luôn hoạt động được; bảo vệ tiền dành cho việc khác.
- **Người dùng:** Owner đặt; hệ thống thực thi.
- **Kích hoạt:** Khi lập kế hoạch và thực thi PAY/REFILL.
- **Đầu vào:** Số dư, buffer `F`, mục tiêu `H` (`H ≥ F`).
- **Logic:** Contract kiểm tra `số dư sau ≥ F` cho ví trả khi PAY, và cho ví nguồn T (`F_T`) khi REFILL. Bộ lập kế hoạch refill tới `H` nếu được, nếu không thì refill đúng phần thiếu.
- **Đầu ra:** Cho phép hoặc revert; thông báo "chưa đạt mục tiêu" nếu có.
- **Luồng chính:** Refill tới mục tiêu → trả → ví ở mức mục tiêu.
- **Luồng thay thế:** Nguồn chỉ đủ mức tối thiểu → refill phần thiếu → trả → báo chưa đạt mục tiêu.
- **Tình huống biên:** Owner rút tiền ngoài module → đọc lại trước mỗi bước và dừng nếu thiếu. Buffer của token native không được bảo đảm nếu chính ví đó trả gas (giới hạn đã ghi nhận).
- **Phân quyền:** Owner đặt.
- **Vai trò AI:** Không tính toán; chỉ giải thích kết quả.
- **Vai trò con người:** Đặt buffer hợp lý.
- **Nghiệm thu:** Invariant: không giao dịch nào qua đường agent làm ví xuống dưới buffer. Các ví dụ ở Domain §3.4 chạy đúng dưới dạng unit test.

#### F-025 · Ngoại lệ một lần
`M1 · P1 · Nguồn: D3, UC-06, Domain §6.1 · Module: mandate / contracts`
- **Mô tả:** Với hóa đơn đã duyệt nhưng vượt trần mỗi khoản, Owner cấp ngoại lệ gắn đúng hóa đơn đó. Ngoại lệ chỉ nâng trần mỗi khoản.
- **Vấn đề giải quyết:** Thỉnh thoảng có khoản lớn mà không muốn nới mandate chung.
- **Người dùng:** Owner cấp; Agent soạn yêu cầu (F-057).
- **Kích hoạt:** Validator trả `NEEDS_APPROVAL` vì vượt trần mỗi khoản, các luật khác đều đạt.
- **Đầu vào:** request_id, số tiền, payee, tài sản, ví trả, chain, contract, phiên bản mandate, hạn dùng, nonce.
- **Logic:** Owner ký EIP-712 → contract kiểm tra khi PAY → dùng hết cùng lúc với thanh toán. Toàn bộ số tiền tính vào trần ngày. Không nâng được trần ngày, buffer, payee, tài sản, chain hay thời hạn.
- **Đầu ra:** Bản ghi ngoại lệ (`Granted → Consumed | Expired | Invalidated`).
- **Luồng chính:** NEEDS_APPROVAL → bản yêu cầu đã soạn → Owner ký → PAY thành công một lần.
- **Luồng thay thế:** Owner từ chối → hóa đơn ở `AwaitingAuthority` → Operator có thể hủy.
- **Tình huống biên:** Dùng lại cho hóa đơn khác → revert. Đổi phiên bản mandate → vô hiệu. Vượt trần ngày → vẫn BLOCK. Hết hạn → vô hiệu.
- **Phân quyền:** Chỉ Owner.
- **Vai trò AI:** Đề xuất (soạn lý do); không bao giờ cấp.
- **Vai trò con người:** Owner quyết định.
- **Nghiệm thu:** AT-11 đạt: dùng đúng một lần; dùng lại, sai phiên bản, vượt trần ngày đều bị chặn.

#### F-026 · Tạm dừng, chạy lại & thu hồi
`M1 · P0 · Nguồn: UC-05, R9 · Module: mandate / contracts`
- **Mô tả:** Owner hoặc Guardian tạm dừng agent: backend dừng ngay, contract từ chối sau khi giao dịch được xác nhận. Chỉ Owner được chạy lại. Owner có thể thu hồi mandate vĩnh viễn.
- **Vấn đề giải quyết:** Dừng khẩn cấp.
- **Người dùng:** Owner, Guardian (chỉ tạm dừng).
- **Kích hoạt:** Thao tác tay hoặc circuit breaker (F-027).
- **Đầu vào:** Lý do; giao dịch đã ký.
- **Logic:** Khi có yêu cầu, backend bật cờ dừng và ngừng gửi → giao dịch dừng on-chain theo sau → UI phân biệt "đã yêu cầu dừng" và "đã dừng on-chain" → hiện các giao dịch đang pending → không đảo ngược gì.
- **Đầu ra:** Mandate Paused hoặc Revoked.
- **Luồng chính:** Dừng → backend ngưng → on-chain xác nhận → PAY bị revert.
- **Luồng thay thế:** Owner chạy lại → kiểm tra lại toàn bộ hóa đơn trong hàng đợi trước khi tiếp tục.
- **Tình huống biên:** Giao dịch broadcast trước khi lệnh dừng được xác nhận vẫn có thể chạy → được báo. Guardian cố chạy lại → bị từ chối.
- **Phân quyền:** Dừng: Owner, Guardian. Chạy lại và thu hồi: chỉ Owner.
- **Vai trò AI:** Không có (agent ngừng lập kế hoạch).
- **Vai trò con người:** Quyết định dừng hoặc chạy lại.
- **Nghiệm thu:** AT-08 đạt. Guardian chạy lại → revert. Kế hoạch tạo trước khi thu hồi không thực thi được sau đó.

#### F-027 · Circuit breaker (tự tạm dừng)
`M1 · P2 · Nguồn: S7 · Module: execution / security`
- **Mô tả:** Backend tự dừng khi vượt ngưỡng bất thường: ít nhất 3 lần contract từ chối trong 10 phút; AI đề xuất kế hoạch vượt mandate; mức bao phủ giảm; số dư thay đổi bất ngờ.
- **Vấn đề giải quyết:** Giới hạn thiệt hại do lỗi hoặc bị tấn công giữa các lần con người kiểm tra.
- **Người dùng:** Hệ thống; báo cho Owner.
- **Kích hoạt:** Vượt ngưỡng.
- **Đầu vào:** Luồng sự kiện.
- **Logic:** Đánh giá luật → bật dừng ở backend → thông báo → (tùy chọn) gửi lệnh dừng on-chain bằng khóa Guardian nếu đã cấu hình.
- **Đầu ra:** Trạng thái dừng kèm mã lý do.
- **Luồng chính:** Bất thường → tự dừng → Owner điều tra → chạy lại.
- **Luồng thay thế:** Luật chỉ cấu hình để cảnh báo.
- **Tình huống biên:** Bật tắt liên tục → có thời gian nghỉ giữa các cảnh báo. Báo nhầm → Owner chạy lại, sự kiện vẫn được ghi.
- **Phân quyền:** Owner cấu hình ngưỡng và chạy lại.
- **Vai trò AI:** Không có (luật xác định).
- **Vai trò con người:** Quyết định chạy lại.
- **Nghiệm thu:** Test bơm 3 lần từ chối → dừng trong một chu kỳ đánh giá.

#### F-028 · Giữ chỗ & khóa tiền on-chain
`Later · Nguồn: Domain §5.2, Q2 · Module: contracts / financial`
- **Mô tả:** Tiền giữ chỗ (`R`) và tiền khóa khi đang thực thi (`L`) cho các nghĩa vụ đã đăng ký được lưu và thực thi on-chain.
- **Vấn đề giải quyết:** Nhiều nghĩa vụ tranh cùng một khoản tiền; giữ chỗ trong database không phải bảo vệ cứng.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Khi duyệt (giữ chỗ) và khi bắt đầu thực thi (khóa).
- **Đầu vào:** Hóa đơn, số tiền, ví.
- **Logic:** Công thức Domain §3.1 trên chain. Chuyển R sang L không tính hai lần. Chỉ giải phóng khi biết rõ kết quả.
- **Đầu ra:** Trạng thái giữ chỗ on-chain.
- **Luồng chính:** Duyệt → giữ chỗ → thực thi → giải phóng.
- **Luồng thay thế:** Hủy → giải phóng.
- **Tình huống biên:** Timeout không giải phóng khóa. Thiếu tiền → báo.
- **Phân quyền:** Hệ thống qua module.
- **Vai trò AI:** Quan sát.
- **Vai trò con người:** Không có ngoài việc duyệt.
- **Nghiệm thu:** Invariant: tổng giữ chỗ và khóa không vượt số dư trừ buffer.

#### F-029 · Duyệt nhiều cấp theo ngưỡng (n-of-m)
`Later · Nguồn: Q14 · Module: invoices / mandate`
- **Mô tả:** Chính sách duyệt yêu cầu k trên n người duyệt theo khoảng số tiền. Ví dụ: dưới 1.000 cần 1 người; 1.000–10.000 cần 2; trên 10.000 cần 2 người cộng Owner.
- **Vấn đề giải quyết:** Kiểm soát nội bộ của doanh nghiệp.
- **Người dùng:** Approver, Owner.
- **Kích hoạt:** Khi duyệt.
- **Đầu vào:** Chính sách, các chữ ký.
- **Logic:** Contract kiểm tra k chữ ký khác nhau, hợp lệ, trên cùng dữ liệu.
- **Đầu ra:** Approved khi đủ ngưỡng.
- **Luồng chính:** Hai người ký → Approved.
- **Luồng thay thế:** Một người từ chối → theo chính sách (phủ quyết hoặc đa số).
- **Tình huống biên:** Một người ký hai lần → tính một. Người duyệt bị xóa giữa chừng → tùy chính sách.
- **Phân quyền:** Owner cấu hình.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Ký.
- **Nghiệm thu:** Luật theo từng khoảng tiền được thực thi on-chain (test từng khoảng).

### 3.4 Hóa đơn & Nghĩa vụ chi

#### F-030 · Nhập hóa đơn thủ công
`M1 · P0 · Nguồn: UC-01, Q15 · Module: invoices`
- **Mô tả:** Operator tạo yêu cầu chi gồm: số hóa đơn, payee, tài sản, số tiền, ví trả, ngày đến hạn, điều khoản (tùy chọn), tệp đính kèm.
- **Vấn đề giải quyết:** Kênh nhận hóa đơn cơ bản.
- **Người dùng:** Operator.
- **Kích hoạt:** Có hóa đơn mới.
- **Đầu vào:** Các trường trên; số tiền hiển thị được đổi sang đơn vị nhỏ nhất.
- **Logic:** Kiểm tra schema → payee phải tồn tại (Active hoặc đang chờ) → tài sản phải là stablecoin của treasury → tính fingerprint (F-037) → trạng thái `Draft`.
- **Đầu ra:** Bản nháp yêu cầu chi.
- **Luồng chính:** Điền → lưu → gửi duyệt (`AwaitingApproval`).
- **Luồng thay thế:** Payee chưa có → "đề xuất payee" (F-022). Lưu nháp.
- **Tình huống biên:** Ngày đến hạn đã qua → cho phép nhưng gắn cờ. Trùng fingerprint → chặn gửi duyệt cho đến khi xử lý. Số tiền lẻ quá decimals → từ chối.
- **Phân quyền:** Operator, OrgAdmin.
- **Vai trò AI:** Không có (kênh thủ công); kiểm tra bất thường F-036 vẫn chạy.
- **Vai trò con người:** Nhập đúng dữ liệu.
- **Nghiệm thu:** Dữ liệu sai bị từ chối kèm lỗi từng trường. Gửi duyệt chuyển sang AwaitingApproval. Người tạo được ghi lại để áp maker-checker.

#### F-031 · Upload PDF/ảnh & AI trích xuất
`M1 · P0 · Nguồn: N1, Q15 · Module: invoices / agent`
- **Mô tả:** Upload PDF hoặc ảnh. AI trích các trường có cấu trúc và điều khoản thanh toán (F-035), rồi chạy kiểm tra bất thường (F-036). Operator xem song song tài liệu và các trường đã trích, sau đó xác nhận.
- **Vấn đề giải quyết:** Nhập liệu thủ công, bỏ sót điều khoản.
- **Người dùng:** Operator.
- **Kích hoạt:** Upload tệp.
- **Đầu vào:** Tệp tối đa 10 MB (PDF, PNG, JPG).
- **Logic:** Lưu tệp riêng tư → trích văn bản (OCR nếu cần) → LLM xuất theo schema chặt → kiểm tra schema → mỗi trường có tham chiếu vị trí và trang trong tài liệu → lệnh chèn bị bỏ qua và gắn cờ (F-091) → `Draft`.
- **Đầu ra:** Bản nháp có nguồn gốc từng trường và các cờ.
- **Luồng chính:** Upload → các trường điền sẵn → Operator sửa nếu sai → gửi duyệt.
- **Luồng thay thế:** Trích xuất lỗi → nhập tay, tài liệu hiển thị bên cạnh.
- **Tình huống biên:** PDF chứa nhiều hóa đơn → M1 từ chối kèm thông báo. Ảnh scan không đọc được → nhập tay. LLM quá thời gian → nhập tay, không đoán. Địa chỉ trong tài liệu khác payee đã đăng ký → gắn cờ, không bao giờ tự đăng ký.
- **Phân quyền:** Operator.
- **Vai trò AI:** Quan sát, Đề xuất (trích xuất, gắn cờ). Không quyết định payee hay việc duyệt.
- **Vai trò con người:** Operator xác nhận từng trường; Approver duyệt.
- **Nghiệm thu:** Báo độ chính xác trên bộ 30 hóa đơn có nhãn. Không trích xuất nào đổi được địa chỉ payee đã đăng ký. Tài liệu không bao giờ gửi cho LLM cùng bí mật.

#### F-032 · Nhập hàng loạt từ CSV
`M1 · P1 · Nguồn: Q15 · Module: invoices`
- **Mô tả:** Nhập nhiều hóa đơn từ file CSV theo mẫu.
- **Vấn đề giải quyết:** Chi hàng loạt (ví dụ trả hơn 40 contractor).
- **Người dùng:** Operator.
- **Kích hoạt:** Upload CSV.
- **Đầu vào:** File CSV theo mẫu; header được kiểm tra.
- **Logic:** Kiểm tra từng dòng độc lập → dòng hợp lệ thành bản nháp → dòng lỗi vào báo cáo tải về → kiểm tra fingerprint trong file và với lịch sử.
- **Đầu ra:** N bản nháp và báo cáo lỗi.
- **Luồng chính:** Upload → xem trước → xác nhận → tạo bản nháp.
- **Luồng thay thế:** Chỉ nhập các dòng hợp lệ.
- **Tình huống biên:** Trùng dòng trong file. Sai dấu phân cách hoặc encoding. Ô chứa công thức bảng tính độc hại (`=`, `+`, `-`, `@`) được vô hiệu.
- **Phân quyền:** Operator.
- **Vai trò AI:** Không có (kiểm tra bất thường chạy cho từng dòng).
- **Vai trò con người:** Xem trước rồi xác nhận.
- **Nghiệm thu:** 500 dòng nhập dưới 10 giây. Lỗi báo theo từng dòng. Công thức độc hại được vô hiệu.

#### F-033 · Hộp thư nhận hóa đơn qua email
`Later · Nguồn: Q15 · Module: invoices / integration`
- **Mô tả:** Mỗi tổ chức có một địa chỉ email riêng; email hóa đơn chuyển tiếp vào sẽ thành bản nháp qua F-031.
- **Vấn đề giải quyết:** Bỏ luôn bước upload.
- **Người dùng:** Operator.
- **Kích hoạt:** Có email đến.
- **Đầu vào:** Email kèm tệp.
- **Logic:** Kiểm tra domain người gửi (SPF/DKIM) → lấy tệp đính kèm → chạy F-031. Nội dung email là dữ liệu không tin cậy.
- **Đầu ra:** Bản nháp.
- **Luồng chính:** Nhà cung cấp gửi email → bản nháp xuất hiện.
- **Luồng thay thế:** Không có tệp đính kèm → đọc nội dung email.
- **Tình huống biên:** Người gửi giả mạo → gắn cờ. Tệp quá lớn → từ chối.
- **Phân quyền:** OrgAdmin bật tính năng.
- **Vai trò AI:** Quan sát, Đề xuất.
- **Vai trò con người:** Xác nhận bản nháp.
- **Nghiệm thu:** Email giả mạo bị gắn cờ. Không bao giờ tự duyệt.

#### F-034 · Nhận hóa đơn qua API/webhook
`Later · Nguồn: Q15 · Module: integration`
- **Mô tả:** API có xác thực để hệ thống khác (ERP, công cụ AP) tạo bản nháp yêu cầu chi.
- **Vấn đề giải quyết:** Tích hợp với quy trình AP có sẵn.
- **Người dùng:** Hệ thống tích hợp (API key theo phạm vi từng tổ chức).
- **Kích hoạt:** Gọi API.
- **Đầu vào:** JSON theo schema, kèm idempotency key.
- **Logic:** Kiểm tra như F-030; idempotent.
- **Đầu ra:** ID bản nháp.
- **Luồng chính:** POST → 201.
- **Luồng thay thế:** Endpoint gửi hàng loạt.
- **Tình huống biên:** Gửi lại cùng idempotency key → cùng kết quả.
- **Phân quyền:** API key có quyền `invoices:create`.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Duyệt.
- **Nghiệm thu:** Idempotency được kiểm chứng. Key theo phạm vi không duyệt được.

#### F-035 · Trích xuất điều khoản thanh toán
`M1 · P0 · Nguồn: N1 · Module: agent / invoices`
- **Mô tả:** Trích điều khoản từ văn bản hóa đơn thành dạng máy đọc được: ngày đến hạn; chiết khấu thanh toán sớm (ví dụ "2/10 net 30"); lịch phạt trễ; ghi chú mức độ quan trọng của nhà cung cấp.
- **Vấn đề giải quyết:** Điều khoản là thứ tạo ra giá trị cho bộ lập lịch (P4).
- **Người dùng:** Operator xác nhận; bộ lập lịch sử dụng.
- **Kích hoạt:** F-031, hoặc trường điều khoản dạng văn bản ở F-030/F-032.
- **Đầu vào:** Văn bản hóa đơn.
- **Logic:** LLM xuất theo schema `{phần trăm chiết khấu, hạn chiết khấu, ngày đến hạn, phạt trễ {loại, mức, chu kỳ}, ghi chú ưu tiên}` → kiểm tra xác định (ngày hợp lệ, phần trăm trong giới hạn) → hiển thị để người xác nhận. **Bộ lập lịch chỉ dùng điều khoản đã được xác nhận.**
- **Đầu ra:** Điều khoản đã xác nhận gắn vào yêu cầu chi.
- **Luồng chính:** "2/10 net 30" → chiết khấu 2% đến ngày D+10, đến hạn D+30 → xác nhận.
- **Luồng thay thế:** Không có điều khoản → chỉ dùng ngày đến hạn.
- **Tình huống biên:** Điều khoản mơ hồ → cờ `uncertain`, Operator phải chọn. Điều khoản mâu thuẫn → gắn cờ.
- **Phân quyền:** Operator xác nhận; Approver thấy điều khoản như một phần của bản duyệt.
- **Vai trò AI:** Quan sát, Đề xuất.
- **Vai trò con người:** Xác nhận điều khoản (trở thành một phần của dữ liệu được duyệt).
- **Nghiệm thu:** Báo độ chính xác trên bộ có nhãn. Điều khoản chưa xác nhận không bao giờ được dùng để lập lịch.

#### F-036 · Phát hiện bất thường & dấu hiệu gian lận
`M1 · P0 · Nguồn: N1, AT-09 · Module: agent / invoices`
- **Mô tả:** Gắn cờ trên mỗi bản nháp khi: địa chỉ payee khác lịch sử nhà cung cấp; số tiền bất thường so với lịch sử; trùng fingerprint; tài liệu chứa lệnh chèn; sai tiền tệ hoặc chain; ngày đến hạn bất thường.
- **Vấn đề giải quyết:** Lừa đảo BEC, trả trùng, prompt injection (P3).
- **Người dùng:** Operator, Approver.
- **Kích hoạt:** Khi tạo hoặc sửa bản nháp.
- **Đầu vào:** Bản nháp, lịch sử nhà cung cấp, danh bạ payee.
- **Logic:** Kiểm tra xác định (địa chỉ, fingerprint, tiền tệ, ngoại lệ thống kê theo median ± k·MAD) cộng LLM phát hiện văn bản giống mệnh lệnh. Mỗi cờ có mức độ, bằng chứng và mã lý do. **Cờ không bao giờ tự duyệt hay tự từ chối; cờ mức cao bắt buộc Approver xác nhận đã đọc.**
- **Đầu ra:** Danh sách cờ.
- **Luồng chính:** Sạch → không có cờ.
- **Luồng thay thế:** Có cờ → Approver xác nhận hoặc từ chối.
- **Tình huống biên:** Nhà cung cấp mới chưa có lịch sử → "chưa có cơ sở so sánh", không phải "sạch". LLM lỗi → chỉ chạy cờ xác định, kèm ghi chú mức bao phủ.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Quan sát, Đề xuất.
- **Vai trò con người:** Approver xác nhận hoặc từ chối.
- **Nghiệm thu:** Bộ red-team 20 hóa đơn có lệnh chèn đều bị gắn cờ. Không cờ nào sửa được các trường.

#### F-037 · Fingerprint chống trùng hóa đơn
`M1 · P0 · Nguồn: S3, UC-04 · Module: invoices / contracts`
- **Mô tả:** `fingerprint = keccak256(nhà cung cấp chuẩn hóa, số hóa đơn chuẩn hóa, số tiền, tài sản)`. Backend cảnh báo khi nhập; registry trên contract chặn PAY lần hai với cùng fingerprint.
- **Vấn đề giải quyết:** Cùng một hóa đơn nhập dưới hai ID khác nhau (lỗ hổng mà tài liệu gốc tự thừa nhận).
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Khi nhập (cảnh báo) và khi PAY (thực thi).
- **Đầu vào:** Các trường đã chuẩn hóa.
- **Logic:** Chuẩn hóa (bỏ khoảng trắng, chữ hoa/thường, ký tự phân cách) → hash → kiểm tra registry. Trường hợp lặp hợp lệ cần số hóa đơn khác, hoặc cờ ghi đè do Owner ký nằm trong bản duyệt.
- **Đầu ra:** Cảnh báo hoặc revert.
- **Luồng chính:** Duy nhất → tiếp tục.
- **Luồng thay thế:** Ghi đè bằng chữ ký Owner.
- **Tình huống biên:** Nhà cung cấp phát hành lại hóa đơn đã sửa (số mới) → cho phép; hủy hóa đơn cũ.
- **Phân quyền:** Ghi đè: chỉ Owner.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Xử lý hóa đơn trùng.
- **Nghiệm thu:** PAY lần hai cùng fingerprint bị revert on-chain (có test).

#### F-038 · Duyệt hóa đơn bằng chữ ký EIP-712
`M1 · P0 · Nguồn: R1, UC-01 · Module: invoices / contracts`
- **Mô tả:** Approver ký dữ liệu có cấu trúc gắn các trường: request_id, hash hóa đơn, fingerprint, chain, contract, treasury, ví trả, tài sản, payee, số tiền, deadline, hash điều khoản đã xác nhận, hạn dùng. Contract kiểm tra chữ ký khi PAY.
- **Vấn đề giải quyết:** Việc duyệt có tính mật mã và gắn đúng các trường, không phải một cờ trong backend.
- **Người dùng:** Approver.
- **Kích hoạt:** Yêu cầu ở trạng thái AwaitingApproval.
- **Đầu vào:** Yêu cầu chi, chữ ký từ ví Approver.
- **Logic:** Kiểm tra maker-checker → hiển thị so sánh và cờ (F-131) → ví ký → backend kiểm tra → `Approved`. Sửa bất kỳ trường nào làm bản duyệt mất hiệu lực.
- **Đầu ra:** Bản ghi duyệt kèm chữ ký.
- **Luồng chính:** Xem → ký → Approved.
- **Luồng thay thế:** Từ chối kèm lý do → `Rejected`. Yêu cầu sửa → quay lại Draft.
- **Tình huống biên:** Chữ ký cho sai chain hoặc contract → không hợp lệ. Approver bị xóa trước khi thực thi → contract kiểm tra theo danh sách approver hiện tại. Bản duyệt hết hạn → phải duyệt lại.
- **Phân quyền:** Vai trò Approver có ví liên kết.
- **Vai trò AI:** Không có.
- **Vai trò con người:** **Quyết định có trả hay không.**
- **Nghiệm thu:** PAY với trường bị sửa bị revert (có test). Sửa trường làm mất hiệu lực bản duyệt (có test).

#### F-039 · Vòng đời & máy trạng thái của yêu cầu chi
`M1 · P0 · Nguồn: Use-Case §5 · Module: invoices / core`
- **Mô tả:** Trạng thái chính: `Draft → AwaitingApproval → Approved → Scheduled → Planning → Preparing → Paying → Paid`. Nhánh phụ: `Rejected`, `AwaitingAuthority`, `NeedsReview`, `Expired`, `Cancelled`. Trạng thái giao dịch và trạng thái đối soát được tách riêng.
- **Vấn đề giải quyết:** Trạng thái rõ ràng; không có một trạng thái "Failed" chung xóa mất lịch sử.
- **Người dùng:** Tất cả.
- **Kích hoạt:** Mỗi lần chuyển trạng thái.
- **Đầu vào:** Sự kiện.
- **Logic:** Bảng chuyển trạng thái tường minh; chuyển sai bị từ chối; mọi lần chuyển đều được audit. Không được `Cancelled` khi giao dịch PAY đang pending hoặc unknown.
- **Đầu ra:** Trạng thái hiện tại và lịch sử.
- **Luồng chính:** Như trên.
- **Luồng thay thế:** Các nhánh phụ.
- **Tình huống biên:** Chuyển trạng thái đồng thời → dùng optimistic lock.
- **Phân quyền:** Mỗi lần chuyển gắn với vai trò (ví dụ chỉ Approver chuyển được AwaitingApproval → Approved).
- **Vai trò AI:** Không có.
- **Vai trò con người:** Theo vai trò.
- **Nghiệm thu:** Có unit test cho bảng chuyển trạng thái; chuyển sai bị từ chối.

#### F-040 · Lịch thanh toán định kỳ
`Later · Nguồn: D5, Q2 · Module: invoices`
- **Mô tả:** Định nghĩa nghĩa vụ lặp lại (ví dụ phí contractor hằng tháng). Mỗi kỳ sinh ra **bản nháp** vẫn phải được duyệt.
- **Vấn đề giải quyết:** Nhập lặp đi lặp lại.
- **Người dùng:** Operator.
- **Kích hoạt:** Đến kỳ.
- **Đầu vào:** Mẫu, chu kỳ, ngày kết thúc.
- **Logic:** Chỉ sinh bản nháp; không bao giờ tự duyệt.
- **Đầu ra:** Bản nháp theo kỳ.
- **Luồng chính:** Mỗi tháng có bản nháp → được duyệt.
- **Luồng thay thế:** Bỏ qua một kỳ.
- **Tình huống biên:** Mẫu đổi payee → bản nháp mới dùng payee mới, phải qua thời gian chờ.
- **Phân quyền:** Operator tạo; Approver duyệt từng kỳ.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Duyệt từng kỳ.
- **Nghiệm thu:** Không bản nháp sinh tự động nào được trả khi chưa duyệt.

#### F-041 · Hóa đơn fiat có quy đổi tỷ giá & kiểm tra depeg
`Later · Nguồn: Q20 · Module: financial`
- **Mô tả:** Hóa đơn tính bằng tiền fiat (USD, EUR…) được quy đổi sang stablecoin qua nguồn tỷ giá đã cấu hình. Chặn thanh toán nếu stablecoin lệch giá quá ngưỡng.
- **Vấn đề giải quyết:** Hóa đơn thật thường tính bằng fiat.
- **Người dùng:** Operator, Approver.
- **Kích hoạt:** Nhận hóa đơn fiat.
- **Đầu vào:** Số tiền fiat, loại tiền, nguồn tỷ giá.
- **Logic:** Bản duyệt gắn số tiền fiat và số stablecoin tối đa. Tỷ giá chốt lúc thực thi, trong biên cho phép. Kiểm tra depeg trước khi PAY.
- **Đầu ra:** Thanh toán đã quy đổi.
- **Luồng chính:** €1.000 → số USDC trong biên → trả.
- **Luồng thay thế:** Ngoài biên → NeedsReview.
- **Tình huống biên:** Nguồn tỷ giá cũ → chặn.
- **Phân quyền:** Owner cấu hình nguồn tỷ giá.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Duyệt biên cho phép.
- **Nghiệm thu:** Không bao giờ trả vượt số stablecoin tối đa đã duyệt.

### 3.5 Thanh khoản & Lập kế hoạch

#### F-050 · Đọc trạng thái chain & snapshot mới
`M1 · P0 · Nguồn: UC-02, Autonomy §3 · Module: chain-reader`
- **Mô tả:** Đọc số dư (stablecoin và native), trạng thái mandate, bộ đếm, trạng thái payee và cấu hình module tại một block cụ thể. Snapshot ghi `blockNumber`, `blockHash`, thời điểm đọc và mức bao phủ.
- **Vấn đề giải quyết:** Kế hoạch phải dựa trên trạng thái mới, chứng minh được; không dùng snapshot cũ sau khi trạng thái đã đổi.
- **Người dùng:** Hệ thống (planner, validator, executor).
- **Kích hoạt:** Trước khi lập kế hoạch, trước mỗi bước, và theo lịch polling.
- **Đầu vào:** Cấu hình treasury.
- **Logic:** Đọc gộp tại một block → snapshot. Ngưỡng độ mới là N block. Cũ hoặc thiếu → mức bao phủ `PARTIAL/UNKNOWN` → không thực thi.
- **Đầu ra:** Snapshot.
- **Luồng chính:** Đọc → snapshot COMPLETE.
- **Luồng thay thế:** Chuyển sang nhà cung cấp RPC dự phòng.
- **Tình huống biên:** Các RPC lệch nhau hoặc chậm → UNKNOWN. Reorg → đọc lại.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Quan sát (tool chỉ đọc).
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Không bước nào chạy trên snapshot cũ hơn ngưỡng. RPC lỗi không bao giờ cho kết quả "ổn".

#### F-051 · Bộ tính thanh khoản
`M1 · P0 · Nguồn: Domain §3 · Module: financial-engine`
- **Mô tả:** Tính xác định các đại lượng `Available`, `FundingDeficit`, `Shortage`, `PreferredRefill`, `SourceCapacity`, `Cap`, và áp bảng quyết định: refill mức ưu tiên / refill phần thiếu / dừng.
- **Vấn đề giải quyết:** Số tiền không bao giờ do LLM tính.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Khi lập kế hoạch.
- **Đầu vào:** Snapshot, các yêu cầu chi, buffer, mục tiêu, ngân sách.
- **Logic:** Đúng công thức Domain §3.1–3.3, dùng số nguyên ở đơn vị nhỏ nhất.
- **Đầu ra:** Số liệu cấp vốn cho từng yêu cầu, kèm lý do.
- **Luồng chính:** B=20, P=100, F=H=10 → Shortage = PreferredRefill = 90.
- **Luồng thay thế:** Cap nằm giữa Shortage và Preferred → refill phần thiếu, báo chưa đạt mục tiêu.
- **Tình huống biên:** Cap < Shortage → DỪNG. Cấu hình `H < F` → bị chặn từ đầu.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Các ví dụ Domain §3.4 và UC-02 chạy thành test. Property test: không đầu ra nào xâm phạm buffer.

#### F-052 · Bộ lập lịch xác định theo điều khoản
`M1 · P0 · Nguồn: N2, O8 · Module: financial-engine`
- **Mô tả:** Từ các yêu cầu đã duyệt kèm điều khoản đã xác nhận, thanh khoản và ngân sách hiện có, tính lịch trả khả thi tối ưu theo thứ tự ưu tiên: (1) không vi phạm luật cứng; (2) đạt mọi deadline có thể đạt; (3) tối đa chiết khấu nhận được trừ phí phạt; (4) tối thiểu số giao dịch. Baseline B1 là "đến hạn sớm trả trước" (EDF).
- **Vấn đề giải quyết:** P4: luật đơn giản bỏ sót tiền.
- **Người dùng:** Hệ thống; kết quả hiển thị cho Finance và Owner.
- **Kích hoạt:** Mỗi chu kỳ lập kế hoạch.
- **Đầu vào:** Yêu cầu chi, điều khoản, snapshot, ngân sách, ngày hiện tại.
- **Logic:** Tìm kiếm chính xác khi N ≤ 12, hoặc tham lam rồi cải thiện bằng hoán đổi. Xuất lịch kèm các ràng buộc đang chặn. Mục không khả thi có lý do: payee đang chờ; vượt trần ngày → chuyển sang ngày sau; cần ngoại lệ.
- **Đầu ra:** Lịch trả kèm giá trị kỳ vọng từng mục.
- **Luồng chính:** Trả sớm hóa đơn có chiết khấu; trả hóa đơn có phạt trước ngày phạt.
- **Luồng thay thế:** AI đề xuất thứ tự khác → chấm bằng cùng hàm mục tiêu → chọn phương án khả thi tốt hơn (F-053).
- **Tình huống biên:** Bằng điểm → theo thứ tự duyệt. Tất cả đều không khả thi → NeedsReview kèm lý do.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có (xác định); AI dùng và giải thích kết quả.
- **Vai trò con người:** Xác nhận điều khoản ở bước trước.
- **Nghiệm thu:** Unit test với các ca tính tay. Property test: hàm mục tiêu không bao giờ vi phạm luật cứng.

#### F-053 · AI đề xuất & giải thích kế hoạch
`M1 · P0 · Nguồn: N2, Autonomy §2 · Module: agent`
- **Mô tả:** LLM agent dùng tool chỉ đọc để đề xuất cấu trúc và thứ tự kế hoạch: trả gì bây giờ, hoãn gì, cái nào cần ngoại lệ, dùng ví nào. Agent viết giải thích dễ đọc, có trích bằng chứng (điều khoản, số dư, hạn mức). Số tiền lấy từ F-051 và F-052.
- **Vấn đề giải quyết:** Xử lý các ca cần phán đoán (ghi chú mức quan trọng của nhà cung cấp, ưu tiên mơ hồ, đánh đổi nhiều ràng buộc) và giải thích.
- **Người dùng:** Hệ thống; người dùng xem giải thích.
- **Kích hoạt:** Mỗi chu kỳ lập kế hoạch.
- **Đầu vào:** Kết quả bộ lập lịch, snapshot, yêu cầu chi và điều khoản, tóm tắt chính sách.
- **Logic:** Xuất theo schema `{thứ tự, hoãn, yêu cầu ngoại lệ, lý do, evidenceIds}` → kiểm tra schema → chấm bằng hàm mục tiêu của F-052 → kiểm tra chính sách (F-055). Kế hoạch sai hoặc nguy hiểm bị loại và chuyển NeedsReview. Ghi `plannerSource=AI`.
- **Đầu ra:** Kế hoạch ứng viên kèm giải thích.
- **Luồng chính:** AI đề xuất → hợp lệ → được chọn.
- **Luồng thay thế:** AI quá thời gian → F-054. Kế hoạch AI điểm thấp hơn kế hoạch xác định → chọn kế hoạch xác định và ghi lại so sánh.
- **Tình huống biên:** AI tham chiếu yêu cầu không tồn tại hoặc tự bịa số tiền → loại. Độ tự tin của AI không phải tín hiệu; validator quyết định.
- **Phân quyền:** Agent chỉ có tool đọc.
- **Vai trò AI:** Quan sát, Đề xuất, Quyết định (trong các phương án hợp lệ).
- **Vai trò con người:** Không cần cho từng kế hoạch trong mandate; ngoại lệ chuyển cho Owner.
- **Nghiệm thu:** Không đầu ra AI nào tới executor nếu chưa qua F-055. Mọi kế hoạch ghi plannerSource và evidence ID.

#### F-054 · Kế hoạch dự phòng rule-based
`M1 · P0 · Nguồn: D6, AD-02 · Module: agent / financial-engine`
- **Mô tả:** Khi AI không phản hồi, dùng mẫu đã kiểm thử (trả trực tiếp; refill rồi trả; swap qua route cố định rồi trả) với thứ tự xác định (F-052).
- **Vấn đề giải quyết:** Đảm bảo hệ thống vẫn chạy mà không cấp thêm quyền.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** AI quá thời gian hoặc lỗi.
- **Đầu vào:** Như F-053.
- **Logic:** Chỉ dùng khi dữ liệu đủ, có mẫu khớp, không có giao dịch Unknown và không có cảnh báo an toàn. Ghi `plannerSource=RULE_BASED`.
- **Đầu ra:** Kế hoạch.
- **Luồng chính:** AI lỗi → dùng mẫu → thực thi.
- **Luồng thay thế:** Không mẫu nào khớp → NeedsReview.
- **Tình huống biên:** Còn giao dịch Unknown → không dùng dự phòng (AD-03).
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** AD-02 và AD-03 đạt.

#### F-055 · Kiểm tra chính sách (ALLOW / NEEDS_APPROVAL / BLOCK)
`M1 · P0 · Nguồn: Autonomy §4, FJ · Module: policy-engine`
- **Mô tả:** Validator xác định kiểm tra toàn kế hoạch và từng bước: bản duyệt còn hiệu lực, mandate Active, payee Active, hạn mức, buffer, quote, deadline, mức bao phủ, giao dịch Unknown. Xuất quyết định kèm mã lý do.
- **Vấn đề giải quyết:** Một cổng kiểm tra duy nhất, audit được, phản chiếu đúng các kiểm tra của contract.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Trước khi ký xác nhận kế hoạch và trước mỗi bước.
- **Đầu vào:** Kế hoạch, snapshot, mandate, bản duyệt.
- **Logic:** Theo bảng quyết định Autonomy §4. Nhiều lỗi cùng lúc → lấy kết quả chặt nhất. Ngoại lệ không bao giờ che lỗi luật cứng.
- **Đầu ra:** `{quyết định, mã lý do[], các kiểm tra[]}`.
- **Luồng chính:** ALLOW.
- **Luồng thay thế:** NEEDS_APPROVAL → F-025/F-057. BLOCK → F-082.
- **Tình huống biên:** Thiếu dữ liệu → không bao giờ ALLOW.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Mỗi mã lý do có unit test. Validator và contract cho cùng kết quả trên mọi ca AT-05 (differential test).

#### F-056 · Ký xác nhận kế hoạch (plan attestation)
`M1 · P1 · Nguồn: GA p.21–22 · Module: policy-engine / contracts`
- **Mô tả:** Sau khi ALLOW, review signer ký EIP-712 gắn `planHash`, requestId, step id, policyVersion, executor, hạn dùng, nonce và evidenceDigest. Executor chỉ gửi các bước đã được ký xác nhận.
- **Vấn đề giải quyết:** Payload bị sửa giữa lúc kiểm tra và lúc thực thi (plan drift).
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Có quyết định ALLOW.
- **Đầu vào:** Kế hoạch đã kiểm tra.
- **Logic:** Mã hóa chuẩn (không dùng JSON) → hash → ký. Contract hoặc executor kiểm tra chữ ký, hạn dùng và nonce.
- **Đầu ra:** Attestation.
- **Luồng chính:** Ký → gửi → kiểm tra.
- **Luồng thay thế:** Hết hạn → kiểm tra lại → ký lại.
- **Tình huống biên:** Khóa signer bị lộ → thiệt hại bị giới hạn bởi mandate (rủi ro đã ghi nhận).
- **Phân quyền:** Chỉ signer service.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Bước bị sửa nhưng dùng attestation cũ → bị từ chối (có test).

#### F-057 · AI soạn yêu cầu ngoại lệ
`M1 · P1 · Nguồn: N2 · Module: agent`
- **Mô tả:** Khi NEEDS_APPROVAL, agent soạn yêu cầu gửi Owner: cần gì, vì sao (điều khoản, deadline, hậu quả), ảnh hưởng tới ngân sách ngày, và các phương án thay thế (đợi sang ngày mai; không được chia nhỏ…).
- **Vấn đề giải quyết:** Owner quyết nhanh và có đủ thông tin.
- **Người dùng:** Owner.
- **Kích hoạt:** NEEDS_APPROVAL.
- **Đầu vào:** Yêu cầu chi, kết quả validator, bối cảnh bộ lập lịch.
- **Logic:** LLM viết văn bản kèm bản tóm tắt có cấu trúc. Con số lấy từ engine. Owner ký qua F-025.
- **Đầu ra:** Thẻ yêu cầu ngoại lệ.
- **Luồng chính:** Soạn → Owner ký.
- **Luồng thay thế:** Owner từ chối.
- **Tình huống biên:** LLM lỗi → dùng văn bản mẫu.
- **Phân quyền:** Owner hành động.
- **Vai trò AI:** Đề xuất.
- **Vai trò con người:** Quyết định.
- **Nghiệm thu:** Con số trong bản soạn khớp chính xác với engine (có test).

#### F-058 · Dự báo thanh khoản & runway
`M1 · P2 · Nguồn: T8 · Module: financial-engine`
- **Mô tả:** Xem trước 7 ngày cho từng ví: nghĩa vụ đã duyệt theo ngày so với số dư, khi nào chạm buffer, kèm gợi ý refill trước.
- **Vấn đề giải quyết:** Chủ động thay vì refill phút chót.
- **Người dùng:** Owner, Finance, Operator.
- **Kích hoạt:** Mở dashboard; job chạy hằng ngày.
- **Đầu vào:** Yêu cầu đã duyệt, số dư, hạn mức.
- **Logic:** Dự phóng xác định; không tính bản nháp chưa duyệt trừ khi bật chế độ "nếu… thì sao".
- **Đầu ra:** Biểu đồ runway và cảnh báo.
- **Luồng chính:** "O1 chạm buffer vào thứ Năm; nên refill 1.200 vào thứ Tư."
- **Luồng thay thế:** Bao gồm cả bản nháp.
- **Tình huống biên:** Còn giao dịch Unknown → hiển thị như vùng bất định.
- **Phân quyền:** Mọi vai trò được đọc.
- **Vai trò AI:** Đề xuất (lời diễn giải).
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Phép dự phóng có test. Gợi ý refill nằm trong hạn mức.

#### F-059 · Refill từ ví vận hành khác
`Later · Nguồn: D5, Q2 · Module: financial-engine / contracts`
- **Mô tả:** Cho phép refill `Oi → Oj` khi T thiếu, trong đường và hạn mức của mandate.
- **Vấn đề giải quyết:** Tiền bị kẹt ở một ví vận hành.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Khi lập kế hoạch mà T không đủ.
- **Đầu vào:** Snapshot, đường refill trong mandate.
- **Logic:** Bảo vệ buffer và nghĩa vụ sắp tới của ví nguồn.
- **Đầu ra:** Thêm lựa chọn refill.
- **Luồng chính:** O2 dư → chuyển sang O1.
- **Luồng thay thế:** —
- **Tình huống biên:** Chặn refill vòng tròn.
- **Phân quyền:** Mandate phải liệt kê đường refill.
- **Vai trò AI:** Đề xuất.
- **Vai trò con người:** Cấu hình đường refill.
- **Nghiệm thu:** Nghĩa vụ của ví nguồn không bao giờ thiếu tiền (property test).

### 3.6 Thực thi

#### F-060 · Tự kích hoạt theo deadline
`M1 · P0 · Nguồn: T1 · Module: orchestrator`
- **Mô tả:** Scheduler thức dậy định kỳ và khi có sự kiện (duyệt, số dư đổi), bắt đầu lập kế hoạch cho các yêu cầu vào cửa sổ thực thi (deadline trừ thời gian dự trữ, hoặc cửa sổ chiết khấu). Không ai phải bấm "thực thi".
- **Vấn đề giải quyết:** Biến agent thành người tham gia tài chính, không phải một nút bấm.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Bộ hẹn giờ (demo: mỗi phút) hoặc sự kiện.
- **Đầu vào:** Yêu cầu đã duyệt, các cửa sổ thời gian.
- **Logic:** Chọn yêu cầu đủ điều kiện → lập kế hoạch → thực thi. Bỏ qua nếu đang dừng, mức bao phủ chưa COMPLETE, hoặc còn giao dịch Unknown.
- **Đầu ra:** Job lập kế hoạch.
- **Luồng chính:** Mở cửa sổ → lập kế hoạch → trả.
- **Luồng thay thế:** Operator bấm "chạy ngay", vẫn qua cùng các kiểm tra.
- **Tình huống biên:** Trigger chồng nhau → khóa single-flight theo treasury.
- **Phân quyền:** Hệ thống; chạy tay cần vai trò Operator.
- **Vai trò AI:** Hành động (khởi động tự động; hành động vẫn được kiểm tra).
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Log cho thấy trigger tự động dẫn tới tx hash mà không có thao tác người dùng. Khóa ngăn chạy đồng thời.

#### F-061 · Executor tuần tự & signer service
`M1 · P0 · Nguồn: UC-02, S8 · Module: execution / signer`
- **Mô tả:** Executor chuyển các bước đã ký xác nhận thành lời gọi có kiểu tới module, gửi qua signer service riêng giữ khóa executor. Mỗi treasury chỉ chạy một bước, một yêu cầu tại một thời điểm.
- **Vấn đề giải quyết:** Cách ly khóa khỏi LLM và tiến trình API; an toàn về thứ tự.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Có kế hoạch đã ký xác nhận.
- **Đầu vào:** Bước, attestation.
- **Logic:** Kiểm tra lại trước khi gửi → mô phỏng (eth_call) đúng lời gọi → ký → lưu nonce và txHash trước khi broadcast (outbox) → broadcast → chuyển cho F-070.
- **Đầu ra:** Giao dịch đã gửi.
- **Luồng chính:** Mô phỏng ổn → gửi → theo dõi.
- **Luồng thay thế:** Mô phỏng revert → không broadcast → NeedsReview.
- **Tình huống biên:** Nonce trống hoặc giao dịch kẹt → giao dịch thay thế cùng nonce được theo dõi như bản thay thế, không phải khoản trả mới.
- **Phân quyền:** Signer chỉ nhận payload có attestation của validator.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Tiến trình LLM không có đường mạng tới signer ngoài qua validator (test kiến trúc). Outbox tồn tại qua sự cố sập.

#### F-062 · Thực thi REFILL
`M1 · P0 · Nguồn: D4, UC-02 · Module: contracts / execution`
- **Mô tả:** Chuyển stablecoin (hoặc gas native trong trần gas) từ T sang ví vận hành theo đường được phép, cho một yêu cầu và một bước cụ thể.
- **Vấn đề giải quyết:** P1.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Một bước trong kế hoạch.
- **Đầu vào:** ID yêu cầu, ID bước, số tiền.
- **Logic:** Contract kiểm tra: mandate Active, đường được phép, hạn mức refill, buffer `F_T`, ID bước chưa dùng, yêu cầu đã duyệt → thực thi qua module Safe → đánh dấu bước đã dùng.
- **Đầu ra:** Giao dịch và event `RefillExecuted`.
- **Luồng chính:** Refill 90 → xác nhận.
- **Luồng thay thế:** —
- **Tình huống biên:** Thử lại sau khi đã thành công → ID bước đã dùng → revert (AT-07).
- **Phân quyền:** Executor qua module.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** AT-02 và AT-07 đạt. Event mang ID yêu cầu và ID bước.

#### F-063 · Thực thi PAY
`M1 · P0 · Nguồn: D4, UC-02 · Module: contracts / execution`
- **Mô tả:** Trả đúng số tiền đã duyệt cho đúng payee từ ví trả.
- **Vấn đề giải quyết:** Công việc cốt lõi.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Một bước trong kế hoạch.
- **Đầu vào:** Dữ liệu yêu cầu, chữ ký duyệt, ngoại lệ (nếu có), attestation.
- **Logic:** Contract kiểm tra: chữ ký duyệt (đúng các trường), fingerprint chưa dùng, yêu cầu chưa dùng, payee Active, hạn mức mỗi khoản và mỗi ngày (hoặc ngoại lệ), buffer sau khi trả, không đang dừng → chuyển tiền → đánh dấu đã dùng và cập nhật bộ đếm trong cùng giao dịch.
- **Đầu ra:** Giao dịch và event `PaymentExecuted(requestId, fingerprint, payee, amount)`.
- **Luồng chính:** Trả 100 → xác nhận → Paid sau đủ số xác nhận.
- **Luồng thay thế:** Có ngoại lệ → ngoại lệ bị dùng hết.
- **Tình huống biên:** Token trả về false → coi là thất bại. Bất kỳ kiểm tra nào trượt → revert kèm mã lỗi.
- **Phân quyền:** Executor qua module.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Đã duyệt ở bước trước.
- **Nghiệm thu:** AT-01, AT-05, AT-06, AT-11 đạt; các invariant S1 giữ đúng.

#### F-064 · SWAP qua adapter được phép (router test có ghi nhãn)
`M1 · P2 · Nguồn: AT-04, R5 · Module: contracts / execution`
- **Mô tả:** Ở M1, swap stablecoin sang gas native qua adapter và router trong allowlist. Quote lấy từ nguồn đã cấu hình; `minOut` tính từ quote; allowance đúng bằng lượng vào và đặt lại về 0 trong cùng giao dịch. Router ở M1 do team triển khai và được ghi nhãn rõ.
- **Vấn đề giải quyết:** Thiếu gas (AT-03/04).
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Bước kế hoạch khi thiếu gas.
- **Đầu vào:** Quote, lượng vào.
- **Logic:** Kiểm tra hạn mức swap, độ mới của quote, cặp tài sản → approve đúng lượng → swap → approve(0) → kiểm tra `out ≥ minOut`.
- **Đầu ra:** Giao dịch.
- **Luồng chính:** Swap 5 USDC → gas → tiếp tục.
- **Luồng thay thế:** Không có quote hợp lệ → DỪNG.
- **Tình huống biên:** Agent cố hạ minOut → không thể (engine tính). Quote cũ → từ chối.
- **Phân quyền:** Executor qua module.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Cấu hình router và trượt giá.
- **Nghiệm thu:** AT-04, AT-13 đạt. Allowance bằng 0 sau mỗi lần swap (có test). Ghi nhãn "router test" trên UI và tài liệu.

#### F-065 · Swap DEX/aggregator thật với quote đã xác minh
`Later · Nguồn: Domain §5.3, Q2 · Module: contracts / integration`
- **Mô tả:** Swap thật qua DEX hoặc aggregator, quote được nguồn tin cậy ký và kiểm tra on-chain.
- **Vấn đề giải quyết:** Thanh khoản thật và bảo vệ giá thật.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Bước kế hoạch.
- **Đầu vào:** Quote đã ký.
- **Logic:** Adapter kiểm tra chữ ký quote, hạn dùng, cặp tài sản, người nhận.
- **Đầu ra:** Giao dịch.
- **Luồng chính:** Quote → swap.
- **Luồng thay thế:** Nguồn quote dự phòng.
- **Tình huống biên:** Depeg hoặc quote lệch → chặn.
- **Phân quyền:** Owner chọn nguồn quote.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Chọn nhà cung cấp.
- **Nghiệm thu:** Quote giả bị từ chối on-chain.

#### F-066 · Quản lý gas
`M1 · P1 · Nguồn: R7, Domain §5.4, O6 · Module: execution`
- **Mô tả:** Ví hạ tầng của executor được nạp gas trước. Trần cấp gas (native) tách riêng. Ghi phí thực tế từng giao dịch. Cảnh báo khi gas thấp.
- **Vấn đề giải quyết:** Lỗi "có USDC nhưng thiếu gas" (E3).
- **Người dùng:** Hệ thống, Owner.
- **Kích hoạt:** Mỗi giao dịch và khi chạm ngưỡng.
- **Đầu vào:** Dữ liệu phí.
- **Logic:** Kiểm tra mức phí trước khi gửi. Ghi phí thực tế, kể cả khi revert. Cảnh báo khi dưới ngưỡng. Gas native không bao giờ dùng để PAY cho nhà cung cấp.
- **Đầu ra:** Bản ghi phí và cảnh báo.
- **Luồng chính:** Đủ gas → gửi.
- **Luồng thay thế:** Gas thấp → cảnh báo → Owner nạp thêm, hoặc kế hoạch có bước refill/swap gas.
- **Tình huống biên:** Không còn gas ở đâu → DỪNG kèm thông báo rõ (R7).
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Quan sát.
- **Vai trò con người:** Nạp thêm khi được cảnh báo.
- **Nghiệm thu:** 100% giao dịch được ghi phí. AT-03 đạt.

#### F-067 · Bridge liên chain
`Later · Nguồn: D5, Q2 · Module: execution / integration`
- **Mô tả:** Chuyển tiền giữa các treasury trên chain khác nhau qua bridge trong allowlist.
- **Vấn đề giải quyết:** Thanh khoản kẹt trên chain khác.
- **Người dùng:** Hệ thống, Owner.
- **Kích hoạt:** Lập kế hoạch đa chain.
- **Đầu vào:** Route bridge.
- **Logic:** Tiền đang chuyển không tính vào số dư. Hạn mức riêng. Theo dõi timeout.
- **Đầu ra:** Giao dịch bridge.
- **Luồng chính:** Bridge → xác minh tiền đã tới.
- **Luồng thay thế:** —
- **Tình huống biên:** Bridge kẹt → trạng thái Unknown, không gửi lại.
- **Phân quyền:** Mandate phải cho phép.
- **Vai trò AI:** Đề xuất.
- **Vai trò con người:** Chọn bridge được phép.
- **Nghiệm thu:** Không bridge trùng khi timeout (có test).

### 3.7 Xác minh & Đối soát

#### F-070 · Theo dõi & xác nhận giao dịch
`M1 · P0 · Nguồn: UC-03 · Module: verification`
- **Mô tả:** Theo dõi mọi giao dịch qua các trạng thái `NotSubmitted → Submitted → Pending → Confirmed | Reverted | Unknown`, với độ sâu xác nhận theo từng chain.
- **Vấn đề giải quyết:** Đã broadcast chưa có nghĩa là xong. Chỉ ghi Paid sau khi đủ xác nhận.
- **Người dùng:** Hệ thống; mọi người đều xem được.
- **Kích hoạt:** Sau broadcast; theo lịch polling hoặc subscription.
- **Đầu vào:** txHash, nonce.
- **Logic:** Poll receipt. Phát hiện reorg qua blockHash. Quá thời gian thì chuyển Unknown, không bao giờ chuyển Failed.
- **Đầu ra:** Trạng thái giao dịch và receipt.
- **Luồng chính:** Pending → Confirmed sau N block.
- **Luồng thay thế:** Giao dịch thay thế (cùng nonce) được liên kết.
- **Tình huống biên:** Reorg → quay về Pending.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Mô phỏng reorg trên Anvil thì trạng thái được đánh giá lại. Không giao dịch nào được ghi Paid trước N xác nhận.

#### F-071 · Kiểm tra hậu điều kiện
`M1 · P0 · Nguồn: UC-02, GA p.14 · Module: verification`
- **Mô tả:** Sau mỗi bước đã xác nhận, kiểm tra kết quả kỳ vọng: số dư đổi đúng mức, yêu cầu đã được đánh dấu dùng on-chain, allowance bằng 0 sau swap, bộ đếm đã tăng.
- **Vấn đề giải quyết:** Giao dịch không revert chưa chứng minh là đúng.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Có xác nhận.
- **Đầu vào:** Biến động kỳ vọng từ kế hoạch; đọc trạng thái sau.
- **Logic:** So sánh → `PASSED | DISCREPANCY | UNKNOWN`. Lệch → NeedsReview, đồng thời gửi tín hiệu cho circuit breaker.
- **Đầu ra:** Bản ghi xác minh.
- **Luồng chính:** PASSED.
- **Luồng thay thế:** —
- **Tình huống biên:** Owner chuyển tiền ngoài cùng lúc → giải thích là "phát hiện thay đổi từ bên ngoài".
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Đề xuất (giải thích chênh lệch).
- **Vai trò con người:** Xử lý chênh lệch.
- **Nghiệm thu:** Mọi bước đã xác nhận đều có bản ghi xác minh.

#### F-072 · Đối soát (Paid khác Matched)
`M1 · P0 · Nguồn: UC-03 · Module: reconciliation`
- **Mô tả:** Liên kết mỗi yêu cầu với mọi giao dịch của nó (refill, swap, pay), phí và phân loại: refill là chuyển nội bộ, swap là chuyển đổi, pay là chi phí bên ngoài. Trạng thái đối soát: `NotReady → Pending → Matched | Discrepancy`.
- **Vấn đề giải quyết:** P5.
- **Người dùng:** Finance.
- **Kích hoạt:** Yêu cầu đã Paid.
- **Đầu vào:** Yêu cầu, giao dịch, receipt, dữ liệu hóa đơn.
- **Logic:** Tự đối chiếu số tiền, payee, fingerprint và tx. Finance xác nhận Matched, hoặc hệ thống tự Matched khi mọi bằng chứng khớp nếu tổ chức bật cấu hình này.
- **Đầu ra:** Bản ghi đối soát.
- **Luồng chính:** Paid → bằng chứng khớp → Finance đánh dấu Matched.
- **Luồng thay thế:** Chênh lệch → ghi chú → xử lý.
- **Tình huống biên:** Refill xong nhưng pay bị chặn → refill hiện là chuyển nội bộ, không có chi phí.
- **Phân quyền:** Finance.
- **Vai trò AI:** Đề xuất (tóm tắt chênh lệch).
- **Vai trò con người:** Đánh dấu Matched.
- **Nghiệm thu:** Refill không bao giờ bị ghi thành chi phí nhà cung cấp (có test). Một yêu cầu có thể gắn nhiều giao dịch.

#### F-073 · Xuất đối soát (CSV / bút toán)
`M1 · P1 · Nguồn: T5 · Module: reconciliation`
- **Mô tả:** Xuất CSV theo kỳ cùng bút toán kép đơn giản: Nợ chi phí nhà cung cấp / Có ví stablecoin; refill là chuyển giữa các tài khoản ví; gas là chi phí phí giao dịch.
- **Vấn đề giải quyết:** Bàn giao cho kế toán.
- **Người dùng:** Finance, Auditor.
- **Kích hoạt:** Xuất thủ công.
- **Đầu vào:** Kỳ, treasury.
- **Logic:** Ánh xạ xác định, hệ thống tài khoản cấu hình được.
- **Đầu ra:** File CSV.
- **Luồng chính:** Chọn kỳ → tải về.
- **Luồng thay thế:** —
- **Tình huống biên:** Khoản chưa khớp vẫn được xuất, có cột trạng thái.
- **Phân quyền:** Finance, Auditor.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Cấu hình ánh xạ tài khoản.
- **Nghiệm thu:** Tổng trong file bằng tổng on-chain của kỳ (có test).

#### F-074 · Attestation thanh toán on-chain
`M1 · P2 · Nguồn: N6 · Module: reconciliation / contracts`
- **Mô tả:** Ghi một attestation (ví dụ EAS, nếu chain hỗ trợ) cho mỗi yêu cầu đã trả: `{hash fingerprint, requestId, payTxHash, số tiền, payee, thời điểm}`. Không chứa dữ liệu cá nhân.
- **Vấn đề giải quyết:** Bằng chứng thanh toán mà bên thứ ba kiểm chứng được; giúp lấy điểm thưởng on-chain.
- **Người dùng:** Finance, Auditor, nhà cung cấp (để kiểm chứng).
- **Kích hoạt:** Khi Matched (hoặc Paid, tùy cấu hình).
- **Đầu vào:** Bản ghi đối soát.
- **Logic:** Đăng ký schema một lần. Giao dịch attestation được theo dõi như các giao dịch khác.
- **Đầu ra:** UID của attestation.
- **Luồng chính:** Matched → attestation.
- **Luồng thay thế:** Tổ chức tắt tính năng.
- **Tình huống biên:** Attestation lỗi → thử lại, không ảnh hưởng trạng thái thanh toán.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Bật tính năng.
- **Nghiệm thu:** UID tra được trên explorer; không chứa dữ liệu cá nhân.

#### F-075 · Tích hợp ERP / kế toán
`Later · Nguồn: D5, Q2 · Module: integration`
- **Mô tả:** Đồng bộ nhà cung cấp, hóa đơn và thanh toán với Xero / QuickBooks / NetSuite.
- **Vấn đề giải quyết:** Nhập liệu hai lần.
- **Người dùng:** Finance.
- **Kích hoạt:** Theo lịch đồng bộ hoặc webhook.
- **Đầu vào:** Kết nối OAuth.
- **Logic:** Hóa đơn nhập vào là bản nháp (không bao giờ được duyệt sẵn). Khoản đã trả được đồng bộ ngược kèm tham chiếu tx.
- **Đầu ra:** Bản ghi đã đồng bộ.
- **Luồng chính:** Hóa đơn trong ERP → bản nháp → trả → đánh dấu đã trả trong ERP.
- **Luồng thay thế:** —
- **Tình huống biên:** Sửa xung đột → ERP là nguồn chuẩn cho dữ liệu hóa đơn; TreasuryPilot là nguồn chuẩn cho trạng thái thanh toán.
- **Phân quyền:** OrgAdmin kết nối.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Duyệt.
- **Nghiệm thu:** Không lần đồng bộ ERP nào duyệt được thanh toán.

### 3.8 Phục hồi & Xử lý ngoại lệ

#### F-080 · Phục hồi trạng thái Unknown (không trả trùng)
`M1 · P0 · Nguồn: R8, AT-06, T3 · Module: recovery`
- **Mô tả:** Sau timeout, sự cố sập hoặc mất kết nối, xác định kết quả của từng thao tác đang dở bằng txHash, nonce và cờ `requestUsed`/`stepUsed` on-chain trước khi làm bất cứ việc gì mới.
- **Vấn đề giải quyết:** Rủi ro trả trùng.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Worker khởi động lại, giao dịch Unknown, lỗi RPC.
- **Đầu vào:** Các bản ghi outbox.
- **Logic:** Với từng thao tác: on-chain báo đã dùng → ghi Confirmed/Paid; đang pending → chờ; chưa từng broadcast → được gửi với **cùng định danh**. Treasury bị chặn thực thi khi còn thao tác Unknown.
- **Đầu ra:** Trạng thái thao tác đã được xác định.
- **Luồng chính:** Tắt executor sau broadcast → khởi động lại → tìm thấy giao dịch → không trả lần hai.
- **Luồng thay thế:** Giao dịch bị rớt → gửi lại cùng ID yêu cầu và ID bước (contract chống trùng).
- **Tình huống biên:** Không xác định được quá ngưỡng thời gian → NeedsReview.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có (AI không tham gia quyết định phục hồi).
- **Vai trò con người:** Xử lý NeedsReview.
- **Nghiệm thu:** Test sập (T3): đúng một giao dịch PAY on-chain qua 20 lần lặp.

#### F-081 · Xử lý hoàn thành một phần
`M1 · P0 · Nguồn: AT-07 · Module: recovery`
- **Mô tả:** Refill thành công nhưng trả bị chặn hoặc lỗi → giữ nguyên refill, ghi "hoàn thành một phần", không tự đảo ngược. Thử lại thì tiếp từ bước chưa xong.
- **Vấn đề giải quyết:** Kế hoạch nhiều giao dịch không có tính nguyên tử.
- **Người dùng:** Hệ thống, Operator.
- **Kích hoạt:** Một bước lỗi sau khi các bước trước đã thành công.
- **Đầu vào:** Trạng thái kế hoạch.
- **Logic:** Đánh dấu các bước đã xong → yêu cầu chuyển NeedsReview hoặc thử lại → khi thử lại thì kiểm tra lại và bỏ qua bước đã xong.
- **Đầu ra:** Trạng thái hoàn thành một phần, hiển thị rõ.
- **Luồng chính:** Refill xong, pay bị chặn (payee bị tạm ngưng) → một phần → xử lý sau → chỉ chạy pay.
- **Luồng thay thế:** Hủy yêu cầu → tiền đã refill nằm lại ở O1 (có báo).
- **Tình huống biên:** —
- **Phân quyền:** Operator được thử lại hoặc hủy.
- **Vai trò AI:** Đề xuất bước tiếp theo.
- **Vai trò con người:** Quyết định thử lại hay hủy.
- **Nghiệm thu:** AT-07: không refill trùng khi thử lại.

#### F-082 · Hàng đợi cần xem xét & định tuyến ngoại lệ
`M1 · P0 · Nguồn: UC-04, FJ · Module: recovery`
- **Mô tả:** Mọi điểm dừng vào một hàng đợi, được phân loại: lỗi chính sách hoặc dữ liệu; lỗi thử lại được; kết quả chưa rõ; cần quyền; lỗi hạ tầng. Mỗi mục có mã lý do, các bước đã xong và hành động cho từng vai trò.
- **Vấn đề giải quyết:** Ngoại lệ không bị mất, không bị "tự sửa" bằng cách nới chính sách.
- **Người dùng:** Operator, Owner, Finance.
- **Kích hoạt:** BLOCK, NEEDS_APPROVAL, chênh lệch, Unknown, AI bị loại.
- **Đầu vào:** Sự kiện và bối cảnh.
- **Logic:** Chuyển tới đúng vai trò: vượt trần → Owner (F-025); thay payee hoặc ngân sách → Owner sửa chính sách; thay số tiền hoặc payee của nghĩa vụ → duyệt lại.
- **Đầu ra:** Các mục trong hàng đợi, có đồng hồ SLA.
- **Luồng chính:** Mục → đúng vai trò xử lý.
- **Luồng thay thế:** Quá SLA → leo thang (thông báo).
- **Tình huống biên:** Một yêu cầu nhiều lỗi → liệt kê cùng nhau, luật cứng hiển thị trước.
- **Phân quyền:** Theo loại mục.
- **Vai trò AI:** Đề xuất (giải thích).
- **Vai trò con người:** Xử lý.
- **Nghiệm thu:** Mỗi kết quả không phải ALLOW tạo đúng một mục mở, chỉ đóng khi có hành động rõ ràng.

#### F-083 · Chính sách retry idempotent
`M1 · P0 · Nguồn: UC-04 · Module: recovery / execution`
- **Mô tả:** Khi thử lại, giữ nguyên request_id, step_id, operation id và idempotency key. Lỗi thử lại được (RPC, nonce, giá gas) dùng backoff hàm mũ, tối đa N lần.
- **Vấn đề giải quyết:** Thử lại sinh ra nghĩa vụ mới hoặc lách chống trùng.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Lỗi thử lại được.
- **Đầu vào:** Thao tác.
- **Logic:** Phân loại lỗi → thử lại hoặc dừng. Không bao giờ sinh ID mới khi thử lại.
- **Đầu ra:** Thao tác được thử lại.
- **Luồng chính:** RPC 503 → thử lại → thành công.
- **Luồng thay thế:** Quá số lần → NeedsReview.
- **Tình huống biên:** Thử lại sau khi đã tạm dừng → bị chặn.
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Không có.
- **Nghiệm thu:** Test ID giữ nguyên qua các lần thử lại đạt.

### 3.9 Nền tảng AI

#### F-090 · Treasury Copilot (hỏi "nếu… thì sao")
`M1 · P1 · Nguồn: N4 · Module: agent`
- **Mô tả:** Giao diện chat để Owner, Finance, Operator hỏi về quỹ, ví dụ "Tuần này trả hết được không mà không phá buffer?" hay "Nếu hoãn hóa đơn C thì sao?". Agent trả lời bằng tool chỉ đọc và chạy engine xác định ở **chế độ mô phỏng**.
- **Vấn đề giải quyết:** Hỗ trợ ra quyết định nhanh, có giải thích; nâng chất lượng tương tác.
- **Người dùng:** Owner, Finance, Operator; Auditor chỉ đọc.
- **Kích hoạt:** Người dùng đặt câu hỏi.
- **Đầu vào:** Câu hỏi và bối cảnh tổ chức, giới hạn theo vai trò.
- **Logic:**
  - Tool có sẵn: `get_snapshot`, `list_requests`, `simulate_schedule`, `get_policy_summary`, `explain_decision`.
  - Mọi con số trong câu trả lời phải lấy từ kết quả tool và có trích dẫn.
  - **Không có tool ghi.** Copilot chỉ được *gợi ý* mở form bản nháp hoặc form ngoại lệ; người dùng tự hoàn tất.
- **Đầu ra:** Câu trả lời gồm số liệu, kế hoạch và trích dẫn.
- **Luồng chính:** Hỏi → mô phỏng → trả lời.
- **Luồng thay thế:** Câu hỏi ngoài phạm vi → Copilot nói rõ là không trả lời được.
- **Tình huống biên:** Văn bản hóa đơn đã lưu có lệnh chèn → coi là dữ liệu. Người dùng yêu cầu trả tiền → từ chối và chỉ sang luồng duyệt.
- **Phân quyền:** Dữ liệu giới hạn theo vai trò của người hỏi.
- **Vai trò AI:** Quan sát, Đề xuất.
- **Vai trò con người:** Mọi hành động.
- **Nghiệm thu:** Bộ 20 câu hỏi có số liệu khớp engine. Audit log cho thấy không có tác dụng phụ nào.

#### F-091 · Ranh giới dữ liệu không tin cậy & chống prompt injection
`M1 · P0 · Nguồn: AT-09, AD-01, S5 · Module: agent / security`
- **Mô tả:** Mọi nội dung bên ngoài (hóa đơn, email, ghi chú nhà cung cấp, metadata token) được bọc như dữ liệu và gắn nhãn nguồn. Ngoài ra còn có:
  - giới hạn độ dài và chuẩn hóa đầu vào;
  - schema đầu ra chặt;
  - allowlist tool;
  - validator chạy sau LLM;
  - không đưa bí mật vào prompt.
- **Vấn đề giải quyết:** Lệnh chèn làm đổi payee hoặc hạn mức.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Mọi lần gọi LLM.
- **Đầu vào:** Nội dung.
- **Logic:** Theo hướng dẫn OWASP cho LLM: tách dữ liệu khỏi chỉ thị, giới hạn tool, kiểm tra trước khi hành động. Prompt không bao giờ là cơ chế kiểm soát duy nhất.
- **Đầu ra:** Lời gọi LLM đã được làm sạch, kèm cờ injection.
- **Luồng chính:** Hóa đơn có lệnh chèn bị gắn cờ và không gây tác động gì.
- **Luồng thay thế:** —
- **Tình huống biên:** Địa chỉ dùng ký tự Unicode giống hệt chữ thật → kiểm tra địa chỉ bằng code xác định (so checksum với danh bạ).
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Bộ red-team 20 hóa đơn: không có lần nào đổi được trường hoặc chính sách. AT-09 và AD-01 đạt.

#### F-092 · Bộ đánh giá AI (B1 và B2)
`M1 · P0 · Nguồn: N3, Autonomy §6 · Module: agent / quality`
- **Mô tả:** Benchmark tái lập được, gồm từ 30 kịch bản trở lên (yêu cầu chi, điều khoản, số dư, hạn mức).
  - **B1:** baseline rule xác định (EDF cộng mẫu).
  - **B2:** lập kế hoạch có AI hỗ trợ.
  - **Chỉ số:** stablecoin tiết kiệm (chiết khấu trừ phạt), tỷ lệ đúng hạn, số ngoại lệ cần, số giao dịch, phí, số vi phạm (phải bằng 0), độ trễ, chi phí model.
- **Vấn đề giải quyết:** Trả lời câu hỏi "vì sao cần AI?" bằng dữ liệu trung thực.
- **Người dùng:** Team, giám khảo.
- **Kích hoạt:** CI hoặc chạy tay.
- **Đầu vào:** File kịch bản kèm đáp án chuẩn.
- **Logic:**
  - B1 và B2 dùng cùng dữ liệu, cùng quyền, cùng kiểm tra.
  - Tách bộ dùng khi phát triển và bộ giữ lại để kiểm tra.
  - Không đưa đáp án vào prompt.
- **Đầu ra:** Báo cáo (markdown + CSV).
- **Luồng chính:** Chạy → báo cáo.
- **Luồng thay thế:** —
- **Tình huống biên:** Kết quả AI không ổn định → chạy N lần, báo trung bình và độ phân tán.
- **Phân quyền:** —
- **Vai trò AI:** Đối tượng được đánh giá.
- **Vai trò con người:** Viết kịch bản và đáp án.
- **Nghiệm thu:** Chạy bằng một lệnh. Báo cáo có cả các ca B2 kém hơn B1.

#### F-093 · Nhật ký quyết định AI
`M1 · P0 · Nguồn: Autonomy §5 · Module: agent / audit`
- **Mô tả:** Mỗi lần gọi AI đều ghi lại:
  - mục đích;
  - model và phiên bản;
  - phiên bản prompt;
  - tham chiếu đầu vào (không chứa bí mật);
  - các lần gọi tool;
  - đầu ra;
  - kết quả kiểm tra;
  - plannerSource;
  - độ trễ và chi phí.
- **Vấn đề giải quyết:** Truy vết được câu hỏi "vì sao agent làm vậy?".
- **Người dùng:** Auditor, team.
- **Kích hoạt:** Mọi lần gọi LLM.
- **Đầu vào:** —
- **Logic:** Chỉ ghi thêm, không sửa. Liên kết với ID yêu cầu chi và ID kế hoạch. Che dữ liệu cá nhân.
- **Đầu ra:** Bản ghi nhật ký.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** Ghi log lỗi → lần lập kế hoạch đó thất bại theo hướng an toàn. Không có quyết định AI nào không được ghi.
- **Phân quyền:** Auditor, OrgAdmin được đọc.
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** 100% kế hoạch liên kết tới một bản ghi AI hoặc RULE_BASED.

#### F-094 · Adapter & định tuyến model
`M1 · P1 · Nguồn: NEW · Module: agent`
- **Mô tả:** Giao diện gọi LLM không phụ thuộc nhà cung cấp (structured output, tool calling, timeout). Chọn model theo từng tác vụ, ví dụ model rẻ để trích xuất, model mạnh để giải thích kế hoạch. Có nhà cung cấp dự phòng.
- **Vấn đề giải quyết:** Bị khóa vào một nhà cung cấp; chi phí; tính sẵn sàng.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Mọi lần gọi LLM.
- **Đầu vào:** Loại tác vụ.
- **Logic:** Bảng định tuyến trong cấu hình. Quá thời gian → chuyển sang F-054 hoặc luồng thủ công.
- **Đầu ra:** Phản hồi của model.
- **Luồng chính:** —
- **Luồng thay thế:** Nhà cung cấp chính sập → chuyển sang nhà cung cấp phụ.
- **Tình huống biên:** Schema lệch giữa các nhà cung cấp → bước kiểm tra phát hiện.
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Đổi nhà cung cấp chỉ cần sửa cấu hình. Có contract test cho từng nhà cung cấp.

### 3.10 Thông báo

#### F-100 · Thông báo trong app
`M1 · P1 · Nguồn: Q16 · Module: notification`
- **Mô tả:** Trung tâm thông báo cho các sự kiện: cần duyệt, cần ngoại lệ, đã trả, cần xem xét, đã tạm dừng, có bất thường, gas thấp.
- **Vấn đề giải quyết:** Người dùng hành động kịp thời.
- **Người dùng:** Tất cả, theo vai trò.
- **Kích hoạt:** Sự kiện nghiệp vụ.
- **Đầu vào:** Sự kiện.
- **Logic:** Định tuyến sự kiện tới người nhận theo vai trò. Có trạng thái đã đọc/chưa đọc.
- **Đầu ra:** Thông báo.
- **Luồng chính:** Có sự kiện → huy hiệu chuông → bấm → mở deep link.
- **Luồng thay thế:** —
- **Tình huống biên:** Sự kiện trùng → bỏ trùng theo ID sự kiện.
- **Phân quyền:** Theo vai trò.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Hành động.
- **Nghiệm thu:** Mỗi loại sự kiện được định tuyến đều có test. Không lộ dữ liệu giữa các tổ chức.

#### F-101 · Thông báo Telegram kèm deep link
`M1 · P2 · Nguồn: N7, Q16 · Module: notification`
- **Mô tả:** Mỗi người dùng liên kết với bot Telegram. Bot gửi cùng các sự kiện, kèm link mở web app. **Không ký gì trong Telegram.**
- **Vấn đề giải quyết:** Phản ứng nhanh khi không ngồi máy.
- **Người dùng:** Người dùng tự chọn bật.
- **Kích hoạt:** Sự kiện nghiệp vụ.
- **Đầu vào:** chat id đã liên kết.
- **Logic:** Liên kết bằng mã một lần. Nội dung tối thiểu: không hiện đầy đủ địa chỉ hay số tiền nếu người dùng không bật.
- **Đầu ra:** Tin nhắn Telegram.
- **Luồng chính:** "Hóa đơn B cần ngoại lệ → mở app".
- **Luồng thay thế:** Hủy liên kết.
- **Tình huống biên:** Người dùng chặn bot → đánh dấu kênh không hoạt động.
- **Phân quyền:** Tự quản lý.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Hành động trong app.
- **Nghiệm thu:** Trong demo, tin nhắn đến trong vòng 10 giây sau sự kiện. Không hoàn tất được hành động nào trong Telegram.

#### F-102 · Thông báo email
`Later · Nguồn: Q16 · Module: notification`
- **Mô tả:** Kênh email cho cùng các sự kiện, kèm bản tổng hợp.
- **Vấn đề giải quyết:** Tiếp cận người dùng khi họ không mở app.
- **Người dùng:** Tất cả.
- **Kích hoạt:** Sự kiện hoặc bản tổng hợp hằng ngày.
- **Đầu vào:** Email.
- **Logic:** Có mẫu email; hủy đăng ký theo từng loại, trừ sự kiện bảo mật.
- **Đầu ra:** Email.
- **Luồng chính:** —
- **Luồng thay thế:** Chế độ tổng hợp.
- **Tình huống biên:** Email bị trả về.
- **Phân quyền:** Tự quản lý.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Không hủy đăng ký được sự kiện bảo mật.

#### F-103 · Webhook gửi ra
`Later · Nguồn: Q16 · Module: integration`
- **Mô tả:** Webhook có chữ ký, gửi sự kiện tới hệ thống của khách.
- **Vấn đề giải quyết:** Tích hợp.
- **Người dùng:** Đơn vị tích hợp.
- **Kích hoạt:** Sự kiện.
- **Đầu vào:** Endpoint, secret.
- **Logic:** Chữ ký HMAC; thử lại với backoff; có ID sự kiện.
- **Đầu ra:** Các request POST.
- **Luồng chính:** —
- **Luồng thay thế:** Gửi lại từ dashboard.
- **Tình huống biên:** Endpoint sập → thử lại → chuyển vào hàng đợi lỗi.
- **Phân quyền:** OrgAdmin.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Cách kiểm tra chữ ký có tài liệu và có test.

#### F-104 · Thông báo Slack / Lark / WeCom
`Later · Nguồn: Q16 · Module: notification`
- **Mô tả:** Kênh nền tảng chat, kèm deep link.
- **Vấn đề giải quyết:** Quy trình làm việc nhóm, kể cả công cụ chat phổ biến ở thị trường Trung Quốc.
- **Người dùng:** Các team.
- **Kích hoạt:** Sự kiện.
- **Đầu vào:** Kết nối workspace.
- **Logic:** Như F-101.
- **Đầu ra:** Tin nhắn.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** OrgAdmin kết nối.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Hỗ trợ cùng tập sự kiện như Telegram.

#### F-105 · Tùy chọn nhận thông báo
`Later · Nguồn: NEW · Module: notification`
- **Mô tả:** Mỗi người chọn kênh, loại thông báo và giờ yên lặng.
- **Vấn đề giải quyết:** Quá nhiều thông báo.
- **Người dùng:** Tất cả.
- **Kích hoạt:** Cài đặt.
- **Đầu vào:** Tùy chọn.
- **Logic:** Sự kiện bảo mật và sự kiện SLA duyệt luôn được gửi qua ít nhất một kênh.
- **Đầu ra:** Tùy chọn đã lưu.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** Tự quản lý.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Không tắt hoàn toàn được các loại bắt buộc.

### 3.11 Tuân thủ

#### F-110 · Sàng lọc payee theo danh sách trừng phạt/chặn
`M1 · P1 · Nguồn: S6, Q17 · Module: compliance`
- **Mô tả:** Sàng lọc địa chỉ payee khi đăng ký và trước mỗi lần PAY, qua một nhà cung cấp sàng lọc. M1 dùng dữ liệu mẫu có nhãn, lấy từ danh sách trừng phạt công khai, cộng một danh sách chặn tự quản.
- **Vấn đề giải quyết:** Trả cho địa chỉ bị trừng phạt hoặc đã biết là độc hại.
- **Người dùng:** Hệ thống, Owner.
- **Kích hoạt:** Đăng ký payee; trước khi PAY.
- **Đầu vào:** Địa chỉ.
- **Logic:**
  - Giao diện adapter: `screen(address) → {kết quả, nguồn, thời điểm kiểm}`.
  - Trúng danh sách → BLOCK.
  - Nhà cung cấp lỗi khi đăng ký → mặc định đóng (không cho đăng ký).
  - Nhà cung cấp lỗi khi PAY → dùng kết quả cache gần đây còn trong TTL; nếu không có thì chặn.
- **Đầu ra:** Bản ghi sàng lọc.
- **Luồng chính:** Sạch → tiếp tục.
- **Luồng thay thế:** Trúng → BLOCK và báo Owner.
- **Tình huống biên:** Báo nhầm → cần ghi đè thủ công kèm lý do (Later; M1 chỉ chặn).
- **Phân quyền:** Hệ thống.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Xem xét các trường hợp trúng.
- **Nghiệm thu:** Địa chỉ trong danh sách chặn không đăng ký và không trả được (có test). Dữ liệu mẫu ghi nhãn "TEST DATA".

#### F-111 · KYB khi onboarding
`Later · Nguồn: Q17 · Module: compliance`
- **Mô tả:** Xác minh doanh nghiệp qua nhà cung cấp trước khi kích hoạt treasury trên mainnet.
- **Vấn đề giải quyết:** Onboarding theo yêu cầu pháp lý.
- **Người dùng:** OrgAdmin.
- **Kích hoạt:** Kích hoạt mainnet.
- **Đầu vào:** Giấy tờ công ty.
- **Logic:** Adapter nhà cung cấp; trạng thái KYB là điều kiện để kích hoạt mainnet.
- **Đầu ra:** Trạng thái KYB.
- **Luồng chính:** Nộp → được duyệt.
- **Luồng thay thế:** Xem xét thủ công.
- **Tình huống biên:** Hết hạn → xác minh lại.
- **Phân quyền:** OrgAdmin.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Cung cấp giấy tờ.
- **Nghiệm thu:** Không có KYB thì không kích hoạt được treasury mainnet.

#### F-112 · Hỗ trợ Travel Rule
`Later · Nguồn: Q17 · Module: compliance`
- **Mô tả:** Với các giao dịch thuộc diện áp dụng, trao đổi thông tin người gửi và người nhận qua nhà cung cấp giao thức Travel Rule.
- **Vấn đề giải quyết:** Yêu cầu pháp lý ở một số khu vực.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** PAY vượt ngưỡng tới địa chỉ do sàn hoặc VASP quản lý.
- **Đầu vào:** Dữ liệu các bên.
- **Logic:** Adapter nhà cung cấp; ngưỡng theo từng khu vực pháp lý.
- **Đầu ra:** Bản ghi Travel Rule.
- **Luồng chính:** —
- **Luồng thay thế:** Ví tự quản → dùng luồng attestation.
- **Tình huống biên:** VASP bên nhận không liên lạc được → tạm giữ.
- **Phân quyền:** —
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Xác định cùng nhà cung cấp được chọn.

#### F-113 · Tối thiểu hóa dữ liệu
`M1 · P0 · Nguồn: Use-Case §2, S6 · Module: compliance / platform`
- **Mô tả:**
  - Chỉ đưa hash hoặc commitment (hash hóa đơn, fingerprint) lên chain.
  - Tệp hóa đơn và dữ liệu cá nhân của nhà cung cấp lưu ở kho riêng tư.
  - Lời gọi LLM chỉ gửi nội dung tối thiểu cần thiết, và bật cấu hình không lưu dữ liệu ở phía nhà cung cấp nếu có.
- **Vấn đề giải quyết:** Quyền riêng tư; dữ liệu đã lên chain thì không xóa được.
- **Người dùng:** Hệ thống.
- **Kích hoạt:** Luôn luôn.
- **Đầu vào:** —
- **Logic:** Phân loại dữ liệu theo trường: Public / Internal / Confidential / Secret. Mã hóa khi lưu với dữ liệu Confidential. Che dữ liệu trong log.
- **Đầu ra:** —
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Rà event và calldata của contract không thấy dữ liệu cá nhân. Test che log đạt.

#### F-114 · Chính sách lưu trữ & vùng dữ liệu
`Later · Nguồn: Q17 · Module: compliance / platform`
- **Mô tả:** Cấu hình thời gian lưu trữ, quy trình xóa, và chọn vùng địa lý lưu dữ liệu.
- **Vấn đề giải quyết:** Nghĩa vụ kiểu GDPR/PDPL.
- **Người dùng:** OrgAdmin, PlatformAdmin.
- **Kích hoạt:** Theo chính sách hoặc khi có yêu cầu xóa.
- **Đầu vào:** Chính sách.
- **Logic:** Bằng chứng audit được giữ theo mức tối thiểu luật định. Xóa dữ liệu vẫn để lại hash trên chain (không chứa dữ liệu cá nhân).
- **Đầu ra:** —
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** Lệnh giữ pháp lý được ưu tiên hơn yêu cầu xóa.
- **Phân quyền:** OrgAdmin.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Quy trình xóa có test. Việc chọn vùng được thực thi ở tầng lưu trữ.

### 3.12 Audit & Bằng chứng

#### F-120 · Nhật ký audit nối hash & event on-chain
`M1 · P0 · Nguồn: S6, GA p.14 · Module: audit`
- **Mô tả:** Nhật ký chỉ ghi thêm cho mọi thao tác người dùng, chuyển trạng thái, quyết định kiểm tra, quyết định AI và giao dịch. Mỗi bản ghi chứa hash của bản ghi trước. Contract phát event cho mọi thay đổi quyền và mọi lần thực thi.
- **Vấn đề giải quyết:** Truy vết, phát hiện được chỉnh sửa.
- **Người dùng:** Auditor, OrgAdmin.
- **Kích hoạt:** Mọi thao tác.
- **Đầu vào:** Sự kiện.
- **Logic:** `hash_i = H(bản ghi_i ‖ hash_{i-1})`. Tùy chọn neo hằng ngày: đưa hash gốc lên chain (Later).
- **Đầu ra:** Bản ghi audit.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** Ghi audit lỗi → thao tác tài chính thất bại theo hướng an toàn.
- **Phân quyền:** Auditor, OrgAdmin được đọc. Không ai được sửa hoặc xóa.
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Script kiểm tra phát hiện bất kỳ bản ghi nào bị sửa.

#### F-121 · Xuất gói bằng chứng
`M1 · P0 · Nguồn: GA p.39, AT §6 · Module: audit`
- **Mô tả:** Gói JSON cho từng yêu cầu chi hoặc từng kịch bản, gồm:
  - môi trường, chainId, các contract;
  - bản duyệt, phiên bản chính sách;
  - kế hoạch và planHash;
  - tham chiếu snapshot;
  - quyết định của validator, plannerSource;
  - attestation;
  - các txHash và receipt;
  - trạng thái sau thực thi, kết quả xác minh;
  - các giới hạn còn lại.
- **Vấn đề giải quyết:** "Bằng chứng thực thi" theo yêu cầu cuộc thi; phục vụ audit doanh nghiệp.
- **Người dùng:** Auditor, Finance, team.
- **Kích hoạt:** Xuất thủ công hoặc từ scenario runner.
- **Đầu vào:** ID yêu cầu chi.
- **Logic:** Ghép từ các bản ghi đã lưu. Dữ liệu mẫu được ghi nhãn. **Không bao giờ** chứa hash bịa.
- **Đầu ra:** File JSON kèm README.
- **Luồng chính:** Xuất → tải file.
- **Luồng thay thế:** Xuất hàng loạt theo kỳ.
- **Tình huống biên:** Bị chặn trước khi broadcast nên không có tx hash → đính kèm log validator và tham chiếu test contract thay thế.
- **Phân quyền:** Auditor, Finance, OrgAdmin.
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Gói hợp lệ theo JSON schema. Mọi hash đều tra được trên explorer.

#### F-122 · Nhãn mức bao phủ & mức chắc chắn
`M1 · P1 · Nguồn: GA p.5 · Module: audit / UX`
- **Mô tả:** Mọi đánh giá, snapshot và trạng thái đều mang nhãn `coverage: COMPLETE_WITHIN_SCOPE | PARTIAL | UNKNOWN`, kèm phần dữ liệu còn thiếu. UI dùng từ ngữ chính xác, ví dụ "Đã gửi lệnh trả, đang chờ xác nhận" chứ không phải "Đã trả".
- **Vấn đề giải quyết:** Tín hiệu giả kiểu "an toàn" hay "đã xong".
- **Người dùng:** Tất cả.
- **Kích hoạt:** Ở mọi nơi.
- **Đầu vào:** —
- **Logic:** Thiếu dữ liệu bắt buộc → không bao giờ ALLOW. Tuân theo quy tắc từ ngữ UI (GA p.32).
- **Đầu ra:** Nhãn.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Checklist từ ngữ UI đã được rà soát. Không có nhãn "an toàn" hay "xong" nếu trạng thái chưa được xác minh.

### 3.13 Trải nghiệm người dùng

#### F-130 · Dashboard treasury
`M1 · P0 · Nguồn: N5 · Module: web`
- **Mô tả:** Tổng quan từng treasury:
  - số dư từng ví so với buffer và mục tiêu;
  - ngân sách hôm nay đã dùng so với hạn mức;
  - mức bao phủ;
  - trạng thái mandate (Active/Paused);
  - số lượng trong các hàng đợi (chờ duyệt, đã lên lịch, cần xem xét);
  - runway (F-058);
  - hoạt động gần đây.
- **Vấn đề giải quyết:** Nhìn một lần là biết tình trạng quỹ.
- **Người dùng:** Mọi vai trò.
- **Kích hoạt:** Mở app.
- **Đầu vào:** Dữ liệu từ API.
- **Logic:** Hiển thị số tiền quy đổi từ đơn vị nhỏ nhất. Tài sản test có nhãn. Giá trị chưa chắc chắn được đánh dấu.
- **Đầu ra:** Dashboard.
- **Luồng chính:** —
- **Luồng thay thế:** Chưa có dữ liệu → hiện checklist onboarding.
- **Tình huống biên:** Dữ liệu cũ → hiện banner cảnh báo.
- **Phân quyền:** Giao diện theo vai trò.
- **Vai trò AI:** Không có (có thể hiện lối vào Copilot).
- **Vai trò con người:** —
- **Nghiệm thu:** Dùng tốt ở độ rộng 1280 px và 390 px. Mọi giá trị khớp API.

#### F-131 · Hộp duyệt có so sánh & cờ
`M1 · P0 · Nguồn: N5, N1 · Module: web`
- **Mô tả:** Danh sách yêu cầu chờ duyệt. Màn hình chi tiết hiển thị:
  - tài liệu bên cạnh các trường đã trích;
  - so sánh với lịch sử nhà cung cấp;
  - các cờ kèm bằng chứng;
  - điều khoản đã xác nhận;
  - nút "Ký duyệt" (ví ký EIP-712).
- **Vấn đề giải quyết:** Duyệt nhanh mà có đủ thông tin (P3).
- **Người dùng:** Approver.
- **Kích hoạt:** Có yêu cầu ở AwaitingApproval.
- **Đầu vào:** Yêu cầu chi và các cờ.
- **Logic:** Cờ mức cao phải tick xác nhận đã đọc trước khi ký. Áp dụng maker-checker.
- **Đầu ra:** Bản duyệt đã ký, hoặc lệnh từ chối.
- **Luồng chính:** Mở → xem → ký.
- **Luồng thay thế:** Từ chối kèm lý do.
- **Tình huống biên:** Ví đang ở sai chain → nhắc chuyển chain. Người dùng từ chối ký trong ví → không có gì thay đổi.
- **Phân quyền:** Approver.
- **Vai trò AI:** Đề xuất (các cờ).
- **Vai trò con người:** Quyết định.
- **Nghiệm thu:** Không ký được khi còn cờ mức cao chưa xác nhận. Dữ liệu hiển thị đúng bằng dữ liệu được ký.

#### F-132 · Thẻ kế hoạch & timeline thực thi trực tiếp
`M1 · P0 · Nguồn: N5 · Module: web`
- **Mô tả:** Với mỗi chu kỳ lập kế hoạch:
  - **Thẻ kế hoạch:** thứ tự, số tiền, các lần refill, tiết kiệm dự kiến, nguồn lập kế hoạch (AI hay RULE).
  - **Ô "Vì sao?":** mã lý do từ validator và lời giải thích của AI, tách bạch rõ ràng.
  - **Timeline trực tiếp cho từng bước:** đã gửi → pending → đã xác nhận, kèm link explorer và kết quả xác minh.
- **Vấn đề giải quyết:** Khả năng giải thích; phản hồi theo thời gian thực.
- **Người dùng:** Tất cả.
- **Kích hoạt:** Sự kiện lập kế hoạch hoặc thực thi (đẩy qua SSE/WebSocket).
- **Đầu vào:** Sự kiện của kế hoạch và các thao tác.
- **Logic:** Lý do từ validator là căn cứ chính thức. Văn bản AI được ghi nhãn "Giải thích của AI".
- **Đầu ra:** Giao diện.
- **Luồng chính:** Xem khoản trả diễn ra trực tiếp.
- **Luồng thay thế:** —
- **Tình huống biên:** Trạng thái Unknown → hiện rõ "đang kiểm tra chain…".
- **Phân quyền:** Mọi vai trò được đọc.
- **Vai trò AI:** Đề xuất (lời giải thích).
- **Vai trò con người:** —
- **Nghiệm thu:** Sự kiện hiện trên UI trong vòng 2 giây sau khi backend đổi trạng thái. Link explorer đúng theo từng chain.

#### F-133 · Màn hình đối soát
`M1 · P0 · Nguồn: UC-03 · Module: web`
- **Mô tả:** Bảng yêu cầu chi ↔ giao dịch ↔ phí ↔ phân loại ↔ trạng thái đối soát. Có bộ lọc, nút "Đánh dấu khớp", ghi chú chênh lệch và chức năng xuất (F-073).
- **Vấn đề giải quyết:** P5.
- **Người dùng:** Finance, Auditor.
- **Kích hoạt:** Mở màn hình.
- **Đầu vào:** Bản ghi đối soát.
- **Logic:** —
- **Đầu ra:** Giao diện và hành động.
- **Luồng chính:** Lọc "đã trả, chưa khớp" → kiểm tra → đánh dấu.
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** Finance đánh dấu; Auditor chỉ đọc.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Đánh dấu khớp.
- **Nghiệm thu:** Tổng theo kỳ bằng tổng trong file xuất.

#### F-134 · Giao diện quản lý mandate & payee
`M1 · P0 · Nguồn: UC-01 · Module: web`
- **Mô tả:**
  - Form mandate, có bản tóm tắt dễ đọc và so sánh với phiên bản đang Active.
  - Danh bạ payee: trạng thái, đếm ngược thời gian chờ, kết quả sàng lọc.
  - Các luồng để Owner ký.
- **Vấn đề giải quyết:** Người không phải lập trình viên vẫn cấu hình an toàn được.
- **Người dùng:** Owner; người khác chỉ đọc.
- **Kích hoạt:** Mở màn hình.
- **Đầu vào:** —
- **Logic:** Theo F-020, F-021, F-022.
- **Đầu ra:** Giao dịch đã ký.
- **Luồng chính:** Sửa → xem so sánh → ký.
- **Luồng thay thế:** —
- **Tình huống biên:** Đang chờ kích hoạt → hiển thị rõ.
- **Phân quyền:** Owner ghi.
- **Vai trò AI:** Không có.
- **Vai trò con người:** Quyết định.
- **Nghiệm thu:** Bản so sánh hiện mọi trường thay đổi, cả ở đơn vị nhỏ nhất lẫn đơn vị hiển thị.

#### F-135 · Bảng điều khiển ngoại lệ & xem xét
`M1 · P0 · Nguồn: UC-04, UC-06 · Module: web`
- **Mô tả:** Giao diện cho các mục F-082 và yêu cầu ngoại lệ F-025. Hiển thị mã lý do, các bước đã xong, lý do do AI soạn, và hành động theo vai trò: cấp ngoại lệ, thử lại, hủy, sửa rồi duyệt lại.
- **Vấn đề giải quyết:** Con người xử lý ngoại lệ nhanh và đúng.
- **Người dùng:** Owner, Operator, Finance.
- **Kích hoạt:** Có mục đang mở.
- **Đầu vào:** Các mục trong hàng đợi.
- **Logic:** Mỗi hành động gọi API tương ứng. Không có hành động nào ngầm nới chính sách.
- **Đầu ra:** Các mục đã xử lý.
- **Luồng chính:** Vượt trần → Owner ký ngoại lệ → mục đóng sau khi thực thi.
- **Luồng thay thế:** —
- **Tình huống biên:** Mục đã cũ (trạng thái đổi) → phải tải lại trước khi hành động.
- **Phân quyền:** Theo loại mục.
- **Vai trò AI:** Đề xuất.
- **Vai trò con người:** Xử lý.
- **Nghiệm thu:** Mỗi loại mục có hành động được nối và test end-to-end.

### 3.14 Phân tích & Giám sát

#### F-140 · Chỉ số vận hành
`M1 · P1 · Nguồn: T6, AT §6 · Module: analytics`
- **Mô tả:** Các chỉ số:
  - tỷ lệ hoàn thành các yêu cầu hợp lệ;
  - phần trăm trả trước deadline;
  - số lần con người can thiệp mỗi yêu cầu;
  - số phút thao tác (tự khai hoặc ước tính);
  - phí và số giao dịch;
  - thời gian từ trigger đến Paid, tách theo phân tích / hàng đợi / chain / xác minh;
  - số yêu cầu bị từ chối, theo lý do.
- **Vấn đề giải quyết:** Đo được giá trị; báo cáo trung thực.
- **Người dùng:** Owner, Finance, team.
- **Kích hoạt:** Liên tục, kèm trang báo cáo.
- **Đầu vào:** Kho sự kiện.
- **Logic:** Yêu cầu bị chặn hoặc từ chối vẫn được báo, không bị giấu.
- **Đầu ra:** Dashboard và CSV.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** Owner, Finance, Auditor.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Định nghĩa chỉ số có tài liệu; tính lại được từ sự kiện gốc.

#### F-141 · Báo cáo tiết kiệm
`M1 · P1 · Nguồn: N3 · Module: analytics`
- **Mô tả:** Chiết khấu nhận được và phí phạt tránh được, so với kịch bản đối chứng B1, cho các đợt chi đã thực hiện. Kèm kết quả benchmark.
- **Vấn đề giải quyết:** Thể hiện giá trị của AI bằng tiền.
- **Người dùng:** Owner, Finance, giám khảo.
- **Kích hoạt:** Sau mỗi đợt chi; có trang báo cáo.
- **Đầu vào:** Lịch đã thực hiện, điều khoản, mô phỏng B1.
- **Logic:** Kịch bản đối chứng dùng cùng ràng buộc. Hiển thị phương pháp tính.
- **Đầu ra:** Báo cáo.
- **Luồng chính:** "Tháng này: +X USDC so với baseline."
- **Luồng thay thế:** —
- **Tình huống biên:** Tiết kiệm âm → vẫn hiển thị trung thực.
- **Phân quyền:** Owner, Finance.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Tính lại được từ dữ liệu đã lưu.

#### F-142 · Giám sát hệ thống
`M1 · P1 · Nguồn: NEW · Module: platform`
- **Mô tả:**
  - Log có cấu trúc, gắn ID liên kết (yêu cầu / kế hoạch / thao tác).
  - Metric: độ sâu hàng đợi, lỗi RPC, độ trễ và chi phí LLM, trạng thái giao dịch.
  - Trace xuyên suốt API → worker → signer → chain.
  - Theo dõi lỗi và cảnh báo.
- **Vấn đề giải quyết:** Vận hành và gỡ lỗi.
- **Người dùng:** Team, PlatformAdmin.
- **Kích hoạt:** Luôn luôn.
- **Đầu vào:** —
- **Logic:** Log được che dữ liệu nhạy cảm (F-113).
- **Đầu ra:** Dashboard và cảnh báo.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** Team.
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Truy được một yêu cầu end-to-end bằng ID của nó.

### 3.15 Quản trị & Nền tảng

#### F-150 · Quản trị nền tảng: quản lý tenant
`Later · Nguồn: Q13 · Module: admin`
- **Mô tả:** Bảng điều khiển cho PlatformAdmin: liệt kê và tạm khóa tenant, xem tình trạng hoạt động. Hỗ trợ khách bằng chế độ chỉ đọc, có sự đồng ý của khách và có audit.
- **Vấn đề giải quyết:** Vận hành SaaS nhiều tổ chức.
- **Người dùng:** PlatformAdmin.
- **Kích hoạt:** —
- **Đầu vào:** —
- **Logic:** PlatformAdmin không bao giờ ký được hay chuyển được tiền của khách (không có khóa).
- **Đầu ra:** —
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** PlatformAdmin.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Mọi thao tác của admin được audit. Không tồn tại khả năng chuyển tiền.

#### F-151 · Cấu hình nền tảng (chain, RPC, tài sản)
`M1 · P1 · Nguồn: O5 · Module: admin / platform`
- **Mô tả:** Cấu hình:
  - các chain hỗ trợ: chainId, RPC kèm RPC dự phòng, độ sâu xác nhận, URL explorer;
  - địa chỉ contract đã triển khai trên từng chain;
  - danh mục tài sản chung;
  - cờ test hay production.
- **Vấn đề giải quyết:** Loại bỏ giá trị mạng viết cứng trong code.
- **Người dùng:** PlatformAdmin. M1 dùng file cấu hình và script seed.
- **Kích hoạt:** Khi triển khai.
- **Đầu vào:** Cấu hình.
- **Logic:** Kiểm tra khi khởi động. Manifest triển khai được commit vào repo.
- **Đầu ra:** Cấu hình.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** Sai chainId → không khởi động.
- **Phân quyền:** PlatformAdmin.
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Cấu hình sai thì dừng ngay khi khởi động.

#### F-152 · Billing & gói thuê bao
`Later · Nguồn: Q22 · Module: admin`
- **Mô tả:** Gói dịch vụ, đo lượng sử dụng (số yêu cầu đã trả, khối lượng tiền), xuất hóa đơn cho khách, thu tiền.
- **Vấn đề giải quyết:** Thương mại hóa.
- **Người dùng:** OrgAdmin, PlatformAdmin.
- **Kích hoạt:** Chu kỳ thanh toán.
- **Đầu vào:** Lượng sử dụng.
- **Logic:** Đo từ kho sự kiện. Không bao giờ tự trừ phí từ treasury của khách.
- **Đầu ra:** Hóa đơn gửi khách.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** Không có.
- **Vai trò con người:** —
- **Nghiệm thu:** Số liệu sử dụng khớp với kho sự kiện.

### 3.16 Bàn giao & Chất lượng

#### F-160 · Môi trường local một lệnh & kịch bản mẫu
`M1 · P1 · Nguồn: T7 · Module: devex`
- **Mô tả:** Một lệnh `docker compose up` (hoặc `make dev`) dựng toàn bộ hệ thống:
  - DB, API, worker, web;
  - chain Anvil có contract và Safe đã triển khai sẵn;
  - dữ liệu mẫu: tổ chức, payee, hóa đơn.
- **Vấn đề giải quyết:** Giám khảo và dev tái lập được.
- **Người dùng:** Dev, giám khảo.
- **Kích hoạt:** —
- **Đầu vào:** —
- **Logic:** —
- **Đầu ra:** Hệ thống chạy được.
- **Luồng chính:** Chạy một lệnh → UI mở ở localhost.
- **Luồng thay thế:** Profile testnet.
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Clone mới và làm theo README → có demo chạy trong tối đa 15 phút.

#### F-161 · Pipeline CI
`M1 · P1 · Nguồn: T7 · Module: devex`
- **Mô tả:** Trên mỗi PR chạy lần lượt:
  - lint, typecheck;
  - unit test;
  - test Foundry (có fuzz và invariant);
  - phân tích tĩnh;
  - integration test trên Anvil;
  - build.
- **Vấn đề giải quyết:** Cổng chất lượng.
- **Người dùng:** Dev.
- **Kích hoạt:** PR hoặc push.
- **Đầu vào:** —
- **Logic:** `main` bắt buộc các check này.
- **Đầu ra:** Trạng thái check.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Branch protection yêu cầu CI xanh.

#### F-162 · Scenario runner & kịch bản demo
`M1 · P1 · Nguồn: GA p.14, p.41 · Module: devex`
- **Mô tả:** CLI reset môi trường rồi chạy kịch bản có tên: luồng chuẩn, vượt trần, hóa đơn có lệnh chèn, phục hồi sau sập, tạm dừng. Mỗi lần chạy xuất gói bằng chứng. Kèm runbook demo từng bước.
- **Vấn đề giải quyết:** Demo ổn định và có bằng chứng.
- **Người dùng:** Team.
- **Kích hoạt:** Chạy tay.
- **Đầu vào:** Tên kịch bản.
- **Logic:** Chỉ chạy trên chain test nằm trong allowlist.
- **Đầu ra:** Log và gói bằng chứng.
- **Luồng chính:** `scenario run demo-main` → gói bằng chứng.
- **Luồng thay thế:** —
- **Tình huống biên:** chainId mainnet → từ chối.
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Mỗi cảnh trong runbook ứng với một kịch bản.

#### F-163 · Bộ test bảo mật
`M1 · P0 · Nguồn: S1, S5 · Module: quality`
- **Mô tả:**
  - Unit, fuzz và invariant test bằng Foundry, ít nhất 8 invariant: BR-001, BR-013, BR-022, BR-024, BR-030, BR-041, BR-062 và chống replay.
  - Báo cáo phân tích tĩnh.
  - Test cố vượt quyền bằng cách gọi thẳng module.
  - Bộ red-team prompt injection.
- **Vấn đề giải quyết:** Bằng chứng cho tiêu chí Security.
- **Người dùng:** Team.
- **Kích hoạt:** CI.
- **Đầu vào:** —
- **Logic:** —
- **Đầu ra:** Báo cáo.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** Đối tượng bị kiểm tra trong red-team.
- **Vai trò con người:** —
- **Nghiệm thu:** Mọi invariant giữ đúng qua 10.000 lượt fuzz. Không còn phát hiện mức cao nào chưa xử lý hoặc chưa ghi nhận.

#### F-164 · Bộ chạy kiểm tra độ ổn định
`M1 · P1 · Nguồn: T6 · Module: quality`
- **Mô tả:** Chạy kịch bản chính 30 lần trên Anvil và ít nhất 10 lần trên testnet. Báo tỷ lệ hoàn thành, độ trễ trung vị, phí và các lỗi.
- **Vấn đề giải quyết:** Bằng chứng cho phần "ổn định, lặp lại được" của Task Completion.
- **Người dùng:** Team.
- **Kích hoạt:** Chạy tay hoặc hằng đêm.
- **Đầu vào:** —
- **Logic:** Lỗi được phân loại, không bị bỏ qua.
- **Đầu ra:** Báo cáo.
- **Luồng chính:** —
- **Luồng thay thế:** —
- **Tình huống biên:** —
- **Phân quyền:** —
- **Vai trò AI:** —
- **Vai trò con người:** —
- **Nghiệm thu:** Báo cáo được commit vào `docs/evidence/`.
