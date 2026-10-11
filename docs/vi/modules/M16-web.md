# M16 · Ứng dụng web

**Nguồn chuẩn:** `docs/modules/web/README.md` · **Trạng thái:** Chi tiết — quyết định đã chốt (trưởng nhóm ủy quyền cho tech lead, 11/10/2026) · **ADR:** ADR-010, ADR-013

## 1. Mục đích và ranh giới

Web là nơi **con người quyết định và ký**, và nơi họ **thấy chính xác agent đang làm gì và vì sao**. Web không giữ bí mật và không có luật nghiệp vụ: mọi số liệu và quyết định đến từ API; mọi chữ ký được tạo trong ví của chính người dùng trên dữ liệu do server dựng.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Mọi màn hình dưới đây, kết nối ví, SIWE, ký EIP-712 (bản duyệt, SafeTx), gửi `execTransaction` của Safe | App di động; ngôn ngữ ngoài tiếng Anh (chuỗi đã tách cho vi/zh Later) |
| Cập nhật trực tiếp qua SSE | Bảng quản trị nền tảng (Later) |
| Chuẩn truy cập AA cho luồng chính, giao diện 390 px cho duyệt và thông báo | |

## 2. Feature, yêu cầu

F-130 (FR-915), F-131 (FR-916, FR-313), F-132 (FR-917, BR-057), F-133 (FR-918), F-134 (FR-919), F-135 (FR-920); giao diện cho F-001–F-005, F-010–F-026, F-030–F-038, F-066, F-090, F-100, F-140/141, F-058; NFR-UX-01…05.

## 3. Bản đồ màn hình

| Route | Màn hình | Vai trò | Ticket |
|---|---|---|---|
| `/login`, `/verify` | Magic link | công khai | WEB-002 |
| `/orgs`, `/o/:org/onboarding` | Chọn/tạo tổ chức, checklist | mọi người | WEB-002 |
| `/me/wallets` | Liên kết ví (SIWE) | mọi người | WEB-003 |
| `/o/:org/treasuries/new` | Wizard: chain/tài sản → Safe → giao dịch quản trị module → coverage → Guardian Safe | OWN, ADM | WEB-004 |
| `/o/:org/t/:t` | Dashboard: số dư so buffer/target, ngân sách, coverage, mandate, hàng đợi, dự báo, hoạt động, banner | mọi người | WEB-010, 019, 021 |
| `/o/:org/t/:t/mandate` | Soạn mandate: form, tóm tắt, diff (lỏng/chặt), tạo giao dịch quản trị | OWN (sửa) | WEB-005 |
| `/o/:org/t/:t/payees` | Vendor & payee: đề xuất, sàng lọc, xác minh ngoài kênh, giao dịch đăng ký, đếm ngược cooling | OPR, OWN | WEB-006 |
| `/o/:org/governance` | Hộp ký giao dịch quản trị: lệnh giải mã, tóm tắt, ký SafeTx, thực thi | OWN | WEB-025 |
| `/o/:org/requests`, `/new`, `/:r` | Danh sách, form nhập tay, chi tiết (phiên bản, cờ, bản duyệt, timeline, hủy / hủy on-chain) | OPR | WEB-007 |
| `/o/:org/requests/upload`, `/import` | Upload + soát trích xuất (đặt cạnh tài liệu), nhập CSV | OPR | WEB-008, 020 |
| `/o/:org/approvals` | Hộp duyệt: tài liệu, trường, so lịch sử vendor, cờ + xác nhận, typed data, ký | APR | WEB-009 |
| `/o/:org/t/:t/plans/:p` | Thẻ plan + panel "Vì sao" + timeline trực tiếp | mọi người | WEB-011, 012 |
| `/o/:org/review` | Bảng review & ngoại lệ (hành động theo vai trò, giao dịch cấp ngoại lệ, chấp nhận phí) | theo vai trò | WEB-013, 024 |
| `/o/:org/reconciliation` | Bảng đối soát, khớp/chênh lệch, xuất file, tải bằng chứng, link EAS | FIN | WEB-014 |
| `/o/:org/t/:t/settings/fees` | Đề xuất chính sách phí → Chấp nhận | OWN | WEB-024 |
| `/o/:org/members` | Thành viên, vai trò, lời mời, solo mode | ADM, OWN | WEB-017 |
| `/o/:org/metrics` | Chỉ số vận hành và tiết kiệm so B1 | OWN, FIN | WEB-018 |
| Panel Copilot | Chat có trích dẫn, nhãn "Giải thích của AI" | mọi người | WEB-016 |
| Chuông thông báo | Chưa đọc, link sâu, trực tiếp | mọi người | WEB-015 |

## 4. Kiến trúc client

React 18 + Vite + TypeScript; React Router; TanStack Query (sự kiện SSE làm mới cache theo entity); Tailwind + shadcn/ui; wagmi v2 + viem + RainbowKit (chain Sepolia; local Anvil); client OpenAPI sinh tự động (`make openapi`); Recharts; Playwright. Không có store toàn cục ngoài auth/tổ chức và tùy chọn giao diện.

## 5. Trạng thái và câu chữ (NFR-UX-04)

| Trạng thái backend | Câu chữ trên giao diện |
|---|---|
| Submitted / Pending | "Đã gửi — đang chờ mạng" |
| Confirmed (chưa xác minh) | "Đã xác nhận on-chain — đang kiểm" |
| Verified / Paid | "Đã trả · 3 xác nhận" (+ "Chốt" khi finalized) |
| Unknown | "Đang kiểm tra chain — sẽ không gửi khoản chi mới" |
| Yêu cầu pause / pause có hiệu lực | "Đang tạm dừng…" / "Đã tạm dừng on-chain" |
| Coverage PARTIAL đã xác nhận | "Đã tắt chế độ bảo vệ — module khác có thể chuyển tiền" |
| Văn bản AI | luôn trong khung **Giải thích của AI**; lý do của validator ghi **Quyết định policy** |

Không bao giờ ghi "an toàn", "xong" hay "đảm bảo" khi chưa xác minh. Số tiền luôn kèm ký hiệu + mạng; tài sản TEST có nhãn.

## 6. Tương tác ví

| Việc | Cách | Nguồn dữ liệu |
|---|---|---|
| Liên kết ví | `signMessage` (SIWE) | nonce của server |
| Duyệt request | `signTypedData` (PaymentApproval) | `GET approval-typed-data` (server dựng; trường hiển thị = object được ký) |
| Ký quản trị | `signTypedData` (SafeTx) | `GET governance-txs/{g}` |
| Thực thi quản trị | `sendTransaction` tới Safe (`execTransaction`) | `GET exec-call` |
| Hủy on-chain | `sendTransaction` `cancelRequest` | `GET cancel-tx` |
| Guardian pause (không có sentinel) | `sendTransaction` tới Guardian Safe | phản hồi `/pause` |

Sai mạng → chặn và nhắc chuyển mạng. Người dùng từ chối trong ví → không đổi trạng thái, hiện thông báo.

## 7. Luồng chính

Duyệt: hộp duyệt → chi tiết → xác nhận cờ HIGH (ghi chú) → "Xem lại thứ bạn ký" (bảng typed data) → ký → gửi approve → Approved. Quản trị: thông báo → mục trong hộp → lệnh giải mã + diff → ký (n/ngưỡng) → owner cuối bấm Thực thi → trạng thái cập nhật qua SSE. Thực thi: thẻ plan → các bước cập nhật trực tiếp qua SSE kèm link explorer.

## 8. Luật ở client

Không có luật nào mang tính quyết định. Kiểm ở client chỉ để trải nghiệm (số lẻ, trường bắt buộc), lặp lại lỗi API. Chuyển số tiền hiển thị ↔ base unit theo số lẻ của tài sản bằng bigint, không dùng số thực.

## 9. Cấu hình

`VITE_API_URL`, `VITE_CHAIN_ID`, `VITE_WALLETCONNECT_ID`; URL explorer lấy từ `/chains`. CSP: `default-src 'self'`; connect-src gồm API, RPC, WalletConnect; không script inline.

## 10. Bảo mật

Typed data hiển thị = object đưa vào ví (có unit test); bundle không có bí mật; header CSRF khi ghi; cookie httpOnly; CSP; audit dependency trong CI; văn bản hóa đơn hiển thị như chữ thường (không HTML).

## 11. Tình huống lỗi

API lỗi → màn hình lỗi có thử lại; SSE đứt → tự nối lại bằng Last-Event-ID, rồi hỏi định kỳ 10 giây; ví từ chối → không đổi gì; ETag cũ → "Có người vừa sửa, tải lại".

## 12. Kế hoạch test

Test component cho hiển thị typed data và chuyển đổi số tiền; Playwright luồng chính (WEB-023) với ví giả trên Anvil; axe cho duyệt/review/dashboard; kiểm 390 px; checklist câu chữ trạng thái.

## 13. Ticket theo thứ tự

WEB-001 → 002 → 003 → 004 → 025 → 005 → 006 → 007 → 008 → 009 → 010 → 011 → 012 → 013 → 019 → 014 → 024 → 015 → 016 → 017 → 018 → 020 → 021 → 022 → 023.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M16-D1 | Server dựng mọi object được ký; giao diện hiển thị đúng object đó. |
| M16-D2 | Ký giao dịch quản trị ngay trong app (WEB-025); link Safe{Wallet} là tùy chọn. |
| M16-D3 | Ngoại lệ cấp qua giao dịch quản trị, không qua EIP-712 (đã sửa WEB-013). |
| M16-D4 | Bảng câu chữ §5 là bắt buộc. |
| M16-D5 | Văn bản AI luôn có nhãn; lý do validator là bản chính thức. |
| M16-D6 | Chuyển đổi số tiền bằng bigint; không dùng số thực. |
| M16-D7 | SSE làm mới cache TanStack Query; dự phòng hỏi định kỳ 10 giây. |
| M16-D8 | M1 chỉ tiếng Anh, chuỗi đã tách. |
| M16-D9 | Chain Sepolia (local Anvil); sai mạng thì chặn và nhắc. |
| M16-D10 | CSP chặt, không script inline. |
| M16-D11 | Màn hình phí hiển thị đề xuất của hệ thống; Owner chấp nhận hoặc chọn mức khác. |
| M16-D12 | Banner hủy on-chain giữ tới khi xác nhận. |
| M16-D13 | Guardian pause dùng giao dịch từ ví khi không có sentinel. |
| M16-D14 | Dùng Recharts cho biểu đồ; không thêm thư viện khác. |
