# M19 · Trải nghiệm dev & chất lượng

**Nguồn chuẩn:** `docs/modules/devex/README.md` · **Trạng thái:** Chi tiết (bổ sung spec 11/10/2026; *(mặc định)* = đề xuất chờ review) · **ADR:** ADR-001, ADR-008, ADR-010

## 1. Mục đích và ranh giới

M19 làm cho codebase **dễ bắt đầu, khó làm hỏng, và tự chứng minh được**: khung monorepo, stack local một lệnh, dữ liệu seed, cổng CI, kiểm ranh giới module, công cụ chạy kịch bản, bộ đo độ ổn định, runbook demo và VM testnet.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Monorepo (uv + pnpm), pre-commit | Gia cố production, nhiều VM |
| Stack Compose: profile local + testnet, Caddy TLS | |
| Seed, chạy kịch bản, đo độ ổn định, runbook demo | |
| CI: Python, contract (fuzz, Slither), web + kiểm lệch client OpenAPI, gitleaks, import-linter | |

## 2. Feature, yêu cầu

F-160 (FR-927), F-161 (FR-928, NFR-MAINT-01/03), F-162 (FR-929, BR-095), F-163 (FR-930, NFR-SEC-02/06/07), F-164 (FR-931, NFR-REL-01), F-151 (FR-925).

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Profile** | `local` (Anvil 31337, MinIO, mọi service) và `testnet` (Sepolia, không Anvil, có Caddy). |
| **Kịch bản** | YAML trong `scenarios/` mô tả thiết lập, hành động, kết quả mong đợi; chỉ chạy trên chain nằm trong danh sách cho phép. |
| **Bằng chứng** | Báo cáo và gói bằng chứng ghi vào `docs/evidence/` (độ ổn định, benchmark, red-team, trích xuất). |

## 4. Cấu trúc repo

`apps/web`, `services/{api,worker,signer}`, `packages/py-core`, `contracts/`, `infra/{compose.yaml, Caddyfile, env/.env.example}`, `evals/`, `scenarios/`, `deployments/`, `docs/`, `planning/`. Python 3.12, workspace uv; pnpm cho web; ghim phiên bản Foundry.

## 5. Lệnh make

| Lệnh | Làm gì |
|---|---|
| `make dev` / `make down` | bật/tắt postgres 16, redis 7, minio, anvil + các service app |
| `make seed` | deploy contract + Safe trên Anvil, tổ chức/người dùng/vai trò, treasury, mandate Active, payee (một cái đang cooling), 5 hóa đơn; chạy lại không tạo trùng |
| `make test` / `make lint` | mọi test / linter Python, web, contract |
| `make openapi` | xuất OpenAPI và sinh lại client TS |
| `make deploy-local` / `make deploy-sepolia` | deploy contract bằng CREATE2 (SC-016) |
| `scenario run <tên>` | demo-main, over-cap-exception, injected-invoice, crash-recovery, pause, unexpected-outflow *(thêm)*, fee-spike *(thêm)* |
| `make reliability` | 30 lượt demo-main trên Anvil + N lượt trên Sepolia → `docs/evidence/reliability-<ngày>.md` |
| `make bench`, `make eval-extraction`, `make redteam`, `make eval-validate` | đánh giá AI (M09, M20) |

## 6. Workflow CI

| Workflow | Cổng |
|---|---|
| `ci.yml` (Python) | ruff, ruff format, mypy (strict cho py-core), pytest + coverage (py-core ≥ 85 %), import-linter, gitleaks |
| `contracts.yml` | forge fmt, build, test (fuzz 1k trên PR, 10k trên main), bất biến, Slither (artifact) |
| `web.yml` | eslint, tsc, vite build, kiểm lệch client OpenAPI |
| `e2e.yml` (main + hằng đêm) | Playwright luồng chính trên Anvil (WEB-023), test crash RCV-007 *(mặc định: hằng đêm)* |
| `images.yml` | build + đẩy lên GHCR, tag bằng git SHA |

Luật import-linter: py-core cấm sqlalchemy, httpx, web3, celery, fastapi (cho phép ortools và eth-account, ADR-015/ENG-010); các service không import lẫn nhau; code của worker-ai không được import module signer/attestation.

## 7. Luồng

Dev mới: clone → `uv sync && pnpm install` → `make dev && make seed` → app ở `http://localhost:5173` kèm link đăng nhập in ra (≤ 15 phút). Deploy: push main → build image → trên VM `docker compose --profile testnet pull && up -d`.

## 9. Cấu hình

`.env.example` chỉ liệt kê tên biến; bí mật qua Docker secret (keystore và mật khẩu của executor/sentinel/policy/biên nhận, khóa mã hóa trường, khóa LLM, Sentry DSN, token Telegram). Chỉ web và api lộ ra qua Caddy; signer, postgres, redis, minio ở mạng nội bộ.

## 10. Bảo mật

gitleaks ở pre-commit + CI; image không chứa bí mật; Slither + fuzz + bất biến cho contract; công cụ kịch bản từ chối chain id ngoài danh sách (BR-095); tài sản test có nhãn.

## 11. Tình huống lỗi

Testnet chập chờn → báo cáo ghi rõ lần thử lại, không giấu (báo cáo độ ổn định phân loại lỗi); Anvil reset → `make seed` chạy lại được.

## 12. Kế hoạch test

Chính các workflow; secret giả bị chặn; import sai luật làm CI lỗi; đo thời gian clone mới; một thành viên chạy thử runbook.

## 13. Ticket

DEV-001 → DEV-002 → DEV-011 → DEV-003 → DEV-004 → DEV-005 → DEV-006 → DEV-007 → DEV-008 → DEV-009 → DEV-010.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M19-D1 | Monorepo uv + pnpm + Foundry, ghim phiên bản. |
| M19-D2 | Profile Compose local/testnet; Caddy TLS trên một VM. |
| M19-D3 | Seed chạy lại không trùng, dùng API công khai khi có thể. |
| M19-D4 | Kịch bản bằng YAML; danh sách chain id cho phép. |
| M19-D5 | Thêm kịch bản unexpected-outflow, fee-spike. *(mặc định)* |
| M19-D6 | Cổng coverage py-core ≥ 85 %. |
| M19-D7 | Import-linter cho phép ortools và eth-account trong py-core. |
| M19-D8 | Fuzz 1k trên PR, 10k trên main. |
| M19-D9 | E2E và test crash chạy hằng đêm + trên main. *(mặc định)* |
| M19-D10 | Image trên GHCR tag bằng git SHA. |
| M19-D11 | Chỉ web và api truy cập được từ internet. |
| M19-D12 | Độ ổn định: 30 lượt local + N lượt Sepolia, lỗi được phân loại. |
