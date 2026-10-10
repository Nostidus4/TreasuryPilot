# TreasuryPilot: Mô hình dữ liệu

**Nguồn chuẩn:** `docs/DATA_MODEL.md` (có sơ đồ ER dạng Mermaid) · **Lưu trữ:** PostgreSQL 16

## 1. Quy ước

- **Khóa chính:** `id UUID` (v7, sắp theo thời gian).
- **Đa tổ chức:** mọi bảng thuộc tổ chức đều có `org_id`, và mọi truy vấn đều lọc theo `org_id`.
- **Trường audit** trên bảng sửa được: `created_at`, `created_by`, `updated_at`, `updated_by`, `version` (optimistic lock).
- **Bảng bất biến** (chỉ ghi thêm, DB chặn UPDATE/DELETE bằng trigger): `audit_log`, `ai_calls`, `mandate_versions`, `approvals`, `observed_events`, `verifications`.
- **Tiền:** `NUMERIC(78,0)`, số nguyên ở đơn vị nhỏ nhất.
- **Định danh chain:** `chain_id`; địa chỉ lưu 20 byte; `tx_hash` 32 byte.

## 2. Các nhóm bảng

### 2.1 Định danh (M01)

| Bảng | Cột chính | Ràng buộc |
|---|---|---|
| `users` | email, tên hiển thị, trạng thái | email duy nhất |
| `sessions` | user, hạn dùng, lần cuối hoạt động, thu hồi | |
| `magic_links` | email, hash token, hạn dùng, đã dùng | hash token duy nhất |
| `wallet_links` | user, địa chỉ, có phải ví contract | **mỗi địa chỉ chỉ thuộc một user** |
| `siwe_nonces` | nonce, hạn dùng, đã dùng | |
| `organizations` | tên, pháp nhân, quốc gia, múi giờ hiển thị, solo_mode | |
| `memberships` | org, user, danh sách vai trò | duy nhất theo (org, user) |
| `invites` | org, email, vai trò, hash token, hạn dùng | |

### 2.2 Treasury & chain (M02)

| Bảng | Cột chính |
|---|---|
| `chains` | chain_id, tên, có phải testnet, số xác nhận, URL explorer, danh sách RPC |
| `assets` | chain, địa chỉ, ký hiệu, decimals, nhà phát hành, cờ test, cờ native |
| `deployments` | chain, tên, địa chỉ, hash code, phiên bản |
| `treasuries` | org, chain, stablecoin thanh toán, địa chỉ module, trạng thái, mức bao phủ |
| `treasury_wallets` | treasury, vai trò (SOURCE / OPERATIONAL), nhãn, địa chỉ Safe, owners, threshold |
| `safe_config_snapshots` | ví, block, owners, threshold, modules, guard |

### 2.3 Mandate, payee, ngoại lệ (M03)

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `mandate_versions` | treasury, phiên bản, trạng thái, cấu hình (jsonb), hash cấu hình, tx kích hoạt, hiệu lực từ/đến | Dòng bất biến |
| `mandate_status_events` | phiên bản mandate, từ → đến, tx, thời điểm, người làm | Chỉ ghi thêm |
| `vendors` | org, tên, mã tham chiếu, liên hệ (mã hóa) | Dữ liệu mật |
| `payees` | treasury, vendor, nhãn, địa chỉ, trạng thái (Screening / Cooling / Active / Deactivated), `active_from` | |
| `screenings` | địa chỉ, nhà cung cấp, kết quả (CLEAR / HIT / ERROR), thời điểm, hạn TTL | |
| `exceptions` | yêu cầu chi, phiên bản mandate, số tiền, hạn, nonce, chữ ký owner, trạng thái | Mỗi yêu cầu tối đa một ngoại lệ đang Granted |

### 2.4 Hóa đơn & yêu cầu chi (M05)

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `payment_requests` | org, treasury, vendor, payee, số hóa đơn, số tiền, tài sản, ví trả, hạn, điều khoản đã xác nhận, fingerprint, trạng thái, người tạo, người sửa cuối | **fingerprint duy nhất trong treasury** với các yêu cầu còn hiệu lực |
| `request_revisions` | yêu cầu, số revision, bản chụp | Sửa thì bản duyệt mất hiệu lực |
| `documents` | yêu cầu, khóa lưu trữ, sha256, loại tệp | Tệp nằm ở S3 riêng tư |
| `extractions` | tài liệu, lời gọi AI, các trường kèm nguồn gốc, điều khoản, người xác nhận | |
| `flags` | yêu cầu, mã, mức độ, bằng chứng, nguồn (DETERMINISTIC / AI), người xác nhận | |
| `approvals` | yêu cầu, revision, người duyệt, địa chỉ, dữ liệu đã ký, chữ ký, hạn, trạng thái | |
| `request_status_events` | yêu cầu, từ → đến, người làm, lý do | Chỉ ghi thêm |

### 2.5 Lập kế hoạch & AI (M07–M09)

| Bảng | Cột chính |
|---|---|
| `snapshots` | treasury, block, thời điểm, dữ liệu (số dư, bộ đếm, payee, mandate), mức bao phủ, phần thiếu |
| `plans` | treasury, snapshot, nguồn lập kế hoạch (AI / RULE_BASED / DETERMINISTIC), lý do chọn, điểm mục tiêu, trạng thái, plan_hash |
| `plan_steps` | kế hoạch, thứ tự, `step_id` (duy nhất), yêu cầu, hành động (REFILL / PAY / SWAP), ví nguồn, địa chỉ đích, số tiền |
| `validations` | kế hoạch, bước, quyết định, mã lý do, chi tiết kiểm tra, phiên bản chính sách |
| `attestations` | kế hoạch, dữ liệu đã ký, chữ ký, nonce (duy nhất), hạn dùng |
| `ai_calls` | mục đích, model, phiên bản prompt, tham chiếu đầu vào, tool đã gọi, đầu ra, kết quả kiểm tra, độ trễ, token, chi phí. **Đây là lịch sử quyết định AI** |
| `copilot_threads`, `copilot_messages` | hội thoại Copilot |

### 2.6 Thực thi & chain (M06, M10)

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `operations` (**outbox**) | treasury, bước kế hoạch, yêu cầu, `step_id`, loại, payload, idempotency key, trạng thái, số lần thử | `step_id` duy nhất |
| `transactions` | thao tác, chain, tx_hash, nonce, giao dịch thay thế, trạng thái, block, gas, phí | |
| `observed_events` | treasury, block, tx, log index, tên event, payload, cờ bị reorg | Duy nhất theo (chain, tx, log index) |
| `verifications` | thao tác, kỳ vọng, quan sát, kết quả (PASSED / DISCREPANCY / UNKNOWN) | |
| `gas_ledger` | treasury, giao dịch, phí, ví trả phí, có revert không | |

### 2.7 Đối soát, phục hồi, thông báo, audit (M11–M15)

| Bảng | Cột chính |
|---|---|
| `reconciliations` | yêu cầu, trạng thái (NotReady / Pending / Matched / Discrepancy), người khớp, ghi chú |
| `recon_lines` | bản đối soát, giao dịch, phân loại (chuyển nội bộ / chuyển đổi / chi phí ngoài / phí), số tiền |
| `chain_attestations` | yêu cầu, schema UID, attestation UID, tx |
| `review_items` | org, treasury, yêu cầu, kế hoạch, loại, mã lý do, bước đã xong, vai trò xử lý, trạng thái, hạn SLA |
| `circuit_events` | treasury, luật, chi tiết, hành động (ALERT / PAUSE) |
| `notifications` | org, user, loại sự kiện, ID sự kiện, đã đọc |
| `notification_channels` | user, loại kênh, đích (mã hóa), đã xác minh, có hiện số tiền không |
| `audit_log` | org, thời điểm, loại tác nhân (USER / SYSTEM / AI / CONTRACT), hành động, đối tượng, dữ liệu, `prev_hash`, `hash` |
| `evidence_bundles` | org, yêu cầu hoặc kịch bản, khóa lưu trữ, sha256 |

## 3. Lịch sử sự kiện và lịch sử quyết định AI

- Dòng thời gian đầy đủ của một yêu cầu chi được dựng lại từ: các bảng `*_status_events`, `validations`, `ai_calls`, `operations`, `transactions` và `audit_log`. Gói bằng chứng được ghép từ các bảng này.
- Mỗi kế hoạch tham chiếu tới các `ai_calls` đã tạo ra hoặc giải thích nó, và tới bản kiểm tra đã chấp nhận hoặc loại nó. Cột `planner_source` và `chosen_reason` ghi lại vì sao kế hoạch AI hay kế hoạch xác định được chọn.

## 4. Ràng buộc quan trọng

| Ràng buộc | Mục đích |
|---|---|
| `payment_requests (treasury_id, fingerprint)` duy nhất có điều kiện | Chống trùng hóa đơn (BR-071) |
| `plan_steps.step_id` và `operations.step_id` duy nhất | Không thực thi trùng bước (BR-061) |
| `attestations.nonce` duy nhất | Chống replay (BR-059) |
| `wallet_links.address` duy nhất có điều kiện | Mỗi địa chỉ một user |
| Một ngoại lệ Granted cho mỗi yêu cầu | BR-041 |
| Chuỗi hash của `audit_log` + trigger chặn sửa | BR-097 |
| `CHECK (amount >= 0)` trên mọi cột tiền | ADR-014 |

## 5. Phân loại dữ liệu

| Loại | Ví dụ | Cách xử lý |
|---|---|---|
| Bí mật | Token phiên, mật khẩu keystore | Không lưu dạng rõ, không ghi log |
| Mật | Tệp hóa đơn, liên hệ nhà cung cấp, chat id Telegram | Mã hóa khi lưu; URL có chữ ký; che trong log |
| Nội bộ | Yêu cầu chi, kế hoạch, ai_calls | Giới hạn theo tổ chức |
| Công khai | Hash và event trên chain | Vốn đã công khai |
