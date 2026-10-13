# M16 · Web — Plan refactor giao diện

**Trạng thái:** Đề xuất, chờ duyệt · **Ngày:** 2026-10-11 · **Code:** `apps/web` · **Spec gốc:** [README.md](README.md)
**Phạm vi:** thay toàn bộ lớp `features/showcase` bằng UI thật theo từng màn hình, phủ 26 issue `area:frontend` (#208–#229, #250, #252, #262, #263).

---

## 1. Vì sao UI hiện tại trông như "AI gen"

Số liệu đo trực tiếp trên `apps/web/src` (commit `61a3044`):

| Triệu chứng | Bằng chứng | Hậu quả |
|---|---|---|
| Một template vẽ mọi màn hình | 31 màn hình đều là dữ liệu `ScreenSpec`, render qua 6 `kind` (`dashboard`, `table`, `form`, `timeline`, `settings`, `cards`) trong `screen-page.tsx` (668 dòng) | Approval inbox, mandate editor, governance đều ra cùng một bố cục "tiêu đề + 4 thẻ số + bảng". Không màn nào có hình dạng riêng của nghiệp vụ |
| Form giả | `FormSection` vẽ `<span>` trông như input; `Toggle` không đổi trạng thái; tab luôn chọn tab đầu; ô search không lọc gì | Không có tương tác thật, không có trạng thái loading / lỗi / rỗng |
| Chữ quá nhỏ | 74 chỗ dùng `text-[9px]`, `text-[10px]`, `text-[11px]`; chỉ 3 chỗ 12px | Khó đọc, không đạt WCAG AA (NFR-UX-01) |
| Không có design token | 119 mã màu hex khác nhau viết thẳng trong class; 8 giá trị `rounded-[Npx]` khác nhau; `Button` trong `components/ui` (xanh emerald) không được màn nào dùng | Không thể đổi theme, không có dark mode, mỗi component một kiểu |
| Trang trí thay cho thông tin | Sparkline giống nhau trên mọi thẻ số, gradient nền, bóng đổ màu xanh, hover nhấc thẻ lên, thanh gradient chạy dưới thẻ | Đúng "chữ ký" của UI sinh tự động: nhiều hiệu ứng, ít nội dung |
| Điều hướng kiểu catalogue | Sidebar 31 mục có đánh số `01…31`, thêm `<select>` "Jump to screen", nhóm "Future concepts" 8 màn hình | Đây là bộ sưu tập mockup, không phải sản phẩm. Người dùng không biết việc của mình nằm ở đâu |
| Route không theo spec | Mọi thứ là `/app/:screenId`; spec §3 yêu cầu `/o/:org/t/:t/...` | Không deep-link được tới một request, plan hay governance tx cụ thể |
| Vi phạm quy tắc hiển thị | Số tiền là chuỗi cứng (`'163,000 USDC TEST'`); không có lớp format chung | Không đảm bảo NFR-UX-03 (symbol + network + nhãn TEST) và M16-D6 (bigint) |

Kết luận: không thể "sửa cho đẹp" trên nền hiện tại. Cần bỏ renderer chung và viết từng màn hình bằng component riêng.

## 2. Tham khảo bên ngoài và thứ mình lấy

| Nguồn | Điều học được | Áp dụng vào TreasuryPilot |
|---|---|---|
| **Linear** (bài "How we redesigned the Linear UI") | Giảm nhiễu ở khung ngoài (sidebar, header, panel), tăng mật độ và phân cấp; không phải phần tử nào cũng có cùng trọng lượng thị giác; theme sinh từ 3 biến (base, accent, contrast); Inter Display cho heading, Inter cho body | Khung app phẳng, viền mảnh, không bóng đổ. Token màu sinh từ ít biến. Một cấp chữ rõ ràng |
| **Mercury** | Hai tầng: vị thế tài chính ở trên, điều khiển vận hành ở dưới một cấp. Màu chức năng tách hẳn màu trang trí; đỏ và vàng chỉ dùng cho lỗi và cảnh báo. Bảng giao dịch dày, lọc được, là bề mặt làm việc chính | Dashboard mở đầu bằng "tiền đang ở đâu", không phải 4 thẻ số ngang hàng. Màu trạng thái chỉ xuất hiện khi có trạng thái |
| **Ramp Bill Pay** | OCR chạy 30–60 giây, chạy một lần; người dùng sửa thì dừng OCR; lịch sử, mã hoá và phê duyệt nằm trong một view; trạng thái "đang chờ" hiện ngay sau khi gửi | Màn extraction review có trạng thái "đang đọc hoá đơn" rõ ràng, khoá form tới khi xong. Trường AI điền có đánh dấu nguồn và độ tin cậy |
| **Safe{Wallet}** + hướng dẫn kiểm tra giao dịch của Safe | Người ký phải thấy `to`, `value`, `data`, `operation`, `nonce` và đối chiếu với ví. `operation = 1` (delegatecall) phải cảnh báo. Nguyên tắc: "không kiểm chứng được thì đừng ký" | Component `TypedDataTable` hiển thị đúng object đưa vào `signTypedData` (M16-D1). Governance detail có khối "Decoded calls" + ngưỡng `n/threshold` + cảnh báo delegatecall |
| **Multisig Inspector, Fordefi** | Hàng đợi chia nhóm: chờ chữ ký, sẵn sàng thực thi, lịch sử. Hiển thị ý định đã giải mã thay vì `execTransaction` thô | Governance inbox chia 3 nhóm đúng như vậy |
| **Stripe Dashboard** | Số tiền căn phải; header bảng dính; badge trạng thái dùng icon + màu nhạt, không chỉ màu; chữ và nền badge là hai token riêng để đủ tương phản | Quy ước bảng ở §5.3; `StatusBadge` luôn có icon hoặc chấm + chữ |

Lưu ý về độ tin cậy: phần Linear, Safe và Ramp lấy từ tài liệu chính chủ. Phần Mercury và Stripe là phân tích của bên thứ ba, dùng làm định hướng chứ không phải đặc tả.

Nguồn:
[Linear redesign](https://linear.app/now/how-we-redesigned-the-linear-ui) ·
[Mercury design breakdown](https://www.925studios.co/blog/mercury-design-breakdown) ·
[Ramp Bill Pay OCR](https://support.ramp.com/hc/en-us/articles/45686841394579-Ramp-Bill-Pay-OCR) ·
[Safe transaction checks](https://help.safe.global/articles/2485383995-how-to-perform-basic-transactions-checks-on-safewallet) ·
[Multisig Inspector](https://multisiginspector.quillaudits.com/docs/transaction-inspector) ·
[Fordefi Safe transactions](https://docs.fordefi.com/user-guide/manage-transactions/safe-transactions) ·
[shadcn/ui Tailwind v4 note](https://ui.shadcn.com/docs/tailwind-v4)

## 3. Hướng thiết kế

**Một câu:** sổ cái yên tĩnh, dày thông tin, nơi con số và trạng thái on-chain là nhân vật chính; AI luôn nằm trong khung có nhãn.

| Nguyên tắc | Cụ thể |
|---|---|
| Phẳng, viền mảnh | Bề mặt tách nhau bằng viền 1px và chênh nền rất nhẹ. Bóng đổ chỉ dùng cho lớp nổi (popover, dialog, sheet). Không gradient, không hover nhấc thẻ |
| Một màu nhấn | Nền trung tính (zinc). Accent xanh lục đậm dùng cho hành động chính và mục đang chọn. Xanh dương hiện tại bỏ |
| Màu trạng thái có nghĩa | `success`, `warning`, `danger`, `info`, `neutral`. Chỉ dùng khi có trạng thái thật. Mỗi tone có cặp `bg` / `fg` / `border` riêng, đạt 4.5:1 |
| Chữ đọc được | Body 14px, bảng 13px, chú thích 12px là nhỏ nhất. Cấm `text-[Npx]` bằng ESLint |
| Số là số | Số tiền, địa chỉ, hash dùng IBM Plex Mono + `tabular-nums`, căn phải trong bảng |
| Bo góc nhất quán | `sm` 4px (badge, input nhỏ), `md` 6px (button, input), `lg` 8px (card, dialog). Không giá trị nào khác |
| Chuyển động có lý do | 120–180ms cho mở/đóng lớp nổi và đổi trạng thái timeline. Tôn trọng `prefers-reduced-motion` (đã có trong `styles.css`) |
| Dark mode từ đầu | Token định nghĩa cho cả `:root` và `.dark`; `darkMode: ['class']` đã bật sẵn |

**Token** (thay khối `:root` trong `src/styles.css`, mở rộng `tailwind.config.ts`):

- Bề mặt: `background`, `surface`, `surface-muted`, `border`, `border-strong`
- Chữ: `foreground`, `muted-foreground`, `subtle-foreground`
- Nhấn: `primary`, `primary-foreground`, `ring`
- Trạng thái: `{success|warning|danger|info}` × `{DEFAULT|foreground|muted|border}`
- Riêng nghiệp vụ: `ai` (khung "AI explanation"), `policy` (khung "Policy decision"), `test-asset` (nhãn TEST)
- Cỡ chữ: `xs 12/16`, `sm 13/20`, `base 14/20`, `lg 16/24`, `xl 20/28`, `2xl 24/32`, `display 32/40`

**Font:** IBM Plex Sans + IBM Plex Mono, tự host qua `@fontsource` (CSP `default-src 'self'` không cho gọi Google Fonts, M16-D10).

## 4. Thư viện

Giữ nguyên: React 18.3, Vite 8, **Tailwind 3.4**, React Router 6, TanStack Query, RHF + Zod, wagmi + viem + RainbowKit, Recharts (M16-D14), lucide-react. Không nâng Tailwind 4 / React 19 trong đợt này: shadcn xác nhận project v3 + React 18 vẫn được hỗ trợ, và nâng cấp chỉ thêm rủi ro trước hạn nộp.

| Thêm | Bản | Dùng cho | Ghi chú |
|---|---|---|---|
| shadcn/ui (style `new-york`, đã có `components.json`) + Radix | CLI mới nhất | Toàn bộ primitive: dialog, sheet, dropdown, popover, tooltip, tabs, select, checkbox, switch, form, table, sidebar, breadcrumb, skeleton, alert, badge, progress, scroll-area, separator, accordion, calendar, chart | Code copy vào `components/ui`, sửa theo token của mình |
| `tailwindcss-animate` | 1.0.7 | Animation cho component shadcn | Bản cho Tailwind 3; `tw-animate-css` chỉ dành cho v4 |
| `@tanstack/react-table` | 9.x | Mọi bảng: sort, filter, chọn dòng, ẩn cột, phân trang | |
| `cmdk` | 1.1 | Command palette `⌘K` thật (thay ô search giả và `<select>` nhảy màn) | |
| `sonner` | 2.x | Toast (ví từ chối, lưu thành công, lỗi API) | |
| `vaul` | 1.1 | Bottom sheet trên mobile cho approval và notifications (NFR-UX-02, 390px) | |
| `react-resizable-panels` | 4.x | Chia đôi tài liệu / trường dữ liệu ở extraction review và approval detail | |
| `react-dropzone` | 20.x | Upload hoá đơn, CSV | |
| `react-day-picker` + `date-fns` | 10.x / 4.x | Chọn ngày đến hạn, khoảng ngày lọc | |
| `motion` | 14.x | Chuyển trạng thái timeline, đổi layout danh sách | Dùng tiết kiệm |
| `i18next` + `react-i18next` | 26.x / 17.x | Tách chuỗi (NFR-UX-05, M16-D8) | Chỉ `en`; đặt bảng wording §5 của spec vào đây |
| `msw` | 3.x | Mock API theo `docs/API_SPEC.md` cho dev, test và demo | Xem §6 |
| `@fontsource-variable/geist`, `-geist-mono` | 5.x | Font | |
| `@playwright/test`, `@axe-core/playwright` | 1.64 / 4.13 | #229, #228 | |

Không dùng: `react-pdf` (bản 11 yêu cầu React 19) — xem PDF bằng `<object>` gốc của trình duyệt, ảnh thì `<img>`; thư viện chart thứ hai; state manager toàn cục.

## 5. Kiến trúc code

### 5.1 Cấu trúc thư mục

```
src/
  app.tsx                      route tree theo spec §3
  styles.css                   token
  components/
    ui/                        primitive shadcn (không chứa nghiệp vụ)
    layout/                    AppShell, AppSidebar, TopBar, PageHeader, CommandMenu
    data/                      DataTable, Toolbar, FilterChips, Pagination, DescriptionList
    feedback/                  EmptyState, ErrorState, StaleBanner, StatusBanner, Skeletons
    domain/                    component nghiệp vụ dùng chung (§5.3)
  features/
    auth/  orgs/  wallets/  treasury-setup/  dashboard/  mandate/  payees/
    governance/  requests/  extraction/  approvals/  plans/  review/
    reconciliation/  fees/  members/  metrics/  copilot/  notifications/
      api.ts                   query + mutation hook (TanStack Query)
      components/              component riêng của feature
      routes/                  page component
      *.test.tsx
  lib/
    api/                       client openapi-fetch, query keys, lỗi chuẩn hoá
    money/                     bigint <-> hiển thị (M16-D6)
    chain/                     explorer link, rút gọn địa chỉ, chain guard
    sse/                       EventSource + Last-Event-ID + fallback polling 10s
    i18n/                      en.json, status-wording.ts
  mocks/                       handler MSW + fixture (thay features/showcase/data)
```

Xoá: `features/showcase/**`, `components/app-layout.tsx` (không dùng), nhóm "Future concepts" và `dashboard-expanded` (không thuộc issue nào).

### 5.2 Khung ứng dụng

Sidebar theo **việc cần làm**, không theo danh sách màn hình:

```
[Org switcher ▾]  [Treasury switcher ▾]
Overview
Inbox            Approvals (3) · Governance (1) · Review (2)
Payments         Requests · Plans · Reconciliation
Controls         Mandate · Payees · Fees
Insights         Metrics
──────────
Settings         Members · Wallets
```

- Mục hiển thị theo role (OWN, ADM, OPR, APR, FIN); số đếm lấy từ API.
- Top bar: breadcrumb, `⌘K`, trạng thái ví + mạng, chuông thông báo, nút Copilot, menu người dùng.
- `StatusBanner` toàn cục ngay dưới top bar: Paused, Pausing, coverage PARTIAL, sai mạng, snapshot cũ, cancel on-chain đang chờ (M16-D12).
- Copilot là panel bên phải mở từ mọi trang (spec: "Copilot panel (global)"), không phải một trang riêng.
- Mobile: sidebar thành sheet; approvals và notifications có layout 390px riêng.

### 5.3 Component nghiệp vụ dùng chung (`components/domain`)

Mỗi component có đủ trạng thái `loading / empty / error / ready`, có test, và là nơi duy nhất thực thi quy tắc hiển thị của nó.

| Component | Hợp đồng | Quy tắc gắn kèm |
|---|---|---|
| `Amount` | `value: bigint`, `asset`, `network`, `size` | Luôn có symbol + network; nhãn `TEST` cho tài sản test (NFR-UX-03); mono, tabular |
| `AmountInput` | RHF field, trả `bigint` | Chuyển đổi bằng số nguyên theo decimals (M16-D6) |
| `Address` / `TxHash` | rút gọn, copy, link explorer, tên payee nếu biết | Explorer URL từ `/chains` |
| `StatusBadge` | `status` (enum backend) | Chữ lấy từ bảng wording §5; không bao giờ tự viết "safe", "done" (M16-D4) |
| `AiExplanation` / `PolicyDecision` | nội dung + nguồn | Hai khung khác nhau về màu, icon, nhãn; text render thuần, không HTML (M16-D5) |
| `TypedDataTable` | `typedData` từ server | Render đúng object truyền cho `signTypedData`; có unit test so khớp (M16-D1) |
| `SignButton` | `typedData`, `onSigned`, `disabledReason` | Chặn khi sai mạng / chưa nối ví / chưa ack flag; ví từ chối thì toast, không đổi state |
| `ChainGuard` | bọc hành động ví | Sai mạng → prompt chuyển mạng dạng chặn (M16-D9) |
| `SignatureProgress` | `signed`, `threshold`, `owners[]` | Avatar người đã ký + `n/threshold` |
| `DecodedCalls` | `calls[]` | Tên hàm, tham số, cảnh báo delegatecall |
| `DiffView` | `before`, `after`, `direction` | Đánh dấu looser / stricter cho mandate |
| `FlagList` | `flags[]`, `onAcknowledge` | Flag HIGH bắt buộc ghi chú trước khi ký |
| `Timeline` / `TimelineStep` | `steps[]` | Unknown = "Checking the chain", không bao giờ tô đỏ như failed |
| `DocumentViewer` | `fileUrl`, `mime` | PDF / ảnh, zoom, trang |
| `ConfidenceField` | field + nguồn AI + độ tin cậy | Đánh dấu trường AI điền, trường người sửa |
| `CountdownChip` | `until` | Cooling period của payee |
| `KeyValueList`, `StatTile`, `MeterBar` | hiển thị số | `MeterBar` cho balance vs buffer vs target, budget vs limit |

### 5.4 Quy ước bảng (`DataTable`)

Header dính; số tiền căn phải, mono; cột đầu là định danh, đậm vừa; dòng cao 44px (40px ở chế độ compact); click dòng mở chi tiết; toolbar gồm search, filter dạng chip, ẩn/hiện cột; filter và phân trang nằm trên URL; trạng thái rỗng nói rõ bước tiếp theo; skeleton đúng số cột.

## 6. Dữ liệu: điểm phải nói thẳng

Backend hiện chỉ có `/health` và `/v1/health` trong `openapi.json`. Cả 26 issue frontend đều phụ thuộc endpoint chưa tồn tại (IDN, INV, MDT, EXE, CHR, NTF…).

Cách làm đề xuất:

1. Viết type và handler **MSW** theo đúng 76 endpoint trong `docs/API_SPEC.md`. Component chỉ gọi hook trong `features/*/api.ts`, không biết mình đang chạy trên mock.
2. Fixture chuyển từ `features/showcase/data/*` sang `mocks/fixtures`, đổi số tiền sang base unit dạng chuỗi.
3. SSE mock phát sự kiện đổi trạng thái để timeline chạy thật trong demo.
4. Ví: SIWE và EIP-712 ký bằng ví thật (wagmi), mock chỉ thay phần verify phía server.
5. Khi backend có endpoint: chạy `generate:api`, bỏ handler tương ứng. Bật/tắt bằng `VITE_API_MOCK`.

Hệ quả: sau đợt này, mỗi issue đạt mức **"UI hoàn chỉnh trên contract mock"**. Các tiêu chí như "Values match the API" (#216), "Numbers equal the engine output" (#262), "E2E on Anvil" (#218, #229) chỉ kiểm chứng được khi backend và contract sẵn sàng. Đề xuất: không đóng issue, mà tick phần UI và ghi chú phần còn chờ backend.

## 7. Từng màn hình ↔ issue

| # | Ticket | Route | Bố cục và component chính | Điểm khác hẳn bản cũ |
|---|---|---|---|---|
| #208 | WEB-002 | `/login`, `/verify`, `/orgs`, `/o/:org/onboarding` | Login một cột, form magic link, trạng thái "check your email"; danh sách org + tạo org; checklist có tiến độ và link tới bước | Bỏ hero hai cột và mật khẩu demo cứng; checklist do API điều khiển |
| #209 | WEB-003 | `/me/wallets` | Danh sách ví đã liên kết, nút Connect (RainbowKit), bước ký SIWE, lỗi `ADDRESS_LINKED_ELSEWHERE` | Kết nối ví thật |
| #210 | WEB-004 | `/o/:org/treasuries/new` | Wizard 5 bước có stepper dọc: chain/asset → Safes → module governance tx → coverage → Guardian Safe; mỗi bước có tóm tắt bên phải | Form thật, validate Zod, lưu nháp |
| #250 | WEB-025 | `/o/:org/governance` | Danh sách 3 nhóm (chờ ký / sẵn sàng thực thi / lịch sử) + panel chi tiết: `DecodedCalls`, tóm tắt, `DiffView`, `SignatureProgress`, `TypedDataTable`, Sign / Execute; trạng thái Superseded, Failed | Từ "timeline" chung thành inbox ký thật |
| #211 | WEB-005 | `/o/:org/t/:t/mandate` | Trái: form theo nhóm (limits, buffers, payees, thời hạn). Phải: tóm tắt bằng lời + `DiffView` looser/stricter dính theo cuộn. Cuối: "Create governance transaction" | Thay danh sách settings tĩnh |
| #212 | WEB-006 | `/o/:org/t/:t/payees` | `DataTable` + sheet đề xuất payee; cột screening, OOB verification, `CountdownChip` cooling; hành động đăng ký tx | |
| #213 | WEB-007 | `/o/:org/requests`, `/new`, `/:r` | List có filter trạng thái; form nhập tay với `AmountInput`; trang chi tiết: revisions, flags, approvals, timeline, cancel / cancel on-chain | Trang chi tiết có route riêng |
| #214 | WEB-008 | `/o/:org/requests/upload` | Dropzone → trạng thái "đang đọc" → chia đôi resizable: `DocumentViewer` trái, `ConfidenceField` phải; cảnh báo văn bản dạng chỉ thị trong tài liệu | Bỏ hoá đơn giả vẽ bằng div |
| #226 | WEB-020 | `/o/:org/requests/import` | Upload CSV → map cột → preview có lỗi theo dòng → xác nhận | |
| #215 | WEB-009 | `/o/:org/approvals` | List trái + chi tiết phải (mobile: list → trang chi tiết + `vaul`). Chi tiết: tài liệu, trường, diff so lịch sử vendor, `FlagList` có ack, so sánh trùng lặp cạnh nhau, lựa chọn **early vs standard**, "Review what you sign" (`TypedDataTable` 13 trường), `SignButton`, reject / request changes, thông báo maker-checker | Luồng ký EIP-712 thật; nút ký khoá tới khi ack flag HIGH |
| #216 | WEB-010 | `/o/:org/t/:t` | Hàng 1: vị thế (tiền ở đâu) + `MeterBar` balance vs buffer vs target. Hàng 2: budget hôm nay vs limit, coverage, mandate. Hàng 3: hàng đợi (link tới Inbox), hoạt động gần đây. `StaleBanner` | Bỏ 4 thẻ số + sparkline trang trí |
| #262 | WEB-026 | (trong dashboard) | Position card: Safe USDC, aUSDC, pool liquidity, phân rã RequiredSafeReserve (thanh xếp chồng), AvailableForSupply, APY có nhãn testnet, hành động thanh khoản gần nhất kèm giải thích | |
| #263 | WEB-027 | `/o/:org/t/:t/borrow/:id` | So sánh withdraw vs borrow (2 cột chi phí), health factor trước/sau, lý do, dòng "no transaction without owner authorization" | |
| #227 | WEB-021 | (trong dashboard) | Runway chart (Recharts): đường dự báo + dải buffer + mốc hoá đơn đến hạn | Chart có trục và chú giải thật |
| #217 | WEB-011 | `/o/:org/t/:t/plans/:p` | Plan card: các bước theo thứ tự, số tiền, tiết kiệm dự kiến, badge nguồn planner (AI / RULE_BASED). Why panel: `PolicyDecision` (reason code) tách khỏi `AiExplanation`; binding constraints | |
| #218 | WEB-012 | (cùng trang plan) | `Timeline` sống qua SSE, wording §5, link explorer, kết quả verify, hiển thị hoàn thành một phần | SSE + reconnect + fallback polling |
| #219 | WEB-013 | `/o/:org/review` | Console 2 cột: hàng đợi theo loại (exception, review, fee) + chi tiết với hành động theo role; cấp exception qua governance tx (M16-D3) | |
| #225 | WEB-019 | (toàn cục) | `StatusBanner` + dialog Pause / Resume có xác nhận; "Pausing…" / "Paused on-chain"; fallback gửi tx tới Guardian Safe (M16-D13) | |
| #220 | WEB-014 | `/o/:org/reconciliation` | `DataTable` match / discrepancy, panel chi tiết, export, tải evidence, link EAS | |
| #252 | WEB-024 | `/o/:org/t/:t/settings/fees` | Đề xuất của hệ thống + preset, biểu đồ quan sát phí, nút Accept (M16-D11) | |
| #221 | WEB-015 | (chuông toàn cục) | Popover (desktop) / sheet (mobile): chưa đọc, nhóm theo ngày, deep link, cập nhật sống | Không còn là trang "cards" |
| #222 | WEB-016 | (panel toàn cục) | Chat có trích dẫn nguồn, mọi câu trả lời trong khung "AI explanation", gợi ý câu hỏi theo trang đang mở | |
| #223 | WEB-017 | `/o/:org/members` | `DataTable` thành viên, dialog mời, sửa role, solo mode | |
| #224 | WEB-018 | `/o/:org/metrics` | Chỉ số vận hành + tiết kiệm so với B1; chart theo quy ước dataviz | |
| #228 | WEB-022 | — | axe trên approve / review / dashboard; kiểm 390px; checklist wording | |
| #229 | WEB-023 | — | Playwright happy path: login → upload → approve → plan → paid | Chạy trên MSW trước; Anvil khi contract sẵn sàng |

## 8. Thứ tự thực hiện

Mỗi giai đoạn là một PR chạy được, có test, `pnpm lint && pnpm typecheck && pnpm test` xanh.

| GĐ | Nội dung | Issue | Kết quả kiểm chứng |
|---|---|---|---|
| 0 | Nền tảng: token, font, primitive shadcn, ESLint cấm `text-[Npx]` và màu hex, i18n, `lib/money`, `lib/chain`, MSW khung | — | Trang `/dev/components` hiển thị mọi primitive ở light + dark |
| 1 | Khung app: route tree theo spec, AppShell, sidebar theo role, top bar, `⌘K`, `StatusBanner`, component `domain` và `data` | #225 (phần banner) | Điều hướng đủ mọi route với trang rỗng có skeleton |
| 2 | Vào cửa: login, org, onboarding, ví, setup wizard | #208, #209, #210 | Người dùng mới đi từ login tới treasury đã tạo |
| 3 | Luồng thanh toán lõi: requests, upload + extraction, approvals + ký | #213, #214, #215 | Tạo request → ký EIP-712 → Approved |
| 4 | Treasury và thực thi: dashboard, position card, plan + Why, timeline sống | #216, #262, #217, #218 | Plan chạy tới "Paid · 3 confirmations" qua SSE mock |
| 5 | Kiểm soát: governance inbox, mandate, payees, pause/resume | #250, #211, #212, #225 | Sửa mandate → governance tx → ký → execute |
| 6 | Tier B: review console, reconciliation, fees, borrow | #219, #220, #252, #263 | |
| 7 | Sau submission: notifications, copilot, members, metrics, CSV, runway | #221, #222, #223, #224, #226, #227 | |
| 8 | Chất lượng: a11y + responsive, Playwright, xoá `features/showcase` | #228, #229 | axe không lỗi trên 3 luồng lõi; E2E xanh |

Giai đoạn 0–5 phủ toàn bộ Tier A của frontend. Thứ tự 2–5 khớp chuỗi phụ thuộc trong spec §13, trừ việc đưa governance (#250) xuống cùng mandate để luồng demo thanh toán chạy được sớm hơn.

## 9. Định nghĩa "xong" cho mỗi màn hình

- Đủ 4 trạng thái: loading (skeleton), empty (có hướng dẫn bước tiếp), error (có retry), ready.
- Mọi số tiền qua `Amount`; mọi trạng thái qua `StatusBadge`; mọi chuỗi qua i18n.
- Dùng được bằng bàn phím; focus nhìn thấy; tương phản AA.
- Chạy ở 1280px và 390px.
- Có test component cho logic riêng (ack flag khoá nút ký, typed data hiển thị = object ký, chuyển đổi bigint).
- Không còn `text-[Npx]`, màu hex, hay `rounded-[Npx]` trong file.

## 10. Rủi ro và quyết định cần chốt

| Vấn đề | Đề xuất | Cần ai quyết |
|---|---|---|
| Backend chưa có endpoint | Làm trên MSW theo `API_SPEC.md`; giữ issue mở phần tích hợp | Project owner |
| Spec yêu cầu magic link; `SUBMISSION_CUT` có phương án chỉ dùng SIWE với role seed sẵn | Làm cả hai màn; bật magic link bằng cờ | Tech lead |
| Thay đổi màu thương hiệu (xanh dương → trung tính + xanh lục) | Duyệt trên trang `/dev/components` ở GĐ 0 trước khi làm màn hình | Project owner |
| 8 màn "Future concepts" và `dashboard-expanded` | Xoá khỏi app; nếu cần cho pitch thì giữ ảnh chụp trong `docs` | Project owner |
| Test hiện tại (`app.test.tsx`) bám vào chữ của UI cũ | Viết lại theo luồng mới ở GĐ 2 | — |
| Khối lượng: 26 issue ≈ 20 ngày công theo ước lượng ticket | Ưu tiên GĐ 0–5 trước 20/10; GĐ 6–8 sau | Tech lead |
