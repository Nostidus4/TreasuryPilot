"""Create editable draw.io sources for the technical report.

Run this script after changing the diagrams below, then export with draw.io:
  draw.io -x -f svg -o <name>.svg <name>.drawio
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
INK = "#25343B"
MUTED = "#566970"
LINE = "#B9C9CA"
TEAL = "#205C62"
TEAL_LIGHT = "#EAF2F1"
SAND = "#F7F2E9"
WHITE = "#FFFFFF"


class Diagram:
    def __init__(self, name: str, width: int = 1120, height: int = 580):
        self.name = name
        self.mxfile = ET.Element("mxfile", {"host": "app.diagrams.net", "type": "device", "version": "24.7.17"})
        page = ET.SubElement(self.mxfile, "diagram", {"id": name, "name": name.replace("-", " ").title()})
        graph = ET.SubElement(page, "mxGraphModel", {
            "dx": "1400", "dy": "900", "grid": "1", "gridSize": "10", "guides": "1", "tooltips": "1",
            "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1",
            "pageWidth": str(width), "pageHeight": str(height), "math": "0", "shadow": "0",
        })
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})

    def box(self, key: str, label: str, x: int, y: int, w: int, h: int, *, fill: str = WHITE,
            stroke: str = LINE, color: str = INK, size: int = 16, bold: bool = False) -> None:
        style = ("rounded=0;whiteSpace=wrap;html=0;align=center;verticalAlign=middle;"
                 f"fillColor={fill};strokeColor={stroke};fontColor={color};fontSize={size};"
                 f"fontStyle={1 if bold else 0};fontFamily=Helvetica;spacing=8;")
        cell = ET.SubElement(self.root, "mxCell", {"id": key, "value": label, "style": style,
                                                    "vertex": "1", "parent": "1"})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w),
                                               "height": str(h), "as": "geometry"})

    def label(self, key: str, value: str, x: int, y: int, w: int, h: int = 28,
              *, color: str = MUTED, size: int = 13, bold: bool = False) -> None:
        style = ("text;html=0;align=left;verticalAlign=middle;whiteSpace=wrap;overflow=visible;"
                 f"fontColor={color};fontSize={size};fontStyle={1 if bold else 0};fontFamily=Helvetica;")
        cell = ET.SubElement(self.root, "mxCell", {"id": key, "value": value, "style": style,
                                                    "vertex": "1", "parent": "1"})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w),
                                               "height": str(h), "as": "geometry"})

    def edge(self, key: str, source: str, target: str, *, label: str = "", dashed: bool = False,
             color: str = TEAL, arrow: bool = True, anchors: str = "") -> None:
        style = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
                 f"html=0;strokeColor={color};strokeWidth=2;endArrow={'block' if arrow else 'none'};"
                 f"endFill=1;dashed={1 if dashed else 0};fontColor={MUTED};fontSize=12;"
                 f"labelBackgroundColor=#FFFFFF;{anchors}")
        cell = ET.SubElement(self.root, "mxCell", {"id": key, "value": label, "style": style,
                                                    "edge": "1", "parent": "1", "source": source, "target": target})
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    def write(self) -> None:
        ET.indent(self.mxfile, space="  ")
        ET.ElementTree(self.mxfile).write(HERE / f"{self.name}.drawio", encoding="utf-8", xml_declaration=True)


def architecture() -> None:
    d = Diagram("system-architecture", 1180, 660)
    d.label("title", "01 / DEPLOYMENT & DATA FLOW", 35, 20, 700, 32, color=TEAL, size=14, bold=True)
    d.label("userlab", "USER & APPLICATION", 35, 80, 300, bold=True)
    d.label("servicelab", "CONTROL PLANE", 400, 80, 300, bold=True)
    d.label("chainlab", "EXECUTION PLANE", 800, 80, 300, bold=True)
    d.box("browser", "Browser / React\nConnected wallet", 35, 125, 265, 85, fill=TEAL_LIGHT, stroke=TEAL, bold=True)
    d.box("api", "FastAPI\nSession · RBAC · requests", 400, 125, 280, 85, fill=TEAL_LIGHT, stroke=TEAL, bold=True)
    d.box("db", "PostgreSQL\nState · plans · outbox · audit", 400, 285, 280, 80, fill=SAND)
    d.box("redis", "Redis / Celery\nTask dispatch", 400, 445, 280, 80, fill=SAND)
    d.box("ai", "AI worker\nRead-only tools · proposals", 35, 285, 265, 80)
    d.box("core", "Core worker + py-core\nDeterministic engine · policy", 800, 125, 310, 85, fill=TEAL_LIGHT, stroke=TEAL, bold=True)
    d.box("signer", "Isolated signer\nValidate · simulate · submit", 800, 285, 310, 80, fill=SAND)
    d.box("chain", "TreasuryPilotModule + Safes\nAave / EAS integrations", 800, 445, 310, 80, fill=TEAL_LIGHT, stroke=TEAL, bold=True)
    d.edge("e1", "browser", "api")
    d.edge("e2", "api", "db", arrow=False)
    d.edge("e3", "api", "core")
    d.edge("e4", "api", "ai", dashed=True, color=MUTED,
           anchors="exitX=0;exitY=0.85;entryX=1;entryY=0.15;exitDx=0;exitDy=0;entryDx=0;entryDy=0;")
    d.edge("e5", "core", "signer")
    d.edge("e6", "signer", "chain")
    d.edge("e7", "db", "redis", arrow=False)
    d.label("foot", "AI is advisory. PostgreSQL is the business record of truth; Redis dispatches work.", 35, 570, 1060, 44, size=13)
    d.write()


def payment_flow() -> None:
    d = Diagram("payment-flow", 1160, 580)
    d.label("title", "02 / REQUEST TO VERIFIED PAYMENT", 35, 20, 700, 32, color=TEAL, size=14, bold=True)
    steps = [
        ("intake", "01  Invoice intake\nFields · terms · flags", 35, 125),
        ("approve", "02  Human approval\nExact EIP-712 obligation", 260, 125),
        ("plan", "03  Deterministic plan\nFresh balances + mandate", 485, 125),
        ("policy", "04  Policy gate\nALLOW → execute\nNEEDS_APPROVAL / BLOCK → hold", 710, 125),
        ("execute", "05  Signer + module\nRecheck and submit", 935, 125),
    ]
    for key, label, x, y in steps:
        d.box(key, label, x, y, 190, 102, fill=TEAL_LIGHT if key in {"approve", "execute"} else WHITE,
              stroke=TEAL if key in {"approve", "execute"} else LINE, size=14, bold=True)
    for a, b in zip(steps, steps[1:]):
        d.edge(f"e-{a[0]}-{b[0]}", a[0], b[0])
    d.box("hold", "Hold or block\nNo transaction submitted", 710, 350, 190, 100, fill=WHITE, size=14, bold=True)
    d.box("track", "06  Receipt + reconciliation\nVerify effects · evidence", 935, 350, 190, 100, fill=SAND, size=14, bold=True)
    d.edge("e-hold", "policy", "hold")
    d.edge("e-final", "execute", "track")
    d.label("guard", "GATE", 35, 340, 120, bold=True, color=TEAL)
    d.label("guardtxt", "No approval → no executable obligation.\nUnknown receipt → reconcile before retry.\nAI proposal → never a spending authorization.", 35, 375, 595, 95, size=16)
    d.write()


def authority() -> None:
    d = Diagram("authority-boundaries", 1130, 570)
    d.label("title", "03 / AUTHORITY IS CHECKED AT EACH BOUNDARY", 35, 20, 850, 32, color=TEAL, size=14, bold=True)
    rows = [
        ("human", "Human approver", "Signs payee, asset, amount options, deadline and request", 105, TEAL_LIGHT),
        ("policy", "Policy validator", "Checks mandate, balances, caps, floor and chain snapshot", 210, WHITE),
        ("signer", "Isolated signer", "Verifies attestation and calldata; simulates current state", 315, SAND),
        ("module", "On-chain module", "Rechecks authority, payee, caps, floor and replay", 420, TEAL_LIGHT),
    ]
    for key, title, detail, y, fill in rows:
        d.box(key, title, 40, y, 250, 68, fill=fill, stroke=TEAL if key in {"human", "module"} else LINE,
              bold=True, size=17)
        d.box(f"{key}-detail", detail, 350, y, 700, 68, fill=fill, stroke=LINE, size=15)
    for a, b in zip(rows, rows[1:]):
        d.edge(f"e-{a[0]}", a[0], b[0])
    d.label("foot", "AI has read-only tools; it can propose or explain, but does not sign or authorize transfers.", 40, 510, 1030, 30, size=14)
    d.write()


def liquidity() -> None:
    d = Diagram("liquidity-decision", 1130, 570)
    d.label("title", "04 / LIQUIDITY DECISION", 35, 20, 750, 32, color=TEAL, size=14, bold=True)
    d.box("inputs", "Available inputs\nSafe balance · approved unpaid requests\nFloor · debt reserve · holds · Aave cash", 35, 100, 350, 110, fill=TEAL_LIGHT, stroke=TEAL, bold=True, size=15)
    d.box("reserve", "Required Safe reserve\nPayment + floor + debt + holds", 470, 100, 310, 110, fill=SAND, bold=True, size=15)
    d.box("decision", "Compare Safe balance\nwith required reserve", 470, 290, 310, 85, fill=WHITE, bold=True, size=16)
    d.box("supply", "Surplus\nSupply within cap and minimum", 35, 445, 330, 80, fill=TEAL_LIGHT, stroke=TEAL, size=15)
    d.box("withdraw", "Deficit\nWithdraw up to aToken / pool cash", 405, 445, 330, 80, fill=SAND, size=15)
    d.box("block", "Still short\nInsufficient-liquidity decision", 775, 445, 330, 80, fill=WHITE, stroke=TEAL, size=15)
    d.edge("e1", "inputs", "reserve")
    d.edge("e2", "reserve", "decision")
    d.edge("e3", "decision", "supply", label="surplus")
    d.edge("e4", "decision", "withdraw", label="deficit")
    d.edge("e5", "withdraw", "block", label="uncovered")
    d.label("note", "Dynamic reserve is calculated off-chain; the module enforces static floors and supply caps on-chain.", 35, 540, 1060, 20, size=13)
    d.write()


def recovery() -> None:
    d = Diagram("execution-recovery", 1130, 580)
    d.label("title", "05 / EXECUTION OUTCOME & RECOVERY", 35, 20, 780, 32, color=TEAL, size=14, bold=True)
    d.box("recorded", "Outbox recorded\nStable step ID", 35, 130, 235, 90, fill=TEAL_LIGHT, stroke=TEAL, bold=True)
    d.box("submitted", "Transaction submitted\nHash persisted", 360, 130, 235, 90, fill=SAND, bold=True)
    d.box("observed", "Receipt observed\nConfirmations checked", 685, 130, 235, 90, fill=TEAL_LIGHT, stroke=TEAL, bold=True)
    d.box("unknown", "Unknown outcome\nTimeout / unavailable RPC", 360, 350, 235, 90, fill=WHITE, stroke=TEAL, bold=True)
    d.box("resolve", "Reconcile chain state\nReceipt · nonce · effects", 685, 350, 235, 90, fill=SAND, bold=True)
    d.edge("e1", "recorded", "submitted")
    d.edge("e2", "submitted", "observed", label="receipt")
    d.edge("e3", "submitted", "unknown", label="timeout")
    d.edge("e4", "unknown", "resolve")
    d.edge("e5", "resolve", "observed", label="confirmed")
    d.label("guard", "No blind retry after an unknown outcome. Resolve the prior attempt before any new broadcast.", 35, 500, 1000, 38, size=15, color=TEAL, bold=True)
    d.write()


VIETNAMESE = {
    "system-architecture": {
        "title": "01 / TRIỂN KHAI VÀ LUỒNG DỮ LIỆU",
        "userlab": "NGƯỜI DÙNG VÀ ỨNG DỤNG", "servicelab": "LỚP ĐIỀU PHỐI",
        "chainlab": "LỚP THỰC THI",
        "browser": "Trình duyệt / React\nVí đã kết nối",
        "api": "FastAPI\nPhiên · phân quyền · yêu cầu",
        "db": "PostgreSQL\nTrạng thái · kế hoạch · outbox · audit",
        "redis": "Redis / Celery\nPhân phối tác vụ",
        "ai": "AI worker\nCông cụ chỉ đọc · đề xuất",
        "core": "Core worker + py-core\nEngine xác định · policy",
        "signer": "Signer tách biệt\nKiểm tra · mô phỏng · gửi",
        "chain": "TreasuryPilotModule + Safe\nTích hợp Aave / EAS",
        "foot": "AI chỉ tư vấn. PostgreSQL lưu dữ liệu nghiệp vụ; Redis phân phối tác vụ.",
    },
    "payment-flow": {
        "title": "02 / TỪ YÊU CẦU ĐẾN THANH TOÁN ĐÃ XÁC MINH",
        "intake": "01  Tiếp nhận hóa đơn\nTrường · điều khoản · cờ rủi ro",
        "approve": "02  Người duyệt ký\nNghĩa vụ EIP-712 cụ thể",
        "plan": "03  Lập kế hoạch\nSố dư mới + mandate",
        "policy": "04  Cổng policy\nALLOW → thực thi\nNEEDS_APPROVAL / BLOCK → giữ lại",
        "execute": "05  Signer + module\nKiểm lại và gửi",
        "hold": "Giữ lại hoặc chặn\nKhông gửi giao dịch",
        "track": "06  Receipt + đối soát\nKiểm tác động · bằng chứng",
        "guard": "ĐIỀU KIỆN CHẶN",
        "guardtxt": "Không có chữ ký duyệt → không được thực thi.\nReceipt chưa rõ → đối soát trước khi thử lại.\nĐề xuất AI → không phải quyền chi tiền.",
    },
    "authority-boundaries": {
        "title": "03 / KIỂM TRA QUYỀN Ở TỪNG RANH GIỚI",
        "human": "Người duyệt", "human-detail": "Ký payee, asset, mức tiền, hạn và request cụ thể",
        "policy": "Policy validator", "policy-detail": "Kiểm mandate, số dư, hạn mức, floor và chain snapshot",
        "signer": "Signer tách biệt", "signer-detail": "Kiểm attestation và calldata; mô phỏng trạng thái mới",
        "module": "Module on-chain", "module-detail": "Kiểm lại quyền, payee, hạn mức, floor và chống phát lại",
        "foot": "AI chỉ có công cụ đọc: được đề xuất và giải thích, không ký hoặc cho phép chuyển tiền.",
    },
    "liquidity-decision": {
        "title": "04 / QUYẾT ĐỊNH THANH KHOẢN",
        "inputs": "Đầu vào\nSố dư Safe · khoản phải trả đã duyệt\nFloor · dự trữ nợ · hold · tiền Aave",
        "reserve": "Dự trữ Safe bắt buộc\nThanh toán + floor + nợ + hold",
        "decision": "So sánh số dư Safe\nvới mức dự trữ bắt buộc",
        "supply": "Dư tiền\nSupply trong ngưỡng và hạn mức",
        "withdraw": "Thiếu tiền\nWithdraw trong aToken / tiền pool",
        "block": "Vẫn thiếu\nQuyết định không đủ thanh khoản",
        "e3": "dư", "e4": "thiếu", "e5": "chưa bù đủ",
        "note": "Dự trữ động tính ngoài chain; module kiểm floor tĩnh và hạn mức supply trên chain.",
    },
    "execution-recovery": {
        "title": "05 / KẾT QUẢ THỰC THI VÀ PHỤC HỒI",
        "recorded": "Ghi outbox\nStep ID ổn định",
        "submitted": "Đã gửi giao dịch\nLưu transaction hash",
        "observed": "Đã thấy receipt\nKiểm số xác nhận",
        "unknown": "Kết quả chưa rõ\nTimeout / RPC không sẵn",
        "resolve": "Đối soát chain\nReceipt · nonce · tác động",
        "e2": "receipt", "e3": "timeout", "e5": "đã xác nhận",
        "guard": "Không thử lại mù khi kết quả chưa rõ. Xác minh lượt trước khi gửi lượt mới.",
    },
}


CHINESE = {
    "system-architecture": {
        "title": "01 / 部署与数据流", "userlab": "用户与应用", "servicelab": "控制层",
        "chainlab": "执行层", "browser": "浏览器 / React\n已连接钱包",
        "api": "FastAPI\n会话 · 权限 · 请求",
        "db": "PostgreSQL\n状态 · 计划 · outbox · 审计",
        "redis": "Redis / Celery\n任务分发",
        "ai": "AI worker\n只读工具 · 建议",
        "core": "Core worker + py-core\n确定性引擎 · 策略",
        "signer": "独立 signer\n检查 · 模拟 · 广播",
        "chain": "TreasuryPilotModule + Safe\nAave / EAS 集成",
        "foot": "AI 仅提供建议。PostgreSQL 保存业务记录；Redis 分发任务。",
    },
    "payment-flow": {
        "title": "02 / 从请求到已核验付款",
        "intake": "01  发票输入\n字段 · 条款 · 风险标记",
        "approve": "02  人工签批\n具体 EIP-712 义务",
        "plan": "03  确定性计划\n最新余额 + mandate",
        "policy": "04  策略关卡\nALLOW → 执行\nNEEDS_APPROVAL / BLOCK → 暂停",
        "execute": "05  Signer + 模块\n复核并广播",
        "hold": "暂停或阻止\n不提交交易",
        "track": "06  回执与对账\n核验结果 · 保存证据",
        "guard": "执行条件",
        "guardtxt": "没有审批签名 → 不执行。\n回执未知 → 先对账再重试。\nAI 建议 → 不构成付款授权。",
    },
    "authority-boundaries": {
        "title": "03 / 每一道边界都检查权限",
        "human": "人工审批人", "human-detail": "签署收款人、资产、金额选项、期限和请求",
        "policy": "策略验证器", "policy-detail": "核验 mandate、余额、上限、floor 与链快照",
        "signer": "独立 signer", "signer-detail": "核验证明与 calldata，并模拟最新状态",
        "module": "链上模块", "module-detail": "再次检查权限、收款人、上限、floor 与重放",
        "foot": "AI 仅能使用只读工具：可以建议和解释，不能签名或授权转账。",
    },
    "liquidity-decision": {
        "title": "04 / 流动性决策",
        "inputs": "可用输入\nSafe 余额 · 已批准未付请求\nfloor · 债务准备金 · 占用 · Aave 现金",
        "reserve": "必需 Safe 准备金\n付款 + floor + 债务 + 占用",
        "decision": "比较 Safe 余额\n与必需准备金",
        "supply": "资金有余\n在上限和最小额内 supply",
        "withdraw": "资金不足\n按 aToken / pool 现金 withdraw",
        "block": "仍有缺口\n流动性不足，停止执行",
        "e3": "余额有余", "e4": "缺口", "e5": "未补足",
        "note": "动态准备金在链下计算；模块在链上执行静态 floor 与 supply 上限。",
    },
    "execution-recovery": {
        "title": "05 / 执行结果与恢复",
        "recorded": "已写入 outbox\n稳定的 step ID",
        "submitted": "已提交交易\n保存交易 hash",
        "observed": "收到回执\n核验确认数",
        "unknown": "结果未知\n超时 / RPC 不可用",
        "resolve": "链上状态对账\n回执 · nonce · 实际影响",
        "e2": "回执", "e3": "超时", "e5": "已确认",
        "guard": "结果未知时不得盲目重试。先查明前一次交易，再考虑新的广播。",
    },
}


def translated_copies() -> None:
    for lang, translations in (("vi", VIETNAMESE), ("zh", CHINESE)):
        for name, labels in translations.items():
            tree = ET.parse(HERE / f"{name}.drawio")
            tree.getroot().find("diagram").set("name", f"{name.replace('-', ' ').title()} {lang.upper()}")
            for cell in tree.findall(".//mxCell"):
                if cell.get("id") in labels:
                    cell.set("value", labels[cell.get("id")])
            ET.indent(tree, space="  ")
            tree.write(HERE / f"{name}-{lang}.drawio", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    architecture()
    payment_flow()
    authority()
    liquidity()
    recovery()
    translated_copies()
    print("Created fifteen editable draw.io diagrams")
