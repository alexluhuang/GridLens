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
    DEFAULT_XML_FILE_NAME,
    INIT_START_OPTIONS,
    NETWORK_CONFIGURATION_TAG_OPTIONS,
    InputConfigurationValues,
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
        basic_form.addRow("Generated XML file", self.xml_file_name)
        basic_form.addRow("Network file", self.network_file)
        basic_form.addRow("Contingency type", contingency_type_row)
        basic_form.addRow("Contingency rating", self.contingency_rating)
        basic_form.addRow("Enforce reactive power limit", self.enforce_reactive_power_limit)

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

        advanced_fields_layout.addWidget(contingency_box)
        advanced_fields_layout.addWidget(powerflow_box)
        advanced_fields_layout.addWidget(monitoring_box)

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

    def set_project(self, project: Project, project_data: ProjectData) -> None:
        self.project = project
        self.project_data = project_data
        network_names = project_network_file_names(project_data)
        selected_network = network_names[0] if network_names else ""
        xml_file_name = project_data.xml_file_name or DEFAULT_XML_FILE_NAME
        values = default_input_configuration_values(selected_network, xml_file_name, project_data.name)

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
                    self.status.setText(f"Loaded project, but existing XML could not be parsed: {exc}")

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
        if network_names:
            self.status.setText(f"Ready to generate {self.xml_file_name.text().strip() or DEFAULT_XML_FILE_NAME}.")
        else:
            self.status.setText("Add a network file to the project before generating XML.")

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
