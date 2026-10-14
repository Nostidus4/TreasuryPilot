# TreasuryPilot: Hướng dẫn phân công

**Nguồn chuẩn:** `planning/ASSIGNMENT_GUIDE.md` · **Trạng thái:** Sẵn sàng phân công (11/10/2026). Spec của cả 20 module đã chốt (tab 16–35). Đây chỉ là **gợi ý** chia luồng; trưởng nhóm tự phân người qua trường **Owner** trên GitHub Project.

Đã xong (PR #254): DEV-001, DEV-002, DEV-003, DEV-005, DEV-011, SC-001, WEB-001.

## 1. Gợi ý chia luồng

| Luồng | Module | Ticket M1 còn mở / ngày công | Trong đó Tier A |
|---|---|---|---|
| **A · Chain & thực thi** (dev 1) | M04 contract (kể cả Aave supply/withdraw), M06 đọc chain, M07 engine (kể cả công thức dự trữ), M08 policy, M10 thực thi, M11 xác minh, M12 phục hồi | 78 / 61 | 61 / 49 |
| **B · Sản phẩm, API, giao diện & AI** (dev 2) | M01 định danh, M02 treasury, M03 mandate, M05 hóa đơn, M09 AI, M13 thông báo, M14 tuân thủ, M15 audit, M16 web, M17 giám sát, M19 devex | 104 / 85.5 | 63 / 52.5 |
| **C · Nghiệp vụ & bằng chứng** (3 cố vấn + anh Phúc) | M20, chia theo tab 35 §2 | 17 / 14 | 11 / 10 |

Lý do: luồng A là đường đi của tiền, phải đúng trước (contract → validator → signer → executor), chủ yếu Python/Solidity. Luồng B là mọi thứ người dùng chạm vào. Hai luồng gặp nhau ở các "hợp đồng" đã viết sẵn trong spec: ABI và vector EIP-712 (SC-017), mô hình snapshot và quyết định (CHR-002, POL-001), client OpenAPI (DEV-005). Luồng B nhiều việc hơn; nếu luồng A xong sớm thì nhận các ticket AGT (AI) trước.

## 2. Làm được ngay (mọi ticket chặn đã xong)

### Luồng A
| Issue | ID | Ticket | Prio | Size | Cut |
|---|---|---|---|---|---|
| #42 | ENG-001 | Create py-core money types and domain models | P0 | M | A |
| #131 | EXE-002 | Set up Celery with core and ai queues | P0 | M | A |
| #28 | SC-002 | Define module storage, structs, EIP-712 domain, errors and events | P0 | M | A |

### Luồng B
| Issue | ID | Ticket | Prio | Size | Cut |
|---|---|---|---|---|---|
| #32 | IDN-001 | Create identity database schema and migrations | P0 | S | A |
| #192 | CMP-003 | Implement data classification, encryption helpers and log redaction | P0 | M | B |
| #25 | DEV-004 | Add CI workflow for contracts | P1 | S | B |

### Luồng C
| Issue | ID | Ticket | Prio | Size | Cut |
|---|---|---|---|---|---|
| #70 | DOM-001 | Verify Ethereum Sepolia infrastructure (owner: Nostidus4) | P0 | S | A |
| #177 | DOM-005 | Author planner scenarios with ground truth (≥30) | P0 | L | A |
| #179 | DOM-006 | Author the red-team invoice set (20) | P0 | M | A |
| #232 | DOM-008 | Review business rules and demo limits from a finance view | P0 | S | A |
| #233 | DOM-009 | Review the threat model and write the known-risk list | P0 | M | A |
| #231 | DOM-003 | Ask the organizers whether testnet evidence is accepted | P1 | S | A |
| #175 | DOM-004 | Author the labelled invoice dataset (30) | P0 | M | B |
| #234 | DOM-010 | Run customer interviews (2–3) | P1 | M | B |
| #239 | DOM-015 | Write the compliance positioning note and license inventory | P1 | S | B |
| #241 | DOM-017 | Choose the repository license | P1 | S | After submission |
| #240 | DOM-016 | Update the FigJam board from the repo diagrams | P2 | S | After submission |

Sau đó đi theo thứ tự ở mục 13 của từng module và các đợt trong tab 15. Trong một luồng: Tier A trước Tier B, P0 trước P1.

## 3. Cách phân công và làm việc

1. Trên GitHub Project, điền **Owner** (tên người) và đặt **Status = Assigned** cho ticket của từng người; bắt đầu làm thì chuyển **In Progress**.
2. Nhánh `feat/<ticket-id>-ten-ngan`; mô tả PR ghi `Closes #<số issue>`; hoàn thành checklist trong PR template.
3. Merge PR là issue tự đóng; dashboard tự tính issue đã đóng là Xong (muốn đồng bộ trường Status thì chạy `python3 planning/tools/sync_closed_status.py` hoặc bật workflow "Item closed → Done" của Project).
4. Spec là nguồn chuẩn: nếu khi code cần quyết định khác, sửa mục 14 của module và `docs/decisions-log.md` ngay trong PR đó.
5. Hằng ngày xem dashboard Google Sheet (tự cập nhật mỗi giờ): tiến độ theo module và theo người.

**Cập nhật v0.3 (ADR-019):** ticket mới SC-023 (bản duyệt hai mức tiền), SC-024 (Aave supply/withdraw), SC-025 (test trên fork Sepolia), ENG-013 (công thức dự trữ), EXE-014 (chu kỳ thanh khoản), DEV-012 (cổng cấu hình) đều thuộc Tier A; ENG-014 và WEB-027 (đề xuất vay) Tier B; SC-026 và MDT-011 (thực thi vay/trả) là P2. WEB-026 (thẻ vị thế quỹ) Tier A.

## 4. Phân công thực tế (trưởng nhóm chốt 11/10/2026)

| Mảng | Người làm | Module / ticket | Người review mặc định |
|---|---|---|---|
| Frontend | **Nostidus4** (Tân) | WEB | therealtunguyen |
| Backend (phục vụ web và nghiệp vụ) | **Nostidus4** (Tân) | IDN, TRS, MDT, INV, ENG, REC, RCV, NTF, CMP, AUD (75 ticket, 57 ngày công, 72 %) | therealtunguyen |
| Backend (lõi thực thi) | **therealtunguyen** (Tú) | EXE, POL, CHR (27 ticket, 22,5 ngày công, 28 %) | Nostidus4 |
| Hạ tầng | **therealtunguyen** | DEV, OBS | Nostidus4 (mặc định, đổi được) |
| AI | **therealtunguyen** | AGT | Nostidus4 (mặc định, đổi được) |
| Blockchain | **longhuynh55** (anh Phúc) | SC | Nostidus4 (mặc định, đổi được) |
| Non-code | chia sau | DOM | – |

Cập nhật 12/10/2026: chuyển khoảng 30 % backend (lõi thực thi: EXE, POL, CHR) cho Tú; Tân giữ phần backend phục vụ web. Đã gán trên GitHub: assignee của issue, trường **Owner** và Status **Assigned** trên Project (182 ticket code M1 còn mở). Người review mặc định nằm trong `.github/CODEOWNERS`, GitHub tự mời review khi mở PR. Chạy lại `python3 planning/tools/assign.py` sau khi thêm ticket mới.

Bàn giao 14/10/2026: **DOM-001 (#70) → @Nostidus4 (Tân)**, chủ repo giữ quyền truy cập hạ tầng. Tân phụ trách kiểm RPC/API/dịch vụ Sepolia và bằng chứng giao dịch Safe; @longhuynh55 hỗ trợ tích hợp contract. Phân công các mảng khác và DOM-002 giữ nguyên.
