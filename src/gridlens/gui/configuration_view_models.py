from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import xml.etree.ElementTree as ET

from gridlens.core.project import (
    MAX_CONFIGURATION_XML_BYTES,
    Project,
    ProjectData,
    is_gridpack_configuration_root,
    safe_folder_name,
)
from gridlens.core.validation import ValidationError


BOOLEAN_OPTIONS = ("True", "False")
CONTINGENCY_RATING_OPTIONS = ("A", "B", "C")
CONTINGENCY_OUTPUT_FORMAT_OPTIONS = ("csv_flat", "csv_delta", "text", "csv", "json")
INIT_START_OPTIONS = ("warm", "flat")
NETWORK_CONFIGURATION_TAG_OPTIONS = (
    "networkConfiguration",
    "networkConfiguration_v33",
    "networkConfiguration_v34",
    "networkConfiguration_v35",
    "networkConfiguration_v36",
    "networkConfiguration_mat",
    "networkConfiguration_GOSS",
)
# The GridLens solver's GPU settings, in Contingency_analysis/GPUBatch and Contingency_analysis/Execution.
GPU_ENABLED_OPTIONS = ("on", "auto")
GPU_ON_UNAVAILABLE_OPTIONS = ("fallback", "error")
GPU_BACKEND_OPTIONS = ("auto", "alg2", "cudss", "cpu_reference")
GPU_WARM_START_OPTIONS = ("base_case", "raw")
GPU_MEMORY_PROFILE_OPTIONS = ("auto", "unified", "coherent", "discrete")
GPU_FORMULATION_OPTIONS = ("superset",)
GPU_PLANNER_ORDERING_OPTIONS = ("amd", "colamd")
GPU_SOLVE_PLACEMENT_OPTIONS = ("gpu", "host")
GPU_TELEMETRY_OPTIONS = ("off", "summary", "detailed")
CPU_BINDING_OPTIONS = ("auto", "none", "performance_first")
LOG_LEVEL_OPTIONS = ("error", "warn", "info", "debug")
DEFAULT_XML_FILE_NAME = "input.xml"
DEFAULT_PETSC_OPTIONS = """-ksp_type preonly
-pc_type lu
-pc_factor_mat_solver_type klu"""


@dataclass(frozen=True, slots=True)
class InputConfigurationValues:
    xml_file_name: str = DEFAULT_XML_FILE_NAME
    network_file_name: str = ""
    network_configuration_tag: str = "networkConfiguration"
    full_branch_n1: bool = True
    full_generator_n1: bool = False
    contingency_rating: str = "C"
    enforce_reactive_power_limit: bool = True
    print_calc_files: bool = False
    group_size: str = "1"
    max_voltage: str = "1.1"
    min_voltage: str = "0.9"
    contingency_qlim_deadband: str = "0.1"
    contingency_ltc: bool = False
    write_stats: bool = False
    contingency_output_format: str = "csv_flat"
    contingency_output_file: str = "ca_results"
    contingency_list: str = ""
    monitor_branches_file: str = ""
    monitor_areas: str = ""
    monitor_kv_min: str = "0"
    monitor_kv_max: str = "0"
    init_start: str = "warm"
    switched_shunt: bool = False
    powerflow_qlim_deadband: str = "0.1"
    powerflow_ltc: bool = False
    area_interchange: bool = False
    max_controller_iterations: str = "10"
    max_iteration: str = "50"
    tolerance: str = "1.0e-4"
    max_qlim_iterations: str = "3"
    damping_factor: str = "1.0"
    phase_shift_sign: str = "1.0"
    petsc_prefix: str = ""
    petsc_options: str = DEFAULT_PETSC_OPTIONS
    use_gpu: bool = True
    gpu_enabled: str = "on"
    gpu_on_unavailable: str = "fallback"
    gpu_backend: str = "auto"
    gpu_batch_size: str = "auto"
    gpu_warm_start: str = "base_case"
    gpu_shadow_fraction: str = "0"
    gpu_plugin_path: str = ""
    gpu_device: str = "0"
    gpu_max_validated_batch: str = ""
    gpu_backfill: bool = True
    gpu_threads_per_block: str = "auto"
    gpu_memory_profile: str = "auto"
    gpu_memory_headroom_gb: str = ""
    gpu_max_memory_gb: str = "0"
    gpu_formulation: str = "superset"
    gpu_planner_ordering: str = "amd"
    gpu_pivot_tolerance: str = "0.001"
    gpu_solve_placement: str = "gpu"
    gpu_refinement_steps: str = "0"
    gpu_residual_limit: str = "1e-6"
    gpu_pivot_limit: str = "1e-12"
    gpu_check_non_finite: bool = True
    gpu_telemetry: str = "summary"
    gpu_profiler_ranges: bool = False
    accelerator_ranks: str = "auto"
    cpu_binding: str = "auto"
    log_level: str = "info"


def default_input_configuration_values(
    network_file_name: str = "",
    xml_file_name: str = DEFAULT_XML_FILE_NAME,
    project_name: str = "",
) -> InputConfigurationValues:
    output_file_name = safe_folder_name(project_name) if project_name.strip() else "ca_results"
    return InputConfigurationValues(
        network_file_name=network_file_name,
        xml_file_name=xml_file_name or DEFAULT_XML_FILE_NAME,
        contingency_output_file=output_file_name,
    )


def project_network_file_names(project_data: ProjectData) -> list[str]:
    return [
        record.file_name
        for record in project_data.input_files
        if Path(record.file_name).suffix.lower() in {".raw", ".m", ".goss"}
    ]


def attached_configuration(project_data: ProjectData) -> bool:
    """Return whether the project's configuration was added as an input file rather than generated here.

    A generated XML is recorded with its stored path as its source; an attached one keeps the path it was
    copied from, even after the Configuration tab edits it.
    """
    record = next((item for item in project_data.input_files if item.file_name == project_data.xml_file_name), None)
    return record is not None and Path(record.source_path) != Path(record.stored_path)


def load_input_configuration_values(
    xml_path: str | Path,
    network_file_name: str = "",
    xml_file_name: str = DEFAULT_XML_FILE_NAME,
    project_name: str = "",
) -> InputConfigurationValues:
    values = default_input_configuration_values(network_file_name, xml_file_name, project_name)
    root = ET.parse(xml_path).getroot()
    contingency = root.find("Contingency_analysis")
    powerflow = root.find("Powerflow")

    if contingency is not None:
        values = replace(
            values,
            full_branch_n1=_element_bool(contingency, "FullBranchN1", values.full_branch_n1),
            full_generator_n1=_element_bool(contingency, "FullGeneratorN1", values.full_generator_n1),
            contingency_rating=_element_text(contingency, "contingencyRating", values.contingency_rating),
            enforce_reactive_power_limit=_element_bool(
                contingency,
                "qlim",
                values.enforce_reactive_power_limit,
            ),
            print_calc_files=_element_bool(contingency, "printCalcFiles", values.print_calc_files),
            group_size=_element_text(contingency, "groupSize", values.group_size),
            max_voltage=_element_text(contingency, "maxVoltage", values.max_voltage),
            min_voltage=_element_text(contingency, "minVoltage", values.min_voltage),
            contingency_qlim_deadband=_element_text(
                contingency,
                "qlimDeadband",
                values.contingency_qlim_deadband,
            ),
            contingency_ltc=_element_bool(contingency, "LTC", values.contingency_ltc),
            write_stats=_element_bool(contingency, "writeStats", values.write_stats),
            contingency_output_format=_element_text(
                contingency,
                "outputFormat",
                values.contingency_output_format,
            ),
            contingency_output_file=_element_text(
                contingency,
                "outputFile",
                values.contingency_output_file,
            ),
            contingency_list=_element_text(contingency, "contingencyList", values.contingency_list),
            monitor_branches_file=_element_text(
                contingency,
                "monitorBranchesFile",
                values.monitor_branches_file,
            ),
            monitor_areas=_element_text(contingency, "monitorAreas", values.monitor_areas),
            monitor_kv_min=_element_text(contingency, "monitorKvMin", values.monitor_kv_min),
            monitor_kv_max=_element_text(contingency, "monitorKvMax", values.monitor_kv_max),
        )
        values = _load_gpu_values(contingency, values)

    if powerflow is not None:
        network_tag, network_name = _network_configuration(powerflow)
        values = replace(
            values,
            network_configuration_tag=network_tag or values.network_configuration_tag,
            network_file_name=network_name or values.network_file_name,
            init_start=_element_text(powerflow, "initStart", values.init_start),
            switched_shunt=_element_bool(powerflow, "SwitchedShunt", values.switched_shunt),
            enforce_reactive_power_limit=_element_bool(
                powerflow,
                "qlim",
                values.enforce_reactive_power_limit,
            ),
            powerflow_qlim_deadband=_element_text(
                powerflow,
                "qlimDeadband",
                values.powerflow_qlim_deadband,
            ),
            powerflow_ltc=_element_bool(powerflow, "LTC", values.powerflow_ltc),
            area_interchange=_element_bool(powerflow, "AreaInterchange", values.area_interchange),
            max_controller_iterations=_element_text(
                powerflow,
                "maxControllerIterations",
                values.max_controller_iterations,
            ),
            max_iteration=_element_text(powerflow, "maxIteration", values.max_iteration),
            tolerance=_element_text(powerflow, "tolerance", values.tolerance),
            max_qlim_iterations=_element_text(
                powerflow,
                "maxQlimIterations",
                values.max_qlim_iterations,
            ),
            damping_factor=_element_text(powerflow, "dampingFactor", values.damping_factor),
            phase_shift_sign=_element_text(powerflow, "phaseShiftSign", values.phase_shift_sign),
        )
        linear_solver = powerflow.find("LinearSolver")
        if linear_solver is not None:
            values = replace(
                values,
                petsc_prefix=_element_text(linear_solver, "PETScPrefix", values.petsc_prefix),
                petsc_options=_element_text(linear_solver, "PETScOptions", values.petsc_options),
            )

    return normalize_input_configuration_values(values)


def _load_gpu_values(contingency: ET.Element, values: InputConfigurationValues) -> InputConfigurationValues:
    """Read the GPU settings; a configuration without GPUBatch gets the defaults, as the solver does."""
    gpu = contingency.find("GPUBatch")
    if gpu is not None:
        enabled = _element_text(gpu, "enabled", values.gpu_enabled).lower()
        values = replace(
            values,
            use_gpu=enabled != "off",
            gpu_enabled=values.gpu_enabled if enabled == "off" else enabled,
            gpu_on_unavailable=_element_text(gpu, "onUnavailable", values.gpu_on_unavailable),
            gpu_backend=_element_text(gpu, "backend", values.gpu_backend),
            gpu_batch_size=_element_text(gpu, "batchSize", values.gpu_batch_size),
            gpu_warm_start=_element_text(gpu, "warmStart", values.gpu_warm_start),
            gpu_shadow_fraction=_element_text(gpu, "shadowFraction", values.gpu_shadow_fraction),
            gpu_plugin_path=_element_text(gpu, "pluginPath", values.gpu_plugin_path),
            gpu_device=_element_text(gpu, "device", values.gpu_device),
            gpu_max_validated_batch=_element_text(gpu, "maxValidatedBatch", values.gpu_max_validated_batch),
            gpu_backfill=_element_bool(gpu, "backfill", values.gpu_backfill),
            gpu_threads_per_block=_element_text(gpu, "threadsPerBlock", values.gpu_threads_per_block),
            gpu_memory_profile=_element_text(gpu, "memoryProfile", values.gpu_memory_profile),
            gpu_memory_headroom_gb=_element_text(gpu, "memoryHeadroomGB", values.gpu_memory_headroom_gb),
            gpu_max_memory_gb=_element_text(gpu, "maxMemoryGB", values.gpu_max_memory_gb),
            gpu_formulation=_element_text(gpu, "formulation", values.gpu_formulation),
            gpu_planner_ordering=_element_text(gpu, "plannerOrdering", values.gpu_planner_ordering),
            gpu_pivot_tolerance=_element_text(gpu, "pivotTolerance", values.gpu_pivot_tolerance),
            gpu_solve_placement=_element_text(gpu, "solvePlacement", values.gpu_solve_placement),
            gpu_refinement_steps=_element_text(gpu, "refinementSteps", values.gpu_refinement_steps),
            gpu_telemetry=_element_text(gpu, "telemetry", values.gpu_telemetry),
            gpu_profiler_ranges=_element_bool(gpu, "profilerRanges", values.gpu_profiler_ranges),
        )
        health = gpu.find("health")
        if health is not None:
            values = replace(
                values,
                gpu_residual_limit=_element_text(health, "residualLimit", values.gpu_residual_limit),
                gpu_pivot_limit=_element_text(health, "pivotLimit", values.gpu_pivot_limit),
                gpu_check_non_finite=_element_bool(health, "checkNonFinite", values.gpu_check_non_finite),
            )
    execution = contingency.find("Execution")
    if execution is not None:
        values = replace(
            values,
            accelerator_ranks=_element_text(execution, "acceleratorRanks", values.accelerator_ranks),
            cpu_binding=_element_text(execution, "cpuBinding", values.cpu_binding),
            log_level=_element_text(execution, "logLevel", values.log_level),
        )
    return values


def normalize_input_configuration_values(values: InputConfigurationValues) -> InputConfigurationValues:
    xml_file_name = _validate_file_name(values.xml_file_name, "Generated XML file")
    if Path(xml_file_name).suffix.lower() != ".xml":
        raise ValidationError("Generated XML file name must end with .xml.")

    network_file_name = _validate_file_name(values.network_file_name, "Network file")
    network_configuration_tag = _validate_option(
        values.network_configuration_tag,
        NETWORK_CONFIGURATION_TAG_OPTIONS,
        "Network configuration tag",
    )
    contingency_rating = _validate_option(
        values.contingency_rating,
        CONTINGENCY_RATING_OPTIONS,
        "Contingency rating",
    )
    contingency_output_format = _validate_option(
        values.contingency_output_format,
        CONTINGENCY_OUTPUT_FORMAT_OPTIONS,
        "Contingency output format",
    )
    init_start = _validate_option(values.init_start, INIT_START_OPTIONS, "Powerflow init start")

    return replace(
        _normalize_gpu_values(values),
        xml_file_name=xml_file_name,
        network_file_name=network_file_name,
        network_configuration_tag=network_configuration_tag,
        contingency_rating=contingency_rating,
        group_size=_validate_int(values.group_size, "Group size", minimum=1),
        max_voltage=_validate_float(values.max_voltage, "Maximum voltage"),
        min_voltage=_validate_float(values.min_voltage, "Minimum voltage"),
        contingency_qlim_deadband=_validate_float(
            values.contingency_qlim_deadband,
            "Contingency Q-limit deadband",
        ),
        contingency_output_format=contingency_output_format,
        contingency_output_file=_validate_text(values.contingency_output_file, "Output filename"),
        contingency_list=_validate_optional_text(values.contingency_list, "Contingency list file"),
        monitor_branches_file=_validate_optional_text(values.monitor_branches_file, "Monitor branches file"),
        monitor_areas=_validate_monitor_areas(values.monitor_areas),
        monitor_kv_min=_validate_nonnegative_float(values.monitor_kv_min, "Monitor kV minimum"),
        monitor_kv_max=_validate_nonnegative_float(values.monitor_kv_max, "Monitor kV maximum"),
        init_start=init_start,
        powerflow_qlim_deadband=_validate_float(
            values.powerflow_qlim_deadband,
            "Powerflow Q-limit deadband",
        ),
        max_controller_iterations=_validate_int(
            values.max_controller_iterations,
            "Maximum controller iterations",
            minimum=1,
        ),
        max_iteration=_validate_int(values.max_iteration, "Maximum iterations", minimum=1),
        tolerance=_validate_float(values.tolerance, "Tolerance"),
        max_qlim_iterations=_validate_int(values.max_qlim_iterations, "Maximum Q-limit iterations", minimum=1),
        damping_factor=_validate_float(values.damping_factor, "Damping factor"),
        phase_shift_sign=_validate_float(values.phase_shift_sign, "Phase shift sign"),
        petsc_prefix=_validate_optional_text(values.petsc_prefix, "PETSc prefix"),
        petsc_options=values.petsc_options.strip(),
    )


def _normalize_gpu_values(values: InputConfigurationValues) -> InputConfigurationValues:
    """Validate the GPU settings when the GPU is used; otherwise they are not written, so they are left alone."""
    if not values.use_gpu:
        return values
    return replace(
        values,
        gpu_enabled=_validate_option(values.gpu_enabled, GPU_ENABLED_OPTIONS, "GPU enabled"),
        gpu_on_unavailable=_validate_option(values.gpu_on_unavailable, GPU_ON_UNAVAILABLE_OPTIONS, "GPU unavailable"),
        gpu_backend=_validate_option(values.gpu_backend, GPU_BACKEND_OPTIONS, "GPU backend"),
        gpu_batch_size=_validate_auto_int(values.gpu_batch_size, "GPU batch size", 1, 65536),
        gpu_warm_start=_validate_option(values.gpu_warm_start, GPU_WARM_START_OPTIONS, "GPU warm start"),
        gpu_shadow_fraction=_validate_fraction(values.gpu_shadow_fraction, "GPU shadow fraction"),
        gpu_plugin_path=_validate_optional_text(values.gpu_plugin_path, "GPU plugin path"),
        gpu_device=_validate_int(values.gpu_device, "GPU device", minimum=0, maximum=1023),
        gpu_max_validated_batch=_validate_optional_int(
            values.gpu_max_validated_batch,
            "GPU maximum validated batch",
            1,
            65536,
        ),
        gpu_threads_per_block=_validate_threads_per_block(values.gpu_threads_per_block),
        gpu_memory_profile=_validate_option(values.gpu_memory_profile, GPU_MEMORY_PROFILE_OPTIONS, "GPU memory profile"),
        gpu_memory_headroom_gb=_validate_optional_nonnegative_float(
            values.gpu_memory_headroom_gb,
            "GPU memory headroom",
        ),
        gpu_max_memory_gb=_validate_nonnegative_float(values.gpu_max_memory_gb, "GPU maximum memory"),
        gpu_formulation=_validate_option(values.gpu_formulation, GPU_FORMULATION_OPTIONS, "GPU formulation"),
        gpu_planner_ordering=_validate_option(
            values.gpu_planner_ordering,
            GPU_PLANNER_ORDERING_OPTIONS,
            "GPU planner ordering",
        ),
        gpu_pivot_tolerance=_validate_fraction(values.gpu_pivot_tolerance, "GPU pivot tolerance"),
        gpu_solve_placement=_validate_option(
            values.gpu_solve_placement,
            GPU_SOLVE_PLACEMENT_OPTIONS,
            "GPU solve placement",
        ),
        gpu_refinement_steps=_validate_int(values.gpu_refinement_steps, "GPU refinement steps", minimum=0, maximum=100),
        gpu_residual_limit=_validate_fraction(values.gpu_residual_limit, "GPU residual limit"),
        gpu_pivot_limit=_validate_fraction(values.gpu_pivot_limit, "GPU pivot limit"),
        gpu_telemetry=_validate_option(values.gpu_telemetry, GPU_TELEMETRY_OPTIONS, "GPU telemetry"),
        accelerator_ranks=_validate_accelerator_ranks(values.accelerator_ranks),
        cpu_binding=_validate_option(values.cpu_binding, CPU_BINDING_OPTIONS, "CPU binding"),
        log_level=_validate_option(values.log_level, LOG_LEVEL_OPTIONS, "Log level"),
    )


def render_input_configuration_xml(values: InputConfigurationValues) -> str:
    return _xml_document(_configuration_tree(normalize_input_configuration_values(values)))


def merge_input_configuration_xml(existing_xml: str, values: InputConfigurationValues) -> str:
    """Write values into an existing GridPACK configuration, keeping everything GridLens does not manage.

    The elements the Configuration tab controls are updated in place, added where the tab would put them,
    or removed when the form leaves an optional one blank. Every other element, attribute, and comment
    stays, so a configuration attached in the Project tab keeps the settings the form has no field for. A
    file GridLens generated merges to exactly what render_input_configuration_xml writes.
    """
    normalized = normalize_input_configuration_values(values)
    try:
        existing = ET.fromstring(existing_xml, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except ET.ParseError as exc:
        raise ValidationError(f"{normalized.xml_file_name} could not be read as XML: {exc}") from exc
    if not is_gridpack_configuration_root(existing):
        raise ValidationError(
            f"{normalized.xml_file_name} in the project is not a GridPACK configuration. "
            "Choose another XML file name."
        )
    _merge_children(existing, _configuration_tree(normalized), _MANAGED_TAGS)
    return _xml_document(existing)


def _configuration_tree(normalized: InputConfigurationValues) -> ET.Element:
    root = ET.Element("Configuration")

    contingency = ET.SubElement(root, "Contingency_analysis")
    _add_text(contingency, "printCalcFiles", _bool_text(normalized.print_calc_files))
    if normalized.contingency_list:
        _add_text(contingency, "contingencyList", normalized.contingency_list)
    _add_text(contingency, "FullBranchN1", _bool_text(normalized.full_branch_n1))
    _add_text(contingency, "FullGeneratorN1", _bool_text(normalized.full_generator_n1))
    _add_text(contingency, "groupSize", normalized.group_size)
    _add_text(contingency, "maxVoltage", normalized.max_voltage)
    _add_text(contingency, "minVoltage", normalized.min_voltage)
    _add_text(contingency, "contingencyRating", normalized.contingency_rating)
    _add_text(contingency, "qlim", _bool_text(normalized.enforce_reactive_power_limit))
    _add_text(contingency, "qlimDeadband", normalized.contingency_qlim_deadband)
    _add_text(contingency, "LTC", _bool_text(normalized.contingency_ltc))
    _add_text(contingency, "writeStats", _bool_text(normalized.write_stats))
    _add_text(contingency, "outputFormat", normalized.contingency_output_format)
    _add_text(contingency, "outputFile", normalized.contingency_output_file)
    if normalized.monitor_branches_file:
        _add_text(contingency, "monitorBranchesFile", normalized.monitor_branches_file)
    if normalized.monitor_areas:
        _add_text(contingency, "monitorAreas", normalized.monitor_areas)
    if float(normalized.monitor_kv_min) > 0.0:
        _add_text(contingency, "monitorKvMin", normalized.monitor_kv_min)
    if float(normalized.monitor_kv_max) > 0.0:
        _add_text(contingency, "monitorKvMax", normalized.monitor_kv_max)
    _add_gpu_settings(contingency, normalized)

    powerflow = ET.SubElement(root, "Powerflow")
    _add_text(powerflow, normalized.network_configuration_tag, normalized.network_file_name)
    _add_text(powerflow, "initStart", normalized.init_start)
    _add_text(powerflow, "SwitchedShunt", _bool_text(normalized.switched_shunt))
    _add_text(powerflow, "qlim", _bool_text(normalized.enforce_reactive_power_limit))
    _add_text(powerflow, "qlimDeadband", normalized.powerflow_qlim_deadband)
    _add_text(powerflow, "LTC", _bool_text(normalized.powerflow_ltc))
    _add_text(powerflow, "AreaInterchange", _bool_text(normalized.area_interchange))
    _add_text(powerflow, "maxControllerIterations", normalized.max_controller_iterations)
    _add_text(powerflow, "maxIteration", normalized.max_iteration)
    _add_text(powerflow, "tolerance", normalized.tolerance)
    _add_text(powerflow, "maxQlimIterations", normalized.max_qlim_iterations)
    _add_text(powerflow, "dampingFactor", normalized.damping_factor)
    _add_text(powerflow, "phaseShiftSign", normalized.phase_shift_sign)
    linear_solver = ET.SubElement(powerflow, "LinearSolver")
    if normalized.petsc_prefix:
        _add_text(linear_solver, "PETScPrefix", normalized.petsc_prefix)
    petsc_options = ET.SubElement(linear_solver, "PETScOptions")
    petsc_options.text = _format_petsc_options(normalized.petsc_options)
    return root


def _add_gpu_settings(contingency: ET.Element, normalized: InputConfigurationValues) -> None:
    """Add GPUBatch and Execution; without the GPU, only GPUBatch's enabled, set to off, so the solver stays on the CPU."""
    gpu = ET.SubElement(contingency, "GPUBatch")
    if not normalized.use_gpu:
        _add_text(gpu, "enabled", "off")
        return
    _add_text(gpu, "enabled", normalized.gpu_enabled)
    _add_text(gpu, "onUnavailable", normalized.gpu_on_unavailable)
    _add_text(gpu, "backend", normalized.gpu_backend)
    _add_text(gpu, "batchSize", normalized.gpu_batch_size)
    _add_text(gpu, "warmStart", normalized.gpu_warm_start)
    _add_text(gpu, "shadowFraction", normalized.gpu_shadow_fraction)
    if normalized.gpu_plugin_path:
        _add_text(gpu, "pluginPath", normalized.gpu_plugin_path)
    _add_text(gpu, "device", normalized.gpu_device)
    if normalized.gpu_max_validated_batch:
        _add_text(gpu, "maxValidatedBatch", normalized.gpu_max_validated_batch)
    _add_text(gpu, "backfill", _bool_text(normalized.gpu_backfill))
    _add_text(gpu, "threadsPerBlock", normalized.gpu_threads_per_block)
    _add_text(gpu, "memoryProfile", normalized.gpu_memory_profile)
    if normalized.gpu_memory_headroom_gb:
        _add_text(gpu, "memoryHeadroomGB", normalized.gpu_memory_headroom_gb)
    _add_text(gpu, "maxMemoryGB", normalized.gpu_max_memory_gb)
    _add_text(gpu, "formulation", normalized.gpu_formulation)
    _add_text(gpu, "plannerOrdering", normalized.gpu_planner_ordering)
    _add_text(gpu, "pivotTolerance", normalized.gpu_pivot_tolerance)
    _add_text(gpu, "solvePlacement", normalized.gpu_solve_placement)
    _add_text(gpu, "refinementSteps", normalized.gpu_refinement_steps)
    health = ET.SubElement(gpu, "health")
    _add_text(health, "residualLimit", normalized.gpu_residual_limit)
    _add_text(health, "pivotLimit", normalized.gpu_pivot_limit)
    _add_text(health, "checkNonFinite", _bool_text(normalized.gpu_check_non_finite))
    _add_text(gpu, "telemetry", normalized.gpu_telemetry)
    _add_text(gpu, "profilerRanges", _bool_text(normalized.gpu_profiler_ranges))

    execution = ET.SubElement(contingency, "Execution")
    _add_text(execution, "acceleratorRanks", normalized.accelerator_ranks)
    _add_text(execution, "cpuBinding", normalized.cpu_binding)
    _add_text(execution, "logLevel", normalized.log_level)


def _xml_document(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    xml_text = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return f'<?xml version="1.0" encoding="utf-8"?>\n{xml_text}\n'


# The elements the Configuration tab writes, including those it writes only when a field is set, by parent.
_MANAGED_TAGS = {
    "Configuration": frozenset({"Contingency_analysis", "Powerflow"}),
    "Contingency_analysis": frozenset({
        "printCalcFiles", "contingencyList", "FullBranchN1", "FullGeneratorN1", "groupSize", "maxVoltage",
        "minVoltage", "contingencyRating", "qlim", "qlimDeadband", "LTC", "writeStats", "outputFormat",
        "outputFile", "monitorBranchesFile", "monitorAreas", "monitorKvMin", "monitorKvMax", "GPUBatch",
        "Execution",
    }),
    "GPUBatch": frozenset({
        "enabled", "onUnavailable", "backend", "batchSize", "warmStart", "shadowFraction", "pluginPath", "device",
        "maxValidatedBatch", "backfill", "threadsPerBlock", "memoryProfile", "memoryHeadroomGB", "maxMemoryGB",
        "formulation", "plannerOrdering", "pivotTolerance", "solvePlacement", "refinementSteps", "health",
        "telemetry", "profilerRanges",
    }),
    "health": frozenset({"residualLimit", "pivotLimit", "checkNonFinite"}),
    "Execution": frozenset({"acceleratorRanks", "cpuBinding", "logLevel"}),
    "Powerflow": frozenset({
        *NETWORK_CONFIGURATION_TAG_OPTIONS, "initStart", "SwitchedShunt", "qlim", "qlimDeadband", "LTC",
        "AreaInterchange", "maxControllerIterations", "maxIteration", "tolerance", "maxQlimIterations",
        "dampingFactor", "phaseShiftSign", "LinearSolver",
    }),
    "LinearSolver": frozenset({"PETScPrefix", "PETScOptions"}),
}


def _merge_children(existing: ET.Element, generated: ET.Element, managed: dict[str, frozenset[str]]) -> None:
    """Make existing's managed children match generated's, in generated's order, leaving other children alone.

    A generated child updates the first existing child with its tag, keeping that child's attributes, or is
    inserted after the previous managed child. Managed children the generated tree omits are removed, as
    are repeats of a managed tag, which GridPACK would read ambiguously.
    """
    tags = managed.get(existing.tag, frozenset())
    placed: set[int] = set()
    anchor: ET.Element | None = None
    for child in generated:
        match = next((item for item in existing if item.tag == child.tag), None)
        if match is None:
            match = ET.Element(child.tag)
            existing.insert(0 if anchor is None else list(existing).index(anchor) + 1, match)
        if child.tag in managed:
            _merge_children(match, child, managed)
        else:
            match.text = child.text
        placed.add(id(match))
        anchor = match
    for item in list(existing):
        if isinstance(item.tag, str) and item.tag in tags and id(item) not in placed:
            existing.remove(item)


def validated_input_configuration(
    project_data: ProjectData,
    values: InputConfigurationValues,
    existing_xml: str | None = None,
) -> tuple[InputConfigurationValues, str]:
    """Validate configuration values against the project; return them normalized, with the XML to save.

    existing_xml is the text of the file the XML will be saved to, when it exists. The values are then
    merged into it rather than replacing it, as merge_input_configuration_xml describes.
    """
    normalized = normalize_input_configuration_values(values)
    if normalized.monitor_branches_file:
        input_file_names = {record.file_name for record in project_data.input_files}
        if normalized.monitor_branches_file not in input_file_names:
            raise ValidationError("Monitor branches file must be added to the project input files.")
    if existing_xml is None:
        return normalized, render_input_configuration_xml(normalized)
    return normalized, merge_input_configuration_xml(existing_xml, normalized)


def existing_configuration_text(project: Project, xml_file_name: str) -> str | None:
    """Return the text of the project input a configuration named xml_file_name would be saved over, if any."""
    path = project.original_inputs_dir / xml_file_name.strip()
    if not xml_file_name.strip() or Path(xml_file_name.strip()).name != xml_file_name.strip() or not path.is_file():
        return None
    if path.stat().st_size > MAX_CONFIGURATION_XML_BYTES:
        raise ValidationError(f"{path.name} in the project is too large to be a GridPACK configuration.")
    return path.read_text(encoding="utf-8")


def save_input_configuration(
    project: Project,
    project_data: ProjectData,
    values: InputConfigurationValues,
) -> ProjectData:
    existing = existing_configuration_text(project, values.xml_file_name)
    normalized, xml_text = validated_input_configuration(project_data, values, existing)
    return project.save_generated_xml(project_data, normalized.xml_file_name, xml_text)


def _element_text(parent: ET.Element, tag: str, default: str) -> str:
    element = parent.find(tag)
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _element_bool(parent: ET.Element, tag: str, default: bool) -> bool:
    text = _element_text(parent, tag, "")
    if not text:
        return default
    return text.lower() == "true"


def _network_configuration(powerflow: ET.Element) -> tuple[str, str]:
    for tag in NETWORK_CONFIGURATION_TAG_OPTIONS:
        text = _element_text(powerflow, tag, "")
        if text:
            return tag, text
    return "", ""


def _validate_file_name(value: str, label: str) -> str:
    name = _validate_text(value, label)
    if Path(name).name != name or name in {".", ".."}:
        raise ValidationError(f"{label} must be a file name, not a path.")
    return name


def _validate_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise ValidationError(f"{label} is required.")
    if "\x00" in text:
        raise ValidationError(f"{label} contains an invalid character.")
    return text


def _validate_optional_text(value: str, label: str) -> str:
    text = value.strip()
    if "\x00" in text:
        raise ValidationError(f"{label} contains an invalid character.")
    return text


def _validate_option(value: str, options: tuple[str, ...], label: str) -> str:
    text = _validate_text(value, label)
    if text not in options:
        allowed = ", ".join(options)
        raise ValidationError(f"{label} must be one of: {allowed}.")
    return text


def _validate_int(value: str, label: str, minimum: int | None = None, maximum: int | None = None) -> str:
    text = _validate_text(value, label)
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValidationError(f"{label} must be an integer.") from exc
    if minimum is not None and parsed < minimum:
        raise ValidationError(f"{label} must be at least {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValidationError(f"{label} must be at most {maximum}.")
    return text


def _validate_optional_int(value: str, label: str, minimum: int, maximum: int) -> str:
    if not value.strip():
        return ""
    return _validate_int(value, label, minimum=minimum, maximum=maximum)


def _validate_auto_int(value: str, label: str, minimum: int, maximum: int) -> str:
    if value.strip().lower() == "auto":
        return "auto"
    try:
        return _validate_int(value, label, minimum=minimum, maximum=maximum)
    except ValidationError as exc:
        raise ValidationError(f"{label} must be auto or an integer from {minimum} to {maximum}.") from exc


def _validate_threads_per_block(value: str) -> str:
    text = _validate_auto_int(value, "GPU threads per block", 32, 1024)
    if text != "auto" and int(text) % 32:
        raise ValidationError("GPU threads per block must be auto or a multiple of 32 from 32 to 1024.")
    return text


def _validate_accelerator_ranks(value: str) -> str:
    text = _validate_text(value, "Accelerator ranks")
    if text.lower() == "auto":
        return "auto"
    ranks = [token.strip() for token in text.split(",")]
    if not all(token.isdigit() for token in ranks):
        raise ValidationError("Accelerator ranks must be auto or a comma-separated list of MPI ranks, such as 0,8.")
    return ",".join(ranks)


def _validate_float(value: str, label: str) -> str:
    text = _validate_text(value, label)
    try:
        float(text)
    except ValueError as exc:
        raise ValidationError(f"{label} must be numeric.") from exc
    return text


def _validate_nonnegative_float(value: str, label: str) -> str:
    text = _validate_float(value, label)
    if float(text) < 0.0:
        raise ValidationError(f"{label} must be zero or greater.")
    return text


def _validate_optional_nonnegative_float(value: str, label: str) -> str:
    if not value.strip():
        return ""
    return _validate_nonnegative_float(value, label)


def _validate_fraction(value: str, label: str) -> str:
    text = _validate_float(value, label)
    if not 0.0 <= float(text) <= 1.0:
        raise ValidationError(f"{label} must be from 0 to 1.")
    return text


def _validate_monitor_areas(value: str) -> str:
    text = _validate_optional_text(value, "Monitor areas")
    if not text:
        return ""
    for token in text.split():
        try:
            int(token)
        except ValueError as exc:
            raise ValidationError("Monitor areas must be space-separated area numbers.") from exc
    return text


def _add_text(parent: ET.Element, tag: str, text: str) -> None:
    ET.SubElement(parent, tag).text = text


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _format_petsc_options(options: str) -> str:
    stripped = options.strip()
    if not stripped:
        return ""
    lines = [line.rstrip() for line in stripped.splitlines()]
    return "\n" + "\n".join(f"        {line}" for line in lines) + "\n      "


__all__ = [
    "BOOLEAN_OPTIONS",
    "CONTINGENCY_OUTPUT_FORMAT_OPTIONS",
    "CONTINGENCY_RATING_OPTIONS",
    "CPU_BINDING_OPTIONS",
    "DEFAULT_PETSC_OPTIONS",
    "DEFAULT_XML_FILE_NAME",
    "GPU_BACKEND_OPTIONS",
    "GPU_ENABLED_OPTIONS",
    "GPU_FORMULATION_OPTIONS",
    "GPU_MEMORY_PROFILE_OPTIONS",
    "GPU_ON_UNAVAILABLE_OPTIONS",
    "GPU_PLANNER_ORDERING_OPTIONS",
    "GPU_SOLVE_PLACEMENT_OPTIONS",
    "GPU_TELEMETRY_OPTIONS",
    "GPU_WARM_START_OPTIONS",
    "INIT_START_OPTIONS",
    "LOG_LEVEL_OPTIONS",
    "InputConfigurationValues",
    "NETWORK_CONFIGURATION_TAG_OPTIONS",
    "attached_configuration",
    "default_input_configuration_values",
    "existing_configuration_text",
    "load_input_configuration_values",
    "merge_input_configuration_xml",
    "normalize_input_configuration_values",
    "project_network_file_names",
    "render_input_configuration_xml",
    "save_input_configuration",
]
