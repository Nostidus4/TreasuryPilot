# TreasuryPilot: Câu hỏi mở

**Nguồn chuẩn:** `docs/OPEN_QUESTIONS.md`

Mỗi câu hỏi có khuyến nghị của BA. Khuyến nghị được dùng làm **giả định làm việc** cho đến khi team trả lời. O1–O8 của tài liệu gốc đã đóng theo quyết định Q8 và đã thành giá trị mặc định trong các BR.

| ID | Câu hỏi | Vì sao quan trọng | Ảnh hưởng | Phương án | Khuyến nghị BA |
|---|---|---|---|---|---|
| OQ-01 | Thể lệ yêu cầu bằng chứng nào và nhóm chọn mạng nào? | Phân biệt yêu cầu BTC với giả định của nhóm | NFR-CMP-01, F-151, mục submission 06 | Tx hash on-chain thật; checklist không chỉ định testnet/mainnet | Dùng Ethereum Sepolia theo ADR-012/019 và NFR-CMP-01; hỏi thêm BTC là tùy chọn, không chặn công việc |
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
- **OQ-01:** yêu cầu đã được đối chiếu với thể lệ ngày 14/10/2026; không có bước email bắt buộc. Nhóm dùng Sepolia như giả định làm việc, không tuyên bố có xác nhận từ BTC.
- **Chuyển sang Phase 3 (cổng G2):** OQ-02, 03, 11, 14.

## Cập nhật Phase 3 (11/10/2026)

| ID | Kết quả |
|---|---|
| OQ-02 | **Đã chốt (anh Phúc, 11/10/2026):** Ethereum Sepolia (ADR-012). |
| OQ-03 | **Đã chốt (anh Phúc, 11/10/2026):** `tUSDC` cho demo chính và test tự động; một lượt bằng chứng bằng USDC thật của Circle trên Sepolia với hạn mức chia 100 (faucet Circle: 10 USDC/ngày công khai, 10 × 20 USDC/ngày cho tài khoản developer). |
| OQ-11 | **Đã chốt:** Anthropic Claude qua SDK, có adapter (quyết định Q27). |
| OQ-14 | **Đã chốt:** tự xây magic link + SIWE (quyết định Q33). |
| OQ-01 | **Cách hiểu của nhóm ghi nhận qua anh Phúc (11/10/2026):** dùng public testnet. Đây không phải phản hồi của BTC; xem đối chiếu thể lệ ngày 14/10 dưới đây. |

## OQ-01 / DOM-003 — đối chiếu thể lệ ngày 14/10/2026

[Thể lệ PBCSF Appendix 2](https://www.its.ac.id/international/wp-content/uploads/sites/66/2026/10/PBCSF-Appendix-2-Problem-Description-and-Competition-Rules-for-International-Track.pdf),
trang 3, checklist submission mục 06, yêu cầu Topic on-chain có **tx hash on-chain
thật**. Checklist không chỉ định testnet/mainnet, không yêu cầu gửi email hay có
xác nhận bằng văn bản.

Nhóm tiếp tục dùng Ethereum Sepolia theo ADR-012/019 và phạm vi testnet-only của
NFR-CMP-01. Điều này là lựa chọn/giả định của nhóm, không phải cam kết BTC chấp nhận
testnet. Bằng chứng phải lấy từ action thực sự thực thi; nhóm bổ sung chain ID,
explorer link và receipt/event để dễ kiểm chứng, không coi hash tính offline hoặc
mô phỏng là giao dịch public thật.

Hỏi BTC là tùy chọn để tăng độ chắc chắn, không chặn development/submission và
không phải acceptance bắt buộc của #231. Lần đối chiếu này không gửi email, không
giả lập phản hồi. Nếu sau này BTC đưa ra yêu cầu khác, ghi phản hồi thật và mở
quyết định thay đổi ADR/scope có review; không tự chuyển sang mainnet. Phần deploy
và thu thập tx hashes thực tế vẫn thuộc DOM-001/002 và các ticket thực thi.
