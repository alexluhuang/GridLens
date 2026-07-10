from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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

from gridlens.core.app_settings import AppSettings
from gridlens.core.project import Project, ProjectData, open_project
from gridlens.core.validation import ValidationError
from gridlens.gui.project_view_models import (
    ProjectFormValues,
    default_project_folder,
    prepare_project_save,
    should_update_project_folder,
)
from gridlens.gui.theme import configure_form_layout, set_button_role, set_muted_label


class ProjectTab(QWidget):
    project_changed = Signal(object, object)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.input_paths: list[Path] = []
        self.current_xml_file_name = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        project_box = QGroupBox("Project")
        project_form = QFormLayout(project_box)
        configure_form_layout(project_form)
        self.project_name = QLineEdit("GridPACK Pilot Project")
        self.project_dir = QLineEdit(str(settings.default_projects_dir / "GridPACK_Pilot_Project"))
        self.project_name.setToolTip("Used for project metadata and the default project folder name.")
        self.project_dir.setToolTip("Folder where GridLens stores project.json, copied inputs, and run outputs.")

        project_dir_row = QHBoxLayout()
        project_dir_row.setSpacing(8)
        project_dir_row.addWidget(self.project_dir)
        browse_project = QPushButton("Browse")
        set_button_role(browse_project, "secondary")
        browse_project.setToolTip("Choose the project folder.")
        browse_project.clicked.connect(self.choose_project_dir)
        project_dir_row.addWidget(browse_project)

        project_form.addRow("Project name", self.project_name)
        project_form.addRow("Project folder", project_dir_row)

        input_box = QGroupBox("Input Files")
        input_layout = QVBoxLayout(input_box)
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setTextElideMode(Qt.ElideMiddle)
        self.file_list.setToolTip("GridPACK input files copied into the project when it is saved.")
        input_layout.addWidget(self.file_list)

        input_buttons = QHBoxLayout()
        input_buttons.setSpacing(8)
        add_files = QPushButton("Add Files")
        set_button_role(add_files, "primary")
        add_files.setToolTip("Add XML, RAW, CSV, contingency, monitor, dynamics, or text inputs.")
        add_files.clicked.connect(self.add_files)
        remove_files = QPushButton("Remove Selected")
        set_button_role(remove_files, "destructive")
        remove_files.setToolTip("Remove selected files from this project input list.")
        remove_files.clicked.connect(self.remove_selected_files)
        clear_files = QPushButton("Clear")
        set_button_role(clear_files, "secondary")
        clear_files.setToolTip("Clear the input list.")
        clear_files.clicked.connect(self.clear_files)
        input_buttons.addWidget(add_files)
        input_buttons.addWidget(remove_files)
        input_buttons.addWidget(clear_files)
        input_buttons.addStretch()
        input_layout.addLayout(input_buttons)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.save_button = QPushButton("Create / Save Project")
        set_button_role(self.save_button, "primary")
        self.save_button.setToolTip("Save project metadata and copy the selected input files.")
        self.save_button.clicked.connect(self.save_project)
        self.open_button = QPushButton("Open Existing Project")
        set_button_role(self.open_button, "secondary")
        self.open_button.setToolTip("Open an existing GridLens project.json file.")
        self.open_button.clicked.connect(self.open_existing_project)
        action_row.addWidget(self.save_button)
        action_row.addWidget(self.open_button)
        action_row.addStretch()

        self.status = QLabel("No project saved yet.")
        set_muted_label(self.status)

        layout.addWidget(project_box)
        layout.addWidget(input_box, stretch=1)
        layout.addLayout(action_row)
        layout.addWidget(self.status)

        self.project_name.textChanged.connect(self.update_default_project_dir)

    def update_default_project_dir(self) -> None:
        if should_update_project_folder(self.project_dir.text()):
            try:
                project_dir = default_project_folder(
                    self.settings.default_projects_dir,
                    self.project_name.text(),
                )
            except ValidationError:
                return
            self.project_dir.setText(str(project_dir))

    def choose_project_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder", self.project_dir.text())
        if folder:
            self.project_dir.setText(folder)

    def set_project(self, project: Project, project_data: ProjectData) -> None:
        self.project_name.blockSignals(True)
        self.project_name.setText(project_data.name)
        self.project_name.blockSignals(False)
        self.project_dir.setText(str(project.root_dir))
        self.input_paths = [Path(record.stored_path) for record in project_data.input_files]
        self.current_xml_file_name = project_data.xml_file_name
        self.refresh_file_list()

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose GridPACK input files",
            str(Path.home()),
            "GridPACK Inputs (*.xml *.raw *.csv *.con *.mon *.txt *.dyr *.seq);;All Files (*)",
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
        for path in self.input_paths:
            item = QListWidgetItem(f"{path.name}  -  {path.parent}")
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            self.file_list.addItem(item)

    def save_project(self) -> None:
        try:
            prepared = prepare_project_save(self._project_form_values())
            project_data = prepared.project.save(prepared.input_files, prepared.xml_file_name)
            project = prepared.project
            self.current_xml_file_name = project_data.xml_file_name
            self.status.setText(f"Saved project: {project.project_file}")
            self.project_changed.emit(project, project_data)
        except Exception as exc:
            QMessageBox.critical(self, "Project cannot be saved", str(exc))

    def _project_form_values(self) -> ProjectFormValues:
        return ProjectFormValues(
            project_name=self.project_name.text(),
            project_dir=self.project_dir.text(),
            input_paths=self.input_paths,
            xml_file_name=self._selected_xml_file_name(),
        )

    def _selected_xml_file_name(self) -> str:
        file_names = {path.name for path in self.input_paths}
        if self.current_xml_file_name in file_names:
            return self.current_xml_file_name
        return ""

    def open_existing_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open project.json",
            str(self.settings.default_projects_dir),
            "GridLens Project (project.json);;JSON Files (*.json);;All Files (*)",
        )
        if not file_name:
            return
        try:
            project, project_data = open_project(file_name)
            self.set_project(project, project_data)
            self.status.setText(f"Loaded project: {project.project_file}")
            self.project_changed.emit(project, project_data)
        except Exception as exc:
            QMessageBox.critical(self, "Project cannot be opened", str(exc))
