from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import ast
import csv
import hashlib
import io
import json
import math
import multiprocessing
from pathlib import Path
import shutil
import statistics
import sys
import traceback
from contextlib import redirect_stdout

from gridpack_workbench.analysis.dataset import build_run_analysis
from gridpack_workbench.core.app_settings import AppSettings


ALLOWED_TOOLS = [
    "load_analysis_manifest",
    "query_analysis_table",
    "compute_metric",
    "make_chart",
    "run_python_analysis",
    "save_answer_artifact",
]


@dataclass(slots=True)
class ToolCitation:
    tool: str
    source: str
    detail: str

    def as_text(self) -> str:
        return f"{self.tool}: {self.source} ({self.detail})"


@dataclass(slots=True)
class AgentToolResult:
    tool: str
    data: object
    citations: list[ToolCitation] = field(default_factory=list)
    artifact_path: str = ""


@dataclass(slots=True)
class AgentAnswer:
    answer: str
    citations: list[ToolCitation]
    artifact_paths: list[str] = field(default_factory=list)
    supported: bool = True

    def to_html(self) -> str:
        citation_items = "".join(f"<li>{citation.as_text()}</li>" for citation in self.citations)
        artifact_items = "".join(f"<li>{path}</li>" for path in self.artifact_paths)
        return (
            f"<p>{self.answer}</p>"
            f"<h3>Citations</h3><ul>{citation_items or '<li>No citations produced.</li>'}</ul>"
            f"<h3>Artifacts</h3><ul>{artifact_items or '<li>No artifacts.</li>'}</ul>"
        )


class AnalysisToolbox:
    def __init__(self, run_dir: str | Path, max_rows: int = 50, timeout_seconds: int = 20) -> None:
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds
        self.dataset = build_run_analysis(self.run_dir)

    @property
    def reports_dir(self) -> Path:
        return self.run_dir / "reports"

    def create_session_dir(self) -> Path:
        base = self.reports_dir / "agent_sessions"
        base.mkdir(parents=True, exist_ok=True)
        session = base / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = 2
        while session.exists():
            session = base / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{suffix}"
            suffix += 1
        session.mkdir(parents=True)
        return session

    def load_analysis_manifest(self) -> AgentToolResult:
        manifest = json.loads(self.dataset.manifest_path.read_text(encoding="utf-8"))
        return AgentToolResult(
            "load_analysis_manifest",
            manifest,
            [ToolCitation("load_analysis_manifest", str(self.dataset.manifest_path), f"run_dir={self.run_dir}")],
        )

    def query_analysis_table(
        self,
        table_name: str,
        filters: dict[str, object] | None = None,
        sort_by: str | None = None,
        descending: bool = True,
        limit: int | None = None,
    ) -> AgentToolResult:
        rows = list(self._load_table_rows(table_name))
        filters = filters or {}
        for column, expected in filters.items():
            rows = [row for row in rows if str(row.get(column, "")) == str(expected)]
        if sort_by:
            rows.sort(key=lambda row: _sort_value(row.get(sort_by)), reverse=descending)
        capped = rows[: min(limit or self.max_rows, self.max_rows)]
        detail = f"table={table_name}, filters={filters}, sort_by={sort_by}, returned={len(capped)}"
        return AgentToolResult(
            "query_analysis_table",
            capped,
            [ToolCitation("query_analysis_table", self._table_source(table_name), detail)],
        )

    def compute_metric(self, metric_path: str) -> AgentToolResult:
        value: object = self.dataset.metrics
        for part in metric_path.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
        return AgentToolResult(
            "compute_metric",
            value,
            [ToolCitation("compute_metric", str(self.dataset.manifest_path), f"metric={metric_path}")],
        )

    def make_chart(self, table_name: str, x_column: str, y_column: str, title: str, limit: int = 20) -> AgentToolResult:
        rows = self.query_analysis_table(table_name, sort_by=y_column, descending=True, limit=limit).data
        session = self.create_session_dir()
        chart_spec = {
            "title": title,
            "table": table_name,
            "x_column": x_column,
            "y_column": y_column,
            "rows": rows,
        }
        artifact = session / "chart_spec.json"
        artifact.write_text(json.dumps(chart_spec, indent=2), encoding="utf-8")
        citations = [ToolCitation("make_chart", self._table_source(table_name), f"x={x_column}, y={y_column}, limit={limit}")]

        try:
            from matplotlib.figure import Figure

            labels = [str(row.get(x_column, "")) for row in rows]  # type: ignore[union-attr]
            values = [float(row.get(y_column, 0) or 0) for row in rows]  # type: ignore[union-attr]
            figure = Figure(figsize=(8, 4))
            axis = figure.add_subplot(111)
            axis.bar(labels, values, color="#2f6f9f")
            axis.set_title(title)
            axis.set_ylabel(y_column)
            axis.tick_params(axis="x", labelrotation=45)
            figure.tight_layout()
            png = session / "chart.png"
            figure.savefig(png)
            return AgentToolResult("make_chart", chart_spec, citations, str(png))
        except Exception:
            return AgentToolResult("make_chart", chart_spec, citations, str(artifact))

    def save_answer_artifact(self, file_name: str, content: str) -> AgentToolResult:
        session = self.create_session_dir()
        artifact = _safe_child(session, file_name)
        artifact.write_text(content, encoding="utf-8")
        return AgentToolResult(
            "save_answer_artifact",
            {"artifact": str(artifact)},
            [ToolCitation("save_answer_artifact", str(artifact), "written inside agent session directory")],
            str(artifact),
        )

    def run_python_analysis(self, code: str) -> AgentToolResult:
        _validate_restricted_code(code)
        session = self.create_session_dir()
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        (session / "analysis_code.py").write_text(code, encoding="utf-8")

        queue: multiprocessing.Queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_restricted_python_worker,
            args=(str(self.run_dir), str(session), self.max_rows, code, queue),
        )
        process.start()
        process.join(self.timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(2)
            result = {"ok": False, "error": f"Timed out after {self.timeout_seconds} seconds.", "stdout": ""}
        else:
            result = queue.get() if not queue.empty() else {"ok": False, "error": "No result returned.", "stdout": ""}
        result["code_sha256"] = code_hash
        (session / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return AgentToolResult(
            "run_python_analysis",
            result,
            [ToolCitation("run_python_analysis", str(session / "analysis_code.py"), f"sha256={code_hash}")],
            str(session / "result.json"),
        )

    def _load_table_rows(self, table_name: str) -> list[dict[str, str]]:
        if table_name not in self.dataset.tables:
            raise KeyError(f"Unknown analysis table: {table_name}")
        csv_path = self.dataset.table_files[table_name]["csv"]
        with Path(csv_path).open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _table_source(self, table_name: str) -> str:
        table = self.dataset.tables.get(table_name)
        if not table:
            return table_name
        return f"{self.dataset.table_files[table_name]['csv']} from {table.source_file}"


class NemoClawAgentService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        configured_path = self.settings.nemoclaw_cli_path.strip()
        if not configured_path:
            return False
        return shutil.which(configured_path) is not None or Path(configured_path).exists()

    def configuration_status(self) -> str:
        if self.is_configured():
            return f"NemoClaw configured: {self.settings.nemoclaw_cli_path}"
        return "NemoClaw is not configured. Set a valid nemoclaw CLI path in settings.json to enable the assistant."

    def answer(self, run_dir: str | Path, question: str) -> AgentAnswer:
        if not self.is_configured():
            return AgentAnswer(self.configuration_status(), [], supported=False)
        toolbox = AnalysisToolbox(
            run_dir,
            max_rows=self.settings.agent_max_returned_rows,
            timeout_seconds=self.settings.agent_tool_timeout_seconds,
        )
        policy_path = self._write_nemoclaw_policy(toolbox)
        answer = answer_with_tools(toolbox, question)
        answer.artifact_paths.insert(0, str(policy_path))
        answer.citations.append(
            ToolCitation(
                "nemoclaw_policy",
                str(policy_path),
                "read-only run/tables, writable session directory, inference.local-only egress",
            )
        )
        return answer

    def _write_nemoclaw_policy(self, toolbox: AnalysisToolbox) -> Path:
        session = toolbox.create_session_dir()
        policy = {
            "runtime": "NemoClaw/OpenShell",
            "run_dir": str(toolbox.run_dir),
            "read_only_mounts": [
                str(toolbox.run_dir / "work"),
                str(toolbox.dataset.table_dir),
                str(toolbox.dataset.manifest_path),
            ],
            "writable_mounts": [str(session)],
            "network_egress_allowlist": ["inference.local"],
            "credential_policy": "credentials remain on host; sandbox receives routed inference only",
            "allowlisted_tools": ALLOWED_TOOLS,
            "tool_timeout_seconds": self.settings.agent_tool_timeout_seconds,
            "max_returned_rows": self.settings.agent_max_returned_rows,
            "require_citations": self.settings.agent_require_citations,
            "model_provider": self.settings.llm_provider_name,
            "model_name": self.settings.llm_model_name,
            "note": "Site-specific NemoClaw launch commands should mount these paths with equivalent policy.",
        }
        path = session / "nemoclaw_policy.json"
        path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
        return path


def answer_with_tools(toolbox: AnalysisToolbox, question: str) -> AgentAnswer:
    lowered = question.lower()
    citations: list[ToolCitation] = []
    artifacts: list[str] = []

    if any(word in lowered for word in ("success", "failed", "failure", "converged")):
        metric = toolbox.compute_metric("success")
        citations.extend(metric.citations)
        data = metric.data if isinstance(metric.data, dict) else {}
        return AgentAnswer(
            (
                f"This run has {data.get('success', 0)} successful contingencies, "
                f"{data.get('failure', 0)} failed contingencies, and a success rate of "
                f"{data.get('success_rate_pct', 0)}%."
            ),
            citations,
            artifacts,
        )

    if any(word in lowered for word in ("bottleneck", "thermal", "utilization", "headroom", "overload")):
        metric = toolbox.compute_metric("thermal")
        table = toolbox.query_analysis_table("perf_mm", sort_by="max_utilization_pct", descending=True, limit=5)
        citations.extend(metric.citations)
        citations.extend(table.citations)
        top = table.data[0] if isinstance(table.data, list) and table.data else {}
        chart = toolbox.make_chart("perf_mm", "row_index", "max_utilization_pct", "Top Thermal Bottlenecks", limit=10)
        artifacts.append(chart.artifact_path)
        citations.extend(chart.citations)
        return AgentAnswer(
            (
                "The highest ranked thermal bottleneck is "
                f"row {top.get('row_index', 'n/a')} on {top.get('from_bus', 'n/a')}-"
                f"{top.get('to_bus', 'n/a')} line {top.get('line_id', 'n/a')}, with "
                f"{top.get('max_utilization_pct', 'n/a')}% worst-contingency utilization. "
                "The answer is based on the parsed perf_mm table, not general model knowledge."
            ),
            citations,
            artifacts,
        )

    if any(word in lowered for word in ("voltage", "vmag", "bus")):
        metric = toolbox.compute_metric("voltage")
        table = toolbox.query_analysis_table("vmag_mm", sort_by="min_value", descending=False, limit=5)
        citations.extend(metric.citations)
        citations.extend(table.citations)
        top = table.data[0] if isinstance(table.data, list) and table.data else {}
        return AgentAnswer(
            (
                "The lowest voltage bus in the parsed vmag_mm table is "
                f"bus {top.get('bus_id', 'n/a')} ({top.get('bus_name', '')}), with "
                f"minimum voltage {top.get('min_value', 'n/a')} p.u. at contingency "
                f"{top.get('min_contingency', 'n/a')}."
            ),
            citations,
            artifacts,
        )

    if any(word in lowered for word in ("fault", "line fault")):
        table = toolbox.query_analysis_table("line_flt_cnt", sort_by="fault_count", descending=True, limit=5)
        citations.extend(table.citations)
        top = table.data[0] if isinstance(table.data, list) and table.data else {}
        return AgentAnswer(
            (
                "The line with the largest parsed fault count is "
                f"{top.get('from_bus', 'n/a')}-{top.get('to_bus', 'n/a')} line "
                f"{top.get('line_id', 'n/a')}, with count {top.get('fault_count', 'n/a')}."
            ),
            citations,
            artifacts,
        )

    manifest = toolbox.load_analysis_manifest()
    citations.extend(manifest.citations)
    return AgentAnswer(
        "I cannot answer that from the allowlisted GridPACK analysis tools yet. Ask about success rates, thermal bottlenecks, voltage, or line fault counts, or add a deterministic tool for this question type.",
        citations,
        artifacts,
        supported=False,
    )


def _restricted_python_worker(run_dir: str, session_dir: str, max_rows: int, code: str, queue: multiprocessing.Queue) -> None:
    try:
        toolbox = AnalysisToolbox(run_dir, max_rows=max_rows)
        stdout = io.StringIO()
        saved_artifacts: list[str] = []

        def read_table(name: str, limit: int | None = None) -> list[dict[str, str]]:
            result = toolbox.query_analysis_table(name, limit=limit or max_rows)
            return result.data  # type: ignore[return-value]

        def metric(name: str) -> object:
            return toolbox.compute_metric(name).data

        def save_artifact(name: str, content: str) -> str:
            path = _safe_child(Path(session_dir), name)
            path.write_text(str(content), encoding="utf-8")
            saved_artifacts.append(str(path))
            return str(path)

        globals_dict = {
            "__builtins__": {
                "abs": abs,
                "bool": bool,
                "dict": dict,
                "enumerate": enumerate,
                "float": float,
                "int": int,
                "len": len,
                "list": list,
                "max": max,
                "min": min,
                "print": print,
                "range": range,
                "round": round,
                "set": set,
                "sorted": sorted,
                "str": str,
                "sum": sum,
                "tuple": tuple,
            },
            "math": math,
            "statistics": statistics,
            "read_table": read_table,
            "metric": metric,
            "save_artifact": save_artifact,
        }
        with redirect_stdout(stdout):
            exec(compile(code, "<agent_analysis>", "exec"), globals_dict, {})
        queue.put({"ok": True, "stdout": stdout.getvalue(), "artifacts": saved_artifacts})
    except Exception:
        queue.put({"ok": False, "stdout": "", "error": traceback.format_exc(limit=5)})


def _validate_restricted_code(code: str) -> None:
    tree = ast.parse(code)
    banned_nodes = (ast.Import, ast.ImportFrom, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Lambda)
    banned_names = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars"}
    for node in ast.walk(tree):
        if isinstance(node, banned_nodes):
            raise ValueError(f"Unsupported code construct for restricted analysis: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id in banned_names:
            raise ValueError(f"Restricted analysis cannot use {node.id}.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("Restricted analysis cannot access dunder attributes.")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.replace("\\", "/")
            if value.startswith("/") or "../" in value or value == "..":
                raise ValueError("Restricted analysis cannot reference absolute paths or parent directories.")


def _safe_child(base: Path, child_name: str) -> Path:
    child = (base / child_name).resolve()
    base_resolved = base.resolve()
    if base_resolved != child and base_resolved not in child.parents:
        raise ValueError("Artifact path escapes the agent session directory.")
    return child


def _sort_value(value: object) -> tuple[int, object]:
    if value in (None, ""):
        return (0, "")
    try:
        return (1, float(value))
    except (TypeError, ValueError):
        return (1, str(value))
