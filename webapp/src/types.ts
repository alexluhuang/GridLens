export type ProjectSummary = {
  project_id: string;
  name: string;
  root_dir: string;
  xml_file_name: string;
  input_files: string[];
  run_count: number;
  created_at: string;
  updated_at: string;
  latest_run_id: string;
};

export type RunSummary = {
  project_id: string;
  project_name: string;
  run_id: string;
  run_dir: string;
  status: string;
  updated_at: string;
  return_code: number | null;
  error: string;
  manifest_file: string;
  log_file: string;
  work_dir: string;
  report_dir: string;
};

export type BranchOptions = {
  include_nontransformer_branches: boolean;
  include_two_winding_transformers: boolean;
  include_three_winding_transformers: boolean;
  include_transformer_equivalents: boolean;
};

export type UtilizationRow = {
  line_label: string;
  control_area?: string;
  voltage_group?: string;
  max_contingency?: string;
  max_utilization_pct: number;
  utilization_pct: number;
};

export type GroupRow = {
  line_count: number;
  average_utilization_pct: number;
  min_utilization_pct: number;
  max_utilization_pct: number;
  control_area?: string;
  voltage_group?: string;
};

export type InteractiveAnalysis = {
  project_id: string;
  project_name: string;
  run_id: string;
  generated_at: string;
  branch_options: BranchOptions;
  line_rows: UtilizationRow[];
  max_line_rows: UtilizationRow[];
  control_area_rows: GroupRow[];
  voltage_group_rows: GroupRow[];
  table_names: string[];
  report_dir: string;
  manifest_path: string;
};

