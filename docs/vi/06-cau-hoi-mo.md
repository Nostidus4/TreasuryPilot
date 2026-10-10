# TreasuryPilot: Câu hỏi mở

**Nguồn chuẩn:** `docs/OPEN_QUESTIONS.md`

Mỗi câu hỏi có khuyến nghị của BA. Khuyến nghị được dùng làm **giả định làm việc** cho đến khi team trả lời. O1–O8 của tài liệu gốc đã đóng theo quyết định Q8 và đã thành giá trị mặc định trong các BR.

| ID | Câu hỏi | Vì sao quan trọng | Ảnh hưởng | Phương án | Khuyến nghị BA |
|---|---|---|---|---|---|
| OQ-01 | Cuộc thi có chấp nhận tx hash trên **testnet** làm bằng chứng thực thi cho Topic F không? | Quyết định dùng testnet hay mainnet với stablecoin thật, kéo theo rủi ro pháp lý và tuân thủ | NFR-CMP-01, F-151, mọi bằng chứng | (a) chấp nhận testnet; (b) bắt buộc mainnet | **Email ban tổ chức ngay.** Lên kế hoạch theo (a); dự phòng mainnet giá trị nhỏ trên chain phí thấp |
| OQ-02 | Chain nào cho M1? *(Phase 3)* | Ảnh hưởng: có Safe không, có faucet USDC test không, có EAS không, RPC, explorer | F-010, F-013, F-074, F-151 | Base Sepolia; Ethereum Sepolia; Arbitrum Sepolia | **Base Sepolia**, chờ kiểm chứng ở Phase 3 |
| OQ-03 | Stablecoin cho M1: USDC testnet của Circle hay `tUSDC` tự triển khai? | Đánh đổi giữa tính thực tế và quyền kiểm soát nguồn cung | F-013, demo | (a) USDC Circle; (b) tUSDC | (a) nếu faucet đủ cho hơn 40 lần chạy; nếu không thì (b), ghi nhãn rõ |
| OQ-04 | Thời gian chờ payee | Đánh đổi giữa bảo mật và sự phiền phức | F-022, BR-017 | 24 / 48 / 72 giờ; demo 5 phút | 24 giờ (cấu hình 1 giờ–7 ngày); demo 5 phút |
| OQ-05 | Giá trị hạn mức trong demo | Demo cần một hóa đơn vượt trần và một buffer có ý nghĩa | F-020, F-023, F-024 | Dùng YAML gốc | Theo YAML gốc, co giãn theo lượng faucet |
| OQ-06 | Cửa sổ thực thi mở trước deadline bao lâu | Muộn quá dễ trễ hạn; sớm quá giữ tiền lâu | F-060, F-052 | Cố định; theo nhà cung cấp; tính theo thời gian xác nhận | 24 giờ trước deadline hoặc mốc chiết khấu; demo tính bằng phút |
| OQ-07 | Cho phép **solo mode** (một người vừa tạo vừa duyệt) cho công ty một founder? | Maker-checker sẽ chặn team rất nhỏ | F-005, BR-005 | Không bao giờ; Owner bật, có cờ; luôn bật nếu tổ chức chỉ có một thành viên | Owner bật, có cờ, có audit |
| OQ-08 | Approver bị xóa sau khi đã ký thì bản duyệt còn hiệu lực không? | Đánh đổi giữa bảo mật và gián đoạn | F-038, FR-318 | Còn (theo thời điểm ký); hết (theo danh sách hiện tại) | Hết hiệu lực: contract kiểm theo danh sách hiện tại |
| OQ-09 | Tự đối soát khi mọi bằng chứng khớp? | Công sức hay quyền kiểm soát | F-072 | Luôn thủ công; tự động có cấu hình | Có cấu hình theo tổ chức, mặc định tắt |
| OQ-10 | Ngưỡng phát hiện số tiền bất thường có cần chỉnh theo tổ chức? | Báo nhầm | F-036 | k=3 cố định; theo tổ chức | k=3 ở M1; chỉnh theo tổ chức ở giai đoạn sau |
| OQ-11 | Nhà cung cấp LLM và chính sách dữ liệu *(Phase 3)* | Quyền riêng tư, chi phí, chất lượng, bối cảnh Trung Quốc | F-094, NFR-PRIV-03 | Anthropic Claude; các nhà cung cấp khác qua adapter | Chốt bằng ADR; thiết kế không phụ thuộc nhà cung cấp |
| OQ-12 | Ánh xạ hệ thống tài khoản khi xuất bút toán | Kế toán dùng được ngay | F-073 | Chung; cấu hình theo tổ chức | Mặc định chung + bảng ánh xạ theo tổ chức |
| OQ-13 | Ai được đề xuất payee? | Quy trình | F-022 | Operator; OrgAdmin; cả hai | Cả hai đề xuất được; chỉ Owner kích hoạt |
| OQ-14 | Cơ chế đăng nhập app *(Phase 3)* | Bảo mật, công sức | F-001 | Dịch vụ auth có sẵn; thư viện tự host | Chốt bằng ADR |
| OQ-15 | M1 có cần swap không, khi chỉ có một stablecoin và swap chỉ để mua gas? | Công sức so với giá trị demo; thanh khoản DEX testnet | F-064 | Bỏ; router test có nhãn; DEX testnet | Router test có nhãn, ưu tiên P2; gas của executor luôn nạp trước |
| OQ-16 | Deadline nghĩa là "xác nhận on-chain trước" hay "đã gửi trước"? | Biên an toàn khi lập lịch | F-052, F-060 | Xác nhận trước; gửi trước | Xác nhận on-chain trước deadline, có biên theo thời gian xác nhận của chain |
| OQ-17 | Thông báo Telegram có hiện số tiền và địa chỉ không? | Quyền riêng tư trên ứng dụng chat bên thứ ba | F-101 | Không; tùy chọn bật; luôn hiện | Người dùng tự bật; mặc định tối thiểu |
| OQ-18 | Phỏng vấn được bao nhiêu khách hàng trước khi nộp (H1–H7)? | Để chứng minh vấn đề trong deck | Overview, deck | 0 / 2–3 / 5 | Cố gắng 2–3 người; báo đúng số thật |

## Kết quả cổng G1 (10/10/2026)

- **Chấp nhận khuyến nghị:** OQ-04, 05, 06, 07, 08, 09, 10, 12, 13, 15, 16, 17, 18.
- **Còn mở:** OQ-01 — cần email ban tổ chức; giả định làm việc là testnet được chấp nhận.
- **Chuyển sang Phase 3 (cổng G2):** OQ-02, 03, 11, 14.

## Cập nhật Phase 3 (11/10/2026)

| ID | Kết quả |
|---|---|
| OQ-02 | **Còn mở, anh Phúc phụ trách.** Chọn chain cho M1. Khuyến nghị: Base Sepolia; dự phòng: Ethereum Sepolia. Cần kiểm chứng: Safe đã triển khai chưa, faucet USDC testnet của Circle, EAS, nhà cung cấp RPC, explorer. **Đang chặn:** manifest triển khai, F-010, F-013, F-074, F-151. Ticket: DOM-001. |
| OQ-03 | **Còn mở, anh Phúc phụ trách.** Chọn stablecoin cho M1. Khuyến nghị: USDC testnet của Circle cho demo, cộng `tUSDC` tự triển khai (ghi nhãn TEST) cho test tự động và benchmark. Cần kiểm chứng: giới hạn faucet so với khoảng 40 lần chạy. **Đang chặn:** F-013, script seed, runbook demo. Ticket: DOM-002. |
| OQ-11 | **Đã chốt:** Anthropic Claude qua SDK, có adapter (quyết định Q27). |
| OQ-14 | **Đã chốt:** tự xây magic link + SIWE (quyết định Q33). |
| OQ-01 | **Còn mở.** Cần email ban tổ chức về việc chấp nhận testnet. Ticket: DOM-003. |
