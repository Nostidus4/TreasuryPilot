# TreasuryPilot: Yêu cầu phi chức năng (NFR)

**Nguồn chuẩn:** `docs/NON_FUNCTIONAL_REQUIREMENTS.md` · **Trạng thái:** Đã qua cổng G1

Mục tiêu mặc định áp cho **M1** (bản thi, testnet). Cột **Prod** là mục tiêu cho sản phẩm đầy đủ.

## Bảo mật

| ID | Yêu cầu | M1 | Prod | Cách kiểm chứng |
|---|---|---|---|---|
| NFR-SEC-01 | Mọi luật tài chính đánh dấu "C" được thực thi on-chain, không vượt qua được bằng cách gọi backend hay gọi thẳng contract | 100% luật C có test gọi trực tiếp | Thêm audit bên ngoài | Test vượt quyền bằng Foundry |
| NFR-SEC-02 | Invariant của contract giữ đúng khi fuzz | Ít nhất 8 invariant, 10.000 lượt | 100.000 lượt và kiểm chứng hình thức cho phần lõi | `forge test` |
| NFR-SEC-03 | Cách ly khóa: khóa owner không chạm hệ thống; khóa executor chỉ nằm trong signer service; LLM và API không có khóa | Tiến trình và biến môi trường riêng | Signer dùng KMS/HSM | Rà kiến trúc, quét bí mật |
| NFR-SEC-04 | Không có bí mật trong repo hoặc log | gitleaks trong CI | Như M1 | CI |
| NFR-SEC-05 | Web và API đạt OWASP ASVS L1 (xác thực, phiên, kiểm tra đầu vào, kiểm soát truy cập) | Các kiểm soát chính | ASVS L2 | Checklist và test |
| NFR-SEC-06 | Chống prompt injection | 0/20 ca red-team đổi được trường hoặc chính sách | 0/100 | Bộ red-team |
| NFR-SEC-07 | Phân tích tĩnh contract | Không còn phát hiện mức cao chưa xử lý | Như M1, cộng audit | Báo cáo trong `docs/security/` |
| NFR-SEC-08 | Khóa cứng phiên bản phụ thuộc (lockfile, phiên bản Safe và Solidity chính xác) và quét lỗ hổng | Khóa phiên bản + `npm audit` | Thêm công cụ SCA | CI |
| NFR-SEC-09 | Giới hạn tần suất và giới hạn job (tool call, số hành động mỗi kế hoạch, số lần quét, số lần thử lại) | Có cấu hình giới hạn | Như M1 | Test |

## Hiệu năng

| ID | Yêu cầu | M1 | Prod |
|---|---|---|---|
| NFR-PERF-01 | Độ trễ p95 của API đọc | < 300 ms | < 200 ms |
| NFR-PERF-02 | Một chu kỳ lập kế hoạch với tối đa 12 yêu cầu, không tính thời gian xác nhận chain | < 15 giây, đã gồm LLM | < 10 giây |
| NFR-PERF-03 | Trích xuất một hóa đơn | < 20 giây | < 10 giây |
| NFR-PERF-04 | UI cập nhật timeline sau khi backend đổi trạng thái | < 2 giây | < 1 giây |
| NFR-PERF-05 | Nhập CSV | 500 dòng < 10 giây | 5.000 dòng < 10 giây |

Báo cáo độ trễ phải tách riêng thời gian phân tích, hàng đợi, xác nhận chain và xác minh.

## Tính sẵn sàng & độ tin cậy

| ID | Yêu cầu | M1 | Prod |
|---|---|---|---|
| NFR-REL-01 | Tỷ lệ hoàn thành kịch bản chính trên các yêu cầu hợp lệ, được hỗ trợ | ≥ 95% qua 30 lần chạy local + 10 lần testnet | ≥ 99,5% |
| NFR-REL-02 | Số lần trả trùng | 0 trong mọi bộ test, kể cả test sập | 0 |
| NFR-REL-03 | Worker khởi động lại ở bất kỳ thời điểm nào mà không mất hay nhân đôi thao tác | Có outbox và phục hồi | Như M1 |
| NFR-REL-04 | Số nhà cung cấp RPC, có chuyển đổi dự phòng | 2 | 3, kèm chấm điểm sức khỏe |
| NFR-REL-05 | Khi LLM sập: dùng fallback xác định hoặc luồng thủ công, không treo vô hạn | Timeout ≤ 20 giây | Chuyển nhà cung cấp |
| NFR-REL-06 | Tính sẵn sàng dịch vụ | Cố gắng tốt nhất (demo) | API 99,9%/tháng; worker 99,5% |
| NFR-REL-07 | Sao lưu và khôi phục DB | Snapshot hằng ngày | PITR, RPO ≤ 5 phút, RTO ≤ 1 giờ |

## Khả năng mở rộng

| ID | Yêu cầu | M1 | Prod |
|---|---|---|---|
| NFR-SCAL-01 | Số tổ chức | 1–5 | Hơn 1.000 |
| NFR-SCAL-02 | Số yêu cầu mỗi treasury mỗi ngày | 50 | 5.000 |
| NFR-SCAL-03 | Mở rộng ngang: API không trạng thái; worker chia theo treasury mà vẫn giữ tuần tự trong từng treasury | Thiết kế hỗ trợ | Đã cài đặt |

## Quyền riêng tư

| ID | Yêu cầu | Mục tiêu |
|---|---|---|
| NFR-PRIV-01 | Không có dữ liệu cá nhân hay nội dung hóa đơn trên chain, chỉ hash | 100% (rà event và calldata) |
| NFR-PRIV-02 | Dữ liệu mật (tệp hóa đơn, liên hệ nhà cung cấp) được mã hóa khi lưu; kho riêng tư, truy cập qua URL có chữ ký | M1: bucket riêng tư + DB mã hóa khi lưu |
| NFR-PRIV-03 | Gửi LLM nội dung tối thiểu; bật chế độ không lưu dữ liệu nếu nhà cung cấp hỗ trợ | Có tài liệu theo từng tác vụ |
| NFR-PRIV-04 | Log che email, nội dung tài liệu, và địa chỉ (tùy chọn) | Có test che dữ liệu |
| NFR-PRIV-05 | Cô lập tenant được test ở mọi endpoint | Test tự động truy cập chéo |

## Khả năng audit & log

| ID | Yêu cầu | Mục tiêu |
|---|---|---|
| NFR-AUD-01 | Mọi thao tác ảnh hưởng tiền hoặc quyền đều được audit; ghi audit lỗi thì thao tác thất bại an toàn | 100% |
| NFR-AUD-02 | Nhật ký audit nối hash, kiểm tra được bằng script | Script có trong repo |
| NFR-AUD-03 | Mọi kế hoạch truy được về nguồn lập kế hoạch, phiên bản model, phiên bản prompt, quyết định validator và tx hash | 100% |
| NFR-AUD-04 | Log JSON có cấu trúc, có ID liên kết (`requestId`, `planId`, `operationId`, `traceId`) | Mọi service |
| NFR-AUD-05 | Thời gian lưu bằng chứng | M1: không giới hạn; Prod: ít nhất 7 năm (cấu hình theo luật) |

## Khả năng tiếp cận & dễ dùng

| ID | Yêu cầu | Mục tiêu |
|---|---|---|
| NFR-UX-01 | Luồng chính (duyệt, ngoại lệ, dashboard) đạt WCAG 2.1 AA | Qua kiểm tra axe |
| NFR-UX-02 | Responsive tới 390 px cho duyệt và thông báo | Kiểm tra thủ công |
| NFR-UX-03 | Số tiền luôn đi kèm ký hiệu tài sản và mạng; tài sản test có nhãn | Rà UI |
| NFR-UX-04 | Từ ngữ trạng thái chính xác; không ghi "an toàn" hay "xong" khi chưa xác minh | Checklist từ ngữ |
| NFR-UX-05 | M1 dùng tiếng Anh; sẵn sàng đa ngôn ngữ (tiếng Việt, tiếng Trung sau) | Chuỗi được tách khỏi code |

## Khả năng bảo trì

| ID | Yêu cầu | Mục tiêu |
|---|---|---|
| NFR-MAINT-01 | Ranh giới module đúng như `docs/modules/`; không truy cập DB chéo module | Lint rule hoặc review |
| NFR-MAINT-02 | Kiểu domain dùng chung, an toàn kiểu, giữa web, API, worker | Có package dùng chung |
| NFR-MAINT-03 | Độ phủ test của gói lõi (financial engine, policy, contracts) | ≥ 85% dòng (M1), ≥ 90% (Prod) |
| NFR-MAINT-04 | Mọi quyết định kiến trúc quan trọng có ADR | Thư mục `docs/adr/` |
| NFR-MAINT-05 | Build và môi trường tái lập được (khóa phiên bản, manifest triển khai) | Lockfile + manifest |
| NFR-MAINT-06 | Tài liệu cập nhật trong cùng PR với thay đổi hành vi | Ô kiểm trong mẫu PR |

## Tuân thủ & pháp lý

| ID | Yêu cầu | Mục tiêu |
|---|---|---|
| NFR-CMP-01 | M1 chỉ chạy trên mạng test với tài sản test, có ghi nhãn | Allowlist của scenario runner |
| NFR-CMP-02 | Định vị thị trường loại trừ việc dùng stablecoin của cá nhân và doanh nghiệp tại Trung Quốc đại lục | Ghi rõ trong tài liệu và deck |
| NFR-CMP-03 | Code, dữ liệu, model bên thứ ba có giấy phép phù hợp (quy định IP của cuộc thi) | Danh mục giấy phép trong repo |
| NFR-CMP-04 | Có adapter cho KYB, KYT, Travel Rule để thay nhà cung cấp | Giao diện được định nghĩa ở M1 |
