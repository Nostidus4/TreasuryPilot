# M17 · Giám sát & phân tích

**Nguồn chuẩn:** `docs/modules/observability/README.md` · **Trạng thái:** Chi tiết — quyết định đã chốt (trưởng nhóm ủy quyền cho tech lead, 11/10/2026) · **ADR:** ADR-011

## 1. Mục đích và ranh giới

M17 giúp team **thấy hệ thống đang làm gì** (log, trace, lỗi, metric) và giúp khách hàng, giám khảo **thấy hệ thống đạt được gì** (chỉ số vận hành và tiết kiệm so với baseline theo luật).

| Trong phạm vi (M1) | Ngoài phạm vi |
|---|---|
| Log JSON có correlation id xuyên api/worker/signer | Dashboard host sẵn (Grafana) ngoài một service compose cơ bản (tùy chọn) |
| Tracing OpenTelemetry (FastAPI, Celery, httpx, SQLAlchemy, lời gọi signer) | Metric tính tiền (M18, Later) |
| Sentry (Python + web) và Prometheus `/metrics` | |
| API chỉ số vận hành và báo cáo tiết kiệm | |

## 2. Feature, yêu cầu

F-140 (FR-921), F-141 (FR-922), F-142 (FR-923, NFR-AUD-04).

## 3. Định nghĩa chỉ số

| Chỉ số | Định nghĩa |
|---|---|
| Tỷ lệ hoàn thành | request Paid ÷ request đã vào `Scheduled` trong kỳ (không tính request người dùng từ chối/hủy; có tính request bị policy chặn) |
| Tỷ lệ đúng hạn | Paid có thời gian block PAY ≤ 23:59:59 UTC ngày đến hạn ÷ Paid |
| Can thiệp mỗi request | số thao tác của người sau khi duyệt (review, chấp nhận phí, cấp ngoại lệ, duyệt lại) ÷ Paid |
| Phí | Σ fee_wei (kể cả revert) theo request và theo kỳ; theo loại bước |
| Độ trễ theo giai đoạn | duyệt→lập lịch, lập lịch→ký attestation, ký→gửi bước đầu, gửi→xác nhận, xác nhận→xác minh (trung vị, p90) |
| Lý do bị chặn | số BLOCK theo mã chính; revert của contract theo selector |
| Tiết kiệm so B1 | Σ trên các lô đã chạy `giá trị(thực tế) − giá trị(B1 giả định)` dùng snapshot và đầu vào lịch đã lưu (chiết khấu nhận − phí trễ − phí gas khi trả sớm, FEE-2); số âm vẫn báo |

## 4. Mô hình dữ liệu

Không có bảng nghiệp vụ mới: chỉ số tính từ `request_status_events`, `plans`, `operations`, `transactions`, `gas_ledger`, `validations`, `review_items`, `schedules`; có thể dùng materialized view làm mới mỗi 15 phút.

## 6. Giao diện

GET `/metrics/operations?from=&to=&treasuryId=` (OWN, FIN, ADM, Auditor) · GET `/metrics/savings?from=&to=` → `{total, byRequest[], methodology}` (OWN, FIN) · GET `/metrics` (Prometheus, chỉ mạng nội bộ). Series Prometheus: `tp_queue_depth`, `tp_rpc_errors_total`, `tp_rpc_latency_seconds`, `tp_llm_latency_seconds`, `tp_llm_cost_usd_total`, `tp_tx_status_total`, `tp_validation_decisions_total`, `tp_unknown_operations`, `tp_executor_gas_eth`, `tp_circuit_trips_total`.

## 7. Luồng

Mỗi request/task gắn `correlation_id`, `org_id`, `request_id`, `plan_id`, `operation_id` vào ngữ cảnh structlog; header Celery mang theo; signer nhận qua header. Trace xuất qua OTLP tới collector (service compose; local in ra console).

## 8. Thuật toán

Tiết kiệm giả định: với mỗi ngày lô đã chạy, chạy lại `schedule_edf` trên snapshot đã lưu với cùng request; tính giá trị mục tiêu của B1 và của plan thực tế bằng `request_value` của M07; tiết kiệm = thực tế − B1 theo request; văn bản phương pháp sinh kèm số liệu.

## 9. Cấu hình

Log mức INFO (local DEBUG); lấy mẫu 100 % trace ở M1 (lưu lượng thấp); Sentry DSN mỗi service từ secret; lỗi nghiêm trọng của Sentry báo qua Telegram (dùng M13).

## 10. Bảo mật

Processor che log (M14) chạy trước mọi đích ghi; `/metrics` không công khai (Caddy chặn); không có PII trong nhãn metric.

## 11. Tình huống lỗi

Sentry/collector lỗi → log vẫn có ở local, app không bị ảnh hưởng (exporter không chặn).

## 12. Kế hoạch test

Tìm được correlation id trong log api/worker/signer cho một request; một lần lập kế hoạch tạo đúng một trace; định nghĩa chỉ số được test trên dữ liệu mẫu; tiết kiệm bằng số tính tay cho một lô; tiết kiệm âm vẫn hiển thị.

## 13. Ticket

OBS-001 → OBS-002 → OBS-003 → OBS-004 → OBS-005.

## 14. Quyết định

| ID | Quyết định |
|---|---|
| M17-D1 | Correlation id gắn khắp nơi, kể cả header Celery và signer. |
| M17-D2 | Định nghĩa §3 là nguồn chuẩn cho deck. |
| M17-D3 | Tiết kiệm so B1 tính từ snapshot đã lưu; số âm vẫn báo. |
| M17-D4 | Gas khi trả sớm tính trừ vào tiết kiệm (FEE-2). |
| M17-D5 | Danh sách series §6; không PII trong nhãn. |
| M17-D6 | Lấy mẫu 100 % trace ở M1. |
| M17-D7 | Dùng materialized view làm mới 15 phút nếu truy vấn chậm. |
| M17-D8 | Grafana tùy chọn, không bắt buộc ở M1. |
| M17-D9 | `/metrics` chỉ nội bộ. |
