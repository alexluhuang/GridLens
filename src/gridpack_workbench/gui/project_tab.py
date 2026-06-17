from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gridpack_workbench.core.app_settings import AppSettings
from gridpack_workbench.core.project import Project, open_project, safe_folder_name
from gridpack_workbench.core.validation import ValidationError, validate_existing_files
from gridpack_workbench.gui.theme import set_button_role


class ProjectTab(QWidget):
    project_changed = Signal(object, object)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.input_paths: list[Path] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        project_box = QGroupBox("Project")
        project_form = QFormLayout(project_box)
        self.project_name = QLineEdit("GridPACK Pilot Project")
        self.project_dir = QLineEdit(str(settings.default_projects_dir / "GridPACK_Pilot_Project"))

        project_dir_row = QHBoxLayout()
        project_dir_row.addWidget(self.project_dir)
        browse_project = QPushButton("Browse")
        set_button_role(browse_project, "secondary")
        browse_project.clicked.connect(self.choose_project_dir)
        project_dir_row.addWidget(browse_project)

        project_form.addRow("Project name", self.project_name)
        project_form.addRow("Project folder", project_dir_row)

        input_box = QGroupBox("Input Files")
        input_layout = QVBoxLayout(input_box)
        self.file_list = QListWidget()
        input_layout.addWidget(self.file_list)

        input_buttons = QHBoxLayout()
        add_files = QPushButton("Add Files")
        set_button_role(add_files, "primary")
        add_files.clicked.connect(self.add_files)
        remove_files = QPushButton("Remove Selected")
        set_button_role(remove_files, "destructive")
        remove_files.clicked.connect(self.remove_selected_files)
        clear_files = QPushButton("Clear")
        set_button_role(clear_files, "secondary")
        clear_files.clicked.connect(self.clear_files)
        input_buttons.addWidget(add_files)
        input_buttons.addWidget(remove_files)
        input_buttons.addWidget(clear_files)
        input_buttons.addStretch()
        input_layout.addLayout(input_buttons)

        xml_row = QHBoxLayout()
        self.xml_combo = QComboBox()
        xml_row.addWidget(QLabel("GridPACK XML file"))
        xml_row.addWidget(self.xml_combo)
        input_layout.addLayout(xml_row)

        action_row = QHBoxLayout()
        self.save_button = QPushButton("Create / Save Project")
        set_button_role(self.save_button, "primary")
        self.save_button.clicked.connect(self.save_project)
        self.open_button = QPushButton("Open Existing Project")
        set_button_role(self.open_button, "secondary")
        self.open_button.clicked.connect(self.open_existing_project)
        action_row.addWidget(self.save_button)
        action_row.addWidget(self.open_button)
        action_row.addStretch()

        self.status = QLabel("No project saved yet.")
        self.status.setObjectName("mutedLabel")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(project_box)
        layout.addWidget(input_box, stretch=1)
        layout.addLayout(action_row)
        layout.addWidget(self.status)

        self.project_name.textChanged.connect(self.update_default_project_dir)

    def update_default_project_dir(self) -> None:
        current = Path(self.project_dir.text()).name
        if current.startswith("GridPACK") or current == "GridPACK_Pilot_Project":
            try:
                folder_name = safe_folder_name(self.project_name.text())
            except ValidationError:
                return
            self.project_dir.setText(str(self.settings.default_projects_dir / folder_name))

    def choose_project_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder", self.project_dir.text())
        if folder:
            self.project_dir.setText(folder)

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose GridPACK input files",
            str(Path.home()),
            "GridPACK Inputs (*.xml *.raw *.con *.mon *.txt *.dyr *.seq);;All Files (*)",
        )
        for file_name in files:
            path = Path(file_name).expanduser().resolve()
            if path not in self.input_paths:
                self.input_paths.append(path)
        self.refresh_file_list()

    def remove_selected_files(self) -> None:
        selected = {item.data(Qt.UserRole) for item in self.file_list.selectedItems()}
        self.input_paths = [path for path in self.input_paths if str(path) not in selected]
        self.refresh_file_list()

    def clear_files(self) -> None:
        self.input_paths.clear()
        self.refresh_file_list()

    def refresh_file_list(self) -> None:
        self.file_list.clear()
        self.xml_combo.clear()
        for path in self.input_paths:
            item = QListWidgetItem(f"{path.name}    {path.parent}")
            item.setData(Qt.UserRole, str(path))
            self.file_list.addItem(item)
            if path.suffix.lower() == ".xml":
                self.xml_combo.addItem(path.name)

        if self.xml_combo.count() == 0:
            self.xml_combo.addItem("")

    def save_project(self) -> None:
        try:
            files = validate_existing_files(self.input_paths)
            xml_file_name = self.xml_combo.currentText().strip()
            if not xml_file_name:
                raise ValidationError("Add an XML input file and choose it from the XML file field.")
            if xml_file_name not in {path.name for path in files}:
                raise ValidationError("The selected XML file must be one of the project input files.")

            project = Project(self.project_name.text(), self.project_dir.text())
            project_data = project.save(files, xml_file_name)
            self.status.setText(f"Saved project: {project.project_file}")
            self.project_changed.emit(project, project_data)
        except Exception as exc:
            QMessageBox.critical(self, "Project cannot be saved", str(exc))

    def open_existing_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open project.json",
            str(self.settings.default_projects_dir),
            "GridPACK Workbench Project (project.json);;JSON Files (*.json);;All Files (*)",
        )
        if not file_name:
            return
        try:
            project, project_data = open_project(file_name)
            self.project_name.setText(project_data.name)
            self.project_dir.setText(project_data.root_dir)
            self.input_paths = [Path(record.stored_path) for record in project_data.input_files]
            self.refresh_file_list()
            index = self.xml_combo.findText(project_data.xml_file_name)
            if index >= 0:
                self.xml_combo.setCurrentIndex(index)
            self.status.setText(f"Loaded project: {project.project_file}")
            self.project_changed.emit(project, project_data)
        except Exception as exc:
            QMessageBox.critical(self, "Project cannot be opened", str(exc))
