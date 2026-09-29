"""Render GridLens's SVG icon as the Windows .ico file the executables use.

Usage: python packaging/windows/make_icon.py OUTPUT.ico

The icon is rendered from src/gridlens/resources/gridlens.svg at build time,
so the repository keeps one source for it.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

SOURCE = (Path(__file__).resolve().parents[2]
          / "src" / "gridlens" / "resources" / "gridlens.svg")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    """Return the SVG rendered as a square PNG of size pixels."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def main(argv: list[str]) -> int:
    """Write the icon to the path given as the only argument."""
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    output = Path(argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    application = QGuiApplication([])
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        print(f"Cannot read {SOURCE}", file=sys.stderr)
        return 1
    largest = Image.open(io.BytesIO(render_png(renderer, max(SIZES))))
    largest.save(output, format="ICO", sizes=[(size, size) for size in SIZES])
    del application
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
