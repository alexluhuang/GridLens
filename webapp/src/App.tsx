import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import AnalysisPlot from "./AnalysisPlot";
import {
  createInteractiveAnalysis,
  createProject,
  createRun,
  fetchProject,
  fetchProjects,
  fetchRun,
  fetchRunLog,
} from "./api";
import type {
  BranchOptions,
  InteractiveAnalysis,
  ProjectSummary,
  RunSummary,
  ThemeMode,
  UtilizationRow,
  VoltageGroupSummary,
} from "./types";

const defaultBranchOptions: BranchOptions = {
  include_nontransformer_branches: true,
  include_two_winding_transformers: false,
  include_three_winding_transformers: false,
  include_transformer_equivalents: false,
};

const defaultRunForm = {
  image: "pnnl/gridpack:latest",
  executable: "ca.x",
  xmlFileName: "",
  mpiProcesses: 2,
  notes: "",
};

const themeStorageKey = "gridlens-theme";
const voltageOrder = ["<50 kV", "50-99 kV", "100-229 kV", "230-344 kV", "345-499 kV", "500+ kV", "unknown"];
const guideSections = [
  {
    title: "Project setup",
    body: "Upload the XML and the network file together. The project card keeps those inputs linked so each run copies them into a fresh work folder on the API host.",
  },
  {
    title: "Run controls",
    body: "Start a GridPACK run, watch the log stream, and refresh the selected run. If a run fails, the log panel is the fastest place to spot missing files, MPI sizing issues, or GridPACK solver errors.",
  },
  {
    title: "Interactive analysis",
    body: "Generate charts after a completed run. Click control-area bars to filter the voltage-group chart. Click voltage bars to narrow the detailed maximum-utilization chart. Click again to clear a selection.",
  },
  {
    title: "Themes",
    body: "Use the light or dark toggle in the header to switch the full interface. The chosen theme stays saved in this browser.",
  },
];

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedProject, setSelectedProject] = useState<ProjectSummary | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunSummary | null>(null);
  const [runLog, setRunLog] = useState("");
  const [analysis, setAnalysis] = useState<InteractiveAnalysis | null>(null);
  const [branchOptions, setBranchOptions] = useState<BranchOptions>(defaultBranchOptions);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("Loading projects...");
  const [error, setError] = useState("");
  const [guideOpen, setGuideOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(readInitialTheme);
  const [selectedControlAreas, setSelectedControlAreas] = useState<string[]>([]);
  const [selectedVoltageGroups, setSelectedVoltageGroups] = useState<string[]>([]);

  const [projectName, setProjectName] = useState("");
  const [projectXmlFileName, setProjectXmlFileName] = useState("");
  const [projectInputFiles, setProjectInputFiles] = useState<File[]>([]);
  const [runForm, setRunForm] = useState(defaultRunForm);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(themeStorageKey, theme);
  }, [theme]);

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    void refreshProject(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedRun || !selectedProject) {
      return;
    }
    if (selectedRun.status !== "running") {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refreshRun(selectedProject.project_id, selectedRun.run_id, { includeLog: true });
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [selectedProject, selectedRun]);

  const controlAreaRows = analysis ? deriveControlAreaRows(analysis.line_rows) : [];
  const filteredLineRows = analysis ? filterLineRows(analysis.line_rows, selectedControlAreas, selectedVoltageGroups) : [];
  const voltageGroupRows = analysis
    ? deriveVoltageGroupRows(
        analysis.line_rows,
        selectedControlAreas.length ? selectedControlAreas : controlAreaRows.slice(0, 5).map((row) => row.control_area),
      )
    : [];

  const controlAreaSubtitle = selectedControlAreas.length
    ? `${selectedControlAreas.length} control areas selected`
    : "Click bars to filter related charts";
  const voltageSubtitle = selectedVoltageGroups.length
    ? `${selectedVoltageGroups.join(", ")} selected`
    : "Driven by the current control-area selection";

  async function refreshProjects() {
    setLoading(true);
    setError("");
    try {
      const nextProjects = await fetchProjects();
      setProjects(nextProjects);
      if (!selectedProjectId && nextProjects[0]) {
        setSelectedProjectId(nextProjects[0].project_id);
      }
      setMessage(nextProjects.length ? "Projects loaded." : "Create a project to start a GridPACK run.");
    } catch (nextError) {
      setError(errorMessage(nextError));
      setMessage("Could not load projects.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshProject(projectId: string) {
    setLoading(true);
    setError("");
    try {
      const payload = await fetchProject(projectId);
      setSelectedProject(payload.project);
      setRuns(payload.runs);
      setRunForm((current) => ({
        ...current,
        xmlFileName: current.xmlFileName || payload.project.xml_file_name,
      }));
      if (payload.runs[0]) {
        setSelectedRun((current) => (current?.run_id === payload.runs[0].run_id ? current : payload.runs[0]));
        void refreshRun(projectId, payload.runs[0].run_id, { includeLog: true });
      } else {
        setSelectedRun(null);
        setRunLog("");
        setAnalysis(null);
      }
      setMessage(`Loaded ${payload.project.name}.`);
    } catch (nextError) {
      setError(errorMessage(nextError));
      setMessage("Could not load the selected project.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshRun(projectId: string, runId: string, options: { includeLog: boolean }) {
    try {
      const run = await fetchRun(projectId, runId);
      setSelectedRun(run);
      setRuns((current) => current.map((item) => (item.run_id === run.run_id ? run : item)));
      if (options.includeLog) {
        const log = await fetchRunLog(projectId, runId);
        setRunLog(log);
      }
      if (run.status !== "completed") {
        setAnalysis(null);
        setSelectedControlAreas([]);
        setSelectedVoltageGroups([]);
      }
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  }

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectInputFiles.length) {
      setError("Choose at least the input.xml file and one network file.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const project = await createProject({
        name: projectName,
        xmlFileName: projectXmlFileName,
        inputFiles: projectInputFiles,
      });
      setProjectName("");
      setProjectXmlFileName(project.xml_file_name);
      setProjectInputFiles([]);
      setSelectedProjectId(project.project_id);
      await refreshProjects();
      await refreshProject(project.project_id);
      setMessage(`Created project ${project.name}.`);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) {
      setError("Select a project before starting a run.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const run = await createRun({
        projectId: selectedProject.project_id,
        image: runForm.image,
        executable: runForm.executable,
        xmlFileName: runForm.xmlFileName || selectedProject.xml_file_name,
        mpiProcesses: runForm.mpiProcesses,
        notes: runForm.notes,
      });
      setSelectedRun(run);
      setAnalysis(null);
      setSelectedControlAreas([]);
      setSelectedVoltageGroups([]);
      await refreshProject(selectedProject.project_id);
      await refreshRun(selectedProject.project_id, run.run_id, { includeLog: true });
      setMessage(`Started run ${run.run_id}.`);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  async function handleBuildAnalysis() {
    if (!selectedProject || !selectedRun) {
      setError("Choose a completed run before generating charts.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const nextAnalysis = await createInteractiveAnalysis({
        projectId: selectedProject.project_id,
        runId: selectedRun.run_id,
        branchOptions,
      });
      setAnalysis(nextAnalysis);
      setSelectedControlAreas([]);
      setSelectedVoltageGroups([]);
      setMessage(`Generated interactive analysis for ${selectedRun.run_id}.`);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  function toggleControlArea(area: string) {
    setSelectedVoltageGroups([]);
    setSelectedControlAreas((current) => (current.includes(area) ? current.filter((item) => item !== area) : [...current, area]));
  }

  function toggleVoltageGroup(group: string) {
    setSelectedVoltageGroups((current) => (current.includes(group) ? current.filter((item) => item !== group) : [...current, group]));
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div className="hero-copy-block">
          <div className="hero-topline">
            <p className="eyebrow">Operating Manual Style</p>
            <button type="button" className="guide-button subtle-button" onClick={() => setGuideOpen(true)}>
              Open User Guide
            </button>
          </div>
          <div className="brand-lockup">
            <img src="/gridlens.svg" alt="GridLens logo" className="brand-logo" />
            <div>
              <h1>GridLens</h1>
              <p className="brand-subtitle">GridPACK execution, results review, and interactive analysis.</p>
            </div>
          </div>
          <p className="hero-copy">
            Upload project files, launch EC2-backed GridPACK runs, and review linked utilization charts in a restrained
            black-and-white interface inspired by the NYCTA manual.
          </p>
          <div className="theme-toggle" role="tablist" aria-label="Theme mode selector">
            <button
              type="button"
              role="tab"
              aria-selected={theme === "light"}
              className={theme === "light" ? "theme-option active" : "theme-option"}
              onClick={() => setTheme("light")}
            >
              Light
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={theme === "dark"}
              className={theme === "dark" ? "theme-option active" : "theme-option"}
              onClick={() => setTheme("dark")}
            >
              Dark
            </button>
          </div>
        </div>
        <div className="hero-status">
          <span className={`status-pill ${loading ? "busy" : "ready"}`}>{loading ? "Working" : "Ready"}</span>
          <p>{message}</p>
          {error ? <p className="error-text">{error}</p> : null}
          <div className="status-meta">
            <span>{selectedProject ? selectedProject.name : "No project selected"}</span>
            <span>{selectedRun ? `${selectedRun.run_id} • ${selectedRun.status}` : "Pick a run to inspect analysis"}</span>
          </div>
        </div>
      </header>

      <main className="content-grid">
        <section className="panel">
          <h2>Create Project</h2>
          <form className="stack" onSubmit={handleCreateProject}>
            <label>
              Project name
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} required />
            </label>
            <label>
              XML file name
              <input
                value={projectXmlFileName}
                onChange={(event) => setProjectXmlFileName(event.target.value)}
                placeholder="input.xml"
                required
              />
            </label>
            <label>
              Input files
              <input
                type="file"
                multiple
                onChange={(event) => setProjectInputFiles(Array.from(event.target.files || []))}
                required
              />
            </label>
            <button type="submit">Upload Project Files</button>
          </form>
        </section>

        <section className="panel">
          <h2>Projects</h2>
          <div className="project-list">
            {projects.map((project) => (
              <button
                type="button"
                key={project.project_id}
                className={project.project_id === selectedProjectId ? "project-card active" : "project-card"}
                onClick={() => setSelectedProjectId(project.project_id)}
              >
                <strong>{project.name}</strong>
                <span>{project.run_count} runs</span>
                <span>{project.xml_file_name}</span>
              </button>
            ))}
            {!projects.length ? <p className="muted">No projects yet.</p> : null}
          </div>
        </section>

        <section className="panel">
          <h2>Start Run</h2>
          <form className="stack" onSubmit={handleCreateRun}>
            <label>
              GridPACK image
              <input
                value={runForm.image}
                onChange={(event) => setRunForm({ ...runForm, image: event.target.value })}
                required
              />
            </label>
            <label>
              Executable
              <input
                value={runForm.executable}
                onChange={(event) => setRunForm({ ...runForm, executable: event.target.value })}
                required
              />
            </label>
            <label>
              XML file
              <input
                value={runForm.xmlFileName}
                onChange={(event) => setRunForm({ ...runForm, xmlFileName: event.target.value })}
                placeholder={selectedProject?.xml_file_name || "input.xml"}
                required
              />
            </label>
            <label>
              MPI processes
              <input
                type="number"
                min={1}
                value={runForm.mpiProcesses}
                onChange={(event) => setRunForm({ ...runForm, mpiProcesses: Number(event.target.value) })}
                required
              />
            </label>
            <label>
              Run notes
              <textarea
                rows={3}
                value={runForm.notes}
                onChange={(event) => setRunForm({ ...runForm, notes: event.target.value })}
                placeholder="Optional notes for the manifest."
              />
            </label>
            <button type="submit" disabled={!selectedProject}>
              Start GridPACK Run
            </button>
          </form>
        </section>

        <section className="panel">
          <h2>Runs</h2>
          <div className="run-list">
            {runs.map((run) => (
              <button
                type="button"
                key={run.run_id}
                className={selectedRun?.run_id === run.run_id ? "run-card active" : "run-card"}
                onClick={() => {
                  setSelectedRun(run);
                  setAnalysis(null);
                  setSelectedControlAreas([]);
                  setSelectedVoltageGroups([]);
                  if (selectedProject) {
                    void refreshRun(selectedProject.project_id, run.run_id, { includeLog: true });
                  }
                }}
              >
                <strong>{run.run_id}</strong>
                <span>{run.status}</span>
                <span>{run.return_code === null ? "pending" : `code ${run.return_code}`}</span>
              </button>
            ))}
            {!runs.length ? <p className="muted">No runs yet for this project.</p> : null}
          </div>
        </section>

        <section className="panel panel-wide">
          <div className="panel-header">
            <div>
              <h2>Run Details</h2>
              <p className="muted">
                {selectedRun
                  ? `${selectedRun.run_id} • ${selectedRun.status} • ${selectedRun.report_dir}`
                  : "Select a run to inspect logs and generate charts."}
              </p>
            </div>
            <button
              type="button"
              className="subtle-button"
              onClick={() => {
                if (selectedProject && selectedRun) {
                  void refreshRun(selectedProject.project_id, selectedRun.run_id, { includeLog: true });
                }
              }}
              disabled={!selectedProject || !selectedRun}
            >
              Refresh Run
            </button>
          </div>
          <pre className="log-viewer">{runLog || "No log output yet."}</pre>
        </section>

        <section className="panel panel-wide">
          <div className="panel-header">
            <div>
              <h2>Interactive Analysis</h2>
              <p className="muted">Generate linked charts from the cached GridLens interactive analysis data.</p>
            </div>
            <button
              type="button"
              onClick={() => void handleBuildAnalysis()}
              disabled={!selectedRun || selectedRun.status !== "completed"}
            >
              Generate Charts
            </button>
          </div>
          <div className="checkbox-grid">
            <label>
              <input
                type="checkbox"
                checked={branchOptions.include_nontransformer_branches}
                onChange={(event) =>
                  setBranchOptions({
                    ...branchOptions,
                    include_nontransformer_branches: event.target.checked,
                  })
                }
              />
              Non-transformer branches
            </label>
            <label>
              <input
                type="checkbox"
                checked={branchOptions.include_two_winding_transformers}
                onChange={(event) =>
                  setBranchOptions({
                    ...branchOptions,
                    include_two_winding_transformers: event.target.checked,
                  })
                }
              />
              Two-winding transformers
            </label>
            <label>
              <input
                type="checkbox"
                checked={branchOptions.include_three_winding_transformers}
                onChange={(event) =>
                  setBranchOptions({
                    ...branchOptions,
                    include_three_winding_transformers: event.target.checked,
                  })
                }
              />
              Three-winding transformers
            </label>
            <label>
              <input
                type="checkbox"
                checked={branchOptions.include_transformer_equivalents}
                onChange={(event) =>
                  setBranchOptions({
                    ...branchOptions,
                    include_transformer_equivalents: event.target.checked,
                  })
                }
              />
              Transformer equivalents
            </label>
          </div>
          {analysis ? (
            <AnalysisView
              analysis={analysis}
              controlAreaRows={controlAreaRows}
              filteredLineRows={filteredLineRows}
              selectedControlAreas={selectedControlAreas}
              selectedVoltageGroups={selectedVoltageGroups}
              voltageGroupRows={voltageGroupRows}
              controlAreaSubtitle={controlAreaSubtitle}
              voltageSubtitle={voltageSubtitle}
              onControlAreaToggle={toggleControlArea}
              onVoltageGroupToggle={toggleVoltageGroup}
              onClearControlAreas={() => setSelectedControlAreas([])}
              onClearVoltageGroups={() => setSelectedVoltageGroups([])}
            />
          ) : (
            <p className="muted">No analysis loaded yet.</p>
          )}
        </section>
      </main>

      {guideOpen ? <GuideModal onClose={() => setGuideOpen(false)} /> : null}
    </div>
  );
}

type AnalysisViewProps = {
  analysis: InteractiveAnalysis;
  controlAreaRows: { control_area: string; average_utilization_pct: number; line_count: number }[];
  filteredLineRows: UtilizationRow[];
  selectedControlAreas: string[];
  selectedVoltageGroups: string[];
  voltageGroupRows: VoltageGroupSummary[];
  controlAreaSubtitle: string;
  voltageSubtitle: string;
  onControlAreaToggle: (area: string) => void;
  onVoltageGroupToggle: (group: string) => void;
  onClearControlAreas: () => void;
  onClearVoltageGroups: () => void;
};

function AnalysisView({
  analysis,
  controlAreaRows,
  filteredLineRows,
  selectedControlAreas,
  selectedVoltageGroups,
  voltageGroupRows,
  controlAreaSubtitle,
  voltageSubtitle,
  onControlAreaToggle,
  onVoltageGroupToggle,
  onClearControlAreas,
  onClearVoltageGroups,
}: AnalysisViewProps) {
  const detailRows = filteredLineRows.length ? filteredLineRows : analysis.line_rows;
  const sortedDetailRows = [...detailRows].sort((left, right) => left.max_utilization_pct - right.max_utilization_pct);
  const selectedAreaSet = new Set(selectedControlAreas);
  const selectedVoltageSet = new Set(selectedVoltageGroups);
  const controlAreaLeftMargin = controlAreaMargin(controlAreaRows.map((row) => row.control_area));

  return (
    <div className="analysis-grid">
      <div className="chart-card">
        <div className="chart-card-header">
          <div>
            <h3>Average Line Utilization by Control Area</h3>
            <p className="muted">{controlAreaSubtitle}</p>
          </div>
          {selectedControlAreas.length ? (
            <button type="button" className="subtle-button" onClick={onClearControlAreas}>
              Clear Area Filters
            </button>
          ) : null}
        </div>
        <AnalysisPlot
          data={[
            {
              type: "bar",
              orientation: "h",
              x: controlAreaRows.map((row) => row.average_utilization_pct),
              y: controlAreaRows.map((row) => row.control_area),
              customdata: controlAreaRows.map((row) => row.control_area),
              marker: {
                color: controlAreaRows.map((row) =>
                  selectedAreaSet.size === 0 || selectedAreaSet.has(row.control_area) ? "#ff8a1d" : "#92a4b8",
                ),
                line: {
                  color: controlAreaRows.map((row) => (selectedAreaSet.has(row.control_area) ? "#d66700" : "#6f879e")),
                  width: controlAreaRows.map((row) => (selectedAreaSet.has(row.control_area) ? 2 : 1)),
                },
              },
              hovertemplate: "%{customdata}<br>Average utilization: %{x:.2f}%<extra></extra>",
            },
          ]}
          layout={sharedLayout({
            title: "Average Line Utilization by Control Area",
            height: 520,
            margin: { t: 56, r: 24, b: 40, l: controlAreaLeftMargin },
            xaxis: { title: "Average utilization (%)" },
            yaxis: { automargin: true, autorange: "reversed", tickfont: { size: 14 } },
            shapes: [
              {
                type: "line",
                x0: 30,
                x1: 30,
                y0: -0.5,
                y1: controlAreaRows.length - 0.5,
                xref: "x",
                yref: "y",
                line: { color: "#d06d6d", dash: "dash" },
              },
            ],
            annotations: [
              {
                x: 30,
                y: controlAreaRows.length > 0 ? controlAreaRows.length - 1 : 0,
                xref: "x",
                yref: "y",
                text: "30% threshold",
                showarrow: false,
                bgcolor: "rgba(255,255,255,0.85)",
                bordercolor: "rgba(208,109,109,0.4)",
              },
            ],
          })}
          config={plotConfig()}
          style={{ width: "100%", height: "520px" }}
          onClick={(event: { points?: Array<{ customdata?: string }> }) => {
            const area = event.points?.[0]?.customdata;
            if (typeof area === "string") {
              onControlAreaToggle(area);
            }
          }}
        />
      </div>

      <div className="chart-card">
        <div className="chart-card-header">
          <div>
            <h3>Average N-1 Branch Loading by Voltage Group</h3>
            <p className="muted">{voltageSubtitle}</p>
          </div>
          {selectedVoltageGroups.length ? (
            <button type="button" className="subtle-button" onClick={onClearVoltageGroups}>
              Clear Voltage Filters
            </button>
          ) : null}
        </div>
        <AnalysisPlot
          data={[
            {
              type: "bar",
              x: voltageGroupRows.map((row) => row.voltage_group),
              y: voltageGroupRows.map((row) => row.average_utilization_pct),
              customdata: voltageGroupRows.map((row) => row.voltage_group),
              marker: {
                color: voltageGroupRows.map((row) =>
                  selectedVoltageSet.size === 0 || selectedVoltageSet.has(row.voltage_group) ? "#7ec8ff" : "#8797a8",
                ),
                line: {
                  color: voltageGroupRows.map((row) => (selectedVoltageSet.has(row.voltage_group) ? "#2f7db0" : "#6e7d8a")),
                  width: voltageGroupRows.map((row) => (selectedVoltageSet.has(row.voltage_group) ? 2 : 1)),
                },
              },
              text: voltageGroupRows.map((row) => row.average_utilization_pct.toFixed(1)),
              textposition: "outside",
              hovertemplate: "%{customdata}<br>Average utilization: %{y:.2f}%<extra></extra>",
            },
          ]}
          layout={sharedLayout({
            title: "Average N-1 Branch Loading by Voltage Group",
            height: 520,
            margin: { t: 56, r: 24, b: 70, l: 60 },
            xaxis: { title: "Voltage groups for selected control areas" },
            yaxis: { title: "Average loading (%)" },
          })}
          config={plotConfig()}
          style={{ width: "100%", height: "520px" }}
          onClick={(event: { points?: Array<{ customdata?: string }> }) => {
            const group = event.points?.[0]?.customdata;
            if (typeof group === "string") {
              onVoltageGroupToggle(group);
            }
          }}
        />
      </div>

      <div className="chart-card chart-card-wide">
        <div className="chart-card-header">
          <div>
            <h3>Maximum Observed Utilization</h3>
            <p className="muted">
              {sortedDetailRows.length} lines shown
              {selectedControlAreas.length ? ` • areas: ${selectedControlAreas.join(", ")}` : ""}
              {selectedVoltageGroups.length ? ` • voltage: ${selectedVoltageGroups.join(", ")}` : ""}
            </p>
          </div>
        </div>
        <AnalysisPlot
          data={[
            {
              type: "scatter",
              mode: "lines",
              x: sortedDetailRows.map((_, index) => index + 1),
              y: sortedDetailRows.map((row) => row.max_utilization_pct),
              fill: "tozeroy",
              name: "Utilization",
              line: { color: "#3e8ae0", width: 2.5 },
              fillcolor: "rgba(103, 177, 255, 0.18)",
              customdata: sortedDetailRows.map((row) => [
                row.line_label,
                row.max_contingency || "N/A",
                row.control_area || "unknown",
                row.voltage_group || "unknown",
              ]),
              hovertemplate:
                "%{customdata[0]}<br>Worst observed: %{y:.3f}%<br>Contingency: %{customdata[1]}<br>Control area: %{customdata[2]}<br>Voltage group: %{customdata[3]}<extra></extra>",
            },
          ]}
          layout={sharedLayout({
            title: "Maximum Observed Utilization",
            height: 480,
            margin: { t: 56, r: 24, b: 60, l: 80 },
            xaxis: { title: "Lines in selection, sorted lowest to highest" },
            yaxis: { title: "Max utilization across contingencies (%)" },
          })}
          config={plotConfig()}
          style={{ width: "100%", height: "480px" }}
        />
      </div>

      <div className="table-card">
        <h3>Selection Details</h3>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Line</th>
                <th>Control area</th>
                <th>Voltage group</th>
                <th>Contingency</th>
                <th>Utilization %</th>
              </tr>
            </thead>
            <tbody>
              {sortedDetailRows.slice(-25).reverse().map((row) => (
                <tr key={`${row.line_label}-${row.max_contingency || ""}`}>
                  <td>{row.line_label}</td>
                  <td>{row.control_area || "-"}</td>
                  <td>{row.voltage_group || "-"}</td>
                  <td>{row.max_contingency || "-"}</td>
                  <td>{row.max_utilization_pct.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function GuideModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="guide-modal" onClick={(event) => event.stopPropagation()}>
        <div className="guide-header">
          <div>
            <p className="eyebrow">User Guide</p>
            <h2>How to use the GridLens web app</h2>
          </div>
          <button type="button" className="subtle-button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="guide-grid">
          {guideSections.map((section) => (
            <article key={section.title} className="guide-card">
              <h3>{section.title}</h3>
              <p>{section.body}</p>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

function deriveControlAreaRows(rows: UtilizationRow[]) {
  const buckets = new Map<string, number[]>();
  for (const row of rows) {
    for (const area of row.control_areas?.length ? row.control_areas : [row.control_area || "unknown"]) {
      const bucket = buckets.get(area) || [];
      bucket.push(row.max_utilization_pct);
      buckets.set(area, bucket);
    }
  }
  return [...buckets.entries()]
    .map(([control_area, values]) => ({
      control_area,
      average_utilization_pct: average(values),
      line_count: values.length,
    }))
    .sort((left, right) => right.average_utilization_pct - left.average_utilization_pct);
}

function deriveVoltageGroupRows(rows: UtilizationRow[], selectedAreas: string[]): VoltageGroupSummary[] {
  const selectedSet = new Set(selectedAreas);
  const buckets = new Map<string, number[]>();
  for (const row of rows) {
    const areas = row.control_areas?.length ? row.control_areas : [row.control_area || "unknown"];
    if (selectedSet.size > 0 && !areas.some((area) => selectedSet.has(area))) {
      continue;
    }
    const group = row.voltage_group || "unknown";
    const bucket = buckets.get(group) || [];
    bucket.push(row.max_utilization_pct);
    buckets.set(group, bucket);
  }
  return voltageOrder
    .filter((group) => buckets.has(group))
    .map((voltage_group) => {
      const values = buckets.get(voltage_group) || [];
      return {
        voltage_group,
        average_utilization_pct: average(values),
        line_count: values.length,
      };
    });
}

function filterLineRows(rows: UtilizationRow[], selectedAreas: string[], selectedVoltageGroups: string[]) {
  const selectedAreaSet = new Set(selectedAreas);
  const selectedVoltageSet = new Set(selectedVoltageGroups);
  return rows.filter((row) => {
    const areas = row.control_areas?.length ? row.control_areas : [row.control_area || "unknown"];
    const areaMatch = selectedAreaSet.size === 0 || areas.some((area) => selectedAreaSet.has(area));
    const voltageMatch = selectedVoltageSet.size === 0 || selectedVoltageSet.has(row.voltage_group || "unknown");
    return areaMatch && voltageMatch;
  });
}

function average(values: number[]) {
  if (!values.length) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function controlAreaMargin(labels: string[]) {
  const longest = labels.reduce((max, label) => Math.max(max, label.length), 0);
  return Math.min(340, Math.max(210, 80 + longest * 10));
}

function sharedLayout(layout: Record<string, unknown>) {
  const theme = document.documentElement.dataset.theme || "light";
  const dark = theme === "dark";
  return {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {
      family: "\"Avenir Next\", \"Segoe UI\", \"Helvetica Neue\", Arial, sans-serif",
      color: dark ? "#e6eef8" : "#172033",
    },
    ...layout,
  };
}

function plotConfig() {
  return {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  };
}

function readInitialTheme(): ThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }
  const stored = window.localStorage.getItem(themeStorageKey);
  return stored === "dark" ? "dark" : "light";
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}
