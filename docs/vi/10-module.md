# TreasuryPilot: Các module

**Nguồn chuẩn:** `docs/modules/` (mỗi module một file README có đủ 10 mục) · **Trạng thái:** Đã qua cổng G2

Hệ thống chia thành 20 module. Cả 99 feature đều thuộc ít nhất một module.

| ID | Module | Chạy ở đâu | Trách nhiệm | Feature |
|---|---|---|---|---|
| M01 | Định danh & phân quyền (`identity`) | api | Tài khoản, phiên, SIWE, tổ chức, thành viên, 8 vai trò, maker-checker | F-001–F-007 |
| M02 | Treasury & cấu hình chain (`treasury`) | api, worker | Treasury, Safe, mức bao phủ module, danh mục tài sản, cấu hình chain | F-010–F-015, F-151 |
| M03 | Mandate, payee, ngoại lệ, tạm dừng (`mandate`) | api, worker | Bản nháp và phiên bản mandate, payee (sàng lọc + thời gian chờ), ngoại lệ, tạm dừng/chạy lại (phía off-chain) | F-020–F-029 |
| M04 | Smart contract (`contracts`) | on-chain | `TreasuryPilotModule`, token test, router test, script triển khai | Phần on-chain của F-012, F-021–F-026, F-037, F-038, F-062–F-064, F-074 |
| M05 | Hóa đơn & yêu cầu chi (`invoices`) | api | Nhận hóa đơn, phiên bản, fingerprint, cờ, duyệt, máy trạng thái | F-030–F-041 |
| M06 | Đọc chain & theo dõi giao dịch (`chain-reader`) | worker | Snapshot, theo dõi receipt, xử lý reorg, đọc event, RPC dự phòng | F-050, F-070 |
| M07 | Financial engine (`financial-engine`) | py-core | Công thức thanh khoản, bộ lập lịch theo điều khoản, dự báo | F-051, F-052, F-058, F-059 |
| M08 | Policy engine & attestation (`policy-engine`) | py-core, worker | Kiểm tra ALLOW / NEEDS_APPROVAL / BLOCK, ký attestation | F-055, F-056 |
| M09 | AI agent (`agent`) | worker-ai, api | Adapter LLM, trích xuất, điều khoản, bất thường, đề xuất kế hoạch, soạn ngoại lệ, Copilot, bộ đánh giá | F-031, F-035, F-036, F-053, F-054, F-057, F-090–F-094 |
| M10 | Điều phối & thực thi (`execution`) | worker, signer | Trigger, executor tuần tự, outbox, signer, gas, swap | F-060–F-067 |
| M11 | Xác minh & đối soát (`reconciliation`) | worker, api | Hậu điều kiện, đối soát, xuất file, attestation | F-071–F-075 |
| M12 | Phục hồi & ngoại lệ (`recovery`) | worker | Phục hồi Unknown, hoàn thành một phần, hàng đợi xem xét, retry, circuit breaker | F-027, F-080–F-083 |
| M13 | Thông báo (`notifications`) | worker, api | Trong app, Telegram (email/webhook để sau) | F-100–F-105 |
| M14 | Tuân thủ (`compliance`) | worker, api | Adapter sàng lọc, phân loại dữ liệu (KYB/Travel Rule để sau) | F-110–F-114 |
| M15 | Audit & bằng chứng (`audit`) | mọi nơi | Nhật ký audit nối hash, gói bằng chứng, nhãn mức bao phủ | F-120–F-122 |
| M16 | Web (`web`) | trình duyệt | Toàn bộ giao diện | F-130–F-135 |
| M17 | Giám sát & phân tích (`observability`) | mọi nơi | Log, metric, trace, chỉ số vận hành, báo cáo tiết kiệm | F-140–F-142 |
| M18 | Quản trị nền tảng & billing (`admin`) | api | Cấu hình nền tảng (M1); quản trị tenant, billing (sau) | F-150–F-152 |
| M19 | DevEx & chất lượng (`devex`) | repo/CI | Compose, CI, scenario runner, bộ test bảo mật, kiểm tra độ ổn định | F-160–F-164 |
| M20 | Domain & bằng chứng (`domain-evidence`) | con người | Việc của 3 cố vấn: bộ dữ liệu, kịch bản, rà soát, phỏng vấn, deck, video, tài liệu nộp | Hỗ trợ F-092, F-162, F-163 |

## Mỗi file module gồm những gì

Mục đích · Feature · Đầu vào · Đầu ra · API · Mô hình dữ liệu · Phụ thuộc · Lưu ý bảo mật · Kịch bản lỗi · Câu hỏi mở.

## Các bất biến của contract (module M04)

Bộ test invariant phải chứng minh 9 điều sau:

1. Không có PAY nào thiếu chữ ký approver hợp lệ trên đúng các trường.
2. Chỉ PAY cho payee đang hoạt động và đã hết thời gian chờ.
3. Tổng PAY thành công theo (tài sản, ngày UTC) không vượt trần ngày.
4. Không giao dịch nào qua đường agent làm ví xuống dưới buffer.
5. Mỗi requestId, fingerprint và stepId chỉ thực thi tối đa một lần.
6. Ngoại lệ chỉ nâng trần mỗi khoản và chỉ dùng một lần.
7. Khi tạm dừng hoặc đã thu hồi, mọi lời gọi của executor đều revert.
8. Đổi phiên bản không bao giờ reset bộ đếm.
9. Chỉ Safe T thay đổi quản trị; Guardian chỉ được tạm dừng.
