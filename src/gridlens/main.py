from __future__ import annotations

import importlib
from multiprocessing import freeze_support
import os
import sys
import traceback

from gridlens.system import paths


def _run_import_diagnostics() -> int:
    modules = ("cudf", "dask_cudf", "dask.dataframe")
    failed = False
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            failed = True
            print(f"FAIL {module_name}", file=sys.stderr)
            traceback.print_exc()
            continue
        version = getattr(module, "__version__", "")
        suffix = f" {version}" if version else ""
        print(f"OK {module_name}{suffix}")
    return 1 if failed else 0


# NVIDIA's GPU direct-storage library, which cuDF loads to read results, writes cufile.log into the working
# directory of every process that reads a file, including agent job folders. Keep it in the cache instead.
CUFILE_LOG_ENV = "CUFILE_LOGFILE_PATH"


def _redirect_cufile_log() -> None:
    """Point cuFile's log at the GridLens cache, unless the user chose a place for it."""
    if os.environ.get(CUFILE_LOG_ENV):
        return
    try:
        folder = paths.cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ[CUFILE_LOG_ENV] = str(folder / "cufile.log")


def main() -> int:
    freeze_support()
    # Before anything imports cuDF; job workers and the MCP server run main() too, and inherit it.
    _redirect_cufile_log()
    if sys.argv[1:2] == ["--mcp-server"]:
        from gridlens.agent.mcp_server import main as mcp_main

        return mcp_main()
    if sys.argv[1:2] == ["--agent-tool"]:
        from gridlens.agent.mcp_server import tool_cli

        return tool_cli(sys.argv[2:])
    if sys.argv[1:2] == ["--agent-job"]:
        from gridlens.agent.jobs import main as job_main

        return job_main(sys.argv[2:])
    if os.environ.get("GRIDLENS_DIAGNOSTICS", "").strip().lower() == "imports":
        return _run_import_diagnostics()

    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        print(
            "PySide6 is not installed. Install the app dependencies with:\n"
            "  python3 -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  python -m pip install -e .\n",
            file=sys.stderr,
        )
        return 1

    from gridlens.gui.main_window import MainWindow
    from gridlens.gui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("GridLens")
    app.setOrganizationName("GridLens")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
