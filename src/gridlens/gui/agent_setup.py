"""The Set up Clarke dialog: install Hermes Agent and Ollama, and choose which models to install or remove.

The Agent tab opens it by itself when `check_setup` finds something missing, and from the model list's
"Install or remove models…" entry. Nothing is downloaded or removed until the user presses the dialog's
action button; the work runs in `SetupWorker`, off the GUI thread, and can be cancelled.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gridlens.agent.hermes import SUPPORTED_HERMES
from gridlens.agent.policy import AgentError
from gridlens.agent import setup
from gridlens.agent.setup import MODEL_CATALOG, PREFERRED_MODEL, SetupError, SetupStatus
from gridlens.gui.theme import configure_table, set_button_role, set_muted_label


MODEL_COLUMNS = ("Install", "Model", "Developer", "Total parameters", "Active parameters", "Modalities", "Context", "Download", "Status")


class SetupProbe(QThread):
    """Run check_setup off the GUI thread, which may take seconds when it starts Ollama."""

    checked = Signal(object)

    def run(self) -> None:
        """Emit the SetupStatus of this machine."""
        try:
            self.checked.emit(setup.check_setup())
        except Exception:  # A probe must never take the tab down; report nothing installed instead.
            self.checked.emit(SetupStatus())


class SetupWorker(QThread):
    """Install what is missing, then download and remove models, in that order."""

    log = Signal(str)
    progress = Signal(str, int, int)
    done = Signal(bool, str)

    def __init__(self, status: SetupStatus, install: list[str], remove: list[str], parent: QWidget) -> None:
        super().__init__(parent)
        self.status = status
        self.install = install
        self.remove = remove
        self.cancelled = threading.Event()

    def _progress(self, label: str):
        """Return a callback that reports received and total bytes under label."""
        return lambda received, total: self.progress.emit(label, received, total)

    def run(self) -> None:
        """Do each step, stopping at the first failure with a message the dialog shows."""
        try:
            if not self.status.hermes_ready:
                self.progress.emit(f"Installing Hermes Agent {SUPPORTED_HERMES}…", 0, 0)
                setup.install_hermes(self.log.emit, self.cancelled)
            ollama = self.status.ollama
            if not ollama:
                ollama = setup.install_ollama(self.log.emit, self._progress("Downloading Ollama…"), self.cancelled)
            if not setup.ollama_running():
                self.progress.emit("Starting Ollama…", 0, 0)
                self.log.emit("Starting Ollama.")
                setup.start_ollama(ollama)
            for name in self.install:
                self.progress.emit(f"Downloading {name}…", 0, 0)
                setup.pull_model(name, self.log.emit, self._progress(f"Downloading {name}…"), self.cancelled)
                self.log.emit(f"{name} is installed.")
            for name in self.remove:
                setup.delete_model(name)
                self.log.emit(f"{name} was removed.")
            self.done.emit(True, "Clarke is ready." if self.install or not self.remove else "Models updated.")
        except (SetupError, AgentError, OSError) as exc:
            self.done.emit(False, str(exc))


class AgentSetupDialog(QDialog):
    """Show what Clarke needs, and install or remove Hermes, Ollama, and models with the user's consent."""

    def __init__(self, status: SetupStatus, parent: QWidget | None = None) -> None:
        """Build the dialog from a finished check_setup; the Agent tab re-checks the runtime once it closes."""
        super().__init__(parent)
        self.status = status
        self.worker: SetupWorker | None = None
        self.changed = False
        self.setWindowTitle("Set up Clarke")
        self.resize(1180, 660)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(
            "Clarke runs entirely on this computer. It needs Hermes Agent, the agent harness; Ollama, which runs "
            "the model; and at least one model. GridLens can install whatever is missing. Downloads come from "
            "hermes-agent.nousresearch.com, ollama.com, and the Ollama model library, and nothing from your "
            "projects is sent."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.components = QLabel()
        self.components.setTextFormat(Qt.PlainText)
        self.components.setWordWrap(True)
        layout.addWidget(self.components)
        preferred = QLabel(f"★ {PREFERRED_MODEL} is the preferred model for Clarke. Check each model to install; uncheck an installed model to remove it.")
        preferred.setWordWrap(True)
        set_muted_label(preferred)
        layout.addWidget(preferred)
        self.table = QTableWidget(0, len(MODEL_COLUMNS))
        self.table.setHorizontalHeaderLabels(MODEL_COLUMNS)
        configure_table(self.table)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._update_action)
        layout.addWidget(self.table, 1)
        self.progress_label = QLabel()
        self.progress_label.setTextFormat(Qt.PlainText)
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(140)
        self.log.hide()
        layout.addWidget(self.log)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.action_button = QPushButton()
        set_button_role(self.action_button, "primary")
        self.action_button.clicked.connect(self.apply)
        self.close_button = QPushButton("Close")
        set_button_role(self.close_button, "secondary")
        self.close_button.clicked.connect(self.close_or_cancel)
        buttons.addWidget(self.action_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self._fill_models()
        self._describe_components()
        self._update_action()

    def _fill_models(self) -> None:
        """List the catalog, then any other installed model; check what is installed, or the preferred model."""
        installed = set(self.status.models)
        rows = list(MODEL_CATALOG) + [setup.model_info(name) for name in sorted(installed - {item.name for item in MODEL_CATALOG})]
        first_install = not installed
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row, info in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            wanted = info.name in installed or (first_install and info.preferred)
            check.setCheckState(Qt.Checked if wanted else Qt.Unchecked)
            check.setData(Qt.UserRole, info.name)
            self.table.setItem(row, 0, check)
            values = (
                f"★ {info.name}" if info.preferred else info.name, info.developer, info.total_parameters,
                info.active_parameters, info.modalities, info.context, info.download_size or "—",
                "Installed" if info.name in installed else "Not installed",
            )
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled)
                if info.preferred:
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _describe_components(self) -> None:
        """Say what is installed and what the action button will install or start."""
        status = self.status
        if status.hermes_ready:
            hermes = f"Hermes Agent {status.hermes_version}: installed."
        elif status.hermes:
            hermes = f"Hermes Agent {status.hermes_version}: installed, but Clarke needs {SUPPORTED_HERMES}. GridLens will install {SUPPORTED_HERMES}."
        else:
            hermes = f"Hermes Agent: not installed. GridLens will install version {SUPPORTED_HERMES}, which takes a few minutes."
        if status.ollama_running:
            ollama = "Ollama: installed and running."
        elif status.ollama:
            ollama = "Ollama: installed, but it did not start. GridLens will try to start it again."
        else:
            ollama = "Ollama: not installed. GridLens will install it for your user account; no administrator password is needed."
        self.components.setText(f"{hermes}\n{ollama}\nModels: {len(status.models)} installed.")

    def selected_changes(self) -> tuple[list[str], list[str]]:
        """Return the models to install and the models to remove, from the checkboxes."""
        installed = set(self.status.models)
        install, remove = [], []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            name = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked and name not in installed:
                install.append(name)
            elif item.checkState() != Qt.Checked and name in installed:
                remove.append(name)
        return install, remove

    def _update_action(self, *_args) -> None:
        """Name what the action button will do, and disable it when there is nothing to do."""
        install, remove = self.selected_changes()
        parts = []
        if not self.status.hermes_ready:
            parts.append("Hermes Agent")
        if not self.status.ollama:
            parts.append("Ollama")
        if install:
            parts.append(f"{len(install)} model{'s' if len(install) != 1 else ''}")
        label = "Install " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] if parts else ""
        if remove:
            label = (label + " and remove" if label else "Remove") + f" {len(remove)} model{'s' if len(remove) != 1 else ''}"
        if not label and not self.status.ollama_running and self.status.ollama:
            label = "Start Ollama"
        remaining_models = set(self.status.models) - set(remove) | set(install)
        self.action_button.setText(label or "Nothing to change")
        self.action_button.setEnabled(bool(label) and self.worker is None)
        self.progress_label.setText("" if remaining_models or self.worker else "Clarke needs at least one model. Check one to install.")

    def apply(self) -> None:
        """Confirm removals, then start the worker that installs and removes what the user chose."""
        install, remove = self.selected_changes()
        if remove:
            answer = QMessageBox.question(
                self, "Remove models",
                "Remove " + ", ".join(remove) + "? Installing a model again means downloading it again.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.worker = SetupWorker(self.status, install, remove, self)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.finished.connect(self._worker_finished)
        self.log.show()
        self.progress.show()
        self.table.setEnabled(False)
        self.close_button.setText("Cancel")
        self.changed = True
        self.worker.start()
        self._update_action()

    def on_progress(self, label: str, received: int, total: int) -> None:
        """Show the step in progress, with a byte count when the step downloads something."""
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(1000 * received / total))
            self.progress_label.setText(f"{label} {received / 1e9:.1f} of {total / 1e9:.1f} GB")
        else:
            self.progress.setRange(0, 0)
            self.progress_label.setText(label)

    def on_done(self, ok: bool, message: str) -> None:
        """Report the outcome, and refresh the model list from what Ollama now has."""
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if ok else 0)
        self.log.appendPlainText(message)
        try:
            self.status = setup.check_setup(start=False)
        except (AgentError, OSError):
            pass
        self._fill_models()
        self._describe_components()
        self.progress_label.setText(message if ok else f"Setup stopped: {message}")

    def _worker_finished(self) -> None:
        """Release the worker and let the user close the dialog or change more models."""
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self.table.setEnabled(True)
        self.close_button.setText("Close")
        self._update_action()

    def close_or_cancel(self) -> None:
        """Cancel a running step, or close the dialog when nothing runs."""
        if self.worker is not None:
            self.worker.cancelled.set()
            self.progress_label.setText("Cancelling…")
            return
        self.accept()

    def reject(self) -> None:  # noqa: D401 - Qt override
        """Treat Escape and the window's close button like Cancel while a step runs."""
        if self.worker is not None:
            self.close_or_cancel()
            return
        super().reject()
