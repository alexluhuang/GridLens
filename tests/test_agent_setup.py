"""Set up Clarke: detection, installation with stand-in downloads, model pulls, and the dialog's choices."""
from __future__ import annotations

import io
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
import subprocess
import sys
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gridlens.agent import setup
from gridlens.agent.hermes import SUPPORTED_HERMES, SUPPORTED_HERMES_COMMIT
from gridlens.agent.setup import MODEL_CATALOG, PREFERRED_MODEL, SetupError, SetupStatus
from gridlens.gui.agent_setup import AgentSetupDialog


def test_status_names_what_is_missing():
    """Only the validated Hermes, a running Ollama, and one model make Clarke ready."""
    assert SetupStatus("/h", SUPPORTED_HERMES, "/o", True, ("m",)).ready
    assert SetupStatus().missing() == ["Hermes Agent is not installed.", "Ollama is not installed."]
    old = SetupStatus("/h", "0.20.0", "/o", True, ())
    assert not old.ready
    assert old.missing() == [f"Hermes Agent 0.20.0 is installed; Clarke needs version {SUPPORTED_HERMES}.", "No model is installed."]
    assert SetupStatus("/h", SUPPORTED_HERMES, "/o", False).missing() == ["Ollama is installed but did not start."]


def test_catalog_lists_the_preferred_model_once_with_every_detail():
    names = [item.name for item in MODEL_CATALOG]
    assert len(names) == len(set(names))
    assert [item.name for item in MODEL_CATALOG if item.preferred] == [PREFERRED_MODEL] == [names[0]]
    for item in MODEL_CATALOG:
        assert all((item.developer, item.total_parameters, item.active_parameters, item.modalities, item.context, item.download_size))


def test_model_info_describes_an_unlisted_model_from_ollama(monkeypatch):
    show = {
        "capabilities": ["completion", "tools", "vision"],
        "model_info": {"general.architecture": "llama", "general.parameter_count": 8_030_000_000, "llama.context_length": 131072},
    }
    monkeypatch.setattr(setup, "ollama_json", lambda *_args: show)
    info = setup.model_info("custom:8b")
    assert (info.total_parameters, info.active_parameters, info.modalities, info.context) == ("8B", "8B", "Text, image", "128K")
    show["model_info"].update({"llama.expert_count": 8, "llama.expert_used_count": 2})
    assert setup.model_info("custom:8b").active_parameters == "—"
    assert setup.model_info(PREFERRED_MODEL) is MODEL_CATALOG[0]


def test_check_setup_starts_an_installed_ollama_that_is_not_running(monkeypatch):
    started = []
    monkeypatch.setattr(setup, "hermes_executable", lambda: "")
    monkeypatch.setattr(setup, "ollama_executable", lambda: "/opt/ollama")
    monkeypatch.setattr(setup, "ollama_running", lambda *_args: False)
    monkeypatch.setattr(setup, "start_ollama", lambda executable, endpoint: started.append(executable))
    monkeypatch.setattr(setup, "local_models", lambda *_args: ("m:1",))
    status = setup.check_setup()
    assert started == ["/opt/ollama"]
    assert (status.ollama_running, status.started_ollama, status.models) == (True, True, ("m:1",))
    assert not setup.check_setup(start=False).ollama_running


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _serve_pull(monkeypatch, events):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return _Response(b"".join(json.dumps(event).encode() + b"\n" for event in events))

    monkeypatch.setattr(setup, "build_opener", lambda *_args: Opener())
    return requests


def test_pull_reports_progress_across_layers_and_needs_success(monkeypatch):
    requests = _serve_pull(monkeypatch, [
        {"status": "pulling manifest"},
        {"status": "pulling a", "digest": "a", "total": 100, "completed": 50},
        {"status": "pulling b", "digest": "b", "total": 300, "completed": 300},
        {"status": "pulling a", "digest": "a", "total": 100, "completed": 100},
        {"status": "success"},
    ])
    lines, progress = [], []
    setup.pull_model("m:1", lines.append, lambda done, total: progress.append((done, total)), threading.Event())
    assert requests[0].full_url == "http://127.0.0.1:11434/api/pull"
    assert json.loads(requests[0].data) == {"model": "m:1", "stream": True}
    assert progress == [(50, 100), (350, 400), (400, 400)]
    assert lines == ["m:1: pulling manifest", "m:1: success"]
    _serve_pull(monkeypatch, [{"status": "pulling manifest"}, {"error": "file does not exist"}])
    with pytest.raises(SetupError, match="file does not exist"):
        setup.pull_model("m:1", lines.append, lambda *_args: None, threading.Event())
    _serve_pull(monkeypatch, [{"status": "pulling manifest"}])
    with pytest.raises(SetupError, match="before it finished"):
        setup.pull_model("m:1", lines.append, lambda *_args: None, threading.Event())


def test_model_requests_refuse_a_remote_endpoint():
    with pytest.raises(Exception, match="loopback"):
        setup.pull_model("m:1", print, print, threading.Event(), endpoint="http://example.com:11434")


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("zstd"), reason="Linux Ollama archives are .tar.zst")
def test_install_ollama_unpacks_the_release_into_the_data_folder(monkeypatch, tmp_path):
    release = tmp_path / "release"
    (release / "bin").mkdir(parents=True)
    (release / "bin" / "ollama").write_text("#!/bin/sh\n")
    (release / "bin" / "ollama").chmod(0o755)
    archive = tmp_path / "ollama.tar.zst"
    subprocess.run(["tar", "--use-compress-program=zstd", "-cf", str(archive), "-C", str(release), "bin"], check=True)
    urls = []

    def download(url, destination, progress, cancelled):
        urls.append(url)
        shutil.copy(archive, destination)

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(setup, "_download", download)
    monkeypatch.setattr(setup.platform, "machine", lambda: "aarch64")
    path = setup.install_ollama(lambda _line: None, lambda *_args: None, threading.Event())
    assert urls == ["https://ollama.com/download/ollama-linux-arm64.tar.zst"]
    assert path == str(tmp_path / "data" / "gridlens" / "ollama" / "bin" / "ollama")
    assert os.access(path, os.X_OK)


@pytest.mark.skipif(sys.platform == "win32", reason="The POSIX installer runs through bash")
def test_install_hermes_runs_the_official_installer_at_the_validated_commit(monkeypatch, tmp_path):
    """A stand-in installer checks the flags GridLens passes, then puts a hermes CLI in ~/.local/bin."""
    installer = f"""#!/bin/bash
[ "$*" = "--non-interactive --skip-browser --skip-computer-use --commit {SUPPORTED_HERMES_COMMIT}" ] || exit 3
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\\necho "Hermes Agent v{SUPPORTED_HERMES} (test)"\\n' > "$HOME/.local/bin/hermes"
chmod +x "$HOME/.local/bin/hermes"
echo installed
"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    monkeypatch.setattr(setup, "_download", lambda url, destination, progress, cancelled: destination.write_text(installer))
    lines = []
    path = setup.install_hermes(lines.append, threading.Event())
    assert path == str(tmp_path / ".local" / "bin" / "hermes")
    assert "installed" in lines
    monkeypatch.setattr(setup, "_download", lambda url, destination, progress, cancelled: destination.write_text("exit 7\n"))
    with pytest.raises(SetupError, match="exited with code 7"):
        setup.install_hermes(lines.append, threading.Event())


def test_dialog_checks_the_preferred_model_first_and_names_its_action():
    app = QApplication.instance() or QApplication([])
    dialog = AgentSetupDialog(SetupStatus("", "", "", False, ()))
    assert dialog.selected_changes() == ([PREFERRED_MODEL], [])
    assert dialog.action_button.text() == "Install Hermes Agent, Ollama and 1 model"
    assert dialog.table.item(0, 1).text() == f"★ {PREFERRED_MODEL}"
    assert [dialog.table.horizontalHeaderItem(column).text() for column in range(dialog.table.columnCount())][1:7] == [
        "Model", "Developer", "Total parameters", "Active parameters", "Modalities", "Context"]
    dialog.table.item(0, 0).setCheckState(Qt.Unchecked)
    assert dialog.action_button.text() == "Install Hermes Agent and Ollama"
    assert "at least one model" in dialog.progress_label.text()
    dialog.deleteLater()
    app.processEvents()


def test_dialog_installs_checked_models_and_removes_unchecked_installed_ones(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(setup, "model_info", lambda name, endpoint=setup.DEFAULT_ENDPOINT: setup.ModelInfo(name, "—", "—", "—", "—", "—"))
    status = SetupStatus("/h", SUPPORTED_HERMES, "/o", True, ("gpt-oss:20b", "custom:1b"))
    dialog = AgentSetupDialog(status)
    rows = {dialog.table.item(row, 0).data(Qt.UserRole): row for row in range(dialog.table.rowCount())}
    assert "custom:1b" in rows
    assert dialog.table.item(rows["gpt-oss:20b"], 8).text() == "Installed"
    assert dialog.selected_changes() == ([], [])
    assert not dialog.action_button.isEnabled()
    dialog.table.item(rows[PREFERRED_MODEL], 0).setCheckState(Qt.Checked)
    dialog.table.item(rows["custom:1b"], 0).setCheckState(Qt.Unchecked)
    assert dialog.selected_changes() == ([PREFERRED_MODEL], ["custom:1b"])
    assert dialog.action_button.text() == "Install 1 model and remove 1 model"
    dialog.deleteLater()
    app.processEvents()
