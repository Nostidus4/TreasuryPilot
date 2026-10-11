# M02 · Treasury & cấu hình chain

**Nguồn chuẩn:** `docs/modules/treasury/README.md` · **Trạng thái:** Chi tiết (bổ sung spec 11/10/2026; *(mặc định)* = đề xuất chờ review) · **ADR:** ADR-002, ADR-012, ADR-014

## 1. Mục đích và ranh giới

M02 ghi nhận **một treasury gồm những gì**: một chain, một stablecoin thanh toán, một Safe nguồn **T**, các Safe vận hành **O1, O2**, bản module clone quản lý chúng, và module đó có phải là **thứ duy nhất** chuyển được tiền hay không (mức bao phủ – coverage).

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Cấu hình chain của nền tảng và file manifest triển khai | Nội dung mandate (M03) |
| Danh mục tài sản, kiểm decimals on-chain, nhãn TEST | Đọc số dư để lập kế hoạch (M06) |
| Tạo treasury có kiểm tra Safe | Nhiều treasury/nhiều tài sản (Later) |
| Snapshot cấu hình Safe và phát hiện thay đổi | |
| Deploy module (factory) + bật trên T/O1/O2 (qua MDT-009) | |
| Tính coverage và Owner xác nhận | |
| Tạo Safe từ giao diện (P2) | |

## 2. Feature, yêu cầu, luật

F-010 (FR-101–102), F-011 (FR-103–105), F-012 (FR-106–107, BR-018), F-013 (FR-108–109, BR-083), F-151 (FR-925); Later F-014/F-015.

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Treasury** | `(tổ chức, chain, tài sản, T, {O1, O2}, module)`. Trạng thái `Draft → ModulePending → Ready → (Paused) → Revoked`. |
| **Coverage** | COMPLETE: module bật trên mỗi Safe đúng bằng {clone của ta trỏ tới implementation đã biết}, không có guard (hoặc guard trong danh sách cho phép), fallback handler chuẩn. PARTIAL: mọi trường hợp khác. UNKNOWN: đọc lỗi. |
| **Xác nhận coverage** | Owner chấp nhận PARTIAL một cách tường minh ("tắt chế độ bảo vệ"); có audit, có banner; cho phép chạy (BR-018). |
| **Manifest triển khai** | `deployments/<chainId>.json`: implementation, factory, tUSDC, Circle USDC, Safe singleton, MultiSendCallOnly, Multicall3, EAS + schema UID, code hash. |

## 4. Mô hình dữ liệu

`chains` (11155111, 3 xác nhận, explorer, RPC), `assets` (tUSDC là TEST, Circle USDC), `deployments`, `treasuries` (+ trạng thái, module_address, coverage, người xác nhận), `treasury_wallets` (SOURCE/OPERATIONAL, nhãn, địa chỉ Safe, owners, threshold), `safe_config_snapshots`.

## 5. Trạng thái

Treasury: `Draft` (Safe đã kiểm) → `ModulePending` (giao dịch quản trị deploy+bật đang gom chữ ký/đã gửi) → `Ready` (có module, đã tính coverage) → `Revoked`. Coverage `UNKNOWN ⇄ PARTIAL ⇄ COMPLETE` tính lại khi có event cấu hình Safe và mỗi 10 phút.

## 6. API (API_SPEC §2)

| Method | Endpoint | Quyền | Lỗi |
|---|---|---|---|
| GET | `/chains` | đăng nhập | |
| POST | `/orgs/{o}/treasuries` | OWN, ADM | `NOT_A_SAFE`, `WRONG_CHAIN`, `DUPLICATE_WALLET`, `UNSUPPORTED_ASSET`, `SAFE_VERSION_UNSUPPORTED`, `OWNER_SETS_DIFFER` (cảnh báo) |
| GET | `/orgs/{o}/treasuries/{t}` | thành viên | |
| POST | `/orgs/{o}/treasuries/{t}/module/governance-tx` | OWN | → giao dịch quản trị (factory.create + bật module) |
| POST | `/orgs/{o}/treasuries/{t}/coverage/refresh` | OWN, ADM | 503 `RPC_UNAVAILABLE` |
| POST | `/orgs/{o}/treasuries/{t}/coverage/acknowledge` | OWN | 409 `COVERAGE_COMPLETE` |
| POST | `/orgs/{o}/safes/deploy-tx` (P2) | OWN | giao dịch tạo Safe |

## 7. Luồng

Wizard: chọn chain (Sepolia) và tài sản (tUSDC hoặc Circle USDC) → nhập địa chỉ T/O1/O2 (hoặc tạo mới, P2) → kiểm tra Safe → giao dịch quản trị trên T (factory.create; bật module trên T) → O1 và O2 tự bật module bằng giao dịch Safe của mình (cùng bộ owner, PH-9) → thấy event TreasuryModuleCreated → tính coverage → thiết lập Guardian Safe (MDT-010) → mandate (M03).

## 8. Thuật toán

- **Kiểm Safe:** `getCode` khác rỗng; `masterCopy` (slot 0) thuộc danh sách singleton Safe v1.4.1; `VERSION() == "1.4.1"`; đúng chain. EOA → `NOT_A_SAFE`.
- **Bộ owner:** T, O1, O2 nên cùng owner và threshold (PH-9); khác nhau thì cảnh báo, không chặn *(mặc định)*.
- **Coverage:** với mỗi Safe: `getModulesPaginated` phải đúng `[clone]`, clone trỏ đúng implementation; slot guard = 0; fallback handler thuộc danh sách cho phép. Kết quả tổng = mức xấu nhất của ba Safe.
- **Decimals:** `decimals()` on-chain phải bằng cấu hình, lệch thì từ chối tài sản.

## 9. Cấu hình

Danh sách chain và manifest đọc từ file, kiểm tra khi khởi động (thiếu RPC, thiếu code hash, ít hơn 2 RPC → không chạy). Coverage làm mới 10 phút + theo event. Chỉ hỗ trợ Safe 1.4.1 ở M1 *(mặc định)*.

## 10. Bảo mật

Coverage chặn trường hợp "module khác rút tiền mà ta không biết"; xác nhận PARTIAL phải tường minh và có audit; cấu hình không sửa được lúc chạy ở M1; tài sản test luôn có nhãn (BR-095).

## 11. Tình huống lỗi

RPC lỗi → coverage UNKNOWN (không bao giờ COMPLETE) → đóng cổng thực thi; Owner tự thêm module khác → event → PARTIAL → circuit breaker PAUSE (M12); decimals sai → từ chối tài sản.

## 12. Kế hoạch test

Integration trên Anvil với Safe v1.4.1 thật: kiểm Safe/EOA/sai phiên bản; thiết lập module qua MDT-009; COMPLETE, rồi thêm module giả → PARTIAL, thêm guard → PARTIAL, RPC lỗi → UNKNOWN; xác nhận có audit.

## 13. Ticket theo thứ tự

TRS-001 → TRS-002 → TRS-003 → TRS-004 → TRS-005 → TRS-006 → TRS-007 → TRS-008 (P2). Later TRS-L01/L02.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M02-D1 | Ethereum Sepolia; tài sản tUSDC (test) và Circle USDC (ADR-012). |
| M02-D2 | Chỉ Safe v1.4.1. *(mặc định)* |
| M02-D3 | Coverage = đúng clone của ta + không guard + fallback handler chuẩn trên cả ba Safe. |
| M02-D4 | PARTIAL chỉ chạy khi Owner xác nhận; UNKNOWN không bao giờ cho chạy. |
| M02-D5 | Thiết lập module qua giao dịch quản trị (MDT-009); O1/O2 tự bật bằng giao dịch Safe riêng. |
| M02-D6 | Bộ owner khác nhau chỉ cảnh báo. *(mặc định)* |
| M02-D7 | Làm mới coverage 10 phút + theo event. *(mặc định)* |
| M02-D8 | Cấu hình và manifest là file, kiểm khi khởi động; không sửa lúc chạy ở M1. |
| M02-D9 | Decimals kiểm on-chain khi thêm tài sản. |
| M02-D10 | Tạo Safe từ giao diện là P2 (TRS-008). |
