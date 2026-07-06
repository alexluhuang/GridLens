from __future__ import annotations

from multiprocessing import freeze_support
import sys


def main() -> int:
    freeze_support()
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
