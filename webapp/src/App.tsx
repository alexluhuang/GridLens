import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import AnalysisPlot from "./AnalysisPlot";
import {
  createInteractiveAnalysis,
  createProject,
  createRun,
  downloadRunExport,
  downloadRunOutput,
  fetchAuthMetadata,
  fetchCurrentUser,
  fetchHealth,
  fetchProjectConfiguration,
  fetchProject,
  fetchProjects,
  fetchRun,
  fetchRunLog,
  fetchRunOutputs,
  saveProjectConfiguration,
} from "./api";
import { beginSignIn, clearAuthSession, initializeAuthSession, isAuthEnabled, signOut } from "./auth";
import type {
  BranchOptions,
  CurrentUser,
  InputConfigurationValues,
  InteractiveAnalysis,
  OutputFileSummary,
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

const defaultConfigurationForm: InputConfigurationValues = {
  xml_file_name: "input.xml",
  network_file_name: "",
  network_configuration_tag: "networkConfiguration",
  full_branch_n1: true,
  full_generator_n1: false,
  contingency_rating: "C",
  enforce_reactive_power_limit: true,
  print_calc_files: false,
  group_size: "1",
  max_voltage: "1.1",
  min_voltage: "0.9",
  contingency_qlim_deadband: "0.1",
  contingency_ltc: false,
  write_stats: false,
  contingency_output_format: "csv_flat",
  contingency_output_file: "ca_results",
  contingency_list: "",
  monitor_branches_file: "",
  monitor_areas: "",
  monitor_kv_min: "0",
  monitor_kv_max: "0",
  init_start: "warm",
  switched_shunt: false,
  powerflow_qlim_deadband: "0.1",
  powerflow_ltc: false,
  area_interchange: false,
  max_controller_iterations: "10",
  max_iteration: "50",
  tolerance: "1.0e-4",
  max_qlim_iterations: "3",
  damping_factor: "1.0",
  phase_shift_sign: "1.0",
  petsc_prefix: "",
  petsc_options: "-ksp_type preonly\n-pc_type lu\n-pc_factor_mat_solver_type klu",
};

const themeStorageKey = "gridlens-theme";
const modeStorageKey = "gridlens-app-mode";
const graphVisibilityStorageKey = "gridlens-visible-graphs";
const voltageOrder = ["<50 kV", "50-99 kV", "100-229 kV", "230-344 kV", "345-499 kV", "500+ kV", "unknown"];
const graphDefinitions = [
  { key: "controlArea", label: "Control area averages" },
  { key: "voltageGroup", label: "Voltage group averages" },
  { key: "maxUtilization", label: "Maximum observed utilization" },
] as const;
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

type AppMode = "developer" | "viewer";
type GraphKey = (typeof graphDefinitions)[number]["key"];
type GraphVisibility = Record<GraphKey, boolean>;

const defaultGraphVisibility: GraphVisibility = {
  controlArea: true,
  voltageGroup: true,
  maxUtilization: true,
};

const maxHostedMpiProcesses = 18;

export default function App() {
  const [authEnabled, setAuthEnabled] = useState(isAuthEnabled());
  const [authReady, setAuthReady] = useState(false);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authError, setAuthError] = useState("");
  const [apiOffline, setApiOffline] = useState(false);
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
  const [appMode, setAppMode] = useState<AppMode>(readInitialMode);
  const [selectedControlAreas, setSelectedControlAreas] = useState<string[]>([]);
  const [selectedVoltageGroups, setSelectedVoltageGroups] = useState<string[]>([]);
  const [graphVisibility, setGraphVisibility] = useState<GraphVisibility>(readInitialGraphVisibility);
  const [configurationForm, setConfigurationForm] = useState<InputConfigurationValues>(defaultConfigurationForm);
  const [networkFileOptions, setNetworkFileOptions] = useState<string[]>([]);
  const [monitorBranchOptions, setMonitorBranchOptions] = useState<string[]>([]);
  const [configurationWarning, setConfigurationWarning] = useState("");
  const [xmlPreview, setXmlPreview] = useState("");
  const [runOutputs, setRunOutputs] = useState<OutputFileSummary[]>([]);

  const [projectName, setProjectName] = useState("");
  const [projectXmlFileName, setProjectXmlFileName] = useState("");
  const [projectInputFiles, setProjectInputFiles] = useState<File[]>([]);
  const [runForm, setRunForm] = useState(defaultRunForm);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(themeStorageKey, theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem(modeStorageKey, appMode);
  }, [appMode]);

  useEffect(() => {
    window.localStorage.setItem(graphVisibilityStorageKey, JSON.stringify(graphVisibility));
  }, [graphVisibility]);

  useEffect(() => {
    void bootstrapApp();
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

  const visibleGraphCount = Object.values(graphVisibility).filter(Boolean).length;
  const canStartRun = Boolean(selectedProject?.xml_file_name);

  async function bootstrapApp() {
    setLoading(true);
    setError("");
    setAuthError("");
    try {
      await fetchHealth();
      setApiOffline(false);
      const authMetadata = await fetchAuthMetadata();
      setAuthEnabled(authMetadata.enabled);
      if (authMetadata.enabled) {
        const signedInUser = await initializeAuthSession();
        if (!signedInUser) {
          setCurrentUser(null);
          setAuthReady(true);
          setMessage("Sign in to access your GridLens workspace.");
          setLoading(false);
          return;
        }
        try {
          const verifiedUser = await fetchCurrentUser();
          setCurrentUser(verifiedUser);
        } catch (nextError) {
          clearAuthSession();
          setCurrentUser(null);
          setAuthError(errorMessage(nextError));
          setAuthReady(true);
          setMessage("Sign in to access your GridLens workspace.");
          setLoading(false);
          return;
        }
      } else {
        setCurrentUser(null);
      }
      setAuthReady(true);
      await refreshProjects();
    } catch (nextError) {
      setApiOffline(true);
      setError(errorMessage(nextError));
      setMessage("The GridLens API is not running.");
      setAuthReady(true);
      setLoading(false);
    }
  }

  async function refreshProjects() {
    setLoading(true);
    setError("");
    try {
      const nextProjects = await fetchProjects();
      setApiOffline(false);
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
      setApiOffline(false);
      setSelectedProject(payload.project);
      setRuns(payload.runs);
      setRunForm((current) => ({
        ...current,
        xmlFileName: payload.project.xml_file_name,
      }));
      if (payload.runs[0]) {
        setSelectedRun((current) => (current?.run_id === payload.runs[0].run_id ? current : payload.runs[0]));
        void refreshRun(projectId, payload.runs[0].run_id, { includeLog: true });
      } else {
        setSelectedRun(null);
        setRunLog("");
        setAnalysis(null);
        setRunOutputs([]);
      }
      await refreshProjectConfiguration(projectId);
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
      setApiOffline(false);
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
      const outputs = await fetchRunOutputs(projectId, runId);
      setRunOutputs(outputs);
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  }

  async function refreshProjectConfiguration(projectId: string) {
    try {
      const payload = await fetchProjectConfiguration(projectId);
      setApiOffline(false);
      setConfigurationForm(payload.configuration);
      setNetworkFileOptions(payload.network_file_options);
      setMonitorBranchOptions(payload.monitor_branches_file_options);
      setConfigurationWarning(payload.warning);
      setXmlPreview(payload.xml_preview);
      setRunForm((current) => ({ ...current, xmlFileName: payload.configuration.xml_file_name }));
    } catch (nextError) {
      setConfigurationWarning("");
      setXmlPreview("");
      setNetworkFileOptions([]);
      setMonitorBranchOptions([]);
      setError(errorMessage(nextError));
    }
  }

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectInputFiles.length) {
      setError("Choose at least one project input file, such as a RAW network file.");
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
      setApiOffline(false);
      setProjectName("");
      setProjectXmlFileName("");
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
      setApiOffline(false);
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
      setApiOffline(false);
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

  async function handleSaveConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) {
      setError("Select a project before generating XML.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const payload = await saveProjectConfiguration({
        projectId: selectedProject.project_id,
        configuration: configurationForm,
      });
      setApiOffline(false);
      setSelectedProject(payload.project);
      setProjects((current) => current.map((item) => (item.project_id === payload.project.project_id ? payload.project : item)));
      setConfigurationForm(payload.configuration);
      setNetworkFileOptions(payload.network_file_options);
      setMonitorBranchOptions(payload.monitor_branches_file_options);
      setConfigurationWarning(payload.warning);
      setXmlPreview(payload.xml_preview);
      setRunForm((current) => ({ ...current, xmlFileName: payload.project.xml_file_name }));
      setMessage(`Saved XML configuration ${payload.project.xml_file_name}.`);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  function updateConfigurationField<K extends keyof InputConfigurationValues>(key: K, value: InputConfigurationValues[K]) {
    setConfigurationForm((current) => ({ ...current, [key]: value }));
  }

  if (!authReady) {
    return (
      <div className="app-shell outage-shell">
        <section className="outage-card">
          <div className="brand-lockup">
            <img src={`${import.meta.env.BASE_URL}gridlens.svg`} alt="GridLens logo" className="brand-logo" />
            <div>
              <h1>GridLens</h1>
              <p className="brand-subtitle">Checking API connectivity and authentication.</p>
            </div>
          </div>
        </section>
      </div>
    );
  }

  if (apiOffline) {
    return (
      <div className="app-shell outage-shell">
        <section className="outage-card">
          <div className="hero-topline">
            <p className="eyebrow">GridLens Status</p>
          </div>
          <div className="brand-lockup">
            <img src={`${import.meta.env.BASE_URL}gridlens.svg`} alt="GridLens logo" className="brand-logo" />
            <div>
              <h1>GridLens</h1>
              <p className="brand-subtitle">High Performance Power Grid Simulation and Contingency Analysis.</p>
            </div>
          </div>
          <div className="outage-panel">
            <span className="status-pill ready">API Offline</span>
            <h2>The API is not running.</h2>
            <p className="hero-copy">The GridLens web service is temporarily unavailable and will be back soon.</p>
            {error ? <p className="muted">{error}</p> : null}
            <div className="panel-actions">
              <button type="button" onClick={() => void bootstrapApp()}>
                Retry Connection
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  if (authEnabled && authReady && !currentUser) {
    return (
      <div className="app-shell outage-shell">
        <section className="outage-card">
          <div className="hero-topline">
            <p className="eyebrow">Secure Access</p>
          </div>
          <div className="brand-lockup">
            <img src={`${import.meta.env.BASE_URL}gridlens.svg`} alt="GridLens logo" className="brand-logo" />
            <div>
              <h1>GridLens</h1>
              <p className="brand-subtitle">Sign in with your email before viewing your private GridPACK runs and outputs.</p>
            </div>
          </div>
          <div className="outage-panel">
            <span className="status-pill ready">Authentication Required</span>
            <h2>Sign in to continue.</h2>
            <p className="hero-copy">
              This deployment uses Amazon Cognito for email-and-password authentication and keeps each user limited to
              their own projects, runs, and downloads.
            </p>
            {authError ? <p className="muted">{authError}</p> : null}
            <div className="panel-actions">
              <button type="button" onClick={() => void beginSignIn()}>
                Sign In With Email
              </button>
            </div>
          </div>
        </section>
      </div>
    );
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
            <p className="eyebrow"></p>
            <div className="hero-actions">
              <label className="mode-switch" aria-label="Developer mode toggle">
                <span className="mode-switch-label">Developer Mode</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={appMode === "developer"}
                  className={appMode === "developer" ? "mode-switch-track active" : "mode-switch-track"}
                  onClick={() => setAppMode((current) => (current === "developer" ? "viewer" : "developer"))}
                >
                  <span className="mode-switch-state">{appMode === "developer" ? "On" : "Off"}</span>
                  <span className="mode-switch-thumb" aria-hidden="true" />
                </button>
              </label>
              <button type="button" className="guide-button subtle-button" onClick={() => setGuideOpen(true)}>
                Open User Guide
              </button>
              {authEnabled && currentUser ? (
                <button type="button" className="subtle-button" onClick={() => signOut()}>
                  Sign Out
                </button>
              ) : null}
            </div>
          </div>
          <div className="brand-lockup">
            <img src={`${import.meta.env.BASE_URL}gridlens.svg`} alt="GridLens logo" className="brand-logo" />
            <div>
              <h1>GridLens</h1>
              <p className="brand-subtitle">High Performance Power Grid Simulation and Contingency Analysis.</p>
            </div>
          </div>
          <p className="hero-copy">
            Build projects from uploaded RAW inputs, generate GridPACK XML in the browser, launch runs on the API host,
            and download the outputs you need.
          </p>
          {authEnabled && currentUser ? <p className="hero-copy auth-summary">Signed in as {currentUser.email || currentUser.username}.</p> : null}
          <label className="mode-switch theme-switch" aria-label="Theme mode toggle">
            <span className="mode-switch-label">Dark Mode</span>
            <button
              type="button"
              role="switch"
              aria-checked={theme === "dark"}
              className={theme === "dark" ? "mode-switch-track active" : "mode-switch-track"}
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              <span className="mode-switch-state">{theme === "dark" ? "On" : "Off"}</span>
              <span className="mode-switch-thumb" aria-hidden="true" />
            </button>
          </label>
        </div>
        <div className="hero-status">
          <span className={`status-pill ${loading ? "busy" : "ready"}`}>{loading ? "Working" : "Ready"}</span>
          <p>{message}</p>
          {error ? <p className="error-text">{error}</p> : null}
          <div className="status-meta">
            {authEnabled && currentUser ? <span>{currentUser.email || currentUser.username}</span> : null}
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
              Existing XML file name
              <input
                value={projectXmlFileName}
                onChange={(event) => setProjectXmlFileName(event.target.value)}
                placeholder="Optional if you plan to generate XML in the web app"
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

        <section className="panel panel-wide">
          <div className="panel-header">
            <div>
              <h2>XML Configuration</h2>
              <p className="muted">
                {selectedProject
                  ? "Generate or update the GridPACK XML from the uploaded network inputs."
                  : "Select a project to configure its XML file."}
              </p>
            </div>
          </div>
          {selectedProject ? (
            <form className="stack" onSubmit={handleSaveConfiguration}>
              <div className="form-grid">
                <label>
                  Generated XML file
                  <input
                    value={configurationForm.xml_file_name}
                    onChange={(event) => updateConfigurationField("xml_file_name", event.target.value)}
                    required
                  />
                </label>
                <label>
                  Network file
                  <select
                    value={configurationForm.network_file_name}
                    onChange={(event) => updateConfigurationField("network_file_name", event.target.value)}
                    required
                  >
                    <option value="">Select a network file</option>
                    {networkFileOptions.map((fileName) => (
                      <option key={fileName} value={fileName}>
                        {fileName}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Network configuration tag
                  <select
                    value={configurationForm.network_configuration_tag}
                    onChange={(event) => updateConfigurationField("network_configuration_tag", event.target.value)}
                  >
                    {["networkConfiguration", "networkConfiguration_v33", "networkConfiguration_v34", "networkConfiguration_v35", "networkConfiguration_v36", "networkConfiguration_mat", "networkConfiguration_GOSS"].map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Output format
                  <select
                    value={configurationForm.contingency_output_format}
                    onChange={(event) => updateConfigurationField("contingency_output_format", event.target.value)}
                  >
                    {["csv_flat", "csv_delta", "text", "csv", "json"].map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Output file base name
                  <input
                    value={configurationForm.contingency_output_file}
                    onChange={(event) => updateConfigurationField("contingency_output_file", event.target.value)}
                    required
                  />
                </label>
                <label>
                  Contingency rating
                  <select
                    value={configurationForm.contingency_rating}
                    onChange={(event) => updateConfigurationField("contingency_rating", event.target.value)}
                  >
                    {["A", "B", "C"].map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="checkbox-grid compact-grid">
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.full_branch_n1}
                    onChange={(event) => updateConfigurationField("full_branch_n1", event.target.checked)}
                  />
                  Full branch N-1
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.full_generator_n1}
                    onChange={(event) => updateConfigurationField("full_generator_n1", event.target.checked)}
                  />
                  Full generator N-1
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.enforce_reactive_power_limit}
                    onChange={(event) => updateConfigurationField("enforce_reactive_power_limit", event.target.checked)}
                  />
                  Enforce reactive power limit
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.print_calc_files}
                    onChange={(event) => updateConfigurationField("print_calc_files", event.target.checked)}
                  />
                  Print calculation files
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.contingency_ltc}
                    onChange={(event) => updateConfigurationField("contingency_ltc", event.target.checked)}
                  />
                  Contingency LTC
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.write_stats}
                    onChange={(event) => updateConfigurationField("write_stats", event.target.checked)}
                  />
                  Write stats
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.switched_shunt}
                    onChange={(event) => updateConfigurationField("switched_shunt", event.target.checked)}
                  />
                  Switched shunt
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.powerflow_ltc}
                    onChange={(event) => updateConfigurationField("powerflow_ltc", event.target.checked)}
                  />
                  Powerflow LTC
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={configurationForm.area_interchange}
                    onChange={(event) => updateConfigurationField("area_interchange", event.target.checked)}
                  />
                  Area interchange
                </label>
              </div>

              <details className="advanced-section">
                <summary>Advanced XML settings</summary>
                <div className="form-grid advanced-grid">
                  <label>
                    Group size
                    <input value={configurationForm.group_size} onChange={(event) => updateConfigurationField("group_size", event.target.value)} />
                  </label>
                  <label>
                    Maximum voltage
                    <input value={configurationForm.max_voltage} onChange={(event) => updateConfigurationField("max_voltage", event.target.value)} />
                  </label>
                  <label>
                    Minimum voltage
                    <input value={configurationForm.min_voltage} onChange={(event) => updateConfigurationField("min_voltage", event.target.value)} />
                  </label>
                  <label>
                    Contingency q-limit deadband
                    <input value={configurationForm.contingency_qlim_deadband} onChange={(event) => updateConfigurationField("contingency_qlim_deadband", event.target.value)} />
                  </label>
                  <label>
                    Contingency list file
                    <input value={configurationForm.contingency_list} onChange={(event) => updateConfigurationField("contingency_list", event.target.value)} />
                  </label>
                  <label>
                    Monitor branches CSV
                    <select
                      value={configurationForm.monitor_branches_file}
                      onChange={(event) => updateConfigurationField("monitor_branches_file", event.target.value)}
                    >
                      <option value="">None</option>
                      {monitorBranchOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Monitor areas
                    <input value={configurationForm.monitor_areas} onChange={(event) => updateConfigurationField("monitor_areas", event.target.value)} />
                  </label>
                  <label>
                    Monitor kV minimum
                    <input value={configurationForm.monitor_kv_min} onChange={(event) => updateConfigurationField("monitor_kv_min", event.target.value)} />
                  </label>
                  <label>
                    Monitor kV maximum
                    <input value={configurationForm.monitor_kv_max} onChange={(event) => updateConfigurationField("monitor_kv_max", event.target.value)} />
                  </label>
                  <label>
                    Init start
                    <select value={configurationForm.init_start} onChange={(event) => updateConfigurationField("init_start", event.target.value)}>
                      {["warm", "flat"].map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Powerflow q-limit deadband
                    <input value={configurationForm.powerflow_qlim_deadband} onChange={(event) => updateConfigurationField("powerflow_qlim_deadband", event.target.value)} />
                  </label>
                  <label>
                    Maximum controller iterations
                    <input value={configurationForm.max_controller_iterations} onChange={(event) => updateConfigurationField("max_controller_iterations", event.target.value)} />
                  </label>
                  <label>
                    Maximum iterations
                    <input value={configurationForm.max_iteration} onChange={(event) => updateConfigurationField("max_iteration", event.target.value)} />
                  </label>
                  <label>
                    Tolerance
                    <input value={configurationForm.tolerance} onChange={(event) => updateConfigurationField("tolerance", event.target.value)} />
                  </label>
                  <label>
                    Maximum q-limit iterations
                    <input value={configurationForm.max_qlim_iterations} onChange={(event) => updateConfigurationField("max_qlim_iterations", event.target.value)} />
                  </label>
                  <label>
                    Damping factor
                    <input value={configurationForm.damping_factor} onChange={(event) => updateConfigurationField("damping_factor", event.target.value)} />
                  </label>
                  <label>
                    Phase shift sign
                    <input value={configurationForm.phase_shift_sign} onChange={(event) => updateConfigurationField("phase_shift_sign", event.target.value)} />
                  </label>
                  <label>
                    PETSc prefix
                    <input value={configurationForm.petsc_prefix} onChange={(event) => updateConfigurationField("petsc_prefix", event.target.value)} />
                  </label>
                  <label className="wide-field">
                    PETSc options
                    <textarea
                      rows={4}
                      value={configurationForm.petsc_options}
                      onChange={(event) => updateConfigurationField("petsc_options", event.target.value)}
                    />
                  </label>
                </div>
              </details>

              {configurationWarning ? <p className="muted">{configurationWarning}</p> : null}
              <div className="panel-actions">
                <button type="submit" disabled={!networkFileOptions.length}>
                  Generate XML
                </button>
              </div>
              <label>
                XML preview
                <pre className="xml-preview">{xmlPreview || "Choose a network file and save the configuration to generate XML."}</pre>
              </label>
            </form>
          ) : (
            <p className="muted">No project selected.</p>
          )}
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
                max={maxHostedMpiProcesses}
                value={runForm.mpiProcesses}
                onChange={(event) =>
                  setRunForm({
                    ...runForm,
                    mpiProcesses: clampMpiProcesses(Number(event.target.value)),
                  })
                }
                required
              />
            </label>
            <p className="hint-text">Runs launched from the web app are limited to {maxHostedMpiProcesses} MPI processes.</p>
            <label>
              Run notes
              <textarea
                rows={3}
                value={runForm.notes}
                onChange={(event) => setRunForm({ ...runForm, notes: event.target.value })}
                placeholder="Optional notes for the manifest."
              />
            </label>
            <button type="submit" disabled={!selectedProject || !canStartRun}>
              Start GridPACK Run
            </button>
            {!canStartRun ? <p className="muted">Generate or upload an XML file before starting a run.</p> : null}
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
          {appMode === "developer" ? (
            <div className="developer-controls">
              <div>
                <h3>Developer Mode</h3>
                <p className="muted">
                  Choose which graphs remain visible when the app is switched into viewer mode.
                </p>
              </div>
              <div className="checkbox-grid graph-visibility-grid">
                {graphDefinitions.map((graph) => (
                  <label key={graph.key}>
                    <input
                      type="checkbox"
                      checked={graphVisibility[graph.key]}
                      onChange={(event) =>
                        setGraphVisibility((current) => ({
                          ...current,
                          [graph.key]: event.target.checked,
                        }))
                      }
                    />
                    {graph.label}
                  </label>
                ))}
              </div>
            </div>
          ) : null}
          {visibleGraphCount === 0 ? (
            <p className="muted">No graphs are enabled. Switch to developer mode and check at least one graph to display it.</p>
          ) : null}
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
              graphVisibility={graphVisibility}
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
            <div className="empty-state-box">
              <h3>No analysis loaded yet</h3>
              <p className="muted">Generate charts for a completed run to view the linked graphs and selection table here.</p>
            </div>
          )}
          <RunDownloadsSection
            selectedProjectId={selectedProject?.project_id ?? ""}
            selectedRunId={selectedRun?.run_id ?? ""}
            runOutputs={runOutputs}
          />
        </section>
      </main>

      {guideOpen ? <GuideModal onClose={() => setGuideOpen(false)} /> : null}
    </div>
  );
}

type AnalysisViewProps = {
  analysis: InteractiveAnalysis;
  graphVisibility: GraphVisibility;
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
  graphVisibility,
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
  const showControlArea = graphVisibility.controlArea;
  const showVoltageGroup = graphVisibility.voltageGroup;
  const showMaxUtilization = graphVisibility.maxUtilization;
  const selectionTableRows = sortedDetailRows.slice(-25).reverse();

  return (
    <div className="analysis-grid">
      {showControlArea ? (
      <div className="chart-card">
        <div className="chart-card-header">
          <div>
            <h3>Average Line Utilization by Control Area</h3>
            <p className="muted">{controlAreaSubtitle}</p>
          </div>
          <div className="chart-card-actions">
            <button
              type="button"
              className="subtle-button"
              onClick={() =>
                downloadCsvFile(
                  `${analysis.project_name}-${analysis.run_id}-control-area-averages.csv`,
                  toCsv([
                    ["control_area", "average_utilization_pct", "line_count"],
                    ...controlAreaRows.map((row) => [row.control_area, row.average_utilization_pct.toFixed(3), String(row.line_count)]),
                  ]),
                )
              }
            >
              Download CSV
            </button>
            {selectedControlAreas.length ? (
              <button type="button" className="subtle-button" onClick={onClearControlAreas}>
                Clear Area Filters
              </button>
            ) : null}
          </div>
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
      ) : null}

      {showVoltageGroup ? (
      <div className="chart-card">
        <div className="chart-card-header">
          <div>
            <h3>Average N-1 Branch Loading by Voltage Group</h3>
            <p className="muted">{voltageSubtitle}</p>
          </div>
          <div className="chart-card-actions">
            <button
              type="button"
              className="subtle-button"
              onClick={() =>
                downloadCsvFile(
                  `${analysis.project_name}-${analysis.run_id}-voltage-group-averages.csv`,
                  toCsv([
                    ["voltage_group", "average_utilization_pct", "line_count"],
                    ...voltageGroupRows.map((row) => [row.voltage_group, row.average_utilization_pct.toFixed(3), String(row.line_count)]),
                  ]),
                )
              }
            >
              Download CSV
            </button>
            {selectedVoltageGroups.length ? (
              <button type="button" className="subtle-button" onClick={onClearVoltageGroups}>
                Clear Voltage Filters
              </button>
            ) : null}
          </div>
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
      ) : null}

      {showMaxUtilization ? (
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
          <div className="chart-card-actions">
            <button
              type="button"
              className="subtle-button"
              onClick={() =>
                downloadCsvFile(
                  `${analysis.project_name}-${analysis.run_id}-maximum-utilization.csv`,
                  toCsv([
                    ["line_label", "control_area", "voltage_group", "max_contingency", "max_utilization_pct", "utilization_pct"],
                    ...sortedDetailRows.map((row) => [
                      row.line_label,
                      row.control_area || "unknown",
                      row.voltage_group || "unknown",
                      row.max_contingency || "",
                      row.max_utilization_pct.toFixed(3),
                      row.utilization_pct.toFixed(3),
                    ]),
                  ]),
                )
              }
            >
              Download CSV
            </button>
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
      ) : null}

      <div className="table-card">
        <div className="table-card-header">
          <h3>Selection Details</h3>
          <div className="table-card-actions">
            <button
              type="button"
              className="subtle-button"
              onClick={() =>
                downloadCsvFile(
                  `${analysis.project_name}-${analysis.run_id}-selection-details.csv`,
                  toCsv([
                    ["line_label", "control_area", "voltage_group", "contingency", "max_utilization_pct"],
                    ...selectionTableRows.map((row) => [
                      row.line_label,
                      row.control_area || "-",
                      row.voltage_group || "-",
                      row.max_contingency || "-",
                      row.max_utilization_pct.toFixed(3),
                    ]),
                  ]),
                )
              }
            >
              Download CSV
            </button>
          </div>
        </div>
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
              {selectionTableRows.map((row) => (
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

function RunDownloadsSection({
  selectedProjectId,
  selectedRunId,
  runOutputs,
}: {
  selectedProjectId: string;
  selectedRunId: string;
  runOutputs: OutputFileSummary[];
}) {
  return (
    <div className="table-card">
      <div className="download-section-header">
        <div>
          <h3>Run Downloads</h3>
          <p className="muted">Export the full run package or download individual output files even if charts have not been generated yet.</p>
        </div>
        {selectedProjectId && selectedRunId ? (
          <button
            type="button"
            className="button-link"
            onClick={() => void downloadRunExport(selectedProjectId, selectedRunId)}
          >
            Export Run ZIP
          </button>
        ) : null}
      </div>
      <div className="download-section">
        {selectedProjectId && selectedRunId ? (
          runOutputs.length ? (
            <div className="download-grid">
              {runOutputs.map((file) => (
                <div key={file.relative_path} className="output-file-row">
                  <div>
                    <strong>{file.file_name}</strong>
                    <p className="muted">
                      {file.relative_path} • {formatBytes(file.size_bytes)}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="subtle-link"
                    onClick={() => void downloadRunOutput(selectedProjectId, selectedRunId, file.relative_path)}
                  >
                    Download
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No output files discovered for this run yet.</p>
          )
        ) : (
          <p className="muted">Select a run to enable the ZIP export and per-file downloads.</p>
        )}
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

function clampMpiProcesses(value: number) {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.min(maxHostedMpiProcesses, Math.max(1, Math.round(value)));
}

function toCsv(rows: string[][]) {
  return rows
    .map((row) =>
      row
        .map((value) => `"${String(value).replace(/"/g, "\"\"")}"`)
        .join(","),
    )
    .join("\n");
}

function downloadCsvFile(fileName: string, csvText: string) {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
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

function readInitialMode(): AppMode {
  if (typeof window === "undefined") {
    return "viewer";
  }
  return window.localStorage.getItem(modeStorageKey) === "developer" ? "developer" : "viewer";
}

function readInitialGraphVisibility(): GraphVisibility {
  if (typeof window === "undefined") {
    return defaultGraphVisibility;
  }
  try {
    const stored = window.localStorage.getItem(graphVisibilityStorageKey);
    if (!stored) {
      return defaultGraphVisibility;
    }
    const parsed = JSON.parse(stored) as Partial<GraphVisibility>;
    return {
      controlArea: parsed.controlArea ?? true,
      voltageGroup: parsed.voltageGroup ?? true,
      maxUtilization: parsed.maxUtilization ?? true,
    };
  } catch {
    return defaultGraphVisibility;
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  if (size < 1024 * 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
