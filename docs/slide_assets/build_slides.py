"""Generate editable 16:9 draw.io slide illustrations for TreasuryPilot.

Export each .drawio with draw.io desktop to PNG and SVG. The PNGs are intended
for presentation slides; the .drawio sources remain editable.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
W, H = 1920, 1080
BG = "#F7FAFD"
INK = "#112D56"
MUTED = "#496480"
BLUE = "#2058BE"
PINK = "#E43C91"
CYAN = "#DDF4FA"
LAVENDER = "#E7E4F8"
PALE = "#ECF3FB"
WHITE = "#FFFFFF"
LINE = "#B8C9E0"


class Slide:
    def __init__(self, filename: str, number: str, title: str, subtitle: str):
        self.filename = filename
        mx = ET.Element("mxfile", {"host": "app.diagrams.net", "type": "device", "version": "24.7.17"})
        diagram = ET.SubElement(mx, "diagram", {"id": filename, "name": title.title()})
        graph = ET.SubElement(diagram, "mxGraphModel", {
            "dx": "1920", "dy": "1080", "grid": "0", "guides": "1", "tooltips": "1",
            "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1",
            "pageWidth": str(W), "pageHeight": str(H), "math": "0", "shadow": "0",
        })
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})
        self.mx = mx
        self.shape("background", "", 0, 0, W, H, BG, BG, rounded=False)
        self.shape("top-accent", "", 0, 0, W, 11, BLUE, BLUE, rounded=False)
        self.shape("corner-pink", "", 1660, 0, 260, 105, "#FBE1EE", "#FBE1EE", rounded=False)
        self.shape("corner-blue", "", 0, 930, 210, 150, "#E4F2FC", "#E4F2FC", rounded=False)
        self.text("number", number, 70, 63, 160, 82, color=PINK, size=65, bold=True)
        self.text("title", title, 205, 67, 1615, 76, color=BLUE, size=54, bold=True)
        self.text("subtitle", subtitle, 80, 151, 1720, 43, color=MUTED, size=23)
        self.shape("footer-rule", "", 80, 1015, 1760, 2, LINE, LINE, rounded=False)
        self.text("footer-left", "TREASURYPILOT  /  TECHNICAL OVERVIEW", 80, 1031, 950, 28, color=MUTED, size=16, bold=True)
        self.text("footer-right", number, 1780, 1031, 60, 28, color=PINK, size=18, bold=True, align="right")

    def shape(self, key: str, label: str, x: int, y: int, w: int, h: int,
              fill: str = WHITE, stroke: str = LINE, *, rounded: bool = True,
              color: str = INK, size: int = 24, bold: bool = False,
              align: str = "center", gradient: str | None = None) -> None:
        style = (f"rounded={1 if rounded else 0};arcSize=13;whiteSpace=wrap;html=0;"
                 f"align={align};verticalAlign=middle;fillColor={fill};strokeColor={stroke};"
                 f"strokeWidth=2;fontColor={color};fontSize={size};fontStyle={1 if bold else 0};"
                 "fontFamily=Arial;spacing=12;")
        if gradient:
            style += f"gradientColor={gradient};gradientDirection=south;"
        cell = ET.SubElement(self.root, "mxCell", {"id": key, "value": label, "style": style,
                                                   "vertex": "1", "parent": "1"})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w),
                                               "height": str(h), "as": "geometry"})

    def text(self, key: str, label: str, x: int, y: int, w: int, h: int,
             *, color: str = INK, size: int = 24, bold: bool = False,
             align: str = "left") -> None:
        style = ("text;html=0;whiteSpace=wrap;overflow=visible;verticalAlign=middle;"
                 f"align={align};fontColor={color};fontSize={size};fontStyle={1 if bold else 0};"
                 "fontFamily=Arial;")
        cell = ET.SubElement(self.root, "mxCell", {"id": key, "value": label, "style": style,
                                                   "vertex": "1", "parent": "1"})
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w),
                                               "height": str(h), "as": "geometry"})

    def edge(self, key: str, source: str, target: str, *, color: str = BLUE,
             dashed: bool = False, width: int = 3, anchors: str = "") -> None:
        style = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=0;"
                 f"strokeColor={color};strokeWidth={width};endArrow=block;endFill=1;"
                 f"dashed={1 if dashed else 0};{anchors}")
        cell = ET.SubElement(self.root, "mxCell", {"id": key, "value": "", "style": style,
                                                   "edge": "1", "parent": "1", "source": source, "target": target})
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    def pill(self, key: str, label: str, x: int, y: int, w: int, fill: str = PALE) -> None:
        self.shape(key, label, x, y, w, 53, fill, fill, color=INK, size=20, bold=True)

    def save(self) -> None:
        ET.indent(self.mx, space="  ")
        ET.ElementTree(self.mx).write(HERE / f"{self.filename}.drawio", encoding="utf-8", xml_declaration=True)


def overall() -> None:
    s = Slide("05-system-architecture", "05", "HIGH-LEVEL SYSTEM ARCHITECTURE",
              "Human approval  →  deterministic planning  →  constrained on-chain execution")
    for i, (key, title, x) in enumerate([
        ("operator", "Finance Operator", 165), ("approver", "Approver", 780), ("owner", "Treasury Owner", 1395)
    ]):
        s.shape(key, title, x, 227, 360, 70, CYAN, CYAN, color=INK, size=27, bold=True)
    s.shape("front-panel", "", 100, 375, 385, 270, LAVENDER, LAVENDER, gradient="#D7EEFB")
    s.shape("api-panel", "", 545, 375, 385, 270, LAVENDER, LAVENDER, gradient="#D7EEFB")
    s.shape("core-panel", "", 990, 375, 385, 270, LAVENDER, LAVENDER, gradient="#D7EEFB")
    s.shape("sign-panel", "", 1435, 375, 385, 270, LAVENDER, LAVENDER, gradient="#D7EEFB")
    components = [
        ("frontend", "FRONTEND", "React · Vite · TypeScript\nwallet signing", 118),
        ("api", "API", "FastAPI · session / RBAC\ninvoice & approval", 563),
        ("core", "CORE + AI WORKERS", "Celery · py-core policy\nAI read-only proposals", 1008),
        ("signer", "ISOLATED SIGNER", "attestation · simulation\nexecutor key", 1453),
    ]
    for key, heading, detail, x in components:
        s.shape(key, f"{heading}\n{detail}", x, 411, 348, 198, WHITE, WHITE,
                color=INK, size=25, bold=True)
    for a,b in (("frontend","api"),("api","core"),("core","signer")):
        s.edge(f"e-{a}-{b}",a,b)
    s.shape("data", "POSTGRESQL  +  REDIS\nBusiness state / outbox    •    task dispatch", 100, 743, 610, 144,
            PALE, LINE, size=25, bold=True)
    s.shape("chain", "TREASURYPILOT MODULE  +  SAFES\nOn-chain caps / floor / replay  •  Aave / EAS", 805, 743, 1015, 144,
            CYAN, LINE, size=25, bold=True)
    s.edge("e-data", "api", "data", color=MUTED)
    s.edge("e-chain", "signer", "chain")
    s.text("note", "Control boundary: AI cannot authorize or sign a payment; the approver, policy, signer and module each check a different condition.",
           100, 932, 1730, 53, color=MUTED, size=22)
    s.save()


def frontend() -> None:
    s = Slide("05A-frontend", "05A", "FRONTEND",
              "A single workspace for finance operators, approvers and treasury owners")
    s.shape("flow-panel", "", 83, 248, 1150, 420, LAVENDER, LAVENDER, gradient="#D8ECFB")
    for key, label, x in [
        ("actor1", "Operator", 173), ("actor2", "Approver", 490), ("actor3", "Owner", 807)
    ]:
        s.shape(key, label, x, 280, 250, 70, CYAN, CYAN, size=26, bold=True)
    steps = [
        ("router", "ROUTER\nURL + access guard", 111),
        ("view", "PAGE / VIEW\nRequests + treasury", 386),
        ("client", "API CLIENT\nTyped /v1 requests", 661),
        ("wallet", "WALLET\nSIWE + EIP-712", 936),
    ]
    for key, label, x in steps:
        s.shape(key, label, x, 424, 225, 164, WHITE, WHITE, size=24, bold=True)
    for a,b in zip(steps,steps[1:]): s.edge(f"e-{a[0]}", a[0], b[0])
    s.shape("role-panel", "", 1290, 248, 545, 420, WHITE, LINE)
    s.text("role-title", "WHAT USERS DO", 1330, 277, 475, 48, color=PINK, size=29, bold=True)
    s.text("role-text", "Operator  ·  intake invoices, review plans\n\nApprover  ·  check fields and sign payments\n\nOwner  ·  govern mandate, payees and pause",
           1330, 348, 455, 255, color=INK, size=26)
    s.text("stack-title", "IMPLEMENTED WEB STACK", 100, 725, 750, 42, color=BLUE, size=28, bold=True)
    for key, label, x, w in [
        ("react", "React 18", 100, 220), ("vite", "Vite", 345, 190),
        ("ts", "TypeScript", 560, 240), ("wagmi", "wagmi / viem", 825, 280),
        ("query", "TanStack Query", 1130, 290)
    ]: s.pill(key,label,x,804,w)
    s.shape("callout", "Browser signs exact obligations; backend and module still validate before money moves.",
            100, 910, 1740, 70, CYAN, CYAN, color=INK, size=24, bold=True)
    s.save()


def backend() -> None:
    s = Slide("05B-backend", "05B", "BACKEND & CORE SERVICES",
              "Separate responsibilities keep document interpretation away from signing authority")
    s.shape("lane", "", 90, 235, 635, 715, LAVENDER, LAVENDER, gradient="#E0F0FC")
    steps = [
        ("routes", "FASTAPI ROUTES", "organization-scoped /v1 endpoints", 275),
        ("identity", "IDENTITY + APPROVAL", "RBAC · maker-checker · typed data", 403),
        ("queue", "CELERY / REDIS", "queued jobs and scheduling", 531),
        ("engine", "WORKER CORE + PY-CORE", "liquidity · EDF/CP-SAT · policy", 659),
        ("signer", "ISOLATED SIGNER", "attestation · eth_call · broadcast", 787),
    ]
    for key, title, detail, y in steps:
        s.shape(key, f"{title}\n{detail}", 128, y, 560, 92, WHITE, WHITE, size=22, bold=True)
    for a,b in zip(steps,steps[1:]): s.edge(f"e-{a[0]}",a[0],b[0])
    s.text("roles-title", "SERVICE RESPONSIBILITIES", 790, 240, 1000, 50, color=PINK, size=33, bold=True)
    s.text("roles", "API                 authenticates users; stores requests and approvals\n\nWorker AI          extracts and proposes with read-only tools\n\nWorker Core     builds plans and applies deterministic policy\n\nSigner              validates a typed step and controls the executor key\n\nTracker            verifies receipts, chain state and reconciliation",
           795, 318, 985, 405, color=INK, size=27)
    s.text("stack-title", "IMPLEMENTED BACKEND STACK", 795, 765, 900, 42, color=BLUE, size=26, bold=True)
    for key, label, x, w in [
        ("fastapi", "FastAPI / Python", 795, 295), ("celery", "Celery", 1115, 195),
        ("postgres", "PostgreSQL", 1335, 245), ("redis", "Redis", 1605, 180)
    ]: s.pill(key,label,x,830,w)
    s.text("note", "Redis dispatches tasks; PostgreSQL remains the business record of truth.",
           795, 919, 990, 45, color=MUTED, size=23)
    s.save()


def data_model() -> None:
    s = Slide("05C-data-model", "05C", "DATABASE & EVIDENCE MODEL",
              "Conceptual domain groups from the current PostgreSQL schema — not a literal table-by-table ERD")
    groups = [
        ("identity", "IDENTITY & ORG", ["Organization", "Member / Role", "Session"], 100, 255, CYAN),
        ("treasury", "TREASURY & MANDATE", ["Treasury / Safe", "Mandate / Payee", "Chain Snapshot"], 545, 255, LAVENDER),
        ("invoice", "INVOICE & APPROVAL", ["Invoice / Request", "PaymentApproval", "Terms / Risk Flags"], 990, 255, "#FBE6F0"),
        ("execution", "EXECUTION & EVIDENCE", ["Plan / Step", "Operation / Receipt", "Reconciliation / Audit"], 1435, 255, PALE),
    ]
    for key, heading, items, x, y, fill in groups:
        s.shape(key+"-panel", "", x, y, 385, 535, fill, fill)
        s.text(key+"-head", heading, x+24, y+26, 335, 59, color=BLUE, size=28, bold=True, align="center")
        for j, item in enumerate(items):
            s.shape(f"{key}-{j}", item, x+34, y+126+j*118, 317, 74,
                    WHITE, LINE, color=INK, size=25, bold=True)
    s.text("flow-label", "EVIDENCE CHAIN", 100, 835, 400, 38, color=PINK, size=26, bold=True)
    s.shape("flow", "request  →  approval signature  →  plan / policy  →  transaction receipt  →  verification  →  audit bundle",
            100, 885, 1720, 79, WHITE, LINE, color=INK, size=25, bold=True)
    s.save()


def ai_controls() -> None:
    s = Slide("05D-ai-and-controls", "05D", "AI, ENGINE & CONTROL BOUNDARIES",
              "AI prepares evidence and options; deterministic components decide what can move")
    lanes = [
        ("ai", "AI WORKER", "Invoice fields · terms · plan suggestions\nRead-only tools; no signing key", 110, CYAN),
        ("engine", "FINANCIAL ENGINE", "Integer amounts · reserves · EDF / CP-SAT\nFresh balances and constraints", 548, LAVENDER),
        ("policy", "POLICY ENGINE", "ALLOW / NEEDS_APPROVAL / BLOCK\nVersioned reason codes and attestation", 986, PALE),
        ("chain", "SIGNER + MODULE", "Simulate and sign · then recheck on-chain\nPayee · caps · floor · replay", 1424, "#FBE6F0"),
    ]
    for key, title, detail, x, fill in lanes:
        s.shape(key+"-panel", "", x, 293, 385, 455, fill, fill)
        s.text(key+"-title", title, x+26, 330, 335, 61, color=BLUE, size=29, bold=True, align="center")
        s.shape(key, detail, x+25, 435, 335, 219, WHITE, WHITE, color=INK, size=25)
    for a,b in zip(lanes,lanes[1:]):
        s.edge(f"e-{a[0]}",a[0],b[0],dashed=(a[0]=="ai"))
    s.shape("guard", "AI proposals are optional. Human EIP-712 approval binds the obligation; unknown outcomes are reconciled before retry.",
            110, 840, 1699, 100, WHITE, LINE, color=INK, size=26, bold=True)
    s.save()


if __name__ == "__main__":
    overall(); frontend(); backend(); data_model(); ai_controls()
    print("Created five editable 1920×1080 draw.io slide illustrations")
