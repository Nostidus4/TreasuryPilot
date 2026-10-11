# TreasuryPilot: Nhật ký quyết định

**Nguồn chuẩn:** `docs/decisions-log.md`

| ID | Quyết định |
|---|---|
| Q1 | Feature lấy từ mọi nguồn: tài liệu `TreasuryPilot.md` v0.2, kế hoạch nâng điểm (T/S/N), cơ chế lấy từ GuardianAI, FigJam board. |
| Q2 | Mục "ngoài MVP" chia hai: loại *làm sau* thành feature `Later`; loại *trái bản chất sản phẩm* thành Non-goal / BR cấm. |
| Q3 | Thiết kế cho sản phẩm thật, nhiều tổ chức; Milestone 1 là bản thi. |
| Q4 | Repo và GitHub issue bằng tiếng Anh; Google Doc bằng tiếng Việt. |
| Q5 | Repo GitHub là nguồn chuẩn duy nhất. |
| Q6 | Repo `Nostidus4/TreasuryPilot`, để private, chuyển public trước khi nộp. |
| Q7 | Dùng GitHub Project có sẵn ticket, định nghĩa kỹ cùng trưởng nhóm; có file Excel theo dõi tiến độ theo module. |
| Q8 | O1–O8 dùng phương án đề xuất làm mặc định. |
| Q9 | Ba cổng review: G1 (tài liệu BA), G2 (kiến trúc), G3 (ticket). |
| Q10 | Google Doc chia mỗi tài liệu một tab. |
| Q11 | FigJam là đầu vào; sơ đồ vẽ bằng Mermaid trong repo, team tự cập nhật lên FigJam. |
| Q12 | Thư mục làm việc local là `~/Documents/GitHub/TreasuryPilot`. |
| Q13 | Có 8 vai trò; áp dụng maker-checker. |
| Q14 | Duyệt nhiều cấp n-of-m để `Later`; M1 dùng một người duyệt. |
| Q15 | Năm kênh nhận hóa đơn; M1 gồm nhập tay, upload, CSV. |
| Q16 | Kênh thông báo: app, email, Telegram, webhook (Slack/Lark/WeCom để sau); M1 gồm app + Telegram. |
| Q17 | Tuân thủ gồm KYB, KYT/trừng phạt, Travel Rule, lưu trữ dữ liệu, đều qua adapter; M1 dùng dữ liệu mẫu danh sách chặn. |
| Q18 | Một GitHub Project v2 có các field Status, Module, Epic, Priority, Phase, Size, Blocked by. Ticket 0,5–1 ngày công; quá 2 ngày phải tách. |
| Q19 | File Excel được sinh lại từ GitHub bằng script. |
| Q20 | Hóa đơn M1 chỉ tính bằng stablecoin thanh toán; fiat và FX để `Later`. |
| Q21 | Mô hình dữ liệu: một tổ chức có nhiều treasury; M1 cấu hình một treasury gồm T + O1 + O2. |
| Q22 | Billing để `Later`, ở mức tối thiểu. |
| Q23 | Team khoảng 5 người: **2 dev chính**, 3 thành viên cố vấn về tài chính và blockchain. Dev thạo **Python**. Trợ lý lập bảng chia việc; trưởng nhóm phân người. |
| Q24 | Chain cho M1: **Ethereum Sepolia** (anh Phúc chốt 11/10/2026, PH-1). |
| Q25 | Stablecoin cho M1: **`tUSDC`** cho demo chính + một lượt **Circle USDC** với hạn mức ÷ 100 (anh Phúc chốt 11/10/2026, PH-2). |
| Q26 | Smart account: **Safe + `TreasuryPilotModule` tự viết**, mỗi treasury một module dùng chung cho T, O1, O2. |
| Q27 | LLM: **Anthropic Claude**, gọi trực tiếp SDK, orchestrator tự viết mỏng, không dùng framework agent. |
| Q28 | Khóa executor: keystore mã hóa trong container signer riêng ở M1; production dùng KMS. |
| Q29 | Môi trường M1: **Docker Compose trên một máy ảo cloud**. |
| Q30 | Backend: Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic; quản lý môi trường bằng **uv**; web3.py, safe-eth-py, SDK Anthropic. |
| Q31 | Frontend: React + Vite + TypeScript, wagmi/viem + RainbowKit, TanStack Query, Tailwind + shadcn/ui. |
| Q32 | Job: **Celery + Redis** (trưởng nhóm chọn). Outbox và khóa tuần tự theo treasury vẫn nằm trong PostgreSQL. |
| Q33 | Đăng nhập tự xây: magic link qua email + SIWE, cookie phiên httpOnly, RBAC trong DB. |
| Q34 | Monorepo: `apps/web`, `services/{api,worker,signer}`, `packages/py-core`, `contracts/`, `infra/`, `docs/`, `planning/`. |
| Q35 | Giám sát: structlog + OpenTelemetry + Sentry + Prometheus. |
| Q36 | Có epic riêng **"Domain & Evidence"** với ticket `non-code` cho 3 thành viên cố vấn. |
| G2 | Đã duyệt bộ tài liệu kiến trúc Phase 3–8 ngày 11/10/2026. Điểm chỉnh sau duyệt: tách `worker-ai` để tiến trình gọi LLM không giữ khóa ký nào. |
| G3 | Trưởng nhóm duyệt bộ ticket (11/10/2026) và yêu cầu không giới hạn kế hoạch theo thời gian. Đã tạo trên GitHub: 20 epic, ticket là sub-issue, liên kết blocked-by, nhãn, milestone và Project "TreasuryPilot · Delivery". Ticket M1 ở trạng thái Sẵn sàng phân công; chưa phân người. |
| M04 | Grilling contract: Safe v1.4.1; factory + clone; ngoại lệ và cho phép trùng qua giao dịch quản trị; giới hạn refill; payee theo treasury, cooling trong mandate; chỉ trả từ ví vận hành; approver ERC-1271; kiểm số dư thay đổi; factory do Safe T gọi; không chuyển token gốc; contract chỉ áp hạn bản duyệt. Luật mới BR-019, BR-036. Chi tiết: tab 19. |
| M07 | Grilling financial engine: phí trễ cố định / % mỗi kỳ / trần; không tính chi phí vốn; rolling horizon 30 ngày UTC; refill bị giới hạn bởi bound của contract; OR-Tools CP-SAT (ADR-015) + oracle vét cạn để test + EDF làm baseline/dự phòng; giải tất định. Ticket mới ENG-012. Chi tiết: tab 22. |
| M08 | Grilling policy engine: plan theo từng request; một attestation 15 phút + kiểm lại trước mỗi bước; khóa policy EIP-712; cờ HIGH phải được xác nhận; chạy thử `eth_call` trước khi gửi; trả trễ = ALLOW + cảnh báo. ADR-016, BR-066, BR-067, ticket POL-007. Chi tiết: tab 23. |
| M05 | Grilling hóa đơn: một Approver; bảng vendor có nhiều địa chỉ payee; cờ gần trùng; hủy on-chain bằng `cancelRequest` (Approver hoặc Safe T); trường ràng buộc và trường tự do. BR-007, BR-076, BR-077; ticket INV-012, SC-022. Chi tiết: tab 20. |
| PH | Vòng chain với anh Phúc: Ethereum Sepolia; tUSDC + một lượt Circle USDC; public testnet được chấp nhận; Guardian Safe 1-trên-N có sentinel; "Đã trả" sau 3 xác nhận; đọc event bằng getLogs + quét lại 64 block; gas EIP-1559 do hệ thống đề xuất; Alchemy + RPC công khai; T/O1/O2 cùng owner 2-trên-3; deploy CREATE2 + verify Etherscan; biên nhận EAS lên P1/Tier A (ADR-018). |
| M03 | Grilling mandate: ký giao dịch Safe ngay trong app (ADR-017); sentinel chỉ pause được; gói thay đổi chỉ tăng version khi cần; đọc lại on-chain mới Active; payee phải xác minh ngoài kênh; ngoại lệ 72 giờ; chính sách phí FEE-1…3 (hệ thống đề xuất ngưỡng/ngân sách, Owner chấp nhận; hoãn khi còn kịp hạn; hỏi người ở ngày cuối). BR-008, BR-068, BR-084; ticket MDT-009/010, EXE-012/013, WEB-024/025. Chi tiết: tab 18. |
| M06 | Grilling đọc chain: đối chiếu RPC thứ hai trước khi báo Đã trả; theo dõi dòng tiền token và cảnh báo tiền ra không qua agent; snapshot Multicall3 ghim block; ngày theo block. BR-069, FR-419, ticket CHR-006. Chi tiết: tab 21. |
| SPEC | Bổ sung spec chi tiết (theo yêu cầu trưởng nhóm) cho M01, M02, M09–M19 theo mẫu 14 mục; mục *(mặc định)* là đề xuất đã áp dụng, chờ review. Căn chỉnh ticket WEB/RCV/NTF/REC/AGT. Epic trên GitHub có mô tả đầy đủ. Bản tiếng Việt chi tiết của 20 module ở tab 16–35. |
