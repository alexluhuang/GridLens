import type { BranchOptions, InteractiveAnalysis, ProjectSummary, RunSummary } from "./types";

const configuredBaseUrl = (import.meta.env.VITE_GRIDLENS_API_BASE_URL || "").trim().replace(/\/$/, "");

function apiUrl(path: string): string {
  return configuredBaseUrl ? `${configuredBaseUrl}${path}` : path;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const payload = await parseResponse<{ projects: ProjectSummary[] }>(await fetch(apiUrl("/api/projects")));
  return payload.projects;
}

export async function fetchProject(projectId: string): Promise<{ project: ProjectSummary; runs: RunSummary[] }> {
  return parseResponse(await fetch(apiUrl(`/api/projects/${projectId}`)));
}

export async function createProject(data: {
  name: string;
  xmlFileName: string;
  inputFiles: File[];
}): Promise<ProjectSummary> {
  const formData = new FormData();
  formData.set("name", data.name);
  formData.set("xml_file_name", data.xmlFileName);
  for (const inputFile of data.inputFiles) {
    formData.append("input_files", inputFile);
  }
  const payload = await parseResponse<{ project: ProjectSummary }>(
    await fetch(apiUrl("/api/projects"), { method: "POST", body: formData }),
  );
  return payload.project;
}

export async function createRun(data: {
  projectId: string;
  image: string;
  executable: string;
  xmlFileName: string;
  mpiProcesses: number;
  notes: string;
}): Promise<RunSummary> {
  const formData = new FormData();
  formData.set("image", data.image);
  formData.set("executable", data.executable);
  formData.set("xml_file_name", data.xmlFileName);
  formData.set("mpi_processes", String(data.mpiProcesses));
  formData.set("notes", data.notes);
  const payload = await parseResponse<{ run: RunSummary }>(
    await fetch(apiUrl(`/api/projects/${data.projectId}/runs`), {
      method: "POST",
      body: formData,
    }),
  );
  return payload.run;
}

export async function fetchRun(projectId: string, runId: string): Promise<RunSummary> {
  const payload = await parseResponse<{ run: RunSummary }>(
    await fetch(apiUrl(`/api/projects/${projectId}/runs/${runId}`)),
  );
  return payload.run;
}

export async function fetchRunLog(projectId: string, runId: string): Promise<string> {
  const response = await fetch(apiUrl(`/api/projects/${projectId}/runs/${runId}/log`));
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to load log for ${runId}`);
  }
  return response.text();
}

export async function createInteractiveAnalysis(data: {
  projectId: string;
  runId: string;
  branchOptions: BranchOptions;
}): Promise<InteractiveAnalysis> {
  const formData = new FormData();
  formData.set(
    "include_nontransformer_branches",
    String(data.branchOptions.include_nontransformer_branches),
  );
  formData.set(
    "include_two_winding_transformers",
    String(data.branchOptions.include_two_winding_transformers),
  );
  formData.set(
    "include_three_winding_transformers",
    String(data.branchOptions.include_three_winding_transformers),
  );
  formData.set(
    "include_transformer_equivalents",
    String(data.branchOptions.include_transformer_equivalents),
  );
  const payload = await parseResponse<{ analysis: InteractiveAnalysis }>(
    await fetch(apiUrl(`/api/projects/${data.projectId}/runs/${data.runId}/analysis/interactive`), {
      method: "POST",
      body: formData,
    }),
  );
  return payload.analysis;
}

