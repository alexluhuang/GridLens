from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import xml.etree.ElementTree as ET

from gridlens.core.project import Project, ProjectData, safe_folder_name
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
        values,
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


def render_input_configuration_xml(values: InputConfigurationValues) -> str:
    normalized = normalize_input_configuration_values(values)
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

    ET.indent(root, space="  ")
    xml_text = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return f'<?xml version="1.0" encoding="utf-8"?>\n{xml_text}\n'


def save_input_configuration(
    project: Project,
    project_data: ProjectData,
    values: InputConfigurationValues,
) -> ProjectData:
    normalized = normalize_input_configuration_values(values)
    if normalized.monitor_branches_file:
        input_file_names = {record.file_name for record in project_data.input_files}
        if normalized.monitor_branches_file not in input_file_names:
            raise ValidationError("Monitor branches file must be added to the project input files.")
    xml_text = render_input_configuration_xml(normalized)
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


def _validate_int(value: str, label: str, minimum: int | None = None) -> str:
    text = _validate_text(value, label)
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValidationError(f"{label} must be an integer.") from exc
    if minimum is not None and parsed < minimum:
        raise ValidationError(f"{label} must be at least {minimum}.")
    return text


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
    "DEFAULT_PETSC_OPTIONS",
    "DEFAULT_XML_FILE_NAME",
    "INIT_START_OPTIONS",
    "InputConfigurationValues",
    "NETWORK_CONFIGURATION_TAG_OPTIONS",
    "default_input_configuration_values",
    "load_input_configuration_values",
    "normalize_input_configuration_values",
    "project_network_file_names",
    "render_input_configuration_xml",
    "save_input_configuration",
]
