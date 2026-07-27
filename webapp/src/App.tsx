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
import type { BranchOptions, InteractiveAnalysis, ProjectSummary, RunSummary } from "./types";

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
  mpiProcesses: 4,
  notes: "",
};

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

  const [projectName, setProjectName] = useState("");
  const [projectXmlFileName, setProjectXmlFileName] = useState("");
  const [projectInputFiles, setProjectInputFiles] = useState<File[]>([]);
  const [runForm, setRunForm] = useState(defaultRunForm);

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

  async function refreshRun(
    projectId: string,
    runId: string,
    options: { includeLog: boolean },
  ) {
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
      setMessage(`Generated interactive analysis for ${selectedRun.run_id}.`);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">GridLens Web</p>
          <h1>Run GridPACK on EC2 and inspect the network in the browser.</h1>
          <p className="hero-copy">
            Upload project files, start contingency analysis jobs, poll run status, and keep interactive utilization
            plots in a web app.
          </p>
        </div>
        <div className="hero-status">
          <span className={`status-pill ${loading ? "busy" : "ready"}`}>{loading ? "Working" : "Ready"}</span>
          <p>{message}</p>
          {error ? <p className="error-text">{error}</p> : null}
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
              <p className="muted">Build browser charts from the cached interactive GridLens analysis tables.</p>
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
          {analysis ? <AnalysisView analysis={analysis} /> : <p className="muted">No analysis loaded yet.</p>}
        </section>
      </main>
    </div>
  );
}

function AnalysisView({ analysis }: { analysis: InteractiveAnalysis }) {
  const lineRows = analysis.line_rows.slice(0, 200);

  return (
    <div className="analysis-grid">
      <div className="chart-card">
        <h3>Line Utilization</h3>
        <AnalysisPlot
          data={[
            {
              type: "scatter",
              mode: "markers",
              x: lineRows.map((row) => row.line_label),
              y: lineRows.map((row) => row.max_utilization_pct),
              text: lineRows.map((row) => `${row.line_label}<br>${row.max_contingency || "no contingency label"}`),
              marker: {
                color: lineRows.map((row) => row.max_utilization_pct),
                colorscale: "YlOrRd",
                size: 10,
              },
            },
          ]}
          layout={{
            paper_bgcolor: "#f8f4ec",
            plot_bgcolor: "#f8f4ec",
            font: { family: "Georgia, serif", color: "#17211f" },
            margin: { t: 24, r: 24, b: 90, l: 60 },
            xaxis: { title: "Line label", tickangle: -35, automargin: true },
            yaxis: { title: "Max utilization (%)" },
          }}
          config={{ responsive: true, displaylogo: false }}
          style={{ width: "100%", height: "420px" }}
        />
      </div>

      <div className="chart-card">
        <h3>Average Utilization by Control Area</h3>
        <AnalysisPlot
          data={[
            {
              type: "bar",
              x: analysis.control_area_rows.map((row) => row.control_area || "unknown"),
              y: analysis.control_area_rows.map((row) => row.average_utilization_pct),
              marker: { color: "#d26a2e" },
            },
          ]}
          layout={{
            paper_bgcolor: "#f8f4ec",
            plot_bgcolor: "#f8f4ec",
            font: { family: "Georgia, serif", color: "#17211f" },
            margin: { t: 24, r: 24, b: 110, l: 60 },
            xaxis: { tickangle: -35, automargin: true },
            yaxis: { title: "Average utilization (%)" },
          }}
          config={{ responsive: true, displaylogo: false }}
          style={{ width: "100%", height: "360px" }}
        />
      </div>

      <div className="chart-card">
        <h3>Average Utilization by Voltage Group</h3>
        <AnalysisPlot
          data={[
            {
              type: "bar",
              x: analysis.voltage_group_rows.map((row) => row.voltage_group || "unknown"),
              y: analysis.voltage_group_rows.map((row) => row.average_utilization_pct),
              marker: { color: "#275d63" },
            },
          ]}
          layout={{
            paper_bgcolor: "#f8f4ec",
            plot_bgcolor: "#f8f4ec",
            font: { family: "Georgia, serif", color: "#17211f" },
            margin: { t: 24, r: 24, b: 60, l: 60 },
            xaxis: { automargin: true },
            yaxis: { title: "Average utilization (%)" },
          }}
          config={{ responsive: true, displaylogo: false }}
          style={{ width: "100%", height: "360px" }}
        />
      </div>

      <div className="table-card">
        <h3>Top Rows</h3>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Line</th>
                <th>Control area</th>
                <th>Voltage group</th>
                <th>Utilization %</th>
              </tr>
            </thead>
            <tbody>
              {analysis.line_rows.slice(-25).reverse().map((row) => (
                <tr key={`${row.line_label}-${row.max_contingency || ""}`}>
                  <td>{row.line_label}</td>
                  <td>{row.control_area || "-"}</td>
                  <td>{row.voltage_group || "-"}</td>
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

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}
