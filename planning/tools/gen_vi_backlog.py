"""Regenerate docs/vi/15-backlog.md (Vietnamese backlog tab) from the ticket data."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import gen_issues as G
from data import TICKETS, MODULES
from data.cut import tier

ROOT = pathlib.Path(__file__).resolve().parents[2]
D = {"S": 0.5, "M": 1, "L": 2}
VI_STATUS = {"Ready for Assignment": "Sẵn sàng phân công", "Accepted": "Đã chấp nhận (Later)"}

def main():
    W = G.waves()
    BY = {t["id"]: t for t in TICKETS}
    m1 = [t for t in TICKETS if t["phase"] == "M1"]; later = [t for t in TICKETS if t["phase"] != "M1"]
    cnt = lambda p: sum(1 for t in m1 if t["prio"] == p)
    L = ["# TreasuryPilot: Backlog & phụ thuộc", "",
         "**Nguồn chuẩn:** `planning/BACKLOG.md`, `planning/DEPENDENCIES.md`, `planning/issues/` · **Trạng thái:** Đã qua G3; cập nhật sau grilling các module (11/10/2026)", "",
         "Tiêu đề ticket giữ tiếng Anh vì GitHub issue viết bằng tiếng Anh (Q4). Mỗi ticket có file riêng trong `planning/issues/<module>/` và một issue trên GitHub Project #1.", "",
         "## 1. Tổng số", "",
         "| Phase | P0 | P1 | P2 | Tổng |", "|---|---:|---:|---:|---:|",
         f"| M1 (bản thi) | {cnt('P0')} | {cnt('P1')} | {cnt('P2')} | {len(m1)} |",
         f"| Later | – | – | – | {len(later)} |",
         f"| **Tất cả** | | | | **{len(TICKETS)}** |", "",
         "Kích thước: S ≤ 0,5 ngày · M khoảng 1 ngày · L 1,5–2 ngày. Cut: A = bắt buộc cho bản demo nộp bài (khép kín phụ thuộc), B = nên có, còn lại làm sau khi nộp.", "",
         "## 2. Epic theo module", "",
         "| Epic | Module | Ticket M1 | Tier A | Ticket Later | Ước tính công M1 (ngày) |", "|---|---|---:|---:|---:|---:|"]
    for p, (folder, _, mnum, name) in MODULES.items():
        ts = [t for t in TICKETS if t["id"].startswith(p + "-")]
        a = [t for t in ts if t["phase"] == "M1"]
        L.append(f"| {mnum} · {name} | `{folder}` | {len(a)} | {sum(1 for t in a if tier(t['id'])=='A')} | {len(ts)-len(a)} | {sum(D[t['size']] for t in a):g} |")
    L += ["", "## 3. Toàn bộ ticket", "",
          "| ID | Module | Ticket | Feature | Phase | Ưu tiên | Cỡ | Cut | Phụ thuộc | Trạng thái |", "|---|---|---|---|---|---|---|---|---|---|"]
    for t in TICKETS:
        cut = tier(t["id"]) if t["phase"] == "M1" else "Later"
        L.append(f"| {t['id']} | {MODULES[G.prefix(t)][0]} | {t['title']} | {t['feats']} | {t['phase']} | {t['prio']} | {t['size']} | {cut} | {', '.join(t['deps']) or '—'} | {VI_STATUS[G.status(t)]} |")
    L += ["", "## 4. Các đợt thực hiện (M1)", "", "Ticket trong cùng một đợt không chặn nhau nên **làm song song được**.", "",
          "| Đợt | Số ticket |", "|---|---:|"]
    for i, w in enumerate(W, 1): L.append(f"| {i} | {len(w)} |")
    chain = open(ROOT / "planning/DEPENDENCIES.md").read().split("## 4. Longest blocking chain")[1].strip().splitlines()[-1]
    L += ["", "## 5. Chuỗi phụ thuộc dài nhất", "", "Bất kỳ ticket nào trên chuỗi này trễ thì cuối M1 trễ theo:", "", chain, ""]
    (ROOT / "docs/vi/15-backlog.md").write_text("\n".join(L))
    print("vi backlog", len(TICKETS))

if __name__ == "__main__": main()
