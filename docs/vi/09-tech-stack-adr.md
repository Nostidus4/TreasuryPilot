# TreasuryPilot: Tech stack & các quyết định kiến trúc (ADR)

**Nguồn chuẩn:** `docs/TECH_STACK.md`, `docs/adr/` · **Trạng thái:** Đã qua cổng G2

## 1. Căn cứ lựa chọn

1. **Team:** 2 dev chính thạo Python; 3 thành viên cố vấn không code.
2. **Câu chuyện bảo mật chính là sản phẩm:** luật được thực thi on-chain; phần off-chain phải làm rõ ranh giới tin cậy giữa AI, validator, signer và contract.
3. **Yêu cầu:** không trả trùng (cần outbox giao dịch); cách ly khóa; dựng lại được bằng một lệnh.
4. **Ít thành phần ở M1:** mỗi service thêm vào là một rủi ro cho ngày demo.

## 2. Bảng tóm tắt

| Tầng | Lựa chọn |
|---|---|
| Smart contract | Solidity 0.8.x, Foundry (forge/anvil/cast), Safe contracts và OpenZeppelin (khóa phiên bản), Slither |
| Smart account | Safe + `TreasuryPilotModule` tự viết, mỗi treasury một module |
| Backend API | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| Lõi nghiệp vụ | `packages/py-core`: Python thuần (financial engine, policy, kiểu domain), không I/O |
| Lưu trữ | PostgreSQL 16, SQLAlchemy 2 (async), Alembic |
| Job | Celery 5 + Redis 7 + Celery beat; outbox và advisory lock nằm trong Postgres |
| Truy cập chain | web3.py, eth-account (EIP-712), safe-eth-py; 2 nhà cung cấp RPC có dự phòng |
| Signer | Service FastAPI riêng; keystore mã hóa ở M1, adapter KMS cho production |
| AI | SDK Anthropic cho Python (Claude), tool use + structured output, orchestrator tự viết, chọn model theo tác vụ |
| Đăng nhập | Tự xây: magic link qua email (Resend) + SIWE, cookie phiên httpOnly, RBAC trong DB |
| Frontend | React 18 + Vite + TypeScript, wagmi/viem + RainbowKit, TanStack Query, React Hook Form + Zod, Tailwind + shadcn/ui, Recharts, client sinh từ OpenAPI |
| Realtime | Server-Sent Events |
| Thông báo | Trong app + Telegram; email để sau |
| Lưu tệp | Object storage tương thích S3 (MinIO khi local), bucket riêng tư + URL có chữ ký |
| Giám sát | structlog (JSON), OpenTelemetry, Sentry, Prometheus `/metrics` |
| Kiểm thử | pytest + hypothesis, Foundry fuzz/invariant, Playwright, bộ đánh giá AI tự viết |
| Công cụ | uv (Python), pnpm (web), ruff + mypy, eslint + prettier, pre-commit, gitleaks |
| CI/CD | GitHub Actions; image đẩy lên GHCR |
| Môi trường M1 | Docker Compose trên một máy ảo cloud |

## 3. Lý do, phương án đã cân nhắc và đánh đổi

| Lựa chọn | Vì sao | Phương án khác | Đánh đổi |
|---|---|---|---|
| Solidity + Foundry + Safe | Safe là smart account phổ biến nhất; module cho phép hành động mà không cần owner ký từng giao dịch. Foundry có fuzz/invariant nhanh | Hardhat; chỉ dùng Zodiac Roles; ERC-4337 | Module tự viết là code trọng yếu, chưa audit → giữ bề mặt nhỏ, test invariant, phân tích tĩnh |
| Python + FastAPI | Ngôn ngữ của team; Pydantic cho schema chặt (cả API lẫn đầu ra LLM); tự sinh OpenAPI | Django; Node/TS | Công cụ web3 của Python kém tiện hơn viem; chấp nhận được vì phần ký nằm ở trình duyệt |
| Lõi nghiệp vụ là package thuần | Logic tiền quan trọng nhất phải test độc lập, dùng chung cho API, worker và benchmark | Viết lẫn trong service | Cần kỷ luật, được ép bằng import-linter |
| PostgreSQL | Toàn vẹn quan hệ cho tiền, trạng thái, audit; outbox giao dịch; advisory lock | MongoDB; SQLite | Phải cẩn thận với migration |
| Celery + Redis (trưởng nhóm chọn) | Hệ job Python quen thuộc, có retry, lịch, giám sát | Hàng đợi chỉ dùng Postgres; Dramatiq/RQ | Thêm một service; có thể giao trùng job → xử lý bằng idempotency. **Celery chỉ điều phối; dữ liệu chuẩn luôn ở Postgres** |
| Signer riêng | Chỉ một tiến trình giữ khóa executor, và chỉ ký payload có attestation | Ký trong worker; dịch vụ MPC/TEE | Thêm service; keystore ở M1 kém an toàn hơn KMS (rủi ro đã ghi nhận) |
| Claude qua SDK, không dùng framework agent | Ít tool, schema chặt, validator xác định. Framework sẽ che mất ranh giới an toàn. Claude đọc được PDF trực tiếp | LangChain/LangGraph; nhà cung cấp khác | Tự viết orchestrator nhỏ và bộ đánh giá |
| Tự xây đăng nhập | Phạm vi nhỏ; kiểm soát được RBAC và maker-checker; SIWE đằng nào cũng phải làm | Clerk, Auth0, Supabase | Tự chịu trách nhiệm bảo mật phiên |
| React + Vite + wagmi | Ký ví trên trình duyệt cần JavaScript; SPA gọi API riêng | Next.js; Streamlit | Thêm một ngôn ngữ; client sinh tự động tránh lệch kiểu |
| Docker Compose trên một VM | Một cấu hình dùng cho local, CI và demo | Nhiều PaaS; Kubernetes | Một điểm lỗi duy nhất khi demo → có video và bản chạy local dự phòng |

## 4. Danh sách ADR

| ADR | Quyết định | Trạng thái |
|---|---|---|
| 001 | Monorepo: Python cho off-chain, TypeScript cho web, Solidity cho contract. Ranh giới module ép bằng import-linter | Đã duyệt (G2) |
| 002 | Safe + `TreasuryPilotModule` tự viết, mỗi treasury một module. Safe T quản trị. Không nâng cấp được ở M1 | Đã duyệt |
| 003 | EIP-712 cho ba loại: `PaymentApproval` (Approver ký), `OneTimeException` (Owner ký), `PlanAttestation` (policy engine ký). Hỗ trợ ERC-1271. Chống replay bằng nonce và cờ đã dùng | Đã duyệt |
| 004 | PostgreSQL là nguồn chuẩn. Mọi bước chuyển tiền được ghi vào outbox **trong cùng transaction** trước khi ký | Đã duyệt |
| 005 | Claude qua SDK; AI chỉ tư vấn. Tool chỉ đọc; mọi đầu ra qua kiểm tra xác định; có fallback rule-based | Đã duyệt |
| 006 | Signer service: kiểm tra attestation → so khớp payload → kiểm tra chain → mô phỏng → ký → gửi. M1 dùng keystore mã hóa; production dùng KMS | Đã duyệt |
| 007 | Celery + Redis chạy job. Hai hàng đợi: `core` (giữ khóa attestation) và `ai` (không giữ khóa ký). Khóa tuần tự theo treasury bằng advisory lock của Postgres | Đã duyệt |
| 008 | Docker Compose cho M1, ba profile `local`, `testnet`, `ci`. Caddy làm reverse proxy có TLS | Đã duyệt |
| 009 | Đăng nhập bằng magic link + SIWE, phiên lưu phía server, cookie httpOnly, CSRF, RBAC trong DB | Đã duyệt |
| 010 | REST `/v1` bằng FastAPI; client TypeScript sinh từ OpenAPI; SSE cho realtime; lỗi dạng problem+json | Đã duyệt |
| 011 | Giám sát: structlog + OpenTelemetry + Sentry + Prometheus | Đã duyệt |
| 012 | **Chain và stablecoin cho M1: còn mở, anh Phúc phụ trách.** Khuyến nghị: Base Sepolia; USDC testnet của Circle cho demo và `tUSDC` tự triển khai cho test tự động | **Còn mở** |
| 013 | Frontend: React + Vite + wagmi | Đã duyệt |
| 014 | Tiền là số nguyên ở đơn vị nhỏ nhất xuyên suốt; cấm số thực | Đã duyệt |
