# M06 · Đọc chain & theo dõi giao dịch

**Nguồn chuẩn:** `docs/modules/chain-reader/README.md` · **Trạng thái:** Chi tiết (grilling M06, 11/10/2026) · **ADR:** ADR-012, ADR-004

## 1. Mục đích và ranh giới

M06 là **cửa sổ duy nhất của hệ thống nhìn vào chain**. Mọi module khác đọc dữ liệu chain qua nó: snapshot để lập kế hoạch và kiểm tra, trạng thái giao dịch để thực thi, event để đồng bộ, lịch sử phí cho chính sách phí. M06 không bao giờ ký hay gửi gì.

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| RPC client có dự phòng và nguồn thứ hai để đối chiếu | Ký và gửi giao dịch (signer, M10) |
| Snapshot nhất quán theo block (Multicall3, ghim block) | Quyết định cho/chặn (M08) |
| Theo dõi giao dịch: Submitted → Pending → Confirmed / Reverted / Unknown, giao dịch thay thế | Phục hồi Unknown (M12) |
| Phát hiện reorg (quét lại 64 block) | Logic đối soát (M11) |
| Đọc event: module, cấu hình Safe, thực thi Safe, `Transfer` ERC-20 của ví treasury | Phản ứng nghiệp vụ với event (M03, M05, M12 đăng ký nhận) |
| Phát hiện tiền ra không qua agent (M06-D2) | Oracle giá (Later) |
| Lịch sử phí cho EXE-012 | |

## 2. Feature, yêu cầu, luật

F-050 (FR-401, FR-402, BR-051, BR-018) · F-070 (FR-601, FR-602, BR-053, BR-060) · F-011/F-012 phía đọc (FR-103, FR-105–107) · F-120 event (FR-510) · tiền ra bất thường **FR-419, BR-069 (mới)**.

## 3. Khái niệm

| Thuật ngữ | Định nghĩa |
|---|---|
| **Head** | Block mới nhất thấy từ RPC chính. |
| **Số xác nhận** | `head − block của receipt + 1`. Confirmed khi ≥ 3 (PH-5, ~36 giây trên Sepolia). |
| **Snapshot** | Mọi giá trị cần cho lập kế hoạch/kiểm tra của một treasury, đọc tại **một** block qua Multicall3, kèm số block, hash, timestamp, coverage và các trường thiếu. |
| **Con trỏ** | Block cuối đã xử lý xong cho mỗi (treasury, luồng event). |
| **Cửa sổ reorg** | 64 block (~2 epoch, finality của Sepolia); event và xác nhận trong cửa sổ được kiểm lại theo block hash. |
| **Tiền ra bất thường** | Lệnh `Transfer` của asset **từ** T/O1/O2 không khớp thao tác nào của ta (M06-D2). |

## 4. Mô hình dữ liệu

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `snapshots` | treasury, purpose (PLAN, PRE_STEP, DASHBOARD, READBACK), block_number, block_hash, block_timestamp, provider, data, coverage, missing | bất biến; DASHBOARD giữ 7 ngày |
| `transactions` | operation, tx_hash, nonce, from, replaced_by, status (Submitted, Pending, Confirmed, Reverted, Dropped, Unknown), block, confirmations, revert_selector, gas, fee_wei, crosscheck (NotRun, Match, Mismatch) | |
| `observed_events` | treasury, stream (MODULE, SAFE_CONFIG, SAFE_EXEC, TOKEN), block, block_hash, tx_hash, log_index, address, event_name, payload, classification, removed | duy nhất (chain, tx_hash, log_index) |
| `index_cursors` *(mới)* | treasury, stream, last_block, last_block_hash | |
| `token_movements` *(mới)* | wallet, direction (IN, OUT), counterparty, amount, class (AGENT, INTERNAL_REFILL, INFLOW, UNEXPECTED_OUTFLOW), operation, người xác nhận | |
| `rpc_health` *(mới)* | provider, ok, latency, head, lỗi cuối | giữ 24 giờ |

## 5. Trạng thái giao dịch

`Submitted` (signer trả hash, đã lưu trước khi gửi) → `Pending` (thấy trong mempool hoặc có receipt chưa đủ xác nhận) → `Confirmed` (status 1, ≥ 3 xác nhận **và** RPC thứ hai khớp) hoặc `Reverted` (status 0, ≥ 3 xác nhận). `Pending → Dropped` (giao dịch khác cùng nonce được đào, liên kết replaced_by). `Submitted/Pending → Unknown` (10 phút không có receipt và không còn trong mempool, hoặc hai RPC không khớp). Reorg đưa `Confirmed/Reverted` về `Pending`. **Không có Failed.** `Unknown` chặn treasury (BR-060) cho tới khi M12 xử lý dựa trên receipt và `requestPaid`/`stepUsed`.

## 6. Giao diện nội bộ

| Hàm | Kết quả |
|---|---|
| `rpc.call(method, params, critical)` | thử các RPC theo thứ tự, timeout 4 giây, mỗi RPC thử 2 lần rồi chuyển; lỗi hết thì `RpcUnavailable` (không bao giờ trả giá trị mặc định) |
| `rpc.crosscheck_receipt(tx_hash)` | đọc receipt + block hash từ RPC thứ hai: Match / Mismatch / Unavailable |
| `snapshot(treasury, purpose, block)` | §8.1 |
| `is_fresh(snapshot, now, head)` | ≤ 30 giây và chậm ≤ 2 block |
| `track(tx_id)` | task Celery mỗi 6 giây khi Submitted/Pending |
| `index(treasury)` | Celery beat mỗi 6 giây, §8.3 |
| `fee_history(20 block, phân vị 25/50/75)` | cho EXE-012 |
| `safe_config(safe)` | owners, threshold, modules, guard, fallback handler, nonce |
| Đăng ký nhận event | handler của M03 (payee, mandate, pause, ngoại lệ, hủy, giao dịch quản trị), M05, M12 |

## 7. Luồng

**Xác nhận thanh toán:** mỗi 6 giây tracker hỏi RPC chính receipt và block hiện tại. Chưa có receipt → hỏi mempool. Có receipt và ≥ 3 xác nhận → hỏi RPC thứ hai receipt + block hash. Khớp → Confirmed (status 1) hoặc Reverted (status 0, giải mã selector). Không khớp hoặc không đọc được → giữ Pending; quá 10 phút → Unknown + review item.

**Tiền ra bất thường (M06-D2):** thấy `Transfer(from = O1, to = X, 500)` → không khớp thao tác nào (cùng tx hash) → `UNEXPECTED_OUTFLOW` → báo Owner và Finance → nếu treasury đang chạy plan thì yêu cầu kiểm lại PRE_STEP ngay (bắt ví dụ 10 của M08 tức thì) → gửi tín hiệu cho circuit breaker. Owner có thể xác nhận ("tôi tự rút").

## 8. Thuật toán

**8.1 Bộ đọc snapshot (một lệnh Multicall3 `aggregate3` tại block B):** `balanceOf(T, O1, O2)`; `decimals()` (cache); module `mandate()`, `status()`, `usedToday(PAY/REFILL)`, `bufferOf/targetOf` của T/O1/O2, `isApprover` của approver đã biết; với các request liên quan: `payeeStatus`, `requestPaid`, `requestCancelled`, `stepUsed`, `fingerprintPaid`, `refilledFor`, `exceptions`, `duplicateAllowedFor`; Safe: modules, guard (đọc slot), owners, threshold, nonce. B = head lúc gọi, gọi với `blockTag = B`, lưu hash và timestamp của B. Lệnh con lỗi → ghi vào `missing`; snapshot vẫn lưu (M08 chặn bằng `DATA_MISSING`).

**8.2 Luật tracker:** hỏi mỗi 6 giây; Confirmed khi 3 xác nhận **và** RPC thứ hai khớp; RPC thứ hai không có → thử tới 10 phút rồi Unknown. Giao dịch thay thế cùng `(from, nonce)` được đào → bản gốc `Dropped`, liên kết `replaced_by`. Revert → giải mã selector bằng `decode_revert` của POL-001. Ngày tính theo **timestamp của block đã đào** (BR-026).

**8.3 Đọc event và xử lý reorg (PH-6):** với mỗi luồng [MODULE, SAFE_CONFIG, SAFE_EXEC, TOKEN]: `from = con trỏ − 64`, `to = head`; `eth_getLogs` theo địa chỉ và topic, chia khúc ≤ 2.000 block; upsert theo (chain, tx_hash, log_index), lưu block hash; event đã lưu trong khoảng mà không còn trả về hoặc khác block hash → `removed = true`, gọi handler "removed"; cập nhật con trỏ. Luồng TOKEN lọc `Transfer` của asset với topic1 ∈ {T, O1, O2} **hoặc** topic2 ∈ {T, O1, O2}. Phân loại: tx hash khớp thao tác của ta → AGENT (T→O là INTERNAL_REFILL); đích là ví treasury, nguồn không phải → INFLOW; còn lại là tiền ra → UNEXPECTED_OUTFLOW.

**8.4 Ví dụ:** O1 = 110 sau refill (block 100). Block 103: Owner chuyển 50 ra khỏi O1 qua Safe. Khoảng block 104 indexer thấy `Transfer(O1 → owner, 50)`, không khớp thao tác → UNEXPECTED_OUTFLOW; plan đang chạy được kiểm lại ngay → PAY 100 từ 60 vi phạm buffer 10 → BLOCK, PartiallyCompleted, review item; Owner nhận một thông báo gộp.

## 9. Cấu hình

| Tham số | Giá trị |
|---|---|
| Chain | Ethereum Sepolia 11155111 (block 12 giây) |
| RPC | Alchemy (chính), RPC Sepolia công khai, ví dụ publicnode (phụ) |
| Timeout / thử lại | 4 giây / 2 lần mỗi RPC |
| Số xác nhận | 3 |
| Chu kỳ tracker / indexer | 6 giây |
| Chuyển Unknown sau | 10 phút |
| Cửa sổ reorg | 64 block |
| Khúc getLogs | 2.000 block |
| Độ tươi snapshot | ≤ 30 giây và ≤ 2 block |
| Snapshot dashboard | mỗi 60 giây, giữ 7 ngày |
| Multicall3 | `0xcA11bde05977b3631167028862bE2a173976CA11` |

## 10. Bảo mật

| Mối đe dọa | Biện pháp | Test |
|---|---|---|
| RPC nói dối/chậm làm báo Đã trả sai | đối chiếu RPC thứ hai trước Confirmed; lệch thì không bao giờ Paid | CHR-003 với RPC giả |
| Dùng dữ liệu cũ để quyết định | ghim block + kiểm độ tươi; M08 chặn dữ liệu cũ | test độ tươi |
| Reorg để lại Paid sai | quét lại 64 block, hạ trạng thái theo block hash | mô phỏng reorg trên Anvil |
| Tiền bị chuyển ngoài agent | luồng TOKEN + cảnh báo + kiểm lại ngay | test §8.4 |
| Event giả từ contract khác | lọc log theo đúng địa chỉ (module clone, Safe, asset) | test lọc địa chỉ |
| Trả giá trị mặc định khi RPC lỗi | ném `RpcUnavailable`; không bao giờ số dư 0 giả | unit |

## 11. Tình huống lỗi

RPC chính lỗi → chuyển sang RPC phụ, đối chiếu đánh dấu Unavailable (Confirmed phải chờ) · mọi RPC lỗi → snapshot lỗi → M08 `SNAPSHOT_STALE`/`DATA_MISSING` → không thực thi; tracker tiếp tục thử; không gì chuyển Failed · khoảng getLogs quá lớn → chia đôi và thử lại · worker khởi động lại → con trỏ đã lưu, cửa sổ quét lại bù khoảng trống · reorg sâu > 64 block → không tự xử lý (finality Sepolia); đối soát M11 kiểm `finalized` sẽ gắn cờ.

## 12. Kế hoạch test

Unit: chuyển RPC, không trả mặc định, luật phân loại, độ tươi (CHR-001, CHR-006). Integration (Anvil): snapshot cùng một block; các trạng thái tracker gồm thay thế và giải mã revert; đối chiếu lệch; indexer không tạo trùng (CHR-002, 003, 005). Reorg: `anvil_snapshot`/`revert` + đào lại để đổi block hash → Confirmed bị hạ, event bị đánh dấu removed (CHR-004). E2E: tiền ra bất thường giữa plan (§8.4, CHR-006 + EXE-008).

## 13. Ticket theo thứ tự

CHR-001 RPC client (+ đối chiếu) → CHR-002 snapshot (Multicall3) → CHR-003 tracker → CHR-005 indexer → CHR-004 reorg → **CHR-006 dòng tiền token và tiền ra bất thường (mới)**.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M06-D1 | Đối chiếu RPC thứ hai chỉ ở điểm quan trọng: trước Confirmed/Paid và khi đọc lại mandate; lệch → Pending/Unknown hoặc Discrepancy. |
| M06-D2 | Đọc `Transfer` ERC-20 của asset vào/ra T/O1/O2; phân loại AGENT / INTERNAL_REFILL / INFLOW / UNEXPECTED_OUTFLOW; tiền ra bất thường thì cảnh báo và kiểm lại ngay (BR-069). |
| M06-D3 | Snapshot qua Multicall3 ghim một block; lệnh con lỗi ghi vào missing. |
| M06-D4 | "Hôm nay" của validator = ngày UTC theo timestamp block mới nhất, không dùng giờ server. |
| M06-D5 | Unknown sau 10 phút không có receipt và không trong mempool; không bao giờ Failed. |
| M06-D6 | Event cấu hình Safe kích hoạt tính lại coverage; coverage giảm thì báo circuit breaker. |
| M06-D7 | Snapshot của plan bất biến; snapshot dashboard mỗi 60 giây, giữ 7 ngày. |
| M06-D8 | Tracker và indexer chạy mỗi 6 giây; khúc getLogs ≤ 2.000 block. |
| M06-D9 | Lọc log theo đúng địa chỉ (module clone, Safe, asset). |
| M06-D10 | Thay đổi trạng thái đẩy ra giao diện qua SSE (M13). |
| PH-5/6/8 | 3 xác nhận; gọi getLogs định kỳ có quét lại 64 block; Alchemy + RPC công khai. |

## 15. Thay đổi theo v0.3 (ADR-019)

Snapshot đọc thêm (cùng block): số aToken của Safe T, thanh khoản còn trong pool, `getReserveData` (lãi suất gửi/vay), `getUserAccountData` (health factor, nợ). Indexer đọc thêm event `Supplied`, `Withdrawn` (`BorrowExecuted`, `Repaid`). Chuyển tiền giữa Safe T và aToken được phân loại `LENDING`, không phải tiền ra bất thường.
