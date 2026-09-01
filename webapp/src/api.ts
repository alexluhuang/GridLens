import type {
  AuthMetadata,
  BranchOptions,
  CurrentUser,
  InputConfigurationValues,
  InteractiveAnalysis,
  OutputFileSummary,
  ProjectConfigurationResponse,
  ProjectSummary,
  RunSummary,
} from "./types";
import { getAccessToken } from "./auth";

const configuredBaseUrl = (import.meta.env.VITE_GRIDLENS_API_BASE_URL || "").trim().replace(/\/$/, "");

function apiUrl(path: string): string {
  if (!configuredBaseUrl) {
    return path;
  }
  if (configuredBaseUrl === "/api" && path.startsWith("/api/")) {
    return path;
  }
  return `${configuredBaseUrl}${path}`;
}

function healthUrl(): string {
  if (!configuredBaseUrl) {
    return "/health";
  }
  if (configuredBaseUrl === "/api") {
    return "/health";
  }
  if (configuredBaseUrl.endsWith("/api")) {
    return `${configuredBaseUrl.slice(0, -4)}/health`;
  }
  return `${configuredBaseUrl}/health`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function authenticatedFetch(input: string, init?: RequestInit): Promise<Response> {
  const token = getAccessToken();
  const headers = new Headers(init?.headers || {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}

export async function fetchHealth(): Promise<{ status: string }> {
  return parseResponse(await fetch(healthUrl()));
}

export async function fetchAuthMetadata(): Promise<AuthMetadata> {
  return parseResponse(await fetch(apiUrl("/api/auth")));
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  return parseResponse(await authenticatedFetch(apiUrl("/api/me")));
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const payload = await parseResponse<{ projects: ProjectSummary[] }>(await authenticatedFetch(apiUrl("/api/projects")));
  return payload.projects;
}

export async function fetchProject(projectId: string): Promise<{ project: ProjectSummary; runs: RunSummary[] }> {
  return parseResponse(await authenticatedFetch(apiUrl(`/api/projects/${projectId}`)));
}

export async function fetchProjectConfiguration(projectId: string): Promise<ProjectConfigurationResponse> {
  return parseResponse(await authenticatedFetch(apiUrl(`/api/projects/${projectId}/configuration`)));
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
    await authenticatedFetch(apiUrl("/api/projects"), { method: "POST", body: formData }),
  );
  return payload.project;
}

export async function saveProjectConfiguration(data: {
  projectId: string;
  configuration: InputConfigurationValues;
}): Promise<{ project: ProjectSummary } & ProjectConfigurationResponse> {
  return parseResponse(
    await authenticatedFetch(apiUrl(`/api/projects/${data.projectId}/configuration`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data.configuration),
    }),
  );
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
    await authenticatedFetch(apiUrl(`/api/projects/${data.projectId}/runs`), {
      method: "POST",
      body: formData,
    }),
  );
  return payload.run;
}

export async function fetchRun(projectId: string, runId: string): Promise<RunSummary> {
  const payload = await parseResponse<{ run: RunSummary }>(
    await authenticatedFetch(apiUrl(`/api/projects/${projectId}/runs/${runId}`)),
  );
  return payload.run;
}

export async function fetchRunLog(projectId: string, runId: string): Promise<string> {
  const response = await authenticatedFetch(apiUrl(`/api/projects/${projectId}/runs/${runId}/log`));
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to load log for ${runId}`);
  }
  return response.text();
}

export async function fetchRunOutputs(projectId: string, runId: string): Promise<OutputFileSummary[]> {
  const payload = await parseResponse<{ files: OutputFileSummary[] }>(
    await authenticatedFetch(apiUrl(`/api/projects/${projectId}/runs/${runId}/outputs`)),
  );
  return payload.files;
}

export function runOutputDownloadUrl(projectId: string, runId: string, relativePath: string): string {
  const encodedPath = relativePath
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return apiUrl(`/api/projects/${projectId}/runs/${runId}/outputs/download/${encodedPath}`);
}

export function runExportDownloadUrl(projectId: string, runId: string): string {
  return apiUrl(`/api/projects/${projectId}/runs/${runId}/export`);
}

export async function downloadRunOutput(projectId: string, runId: string, relativePath: string): Promise<void> {
  const response = await authenticatedFetch(runOutputDownloadUrl(projectId, runId, relativePath));
  await downloadResponseFile(response, fileNameFromPath(relativePath));
}

export async function downloadRunExport(projectId: string, runId: string): Promise<void> {
  const response = await authenticatedFetch(runExportDownloadUrl(projectId, runId));
  await downloadResponseFile(response, `${runId}.zip`);
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
    await authenticatedFetch(apiUrl(`/api/projects/${data.projectId}/runs/${data.runId}/analysis/interactive`), {
      method: "POST",
      body: formData,
    }),
  );
  return payload.analysis;
}

async function downloadResponseFile(response: Response, fallbackFileName: string): Promise<void> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Download failed with status ${response.status}`);
  }
  const blob = await response.blob();
  const header = response.headers.get("Content-Disposition") || "";
  const match = header.match(/filename="?([^"]+)"?/i);
  const fileName = match?.[1] || fallbackFileName;
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

function fileNameFromPath(relativePath: string): string {
  const parts = relativePath.split("/");
  return parts[parts.length - 1] || "download";
}
