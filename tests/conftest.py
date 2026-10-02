from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import shutil

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from gridlens.agent.library import index, vectors, worker
from gridlens.agent.policy import AgentError
from gridlens.agent.session import SessionContext
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.parser_models import PARSER_VERSION
from gridlens.core.project import Project
from gridlens.gui.configuration_view_models import (
    default_input_configuration_values,
    render_input_configuration_xml,
)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory, monkeypatch):
    """Point GridLens settings at a temporary projects folder, so no test writes to the user's projects."""
    config = tmp_path_factory.mktemp("config")
    projects = tmp_path_factory.mktemp("projects")
    (config / "gridlens").mkdir()
    (config / "gridlens" / "settings.json").write_text(json.dumps({"default_projects_dir": str(projects)}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    return projects


@pytest.fixture
def agent_project(tmp_path):
    root = tmp_path / "Synthetic_Project"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"name": "Synthetic Project"}))
    for run_id, offset in (("run_a", 0), ("run_b", 10)):
        run = root / "runs" / run_id
        work = run / "work"
        work.mkdir(parents=True)
        (run / "logs").mkdir()
        (run / "status.json").write_text('{"status": "completed"}')
        (run / "manifest.json").write_text(json.dumps({"run_id": run_id, "gridpack_image": "synthetic:test", "gridpack_executable": "ca.x", "mpi_processes": 4, "xml_file": "input.xml", "command": ["mpirun", "-n", "4", "ca.x", "input.xml"], "input_files": []}))
        (work / "input.xml").write_text("<Configuration><Contingency_analysis><FullBranchN1>true</FullBranchN1><minVoltage>0.9</minVoltage><maxVoltage>1.1</maxVoltage><contingencyRating>C</contingencyRating><qlim>true</qlim><qlimDeadband>0.1</qlimDeadband></Contingency_analysis><Powerflow><qlim>false</qlim><qlimDeadband>0.2</qlimDeadband></Powerflow></Configuration>")
        (work / "case.raw").write_text("Synthetic fixture only\n")
        (work / "case_flat.csv").write_text(
            "event_idx,contingency,from_bus,to_bus,circuit_id,section,rate_mva,loading_percent,viol\n"
            "0,base,1,2,1,,100,70,0\n"
            "1,line outage,1,2,1,,100,120,1\n"
            "2,island,1,2,1,2,100,90,0\n"
        )
        (work / "case_convergence.csv").write_text("event_idx,contingency,converged,status_code\n0,base,true,OK\n1,line outage,true,OK\n2,island,false,ISLANDED\n")
        rows = []
        for line_id, section, maximum, base, branch_type, kv in (
            ("1", "", 120, 70, "nontransformer_branch", 230),
            ("2", "", 80, 20, "nontransformer_branch", 230),
            ("1", "2", 110, 60, "nontransformer_branch", 230),
            ("T", "", 95, 60, "two_winding_transformer_branch", 115),
            ("L", "", 200, 90, "nontransformer_branch", 13.8),
        ):
            rows.append({"from_bus": 1, "to_bus": 2, "line_id": line_id, "section": section, "from_bus_name": "ALPHA", "to_bus_name": "BETA", "from_base_kv": kv, "to_base_kv": kv, "from_area": "1", "to_area": "2", "from_area_name": "North", "to_area_name": "South", "raw_branch_type": branch_type, "rate_mva": 100, "ratec": 100, "base_utilization_pct": base + offset, "mean_utilization_pct": 65, "max_utilization_pct": maximum + offset, "max_utilization_contingency": 1, "max_contingency_label": "line outage", "contingency_count": 3, "overload_count": int(maximum >= 100), "thermal_overload_count": int(maximum >= 100), "utilization_source": "csv_flat.loading_percent"})
        table_dir = run / "reports/interactive_tables"
        table_dir.mkdir(parents=True)
        tables = {"pflow_mm": rows, "branch_metadata": rows, "area_metadata": [{"area": 1, "area_name": "North"}, {"area": 2, "area_name": "South"}]}
        manifest = {"dataset_version": ANALYSIS_DATASET_VERSION, "parser_version": PARSER_VERSION, "tables": {}}
        for name, values in tables.items():
            path = table_dir / f"{name}.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(values[0]))
                writer.writeheader()
                writer.writerows(values)
            manifest["tables"][name] = {"source_file": "case.raw" if name == "area_metadata" else "case_flat.csv", "notes": [], "csv_path": str(path)}
        (run / "reports/interactive_analysis_manifest.json").write_text(json.dumps(manifest))
    return root


@pytest.fixture
def agent_context(agent_project):
    return SessionContext.create(agent_project, ("run_a", "run_b"), "fixture:model", "http://127.0.0.1:11434", projects_dir=agent_project.parent)


@pytest.fixture
def three_bus_project(tmp_path):
    """Save a project of the version 33 three-bus case and a GridLens XML."""
    raw = tmp_path / "three_bus_v33.raw"
    shutil.copy(Path(__file__).parent / "data" / raw.name, raw)
    xml = tmp_path / "input.xml"
    values = default_input_configuration_values(raw.name)
    xml.write_text(render_input_configuration_xml(values), encoding="utf-8")
    project = Project("Sensitivity Test", tmp_path / "project")
    return project, project.save([raw, xml], "input.xml")


# Two pages of a planning standard: lettered parts, requirements, and
# the sentences the document search tests look for.
REFERENCE_STANDARD = [
    [
        "B. Requirements and Measures",
        "R1. Each Planning Coordinator shall maintain System models.",
        "Rate B applies to the facility ratings after a contingency.",
    ],
    [
        "R2. Each Transmission Planner shall study P1 single contingency "
        "events.",
        "Steady state voltage limits apply to every bus.",
    ],
]


def _pdf(pages, *, title="", first_label=0):
    """Return a PDF whose pages hold these lines of text.

    title sets the PDF's own title, and first_label, when it is not 0,
    numbers the printed page labels from it.
    """
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    for lines in pages:
        page = writer.add_blank_page(612, 792)
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        shown = "".join(f"({line}) Tj T* " for line in lines)
        content = f"BT /F1 11 Tf 14 TL 72 720 Td {shown}ET"
        stream.set_data(content.encode("latin-1"))
        page.replace_contents(stream)
    if first_label:
        writer.set_page_label(0, len(pages) - 1, style="/D",
                              start=first_label)
    if title:
        writer.add_metadata({"/Title": title})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def make_pdf():
    """Return a function that builds a small PDF from lines of text."""
    return _pdf


@pytest.fixture
def reference_library(tmp_path) -> Path:
    """Return a Reference documents folder of synthetic documents.

    It holds a two-page standard with printed page labels from 5, a
    Markdown note in a subfolder, an HTML page, and two files the
    search cannot read: a PDF with no text and a Word document.
    """
    folder = tmp_path / "projects" / "Reference documents"
    folder.mkdir(parents=True)
    title = "TPL-001-5.1 Transmission System Planning Performance"
    standard = _pdf(REFERENCE_STANDARD, title=title, first_label=5)
    (folder / "TPL-001-5.1.pdf").write_bytes(standard)
    (folder / "criteria").mkdir()
    (folder / "criteria/planning_criteria.md").write_text(
        "# Planning criteria\n\n## Ratings\n\n"
        "Post-contingency flows are compared with Rate B.\n"
    )
    (folder / "guide.html").write_text(
        "<html><head><title>Operating guide</title>"
        "<script>var x = 'Rate B';</script></head><body>"
        "<h2>Voltage</h2><p>Buses stay within 0.95 to 1.05 pu.</p>"
        "</body></html>"
    )
    (folder / "scanned.pdf").write_bytes(_pdf([[]]))
    (folder / "notes.docx").write_bytes(b"PK")
    return folder


# The words whose counts make the stand-in embedding model's vectors.
EMBEDDED_TERMS = ("rate", "voltage", "contingency", "bus", "model")
EMBEDDING_MODEL = "embeddinggemma:latest"


@pytest.fixture(autouse=True)
def offline_ollama(monkeypatch):
    """Keep tests off any real Ollama: it answers only when faked."""
    def unavailable(endpoint, path, body=None, *, timeout=5):
        raise AgentError("OLLAMA_UNAVAILABLE", "Start Ollama.")

    monkeypatch.setattr(vectors, "ollama_json", unavailable)


@pytest.fixture(autouse=True)
def inline_indexer(monkeypatch):
    """Run the background indexer at once, in the test's own process.

    No test starts a real indexer process. Returns the (folder,
    endpoint) of each start; its original attribute is the real
    worker.start.
    """
    starts = _Starts()
    starts.original = worker.start

    def start(folder, endpoint=""):
        starts.append((folder, endpoint))
        worker.run(folder, endpoint)

    monkeypatch.setattr(worker, "start", start)
    return starts


class _Starts(list):
    """The indexer starts a test made, and the real start function."""


@pytest.fixture
def local_embeddings(monkeypatch):
    """Serve EMBEDDING_MODEL from a stand-in for the local Ollama.

    A text's vector counts the EMBEDDED_TERMS in it, plus a constant.
    Returns the list of every text embedded, in order; a test can set
    local_embeddings.width to change the vectors' width.
    """
    embedded = _Embedded()

    def answer(endpoint, path, body=None, *, timeout=5):
        if path == "/api/tags":
            names = ["gemma4:31b", EMBEDDING_MODEL]
            return {"models": [{"name": name} for name in names]}
        if path == "/api/show":
            return {"capabilities": ["embedding"]}
        assert path == "/api/embed"
        embedded.extend(body["input"])
        return {"embeddings": [embedded.vector(text)
                               for text in body["input"]]}

    monkeypatch.setattr(vectors, "ollama_json", answer)
    return embedded


class _Embedded(list):
    """The texts the stand-in model embedded, and its vectors' width."""

    width = len(EMBEDDED_TERMS) + 1

    def vector(self, text):
        """Return the stand-in embedding of a text."""
        words = index.tokens(text)
        counts = [float(words.count(term)) for term in EMBEDDED_TERMS]
        return (counts + [0.1] * self.width)[:self.width]
