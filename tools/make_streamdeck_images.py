"""Draw the Stream Deck plugin's images from FaderDeck's own icons and logo.

Run after changing an icon or the logo:

    .\\.venv\\Scripts\\python.exe tools\\make_streamdeck_images.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

import main

PLUGIN = os.path.join(ROOT, "streamdeck", "com.faderdeck.streamdeck.sdPlugin", "imgs")
ICON_GREY = "#d7e1eb"  # the colour the icons are drawn in

# action: (icon, key colour, key colour when on/muted)
ACTIONS = {
    "mute": ("speaker", "#58a6ff", "#f85149"),
    "volume": ("speaker", "#58a6ff", None),
    "monitor": ("mic", "#f5b83d", "#f5b83d"),
    "streammute": ("mic", "#58a6ff", "#f85149"),
    "profile": ("settings", "#8a5cff", None),
}


def svg(name, colour):
    return QSvgRenderer(QByteArray(
        main.MONO_ICONS[name].replace(ICON_GREY, colour).encode("utf-8")
    ))


def save(image, folder, name):
    os.makedirs(folder, exist_ok=True)
    image.save(os.path.join(folder, name + ".png"))


def icon(name, size, colour="#ffffff"):
    """A plain icon on a transparent background, for the action list."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg(name, colour).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def key(name, size, colour, lit=False, crossed=False):
    """A key face: the icon on a dark tile, or white on a coloured one."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(colour if lit else "#111923"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.24
    box = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    svg("speaker_off" if crossed else name, "#ffffff" if lit else colour).render(painter, box)
    painter.end()
    return image


def logo(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(main.LOGO_SVG.encode("utf-8"))).render(
        painter, QRectF(0, 0, size, size)
    )
    painter.end()
    return image


if __name__ == "__main__":
    app = QGuiApplication.instance() or QGuiApplication([])
    for action, (name, colour, on_colour) in ACTIONS.items():
        folder = os.path.join(PLUGIN, "actions", action)
        for suffix, scale in (("", 1), ("@2x", 2)):
            save(icon(name, 20 * scale), folder, "icon" + suffix)
            save(key(name, 72 * scale, colour), folder, "key" + suffix)
            if on_colour:
                crossed = action == "mute"
                save(key(name, 72 * scale, on_colour, lit=True, crossed=crossed),
                     folder, "key-on" + suffix)
    plugin = os.path.join(PLUGIN, "plugin")
    for suffix, scale in (("", 1), ("@2x", 2)):
        save(logo(28 * scale), plugin, "category-icon" + suffix)
    save(logo(288), plugin, "marketplace")
    save(logo(512), plugin, "marketplace@2x")
    print(f"Wrote the images under {PLUGIN}")
