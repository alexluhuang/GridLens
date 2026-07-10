from __future__ import annotations

import importlib
from multiprocessing import freeze_support
import os
import sys
import traceback


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


def main() -> int:
    freeze_support()
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
