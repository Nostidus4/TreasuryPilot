# TreasuryPilot: Cấu trúc repository & quy ước làm việc

**Nguồn chuẩn:** `docs/REPOSITORY_STRUCTURE.md`, `CONTRIBUTING.md`, `DEVELOPMENT.md`

## 1. Vì sao dùng monorepo

1. Hai dev: một lần clone, một CI; một PR sửa được cả contract, API và UI.
2. Các struct EIP-712 phải khớp từng byte giữa Solidity, Python và TypeScript; bộ vector chuẩn dùng chung đặt ở một chỗ.
3. Bằng chứng cho giám khảo (tài liệu, bộ đánh giá, báo cáo test) nằm cạnh code.
4. Bài nộp yêu cầu một link GitHub có README và hướng dẫn triển khai.

## 2. Cấu trúc thư mục

| Thư mục | Nội dung |
|---|---|
| `apps/web/` | React + Vite + TypeScript (module M16) |
| `services/api/` | FastAPI: định danh, treasury, mandate, hóa đơn, đối soát, thông báo, audit, Copilot; kèm migration Alembic |
| `services/worker/` | Celery, một codebase chạy hai container: hàng đợi `core` (chain reader, attestation, thực thi, đối soát, phục hồi, thông báo) và hàng đợi `ai` (agent) |
| `services/signer/` | Service ký nội bộ |
| `packages/py-core/` | Lõi thuần: tiền, model domain, financial engine, policy, EIP-712, fingerprint |
| `contracts/` | Foundry: `TreasuryPilotModule.sol`, token và router test, test unit/fuzz/invariant, vector, script triển khai |
| `evals/` | Bộ dữ liệu đánh giá: hóa đơn, kịch bản, red-team, Copilot |
| `scenarios/` | Kịch bản demo và kiểm tra độ ổn định |
| `deployments/` | Manifest địa chỉ và hash code theo chain |
| `infra/` | `compose.yaml` (profile local, testnet, ci), Caddy, `.env.example` |
| `docs/` | Tài liệu sản phẩm, BA, kiến trúc, ADR, module, bản tiếng Việt (`vi/`), bằng chứng, bảo mật |
| `planning/` | Ticket nháp (`issues/`), `BACKLOG.md`, `DEPENDENCIES.md`, công cụ sinh và file theo dõi (`tools/`, `tracker/`) |
| `.github/` | Mẫu issue, mẫu PR, workflow CI |

## 3. Luật của repo

| Luật | Cách ép |
|---|---|
| `py-core` không import I/O (DB, HTTP, web3) | import-linter trong CI |
| Các service không import lẫn nhau; chỉ dùng chung `py-core` | import-linter |
| Mỗi module một thư mục, khớp với `docs/modules` | Review |
| Code sinh tự động không sửa tay | CI sinh lại và so sánh |
| PR đổi hành vi phải cập nhật tài liệu hoặc ADR tương ứng | Ô kiểm trong mẫu PR |
| Không commit bí mật | gitleaks ở pre-commit và CI |

## 4. Quy ước nhánh và commit

- **Trunk-based:** `main` được bảo vệ (CI xanh + 1 review). Nhánh ngắn hạn: `feat/<module>-<số issue>-<mô tả>`, `fix/…`, `docs/…`, `chore/…`.
- **Conventional Commits:** `feat(mandate): add cooling period check (#42)`.
- **Tag phát hành:** `m1-rc1`, `m1-submission`.

## 5. Vòng đời issue

`Draft → Needs Discussion → Ready for Review → Accepted → Ready for Assignment → Assigned → In Progress → Review → Done`

Issue chỉ thành **Accepted** sau khi team review (cổng G3). Không ai tự nhận việc; trưởng nhóm phân công.

## 6. Definition of Done chung cho mọi ticket

- Đạt tiêu chí nghiệm thu.
- Có test và test chạy qua.
- Không luật quan trọng nào chỉ dựa vào LLM hay prompt.
- Tiền là số nguyên ở đơn vị nhỏ nhất.
- Cập nhật tài liệu hoặc ADR nếu đổi hành vi hay thiết kế.
- Đã nối audit log và mã lỗi cho mọi thao tác ảnh hưởng tiền hoặc quyền.
- Đã review và merge với CI xanh.

## 7. Các file ở gốc repo

| File | Dùng để |
|---|---|
| `README.md` | Giới thiệu, bản đồ tài liệu, trạng thái dự án |
| `ARCHITECTURE.md` | Bản tóm tắt kiến trúc hai phút, trỏ sang tài liệu đầy đủ |
| `DEVELOPMENT.md` | Công cụ cần cài, lệnh chạy (mục tiêu), môi trường, bí mật, migration |
| `CONTRIBUTING.md` | Quy trình, nhánh, commit, vòng đời issue, Definition of Done, luật bảo mật cho người đóng góp |
