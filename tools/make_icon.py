"""Build faderdeck.ico from the logo drawing in themes.py (LOGO_SVG).

The window header draws the same SVG, so the two cannot drift apart. Run this
after changing the drawing:

    .\\.venv\\Scripts\\python.exe tools\\make_icon.py
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

import themes

# Windows picks the closest size for the title bar, taskbar, tray and Explorer.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(themes.LOGO_SVG.encode("utf-8"))).render(
        painter, QRectF(0, 0, size, size)
    )
    painter.end()
    return image


def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(path):
    """Write a .ico holding one PNG per size."""
    images = [png_bytes(render(size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for size, data in zip(SIZES, images):
        # A width or height of 0 in the directory means 256.
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    with open(path, "wb") as handle:
        handle.write(header + entries + b"".join(images))


if __name__ == "__main__":
    app = QGuiApplication.instance() or QGuiApplication([])
    target = os.path.join(ROOT, "faderdeck.ico")
    write_ico(target)
    print(f"Wrote {target} ({os.path.getsize(target)} bytes, sizes {SIZES})")
