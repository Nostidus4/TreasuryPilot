# TreasuryPilot: Cập nhật v0.3 (Aave & bản duyệt hai mức tiền)

**Nguồn chuẩn:** `docs/adr/ADR-019-aave-liquidity-and-payment-options.md`, spec v0.3 của nhóm trưởng (`docs/source/TreasuryPilot-v0.3-team-lead-spec.md`) · **Trạng thái:** Đã chốt (11/10/2026)

Bản v0.3 mở rộng MVP từ "chỉ REFILL/PAY, không cho vay" thành **quản lý quỹ on-chain tự động**: giữ tiền cho nghĩa vụ đã duyệt, đưa USDC thực sự dư vào Aave V3, và rút về khi có nghĩa vụ mới. Kiến trúc hiện tại (Python, Safe + một module, CP-SAT, attestation) được giữ nguyên; v0.3 được gộp vào.

## 1. Các quyết định

| ID | Quyết định |
|---|---|
| V3-1 | **SUPPLY / WITHDRAW Aave V3 chạy tự động** qua lệnh cố định tới một Pool trong danh sách cho phép, chỉ với stablecoin của treasury; aToken nằm trong Safe T. |
| V3-2 | **Vay/trả:** M1 chỉ có **đề xuất vay** (so chi phí rút với vay, health factor, lý do), không giao dịch (D6). Thực thi vay/trả có Owner cấp quyền một lần là **P2** (D7). |
| V3-3 | **Bản duyệt hai mức tiền:** thêm `earlyAmount`, `earlyPayBy`. Trước hạn trả sớm contract trả đúng mức sớm, sau đó trả đúng mức chuẩn. Sửa lỗ hổng "tính chiết khấu mà vẫn trả đủ tiền". |
| V3-4 | Backend **giữ Python**; Viem chỉ dùng ở web. |
| V3-5 | Bộ tối ưu **giữ CP-SAT**; thêm các thành phần chi phí của v0.3 dưới dạng số nguyên (phí trễ, chiết khấu bị mất, lãi vay, gas, lãi gửi). |
| V3-6 | Demo dùng **1 ví vận hành** (T + O1); contract vẫn hỗ trợ nhiều ví. |
| V3-7 | Token trên Sepolia = **USDC test của Aave** (`0x94a9…E4C8`, faucet Aave, nhãn TEST); `tUSDC` + pool giả chỉ dùng local/CI; lượt Circle USDC chỉ có PAY. |
| V3-8 | **Bảo vệ dự trữ:** contract giữ **sàn Safe** cố định (Owner đặt) và **hạn mức supply**; phần dự trữ cho hóa đơn đã duyệt (PaymentReserve) do validator off-chain kiểm. Rút luôn tự động về Safe T. |
| V3-9 | **Có ngưỡng:** chỉ supply khi dư ≥ `min_supply` (demo 500); rút phần thiếu + 5 %; mỗi chu kỳ tối đa một lệnh. |
| V3-10 | **Một module duy nhất**, thêm hàm cố định `supply`, `withdraw` (và `borrow`, `repay` P2). |
| V3-11 | Test: pool giả cho unit, **fork Sepolia ở block cố định** cho integration, demo trên Sepolia. |
| V3-12 | **Demo D1–D10** thành kịch bản và cảnh trong runbook. |
| V3-13 | Benchmark thêm **B0** (làm tay/EDF, tiền để không). |
| V3-14 | **Cổng cấu hình trong CI** + câu miễn trừ trong gói bằng chứng (testnet, dữ liệu giả lập, không phê duyệt pháp lý, không audit, không hứa lợi suất). |

## 2. Công thức

```
RequiredSafeReserve = PaymentReserve + sàn Safe + dự trữ trả nợ + khoản đang giữ
AvailableForSupply  = max(0, USDC trong Safe − RequiredSafeReserve)
AccessibleLiquidity = USDC trong Safe + min(aUSDC, thanh khoản pool)
```

Ví dụ: Safe 6.000, sàn 1.000, đã duyệt chưa trả 2.000 → SUPPLY 3.000 (D2). Duyệt thêm 2.500 → thiếu 2.500 → WITHDRAW 2.625 (D3).

## 3. Demo cho giám khảo

| ID | Tình huống | Phải chứng minh |
|---|---|---|
| D1 | Ví vận hành thiếu tiền | tự refill rồi trả, đủ bằng chứng |
| D2 | USDC dư | supply đúng phần dư, dự trữ còn nguyên |
| D3 | Có hóa đơn mới được duyệt | rút từ Aave để khôi phục dự trữ |
| D4 | Payee lạ | bị chặn trước khi thực thi |
| D5 | Vượt trần | bị chặn; chỉ ngoại lệ một lần mới qua |
| D6 | Đề xuất vay | chi phí/health factor; không ký, không giao dịch |
| D7 | Vay có chữ ký (P2) | đúng tham số một lần; trả vẫn phải duyệt |
| D8 | AI ngừng | chỉ chạy đường dự phòng an toàn |
| D9 | Giao dịch không rõ trạng thái | không thử lại cho tới khi rõ |
| D10 | Guardian pause | executor bị từ chối; Safe vẫn tự phục hồi được |

## 4. Luật, yêu cầu, feature

- **Sửa:** BR-024 (trả đúng một mức đã duyệt), BR-090 (cho phép supply/withdraw vào một pool; vẫn cấm đầu cơ, đòn bẩy, tài sản khác; vay chỉ khi Owner cấp quyền).
- **Mới:** BR-037 (công thức dự trữ, sàn, min_supply), BR-038 (rút khi thiếu dự trữ), BR-044 (vay/trả cần quyền một lần); FR-519 đến FR-524; F-068 (quản lý tiền dư trên Aave, P0), F-069 (đề xuất vay, P1), F-079 (thực thi vay/trả, P2).
- ADR-012 sửa: token trên Sepolia là USDC test của Aave.

## 5. Ticket

| Ticket | Nội dung | Cut |
|---|---|---|
| SC-023 (#255) | Bản duyệt hai mức tiền | A |
| SC-024 (#256) | Aave supply/withdraw qua Safe T | A |
| SC-025 (#257) | Test Aave trên fork Sepolia | A |
| SC-026 (#258) | Vay/trả có Owner cấp quyền | P2 |
| ENG-013 (#259) | Công thức dự trữ và quyết định thanh khoản | A |
| ENG-014 (#260) | Đề xuất vay | B |
| EXE-014 (#261) | Chu kỳ thanh khoản | A |
| WEB-026 (#262) | Thẻ vị thế quỹ | A |
| WEB-027 (#263) | Màn hình đề xuất vay | B |
| DEV-012 (#264) | Cổng cấu hình trong CI | A |
| MDT-011 (#265) | Quyền vay/trả qua quản trị | P2 |

Sửa thêm 35 ticket (struct 13 trường, đọc Aave, mã lý do mới, D1–D10, B0…). Tổng 244 ticket. Chi tiết theo module: mục 15 trong các tab 17–35.
