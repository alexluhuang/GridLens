"""Draw the GridLens system architecture diagram as SVG and PNG.

The diagram is a component and deployment view of one workstation: the
external systems GridLens talks to, the boundary of the machine, the
desktop application and its layers, the agent runtime, the processes
and containers GridLens starts, the files it keeps, and the hardware
each part uses. Arrows are labelled with what crosses them; tags mark
security controls and error handling. Facts are taken from
docs/ARCHITECTURE.md and the code, and the commit the diagram describes
is printed in its footer.

    python scripts/draw_architecture_diagram.py [--output PATH]

PATH is the output path without a suffix, by default
docs/diagrams/gridlens_architecture.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import (
    Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle,
)


WIDTH, HEIGHT = 160, 124
FONT = "DejaVu Sans"
INK = "#1F2933"
MUTED = "#52606D"
# One fill and edge per layer, chosen to stay distinguishable for
# common color-vision deficiencies.
LAYERS = {
    "external": ("#FFFFFF", "#7B8794"),
    "gui": ("#DCE9F7", "#2B5C8A"),
    "core": ("#E8EBEF", "#4A5568"),
    "agent": ("#FCEFD4", "#B7791F"),
    "process": ("#DDF1EE", "#2C7A7B"),
    "data": ("#ECE7F5", "#553C9A"),
    "hardware": ("#F4F5F7", "#7B8794"),
}
SECURITY = "#9B2C2C"
ERROR = "#C05621"
DEFAULT_OUTPUT = Path("docs/diagrams/gridlens_architecture")
# A fixed salt for the SVG's element IDs, and no date in its metadata,
# so redrawing an unchanged diagram writes the same file.
SVG_ID_SALT = "gridlens-architecture"


def commit() -> str:
    """Return the short commit the diagram describes.

    Outside a git checkout, returns "working tree".
    """
    try:
        found = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True,
            text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        found = "working tree"
    return found


class Canvas:
    """A WIDTH x HEIGHT grid of data units, and what is drawn on it."""

    def __init__(self) -> None:
        """Start an empty figure with no axes shown."""
        self.figure, self.axes = plt.subplots(figsize=(20, 15.5))
        self.axes.set_xlim(0, WIDTH)
        self.axes.set_ylim(0, HEIGHT)
        self.axes.axis("off")

    def text(self, x, y, text, **style) -> None:
        """Write text in the diagram's font."""
        style.setdefault("family", FONT)
        self.axes.text(x, y, text, **style)

    def box(self, x, y, w, h, layer, title, lines=(), *, title_size=10.5,
            size=8.2, dashed=False, align="left", radius=0.8, tags=(),
            edge=None):
        """Draw a rounded box with a title, lines of text, and tags.

        The tags run along the box's bottom edge.
        """
        fill, layer_edge = LAYERS[layer]
        edge = edge or layer_edge
        self.axes.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fill, edgecolor=edge, linewidth=1.6,
            linestyle=(0, (4, 3)) if dashed else "solid", zorder=2,
        ))
        anchor = x + 0.9 if align == "left" else x + w / 2
        self.text(anchor, y + h - 1.0, title, ha=align, va="top",
                  fontsize=title_size, fontweight="bold",
                  color=edge if layer != "core" else INK, zorder=4)
        top = y + h - 1.0 - title_size * 0.205
        for index, line in enumerate(lines):
            self.text(anchor, top - index * size * 0.185, line, ha=align,
                      va="top", fontsize=size, color=INK, zorder=4)
        for index, (kind, text) in enumerate(reversed(tags)):
            self.tag(x + 0.9, y + 1.3 + index * 2.0, text, kind)

    def store(self, x, y, w, h, title, lines=(), *, size=8.0):
        """Draw a data store as a cylinder."""
        fill, edge = LAYERS["data"]
        cap = 1.6
        self.axes.add_patch(Rectangle((x, y + cap / 2), w, h - cap,
                                      facecolor=fill, edgecolor="none",
                                      zorder=2))
        self.axes.add_patch(Ellipse((x + w / 2, y + cap / 2), w, cap,
                                    facecolor=fill, edgecolor=edge,
                                    linewidth=1.6, zorder=2))
        for side in (x, x + w):
            self.axes.plot([side, side], [y + cap / 2, y + h - cap / 2],
                           color=edge, linewidth=1.6, zorder=3)
        self.axes.add_patch(Ellipse((x + w / 2, y + h - cap / 2), w, cap,
                                    facecolor=fill, edgecolor=edge,
                                    linewidth=1.6, zorder=3))
        self.text(x + 0.9, y + h - cap - 0.5, title, ha="left", va="top",
                  fontsize=9.6, fontweight="bold", color=edge, zorder=4)
        for index, line in enumerate(lines):
            self.text(x + 0.9, y + h - cap - 2.6 - index * size * 0.185,
                      line, ha="left", va="top", fontsize=size, color=INK,
                      zorder=4)

    def zone(self, x, y, w, h, label, edge, *, size=9.5, dashed=True,
             fill="none"):
        """Draw a boundary or grouping, labelled at its top left."""
        self.axes.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2",
            facecolor=fill, edgecolor=edge, linewidth=2.0,
            linestyle=(0, (6, 4)) if dashed else "solid", zorder=1,
        ))
        self.text(x + 1.0, y + h - 0.7, label, ha="left", va="top",
                  fontsize=size, fontweight="bold", color=edge, zorder=4)

    def tag(self, x, y, text, kind):
        """Draw a tag for a security control or an error path."""
        color = SECURITY if kind == "sec" else ERROR
        mark = "SEC" if kind == "sec" else "ERR"
        backing = dict(boxstyle="round,pad=0.18,rounding_size=0.3",
                       facecolor=color, edgecolor=color)
        self.text(x, y, f" {mark} ", ha="left", va="center", fontsize=6.6,
                  fontweight="bold", color="white", zorder=6, bbox=backing)
        self.text(x + 3.3, y, text, ha="left", va="center", fontsize=7.4,
                  color=color, zorder=6, style="italic")

    def arrow(self, start, end, *, color=INK, dashed=False, both=False):
        """Draw an arrow from start to end, with two heads if both."""
        self.axes.add_patch(FancyArrowPatch(
            start, end, arrowstyle="<|-|>" if both else "-|>",
            mutation_scale=13, color=color, linewidth=1.5,
            linestyle=(0, (4, 3)) if dashed else "solid",
            connectionstyle="arc3,rad=0.0", zorder=5, shrinkA=1, shrinkB=1,
        ))

    def label(self, x, y, text, *, size=7.3, ha="left", color=INK):
        """Write an arrow label on a white backing, legible on lines."""
        backing = dict(boxstyle="round,pad=0.12", facecolor="white",
                       edgecolor="none", alpha=0.92)
        self.text(x, y, text, ha=ha, va="center", fontsize=size,
                  color=color, zorder=6, bbox=backing)

    def save(self, output: Path) -> None:
        """Write the diagram as output.svg and output.png."""
        output.parent.mkdir(parents=True, exist_ok=True)
        with matplotlib.rc_context({"svg.hashsalt": SVG_ID_SALT}):
            self.figure.savefig(output.with_suffix(".svg"),
                                bbox_inches="tight", facecolor="white",
                                metadata={"Date": None})
        self.figure.savefig(output.with_suffix(".png"), dpi=160,
                            bbox_inches="tight", facecolor="white")


def draw(output: Path) -> None:
    """Draw the whole diagram and write it to output's SVG and PNG."""
    canvas = Canvas()
    _draw_title(canvas)
    _draw_external_systems(canvas)
    _draw_application(canvas)
    _draw_agent_runtime(canvas)
    _draw_processes(canvas)
    _draw_files_and_hardware(canvas)
    _draw_boundary_arrows(canvas)
    _draw_application_arrows(canvas)
    _draw_agent_arrows(canvas)
    _draw_legend(canvas)
    canvas.save(output)


def _draw_title(c: Canvas) -> None:
    """Write the title and the one-line summary under it."""
    c.text(1, 123, "GridLens system architecture", ha="left", va="top",
           fontsize=19, fontweight="bold", color=INK)
    c.text(1, 119.2,
           "Component and deployment view. Everything inside the dashed "
           "boundary runs on one workstation, and no project data leaves it.",
           ha="left", va="top", fontsize=10.5, color=MUTED)


def _draw_external_systems(c: Canvas) -> None:
    """Draw the people and systems outside the workstation."""
    c.box(1, 95, 19.2, 11, "external", "Planner or regulator",
          ["Opens projects, runs studies,", "reads charts, asks Clarke"],
          title_size=10, size=7.8)
    c.box(1, 74, 19.2, 12, "external", "Install sources",
          ["hermes-agent.nousresearch.com,",
           "ollama.com and its model library;",
           "setup only, after the user agrees"],
          title_size=10, size=7.4, dashed=True)
    c.box(1, 52, 19.2, 11.5, "external", "Container registry",
          ["Image pulls only when the pull", "policy is missing or always;",
           "the default is never"],
          title_size=10, size=7.6, dashed=True)
    c.box(1, 29, 19.2, 12, "external", "Hosted model APIs",
          ["Claude Code, Codex adapters;", "disabled by policy, refused",
           "unless an operator enables them"],
          title_size=10, size=7.6, dashed=True, edge=SECURITY)
    c.zone(22, 13, 136, 101,
           "User's workstation: NVIDIA DGX Spark, DGX OS 7 (Ubuntu 24.04, "
           "ARM64)", "#1F4E79", size=11)
    c.tag(98.5, 113.25,
          "no telemetry; network traffic only for consented setup downloads "
          "and permitted image pulls", "sec")


def _draw_application(c: Canvas) -> None:
    """Draw the desktop application, its controller, and its layers."""
    c.zone(23.5, 88, 68.5, 21.5,
           "GridLens desktop application  (one PySide6 / Qt 6 process)",
           LAYERS["gui"][1], dashed=False, fill="#F3F8FD", size=10)
    tabs = ["Project", "Configuration", "Run", "Sensitivity\nAnalysis",
            "Results", "Branch\nAnalysis", "Transformer\nAnalysis",
            "Agent\n(Clarke)"]
    for index, name in enumerate(tabs):
        c.box(25 + index * 8.25, 96.5, 7.7, 7.2, "gui", name, (),
              title_size=6.7, align="center", radius=0.5)
    c.text(25, 93.8,
           "QThread workers keep the window responsive; view models hold "
           "form logic shared with the agent tools",
           fontsize=7.5, color=MUTED, va="center")
    c.text(25, 91.4,
           "Set up Clarke window installs Hermes, Ollama, and models; the "
           "review dialog runs approved scripts",
           fontsize=7.5, color=MUTED, va="center")
    c.box(99, 88, 57.5, 21.5, "agent",
          "Agent controller  (AgentController, in the GUI process)", [
              "Runs one turn: writes the prompt file, starts the runtime, "
              "reads its events",
              "Checks every cited call ID against the tool audit",
              "Adds disclosures: truncated results, failed tools, changes "
              "awaiting confirmation",
              "Records each turn's time in tools and in the model, and its "
              "token counts",
              "Limits: 3,600 s per turn and 16 MiB of runtime output",
          ], size=8.0,
          tags=[("err", "a citation that matches no recorded call is "
                        "marked invalid")])
    c.zone(23.5, 56, 68.5, 25, "Application core  (plain Python, no Qt)",
           LAYERS["core"][1], dashed=False, fill="#F7F8FA", size=10)
    core = [
        ("runner/", ["docker run command", "as an argument list;",
                     "run and stop;", "progress from output"]),
        ("core/", ["Projects; inputs with", "SHA-256 hashes; run",
                   "manifests; sensitivity", "runs; settings"]),
        ("psse/", ["PSS/E RAW v33-35", "reader; byte-preserving",
                   "patcher; edits named", "by bus and ID"]),
        ("analysis/", ["Output parsers; GPU", "CSV aggregation;",
                       "caches; event index;", "network topology"]),
    ]
    for index, (name, lines) in enumerate(core):
        c.box(25 + index * 16.6, 58, 15.6, 18.5, "core", name, lines,
              title_size=10, size=8.0)


def _draw_agent_runtime(c: Canvas) -> None:
    """Draw the chat model, the runtime CLI, and the tool server."""
    c.zone(98, 56, 58.5, 25, "Agent runtime  (per turn)", LAYERS["agent"][1],
           dashed=False, fill="#FFF9EE", size=10)
    c.box(99.5, 68.3, 24, 10.0, "agent", "Chat model  (Ollama)",
          ["Nemotron 3.5 Lightning preferred;",
           "plans tool calls, writes answers", "127.0.0.1:11434"],
          title_size=9.5, size=7.4, tags=[("sec", "loopback only; rechecked")])
    c.box(132, 68.3, 23.5, 10.0, "agent", "Hermes Agent 0.21.4 CLI",
          ["One process per turn", "Isolated profile per session",
           "GridLens tools only; 60 turns"],
          title_size=9.5, size=7.6)
    c.box(99.5, 56.8, 56, 9.6, "agent",
          "GridLens MCP server  +  ToolService  (18 audited tools)", [
              "rank, rank_groups · topology · list_files, read_file · "
              "search_documents · propose_analysis_script",
              "projects, configuration, runs, sensitivity runs, analysis "
              "builds, status, stop",
          ], title_size=8.8, size=7.3, tags=[
              ("sec", "paths scoped; inputs, XML, stop, and edited-case runs "
                      "wait for the user's next message"),
              ("err", "stale caches and indexes refused, never quoted"),
          ])


def _draw_processes(c: Canvas) -> None:
    """Draw the processes and containers GridLens starts."""
    c.zone(23.5, 33, 46.5, 17.5, "Docker Engine", LAYERS["process"][1],
           dashed=False, fill="#F2FAF9", size=10)
    c.box(25, 34.3, 21.5, 13.2, "process", "GridPACK container",
          ["mpirun -n <N> ca.x <xml>", "Mounts only the run's work/",
           "Host UID and GID"],
          title_size=9.3, size=7.6, tags=[("sec", "network none; pull never")])
    c.box(47.5, 34.3, 21.5, 13.2, "process", "Script sandbox",
          ["User-approved script only", "Run folder read-only, no GPU",
           "2 CPUs, 1 GiB, 120 s"],
          title_size=9.3, size=7.6,
          tags=[("sec", "SHA-256 approved; no network")])
    c.box(72.5, 33, 24, 17.5, "process", "Analysis worker",
          ["Spawned process per build;", "one build at a time (lock)",
           "RAPIDS cuDF / dask-cuDF", "on the GPU"],
          title_size=9.5, size=7.6, tags=[("err", "GPU -> CPU fallbacks")])
    c.box(100, 33, 22, 17.5, "process", "Agent job workers",
          ["gridlens --agent-job, detached", "Runs and analysis builds the",
           "agent starts, through the same", "functions as the GUI"],
          title_size=9.5, size=7.6,
          tags=[("err", "dead worker reported failed")])
    # Labelled at its top right, so the search_documents arrow enters
    # clear of the label.
    c.zone(124.5, 33, 32, 17.5, "", LAYERS["process"][1], dashed=False,
           fill="#F2FAF9")
    c.text(155.8, 49.8, "Document search", ha="right", va="top",
           fontsize=8.6, fontweight="bold", color=LAYERS["process"][1],
           zorder=4)
    c.box(125.5, 34, 13, 13.4, "process", "Document index",
          ["In the MCP server", "pypdf text by page,", "cached by SHA-256",
           "BM25 + similarity,", "averaged"],
          title_size=8.6, size=7.0)
    c.box(142.3, 34, 13.7, 13.4, "agent", "Embedding model",
          ["embeddinggemma via", "the same local Ollama",
           "(/api/embed), apart", "from the chat model",
           "Task prompts on query", "and passages"],
          title_size=8.0, size=6.8, tags=[("sec", "loopback only")])


def _draw_files_and_hardware(c: Canvas) -> None:
    """Draw the files on the local disk and the hardware strip."""
    c.store(23.5, 17.5, 76, 11.5,
            "Projects folder  ~/GridLensProjects/<project>/", [
                "project.json; original_inputs/ (RAW case, GridPACK XML); "
                "agent/jobs/ (job.json, job.log)",
                "runs/<id>/: manifest.json (exact command, input SHA-256); "
                "work/ (GridPACK outputs, CSV flat ~8.7 GB);",
                "reports/ (analysis caches, Parquet event index)",
            ], size=7.6)
    c.store(102, 17.5, 25, 11.5, "Clarke conversations/",
            ["transcript, tool_calls audit,", "results/, conversation.md",
             "(files 0600)"], size=7.6)
    c.store(129.5, 17.5, 14, 11.5, "Reference docs/",
            ["PDF, text, HTML;", ".gridlens-index/"], size=7.4)
    c.store(145.5, 17.5, 11, 11.5, "Installs",
            ["settings.json,", "Hermes, Ollama,", "model weights"], size=7.2)
    c.box(23.5, 13.8, 133, 2.6, "hardware", "", (), title_size=1,
          radius=0.4)
    c.text(25, 15.1,
           "Hardware:  20 Arm cores (10 Cortex-X925, 10 Cortex-A725): "
           "GridPACK MPI ranks, GUI, workers     Blackwell GPU: cuDF "
           "aggregation, model inference     128 GB unified memory",
           fontsize=7.9, color=INK, va="center")


def _draw_boundary_arrows(c: Canvas) -> None:
    """Draw the arrows that cross the workstation's boundary."""
    c.arrow((19.5, 100.5), (23.5, 100.5))
    c.label(19.6, 102.2, "uses", size=7.0)
    c.arrow((19.5, 80), (23.5, 90.5), dashed=True, color=MUTED)
    c.label(19.7, 86.5, "after\nconsent", size=6.8, color=MUTED)
    c.arrow((19.5, 57.5), (23.5, 48.5), dashed=True, color=MUTED)
    c.label(19.7, 51.5, "image\npull", size=6.8, color=MUTED)
    c.arrow((19.5, 35), (22, 35), dashed=True, color=SECURITY)
    c.text(22, 35, "x", ha="center", va="center", fontsize=15,
           fontweight="bold", color=SECURITY, zorder=7)


def _draw_application_arrows(c: Canvas) -> None:
    """Draw the arrows of the GUI's path to runs and analyses."""
    c.arrow((92, 99), (99, 99), both=True)
    c.label(95.5, 96.7, "question,\nanswer", size=6.8, ha="center")
    c.arrow((57.75, 88), (57.75, 81))
    c.label(58.5, 84.5, "function calls")
    c.arrow((38.5, 58), (38.5, 47.5))
    c.label(39.2, 53.6, "docker run (argument list)")
    c.arrow((35.75, 34.3), (35.75, 29))
    c.label(36.5, 31.4, "bind mount work/")
    c.arrow((82.6, 58), (82.6, 50.5))
    c.label(83.3, 54.2, "spawn; progress queue")
    c.arrow((84.5, 33), (84.5, 29), both=True)
    c.label(83.8, 31.0, "read outputs, write caches", size=7.0, ha="right")


def _draw_agent_arrows(c: Canvas) -> None:
    """Draw the arrows of the agent's path, from a turn to its files."""
    c.arrow((144, 88), (144, 78.3))
    c.label(144.7, 84.3, "subprocess per turn;\nstream-json events",
            size=7.0)
    c.arrow((132, 73.5), (123.5, 73.5), both=True)
    c.label(127.75, 76.3, "HTTP,\nloopback", size=6.6, ha="center")
    c.arrow((144, 68.3), (144, 66.4), both=True)
    c.label(144.7, 67.35, "MCP over stdio", size=6.9)
    # The tool server imports the application core and calls it
    # directly, as the GUI does.
    c.arrow((99.5, 61.6), (92, 61.6))
    c.label(95.75, 64.6, "same\nfunction\ncalls", size=6.6, ha="center")
    c.arrow((112.5, 56.8), (112.5, 50.5))
    c.label(113.2, 53.8, "start job", size=7.0)
    c.arrow((136.8, 56.8), (136.8, 47.4))
    c.label(137.5, 53.8, "search_documents", size=7.0)
    c.arrow((138.5, 42.5), (142.3, 42.5), both=True)
    c.text(140.4, 45.3, "text", ha="center", va="center", fontsize=6.3,
           color=INK, zorder=6)
    c.text(140.4, 39.8, "vectors", ha="center", va="center", fontsize=6.3,
           color=INK, zorder=6)
    c.arrow((100, 42), (96.5, 42))
    c.axes.plot([106, 106, 61], [50.5, 52.6, 52.6], color=INK,
                linewidth=1.5, zorder=5)
    c.arrow((61, 52.6), (61, 50.5))
    c.label(64.5, 52.6, "runs GridPACK", size=6.8)
    c.arrow((123.25, 56.8), (123.25, 29))
    c.arrow((99.6, 56.8), (98.6, 29))
    c.arrow((133, 34), (133, 29))
    c.label(133.7, 31.0, "reads; caches text and vectors", size=6.8)
    c.label(99.3, 31.0, "scoped reads", size=6.8)
    c.label(113.5, 31.0, "audit appends", size=6.8)


def _draw_legend(c: Canvas) -> None:
    """Draw the legend and the footer naming the commit drawn."""
    c.axes.add_patch(Rectangle((1, 1.2), 157, 9.4, facecolor="#FAFBFC",
                               edgecolor="#CBD2D9", linewidth=1.0,
                               zorder=1))
    c.text(2, 9.3, "Legend", ha="left", va="center", fontsize=9.5,
           fontweight="bold", color=INK)
    items = [("gui", "Desktop GUI"), ("core", "Application layers"),
             ("agent", "Agent runtime"),
             ("process", "Processes and containers"),
             ("external", "External system")]
    for index, (layer, name) in enumerate(items):
        fill, edge = LAYERS[layer]
        x = 2 + index * 19
        c.axes.add_patch(FancyBboxPatch(
            (x, 5.4), 3.2, 2.2, boxstyle="round,pad=0,rounding_size=0.3",
            facecolor=fill, edgecolor=edge, linewidth=1.4, zorder=2,
        ))
        c.text(x + 4, 6.5, name, ha="left", va="center", fontsize=8.2,
               color=INK)
    x = 2 + 5 * 19
    c.axes.add_patch(Ellipse((x + 1.6, 6.5), 3.2, 2.0,
                             facecolor=LAYERS["data"][0],
                             edgecolor=LAYERS["data"][1], linewidth=1.4,
                             zorder=2))
    c.text(x + 4, 6.5, "Files on local disk", ha="left", va="center",
           fontsize=8.2, color=INK)
    c.axes.add_patch(FancyArrowPatch((2, 2.9), (7, 2.9), arrowstyle="-|>",
                                     mutation_scale=12, color=INK,
                                     linewidth=1.5))
    c.text(8, 2.9, "Control or data flow, labelled with what crosses it",
           ha="left", va="center", fontsize=8.2, color=INK)
    c.axes.add_patch(FancyArrowPatch((48, 2.9), (53, 2.9), arrowstyle="-|>",
                                     mutation_scale=12, color=MUTED,
                                     linewidth=1.5, linestyle=(0, (4, 3))))
    c.text(54, 2.9, "Optional or conditional connection", ha="left",
           va="center", fontsize=8.2, color=INK)
    c.text(84, 2.9, "x", ha="center", va="center", fontsize=13,
           fontweight="bold", color=SECURITY)
    c.text(85.5, 2.9, "Blocked by policy", ha="left", va="center",
           fontsize=8.2, color=INK)
    c.tag(104, 2.9, "Security control", "sec")
    c.tag(127, 2.9, "Error handling or fallback", "err")
    c.text(158, 0.2,
           f"Source: docs/ARCHITECTURE.md and the code at commit {commit()}. "
           "Drawn by scripts/draw_architecture_diagram.py.",
           ha="right", va="bottom", fontsize=7.0, color=MUTED)


def main() -> None:
    """Draw the diagram where the command line says."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="output path without suffix; .svg and .png "
                             "are written")
    options = parser.parse_args()
    matplotlib.use("Agg")
    draw(options.output)
    print(f"wrote {options.output.with_suffix('.svg')} and "
          f"{options.output.with_suffix('.png')}")


if __name__ == "__main__":
    main()
