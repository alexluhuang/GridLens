from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gridlens.core.project import Project, ProjectData
from gridlens.gui.configuration_view_models import (
    BOOLEAN_OPTIONS,
    CONTINGENCY_OUTPUT_FORMAT_OPTIONS,
    CONTINGENCY_RATING_OPTIONS,
    CPU_BINDING_OPTIONS,
    DEFAULT_XML_FILE_NAME,
    GPU_BACKEND_OPTIONS,
    GPU_ENABLED_OPTIONS,
    GPU_FORMULATION_OPTIONS,
    GPU_MEMORY_PROFILE_OPTIONS,
    GPU_ON_UNAVAILABLE_OPTIONS,
    GPU_PLANNER_ORDERING_OPTIONS,
    GPU_SOLVE_PLACEMENT_OPTIONS,
    GPU_TELEMETRY_OPTIONS,
    GPU_WARM_START_OPTIONS,
    INIT_START_OPTIONS,
    LOG_LEVEL_OPTIONS,
    NETWORK_CONFIGURATION_TAG_OPTIONS,
    InputConfigurationValues,
    attached_configuration,
    default_input_configuration_values,
    load_input_configuration_values,
    project_network_file_names,
    save_input_configuration,
)
from gridlens.gui.theme import configure_form_layout, set_button_role, set_context_label, set_muted_label


class ConfigurationTab(QWidget):
    project_changed = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.project_data: ProjectData | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.project_label = QLabel("No project loaded.")
        set_context_label(self.project_label)
        layout.addWidget(self.project_label)

        scroll = QScrollArea()
        scroll.setObjectName("contentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        basic_box = QGroupBox("Configuration")
        basic_form = QFormLayout(basic_box)
        configure_form_layout(basic_form)
        self.xml_file_name = QLineEdit(DEFAULT_XML_FILE_NAME)
        self.xml_file_name.setToolTip("Generated XML file name saved in the project's original inputs folder.")
        self.network_file = QComboBox()
        self.network_file.setToolTip("Network file copied into the project.")
        self.full_branch_n1 = QCheckBox("Full Branch N1")
        self.full_branch_n1.setToolTip("Include all branch N-1 contingencies.")
        self.full_generator_n1 = QCheckBox("Full Generator N1")
        self.full_generator_n1.setToolTip("Include all generator N-1 contingencies.")
        contingency_type_row = QHBoxLayout()
        contingency_type_row.setSpacing(12)
        contingency_type_row.addWidget(self.full_branch_n1)
        contingency_type_row.addWidget(self.full_generator_n1)
        contingency_type_row.addStretch()
        self.contingency_rating = _combo(CONTINGENCY_RATING_OPTIONS)
        self.enforce_reactive_power_limit = _combo(BOOLEAN_OPTIONS)
        self.use_gpu = QCheckBox("Run contingency cases on the GPU")
        basic_form.addRow("Generated XML file", self.xml_file_name)
        basic_form.addRow("Network file", self.network_file)
        basic_form.addRow("Contingency type", contingency_type_row)
        basic_form.addRow("Contingency rating", self.contingency_rating)
        basic_form.addRow("Enforce reactive power limit", self.enforce_reactive_power_limit)
        basic_form.addRow("GPU", self.use_gpu)

        self.advanced_box = QGroupBox("Advanced Configuration")
        self.advanced_box.setObjectName("sectionToggle")
        self.advanced_box.setToolTip("Expand only when GridPACK XML defaults need to be adjusted.")
        self.advanced_box.setCheckable(True)
        self.advanced_box.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced_box)
        self.advanced_fields = QWidget()
        advanced_fields_layout = QVBoxLayout(self.advanced_fields)
        advanced_fields_layout.setContentsMargins(0, 0, 0, 0)
        advanced_fields_layout.setSpacing(12)

        self.network_configuration_tag = _combo(NETWORK_CONFIGURATION_TAG_OPTIONS)
        self.print_calc_files = _combo(BOOLEAN_OPTIONS)
        self.group_size = QLineEdit()
        self.max_voltage = QLineEdit()
        self.min_voltage = QLineEdit()
        self.contingency_qlim_deadband = QLineEdit()
        self.contingency_ltc = _combo(BOOLEAN_OPTIONS)
        self.write_stats = _combo(BOOLEAN_OPTIONS)
        self.contingency_output_format = _combo(CONTINGENCY_OUTPUT_FORMAT_OPTIONS)
        self.contingency_output_file = QLineEdit()
        self.contingency_list = QLineEdit()
        self.contingency_list.setPlaceholderText("Optional contingency list XML file")
        self.monitor_branches_file = QComboBox()
        self.monitor_branches_file.setEditable(True)
        self.monitor_areas = QLineEdit()
        self.monitor_areas.setPlaceholderText("Optional space-separated area numbers")
        self.monitor_kv_min = QLineEdit()
        self.monitor_kv_max = QLineEdit()

        self.init_start = _combo(INIT_START_OPTIONS)
        self.switched_shunt = _combo(BOOLEAN_OPTIONS)
        self.powerflow_qlim_deadband = QLineEdit()
        self.powerflow_ltc = _combo(BOOLEAN_OPTIONS)
        self.area_interchange = _combo(BOOLEAN_OPTIONS)
        self.max_controller_iterations = QLineEdit()
        self.max_iteration = QLineEdit()
        self.tolerance = QLineEdit()
        self.max_qlim_iterations = QLineEdit()
        self.damping_factor = QLineEdit()
        self.phase_shift_sign = QLineEdit()
        self.petsc_prefix = QLineEdit()
        self.petsc_prefix.setPlaceholderText("Optional")
        self.petsc_options = QTextEdit()
        self.petsc_options.setAcceptRichText(False)
        self.petsc_options.setMinimumHeight(92)

        self.gpu_enabled = _combo(GPU_ENABLED_OPTIONS)
        self.gpu_on_unavailable = _combo(GPU_ON_UNAVAILABLE_OPTIONS)
        self.gpu_backend = _combo(GPU_BACKEND_OPTIONS)
        self.gpu_batch_size = QLineEdit()
        self.gpu_warm_start = _combo(GPU_WARM_START_OPTIONS)
        self.gpu_shadow_fraction = QLineEdit()
        self.gpu_plugin_path = QLineEdit()
        self.gpu_plugin_path.setPlaceholderText("Optional, next to ca.x by default")
        self.gpu_device = QLineEdit()
        self.gpu_max_validated_batch = QLineEdit()
        self.gpu_max_validated_batch.setPlaceholderText("Optional, 2048 by default")
        self.gpu_backfill = _combo(BOOLEAN_OPTIONS)
        self.gpu_threads_per_block = QLineEdit()
        self.gpu_memory_profile = _combo(GPU_MEMORY_PROFILE_OPTIONS)
        self.gpu_memory_headroom_gb = QLineEdit()
        self.gpu_memory_headroom_gb.setPlaceholderText("Optional, 10% of unified or 5% of discrete memory by default")
        self.gpu_max_memory_gb = QLineEdit()
        self.gpu_formulation = _combo(GPU_FORMULATION_OPTIONS)
        self.gpu_planner_ordering = _combo(GPU_PLANNER_ORDERING_OPTIONS)
        self.gpu_pivot_tolerance = QLineEdit()
        self.gpu_solve_placement = _combo(GPU_SOLVE_PLACEMENT_OPTIONS)
        self.gpu_refinement_steps = QLineEdit()
        self.gpu_residual_limit = QLineEdit()
        self.gpu_pivot_limit = QLineEdit()
        self.gpu_check_non_finite = _combo(BOOLEAN_OPTIONS)
        self.gpu_telemetry = _combo(GPU_TELEMETRY_OPTIONS)
        self.gpu_profiler_ranges = _combo(BOOLEAN_OPTIONS)
        self.accelerator_ranks = QLineEdit()
        self.cpu_binding = _combo(CPU_BINDING_OPTIONS)
        self.log_level = _combo(LOG_LEVEL_OPTIONS)

        contingency_box = QGroupBox("Contingency")
        contingency_form = QFormLayout(contingency_box)
        configure_form_layout(contingency_form)
        contingency_form.addRow("Print calculation files", self.print_calc_files)
        contingency_form.addRow("Group size", self.group_size)
        contingency_form.addRow("Maximum voltage", self.max_voltage)
        contingency_form.addRow("Minimum voltage", self.min_voltage)
        contingency_form.addRow("Q-limit deadband", self.contingency_qlim_deadband)
        contingency_form.addRow("LTC", self.contingency_ltc)
        contingency_form.addRow("Write stats", self.write_stats)
        contingency_form.addRow("Output format", self.contingency_output_format)
        contingency_form.addRow("Output filename", self.contingency_output_file)
        contingency_form.addRow("Contingency list", self.contingency_list)

        powerflow_box = QGroupBox("Powerflow")
        powerflow_form = QFormLayout(powerflow_box)
        configure_form_layout(powerflow_form)
        powerflow_form.addRow("Network configuration tag", self.network_configuration_tag)
        powerflow_form.addRow("Init start", self.init_start)
        powerflow_form.addRow("Switched shunt", self.switched_shunt)
        powerflow_form.addRow("Q-limit deadband", self.powerflow_qlim_deadband)
        powerflow_form.addRow("LTC", self.powerflow_ltc)
        powerflow_form.addRow("Area interchange", self.area_interchange)
        powerflow_form.addRow("Maximum controller iterations", self.max_controller_iterations)
        powerflow_form.addRow("Maximum iterations", self.max_iteration)
        powerflow_form.addRow("Tolerance", self.tolerance)
        powerflow_form.addRow("Maximum Q-limit iterations", self.max_qlim_iterations)
        powerflow_form.addRow("Damping factor", self.damping_factor)
        powerflow_form.addRow("Phase shift sign", self.phase_shift_sign)
        powerflow_form.addRow("PETSc prefix", self.petsc_prefix)
        powerflow_form.addRow("PETSc options", self.petsc_options)

        monitoring_box = QGroupBox("Monitoring")
        monitoring_form = QFormLayout(monitoring_box)
        configure_form_layout(monitoring_form)
        monitoring_form.addRow("Monitor branches file", self.monitor_branches_file)
        monitoring_form.addRow("Monitor areas", self.monitor_areas)
        monitoring_form.addRow("Monitor kV minimum", self.monitor_kv_min)
        monitoring_form.addRow("Monitor kV maximum", self.monitor_kv_max)

        # Shown only while the GPU is used; without it the XML turns the GPU off and holds none of these.
        self.gpu_box = QGroupBox("GPU Configuration")
        gpu_form = QFormLayout(self.gpu_box)
        configure_form_layout(gpu_form)
        gpu_form.addRow("Enabled", self.gpu_enabled)
        gpu_form.addRow("When no GPU is found", self.gpu_on_unavailable)
        gpu_form.addRow("Backend", self.gpu_backend)
        gpu_form.addRow("Batch size", self.gpu_batch_size)
        gpu_form.addRow("Warm start", self.gpu_warm_start)
        gpu_form.addRow("Shadow fraction", self.gpu_shadow_fraction)
        gpu_form.addRow("Plugin path", self.gpu_plugin_path)
        gpu_form.addRow("Device", self.gpu_device)
        gpu_form.addRow("Maximum validated batch", self.gpu_max_validated_batch)
        gpu_form.addRow("Backfill", self.gpu_backfill)
        gpu_form.addRow("Threads per block", self.gpu_threads_per_block)
        gpu_form.addRow("Memory profile", self.gpu_memory_profile)
        gpu_form.addRow("Memory headroom (GB)", self.gpu_memory_headroom_gb)
        gpu_form.addRow("Maximum memory (GB)", self.gpu_max_memory_gb)
        gpu_form.addRow("Formulation", self.gpu_formulation)
        gpu_form.addRow("Planner ordering", self.gpu_planner_ordering)
        gpu_form.addRow("Pivot tolerance", self.gpu_pivot_tolerance)
        gpu_form.addRow("Solve placement", self.gpu_solve_placement)
        gpu_form.addRow("Refinement steps", self.gpu_refinement_steps)
        gpu_form.addRow("Health: residual limit", self.gpu_residual_limit)
        gpu_form.addRow("Health: pivot limit", self.gpu_pivot_limit)
        gpu_form.addRow("Health: check non-finite", self.gpu_check_non_finite)
        gpu_form.addRow("Telemetry", self.gpu_telemetry)
        gpu_form.addRow("Profiler ranges", self.gpu_profiler_ranges)
        gpu_form.addRow("Accelerator ranks", self.accelerator_ranks)
        gpu_form.addRow("CPU binding", self.cpu_binding)
        gpu_form.addRow("Log level", self.log_level)
        self.use_gpu.toggled.connect(self.gpu_box.setVisible)

        advanced_fields_layout.addWidget(contingency_box)
        advanced_fields_layout.addWidget(powerflow_box)
        advanced_fields_layout.addWidget(monitoring_box)
        advanced_fields_layout.addWidget(self.gpu_box)

        advanced_layout.addWidget(self.advanced_fields)
        self.advanced_fields.setVisible(False)
        self.advanced_box.toggled.connect(self.advanced_fields.setVisible)

        scroll_layout.addWidget(basic_box)
        scroll_layout.addWidget(self.advanced_box)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        action_row = QHBoxLayout()
        self.save_button = QPushButton("Generate / Save XML")
        set_button_role(self.save_button, "primary")
        self.save_button.setToolTip("Write the XML configuration and update the project.")
        self.save_button.clicked.connect(self.save_configuration)
        self.save_button.setEnabled(False)
        action_row.addWidget(self.save_button)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.status = QLabel("Create or open a project before generating XML.")
        set_muted_label(self.status)
        layout.addWidget(self.status)

        self._load_values(default_input_configuration_values())
        self._set_field_hints()

    def _set_field_hints(self) -> None:
        self.contingency_rating.setToolTip("GridPACK contingency rating set used for branch loading checks.")
        self.enforce_reactive_power_limit.setToolTip("Whether generated XML enforces generator reactive power limits.")
        self.print_calc_files.setToolTip("Write additional calculation files during contingency analysis.")
        self.group_size.setToolTip("Optional GridPACK group size override.")
        self.max_voltage.setToolTip("Maximum voltage threshold for contingency calculations.")
        self.min_voltage.setToolTip("Minimum voltage threshold for contingency calculations.")
        self.contingency_qlim_deadband.setToolTip("Reactive power limit deadband for contingency solves.")
        self.contingency_ltc.setToolTip("Enable or disable load tap changer handling for contingency solves.")
        self.write_stats.setToolTip("Write GridPACK statistics output.")
        self.contingency_output_format.setToolTip("Output format written by the contingency analysis.")
        self.contingency_output_file.setToolTip("Base output filename used by GridPACK.")
        self.contingency_list.setToolTip("Optional XML file that narrows the contingency list.")
        self.network_configuration_tag.setToolTip("XML tag variant used to reference the network file.")
        self.init_start.setToolTip("Initial powerflow start mode.")
        self.switched_shunt.setToolTip("Enable or disable switched shunt handling.")
        self.powerflow_qlim_deadband.setToolTip("Reactive power limit deadband for powerflow solves.")
        self.powerflow_ltc.setToolTip("Enable or disable load tap changer handling for powerflow solves.")
        self.area_interchange.setToolTip("Enable or disable area interchange control.")
        self.max_controller_iterations.setToolTip("Maximum controller iterations.")
        self.max_iteration.setToolTip("Maximum powerflow iterations.")
        self.tolerance.setToolTip("Powerflow convergence tolerance.")
        self.max_qlim_iterations.setToolTip("Maximum reactive power limit iterations.")
        self.damping_factor.setToolTip("Powerflow damping factor.")
        self.phase_shift_sign.setToolTip("Phase-shift sign convention.")
        self.petsc_prefix.setToolTip("Optional PETSc prefix.")
        self.petsc_options.setToolTip("Optional PETSc options, one option per line or space-separated.")
        self.monitor_branches_file.setToolTip("Optional CSV file listing monitored branches.")
        self.monitor_areas.setToolTip("Optional space-separated area numbers to monitor.")
        self.monitor_kv_min.setToolTip("Optional minimum kV value for monitored facilities.")
        self.monitor_kv_max.setToolTip("Optional maximum kV value for monitored facilities.")
        self.use_gpu.setToolTip(
            "Give the run's container the GPUs and let the GridLens solver use them. "
            "Clear it on a machine without NVIDIA GPUs, or for an image without GPU support."
        )
        self.gpu_enabled.setToolTip("on: use the GPU. auto: use the GPU if one is found, else the CPU.")
        self.gpu_on_unavailable.setToolTip("fallback: run on the CPU when no GPU is found. error: stop the run.")
        self.gpu_backend.setToolTip("GPU solver. auto: the fastest at startup. cpu_reference: for testing.")
        self.gpu_batch_size.setToolTip("Contingency cases solved together: auto (chosen at startup) or 1-65536.")
        self.gpu_warm_start.setToolTip("Start each case from the base-case solution or from the network file.")
        self.gpu_shadow_fraction.setToolTip("Share of GPU cases, 0-1, re-solved on the CPU as a check.")
        self.gpu_plugin_path.setToolTip("Directory holding the GPU solver plugin. Blank: GRIDPACK_BATCHPF_PLUGIN_PATH, else next to ca.x.")
        self.gpu_device.setToolTip("GPU index, 0-1023.")
        self.gpu_max_validated_batch.setToolTip("Batch size cap, 1-65536. Blank: 2048, the tested limit.")
        self.gpu_backfill.setToolTip("Refill finished batch slots immediately.")
        self.gpu_threads_per_block.setToolTip("CUDA threads per block: auto, or 32-1024 in steps of 32.")
        self.gpu_memory_profile.setToolTip("GPU memory model. auto: detected.")
        self.gpu_memory_headroom_gb.setToolTip("GPU memory kept free, in GB. Blank: 10% of unified memory, else 5%.")
        self.gpu_max_memory_gb.setToolTip("GPU memory cap in GB. 0: no cap.")
        self.gpu_formulation.setToolTip("Batch formulation; superset is the only one.")
        self.gpu_planner_ordering.setToolTip("Factorization ordering.")
        self.gpu_pivot_tolerance.setToolTip("Pivoting threshold, 0-1, for the factorization ordering.")
        self.gpu_solve_placement.setToolTip("gpu: solve on the GPU. host: alg2 solves on the CPU, for testing.")
        self.gpu_refinement_steps.setToolTip("Extra accuracy passes, 0-100, for cudss.")
        self.gpu_residual_limit.setToolTip("Linear solve error limit, 0-1; a case over it goes to the CPU. 0: off.")
        self.gpu_pivot_limit.setToolTip("Near-zero pivot limit, 0-1; a case under it goes to the CPU.")
        self.gpu_check_non_finite.setToolTip("Send a case with NaN or infinite values to the CPU.")
        self.gpu_telemetry.setToolTip("GPU log detail.")
        self.gpu_profiler_ranges.setToolTip("Add NVTX markers for profilers.")
        self.accelerator_ranks.setToolTip("MPI ranks that drive a GPU: auto (one rank per GPU) or a list such as 0,8.")
        self.cpu_binding.setToolTip("How MPI ranks are bound to CPU cores. none: keep mpiexec's placement.")
        self.log_level.setToolTip("Solver log level.")

    def set_project(self, project: Project, project_data: ProjectData) -> None:
        self.project = project
        self.project_data = project_data
        network_names = project_network_file_names(project_data)
        selected_network = network_names[0] if network_names else ""
        xml_file_name = project_data.xml_file_name or DEFAULT_XML_FILE_NAME
        values = default_input_configuration_values(selected_network, xml_file_name, project_data.name)
        load_error = ""

        if project_data.xml_file_name:
            xml_path = project.original_inputs_dir / project_data.xml_file_name
            if xml_path.exists():
                try:
                    values = load_input_configuration_values(
                        xml_path,
                        selected_network,
                        xml_file_name,
                        project_data.name,
                    )
                except Exception as exc:
                    load_error = f"Loaded project, but existing XML could not be parsed: {exc}"

        if values.network_file_name and values.network_file_name not in network_names:
            network_names = [values.network_file_name, *network_names]
        self.network_file.clear()
        self.network_file.addItems(network_names or [""])
        self.monitor_branches_file.clear()
        self.monitor_branches_file.addItem("")
        self.monitor_branches_file.addItems(_project_csv_file_names(project_data))
        self._load_values(values)

        self.project_label.setText(f"Configuration: {project_data.name} ({project.root_dir})")
        self.save_button.setEnabled(bool(network_names))
        if load_error:
            self.status.setText(load_error)
        elif not network_names:
            self.status.setText("Add a network file to the project before generating XML.")
        else:
            self.status.setText(self._ready_message())

    def _ready_message(self) -> str:
        """Say which XML a save writes, and that an attached configuration is edited rather than replaced."""
        name = self.xml_file_name.text().strip() or DEFAULT_XML_FILE_NAME
        if self.project_data and self.project_data.xml_file_name == name and attached_configuration(self.project_data):
            return (
                f"Editing {name}, the configuration added in the Project tab. "
                "Saving keeps the settings GridLens does not manage."
            )
        return f"Ready to generate {name}."

    def save_configuration(self) -> None:
        if not self.project or not self.project_data:
            QMessageBox.warning(self, "No project", "Create or open a project first.")
            return

        try:
            project_data = save_input_configuration(self.project, self.project_data, self._form_values())
            self.project_data = project_data
            xml_path = self.project.original_inputs_dir / project_data.xml_file_name
            self.project_changed.emit(self.project, project_data)
            self.status.setText(f"Saved XML configuration: {xml_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Configuration cannot be saved", str(exc))

    def _load_values(self, values: InputConfigurationValues) -> None:
        self.xml_file_name.setText(values.xml_file_name)
        _set_combo(self.network_file, values.network_file_name)
        _set_combo(self.network_configuration_tag, values.network_configuration_tag)
        self.full_branch_n1.setChecked(values.full_branch_n1)
        self.full_generator_n1.setChecked(values.full_generator_n1)
        _set_combo(self.contingency_rating, values.contingency_rating)
        _set_bool_combo(self.enforce_reactive_power_limit, values.enforce_reactive_power_limit)
        _set_bool_combo(self.print_calc_files, values.print_calc_files)
        self.group_size.setText(values.group_size)
        self.max_voltage.setText(values.max_voltage)
        self.min_voltage.setText(values.min_voltage)
        self.contingency_qlim_deadband.setText(values.contingency_qlim_deadband)
        _set_bool_combo(self.contingency_ltc, values.contingency_ltc)
        _set_bool_combo(self.write_stats, values.write_stats)
        _set_combo(self.contingency_output_format, values.contingency_output_format)
        self.contingency_output_file.setText(values.contingency_output_file)
        self.contingency_list.setText(values.contingency_list)
        _set_combo(self.monitor_branches_file, values.monitor_branches_file)
        self.monitor_areas.setText(values.monitor_areas)
        self.monitor_kv_min.setText(values.monitor_kv_min)
        self.monitor_kv_max.setText(values.monitor_kv_max)
        _set_combo(self.init_start, values.init_start)
        _set_bool_combo(self.switched_shunt, values.switched_shunt)
        self.powerflow_qlim_deadband.setText(values.powerflow_qlim_deadband)
        _set_bool_combo(self.powerflow_ltc, values.powerflow_ltc)
        _set_bool_combo(self.area_interchange, values.area_interchange)
        self.max_controller_iterations.setText(values.max_controller_iterations)
        self.max_iteration.setText(values.max_iteration)
        self.tolerance.setText(values.tolerance)
        self.max_qlim_iterations.setText(values.max_qlim_iterations)
        self.damping_factor.setText(values.damping_factor)
        self.phase_shift_sign.setText(values.phase_shift_sign)
        self.petsc_prefix.setText(values.petsc_prefix)
        self.petsc_options.setPlainText(values.petsc_options)
        self.use_gpu.setChecked(values.use_gpu)
        self.gpu_box.setVisible(values.use_gpu)
        _set_combo(self.gpu_enabled, values.gpu_enabled)
        _set_combo(self.gpu_on_unavailable, values.gpu_on_unavailable)
        _set_combo(self.gpu_backend, values.gpu_backend)
        self.gpu_batch_size.setText(values.gpu_batch_size)
        _set_combo(self.gpu_warm_start, values.gpu_warm_start)
        self.gpu_shadow_fraction.setText(values.gpu_shadow_fraction)
        self.gpu_plugin_path.setText(values.gpu_plugin_path)
        self.gpu_device.setText(values.gpu_device)
        self.gpu_max_validated_batch.setText(values.gpu_max_validated_batch)
        _set_bool_combo(self.gpu_backfill, values.gpu_backfill)
        self.gpu_threads_per_block.setText(values.gpu_threads_per_block)
        _set_combo(self.gpu_memory_profile, values.gpu_memory_profile)
        self.gpu_memory_headroom_gb.setText(values.gpu_memory_headroom_gb)
        self.gpu_max_memory_gb.setText(values.gpu_max_memory_gb)
        _set_combo(self.gpu_formulation, values.gpu_formulation)
        _set_combo(self.gpu_planner_ordering, values.gpu_planner_ordering)
        self.gpu_pivot_tolerance.setText(values.gpu_pivot_tolerance)
        _set_combo(self.gpu_solve_placement, values.gpu_solve_placement)
        self.gpu_refinement_steps.setText(values.gpu_refinement_steps)
        self.gpu_residual_limit.setText(values.gpu_residual_limit)
        self.gpu_pivot_limit.setText(values.gpu_pivot_limit)
        _set_bool_combo(self.gpu_check_non_finite, values.gpu_check_non_finite)
        _set_combo(self.gpu_telemetry, values.gpu_telemetry)
        _set_bool_combo(self.gpu_profiler_ranges, values.gpu_profiler_ranges)
        self.accelerator_ranks.setText(values.accelerator_ranks)
        _set_combo(self.cpu_binding, values.cpu_binding)
        _set_combo(self.log_level, values.log_level)

    def _form_values(self) -> InputConfigurationValues:
        return InputConfigurationValues(
            xml_file_name=self.xml_file_name.text(),
            network_file_name=self.network_file.currentText(),
            network_configuration_tag=self.network_configuration_tag.currentText(),
            full_branch_n1=self.full_branch_n1.isChecked(),
            full_generator_n1=self.full_generator_n1.isChecked(),
            contingency_rating=self.contingency_rating.currentText(),
            enforce_reactive_power_limit=_combo_bool(self.enforce_reactive_power_limit),
            print_calc_files=_combo_bool(self.print_calc_files),
            group_size=self.group_size.text(),
            max_voltage=self.max_voltage.text(),
            min_voltage=self.min_voltage.text(),
            contingency_qlim_deadband=self.contingency_qlim_deadband.text(),
            contingency_ltc=_combo_bool(self.contingency_ltc),
            write_stats=_combo_bool(self.write_stats),
            contingency_output_format=self.contingency_output_format.currentText(),
            contingency_output_file=self.contingency_output_file.text(),
            contingency_list=self.contingency_list.text(),
            monitor_branches_file=self.monitor_branches_file.currentText(),
            monitor_areas=self.monitor_areas.text(),
            monitor_kv_min=self.monitor_kv_min.text(),
            monitor_kv_max=self.monitor_kv_max.text(),
            init_start=self.init_start.currentText(),
            switched_shunt=_combo_bool(self.switched_shunt),
            powerflow_qlim_deadband=self.powerflow_qlim_deadband.text(),
            powerflow_ltc=_combo_bool(self.powerflow_ltc),
            area_interchange=_combo_bool(self.area_interchange),
            max_controller_iterations=self.max_controller_iterations.text(),
            max_iteration=self.max_iteration.text(),
            tolerance=self.tolerance.text(),
            max_qlim_iterations=self.max_qlim_iterations.text(),
            damping_factor=self.damping_factor.text(),
            phase_shift_sign=self.phase_shift_sign.text(),
            petsc_prefix=self.petsc_prefix.text(),
            petsc_options=self.petsc_options.toPlainText(),
            use_gpu=self.use_gpu.isChecked(),
            gpu_enabled=self.gpu_enabled.currentText(),
            gpu_on_unavailable=self.gpu_on_unavailable.currentText(),
            gpu_backend=self.gpu_backend.currentText(),
            gpu_batch_size=self.gpu_batch_size.text(),
            gpu_warm_start=self.gpu_warm_start.currentText(),
            gpu_shadow_fraction=self.gpu_shadow_fraction.text(),
            gpu_plugin_path=self.gpu_plugin_path.text(),
            gpu_device=self.gpu_device.text(),
            gpu_max_validated_batch=self.gpu_max_validated_batch.text(),
            gpu_backfill=_combo_bool(self.gpu_backfill),
            gpu_threads_per_block=self.gpu_threads_per_block.text(),
            gpu_memory_profile=self.gpu_memory_profile.currentText(),
            gpu_memory_headroom_gb=self.gpu_memory_headroom_gb.text(),
            gpu_max_memory_gb=self.gpu_max_memory_gb.text(),
            gpu_formulation=self.gpu_formulation.currentText(),
            gpu_planner_ordering=self.gpu_planner_ordering.currentText(),
            gpu_pivot_tolerance=self.gpu_pivot_tolerance.text(),
            gpu_solve_placement=self.gpu_solve_placement.currentText(),
            gpu_refinement_steps=self.gpu_refinement_steps.text(),
            gpu_residual_limit=self.gpu_residual_limit.text(),
            gpu_pivot_limit=self.gpu_pivot_limit.text(),
            gpu_check_non_finite=_combo_bool(self.gpu_check_non_finite),
            gpu_telemetry=self.gpu_telemetry.currentText(),
            gpu_profiler_ranges=_combo_bool(self.gpu_profiler_ranges),
            accelerator_ranks=self.accelerator_ranks.text(),
            cpu_binding=self.cpu_binding.currentText(),
            log_level=self.log_level.currentText(),
        )


def _combo(items: tuple[str, ...]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(items)
    return combo


def _project_csv_file_names(project_data: ProjectData) -> list[str]:
    return [
        record.file_name
        for record in project_data.input_files
        if Path(record.file_name).suffix.lower() == ".csv"
    ]


def _set_combo(combo: QComboBox, value: str) -> None:
    index = combo.findText(value)
    if index < 0 and value:
        combo.addItem(value)
        index = combo.findText(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _set_bool_combo(combo: QComboBox, value: bool) -> None:
    _set_combo(combo, "True" if value else "False")


def _combo_bool(combo: QComboBox) -> bool:
    return combo.currentText() == "True"
