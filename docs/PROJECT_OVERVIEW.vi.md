# TreasuryPilot: Tổng quan dự án (bản tóm tắt tiếng Việt)

Bản đầy đủ và là nguồn chuẩn nằm ở `PROJECT_OVERVIEW.md` (tiếng Anh).

## 1. Sản phẩm là gì?

TreasuryPilot là **AI điều phối quỹ vận hành** cho doanh nghiệp thanh toán bằng stablecoin. Sản phẩm gồm ứng dụng web và một **lớp hợp đồng thông minh** để thực thi luật.

Doanh nghiệp làm ba việc:
- Kết nối các ví của công ty: ví quỹ `T` và các ví chi `O1`, `O2`.
- Đặt quy tắc chi một lần (gọi là **mandate**).
- Duyệt hóa đơn.

Agent làm phần còn lại:
- Đọc hóa đơn, kể cả PDF lộn xộn, và trích **điều khoản thanh toán**.
- Quyết định nên trả khi nào.
- Nạp tiền từ ví quỹ sang ví chi.
- Trả nhà cung cấp on-chain.
- Đối soát từng khoản.

Câu chốt: **Con người quyết định *có* trả hay không. Agent quyết định trả *thế nào và khi nào*. Hợp đồng đảm bảo agent không làm được gì khác.**

## 2. Vấn đề (người dùng → tình huống → vấn đề → hậu quả)

| | Người dùng | Tình huống | Vấn đề | Hậu quả |
|---|---|---|---|---|
| P1 | Operator | Hóa đơn đã duyệt đến hạn; ví chi thiếu tiền hoặc gas, trong khi ví quỹ còn nhiều | Phải tự kiểm tra, tính, chuyển, chờ ký rồi trả | Trả trễ, tốn giờ công, dễ sai |
| P2 | Founder | Muốn tự động hóa | Công cụ ủy quyền hiện có không giới hạn được *người nhận*; prompt không phải là cơ chế kiểm soát | Hoặc vẫn phải ký từng bước, hoặc giao quyền quá rộng |
| P3 | Người duyệt | Hóa đơn PDF hoặc email có thể bị sửa địa chỉ ví, bị chèn lệnh, hoặc bị trùng | Khó phát hiện | Chuyển nhầm tiền và không đảo ngược được (lừa đảo đổi tài khoản nhà cung cấp, BEC) |
| P4 | Finance lead | Nhiều hóa đơn tranh nhau một nguồn tiền; có hóa đơn được chiết khấu "2/10 net 30", có hóa đơn bị phạt trễ hạn | Luật "trả cái đến hạn sớm trước" bỏ sót tiền | Mất chiết khấu, bị phạt |
| P5 | Kế toán | Mỗi khoản chi gồm nhiều giao dịch | Đối soát thủ công | Chốt sổ chậm, thiếu bằng chứng |

## 3. Ai dùng?

- **Người dùng chính:** Operator, Owner (founder), Approver (finance lead).
- **Người dùng phụ:** Kế toán, Auditor, Guardian (chỉ có quyền pause), OrgAdmin.
- **Sau này:** PlatformAdmin, các tích hợp ERP, KYB/KYT.

## 4. Các hành trình chính

| # | Hành trình |
|---|---|
| J1 | Onboarding và mandate |
| J2 | Thêm payee, có thời gian chờ trước khi được trả |
| J3 | Nhập hóa đơn → AI trích xuất và gắn cờ → người duyệt ký EIP-712 |
| J4 | Agent tự lập kế hoạch → kiểm tra → ký xác nhận kế hoạch → refill → pay → xác minh → đối soát |
| J5 | Ngoại lệ vượt trần |
| J6 | Phục hồi, không trả trùng |
| J7 | Dừng khẩn cấp |
| J8 | Đối soát và audit |
| J9 | Copilot trả lời câu hỏi "nếu… thì sao" |
| J10 | Thông báo |

## 5. Phạm vi

- **99 feature**: 76 thuộc M1 (bản thi), 23 để `Later`. Xem `FEATURES.md`.
- **Non-goals** (không bao giờ làm): đầu cơ, lợi suất, cho vay, quản lý danh mục, giữ tiền của khách, trả hóa đơn chưa duyệt, tự mua dịch vụ, đảo ngược giao dịch.

## 6. Tài liệu đi kèm (cổng G1)

| File | Nội dung |
|---|---|
| `FEATURES.md` | Inventory và đặc tả đầy đủ 99 feature |
| `FUNCTIONAL_REQUIREMENTS.md` | 160 FR, truy ngược về F và BR |
| `NON_FUNCTIONAL_REQUIREMENTS.md` | 49 NFR: bảo mật, hiệu năng, độ tin cậy, quyền riêng tư, audit, UX, khả năng bảo trì |
| `BUSINESS_RULES.md` | 67 BR, ghi rõ nơi enforce (Contract / Backend / UI) |
| `OPEN_QUESTIONS.md` | 18 câu hỏi mở, mỗi câu có khuyến nghị |
| `decisions-log.md` | Các quyết định Q1–Q22 |
