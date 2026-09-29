"""Setting up Clarke on this machine: Hermes Agent, Ollama, and the models Ollama serves.

Clarke needs three things GridLens does not ship: the Hermes Agent harness, the Ollama inference engine,
and at least one model. `check_setup` finds out which of them this machine has, and starts an installed
Ollama that is not running. The Agent tab shows the result and, when something is missing, asks the user
before it installs anything; everything below runs only after that consent.

Hermes and Ollama are downloaded from their official sites, and models from the Ollama library through
the local Ollama service. Installing sends nothing about a project anywhere. Hermes is installed at the
one commit the Hermes adapter is validated against, and Ollama into GridLens's own data folder, so no
administrator password is needed.

The functions take a `log` callback for lines to show the user and a `cancelled` event, and raise
`SetupError` with a message written for the user. None of them touches the GUI.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from gridlens.agent.hermes import DEFAULT_ENDPOINT, SUPPORTED_HERMES, SUPPORTED_HERMES_COMMIT, VERSION_PATTERN, hermes_executable
from gridlens.agent.policy import AgentError, local_endpoint, ollama_json
from gridlens.agent.process import probe_version
from gridlens.system import paths, processes


HERMES_INSTALLER_POSIX = "https://hermes-agent.nousresearch.com/install.sh"
HERMES_INSTALLER_WINDOWS = "https://hermes-agent.nousresearch.com/install.ps1"
OLLAMA_DOWNLOADS = "https://ollama.com/download"
PREFERRED_MODEL = "nemotron-3.5-lightning:latest"
# An installer that stops producing output for this long is treated as stuck.
INSTALL_TIMEOUT_SECONDS = 30 * 60
OLLAMA_START_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 1024 * 1024

Log = Callable[[str], None]
Progress = Callable[[int, int], None]


class SetupError(RuntimeError):
    """A setup step failed; the message says what happened and what the user can do."""


@dataclass(frozen=True)
class ModelInfo:
    """What a user needs in order to choose a model: who made it, how large it is, and what it reads."""

    name: str
    developer: str
    total_parameters: str
    active_parameters: str
    modalities: str
    context: str
    download_size: str = ""

    @property
    def preferred(self) -> bool:
        """Return True for the model Clarke is tuned and evaluated with."""
        return self.name == PREFERRED_MODEL


# The models validated with Clarke, from the Ollama library. Figures are the developers' published ones;
# active parameters are those used for each token, which differ from the total for mixture-of-experts models.
MODEL_CATALOG = (
    ModelInfo("nemotron-3.5-lightning:latest", "NVIDIA", "30B", "3B", "Text", "1M", "25 GB"),
    ModelInfo("nemotron-3-super:120b", "NVIDIA", "120B", "12B", "Text", "256K", "86 GB"),
    ModelInfo("nemotron3:33b", "NVIDIA", "33B", "3B", "Text, image, video, audio", "128K", "27 GB"),
    ModelInfo("gpt-oss:120b", "OpenAI", "117B", "5.1B", "Text", "128K", "65 GB"),
    ModelInfo("gpt-oss:20b", "OpenAI", "21B", "3.6B", "Text", "128K", "13 GB"),
    ModelInfo("gemma4:31b", "Google", "31B", "31B", "Text, image", "256K", "19 GB"),
    ModelInfo("gemma4:e4b", "Google", "8B", "4B", "Text, image, audio", "128K", "9.6 GB"),
    ModelInfo("muse-glimmer:30b", "Meta", "30B", "30B", "Text, image", "128K", "18 GB"),
    ModelInfo("granite4.2:30b", "IBM", "29B", "29B", "Text", "128K", "17 GB"),
    ModelInfo("granite4.2:8b", "IBM", "8.8B", "8.8B", "Text", "128K", "5.3 GB"),
)


@dataclass(frozen=True)
class SetupStatus:
    """What check_setup found: the Hermes CLI and its version, Ollama, and the installed local models."""

    hermes: str = ""
    hermes_version: str = ""
    ollama: str = ""
    ollama_running: bool = False
    models: tuple[str, ...] = ()
    # Set when check_setup started an installed Ollama that was not running.
    started_ollama: bool = False

    @property
    def hermes_ready(self) -> bool:
        """Return True when the validated Hermes version is installed."""
        return bool(self.hermes) and self.hermes_version == SUPPORTED_HERMES

    @property
    def ready(self) -> bool:
        """Return True when Clarke can run: the validated Hermes, a running Ollama, and a model."""
        return self.hermes_ready and self.ollama_running and bool(self.models)

    def missing(self) -> list[str]:
        """Name, for the user, each thing Clarke still needs."""
        needs = []
        if not self.hermes:
            needs.append("Hermes Agent is not installed.")
        elif not self.hermes_ready:
            needs.append(f"Hermes Agent {self.hermes_version} is installed; Clarke needs version {SUPPORTED_HERMES}.")
        if not self.ollama:
            needs.append("Ollama is not installed.")
        elif not self.ollama_running:
            needs.append("Ollama is installed but did not start.")
        elif not self.models:
            needs.append("No model is installed.")
        return needs


def data_folder() -> Path:
    """Return the folder GridLens installs its own copy of Ollama into."""
    return paths.data_dir()


def managed_ollama() -> Path:
    """Return where install_ollama puts the Ollama executable on this platform."""
    if sys.platform == "darwin":
        return Path.home() / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "Ollama" / "ollama.exe"
    return data_folder() / "ollama" / "bin" / "ollama"


def ollama_executable() -> str:
    """Return the Ollama executable on PATH, or the one GridLens installed, or "" when there is none."""
    found = shutil.which("ollama")
    if found:
        return found
    path = managed_ollama()
    return str(path) if path.is_file() and os.access(path, os.X_OK) else ""


def ollama_running(endpoint: str = DEFAULT_ENDPOINT) -> bool:
    """Return True when an Ollama service answers on the loopback endpoint."""
    try:
        ollama_json(endpoint, "/api/version")
        return True
    except AgentError:
        return False


def local_models(endpoint: str = DEFAULT_ENDPOINT) -> tuple[str, ...]:
    """Return the models installed in the local Ollama service, leaving out cloud and remote ones."""
    inventory = ollama_json(endpoint, "/api/tags")
    return tuple(sorted({
        item["name"] for item in inventory.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str) and not item.get("remote_host")
        and "cloud" not in item["name"].lower().split(":")[-1]
    }))


def start_ollama(executable: str, endpoint: str = DEFAULT_ENDPOINT, *, wait: float = OLLAMA_START_SECONDS) -> None:
    """Start `ollama serve` on the loopback endpoint, detached from GridLens, and wait until it answers."""
    origin = local_endpoint(endpoint)
    environment = dict(os.environ, OLLAMA_HOST=origin.removeprefix("http://"))
    log_path = data_folder() / "ollama-serve.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if sys.platform == "win32" else {"start_new_session": True}
    with log_path.open("ab") as log:
        subprocess.Popen([executable, "serve"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=environment, **options)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if ollama_running(origin):
            return
        time.sleep(0.5)
    raise SetupError(f"Ollama was started but did not answer within {wait:.0f} seconds. Its log is {log_path}.")


def check_setup(endpoint: str = DEFAULT_ENDPOINT, *, start: bool = True) -> SetupStatus:
    """Find Hermes, Ollama, and the installed models; start an installed Ollama that is not running."""
    hermes = hermes_executable()
    version = ""
    if hermes:
        try:
            version = probe_version(hermes, VERSION_PATTERN)
        except (OSError, subprocess.SubprocessError):
            version = "unknown"
    ollama = ollama_executable()
    running = ollama_running(endpoint)
    started = False
    if not running and ollama and start:
        try:
            start_ollama(ollama, endpoint)
            running = started = True
        except (SetupError, OSError, AgentError):
            running = False
    models: tuple[str, ...] = ()
    if running:
        try:
            models = local_models(endpoint)
        except AgentError:
            models = ()
    return SetupStatus(hermes, version, ollama, running, models, started)


def _download(url: str, destination: Path, progress: Progress | None, cancelled: threading.Event) -> None:
    """Download url to destination, reporting bytes received, and stop when cancelled."""
    with urlopen(Request(url, headers={"User-Agent": "GridLens"}), timeout=60) as response, destination.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
            if cancelled.is_set():
                raise SetupError("Installation cancelled.")
            handle.write(chunk)
            received += len(chunk)
            if progress:
                progress(received, total)


def _run_logged(argv: list[str], log: Log, cancelled: threading.Event, *, env: dict | None = None, cwd: Path | None = None) -> None:
    """Run an installer, passing each line it prints to log; stop it when cancelled or stuck."""
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, env=env, cwd=cwd,
        **processes.new_group_options())
    last_output = [time.monotonic()]

    def watch() -> None:
        """Stop the installer when the user cancels or it goes silent for too long."""
        while process.poll() is None:
            if cancelled.is_set() or time.monotonic() - last_output[0] > INSTALL_TIMEOUT_SECONDS:
                # Stop the installer with the downloads and tools it started.
                processes.terminate(process)
                return
            time.sleep(0.2)

    threading.Thread(target=watch, daemon=True).start()
    for raw in process.stdout:
        last_output[0] = time.monotonic()
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            log(line)
    code = process.wait()
    if cancelled.is_set():
        raise SetupError("Installation cancelled.")
    if code:
        raise SetupError(f"{Path(argv[0]).name} exited with code {code}. The lines above say why.")


def install_hermes(log: Log, cancelled: threading.Event) -> str:
    """Install the validated Hermes Agent release with its official installer; return the CLI path.

    The installer clones Hermes into ~/.hermes/hermes-agent at SUPPORTED_HERMES_COMMIT and links the CLI
    into ~/.local/bin. It skips its interactive setup and its browser and computer-use tools, which
    Clarke never uses.
    """
    with tempfile.TemporaryDirectory(prefix="gridlens-hermes-") as folder:
        if sys.platform == "win32":
            script = Path(folder) / "install.ps1"
            log(f"Downloading the Hermes Agent installer from {HERMES_INSTALLER_WINDOWS}")
            _download(HERMES_INSTALLER_WINDOWS, script, None, cancelled)
            argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                    "-NonInteractive", "-SkipBrowser", "-SkipComputerUse", "-Commit", SUPPORTED_HERMES_COMMIT]
        else:
            if not shutil.which("git"):
                raise SetupError("The Hermes installer needs git. Install git (for example: sudo apt install git), then try again.")
            script = Path(folder) / "install.sh"
            log(f"Downloading the Hermes Agent installer from {HERMES_INSTALLER_POSIX}")
            _download(HERMES_INSTALLER_POSIX, script, None, cancelled)
            argv = ["bash", str(script), "--non-interactive", "--skip-browser", "--skip-computer-use", "--commit", SUPPORTED_HERMES_COMMIT]
        log(f"Installing Hermes Agent {SUPPORTED_HERMES}. This can take several minutes.")
        _run_logged(argv, log, cancelled, env=dict(os.environ), cwd=Path(folder))
    executable = hermes_executable()
    if not executable:
        raise SetupError("The Hermes installer finished, but the hermes command was not found in ~/.local/bin.")
    version = probe_version(executable, VERSION_PATTERN)
    if version != SUPPORTED_HERMES:
        raise SetupError(f"The installer set up Hermes {version}, not {SUPPORTED_HERMES}.")
    log(f"Hermes Agent {version} is installed at {executable}.")
    return executable


def _linux_architecture() -> str:
    """Return Ollama's name for this machine's architecture."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise SetupError(f"Ollama does not publish a build for {machine} processors.")


def install_ollama(log: Log, progress: Progress, cancelled: threading.Event) -> str:
    """Download Ollama from ollama.com into GridLens's data folder, with no administrator rights; return it.

    On Linux the release archive is unpacked under data_folder()/ollama; on macOS the app goes to
    ~/Applications; on Windows the official installer runs for the current user.
    """
    target = managed_ollama()
    with tempfile.TemporaryDirectory(prefix="gridlens-ollama-") as folder:
        if sys.platform == "win32":
            installer = Path(folder) / "OllamaSetup.exe"
            log(f"Downloading Ollama from {OLLAMA_DOWNLOADS}/OllamaSetup.exe")
            _download(f"{OLLAMA_DOWNLOADS}/OllamaSetup.exe", installer, progress, cancelled)
            log("Installing Ollama.")
            _run_logged([str(installer), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], log, cancelled)
        elif sys.platform == "darwin":
            archive = Path(folder) / "Ollama-darwin.zip"
            log(f"Downloading Ollama from {OLLAMA_DOWNLOADS}/Ollama-darwin.zip")
            _download(f"{OLLAMA_DOWNLOADS}/Ollama-darwin.zip", archive, progress, cancelled)
            applications = Path.home() / "Applications"
            applications.mkdir(exist_ok=True)
            shutil.rmtree(applications / "Ollama.app", ignore_errors=True)
            log(f"Unpacking Ollama into {applications}")
            _run_logged(["ditto", "-x", "-k", str(archive), str(applications)], log, cancelled)
        else:
            if not shutil.which("zstd"):
                raise SetupError("Unpacking Ollama needs zstd. Install it (for example: sudo apt install zstd), then try again.")
            name = f"ollama-linux-{_linux_architecture()}.tar.zst"
            archive = Path(folder) / name
            log(f"Downloading Ollama from {OLLAMA_DOWNLOADS}/{name}")
            _download(f"{OLLAMA_DOWNLOADS}/{name}", archive, progress, cancelled)
            home = target.parents[1]
            staged = home.with_name(home.name + ".new")
            shutil.rmtree(staged, ignore_errors=True)
            staged.mkdir(parents=True)
            log(f"Unpacking Ollama into {home}")
            _run_logged(["tar", "--use-compress-program=zstd", "-xf", str(archive), "-C", str(staged)], log, cancelled)
            shutil.rmtree(home, ignore_errors=True)
            os.replace(staged, home)
    if not target.is_file():
        raise SetupError(f"Ollama was unpacked, but {target} is missing.")
    log(f"Ollama is installed at {target}.")
    return str(target)


def _model_request(endpoint: str, path: str, body: dict, method: str = "POST") -> Request:
    """Build a request to the loopback Ollama service, after checking that the endpoint is loopback."""
    return Request(local_endpoint(endpoint) + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method=method)


def pull_model(name: str, log: Log, progress: Progress, cancelled: threading.Event, endpoint: str = DEFAULT_ENDPOINT) -> None:
    """Download a model into the local Ollama service, reporting bytes received across all its layers.

    Closing the connection is how a pull is cancelled: Ollama stops a pull whose client has gone.
    """
    opener = build_opener(ProxyHandler({}))
    layers: dict[str, tuple[int, int]] = {}
    status = ""
    with opener.open(_model_request(endpoint, "/api/pull", {"model": name, "stream": True}), timeout=120) as response:
        for raw in response:
            if cancelled.is_set():
                raise SetupError("Installation cancelled.")
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("error"):
                raise SetupError(f"Ollama could not download {name}: {event['error']}")
            if event.get("status") and event["status"] != status and not event.get("digest"):
                status = event["status"]
                log(f"{name}: {status}")
            if event.get("digest") and event.get("total"):
                layers[event["digest"]] = (int(event.get("completed") or 0), int(event["total"]))
                progress(sum(done for done, _ in layers.values()), sum(total for _, total in layers.values()))
    if status != "success":
        raise SetupError(f"Ollama stopped downloading {name} before it finished.")


def delete_model(name: str, endpoint: str = DEFAULT_ENDPOINT) -> None:
    """Remove a model from the local Ollama service."""
    try:
        with build_opener(ProxyHandler({})).open(_model_request(endpoint, "/api/delete", {"model": name}, "DELETE"), timeout=60):
            pass
    except OSError as exc:
        raise SetupError(f"Ollama could not remove {name}: {exc}") from exc


def _parameter_label(count: object) -> str:
    """Write a parameter count the way model cards do, such as 8.8B or 117B."""
    if not isinstance(count, (int, float)) or count <= 0:
        return "—"
    billions = count / 1e9
    return f"{billions:.1f}B".replace(".0B", "B") if billions < 10 else f"{billions:.0f}B"


def _context_label(tokens: object) -> str:
    """Write a context length the way model cards do, such as 128K or 1M."""
    if not isinstance(tokens, int) or tokens <= 0:
        return "—"
    return f"{tokens // 1_048_576}M" if tokens >= 1_048_576 else f"{tokens // 1024}K"


def model_info(name: str, endpoint: str = DEFAULT_ENDPOINT) -> ModelInfo:
    """Describe a model: from the catalog when it is listed there, else from what Ollama reports about it."""
    listed = next((item for item in MODEL_CATALOG if item.name == name), None)
    if listed is not None:
        return listed
    try:
        info = ollama_json(endpoint, "/api/show", {"model": name})
    except AgentError:
        return ModelInfo(name, "—", "—", "—", "—", "—")
    details = info.get("model_info") or {}
    architecture = details.get("general.architecture", "")
    experts, used = details.get(f"{architecture}.expert_count"), details.get(f"{architecture}.expert_used_count")
    capabilities = info.get("capabilities") or []
    modalities = ", ".join(["Text"] + [label for key, label in (("vision", "image"), ("audio", "audio")) if key in capabilities])
    return ModelInfo(
        name, str(details.get("general.organization") or "—"), _parameter_label(details.get("general.parameter_count")),
        # A mixture-of-experts model uses only some parameters per token; Ollama does not report how many.
        "—" if experts and used else _parameter_label(details.get("general.parameter_count")),
        modalities, _context_label(details.get(f"{architecture}.context_length")),
    )
