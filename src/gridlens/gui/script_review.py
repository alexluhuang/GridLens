from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout

from gridlens.agent.policy import AgentError
from gridlens.agent.scripts import execute_proposal, read_proposal
from gridlens.agent.session import SessionContext, scoped_path


class ScriptWorker(QThread):
    outcome = Signal(object)

    def __init__(self, context, identifier, digest, image, parent):
        super().__init__(parent)
        self.arguments = (context, identifier, digest, image)
        self.cancelled = threading.Event()

    def run(self) -> None:
        try:
            self.outcome.emit(execute_proposal(*self.arguments, cancelled=self.cancelled))
        except Exception as exc:
            self.outcome.emit({"status": "failed", "detail": str(exc)})


class ScriptReview(QDialog):
    def __init__(self, context: SessionContext, parent):
        super().__init__(parent)
        self.context = context
        self.worker = None
        self.record = None
        self.setWindowTitle("Review generated analysis")
        self.resize(820, 720)
        layout = QVBoxLayout(self)
        self.choice = QComboBox()
        directory = scoped_path(context.directory, "generated", directory=True)
        for path in sorted(directory.glob("*.json")):
            self.choice.addItem(path.stem)
        layout.addWidget(self.choice)
        self.purpose = QLabel()
        self.purpose.setTextFormat(Qt.PlainText)
        self.purpose.setWordWrap(True)
        layout.addWidget(self.purpose)
        self.code = QPlainTextEdit()
        self.code.setReadOnly(True)
        layout.addWidget(self.code, 2)
        limits = QLabel("Approve only code you have reviewed. Execution reads the selected run and prints results; generated results remain unvalidated.\nNo network or GPU; 2 CPUs, 1 GiB RAM, 64 processes, 120 seconds, 256 KiB output. /output is 32 MiB temporary scratch.\nUse an image built from packaging/agent/Dockerfile, then paste its full sha256 image ID below.")
        limits.setWordWrap(True)
        layout.addWidget(limits)
        self.image = QLineEdit()
        self.image.setPlaceholderText("sha256:… (docker image inspect IMAGE --format '{{.Id}}')")
        layout.addWidget(self.image)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        buttons = QHBoxLayout()
        self.approve = QPushButton("Approve this script and run")
        self.approve.clicked.connect(self.run_script)
        self.stop = QPushButton("Stop")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        buttons.addWidget(self.approve)
        buttons.addWidget(self.stop)
        layout.addLayout(buttons)
        self.choice.currentTextChanged.connect(self.show_proposal)
        self.show_proposal()

    def show_proposal(self) -> None:
        self.record = None
        try:
            self.record, _, code = read_proposal(self.context, self.choice.currentText())
            self.purpose.setText(f"Run: {self.record['run_id']}\nPurpose: {self.record['purpose']}\nSHA256: {self.record['sha256']}")
            self.code.setPlainText(code)
        except (AgentError, OSError) as exc:
            self.output.setPlainText(str(exc))
        self.approve.setEnabled(self.record is not None)

    def run_script(self) -> None:
        if not self.record or self.worker:
            return
        self.worker = ScriptWorker(self.context, self.choice.currentText(), self.record["sha256"], self.image.text().strip(), self)
        self.worker.outcome.connect(lambda result: self.output.setPlainText(f"{result['status']}\n{result.get('detail', '')}\n{result.get('output_excerpt', '')}"))
        self.worker.finished.connect(self.finished_script)
        for control in (self.choice, self.image, self.approve):
            control.setEnabled(False)
        self.stop.setEnabled(True)
        self.output.setPlainText("Running approved script…")
        self.worker.start()

    def finished_script(self) -> None:
        self.worker.deleteLater()
        self.worker = None
        for control in (self.choice, self.image, self.approve):
            control.setEnabled(True)
        self.stop.setEnabled(False)

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancelled.set()

    def reject(self) -> None:
        self.cancel()
        if not self.worker or self.worker.wait(5000):
            super().reject()

    def closeEvent(self, event) -> None:
        self.cancel()
        if self.worker and not self.worker.wait(5000):
            event.ignore()
        else:
            event.accept()
