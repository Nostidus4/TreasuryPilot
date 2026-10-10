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
| Q24 | Chain cho M1: **còn mở, anh Phúc phụ trách** (OQ-02). Giả định làm việc: Base Sepolia. |
| Q25 | Stablecoin cho M1: **còn mở, anh Phúc phụ trách** (OQ-03). Giả định làm việc: USDC testnet của Circle cho demo, `tUSDC` cho test tự động. |
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
