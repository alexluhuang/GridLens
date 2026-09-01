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

export type ThemeMode = "light" | "dark";

export type InputConfigurationValues = {
  xml_file_name: string;
  network_file_name: string;
  network_configuration_tag: string;
  full_branch_n1: boolean;
  full_generator_n1: boolean;
  contingency_rating: string;
  enforce_reactive_power_limit: boolean;
  print_calc_files: boolean;
  group_size: string;
  max_voltage: string;
  min_voltage: string;
  contingency_qlim_deadband: string;
  contingency_ltc: boolean;
  write_stats: boolean;
  contingency_output_format: string;
  contingency_output_file: string;
  contingency_list: string;
  monitor_branches_file: string;
  monitor_areas: string;
  monitor_kv_min: string;
  monitor_kv_max: string;
  init_start: string;
  switched_shunt: boolean;
  powerflow_qlim_deadband: string;
  powerflow_ltc: boolean;
  area_interchange: boolean;
  max_controller_iterations: string;
  max_iteration: string;
  tolerance: string;
  max_qlim_iterations: string;
  damping_factor: string;
  phase_shift_sign: string;
  petsc_prefix: string;
  petsc_options: string;
};

export type ProjectConfigurationResponse = {
  configuration: InputConfigurationValues;
  network_file_options: string[];
  monitor_branches_file_options: string[];
  xml_preview: string;
  warning: string;
};

export type OutputFileSummary = {
  file_name: string;
  relative_path: string;
  size_bytes: number;
  suffix: string;
};

export type UtilizationRow = {
  line_label: string;
  control_area?: string;
  control_areas?: string[];
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

export type VoltageGroupSummary = {
  voltage_group: string;
  average_utilization_pct: number;
  line_count: number;
};

export type AuthMetadata = {
  enabled: boolean;
  mode: string;
};

export type CurrentUser = {
  authenticated: boolean;
  subject: string;
  username: string;
  email: string;
};
