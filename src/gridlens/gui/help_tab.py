from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget


class HelpTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        browser = QTextBrowser()
        browser.setObjectName("documentPane")
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            """
            <h1>GridLens Workflow</h1>
            <h2>Recommended Stack</h2>
            <p>Use Python with PySide6/Qt for the desktop interface, Docker Engine for the GridPACK runtime,
            and local project folders for all CEII inputs, logs, outputs, and reports.</p>

            <h2>Run Model</h2>
            <ol>
              <li>Create or open a local project.</li>
              <li>Add the GridPACK input files and choose the XML configuration file.</li>
              <li>Use the Run tab to check Docker and run the configured Docker image.</li>
              <li>Review output files in Results.</li>
              <li>Generate local summaries, charts, and reports in Analysis.</li>
            </ol>

            <h2>CEII Defaults</h2>
            <p>Runs mount only the per-run work folder into the container at <code>/app/workspace</code>.
            The default Docker run uses <code>--network none</code> and <code>--pull=never</code>, so the
            GridPACK image should be installed before sensitive inputs are loaded.</p>

            <h2>Packaging Direction</h2>
            <p>Use PyInstaller for the first pilot build and a Debian package for DGX OS 7 deployment.
            Flatpak is not the first choice because this application needs controlled access to Docker,
            local CEII files, and potentially GPU/container runtime integration.</p>
            """
        )
        layout.addWidget(browser)
