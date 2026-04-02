#!/usr/bin/env python3
"""Generate architecture and workflow SVG diagrams for Loom documentation.

Run:  python docs/generate_diagrams.py
Output: docs/images/*.svg
"""
from __future__ import annotations

import textwrap
from pathlib import Path

OUT = Path(__file__).parent / "images"
OUT.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

class SVG:
    """Minimal SVG builder — no dependencies."""

    def __init__(self, w: int, h: int, *, bg: str = "#fafafb"):
        self.w, self.h = w, h
        self.defs: list[str] = []
        self.body: list[str] = []
        self._id = 0
        self.body.append(f'<rect width="{w}" height="{h}" rx="12" fill="{bg}"/>')

    # --- primitives ---

    def rect(self, x, y, w, h, *, fill="#555", rx=8, stroke=None, sw=1, opacity=1):
        s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'
        if stroke:
            s += f' stroke="{stroke}" stroke-width="{sw}"'
        if opacity < 1:
            s += f' opacity="{opacity}"'
        s += "/>"
        self.body.append(s)

    def text(self, x, y, txt, *, size=14, weight=600, fill="#fff", anchor="middle", baseline="central", family="Inter, system-ui, sans-serif"):
        esc = txt.replace("&", "&amp;").replace("<", "&lt;")
        self.body.append(
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="{baseline}">{esc}</text>'
        )

    def mtext(self, x, y, lines: list[str], *, size=10, weight=400, fill="#666", anchor="start", lh=1.4):
        """Multi-line text."""
        self.body.append(f'<text x="{x}" y="{y}" font-family="Inter, system-ui, sans-serif" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">')
        for i, line in enumerate(lines):
            dy = 0 if i == 0 else size * lh
            esc = line.replace("&", "&amp;").replace("<", "&lt;")
            self.body.append(f'  <tspan x="{x}" dy="{dy}">{esc}</tspan>')
        self.body.append("</text>")

    def line(self, x1, y1, x2, y2, *, color="#999", sw=2, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.body.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d}/>')

    def arrow(self, x1, y1, x2, y2, *, color="#888", sw=2):
        mid = f"arrow_{self._next_id()}"
        self.defs.append(f'<marker id="{mid}" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 3 L 0 6 z" fill="{color}"/></marker>')
        self.body.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}" marker-end="url(#{mid})"/>')

    def circle(self, cx, cy, r, *, fill="#555"):
        self.body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>')

    def _next_id(self):
        self._id += 1
        return self._id

    # --- composites ---

    def box_label(self, x, y, w, h, label, *, fill="#555", text_color="#fff", fs=14, rx=8):
        self.rect(x, y, w, h, fill=fill, rx=rx)
        self.text(x + w / 2, y + h / 2, label, size=fs, fill=text_color)

    def layer_bg(self, x, y, w, h, fill, label):
        self.rect(x, y, w, h, fill=fill, rx=10)
        self.text(x + 14, y + 14, label, size=11, weight=500, fill="#888", anchor="start", baseline="hanging")

    def step_badge(self, x, y, num, color):
        self.circle(x + 16, y + 16, 16, fill=color)
        self.text(x + 16, y + 16, str(num), size=14, weight=700, fill="#fff")

    def msg_box(self, x, y, w, h, title, fields: list[str]):
        self.rect(x, y, w, h, fill="#fffaee", rx=6, stroke="#e6dbb5", sw=1)
        self.text(x + 10, y + 14, title, size=10, weight=700, fill="#888", anchor="start")
        self.mtext(x + 10, y + 30, fields, size=9, fill="#8a7a55")

    def note_box(self, x, y, w, h, text_str, *, bg="#f4f0ff", border="#d4c8ee", text_color="#6b50a0"):
        self.rect(x, y, w, h, fill=bg, rx=4, stroke=border, sw=1)
        self.text(x + w / 2, y + h / 2, text_str, size=9, weight=400, fill=text_color)

    # --- output ---

    def render(self) -> str:
        defs = "\n".join(self.defs)
        body = "\n".join(self.body)
        return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">
        <defs>{defs}</defs>
        {body}
        </svg>""")

    def save(self, path: Path):
        path.write_text(self.render(), encoding="utf-8")
        print(f"  wrote {path}  ({self.w}x{self.h})")


# ===========================================================================
# Diagram 1: Architecture Overview
# ===========================================================================

def architecture_overview():
    s = SVG(1440, 1000)

    # Title
    s.text(40, 38, "Loom — Architecture Overview", size=26, weight=700, fill="#1e1e26", anchor="start")
    s.text(40, 62, "Actor-based LLM orchestration framework  ·  NATS messaging  ·  Typed contracts", size=12, weight=400, fill="#888", anchor="start")

    # --- INTERFACES ---
    s.layer_bg(30, 92, 1380, 118, "#e0e8ff", "INTERFACES")
    boxes = [
        (60, "MCP Gateway", "#4278d9"),
        (250, "Workshop UI", "#4278d9"),
        (440, "CLI", "#4278d9"),
        (590, "TUI Dashboard", "#4278d9"),
        (810, "Council", "#278e94"),
        (990, "ChatBridge", "#278e94"),
    ]
    for bx, label, color in boxes:
        w = 165 if label not in ("CLI",) else 120
        s.box_label(bx, 124, w, 58, label, fill=color)
    s.text(810, 114, "contrib/", size=9, weight=500, fill="#278e94", anchor="start")

    # --- ORCHESTRATION ---
    s.layer_bg(30, 240, 1380, 120, "#ede4ff", "ORCHESTRATION")
    orch = [
        (60, 195, "OrchestratorActor"),
        (280, 200, "PipelineOrchestrator"),
        (505, 180, "GoalDecomposer"),
        (710, 148, "Router"),
        (883, 175, "ResultStream"),
        (1083, 185, "Dead Letter"),
    ]
    for bx, w, label in orch:
        s.box_label(bx, 274, w, 58, label, fill="#7d52c2")
    s.text(285, 342, "FIRST_COMPLETED · Dependency-aware parallel stages", size=9, weight=400, fill="#a888d8", anchor="start")

    # --- NATS BUS ---
    s.rect(30, 390, 1380, 52, fill="#f5c72e", rx=8)
    s.text(55, 408, "NATS Message Bus", size=15, weight=700, fill="#4a3800", anchor="start")
    s.text(55, 428, "loom.goals.*    loom.tasks.*    loom.results.*    loom.control.*    loom.deadletter.*", size=10, weight=500, fill="#7a6510", anchor="start")

    # --- WORKERS ---
    s.layer_bg(30, 472, 1380, 120, "#ddf4de", "WORKERS  —  Stateless · Typed I/O · JSON Schema validation · Per-stage retry")
    wnames = ["Summarizer", "Classifier", "Extractor", "Translator", "QA", "Reviewer", "Custom..."]
    for i, name in enumerate(wnames):
        fill = "#2e9e57" if name != "Custom..." else "#5ab86e"
        s.box_label(55 + i * 185, 506, 165, 58, name, fill=fill)

    # --- BACKENDS ---
    s.layer_bg(30, 622, 640, 110, "#e8e9ec", "PROCESSING BACKENDS")
    for i, (label, sub) in enumerate([("Anthropic", "frontier / standard"), ("OpenAI", "standard"), ("Ollama (Local)", "local")]):
        s.box_label(55 + i * 205, 654, 185, 50, label, fill="#555c70", fs=13)
        s.text(55 + i * 205 + 92, 718, sub, size=9, weight=400, fill="#999")

    # --- STORAGE ---
    s.layer_bg(700, 622, 710, 110, "#f2efe8", "STORAGE & CONFIG")
    for i, (label, sub) in enumerate([("DuckDB", "eval results"), ("Vector Store", "RAG chunks"), ("YAML Configs", "workers · pipelines")]):
        s.box_label(725 + i * 220, 654, 195, 50, label, fill="#997a59", fs=13)
        s.text(725 + i * 220 + 97, 718, sub, size=9, weight=400, fill="#999")

    # --- OBSERVABILITY ---
    s.layer_bg(30, 762, 1380, 85, "#eeeeef", "OBSERVABILITY & TOOLING")
    for i, name in enumerate(["OpenTelemetry", "I/O Tracing", "request_id Logging", "Pre-flight Checks", "Config Validation"]):
        s.box_label(55 + i * 265, 790, 238, 40, name, fill="#858593", fs=12)

    # --- DEPLOYMENT ---
    s.text(40, 875, "DEPLOYMENT:  Docker Compose  ·  Kubernetes  ·  macOS launchd  ·  Windows NSSM  ·  ZIP App Bundles  ·  mDNS Discovery", size=11, weight=500, fill="#999", anchor="start")
    s.text(40, 898, "v0.9.0  ·  1807 tests  ·  90% coverage  ·  MPL 2.0", size=11, weight=400, fill="#aaa", anchor="start")

    # --- ARROWS ---
    # Interfaces → Orchestration
    for x in [143, 333, 500, 673, 893, 1073]:
        s.line(x, 182, x, 240, color="#bbb", sw=1.5, dash="5 5")
    # Orchestration → NATS
    for x in [158, 380, 595, 784, 970, 1175]:
        s.line(x, 332, x, 390, color="#e8c020", sw=2)
    # NATS → Workers
    for i in range(7):
        x = 137 + i * 185
        s.line(x, 442, x, 472, color="#e8c020", sw=2)
    # Workers → Backends
    for x in [148, 353, 558]:
        s.line(x, 564, x, 622, color="#bbb", sw=1.5, dash="5 5")
    # Workers → Storage
    for x in [822, 1027, 1232]:
        s.line(x, 564, x, 622, color="#bbb", sw=1.5, dash="5 5")

    s.save(OUT / "architecture-overview.svg")


# ===========================================================================
# Diagram 2: Data Flow — Goal Lifecycle
# ===========================================================================

def data_flow():
    s = SVG(1100, 1150)

    s.text(40, 38, "Loom — Data Flow", size=26, weight=700, fill="#1e1e26", anchor="start")
    s.text(40, 62, "Goal lifecycle:  submit  >  decompose  >  route  >  process  >  collect  >  return", size=12, weight=400, fill="#888", anchor="start")

    steps = [
        (100, "#e85c5c", "SUBMIT GOAL", "Client sends a Goal via MCP, CLI, or API"),
        (270, "#cc7333", "DECOMPOSE", "GoalDecomposer breaks goal into tasks"),
        (450, "#7d52c2", "ROUTE", "Router dispatches tasks via NATS subjects"),
        (630, "#2e9e57", "PROCESS", "WorkerActor validates, calls backend, validates output"),
        (810, "#4278d9", "COLLECT", "ResultStream gathers results (early-exit, callbacks)"),
        (980, "#278e94", "RETURN", "Aggregated results via MCP / CLI / async iterator"),
    ]

    for i, (y, color, title, desc) in enumerate(steps):
        # Step badge
        s.step_badge(40, y, i + 1, color)
        s.text(80, y + 10, title, size=14, weight=700, fill=color, anchor="start", baseline="hanging")
        s.text(80, y + 30, desc, size=11, weight=400, fill="#888", anchor="start", baseline="hanging")

        # Vertical arrow to next step
        if i < len(steps) - 1:
            next_y = steps[i + 1][0]
            s.arrow(56, y + 55, 56, next_y - 5, color="#ccc", sw=2)

    # --- Step 1: Goal ---
    s.box_label(80, 150, 200, 50, "Goal", fill="#e85c5c")
    s.arrow(280, 175, 340, 175, color="#e85c5c")
    s.msg_box(350, 142, 280, 68, "GoalMessage", [
        "goal_id: str    prompt: str",
        "context: dict   request_id: str",
    ])
    s.text(660, 162, "Published to:", size=10, weight=500, fill="#999", anchor="start")
    s.text(660, 180, "loom.goals.{goal_id}", size=11, weight=600, fill="#d4a820", anchor="start")

    # --- Step 2: Decompose ---
    s.box_label(80, 325, 200, 50, "GoalDecomposer", fill="#cc7333")
    for j, name in enumerate(["Task A", "Task B", "Task C"]):
        tx = 370 + j * 210
        s.arrow(280, 350, tx, 350, color="#cc7333")
        s.box_label(tx, 325, 180, 50, name, fill="#e8b020", text_color="#3a2500")
    s.msg_box(370, 390, 280, 52, "TaskMessage", [
        "task_id  worker_type  payload  tier",
    ])

    # --- Step 3: Route ---
    s.box_label(80, 505, 200, 50, "Router", fill="#7d52c2")
    s.text(310, 518, "NATS subject:", size=10, weight=500, fill="#999", anchor="start")
    s.text(310, 536, "loom.tasks.{worker_type}.{tier}", size=11, weight=600, fill="#d4a820", anchor="start")
    s.note_box(620, 510, 340, 30, "Dispatch-side rate limiting (semaphore per worker type)")

    # --- Step 4: Process ---
    s.box_label(80, 685, 190, 50, "WorkerActor", fill="#2e9e57")
    # Pipeline variant
    s.rect(300, 675, 480, 70, fill="#f5f0fa", rx=8, stroke="#d4c8ee", sw=1)
    s.text(310, 683, "OR: Pipeline Mode", size=10, weight=700, fill="#7d52c2", anchor="start", baseline="hanging")
    for j, stage in enumerate(["Stage 1", "Stage 2", "Stage 3"]):
        sx = 320 + j * 150
        s.box_label(sx, 705, 125, 30, stage, fill="#8a60d0", fs=11)
        if j < 2:
            s.arrow(445 + j * 150, 720, 465 + j * 150, 720, color="#8a60d0")
    s.box_label(810, 685, 200, 50, "LLM Backend Call", fill="#555c70", fs=12)
    s.text(810, 748, "input_schema -> LLM -> output_schema", size=9, weight=400, fill="#999", anchor="start")

    # --- Step 5: Collect ---
    s.box_label(80, 862, 200, 50, "ResultStream", fill="#4278d9")
    s.arrow(280, 887, 340, 887, color="#4278d9")
    s.msg_box(350, 855, 280, 62, "TaskResult", [
        "task_id  success  result  model",
        "latency_ms  tokens",
    ])
    s.text(660, 870, "Published to:", size=10, weight=500, fill="#999", anchor="start")
    s.text(660, 888, "loom.results.{goal_id}", size=11, weight=600, fill="#d4a820", anchor="start")
    s.note_box(660, 900, 350, 24, "Failures -> loom.deadletter.* -> Dead Letter Store (bounded FIFO)", bg="#fff0f0", border="#ecc", text_color="#c55")

    # --- Step 6: Return ---
    for j, label in enumerate(["MCP Response", "CLI Output", "Async Iterator"]):
        s.box_label(80 + j * 210, 1035, 190, 45, label, fill="#278e94", fs=12)
    s.rect(720, 1035, 320, 52, fill="#f2f7f7", rx=6, stroke="#d0e4e4", sw=1)
    s.text(730, 1048, "Includes _timeline metadata:", size=10, weight=600, fill="#278e94", anchor="start", baseline="hanging")
    s.text(730, 1066, "Per-stage timing, model, tokens, request_id", size=9, weight=400, fill="#888", anchor="start", baseline="hanging")

    s.save(OUT / "data-flow.svg")


# ===========================================================================
# Diagram 3: Developer Workflow
# ===========================================================================

def developer_workflow():
    s = SVG(1200, 700)

    s.text(40, 38, "Loom — Developer Workflow", size=26, weight=700, fill="#1e1e26", anchor="start")
    s.text(40, 62, "Define workers, build pipelines, test, evaluate, and deploy", size=12, weight=400, fill="#888", anchor="start")

    # Swimlane headers
    lanes = [
        (90, "#4278d9", "DEFINE"),
        (270, "#7d52c2", "CONFIGURE"),
        (450, "#2e9e57", "TEST & EVAL"),
        (630, "#cc7333", "DEPLOY"),
    ]
    for y, color, label in lanes:
        s.rect(30, y, 1140, 140, fill="#f8f8fa", rx=10)
        s.text(50, y + 16, label, size=12, weight=700, fill=color, anchor="start", baseline="hanging")

    # DEFINE lane
    s.box_label(60, 120, 180, 50, "Write Worker YAML", fill="#4278d9", fs=12)
    s.arrow(240, 145, 280, 145, color="#bbb")
    s.box_label(290, 120, 180, 50, "Set Processing Backend", fill="#4278d9", fs=11)
    s.arrow(470, 145, 510, 145, color="#bbb")
    s.box_label(520, 120, 180, 50, "Define I/O Schema", fill="#4278d9", fs=12)
    s.arrow(700, 145, 740, 145, color="#bbb")
    s.box_label(750, 120, 200, 50, "schema_ref (Pydantic)", fill="#4278d9", fs=12)

    # CONFIGURE lane
    s.box_label(60, 300, 180, 50, "Build Pipeline YAML", fill="#7d52c2", fs=12)
    s.arrow(240, 325, 280, 325, color="#bbb")
    s.box_label(290, 300, 200, 50, "Set Stage Dependencies", fill="#7d52c2", fs=11)
    s.arrow(490, 325, 530, 325, color="#bbb")
    s.box_label(540, 300, 180, 50, "Input Mappings", fill="#7d52c2", fs=12)
    s.arrow(720, 325, 760, 325, color="#bbb")
    s.box_label(770, 300, 200, 50, "Config Validation", fill="#7d52c2", fs=12)

    # TEST & EVAL lane
    s.box_label(60, 480, 180, 50, "Workshop Test Bench", fill="#2e9e57", fs=12)
    s.arrow(240, 505, 280, 505, color="#bbb")
    s.box_label(290, 480, 200, 50, "Write Eval Test Suite", fill="#2e9e57", fs=11)
    s.arrow(490, 505, 530, 505, color="#bbb")
    s.box_label(540, 480, 180, 50, "Run Evaluations", fill="#2e9e57", fs=12)
    s.arrow(720, 505, 760, 505, color="#bbb")
    s.box_label(770, 480, 200, 50, "Promote Baseline", fill="#2e9e57", fs=12)

    # Eval details
    s.mtext(540, 540, ["Scoring: field_match | exact | llm_judge", "Comparison: baseline regression checks"], size=9, fill="#6a6")

    # DEPLOY lane
    s.box_label(60, 660, 180, 50, "Build App Bundle", fill="#cc7333", fs=12)
    s.arrow(240, 685, 280, 685, color="#bbb")
    s.box_label(290, 660, 200, 50, "Upload ZIP to Workshop", fill="#cc7333", fs=11)
    s.arrow(490, 685, 530, 685, color="#bbb")
    s.box_label(540, 660, 180, 50, "Config Hot-Reload", fill="#cc7333", fs=12)
    s.arrow(720, 685, 760, 685, color="#bbb")
    s.box_label(770, 660, 200, 50, "Monitor Dead Letters", fill="#cc7333", fs=12)

    s.mtext(60, 725, ["scripts/build-app.sh", "manifest.yaml + configs"], size=9, fill="#b07040")

    s.save(OUT / "developer-workflow.svg")


# ===========================================================================
# Diagram 4: Workshop UI Mockup
# ===========================================================================

def workshop_mockup():
    s = SVG(1200, 2400)

    s.text(40, 38, "Loom Workshop — UI Overview", size=26, weight=700, fill="#1e1e26", anchor="start")
    s.text(40, 62, "Web-based worker lifecycle management  ·  FastAPI + HTMX + Pico CSS", size=12, weight=400, fill="#888", anchor="start")

    # --- HEADER MOCKUP ---
    y = 100
    s.rect(30, y, 1140, 50, fill="#1a1a2e", rx=8)
    s.text(55, y + 25, "LOOM WORKSHOP", size=14, weight=700, fill="#f5c72e")
    nav_items = ["Workers", "Pipelines", "Apps", "RAG", "Dead Letters"]
    for i, item in enumerate(nav_items):
        s.text(250 + i * 120, y + 25, item, size=12, weight=500, fill="#ccc")
    s.circle(1120, y + 25, 10, fill="#555")
    s.text(1120, y + 25, "D", size=10, weight=600, fill="#ccc")  # theme toggle

    # === PAGE 1: Workers List ===
    y = 180
    s.text(40, y, "Workers List", size=20, weight=700, fill="#1e1e26", anchor="start")
    s.rect(30, y + 30, 1140, 40, fill="#f4f4f6", rx=6)
    s.text(50, y + 50, "Search workers...", size=12, weight=400, fill="#aaa", anchor="start")

    # Table header
    ty = y + 85
    s.rect(30, ty, 1140, 35, fill="#eee", rx=4)
    headers = [("Name", 50), ("Description", 250), ("Kind", 650), ("Tier", 780), ("Actions", 920)]
    for label, hx in headers:
        s.text(hx, ty + 18, label, size=11, weight=600, fill="#666", anchor="start")

    # Table rows
    workers_data = [
        ("summarizer", "Generate concise summaries", "processor", "standard", "Anthropic"),
        ("classifier", "Multi-label classification", "processor", "standard", "Anthropic"),
        ("extractor", "Structured data extraction", "processor", "frontier", "Anthropic"),
        ("translator", "Text translation", "processor", "local", "Ollama"),
    ]
    for i, (name, desc, kind, tier, _) in enumerate(workers_data):
        ry = ty + 40 + i * 40
        if i % 2 == 1:
            s.rect(30, ry, 1140, 38, fill="#fafafa", rx=0)
        s.text(50, ry + 19, name, size=12, weight=600, fill="#4278d9", anchor="start")
        s.text(250, ry + 19, desc, size=11, weight=400, fill="#666", anchor="start")
        # Kind badge
        s.rect(650, ry + 6, 80, 24, fill="#ede4ff", rx=12)
        s.text(690, ry + 18, kind, size=10, weight=500, fill="#7d52c2")
        # Tier badge
        tier_colors = {"standard": "#e0e8ff", "frontier": "#ffeedd", "local": "#ddf4de"}
        s.rect(780, ry + 6, 75, 24, fill=tier_colors.get(tier, "#eee"), rx=12)
        s.text(817, ry + 18, tier, size=10, weight=500, fill="#555")
        # Action buttons
        s.rect(920, ry + 6, 50, 24, fill="none", rx=4, stroke="#2e9e57", sw=1)
        s.text(945, ry + 18, "Test", size=10, weight=500, fill="#2e9e57")
        s.rect(980, ry + 6, 50, 24, fill="none", rx=4, stroke="#4278d9", sw=1)
        s.text(1005, ry + 18, "Eval", size=10, weight=500, fill="#4278d9")

    # === PAGE 2: Test Bench ===
    y = 460
    s.text(40, y, "Test Bench: summarizer", size=20, weight=700, fill="#1e1e26", anchor="start")

    # Backend badges
    s.rect(40, y + 35, 90, 26, fill="#ddf4de", rx=13)
    s.text(85, y + 48, "Anthropic", size=10, weight=500, fill="#2e9e57")
    s.rect(140, y + 35, 75, 26, fill="#ddf4de", rx=13)
    s.text(177, y + 48, "Ollama", size=10, weight=500, fill="#2e9e57")

    # Input schema (collapsed)
    s.rect(40, y + 75, 500, 30, fill="#f8f8fa", rx=6, stroke="#ddd", sw=1)
    s.text(60, y + 90, "> Input Schema (click to expand)", size=11, weight=500, fill="#888", anchor="start")

    # Payload textarea
    s.text(40, y + 120, "Test Payload (JSON):", size=12, weight=600, fill="#333", anchor="start")
    s.rect(40, y + 140, 500, 100, fill="#fff", rx=6, stroke="#ccc", sw=1)
    s.mtext(52, y + 158, [
        '{',
        '  "text": "The quick brown fox...",',
        '  "max_length": 100',
        '}',
    ], size=11, weight=400, fill="#555")

    # Tier dropdown + submit
    s.text(40, y + 255, "Tier:", size=12, weight=600, fill="#333", anchor="start")
    s.rect(80, y + 240, 120, 30, fill="#fff", rx=4, stroke="#ccc", sw=1)
    s.text(140, y + 255, "standard", size=11, weight=400, fill="#555")
    s.rect(220, y + 240, 100, 30, fill="#4278d9", rx=6)
    s.text(270, y + 255, "Run Test", size=12, weight=600, fill="#fff")

    # Result panel
    s.rect(580, y + 75, 530, 210, fill="#f0fff0", rx=8, stroke="#c5e8c5", sw=1)
    s.text(600, y + 95, "Test Result", size=14, weight=700, fill="#2e9e57", anchor="start")
    s.rect(740, y + 84, 50, 22, fill="#2e9e57", rx=11)
    s.text(765, y + 95, "PASS", size=10, weight=600, fill="#fff")

    result_lines = [
        "Model: claude-sonnet-4-20250514",
        "Latency: 1,234 ms",
        "Tokens: 150 prompt + 85 completion",
        "",
        "Output:",
        '{ "summary": "A fox jumped over a lazy dog..." }',
    ]
    s.mtext(600, y + 122, result_lines, size=11, fill="#555", lh=1.6)

    # === PAGE 3: Eval Dashboard ===
    y = 790
    s.text(40, y, "Eval Dashboard: summarizer", size=20, weight=700, fill="#1e1e26", anchor="start")

    # Run form
    s.rect(40, y + 35, 500, 140, fill="#f8f8fa", rx=8, stroke="#eee", sw=1)
    s.text(55, y + 55, "Run New Evaluation", size=13, weight=600, fill="#333", anchor="start")
    s.text(55, y + 78, "Test Suite (YAML):", size=11, weight=500, fill="#666", anchor="start")
    s.rect(55, y + 92, 470, 48, fill="#fff", rx=4, stroke="#ddd", sw=1)
    s.mtext(65, y + 108, ["- name: basic_summary", "  input: {text: 'Hello world'}"], size=10, fill="#888")
    s.rect(55, y + 148, 100, 28, fill="#4278d9", rx=6)
    s.text(105, y + 162, "Run Eval", size=11, weight=600, fill="#fff")

    # Past runs table
    s.text(580, y + 45, "Past Runs", size=14, weight=600, fill="#333", anchor="start")
    s.rect(580, y + 65, 530, 30, fill="#eee", rx=4)
    run_headers = [("Run ID", 595), ("Tier", 700), ("Result", 770), ("Cases", 860), ("Date", 920)]
    for label, hx in run_headers:
        s.text(hx, y + 80, label, size=10, weight=600, fill="#666", anchor="start")

    runs = [
        ("run_abc123", "standard", "ALL PASS", "#2e9e57", "5/5", "2026-03-28"),
        ("run_def456", "frontier", "PARTIAL", "#d4a820", "3/5", "2026-03-27"),
        ("run_ghi789", "local", "ALL FAIL", "#e85c5c", "0/5", "2026-03-26"),
    ]
    for i, (rid, tier, result, rcolor, cases, date) in enumerate(runs):
        ry = y + 100 + i * 32
        s.text(595, ry + 10, rid, size=10, weight=500, fill="#4278d9", anchor="start")
        s.text(700, ry + 10, tier, size=10, weight=400, fill="#666", anchor="start")
        s.rect(770, ry, 70, 22, fill=rcolor, rx=11)
        s.text(805, ry + 11, result.split()[-1], size=9, weight=600, fill="#fff")
        s.text(860, ry + 10, cases, size=10, weight=400, fill="#666", anchor="start")
        s.text(920, ry + 10, date, size=10, weight=400, fill="#999", anchor="start")

    # === PAGE 4: Pipeline Editor ===
    y = 1020
    s.text(40, y, "Pipeline Editor: analysis_pipeline", size=20, weight=700, fill="#1e1e26", anchor="start")
    s.text(40, y + 28, "4 stages  ·  3 execution levels", size=12, weight=400, fill="#888", anchor="start")

    # Execution graph
    s.rect(40, y + 55, 700, 280, fill="#faf8ff", rx=10, stroke="#e8e0f5", sw=1)
    s.text(55, y + 72, "Execution Graph", size=13, weight=600, fill="#7d52c2", anchor="start")

    # Level 0
    s.text(55, y + 105, "Level 0", size=10, weight=600, fill="#999", anchor="start")
    s.box_label(130, y + 92, 200, 40, "extract (extractor)", fill="#7d52c2", fs=11)

    # Arrow down
    s.arrow(230, y + 132, 230, y + 150, color="#bbb")

    # Level 1 — two parallel
    s.text(55, y + 165, "Level 1", size=10, weight=600, fill="#999", anchor="start")
    s.box_label(130, y + 152, 200, 40, "classify (classifier)", fill="#7d52c2", fs=11)
    s.box_label(370, y + 152, 200, 40, "summarize (summarizer)", fill="#7d52c2", fs=11)

    # Arrows down
    s.arrow(230, y + 192, 230, y + 210, color="#bbb")
    s.arrow(470, y + 192, 350, y + 210, color="#bbb")

    # Level 2
    s.text(55, y + 225, "Level 2", size=10, weight=600, fill="#999", anchor="start")
    s.box_label(130, y + 212, 200, 40, "review (reviewer)", fill="#7d52c2", fs=11)

    # Dependencies labels
    s.mtext(370, y + 260, [
        "Dependencies inferred from input_mapping references.",
        "Parallel stages run with asyncio.wait(FIRST_COMPLETED).",
    ], size=9, fill="#a888d8")

    # Stage operations (right side)
    s.rect(780, y + 55, 380, 280, fill="#f8f8fa", rx=8, stroke="#eee", sw=1)
    s.text(800, y + 75, "Stage Operations", size=13, weight=600, fill="#333", anchor="start")
    ops = ["Insert Stage", "Swap Worker", "Remove Stage", "Add Parallel Branch"]
    for i, op in enumerate(ops):
        oy = y + 100 + i * 55
        s.rect(800, oy, 340, 40, fill="#fff", rx=6, stroke="#ddd", sw=1)
        s.text(820, oy + 20, "> " + op, size=12, weight=500, fill="#666", anchor="start")

    # === PAGE 5: Apps ===
    y = 1380
    s.text(40, y, "App Deployment", size=20, weight=700, fill="#1e1e26", anchor="start")

    # Upload form
    s.rect(40, y + 35, 500, 80, fill="#fff8f0", rx=8, stroke="#f0dfc0", sw=1)
    s.text(55, y + 55, "Deploy New App", size=13, weight=600, fill="#cc7333", anchor="start")
    s.rect(55, y + 75, 300, 28, fill="#fff", rx=4, stroke="#ddd", sw=1)
    s.text(70, y + 89, "Choose .zip file...", size=11, weight=400, fill="#aaa", anchor="start")
    s.rect(370, y + 75, 80, 28, fill="#cc7333", rx=6)
    s.text(410, y + 89, "Deploy", size=11, weight=600, fill="#fff")

    # Deployed apps table
    s.text(40, y + 140, "Deployed Apps", size=14, weight=600, fill="#333", anchor="start")
    s.rect(40, y + 160, 1120, 30, fill="#eee", rx=4)
    app_h = [("Name", 55), ("Version", 250), ("Workers", 400), ("Pipelines", 520), ("Actions", 650)]
    for label, hx in app_h:
        s.text(hx, y + 175, label, size=10, weight=600, fill="#666", anchor="start")
    # Sample row
    s.text(55, y + 207, "baft-itp", size=12, weight=600, fill="#cc7333", anchor="start")
    s.text(250, y + 207, "v0.3.0", size=11, weight=400, fill="#666", anchor="start")
    s.text(400, y + 207, "13", size=11, weight=400, fill="#666", anchor="start")
    s.text(520, y + 207, "4", size=11, weight=400, fill="#666", anchor="start")
    s.rect(650, y + 194, 70, 24, fill="none", rx=4, stroke="#e85c5c", sw=1)
    s.text(685, y + 206, "Remove", size=10, weight=500, fill="#e85c5c")

    # === PAGE 6: Dead Letters ===
    y = 1620
    s.text(40, y, "Dead Letters", size=20, weight=700, fill="#1e1e26", anchor="start")
    s.text(200, y + 5, "3", size=14, weight=700, fill="#e85c5c", anchor="start")

    s.rect(40, y + 35, 1120, 30, fill="#eee", rx=4)
    dl_h = [("Timestamp", 55), ("Task ID", 250), ("Worker", 450), ("Reason", 600), ("Actions", 900)]
    for label, hx in dl_h:
        s.text(hx, y + 50, label, size=10, weight=600, fill="#666", anchor="start")

    dl_rows = [
        ("14:23:05", "task_a1b2c3", "extractor", "Timeout after 30s"),
        ("14:20:12", "task_d4e5f6", "classifier", "Output schema validation failed"),
        ("14:18:44", "task_g7h8i9", "translator", "Backend connection refused"),
    ]
    for i, (ts, tid, wt, reason) in enumerate(dl_rows):
        ry = y + 70 + i * 35
        s.text(55, ry + 12, ts, size=11, weight=400, fill="#666", anchor="start")
        s.text(250, ry + 12, tid, size=11, weight=500, fill="#555", anchor="start")
        s.rect(450, ry + 2, 90, 22, fill="#ffeedd", rx=11)
        s.text(495, ry + 13, wt, size=10, weight=500, fill="#cc7333")
        s.text(600, ry + 12, reason, size=11, weight=400, fill="#888", anchor="start")
        s.rect(900, ry + 2, 65, 22, fill="none", rx=4, stroke="#4278d9", sw=1)
        s.text(932, ry + 13, "Replay", size=10, weight=500, fill="#4278d9")

    # === PAGE 7: RAG Dashboard ===
    y = 1830
    s.text(40, y, "RAG Pipeline", size=20, weight=700, fill="#1e1e26", anchor="start")

    # Stats panel
    s.rect(40, y + 35, 350, 120, fill="#f8f8fa", rx=8, stroke="#eee", sw=1)
    s.text(55, y + 55, "Vector Store", size=13, weight=600, fill="#333", anchor="start")
    stats = [
        ("Total chunks:", "12,450"),
        ("Unique posts:", "3,200"),
        ("Unique channels:", "156"),
    ]
    for i, (label, val) in enumerate(stats):
        sy = y + 80 + i * 22
        s.text(55, sy, label, size=11, weight=400, fill="#888", anchor="start")
        s.text(200, sy, val, size=11, weight=600, fill="#333", anchor="start")

    # Channels panel
    s.rect(420, y + 35, 350, 120, fill="#f8f8fa", rx=8, stroke="#eee", sw=1)
    s.text(435, y + 55, "Channels", size=13, weight=600, fill="#333", anchor="start")
    s.text(435, y + 80, "156 channels  ·  142 verified", size=11, weight=400, fill="#888", anchor="start")
    s.text(435, y + 102, "Factions: reformist, principlist, irgc,", size=10, weight=400, fill="#999", anchor="start")
    s.text(435, y + 118, "independent, state_media", size=10, weight=400, fill="#999", anchor="start")

    # Search panel
    s.rect(40, y + 175, 730, 100, fill="#fff", rx=8, stroke="#ddd", sw=1)
    s.text(55, y + 195, "Quick Search", size=13, weight=600, fill="#333", anchor="start")
    s.rect(55, y + 215, 400, 30, fill="#fff", rx=4, stroke="#ccc", sw=1)
    s.text(70, y + 230, "Enter search query...", size=11, weight=400, fill="#aaa", anchor="start")
    s.rect(470, y + 215, 60, 30, fill="#fff", rx=4, stroke="#ccc", sw=1)
    s.text(500, y + 230, "10", size=11, weight=400, fill="#555")
    s.rect(545, y + 215, 80, 30, fill="#4278d9", rx=6)
    s.text(585, y + 230, "Search", size=11, weight=600, fill="#fff")

    # === NAVIGATION MAP ===
    y = 2120
    s.text(40, y, "Navigation Map", size=20, weight=700, fill="#1e1e26", anchor="start")

    pages = [
        ("/workers", "Workers List", ["/{name} — Worker Detail", "/{name}/test — Test Bench", "/{name}/eval — Eval Dashboard", "/{name}/eval/{id} — Eval Detail"]),
        ("/pipelines", "Pipelines List", ["/{name} — Pipeline Editor"]),
        ("/apps", "Apps List", ["/{name} — App Detail"]),
        ("/rag", "RAG Dashboard", ["/search — Semantic Search", "/channels — Channel Registry"]),
        ("/dead-letters", "Dead Letters", []),
    ]
    for i, (route, title, children) in enumerate(pages):
        px = 40 + i * 225
        s.rect(px, y + 35, 205, 40, fill="#1a1a2e", rx=6)
        s.text(px + 102, y + 55, title, size=11, weight=600, fill="#f5c72e")
        s.text(px + 102, y + 85, route, size=9, weight=400, fill="#888")
        for j, child in enumerate(children):
            cy = y + 105 + j * 28
            s.rect(px + 15, cy, 185, 24, fill="#f4f4f6", rx=4, stroke="#ddd", sw=1)
            s.text(px + 107, cy + 12, child, size=8, weight=400, fill="#666")
            s.line(px + 102, y + 75, px + 102, cy, color="#ddd", sw=1, dash="3 3")

    s.save(OUT / "workshop-ui.svg")


# ===========================================================================
# Diagram 5: NATS Message Topology
# ===========================================================================

def nats_topology():
    s = SVG(1100, 600)

    s.text(40, 38, "Loom — NATS Subject Topology", size=26, weight=700, fill="#1e1e26", anchor="start")
    s.text(40, 62, "Message routing conventions and subject hierarchy", size=12, weight=400, fill="#888", anchor="start")

    # Central NATS bus
    s.rect(350, 250, 400, 50, fill="#f5c72e", rx=8)
    s.text(550, 275, "NATS Server", size=16, weight=700, fill="#4a3800")

    # Subject groups — arranged around the bus
    subjects = [
        # (x, y, subject, direction, description, color, publishers, subscribers)
        (40, 100, "loom.goals.*", "#e85c5c",
         ["MCP Gateway", "CLI", "API"], ["OrchestratorActor"]),
        (40, 380, "loom.tasks.{type}.{tier}", "#cc7333",
         ["Router"], ["WorkerActors (queue group)"]),
        (780, 100, "loom.results.{goal_id}", "#4278d9",
         ["WorkerActors"], ["ResultStream"]),
        (780, 380, "loom.control.*", "#7d52c2",
         ["Workshop", "CLI"], ["All Actors"]),
        (350, 430, "loom.deadletter.*", "#999",
         ["Router", "Workers"], ["DeadLetterConsumer"]),
    ]

    for x, y, subj, color, pubs, subs in subjects:
        w = 280
        h = 100
        s.rect(x, y, w, h, fill="#fff", rx=8, stroke=color, sw=2)
        s.text(x + w / 2, y + 18, subj, size=12, weight=700, fill=color)

        # Publishers
        s.text(x + 10, y + 40, "pub:", size=9, weight=600, fill="#999", anchor="start")
        s.text(x + 40, y + 40, ", ".join(pubs), size=9, weight=400, fill="#666", anchor="start")

        # Subscribers
        s.text(x + 10, y + 58, "sub:", size=9, weight=600, fill="#999", anchor="start")
        s.text(x + 40, y + 58, ", ".join(subs), size=9, weight=400, fill="#666", anchor="start")

        # Arrows to/from NATS bus
        if x < 350:
            s.arrow(x + w, y + h / 2, 350, 275, color=color, sw=1.5)
        elif x >= 780:
            s.arrow(750, 275, x, y + h / 2, color=color, sw=1.5)

    # Special arrows for bottom subjects
    s.arrow(490, 300, 490, 430, color="#999", sw=1.5)

    # Queue group note
    s.note_box(40, 490, 400, 26, "Workers use NATS queue groups for load balancing across instances", bg="#fff8f0", border="#f0dfc0", text_color="#cc7333")

    # Control subjects detail
    s.note_box(780, 490, 280, 40, "loom.control.reload — hot-reload configs\nloom.control.shutdown — graceful stop", bg="#f4f0ff", border="#d4c8ee", text_color="#7d52c2")

    s.save(OUT / "nats-topology.svg")


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print("Generating Loom documentation diagrams...")
    architecture_overview()
    data_flow()
    developer_workflow()
    workshop_mockup()
    nats_topology()
    print(f"\nDone! {len(list(OUT.glob('*.svg')))} SVGs in {OUT}/")
