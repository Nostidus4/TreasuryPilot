# TreasuryPilot — Technical Report & Documentation Hub

> **Bản rà soát:** 16/10/2026 · **Code:** commit `50b1117` · **Phạm vi:** repo hiện tại, tài liệu [TreasuryPilot trên Google Docs](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit) (đặc biệt các tab 8, 11, 13, 36, 37) và tài liệu chuẩn trong repo. Đây là báo cáo kỹ thuật theo trạng thái quan sát được; các kết quả đo cũ được ghi rõ mốc thời gian và môi trường.

**TL;DR — TreasuryPilot làm gì?** Hệ thống nhận hóa đơn, yêu cầu người có thẩm quyền xác nhận nghĩa vụ thanh toán và ký duyệt đúng các trường tiền, sau đó dùng bộ lập kế hoạch để quyết định thời điểm trả, chuẩn bị thanh khoản giữa các Safe của cùng tổ chức, thực hiện qua module có giới hạn trên chain, theo dõi biên nhận và đối soát. AI giúp đọc chứng từ, đề xuất và giải thích; quyền chuyển tiền được kiểm bằng chữ ký người dùng, bộ policy xác định, signer riêng và hợp đồng thông minh.

**Cách đọc trạng thái:** **Có trong code** = đã thấy đường triển khai cụ thể; **có bằng chứng cục bộ** = có test hoặc báo cáo chạy local/fork; **cấu hình trên Sepolia** = có manifest đã khai báo/deploy nhưng không suy ra mọi luồng đã chạy end-to-end; **thiết kế/đang kiểm chứng** = tài liệu mô tả đích hoặc có thành phần rời, chưa đủ bằng chứng cho tuyên bố vận hành hoàn chỉnh. [README](../README.md) và một số báo cáo submission được viết ở revision cũ; khi chúng khác code hiện tại, báo cáo này ưu tiên code và artifact có ngày/revision rõ ràng.

## 01 · Bắt đầu

### 1.1 Bài toán và ranh giới sản phẩm

Đối tượng chính là finance/treasury operator, người duyệt và owner của doanh nghiệp chi trả bằng stablecoin. Vấn đề cốt lõi gồm: hóa đơn đã duyệt nhưng ví vận hành thiếu token/gas; việc chia tiền giữa các ví làm thủ công; người dùng muốn tự động hóa mà vẫn khóa người nhận, hạn mức và khoản dự phòng; bằng chứng thanh toán rời rạc, khó đối soát. Tài liệu nguồn phân vai: **con người quyết định có trả hay không; agent đề xuất cách và thời điểm; contract giới hạn hành động được phép**. [Tổng quan sản phẩm](vi/01-tong-quan.md) · [Google Docs, tab tổng quan](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.0).

Mốc M1 dùng tài sản thử nghiệm trên Sepolia; không nên hiểu thành sản phẩm thanh toán mainnet đã được kiểm toán. Bản v0.3 bổ sung supply/withdraw Aave V3 cho tiền dư, hai mức tiền đã duyệt khi trả sớm, và đề xuất vay. Code contract còn có đường borrow/repay với ủy quyền owner một lần; đó là năng lực kỹ thuật/P2, không đồng nghĩa luồng sản phẩm M1 tự vay. [Cập nhật v0.3](vi/37-cap-nhat-v03.md) · [technical documentation hiện có](submission/technical-documentation.md).

Trong vận hành, TreasuryPilot xử lý ba quyết định khác nhau: nghĩa vụ nào được phép trả, ví nào cần cấp thanh khoản, và thời điểm nào có lợi trong điều khoản đã duyệt. M1 là demo trên Sepolia với tài sản thử nghiệm; mô tả vay/Aave trong code cần được đọc như các entry point riêng, không phải bằng chứng rằng doanh nghiệp có thể tự động vay trong luồng mặc định.

**Câu hỏi kiểm chứng tiếp:** Có thể truy từ một invoice đã duyệt tới đúng wallet, mandate và contract đang bảo vệ giao dịch không? Bản demo có tuyên bố chức năng vay nào mà chưa được kiểm chứng bằng giao dịch?

### 1.2 Luồng giá trị từ đầu đến cuối

[![Từ yêu cầu thanh toán đến giao dịch đã xác minh](report_site/diagrams/payment-flow-vi.svg)](report_site/diagrams/payment-flow-vi.svg)

*Hình 01.1 — Luồng thanh toán đầu cuối · [Chỉnh sửa bằng draw.io](report_site/diagrams/payment-flow-vi.drawio).*

1. **Thiết lập:** tạo tổ chức và treasury, liên kết Safe T (quỹ) và Safe O1 (ví vận hành), cấu hình chain/asset, triển khai module, owner đặt mandate, payee, trần và floor.
2. **Nhận hóa đơn:** nhập tay, CSV/API hoặc tài liệu; lưu chứng từ riêng tư; trích trường/điều khoản; kiểm trùng và tín hiệu bất thường.
3. **Xác nhận và duyệt:** người dùng xác nhận trường quan trọng, maker-checker và cờ HIGH được xử lý ở backend, approver ký EIP-712 cho đúng request/payee/asset/số tiền/điều khoản.
4. **Lập kế hoạch:** snapshot chain + nghĩa vụ chưa trả; engine tính số thiếu, dự trữ và lịch; AI chỉ đề xuất trong tập lựa chọn hợp lệ; policy trả `ALLOW`, `NEEDS_APPROVAL` hoặc `BLOCK`.
5. **Thực thi:** ghi outbox, ký policy attestation, signer kiểm calldata và mô phỏng trạng thái mới, gửi các bước theo thứ tự; module trên chain kiểm lại quyền, hạn mức, floor, request/step đã dùng.
6. **Hậu kiểm:** tracker đọc receipt/state, verifier kiểm postcondition, reconciliation gắn giao dịch với request, audit/evidence xuất chứng cứ. Trường hợp `Unknown` phải được giải quyết trước retry.

Luồng trên là **chuỗi mục tiêu của toàn hệ thống**. Các cấu phần có code riêng; mức tích hợp thực tế phải được xác nhận bằng smoke/E2E và bằng chứng giao dịch của đúng môi trường. [Kiến trúc luồng](SYSTEM_ARCHITECTURE.md) · [worker tasks](../services/worker/src/treasurypilot_worker/tasks.py) · [execution API](../services/api/src/treasurypilot_api/execution/routes.py).

Một giao dịch hoàn chỉnh không chỉ là một lệnh `pay`: với số dư thấp, plan có thể cần `REFILL` từ Safe T sang Safe O1 rồi mới `PAY`. Hai bước có giới hạn và counter riêng; nếu refill thành công nhưng pay chưa được xác nhận, trạng thái là partial/unknown cần đối soát, không được suy ra hóa đơn đã thanh toán. Các mô tả từng bước trong sơ đồ là kiến trúc tích hợp; bằng chứng 30/30 thuộc Anvil, còn báo cáo reliability hiện ghi 0 run Sepolia.

**Câu hỏi kiểm chứng tiếp:** Với một request mẫu, có operation/step ID và receipt riêng cho REFILL lẫn PAY không? Sau timeout giữa hai bước, trạng thái UI và quy trình xử lý là gì?

### 1.3 Phân biệt các loại ví và quyền

| Thành phần | Vai trò | Quyền quan trọng |
|---|---|---|
| Safe T | Ví quỹ, chủ mandate và tài sản dự trữ | Owner/threshold đổi cấu hình, pause/revoke, cấp ngoại lệ; giữ aToken Aave. |
| Safe O1/O2 | Ví chi của tổ chức | Nhận refill và trả payee qua module; M1 demo dùng O1, local có thể thử O2. |
| Approver | Duyệt nghĩa vụ cụ thể | Ký EIP-712 đúng các trường; không tự sửa mandate bằng chữ ký hóa đơn. |
| Executor/signer | Phát giao dịch đã được kiểm | Giữ khóa executor trong dịch vụ riêng; không có quyền đổi payee hay policy. |
| AI worker | Đọc, đề xuất, giải thích | Chỉ dùng tool đọc; không giữ khóa, không tự tạo quyền chi. |
| Contract module | Chốt chặn cuối cho đường đi qua module | Kiểm quyền, người nhận, hạn mức, floor, replay và thời hạn tại thời điểm giao dịch. |

Một Safe owner hoặc module khác vẫn có thể thực hiện giao dịch ngoài TreasuryPilot. Vì thế “mandate khóa toàn bộ Safe” là diễn giải sai; nó khóa **đường thực thi của TreasuryPilotModule**. [Known risks KR-02](security/known-risks.md) · [governance contract](../contracts/src/TreasuryPilotGovernance.sol).

Safe T cấp vốn và quản trị module; Safe O1 là nơi module thực hiện chuyển tiền cho vendor. Chữ ký approver chứng minh chấp thuận một payload thanh toán, còn quyền Safe owner thay đổi mandate là một quyền quản trị khác. Executor ký giao dịch blockchain theo quyền module được cấp; signer không thể tự hợp thức hóa payload vượt mandate.

**Câu hỏi kiểm chứng tiếp:** Ai đang là owner/threshold thực tế của từng Safe trên chain được demo? Module nào được enable và có thể chi trực tiếp ngoài TreasuryPilot?

## 02 · Kiến trúc hệ thống

### 2.1 Các lớp triển khai

[![Sơ đồ triển khai và luồng dữ liệu TreasuryPilot](report_site/diagrams/system-architecture-vi.svg)](report_site/diagrams/system-architecture-vi.svg)

*Hình 02.1 — Các lớp triển khai · [Chỉnh sửa bằng draw.io](report_site/diagrams/system-architecture-vi.drawio).*

Code chia thành [web](../apps/web/src/app.tsx), [API](../services/api/src/treasurypilot_api/main.py), [worker](../services/worker/src/treasurypilot_worker/tasks.py), [signer](../services/signer/src/treasurypilot_signer/main.py), [py-core](../packages/py-core/src/treasurypilot_core/) và [contracts](../contracts/src/). Postgres là nguồn sự thật cho nghiệp vụ; Redis là cơ chế phân phối việc, không phải sổ cái giao dịch. [Compose](../infra/compose.yaml) tách `worker`, `worker-ai`, `worker-webhooks`, `beat`, `signer`, `api`, `web`, Postgres, Redis, MinIO; Anvil là profile local.

Postgres giữ trạng thái nghiệp vụ bền vững như request, approval, plan và operation; Redis/Celery chỉ điều phối tác vụ nên không thể dùng hàng đợi làm bằng chứng thanh toán. Worker core chạy quyết định xác định và execution; worker AI là ranh giới gọi model; signer là dịch vụ nhận lệnh ký. Danh sách service trong Compose cho biết cấu hình có thể khởi chạy, không tự chứng minh chúng đã cùng chạy trong cấu hình production hay Sepolia.

**Câu hỏi kiểm chứng tiếp:** Bản demo dùng đúng image/config/commit nào và có log health cho từng service? Khi Redis mất dữ liệu, operation đang chờ được khôi phục từ đâu?

### 2.2 Ranh giới tin cậy

| Ranh giới | Dữ liệu đi qua | Kiểm soát cần có | Giới hạn |
|---|---|---|---|
| Tài liệu hóa đơn → AI | PDF, text, metadata không đáng tin | Bọc nguồn untrusted, quét instruction/secret, schema, người xác nhận | Prompt injection vẫn cần đánh giá bằng bộ tấn công độc lập. |
| Browser → API | session, org ID, chữ ký | RBAC, maker-checker, CSRF/session, kiểm org scope | Mỗi endpoint mới vẫn phải được review. |
| Worker → signer | attestation + calldata + plan | Secret nội bộ, attestation đúng phiên bản, kiểm payload và `eth_call` mới | Cùng host/DB role có rủi ro vận hành cần cô lập thêm. |
| Signer → module | giao dịch được ký | Contract kiểm lại từng hành động | Mô phỏng không giữ trước state của block tương lai. |
| Chain → backend | balances, events, receipt | chain ID, RPC health, confirmations, reorg handling | RPC lỗi/stale có thể làm trễ hoặc sai nhận định tạm thời. |

Nguồn: [AI architecture](AI_AGENT_ARCHITECTURE.md), [signing service](../services/signer/src/treasurypilot_signer/service.py), [known risks](security/known-risks.md).

Điểm cần kiểm soát là nơi dữ liệu không tin cậy trở thành đầu vào có quyền: nội dung invoice phải được người dùng xác nhận; plan do AI gợi ý phải được validator tính lại; calldata chỉ được signer chấp nhận sau attestation và mô phỏng. Mô phỏng là ảnh chụp trạng thái hiện tại, nên contract vẫn phải kiểm lại khi transaction được mined. Các ranh giới này có code, còn mức cô lập hạ tầng và kiểm thử tấn công độc lập cần chứng cứ riêng.

**Câu hỏi kiểm chứng tiếp:** Có thể thay nội dung invoice sau approval mà vẫn giữ chữ ký cũ không? Ai có thể truy cập secret và DB role của signer trong môi trường chạy thật?

### 2.3 Nguyên tắc nhất quán

- **Tiền là số nguyên base units:** API/DB tuần tự hóa decimal string/`NUMERIC(78,0)`; Python `int`/kiểu chặt; Solidity `uint256`. Không dùng float để quyết định thanh toán. [money](../packages/py-core/src/treasurypilot_core/money/base_units.py).
- **Thời gian UTC:** hạn mức ngày theo block time, hiển thị theo timezone tổ chức; lịch và ngày đến hạn quy về UTC day. [utc_days](../packages/py-core/src/treasurypilot_core/domain/utc_days.py).
- **Write before act:** lưu operation/step và danh tính bất biến trước khi phát giao dịch; timeout là trạng thái chưa biết, không phải thất bại. [outbox](../services/worker/src/treasurypilot_worker/executor/outbox.py).
- **Evidence by construction:** mỗi quyết định, phiên bản policy, hash, transaction, receipt và postcondition phải có thể truy ngược. [audit evidence](../services/api/src/treasurypilot_api/audit/evidence.py).

Các quy tắc này ngăn lỗi làm tròn và lệch ngày giữa API, engine và Solidity. Write-before-act tạo bản ghi trước khi gửi giao dịch, nhưng không loại bỏ trạng thái không xác định khi RPC timeout; khi đó phải đối chiếu chain trước retry. Evidence chain hữu ích khi mọi thành phần ghi cùng ID/hash và phiên bản, thay vì chỉ có log văn bản rời rạc.

**Câu hỏi kiểm chứng tiếp:** Có test biên decimals/UTC day thống nhất giữa Python và Solidity không? Khi gửi thành công nhưng worker dừng trước khi lưu receipt, reconciliation khôi phục bằng khóa nào?

## 03 · Nghiệp vụ hóa đơn và duyệt

### 3.1 Trạng thái request

Mô hình nghiệp vụ tách bản nháp/trích xuất khỏi nghĩa vụ có thể thi hành. Người tạo có thể nhập hoặc upload; hệ thống kiểm trường, payee, asset, fingerprint, điều khoản, cờ bất thường; người duyệt nhận payload EIP-712 và ký. Các endpoint trong code gồm tạo/bulk, sửa, xác nhận terms, submit, withdraw/request changes, ack cờ, lấy typed data, approve/reject/cancel/renew. [routes](../services/api/src/treasurypilot_api/invoices/requests.py) · [state machine](../services/api/src/treasurypilot_api/invoices/state_machine.py) · [documents](../services/api/src/treasurypilot_api/invoices/documents.py).

Đường intake có code cho upload, API key và email inbound; cần phân biệt endpoint tồn tại với cấu hình provider/SMTP thực tế. [API keys](../services/api/src/treasurypilot_api/invoices/api_keys.py) · [email inbound](../services/api/src/treasurypilot_api/invoices/inbound_email.py). Fingerprint/near-duplicate giúp phát hiện cùng hóa đơn khác số ID, còn chữ ký duyệt chặn việc dùng một bản ghi “approved” trong DB để chuyển tiền khi thiếu quyền on-chain. [fingerprint](../packages/py-core/src/treasurypilot_core/fingerprint/invoice.py) · [near duplicates](../services/api/src/treasurypilot_api/invoices/near_duplicates.py).

Draft, submitted, approved và executable là khái niệm khác nhau: upload hoặc trích xuất thành công chưa tạo quyền chi; các trường quan trọng cần xác nhận và approval phải ràng buộc đúng phiên bản terms. Fingerprint hỗ trợ cảnh báo duplicate, không thay thế quyết định của người duyệt. Có code cho upload/API/email intake, nhưng khả năng nhận thư thực tế còn phụ thuộc cấu hình mailbox/provider và chưa được chứng minh chỉ bởi endpoint.

**Câu hỏi kiểm chứng tiếp:** Khi payee hoặc terms thay đổi sau ký, hệ thống buộc tạo approval mới ở cả API và contract như thế nào? Intake email đang nối provider nào và có bằng chứng end-to-end không?

### 3.2 Chữ ký thanh toán

`PaymentApproval` ràng buộc request ID, invoice hash, fingerprint, treasury, paying wallet, asset, payee, standard amount, early amount/deadline, terms hash, expiry và cờ fiat. Domain EIP-712 ràng buộc chain/module. Module kiểm người ký hiện là approver (EOA hoặc ERC-1271) và đúng mức tiền theo cửa sổ trả sớm; request chỉ tiêu thụ một lần. Một số trường hợp fiat-quoted dùng cap và logic riêng, vì vậy không nên diễn giải mọi payment thành “luôn đúng một số nguyên cố định”. [PaymentApprovalHash](../contracts/src/libraries/PaymentApprovalHash.sol) · [module pay](../contracts/src/TreasuryPilotModule.sol) · [approval API](../services/api/src/treasurypilot_api/invoices/approval.py).

Typed data giới hạn chữ ký vào một tổ hợp chain, module, request và điều khoản; thay số tiền, địa chỉ trả, asset hoặc deadline sẽ làm digest khác. Approver chấp thuận standard amount hoặc early amount đúng cửa sổ, không chấp thuận một khoản tùy ý do planner đề xuất. Fiat-quoted cap là nhánh có semantics riêng nên cần giải thích rõ số token thực tế có thể biến động theo định giá được ký/kiểm.

**Câu hỏi kiểm chứng tiếp:** Ví dụ chữ ký cụ thể được dựng lại từ typed data có khớp event/payee/amount trên chain không? Trường hợp fiat-quoted có test sai lệch giá và cap nào?

### 3.3 Maker-checker và fraud flags

RBAC xác định ai tạo, sửa, duyệt; maker-checker cấm tự duyệt theo cấu hình, solo mode có kiểm soát riêng. HIGH flags cần được xử lý/ack trước khi đi tiếp; thay đổi payee hoặc trường ký khiến approval cũ không còn hợp lệ. Đây là **kiểm soát backend**, khác kiểm chữ ký của contract. [maker checker](../services/api/src/treasurypilot_api/identity/maker_checker.py) · [RBAC](../services/api/src/treasurypilot_api/identity/rbac.py) · [risk KR-24](security/known-risks.md).

Maker-checker kiểm soát quy trình người dùng ở backend: người tạo không tự duyệt khi policy tổ chức yêu cầu tách vai. Fraud flags là tín hiệu review, không phải kết luận gian lận; HIGH flag cần ack theo luồng trước submit/approve. Contract không biết danh tính maker và checker nếu chữ ký hợp lệ, vì vậy cấu hình RBAC và quy trình tài khoản vẫn là một phần của trust model.

**Câu hỏi kiểm chứng tiếp:** Có kiểm thử quyền cho từng vai trò trên route nhạy cảm và trường hợp solo mode không? Ai được ack HIGH flag và ack đó được lưu cùng phiên bản invoice nào?

## 04 · Financial engine và tối ưu

### 4.1 Refill gắn với request

Với `B` = số dư ví chi, `F` = hard floor, `H` = soft target, `D` = nghĩa vụ cần trả, `R` = tiền dành cho nghĩa vụ khác:

```text
Shortage  = max(0, R + D + F - B)
Preferred = max(0, R + D + H - B)
Bound     = max(0, D + H - B)
Capacity  = max(0, SourceBalance - SourceProtected - SourceFloor)
Cap       = min(Capacity, RemainingRefillDaily, PerRefillLimit)
```

Nếu `Shortage = 0`, không refill chỉ để đạt soft target. Nếu thiếu vượt bound/cap, dừng thay vì gửi một phần rồi vẫn không thể trả. Counter `PAY` và `REFILL` độc lập; module còn ràng buộc đích refill, số lần refill cho request và chênh lệch số dư thực. [engine liquidity](../packages/py-core/src/treasurypilot_core/engine/liquidity.py) · [module refill](../contracts/src/TreasuryPilotModule.sol) · [report thuật toán](submission/technical-documentation.md).

REFILL là chuyển nội bộ từ Safe T sang Safe O1 để tạo đủ số dư thực hiện PAY của một request; đây không phải khoản thanh toán vendor và không làm invoice chuyển sang trạng thái paid. `Shortage` là lượng tối thiểu để đủ nghĩa vụ, reserve và hard floor; `Preferred` nhắm soft target nhưng chỉ dùng khi cần theo logic planner. Nếu cap hoặc capacity không đủ, hệ thống phải block/review thay vì refill thiếu một phần rồi báo thành công.

Counter REFILL và PAY độc lập giúp mandate giới hạn cả tổng ngày lẫn từng bước; gắn refill với request và kiểm chênh lệch số dư hạn chế việc tái sử dụng cho nghĩa vụ khác. Đây là invariant trong code/module; không có số liệu vận hành Sepolia trong báo cáo reliability.

**Câu hỏi kiểm chứng tiếp:** Có thể truy một REFILL mined tới request mà nó tài trợ và chứng minh PAY sau đó dùng đúng số tiền không? Khi token balance thay đổi giữa snapshot và execution, bước nào chặn vượt floor/cap?

### 4.2 Lập lịch và giá trị thanh toán

`schedule_edf` sắp theo hạn UTC, thứ tự duyệt, request ID; mô phỏng tối đa 30 ngày, làm mới hạn mức theo ngày, chuyển số dư qua ngày, kiểm cooling/cap/refill. Đây là heuristic có nghiệm khả thi, không phải chứng nhận tối ưu toàn cục. `schedule_cpsat` tồn tại với giới hạn thời gian mặc định 5 giây và EDF fallback; khi báo kết quả phải ghi thuật toán thực chạy, solver status và fallback. [scheduler](../packages/py-core/src/treasurypilot_core/engine/scheduler.py) · [CP-SAT](../packages/py-core/src/treasurypilot_core/engine/cpsat.py).

Giá trị một lựa chọn trả tiền xét chênh lệch standard/early amount, phí giao dịch, lãi supply bị bỏ lỡ và phạt trễ theo điều khoản đã xác nhận. Phần phân tích không được tăng số tiền PAY vượt chữ ký. B0/B1/B2 trong ADR-019 lần lượt là baseline manual/EDF để tiền nhàn rỗi, optimizer xác định, AI + optimizer; phải công bố cả giả định fee/rate và mẫu dữ liệu khi so sánh. [scoring](../packages/py-core/src/treasurypilot_core/engine/scoring.py) · [ADR-019](adr/ADR-019-aave-liquidity-and-payment-options.md).

EDF ưu tiên nghĩa vụ gần hạn để tìm lịch khả thi dưới các giới hạn ngày, cooling, nguồn tiền và refill; nó không tối đa hóa toàn cục. CP-SAT là solver tùy chọn có time limit, nên kết quả phải nêu status và có dùng fallback hay không. Scoring chỉ chọn thời điểm/option đã được ký, không có quyền tăng cap hoặc thay terms.

**Câu hỏi kiểm chứng tiếp:** Artifact benchmark ghi thuật toán thực chạy, solver status, fallback và phí giả định nào? Có case đối chiếu lịch infeasible hoặc thanh toán trễ với nghiệm tối ưu nhỏ để đánh giá heuristic không?

### 4.3 Dự trữ, Aave và đề xuất vay

[![Quyết định dự trữ thanh khoản và Aave](report_site/diagrams/liquidity-decision-vi.svg)](report_site/diagrams/liquidity-decision-vi.svg)

*Hình 04.1 — Quyết định thanh khoản · [Chỉnh sửa bằng draw.io](report_site/diagrams/liquidity-decision-vi.drawio).*

```text
RequiredSafeReserve = PaymentReserve + SafeFloor + DebtServiceReserve + ExecutionHolds
AvailableForSupply  = max(0, SafeUSDC - RequiredSafeReserve)
AccessibleLiquidity = SafeUSDC + min(aUSDC, PoolAvailableUSDC)
Deficit             = max(0, RequiredSafeReserve - SafeUSDC)
WithdrawTarget      = ceil(Deficit × 105 / 100)
```

`PaymentReserve` tính các nghĩa vụ đã duyệt/chưa trả trong horizon, dùng mức trả sớm khi biết và đúng cửa sổ. Supply chỉ khi đạt ngưỡng tối thiểu, không vượt cap; withdraw bị chặn bởi aToken và thanh khoản pool. Thiếu hụt sau rút cho ra trạng thái không đủ thanh khoản, không tự biến thành giao dịch vay. Hợp đồng chặn floor tĩnh và supply cap; **dự trữ động là trách nhiệm của engine/policy ngoài chain**. [liquidity engine](../packages/py-core/src/treasurypilot_core/engine/liquidity.py) · [forecast](../packages/py-core/src/treasurypilot_core/engine/forecast.py) · [contract Aave paths](../contracts/src/TreasuryPilotModule.sol).

PaymentReserve phản ánh nghĩa vụ đã duyệt trong horizon; supply chỉ dùng phần vượt reserve/floor/debt service/holds. Withdraw phụ thuộc cả số aToken lẫn thanh khoản pool tại thời điểm giao dịch, nên giá trị trên dashboard không đảm bảo rút được. Nếu còn deficit, code có thể tạo đề xuất vay; đề xuất cần approval/authorization riêng và không tự biến thành borrow. Static floor/cap được contract bảo vệ, còn forecast và reserve động là quyết định off-chain.

**Câu hỏi kiểm chứng tiếp:** Demo có receipt supply/withdraw thực trên Sepolia hay chỉ cấu hình địa chỉ/pool? Ai cấp authorization vay và khoản vay được ràng buộc cap, expiry, health factor ra sao?

## 05 · Policy, mandate và smart contract

### 5.1 Quyết định ba mức

[![Bốn lớp kiểm tra quyền thực thi thanh toán](report_site/diagrams/authority-boundaries-vi.svg)](report_site/diagrams/authority-boundaries-vi.svg)

*Hình 05.1 — Ranh giới quyền · [Chỉnh sửa bằng draw.io](report_site/diagrams/authority-boundaries-vi.drawio).*

Validator đánh giá snapshot chain, request, policy version, số dư, hạn mức, payee và plan/step rồi trả `ALLOW`, `NEEDS_APPROVAL` hoặc `BLOCK` kèm reason code. `NEEDS_APPROVAL` là chưa thi hành được; owner phải cấp ngoại lệ đúng request/số tiền, không nới vô hạn. Bộ differential dùng cùng manifest cho Python và Foundry để so quyết định và revert selector; báo cáo hiện liệt kê các trường hợp payee lạ, cooling, pause, expired, over cap, duplicate, floor, replay. [validator](../packages/py-core/src/treasurypilot_core/policy/validator.py) · [reason codes](../packages/py-core/src/treasurypilot_core/policy/reason_codes.py) · [differential report](testing/policy-contract-differential-report.md).

`ALLOW` nghĩa là bước cụ thể vượt validator tại snapshot và có thể tiếp tục chuỗi ký; `NEEDS_APPROVAL` là thiếu ngoại lệ/ủy quyền phù hợp; `BLOCK` là vi phạm không thể thực hiện theo trạng thái hiện tại. Reason code cần đi cùng version policy để UI và audit giải thích được quyết định. Differential report cho biết hai implementation đồng thuận trên case đã khai báo, không chứng minh mọi input có thể có đều tương đương.

**Câu hỏi kiểm chứng tiếp:** Trên cùng snapshot và payload, reason code của API có khớp revert reason trên chain cho các case biên không? Ngoại lệ có giới hạn đúng request, amount và expiry không?

### 5.2 Mandate và quản trị

Safe T owner/threshold quản trị allowlist payee, asset, wallet, hạn mức PAY/REFILL, floor, thời gian hiệu lực, pause/revoke, ngoại lệ, Aave pool và các quyền vay/trả. Module instance được tạo qua factory. Owner/guardian pause chỉ ngăn hành động **sau khi giao dịch pause được mined**; không thu hồi giao dịch đã hoàn tất và không cản quyền trực tiếp của Safe owner. [governance](../contracts/src/TreasuryPilotGovernance.sol) · [factory](../contracts/src/TreasuryPilotModuleFactory.sol) · [mandate API](../services/api/src/treasurypilot_api/mandate/routes.py).

Mandate là quyền của module do Safe T owner quản lý; cấu hình allowlist/cap/floor quyết định phạm vi mà TreasuryPilot có thể dùng. Thay đổi governance cũng là giao dịch cần ký và mined. Pause chỉ có hiệu lực từ block chứa lệnh pause trở đi; nó không đảo ngược giao dịch đã hoàn tất, và không ngăn owner Safe gọi quyền trực tiếp.

**Câu hỏi kiểm chứng tiếp:** Có thể tái dựng lịch sử mandate tại block của mỗi PAY để biết giới hạn lúc thực thi không? Quy trình ứng phó sự cố đã đo thời gian từ phát hiện tới pause mined chưa?

### 5.3 Các entry point on-chain

| Nhóm | Entry point / control | Ý nghĩa |
|---|---|---|
| Chi trả | `pay` | Approval hợp lệ, option đúng, payee được phép, per-request/daily limit, floor, anti-replay. |
| Chuyển nội bộ | `refill` | Safe T → ví vận hành đã đăng ký, gắn request, mức cần thiết và daily/refill cap. |
| Tiền dư | `supply`, `withdraw` | Pool/asset cố định, floor/cap, kiểm chênh lệch tài sản; không có generic arbitrary call. |
| Nợ P2 | `authorizeBorrow`, `authorizeRepay`, `borrow`, `repay` | Owner cấp grant một lần, có expiry; borrow còn kiểm rate/health factor tại thời điểm gọi. |
| Gas / nâng cao | `swapForGas`, `PlanAttestedExecutor`, `ReserveHoldExecutor`, `ThresholdApprovalExecutor` | Đường chuyên biệt cần cấu hình và bằng chứng theo đúng môi trường; không suy ra tất cả đều nằm trong demo M1. |

Nguồn: [TreasuryPilotModule](../contracts/src/TreasuryPilotModule.sol), [PlanAttestedExecutor](../contracts/src/PlanAttestedExecutor.sol), [ReserveHoldExecutor](../contracts/src/ReserveHoldExecutor.sol), [ThresholdApprovalExecutor](../contracts/src/ThresholdApprovalExecutor.sol).

Các entry point chuyên biệt thu hẹp bề mặt hành động so với arbitrary call: `pay` chi cho payee; `refill` chuyển giữa các Safe đã đăng ký; `supply`/`withdraw` tương tác pool cấu hình. `authorizeBorrow` và `authorizeRepay` là grant tách biệt, vì thế sự hiện diện trong ABI không chứng minh chúng được kích hoạt trong demo. Executor nâng cao cần kiểm riêng module, code hash, grant và test theo deployment.

**Câu hỏi kiểm chứng tiếp:** ABI và code hash trên Sepolia có khớp source build/release không? Với mỗi entry point được giới thiệu trong demo, có transaction hoặc bằng chứng revert cụ thể ở đúng chain không?

## 06 · AI agent

### 6.1 Vị trí của AI trong hệ thống

AI được dùng cho trích xuất hóa đơn/điều khoản, gợi ý kế hoạch, soạn ngoại lệ, Copilot và giải thích bất thường. `worker-ai` gọi model, có budget/failover và tool đọc; `worker-core` giữ policy attestation và quyết định tiền qua engine. Code có provider adapter, prompt phiên bản, instruction detector, secret scan, read-only tools và các eval harness. [agent code](../services/worker/src/treasurypilot_worker/agent/) · [AI architecture](AI_AGENT_ARCHITECTURE.md) · [Google Docs, tab AI](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.yed8bvlknow6).

AI có thể đọc/chuyển đổi thông tin và đề xuất lựa chọn, nhưng không có thẩm quyền xác lập nghĩa vụ hoặc phát tiền. Extraction trả candidate fields cần người xác nhận; plan proposal phải nằm trong options khả thi do engine cung cấp; Copilot giải thích dữ liệu đã có. Failover/budget cải thiện tính sẵn có và kiểm soát chi phí model, không làm đầu ra đáng tin hơn mặc nhiên.

**Câu hỏi kiểm chứng tiếp:** Ở cấu hình triển khai, tool AI nào được cấp và có đường gọi ghi nào không? Khi model lỗi/timeout, fallback hiển thị rõ cho operator và vẫn giữ cùng policy không?

### 6.2 Hợp đồng đầu ra và chống injection

Nội dung PDF/email là dữ liệu không tin cậy. AI không được lấy câu trong chứng từ làm lệnh đổi policy/payee, không được đưa địa chỉ vào bước chi nếu chưa qua dữ liệu đã xác nhận, không được gọi API ghi hoặc giữ key. Đầu ra đi qua schema, kiểm tham chiếu và so với tính toán xác định. Các lớp chống injection trong code gồm untrusted wrapper, quét bí mật, instruction detector và prompt policy; đây là giảm rủi ro, không phải bằng chứng “miễn nhiễm”. [untrusted](../services/worker/src/treasurypilot_worker/agent/untrusted.py) · [detector](../services/worker/src/treasurypilot_worker/agent/instruction_detector.py) · [secret scan](../services/worker/src/treasurypilot_worker/agent/secret_scan.py).

Schema validation bảo đảm hình dạng dữ liệu, còn kiểm tham chiếu xác nhận giá trị khớp invoice/plan đã biết; hai kiểm tra này khác nhau. Quét instruction/secret có thể bỏ sót diễn đạt mới, nên tài liệu phải mô tả đây là lớp giảm rủi ro và duy trì xác nhận người dùng cho trường quyền hạn. Không dùng văn bản do model sinh làm địa chỉ/payee hoặc calldata trực tiếp.

**Câu hỏi kiểm chứng tiếp:** Có ca injection qua OCR, email trích dẫn và đa ngôn ngữ trong bộ red-team không? Log có giữ prompt/model/version đủ để tái lập mà không ghi lộ tài liệu nhạy cảm không?

### 6.3 Kết quả eval có điều kiện

| Artifact 15/10/2026 | Kết quả ghi nhận | Giới hạn đọc kết quả |
|---|---|---|
| [Extraction accuracy](evidence/extraction-accuracy.md) | 30 invoice recorded; amount đúng 27/30; terms F1 70,6%, exact terms 60%. | Nhãn đang chờ người thứ hai review; tập public/recorded, không phải đo production. |
| [Copilot fidelity](evidence/copilot-fidelity.md) | 20/20 case giữ đúng số theo quy tắc kiểm. | Case do AI tạo, chờ review độc lập; không đo toàn bộ câu hỏi thật. |
| [Red-team](evidence/redteam-results.md) | 0/20 case đổi field/policy; model flag 20/20. | Keyword fallback tự flag 2/20; bộ 20 case không chứng minh chống mọi prompt injection. |

Các tỷ lệ trong bảng chỉ áp dụng cho tập và ngày ghi trong artifact. Extraction accuracy chưa có reviewer thứ hai; Copilot set tổng hợp; red-team nhỏ và có keyword fallback tham gia flag. Vì vậy các kết quả không đại diện độ chính xác production hoặc khả năng chống tấn công tổng quát, và không được gộp thành một điểm AI chung.

**Câu hỏi kiểm chứng tiếp:** Ai sẽ review độc lập nhãn và chọn held-out set trước khi dùng các tỷ lệ này trong quyết định sản phẩm? Các metric được tính trên model/prompt/configuration nào và có lưu lỗi từng mẫu để tái lập không?

## 07 · Execution, signer và phục hồi

### 7.1 Chuỗi thực thi an toàn

Một bước thực thi phải có plan/step ID ổn định, snapshot mới, policy decision, attestation gắn plan hash/nonce/expiry, outbox trong Postgres rồi mới phát giao dịch. Signer nhận typed step, kiểm attestation, target chain/module, calldata với plan, mô phỏng `eth_call`, giữ nonce/step chống gửi lặp và ký bằng khóa executor. Endpoint nội bộ `/sign-and-send` đã có code; mô tả cũ “signer chỉ có health” trong submission draft không còn đúng với commit hiện tại. [signer main](../services/signer/src/treasurypilot_signer/main.py) · [signer service](../services/signer/src/treasurypilot_signer/service.py) · [signer store](../services/signer/src/treasurypilot_signer/store.py).

Outbox lưu ý định gửi trước khi tương tác RPC; sequencer bảo đảm thứ tự bước phụ thuộc; signer kiểm lại thông tin đầu vào trước khi ký. Attestation gắn plan hash giúp phát hiện payload bị thay đổi, trong khi `eth_call` kiểm khả năng thực thi trên state quan sát được. Đây là nhiều lớp phòng thủ bổ trợ, không phải bảo đảm transaction sẽ thành công khi state thay đổi trước khi mine.

**Câu hỏi kiểm chứng tiếp:** Có thể từ một operation trong DB dựng lại attestation, calldata và tx hash tương ứng không? Quyền ký của executor có giới hạn ở module/chain dự kiến trong cấu hình production không?

### 7.2 Xử lý trạng thái không chắc chắn

[![Luồng xác định kết quả giao dịch và phục hồi](report_site/diagrams/execution-recovery-vi.svg)](report_site/diagrams/execution-recovery-vi.svg)

*Hình 07.1 — Phục hồi kết quả · [Chỉnh sửa bằng draw.io](report_site/diagrams/execution-recovery-vi.drawio).*

Sau timeout, worker không được tạo request/step mới và thử lại mù. Nó đọc receipt, nonce, module `requestPaid`/`stepUsed`, state thực của chain; cho tới khi rõ, treasury bị chặn hoặc chuyển review. Với plan nhiều bước, bước đã confirmed không được phát lại khi bước sau thất bại. Code có outbox, sequencer, tracker, scan/retry/resolve và partial recovery; cần đối chiếu kết quả E2E theo môi trường để khẳng định độ bền đầy đủ. [executor](../services/worker/src/treasurypilot_worker/executor/) · [recovery](../services/worker/src/treasurypilot_worker/recovery/) · [risk KR-09](security/known-risks.md).

Timeout chỉ nói client chưa biết kết quả; transaction có thể đã vào mempool hoặc được mine. Resolver cần so nonce, receipt và trạng thái replay/request trên chain trước khi đánh dấu failed/retry. Với REFILL rồi PAY, đã confirmed REFILL phải được giữ nguyên như bước hoàn tất; chỉ bước PAY còn thiếu mới được xem xét tiếp tục. Code recovery tồn tại, nhưng báo cáo không đưa ra bằng chứng Sepolia hay chaos test để khẳng định mọi crash/reorg đã được xử lý.

**Câu hỏi kiểm chứng tiếp:** Có kịch bản dừng worker sau broadcast và trước khi lưu hash, rồi chứng minh không gửi trùng khi restart không? Reorg sau confirmation được phát hiện và sửa trạng thái đối soát thế nào?

### 7.3 Circuit breaker và pause

Đường phát hiện bất thường có review queue/circuit breaker trong API/worker và đường sentinel pause nội bộ. Cần phân biệt: “pause requested” là yêu cầu; “pause mined” mới là trạng thái contract; Safe owner vẫn có quyền riêng. [circuit API](../services/api/src/treasurypilot_api/recovery/circuit.py) · [sentinel](../services/signer/src/treasurypilot_signer/sentinel.py).

Circuit breaker phía dịch vụ có thể ngừng lập lịch hoặc yêu cầu review; pause on-chain ngăn các đường module khi giao dịch pause đã được xác nhận. Đây là hai cơ chế với thời điểm và phạm vi khác nhau. Cần chỉ rõ ai nhận cảnh báo, ai có quyền pause và trạng thái nào được coi là đã pause thay vì chỉ có yêu cầu.

**Câu hỏi kiểm chứng tiếp:** Có runbook và bằng chứng thời gian phát hiện/ack/pause mined cho sự cố nào chưa? Khi circuit breaker mở, các operation đang chạy được reconcile hay chỉ chặn operation mới?

## 08 · Dữ liệu, API và giao diện

### 8.1 Mô hình dữ liệu

PostgreSQL lưu các nhóm: identity/org/member/session; treasury/wallet/chain; mandate/payee/exception; invoice/request/approval; plan/step/AI call; operation/event/snapshot; reconciliation/evidence/audit; notification/admin. Các bảng nghiệp vụ có `organization_id`/`org_id` cho isolation; amount dùng số nguyên; migration là nguồn thực tế cho schema hiện hành, còn [DATA_MODEL](DATA_MODEL.md) là thiết kế đọc nhanh. [migrations](../services/api/migrations/versions/) · [Google Docs, tab data model](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.py8ti27c4ma4).

Chuỗi chứng cứ tối thiểu: request → invoice hash/fingerprint → approval typed data/signature → plan/policy version → operation/step ID → tx hash/receipt/events → verification → reconciliation → audit/evidence bundle. Việc nối bằng khóa định danh và hash quan trọng hơn chỉ hiển thị một tx hash. [audit models](../services/api/src/treasurypilot_api/audit/models.py) · [reconciliation models](../services/api/src/treasurypilot_api/reconciliation/models.py).

Các bảng nối business record với chain evidence bằng identifier/hash, giúp phân biệt invoice được duyệt với transaction thực hiện. `organization_id` hỗ trợ tenant scope nhưng cần được áp dụng nhất quán ở truy vấn, export, background task và admin path. Migration là bằng chứng schema theo revision; sơ đồ dữ liệu mô tả khái niệm có thể chưa phản ánh mọi cột.

**Câu hỏi kiểm chứng tiếp:** Có kiểm thử truy cập chéo tổ chức cho API, worker task và export không? Hash trong evidence bundle được tạo từ canonical serialization nào để tái lập độc lập?

### 8.2 Bề mặt API hiện có

| Miền | Ví dụ route / hành vi | Code |
|---|---|---|
| Identity | auth, tổ chức, membership, MFA, OIDC/SAML/SCIM | [main/router wiring](../services/api/src/treasurypilot_api/main.py), [identity](../services/api/src/treasurypilot_api/identity/) |
| Treasury | chain, treasury, Safe, forecast, snapshot | [treasury](../services/api/src/treasurypilot_api/treasury/api.py), [forecast](../services/api/src/treasurypilot_api/treasury/forecast.py) |
| Mandate | payee, governance tx, pause, exception, fee policy | [mandate](../services/api/src/treasurypilot_api/mandate/) |
| Requests | intake/upload, terms, approval EIP-712, cancel | [requests](../services/api/src/treasurypilot_api/invoices/requests.py) |
| Execution | plan/operation, sequencing and status | [execution](../services/api/src/treasurypilot_api/execution/routes.py) |
| Evidence | reconciliation, export, audit log, verification | [reconciliation](../services/api/src/treasurypilot_api/reconciliation/), [audit](../services/api/src/treasurypilot_api/audit/) |
| Support | notification, webhook, Copilot, ERP adapter | [notifications](../services/api/src/treasurypilot_api/notifications/), [copilot](../services/api/src/treasurypilot_api/copilot/api.py), [ERP](../services/api/src/treasurypilot_api/integrations/erp/) |

Các API chính ở `/v1`; org-scoped routes gắn organization ID. Spec [API_SPEC](API_SPEC.md) có thể đi trước/đi sau code, vì vậy khi tích hợp client nên kiểm OpenAPI xuất từ app và file [web openapi.json](../apps/web/openapi.json). UI dùng React/Vite, TanStack Query, wagmi/viem và có dashboard, setup, request, approval, plan, review, mandate, payee, reconciliation, metrics, Copilot. [web app](../apps/web/src/app.tsx) · [package](../apps/web/package.json).

Route hiện diện cho biết chức năng được nối vào app, không xác nhận client tương thích hoặc mọi tích hợp đã có credentials. OpenAPI runtime nên được so với spec và web client ở cùng revision; org scope và quyền cần xem ở dependency/handler thay vì chỉ dựa vào URL. Giao diện là lớp thao tác và hiển thị trạng thái, không thay thế nguồn sự thật trong DB/chain.

**Câu hỏi kiểm chứng tiếp:** Có CI hoặc artifact nào so OpenAPI runtime với client bindings không? Từng route mutation có kiểm org scope và vai trò trong test hiện hành không?

## 09 · Chain, bằng chứng và đối soát

Chain reader/indexer tạo snapshot và theo dõi event/receipt; verifier kiểm hậu điều kiện trước khi đánh dấu kết quả thanh toán. Reconciliation phân biệt refill/swap nội bộ với chi phí vendor và cho phép match/discrepancy/resolve. Audit log, evidence bundle và helper EAS thêm khả năng chứng minh, nhưng hash hóa đơn/approval/plan trong EAS vẫn là assertion từ backend; người kiểm toán phải kiểm trusted attester, schema và tx PAY thật. [chain worker](../services/worker/src/treasurypilot_worker/chain/) · [verify](../services/worker/src/treasurypilot_worker/reconcile/verify.py) · [reconciliation routes](../services/api/src/treasurypilot_api/reconciliation/routes.py) · [attestation helper](../infra/scripts/attest_receipt.py).

Manifest [Sepolia](../deployments/11155111.json) ở commit này ghi `deploymentStatus: deployed`, module/Safe T/Safe O1 và các code hash/verified block. Điều này chứng minh **artifact cấu hình triển khai có địa chỉ và mốc kiểm**, nhưng riêng manifest không chứng minh tất cả bước demo hoặc đối soát public đã chạy thành công. [Báo cáo reliability 15/10](evidence/reliability-2026-10-15.md) ghi 30/30 run local Anvil hoàn tất; Sepolia: 0 run. Một số báo cáo submission cũ còn ghi `configured_only`; khi trình bày cần nêu ngày/revision của từng artifact.

Đối soát cần phân biệt ba lớp: receipt transaction thành công, postcondition xác nhận đúng thay đổi tài sản/trạng thái, và match nghiệp vụ nối khoản chi với invoice. REFILL là luồng nội bộ, không phải chi phí vendor; PAY mới là ứng viên thanh toán hóa đơn. EAS attestation ghi nhận lời xác nhận của attester, nên tính độc lập phụ thuộc identity/role của attester và dữ liệu nguồn được hash.

Bằng chứng Sepolia hiện có trong manifest là địa chỉ, code hash và mốc block; đây là thông tin deployment. Reliability report ghi Anvil 30/30 và Sepolia 0 run, nên không được mô tả 30 lần đó là giao dịch public.

**Câu hỏi kiểm chứng tiếp:** Có tx PAY Sepolia nào nối được tới approval, receipt verification và reconciliation record cùng request ID không? Ai kiểm chứng attester/schema và làm sao phát hiện dữ liệu backend sai trước khi anchor?

## 10 · Bảo mật và tuân thủ

### 10.1 Các kiểm soát chính

- Contract chặn người nhận không được phép, hạn mức, floor, expiry, pause/revoke, replay và sai option ký. [contract](../contracts/src/TreasuryPilotModule.sol).
- Signer cô lập khóa executor, kiểm attestation/payload/simulation; AI worker không nhận khóa policy/executor theo cấu hình Compose. [signer](../services/signer/src/treasurypilot_signer/) · [compose](../infra/compose.yaml).
- Identity/RBAC và org-scoped repository bảo vệ dữ liệu đa tenant; maker-checker là một lớp riêng. [RBAC](../services/api/src/treasurypilot_api/identity/rbac.py) · [scoped repository](../services/api/src/treasurypilot_api/common/repository.py).
- Screening/KYB/travel-rule và data region có code/adapter, nhưng fixture screening không đồng nghĩa kết nối provider sống hoặc phê chuẩn pháp lý. [compliance](../services/api/src/treasurypilot_api/compliance/) · [risk KR-19](security/known-risks.md).
- Privacy primitives cho classification/redaction/encryption cần được áp dụng ở từng tích hợp, log và export. [privacy](../packages/py-core/src/treasurypilot_core/privacy/).

Kiểm soát contract áp dụng trên đường module; RBAC/maker-checker áp dụng trong ứng dụng; signer và quản trị secret là kiểm soát hạ tầng. Tuân thủ có adapter và fixture không đồng nghĩa đã kết nối screening provider hay có kết luận pháp lý cho một jurisdiction. Privacy primitives cũng chỉ bảo vệ dữ liệu nếu được gọi đúng ở từng luồng lưu, log và export.

**Câu hỏi kiểm chứng tiếp:** Những kiểm soát nào đã được thử trên cấu hình triển khai thật thay vì unit test/fixture? Provider compliance và retention policy nào đang bật cho dữ liệu demo?

### 10.2 Rủi ro còn mở phải ghi trong báo cáo công khai

Hợp đồng chưa có audit độc lập; owner/module Safe khác có thể giao dịch ngoài mandate; RPC/reorg ảnh hưởng tính cuối cùng; dự trữ động không nằm hoàn toàn on-chain; Aave pool/cap thay đổi; signer với quyền DB cần hardening; dữ liệu hóa đơn và prompt có thể lộ/sai; nhận diện sanctions qua fixture không tương đương kiểm thực tế; một VM/Compose là điểm lỗi tập trung. Danh mục và mức ảnh hưởng chi tiết: [known risks](security/known-risks.md) · [self-assessment](submission/security-self-assessment.md).

Các rủi ro có thể ảnh hưởng trực tiếp tới tính đúng của số dư, quyền chi, tính cuối cùng và bảo mật dữ liệu; mức ưu tiên cần gắn owner, biện pháp giảm thiểu và ngày đánh giá. Việc có `known-risks.md` chứng minh rủi ro được ghi nhận, không chứng minh đã chấp nhận hoặc khắc phục. Đặc biệt, chưa có audit độc lập và dự trữ động vẫn phụ thuộc logic off-chain.

**Câu hỏi kiểm chứng tiếp:** Ai là người chịu trách nhiệm và thời hạn xử lý từng rủi ro trước pilot? Có tài liệu nào ghi rõ rủi ro được chấp nhận bởi owner sản phẩm/security?

## 11 · Kiểm thử, đo lường và khả năng tái lập

| Tầng | Bằng chứng/code | Điều có thể kết luận |
|---|---|---|
| Unit/property | [py-core tests](../packages/py-core/tests/), [API tests](../services/api/tests/) | Logic theo case và invariant đã định nghĩa; không thay thế E2E. |
| Contract | [Foundry tests](../contracts/test/), [test evidence](security/test-evidence.md) | Revert/invariant của module trong môi trường test/fork theo revision báo cáo. |
| Policy ↔ contract | [differential matrix](testing/policy-contract-differential-report.md) | Python/contract đồng ý trên case manifest; báo cáo nêu cả case chưa phủ. |
| Web | [Vitest/Playwright](../apps/web/e2e/) | Luồng UI với fixture/mock theo cấu hình test. |
| AI | [extraction](evidence/extraction-accuracy.md), [Copilot](evidence/copilot-fidelity.md), [red-team](evidence/redteam-results.md) | Kết quả recorded/synthetic, chưa chứng minh chất lượng ngoài tập. |
| Reliability | [30-run Anvil report](evidence/reliability-2026-10-15.md) | 30/30 local scenario; chưa có 10-run Sepolia trong artifact này. |

Để tái lập đánh giá, cần ghi SHA, chain ID/block, asset/decimals, dataset split và lịch sử exposure, model/prompt, algorithm thực dùng (EDF hay CP-SAT/fallback), giả định phí/rate, denominator và số lần fail. Không trộn kết quả fork, Anvil và public Sepolia thành một “success rate”. [technical documentation, §7](submission/technical-documentation.md) · [planner benchmark](../services/worker/src/treasurypilot_worker/planner_bench/).

Các tầng kiểm thử trả lời câu hỏi khác nhau: unit xác nhận quy tắc cục bộ, contract test xác nhận hành vi Solidity, differential tìm lệch Python/on-chain, còn E2E kiểm tích hợp. Chỉ evidence có revision, cấu hình và denominator rõ mới hỗ trợ so sánh. Con số 30/30 là các run Anvil được báo cáo ngày 15/10; không có run Sepolia trong artifact đó, và test có mock không phải bằng chứng giao dịch public.

Đối với benchmark planner/AI, cần lưu dataset và split, seed, model/prompt, solver status/fallback, fee/rate, failure cases và phiên bản source. Không gộp fork, local Anvil, testnet hay synthetic eval vào một success rate.

**Câu hỏi kiểm chứng tiếp:** Artifact nào có thể checkout và chạy lại ở đúng SHA đã ghi? Các run reliability có bao gồm crash/restart, reorg, timeout và partial REFILL/PAY hay chỉ kịch bản thành công?

## 12 · Triển khai và vận hành

### 12.1 Môi trường

Local Compose khởi Postgres 16, Redis 7, MinIO, Anvil tùy profile, migrate, API, worker core/AI/webhooks, beat, signer và web. Sepolia có compose override và deployment scripts/manifest riêng. Trước mỗi demo cần kiểm chain ID, RPC, Safe owners/threshold/module enabled, token decimals, hạn mandate, payee, pool/aToken, gas và EAS attester; điều kiện Aave supply có thể thay đổi ngay cả khi fork lịch sử chạy tốt. [infra README](../infra/README.md) · [compose](../infra/compose.yaml) · [Sepolia override](../infra/compose.sepolia.yaml) · [deployment guide](../contracts/docs/DEPLOYMENT.md).

Compose mô tả topology local; override Sepolia thay cấu hình chain nhưng không tự khởi chạy hay chứng minh deployment còn hoạt động. Trước demo cần xác minh chain ID và block hiện tại, trạng thái Safe/module, decimals, allowlist, pool liquidity, RPC và khóa/attester. Dữ liệu Anvil từ fork có thể khác trạng thái hiện tại của Sepolia, nhất là thanh khoản Aave và gas.

**Câu hỏi kiểm chứng tiếp:** Có checklist preflight tự đọc on-chain state và lưu kết quả cùng block number không? Manifest có được xác nhận lại với explorer/RPC ngay trước demo không?

### 12.2 Observability và sự cố

Log có correlation ID, metrics/trace, Sentry/OpenTelemetry và notification outbox. Sự cố quan trọng phải cho thấy request/plan/operation ID, policy reason code, chain/block, tx/nonce/receipt và quyết định retry hoặc review; không log khóa, session token, chữ ký nguyên văn hay hóa đơn nhạy cảm. [observability core](../packages/py-core/src/treasurypilot_core/observability.py) · [metrics](../services/api/src/treasurypilot_api/observability/metrics.py) · [notifications](../services/worker/src/treasurypilot_worker/notify/).

Correlation ID giúp gom log API/worker, nhưng điều tra chuyển tiền cần cả operation ID và tx/nonce/block để đối chiếu nguồn chain. Metrics cho biết xu hướng, không thay receipt/postcondition làm bằng chứng. Log nên ghi reason code, transition và retry decision nhưng phải tránh bí mật, chữ ký đầy đủ và nội dung hóa đơn.

**Câu hỏi kiểm chứng tiếp:** Alert nào phát hiện operation mắc ở trạng thái unknown hoặc partial quá lâu, và ai trực xử lý? Có thể dựng timeline từ alert đến receipt/reconciliation mà không cần truy cập dữ liệu nhạy cảm không?

## 13 · Trạng thái triển khai và khoảng trống

| Hạng mục | Quan sát ở commit `50b1117` | Điều cần thêm trước khi khẳng định hoàn tất |
|---|---|---|
| Sản phẩm web/API | Nhiều màn hình, endpoint và migration hiện diện. | E2E trên cấu hình demo thật, xác nhận client/OpenAPI không lệch. |
| Engine/policy | EDF, CP-SAT, forecast, liquidity và validator có code/test. | Benchmark B0/B1/B2 đúng nhãn với tập held-out đã review. |
| Contract/on-chain | Module và các entry point, manifest Sepolia `deployed`. | Bằng chứng public tx cho từng cảnh D1–D10, review quyền độc lập, audit trước mainnet. |
| Signer/worker | `/sign-and-send`, outbox/sequencer/recovery có code. | Chaos/restart/reorg và multi-step E2E trên testnet; kiểm quyền DB signer. |
| AI | Extraction/Copilot/eval recorded và guard có code. | Ground truth độc lập, held-out, thêm tấn công/OCR/locale. |
| Reliability | 30/30 Anvil trong báo cáo 15/10. | Chạy và lưu evidence Sepolia riêng; backup/restore và multi-host khi nâng cấp. |

Các mục trên là **đề nghị xác minh**, không phải khẳng định code thiếu. Điểm có thể kết luận chắc từ repo là ranh giới thiết kế và code triển khai từng module; mức sẵn sàng production cần một review kỹ thuật/bảo mật và chứng cứ hệ thống theo release cụ thể. [Submission README](submission/README.md) · [known risks](security/known-risks.md).

Bảng này tách sự hiện diện của code khỏi bằng chứng vận hành: module có thể build/test được mà chưa được tích hợp end-to-end; manifest deployed không chứng minh luồng nghiệp vụ đã chạy. Bằng chứng mạnh nhất đang nêu là local Anvil 30/30; public Sepolia chưa có run trong reliability report. Vì vậy mức production-ready chưa thể suy ra từ số lượng module hoặc endpoint.

Một release claim nên gắn commit, cấu hình chain, tx links/receipt, test/eval artifact và các rủi ro còn mở. Yêu cầu review audit trước mainnet là cổng tương lai, không phải tuyên bố có audit hoặc đã đủ điều kiện mainnet.

**Câu hỏi kiểm chứng tiếp:** Tiêu chí cụ thể nào đóng từng khoảng trống trước pilot hoặc mainnet, ai ký nhận và artifact nào là bằng chứng? Có luồng nào được tuyên bố demo nhưng mới chỉ có code/manifest?

## 14 · Bản đồ module và phụ thuộc triển khai

Tài liệu Google Docs tổ chức công việc thành 20 module M01–M20. Tab 36 ghi cách chia luồng và phân công **tại 11–12/10/2026**; đó là snapshot quản lý công việc, không phải trạng thái issue hiện tại. Bảng dưới ánh xạ module với code/tài liệu để người mới có thể tìm ngay nơi chịu trách nhiệm. [Danh mục module](modules/README.md) · [Google Docs, hướng dẫn phân công](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.3xlngx2j9mze).

| Module | Trách nhiệm kỹ thuật | Điểm vào |
|---|---|---|
| M01 Identity | Session, SIWE, tổ chức, RBAC, MFA/federation | [identity](../services/api/src/treasurypilot_api/identity/) |
| M02 Treasury | Safe, wallet, chain, snapshot, forecast | [treasury API](../services/api/src/treasurypilot_api/treasury/) |
| M03 Mandate | Payee, hạn mức, governance, ngoại lệ, pause | [mandate API](../services/api/src/treasurypilot_api/mandate/) |
| M04 Contracts | Module/factory, EIP-712, Aave, replay/floor/cap | [contracts](../contracts/src/) |
| M05 Invoices | Intake, trích xuất, request, approval | [invoices](../services/api/src/treasurypilot_api/invoices/) |
| M06 Chain reader | RPC, event indexer, tracker, snapshot | [chain worker](../services/worker/src/treasurypilot_worker/chain/) |
| M07 Financial engine | Refill, EDF/CP-SAT, reserve, forecast | [engine](../packages/py-core/src/treasurypilot_core/engine/) |
| M08 Policy | Validator, reason codes, attestation | [policy](../packages/py-core/src/treasurypilot_core/policy/) |
| M09 Agent | Extraction, plan proposal, Copilot, AI eval | [agent](../services/worker/src/treasurypilot_worker/agent/) |
| M10 Execution | Outbox, sequencing, signer, simulation | [executor](../services/worker/src/treasurypilot_worker/executor/), [signer](../services/signer/src/treasurypilot_signer/) |
| M11 Reconciliation | Receipt, verification, match/export | [reconcile worker](../services/worker/src/treasurypilot_worker/reconcile/), [API](../services/api/src/treasurypilot_api/reconciliation/) |
| M12 Recovery | Unknown/partial, retry và review | [recovery worker](../services/worker/src/treasurypilot_worker/recovery/), [API](../services/api/src/treasurypilot_api/recovery/) |
| M13 Notifications | In-app, webhook, email, Telegram | [notify worker](../services/worker/src/treasurypilot_worker/notify/) |
| M14 Compliance | Screening, KYB, travel rule, retention | [compliance](../services/api/src/treasurypilot_api/compliance/) |
| M15 Audit | Audit log, hash chain, evidence bundle | [audit](../services/api/src/treasurypilot_api/audit/) |
| M16 Web | Giao diện operator/approver/owner | [features](../apps/web/src/features/) |
| M17 Observability | Metrics, savings, logging, tracing | [observability](../services/api/src/treasurypilot_api/observability/) |
| M18 Platform admin | Hỗ trợ vận hành đa tổ chức | [admin](../services/api/src/treasurypilot_api/admin/) |
| M19 DevEx | Build, Compose, CI, test, OpenAPI | [infra](../infra/), [workflows](../.github/workflows/) |
| M20 Domain/evidence | Kịch bản demo, đo lường, review nghiệp vụ | [evidence](evidence/), [submission](submission/) |

**Thứ tự phụ thuộc thực tế:** contract ABI/EIP-712 và chain snapshot định hình validator; validator cùng engine định hình plan/attestation; signer và executor chỉ nhận step đã hợp lệ; tracker/verifier mới cho phép Paid/reconciliation; web/AI dựa vào các hợp đồng dữ liệu và trạng thái đó. Chia luồng A (chain/engine/policy/execution/recovery), B (sản phẩm/API/web/AI), C (nghiệp vụ/bằng chứng) trong tab 36 phản ánh phụ thuộc này. Khi điều phối sprint hiện tại, đọc code/PR/Project mới nhất thay vì dùng số ticket còn mở của snapshot 11/10.

Bảng ánh xạ trách nhiệm kỹ thuật tới nơi tìm code, không phải bảng tiến độ hoàn thành M01–M20. Phụ thuộc cốt lõi chạy từ contract ABI và snapshot sang policy/plan, rồi signer/executor, tracker/verifier và reconciliation; UI/AI tiêu thụ trạng thái do các lớp này tạo ra. Thay đổi interface ở đầu chuỗi có thể làm lệch nhiều module dù từng package riêng vẫn qua kiểm tra.

Tab phân công ngày 11–12/10 là snapshot lịch sử; trạng thái hiện thời phải xác minh bằng commit/PR và người chịu trách nhiệm hiện tại.

**Câu hỏi kiểm chứng tiếp:** Có owner hiện hành cho từng interface liên module và cách kiểm compatibility khi ABI/schema đổi không? Những phân công trong tab lịch sử nào đã được đối chiếu với trạng thái repo mới nhất?

## 15 · Bản đồ nguồn và cách cập nhật báo cáo

| Cần hiểu | Nguồn chính |
|---|---|
| Ý tưởng, người dùng, phạm vi | [Google Docs](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit), [PROJECT_OVERVIEW](PROJECT_OVERVIEW.md) |
| Kiến trúc/trust boundary | [SYSTEM_ARCHITECTURE](SYSTEM_ARCHITECTURE.md), [ARCHITECTURE entry](../ARCHITECTURE.md) |
| Quy tắc tiền và quyền | [BUSINESS_RULES](BUSINESS_RULES.md), [contracts](../contracts/src/), [policy](../packages/py-core/src/treasurypilot_core/policy/) |
| Data/API | [DATA_MODEL](DATA_MODEL.md), [API_SPEC](API_SPEC.md), [migrations](../services/api/migrations/versions/) |
| AI | [AI_AGENT_ARCHITECTURE](AI_AGENT_ARCHITECTURE.md), [agent code](../services/worker/src/treasurypilot_worker/agent/) |
| Quyết định v0.3 | [ADR-019](adr/ADR-019-aave-liquidity-and-payment-options.md), [tab 37](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.85x0bmmbqru0) |
| Vận hành/test/rủi ro | [infra](../infra/), [evidence](evidence/), [security](security/), [submission](submission/) |

**Quy tắc cập nhật:** ghi commit và ngày mới; đối chiếu route/schema/contract với source; chạy lại test/eval và gắn report theo đúng revision; xác minh manifest với chain tại block ghi nhận; tách “code có”, “test local có”, “public tx có” và “đã được audit”. Bản Markdown này là nguồn biên tập cho site đa trang trong `docs/report_site/`.

Khi nguồn mâu thuẫn, ưu tiên source code và artifact có revision/ngày/môi trường xác định cho trạng thái kỹ thuật; Google Docs hữu ích cho mục tiêu và bối cảnh nhưng có thể phản ánh kế hoạch cũ. Link report nên giữ tương đối trong repo để site build kiểm tra được. Mọi con số cần trỏ tới artifact nêu tập dữ liệu, môi trường và giới hạn, không chỉ trỏ tới code tổng quát.

**Câu hỏi kiểm chứng tiếp:** Mỗi claim quan trọng trong bản phát hành có nguồn, revision, môi trường và người xác minh chưa? Khi code thay đổi, quy trình nào đánh dấu artifact cũ là stale và cập nhật bản dịch/site?
