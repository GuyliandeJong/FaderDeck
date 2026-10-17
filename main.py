import sys
import math
import array
import atexit
import concurrent.futures
import ctypes
import ctypes.wintypes
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
import warnings
import threading
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, unquote, urlsplit


from PySide6.QtCore import (QPoint, QUrl, Qt, Signal, QObject, QTimer, QRectF, QBuffer, QIODevice, QFileInfo, QThread, QSettings, Slot, QMetaObject, QAbstractNativeEventFilter, QByteArray, QSize, QMimeData, QPointF, qInstallMessageHandler)
from PySide6.QtGui import QDesktopServices, QBrush, QColor, QDrag, QImage, QFont, QFontMetricsF, QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QPixmap

from PySide6.QtSvg import QSvgRenderer

from PySide6.QtWidgets import (

    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QColorDialog,
    QInputDialog,
    QKeySequenceEdit,
    QMessageBox,
    QFileIconProvider,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,

    QMainWindow,

    QDialog,
    QMenu,
    QSystemTrayIcon,
    QPushButton,

    QProgressBar,
    QProgressDialog,
    QScrollArea,
    QSpinBox,

    QStyle,
    QSlider,
    QStyleOptionSlider,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QTabWidget,

    QToolButton,

    QVBoxLayout,
    QWidget,
)


voicemeeterlib = None  # loaded by load_voicemeeterlib()

try:
    from pycaw.pycaw import AudioUtilities
    from pycaw.constants import EDataFlow, DEVICE_STATE
    PYCAW_AVAILABLE = True
except ImportError:
    AudioUtilities = None
    PYCAW_AVAILABLE = False

# Optional: moving an application between virtual channels (drag and drop)
# uses Windows' per-app output device setting through this small package.
# FaderDeck runs without it; dropping an application then shows a hint.
try:
    import winappaudiorouter as war
    APP_ROUTING_AVAILABLE = True
except Exception:
    war = None
    APP_ROUTING_AVAILABLE = False


# Monochrome UI icons. They are embedded as SVG so the application does not
# need extra icon files at runtime or during PyInstaller packaging.


# The FaderDeck mark: three faders on a tile. The window header draws it
# from here, and tools/make_icon.py turns the same drawing into faderdeck.ico.
LOGO_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"
     viewBox="0 0 256 256">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2aa8ff"/>
      <stop offset="1" stop-color="#8a5cff"/>
    </linearGradient>
  </defs>
  <rect x="10" y="10" width="236" height="236" rx="54" fill="url(#tile)"/>
  <rect x="67" y="58" width="14" height="140" rx="7" fill="#ffffff"
        fill-opacity="0.35"/>
  <rect x="51" y="89" width="46" height="30" rx="8" fill="#ffffff"/>
  <rect x="121" y="58" width="14" height="140" rx="7" fill="#ffffff"
        fill-opacity="0.35"/>
  <rect x="105" y="145" width="46" height="30" rx="8" fill="#ffffff"/>
  <rect x="175" y="58" width="14" height="140" rx="7" fill="#ffffff"
        fill-opacity="0.35"/>
  <rect x="159" y="109" width="46" height="30" rx="8" fill="#ffffff"/>
</svg>
"""
# The two colours of the tile's gradient, also used for the name beside it.
LOGO_GRADIENT = ("#2aa8ff", "#8a5cff")


def _svg_icon(svg, size=22):
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# The eye artwork is derived from the user-provided reference image and
# embedded here so the application remains self-contained.
EYE_ICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA4CAYAAABqtn+aAAAACXBIWXMAAA7EAAAOxAGVKw4b"
    "AAANbUlEQVR4nO1be3Bc1X3+fr9zd2VkY/CDR0wKZCCOTTKTpPUjJS1YL6+0LzkCaxpapxgc"
    "Z2imLQRoZmoyqidAM8OzjzSY4WFIIYmMLWsfV1pJtjApSU3cdKYdwBiapKQkjd9gS7J07zm/"
    "/rFa7d2XdVeScTOjb2ZHu3f3fOc73z2P3/mdK2AWs5jFLGYxiymCzreAHLq7u5cQzVlGyroK"
    "RJcQq0th9HwYLQZ8ipgOM9MH2pifkR5+PRaLvXe+NQPn0cBEf/+VSgdjonW9iHyeSF0KMQQI"
    "AEb2Lzx/yftZQHyYldpvjBlwaCT5hZaWX3y4LShU9aHAtu35WqxbiIJfgtBqQBgiKDRJPCW8"
    "8rzXc99R7q0RcfcL4TmLxr4XDoc/OEdNKMGHYmB3d98SFQzeA202AnJxQeN9I2cgF13zmk8g"
    "xe+L6Ge14zzU2rr2V9OUPinOqYG9vb0LXVPzDQhthpjawmqlQvW5IZx77y1T/LtC87zXBRgh"
    "S20bG3bub2trPDa9llTGOTGws7NTXTBv0W1k8ACAS0qr8g7V3DAkAeQwIG9BqXdIjCOkjhnj"
    "agYWQ6kgGVwrWl8L0BLAUNZoAmh86oTx1DF+I0iOQtwtw8Mnnm5vb9cz3dYZN9C291yjhZ4m"
    "oRtL562iaklOCpAUoFdBXg2H698lokqFJrA7k/kdpdX1TFZEWMWg5WKYnHnlihOg6IfGObM5"
    "Hg8dnFLDKmAmDaSkvWcTGTwMYH75KggAG5DZBzbfYRlNhMPh0elUatt2jcYFMRJsFqEGKpwk"
    "4TVUIKeJ+a8iLTc+4edG+cGMGNjZ2TmvtnbRMwCvr9gDiDREdzOb+8Phpn+fiXqLkezd+2kY"
    "+gYZWgeIKp1nBSAFgd5p3ODG1tY/ODXdOqdtYCq1bzlIvwSR6/Lxm1c4gRT9yLjuPbFY44+n"
    "W58f7E5nVlsUfAxGfr9iExUftEjf3Nxc//p06pqWganewUZo+gHELCwKdHPvj4PNvZGWxmf9"
    "DplMJjPXcdQqInWdkCwCABI6pmnszRqF/aFQaMgPj4hQuvfl22D4IYgsKNKF7Kjgk5Cx9dFo"
    "04AfznKYsoGpnoE/haZtANWUoxNCj3GdTX5jsd2pzPUBVfOXYhDNhzy51TrbYGI1BEbKOCOP"
    "xmLNr/nh7e7rW6KcwNMQaS5d/QkgnCGWOyItddv98BVjSgYm0n2bWPgJgFXJ7oHIIciW117b"
    "98jWrVtNRZJxdNr2JbUy5+8g+KOz68nXIzAGhH8eUe5d7c3Nxyero6Ojg1etqrsbzA+INoGS"
    "eZqgIe6fRaNNT07GVU5VVUin995lDB4movHVLh/QCslh0aY9Hl+7zw9XKtW/HBToh8gVlUOe"
    "nMziwBmAZb0bIB0Khep8hSbp9J4bROgHAC4v6Y3EBha+Hg3d+LAfLq8y30inB74qwn+PiVDB"
    "O2TlP0Q76+Lx0M/9cCUSmWXMahBQl+evltt5eM0r3nkQwPi1cUfr/cZ3XT09V1tmzi4CfTaX"
    "l/DUaQB9ZzTa8A9+uLwqJ4WdGfxj7chzBFKF3wgE8kPCSGs0Gj3hh6urq+viQPCi/RBZWhon"
    "ZjnzW7pyva94QcAh5tGVfpMIqVRqAdS8XdBmTUndrDSxszHS3PBdP1w8+U+AVKq/0TiyPWte"
    "cYZEJ44eeXetX/MAIFCz4EEILS29f+PGMB0D9HYw7oNltojop4T5cOG984ZLaqnhed/yW380"
    "Gj3xs7eHm8GSKElsGKPEpWdSqf6QH65Je2AqNfgpwLwK0PzCJABD2KQ+cumFbStWrHD8ik8m"
    "+z5OHHgDAit7xduz9Kgh+psLa/nxurq6M95ytm3XCNX+hWjzTUBq8mXGX4q1xtAnW1ta3vKr"
    "5cCBA4HfHBveJVqi2a2gdzHEB0ZLXTze8NOzcZy1B3Z29l8kkC6A5xcOHQFIpxVGbq7GPAAg"
    "sv681DwAoDFhWh+PNHyr2DwACIfDo5GWNQ+JuG0CjOWH9ziPdpVlgndUo2XFihUO6dM3Q3S6"
    "MBEBQGg+W2rXrl0Di87GUdHAjo4Orr0w+AKBrs1fzZlofnTk8H/fXO0+dnBw0AJRWyEfAAiE"
    "nAdj4YbkZByx2FqbFX8TVDxfAgK6qaOjw6pGUzgcHmU6c5OI7M2PrnFug6tq5vCLZ+OsaOCq"
    "VdffDe1GisMLIT5ojGrduHFjSS+ZDKdOjX4C4CtKFg7ikyND1iN+eSweewxEJyfKT7z4o59d"
    "vXpptbrC4fCo46AdrN4o1GYgRtauXHnD1yuVLWtgKtW/XFBzf/aTZwVkOkbitsXjdUerFQkA"
    "gTlzlham8LP8RMi0t9ed9ssTCoWGILqnJC4UA5bA8qloa2trPKbItIFwJKdrgpu4w7YHritX"
    "rkIP5AiAYGEYYcSIe2s02vTmVAQCgNa0sEQcAIF5p2oygifeLLghC6amDmhpqX8LbDYAYvL6"
    "CBAKGPC6cmXKGsiWJeXiLQVR5X7vG9pBdrL2zl8Epawp5OZEShMY08/OkTEBjG+S/aCsgaKd"
    "JCBOYQDLJBR8JtW/b0pDBADI4vGh7xFHDF2wUPmDCH0sv3J6G2v5jkeLkUr1LxdS2/NnBOMv"
    "Mq4ruuwCV9bASKTxEMT5a2/MBxBgZCEc7EwkBhdPRSALDhYGw5TtSI4TymQyc/3yPP98Zi6h"
    "XHYFYNFvTEVbIpFYLFC7YGRRni83t47dty7S9J/lylVchX/yk395lNhKFv7EAMZdzqx32LZd"
    "U6lsJTQ3171NjF+WbtlogaMDd/vlWbiQvgbBwpIvCO8ND584VK0u27ZrmGt3EGRZsTZh6olE"
    "Qg9VKlvRwK1bt5qhgLMBFr3tJRzfOq0xNHdntSYSkQHQVZocYADWllTPvvhkHIn0QBSw7itM"
    "NgCAgUDvrPbkzbbtGiNzdgK0pnTfLe+MBNwvjusui7PuRNqbmt7XoyNhQB8vyYQYigjPe+nA"
    "gQOBagQbd/QfAeMWcAGAMUFo3ZlM999b7sbYtl2TTA58TUF2ABIsISa4DHy7Gi0HDhwIaKn5"
    "PgSR0rMT8z5g4u1NTe+fjcPXUtOdztxgIZARoTklWzpGYvj00fXt7e1jfoWn7L3/BFF3ZGNC"
    "FPIBIMs6DNEJEfMWERkxWAridTByWcmWKxunAWyejLbUf8Wvhs7OzmDtvEU7YBCf4JkIq2gM"
    "4oRisaaXJ+Pxve6ne/feIkY9B2Oskt5o0SBcvika/UNfK2AqlVpAgYv+TVz9sdJnY/JDsjTJ"
    "WpwJGr9K9F8iwyv9ZoQGBwfnnR7WL5JQrJBXAIIrJLfGwo0v+OGqMqHat0HEehYFS2kusal/"
    "agL6C/Gmpnf9cGUyg8scVwYhuexwjqtc8hQoPunLXRPRh4lG10SjUV8Bfndf3xJ21G4SrCz8"
    "hgBAM+vbwuGm5/1weZX4Rrpnz61i+CkIxk30NIzpVwbmlni43ldKP5HJLGNdkwHoyqxn5Xrd"
    "WaQT3mPSa8PhRl+hS6JnYCVrvATQlaVnxqSJZFMk0rDdpwAAPhOqXkRaGrYL3C8DKFoICDBY"
    "osjqT9mDd3Z0dEzKHQ+FDhpXfo8D6gVMTG7FvcyL3BwlBowXxkbHftePeSJCKbt/M2u8AqCM"
    "eaKF9JerNa+SSl9I9eyNw/D3skeQRTREIkAqoM58pbm5+dd++Gy7/3MC606AogKam09weg7o"
    "mYYEJkkij0ci9fv98HZ3d1/G1rwnSKgVkKItmgCQYUDfHo2Gvu+HrxjT2jx2232fVxLcCdBl"
    "E/tvb9Za8XEyzt3hcP1z1Rysa1irtcY1ZOQjYAbA/yvkHBJn5LV4PD7sUx4lk/0biOgRAIsr"
    "NPWIKNMea5l8ta1YyVQL5tDTM3i1htoNrT+dv1p0AET8itH6rsnS4zOFdLrvMwL1KAR1Zea6"
    "nMLXmUxbJNJY9c7Fi+mnLwAkEolaUvOfINCG/EJQtHoyuxDp0uT8bes5ergokej9JKvAFgit"
    "B6Qoi+wZGSQ7tHv69tbW1vP/cJEX6d6XN4rrPo6JAyhvNbmVmg2gB0nkO0NDR5PVBODlsG3b"
    "tsBHr/p4WIxsFo3m7IF/xdniFJHcGw43PPn/6vE2L2x7zzUG6ikYrCk9KC/SzHycWFIQ3aud"
    "oVdjsdgvfTSMbNu+QiRwvYBbIBQFsLh0qBbVS/KKGL0pFlv79tRbV559xtHZ2alqaxfeCuIH"
    "IHRZ/pviHUeu0QbZvJb8BkSHQPxzZoy4rhxnAGBZALKCJOZaESwFcDlEKM9V7omG8fqIjjCZ"
    "LadPH3vmt+IRXy+6urouDsxZuEWM+SqJuaBwq1aS+UDpsPeu7Fz0+2LpRSYSjzDj20aferCa"
    "Q/9qcU4NzKGvr2/JmKPuAVm3QzA/v/+ttNedSoo+1yHlJAhPact5rHXtb/m/ORQjlUotQGDe"
    "F+HInwj0asoGeSjsmWfrZd7em3+oXMCGWPZD0Xdr2HmxaZIU1EziQzXQi66unqsDNcEYQTWB"
    "+XOiZTFEe+a1onT9xL8yCEAkYBwlyL/CuBmtJRmP+0tizDTOm4HFSCaTVygV/ISIdZUhuoTY"
    "mgvIXBgjIhiCkmGATxjt/iJAY2+Gw+H/Od+aZzGLWcxiFrOYFv4P3gbXzUDddIIAAAAASUVO"
    "RK5CYII="
)


def reference_eye_icon(size=20):
    pixmap = QPixmap()
    pixmap.loadFromData(
        QByteArray.fromBase64(EYE_ICON_PNG_B64.encode("ascii")),
        "PNG",
    )
    if pixmap.isNull():
        return mono_icon("eye", size)
    return QIcon(
        pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )


MONO_ICONS = {
    "mic_off": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <rect x="8.2" y="3.2" width="7.6" height="11.6" rx="3.8"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"/>
          <path d="M5.5 11.5v1.1a6.5 6.5 0 0 0 13 0v-1.1
                   M12 19.1v2.1 M8.5 21.2h7 M4 3l16 18"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round"/>
        </svg>
    """,
    "compact": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M9 4v5H4 M15 4v5h5 M9 20v-5H4 M15 20v-5h5"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    """,
    "speaker": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linejoin="round"/>
          <path d="M15.5 9a4.2 4.2 0 0 1 0 6 M18 6.5a7.8 7.8 0 0 1 0 11"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round"/>
        </svg>
    """,
    "speaker_off": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"
                fill="none" stroke="#f0b6b1" stroke-width="1.8"
                stroke-linejoin="round"/>
          <path d="M15.5 9.5l5 5 M20.5 9.5l-5 5"
                fill="none" stroke="#f0b6b1" stroke-width="1.8"
                stroke-linecap="round"/>
        </svg>
    """,
    "settings": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M4 7h9 M17 7h3 M4 12h3 M11 12h9 M4 17h10 M18 17h2"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round"/>
          <circle cx="15" cy="7" r="2" fill="none" stroke="#d7e1eb"
                  stroke-width="1.8"/>
          <circle cx="9" cy="12" r="2" fill="none" stroke="#d7e1eb"
                  stroke-width="1.8"/>
          <circle cx="16" cy="17" r="2" fill="none" stroke="#d7e1eb"
                  stroke-width="1.8"/>
        </svg>
    """,
    "eye": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M2.2 12s3.7-6.1 9.8-6.1S21.8 12 21.8 12
                   18.1 18.1 12 18.1 2.2 12 2.2 12Z"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="12" cy="12" r="3.2"
                  fill="none" stroke="#d7e1eb" stroke-width="1.8"/>
        </svg>
    """,
    "mic": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <rect x="8.2" y="3.2" width="7.6" height="11.6" rx="3.8"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"/>
          <path d="M5.5 11.5v1.1a6.5 6.5 0 0 0 13 0v-1.1
                   M12 19.1v2.1 M8.5 21.2h7"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round"/>
        </svg>
    """,
    "game": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M7.1 8h9.8c2.1 0 3.6 1.5 4.2 3.5l1.1 4.1
                   c.5 1.9-.6 3.3-2.2 3.3-1 0-1.7-.5-2.4-1.4l-1.5-2H7.9l-1.5 2
                   c-.7.9-1.4 1.4-2.4 1.4-1.6 0-2.7-1.4-2.2-3.3l1.1-4.1
                   C3.5 9.5 5 8 7.1 8Z"
                fill="none" stroke="#d7e1eb" stroke-width="1.7"
                stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M7 11v4 M5 13h4 M15.8 12.2h.1 M18.1 14.3h.1"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round"/>
        </svg>
    """,
    "chat": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M4.2 5.2h15.6c1 0 1.8.8 1.8 1.8v8.1c0 1-.8 1.8-1.8 1.8H11l-4.2 3v-3H4.2
                   c-1 0-1.8-.8-1.8-1.8V7c0-1 .8-1.8 1.8-1.8Z"
                fill="none" stroke="#d7e1eb" stroke-width="1.7"
                stroke-linejoin="round"/>
          <path d="M7 10.5h10 M7 13.5h7"
                fill="none" stroke="#d7e1eb" stroke-width="1.6"
                stroke-linecap="round"/>
        </svg>
    """,
    "media": """
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
             viewBox="0 0 24 24">
          <path d="M9 18.1V6.2l10-2.1v11.9"
                fill="none" stroke="#d7e1eb" stroke-width="1.8"
                stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="6.4" cy="18.3" r="2.8"
                  fill="none" stroke="#d7e1eb" stroke-width="1.8"/>
          <circle cx="16.4" cy="16.2" r="2.8"
                  fill="none" stroke="#d7e1eb" stroke-width="1.8"/>
        </svg>
    """,
}


def mono_icon(name, size=22):
    return _svg_icon(translate_colors(MONO_ICONS[name]), size)


# Qt can emit a harmless font warning from an internal style/font fallback
# even though the application explicitly uses a valid point-sized base font.
# Filter only this exact warning; all other Qt messages remain untouched.
def _qt_message_handler(mode, context, message):
    if message == "QFont::setPointSize: Point size <= 0 (-1), must be greater than 0":
        return
    log.warning(f"Qt: {message}")


log = logging.getLogger("faderdeck")


def log_file_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "FaderDeck", "faderdeck.log")


def setup_logging():
    """Log to a small rotating file and, when there is one, the console.

    The packaged build is windowed: it has no console, so print() output and
    uncaught exceptions would otherwise be lost.
    """
    log.setLevel(logging.INFO)
    handlers = []
    try:
        path = log_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path, maxBytes=512_000, backupCount=2, encoding="utf-8"
            )
        )
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        log.addHandler(handler)

    def log_uncaught(exc_type, exc_value, exc_traceback):
        log.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def log_uncaught_in_thread(args):
        log.critical(
            f"Uncaught exception in thread {getattr(args.thread, 'name', '?')}",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_uncaught
    threading.excepthook = log_uncaught_in_thread


# Folder names that change with every update of an application:
# "154.0.4258.53", "app-1.0.9163" and Store packages such as
# "msteams_25275.2601.4002.2815_x64__8wekyb3d8bbwe".
_VERSION_FOLDER = re.compile(r"^(app-|v)?\d+(\.\d+)+$")
_STORE_FOLDER = re.compile(r"^(.+?)_\d+(\.\d+)+_(.+)$")


def stable_hide_key(executable_path, app_name=""):
    """Identify an application for hiding, independent of its version.

    The key is the executable path with version folders replaced by "*", so
    an application stays hidden after it updates into a new folder, while two
    different programs with the same file name stay separate.
    """
    path = (executable_path or "").strip().casefold()
    if not path:
        return (app_name or "").strip().casefold()

    parts = []
    for part in path.replace("/", "\\").split("\\"):
        if _VERSION_FOLDER.match(part):
            part = "*"
        else:
            part = _STORE_FOLDER.sub(r"\1_*_\3", part)
        parts.append(part)
    return "\\".join(parts)


VOICEMEETER_DOWNLOAD_URL = "https://vb-audio.com/Voicemeeter/potato.htm"
# VoiceMeeter's uninstall key: one for every edition. The library finds
# its DLL through it too.
VOICEMEETER_KEY = (
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\VB:Voicemeeter {17359A74-1236-5467}"
)


def voicemeeter_install_state():
    """"potato" when VoiceMeeter Potato is installed, "other" for only
    Standard or Banana, "missing" for none. Reads the registry and lists
    one folder, so it is quick enough for the GUI thread."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VOICEMEETER_KEY) as key:
            uninstaller = winreg.QueryValueEx(key, "UninstallString")[0]
        folder = os.path.dirname(uninstaller.strip().strip('"'))
        names = {name.lower() for name in os.listdir(folder)}
    except OSError:
        return "missing"
    # Potato's installer brings all three editions; Potato is voicemeeter8.
    if "voicemeeter8.exe" in names or "voicemeeter8x64.exe" in names:
        return "potato"
    return "other"


def load_voicemeeterlib():
    """The voicemeeterlib module, or None while it cannot load (VoiceMeeter
    is not installed). Tried again on every call, so an install made while
    FaderDeck runs is picked up."""
    global voicemeeterlib
    if voicemeeterlib is None:
        try:
            import voicemeeterlib as module
        except Exception as error:
            log.warning(f"VoiceMeeter API not available: {error}")
            return None
        voicemeeterlib = module
    return voicemeeterlib


# Window class of VoiceMeeter's main window (all editions).
VOICEMEETER_WINDOW_CLASS = "VBCABLE0Voicemeeter0MainWindow0"


def voicemeeter_is_running():
    """Return True while VoiceMeeter's main window exists.

    One Win32 call that returns immediately, so it is safe to poll from the
    GUI thread (listing processes is not).
    """
    try:
        return bool(
            ctypes.windll.user32.FindWindowW(VOICEMEETER_WINDOW_CLASS, None)
        )
    except Exception:
        return False


# VoiceMeeter strip indexes

STRIPS = {
    "Mic": 0,
    "Game": 5,
    "Chat": 6,
    "Media": 7,
}

# The Mic strip is the only strip with processing controls and a VU meter.

SETTINGS_NAME = "FaderDeck"
# Executables that are this program: not listed as an application.
OWN_EXECUTABLES = ("faderdeck.exe",)


def app_settings():
    return QSettings(SETTINGS_NAME, SETTINGS_NAME)


def setting_bool(settings, key, default):
    """Read a yes/no setting; QSettings may hand it back as text."""
    value = settings.value(key, default)
    if isinstance(value, str):
        return value.strip().casefold() in ("true", "1", "yes")
    return bool(value)


# The channels the user may rename. The built-in name stays the key for
# settings, profiles, hotkeys and the local API.
CHANNEL_NAME_KEYS = {
    "Game": "channel_name_game",
    "Chat": "channel_name_chat",
    "Media": "channel_name_media",
}
CHANNEL_NAME_MAX = 12  # more does not fit the strip header


def channel_label(name, settings=None):
    """The user's own name for a channel, or its built-in one."""
    key = CHANNEL_NAME_KEYS.get(name)
    if key is None:
        return name
    custom = str((settings or app_settings()).value(key, "") or "").strip()
    return custom[:CHANNEL_NAME_MAX] or name


# Themes. Every colour in this file is written for the dark theme. A theme
# is a translation of those colours, applied where they reach Qt: in style
# sheets, in QColor("#rrggbb") and in the drawn icons. The default theme
# translates nothing.
DEFAULT_THEME = {
    "name": "Dark", "light": False, "accent": "", "base": "", "channels": {},
}
# accent: replaces the hue of the dark theme's bright blues (highlights, the
#   selected tab, checkboxes).
# base: replaces the hue of its greys and backgrounds, and caps how coloured
#   they may be: a nearly grey base gives neutral greys. Without a base they
#   follow the accent, as they did before there was one.
# channels: the colour of a mixer channel (a key of STRIP_COLORS).
# The themes after FaderDeck take their colours from popular programs and
# games; their names describe the look, so they do not suggest any tie to
# those brands.
BUILTIN_THEMES = {
    "Dark": {},
    "Light": {"light": True},
    # The logo's blue-to-purple gradient, spread over the four channels.
    "FaderDeck": {
        "accent": "#5a7dff",
        "channels": {
            "Mic": "#2aa8ff",
            "Game": "#4a90ff",
            "Chat": "#6b75ff",
            "Media": "#8a5cff",
        },
    },
    # Discord: blurple on neutral grey, with its status colours.
    "Blurple": {
        "accent": "#5865f2", "base": "#1e1f22",
        "channels": {"Mic": "#23a55a", "Game": "#f0b232", "Chat": "#5865f2", "Media": "#eb459e"},
    },
    # Twitch: purple on near-black.
    "Live Purple": {
        "accent": "#9146ff", "base": "#18181b",
        "channels": {"Mic": "#bf94ff", "Game": "#9146ff", "Chat": "#00e6a0", "Media": "#ff5c5c"},
    },
    # YouTube: red, white and link blue on black.
    "Broadcast Red": {
        "accent": "#ff0033", "base": "#0f0f0f",
        "channels": {"Mic": "#ff0033", "Game": "#3ea6ff", "Chat": "#f1f1f1", "Media": "#ff8a80"},
    },
    # Steam: light blue and store green on navy.
    "Storefront": {
        "accent": "#66c0f4", "base": "#1b2838",
        "channels": {"Mic": "#66c0f4", "Game": "#a4d007", "Chat": "#c7d5e0", "Media": "#e5b143"},
    },
    # Playnite's default theme: cyan glyphs on deep navy, orange notices.
    "Library": {
        "accent": "#55cdff", "base": "#0d1225",
        "channels": {"Mic": "#55cdff", "Game": "#5b8def", "Chat": "#a3b4ff", "Media": "#ffa500"},
    },
    # Kik: a light theme in its green, with its blue.
    "Lime Chat": {
        "light": True, "accent": "#5dcd11",
        "channels": {"Mic": "#4fb80f", "Game": "#ff8a1a", "Chat": "#1fa8e8", "Media": "#a855f7"},
    },
    # Cyberpunk 2077: yellow, hot pink and cyan on black.
    "Neon City": {
        "accent": "#00f0ff", "base": "#0b0b12",
        "channels": {"Mic": "#fcee0a", "Game": "#ff2a6d", "Chat": "#00f0ff", "Media": "#b967ff"},
    },
    # League of Legends: gold and teal on deep blue.
    "Hextech": {
        "accent": "#0ac8b9", "base": "#010a13",
        "channels": {"Mic": "#c8aa6e", "Game": "#0ac8b9", "Chat": "#cdbe91", "Media": "#f0e6d2"},
    },
    # Valorant: red and cream on dark navy.
    "Tactical": {
        "accent": "#ff4655", "base": "#0f1923",
        "channels": {"Mic": "#ff4655", "Game": "#ece8e1", "Chat": "#3ddcc6", "Media": "#f2b134"},
    },
    # Minecraft: grass, earth, water and gold on dark stone.
    "Overworld": {
        "accent": "#7cbd3c", "base": "#25221d",
        "channels": {"Mic": "#7cbd3c", "Game": "#b07a45", "Chat": "#4aa3df", "Media": "#e0c25a"},
    },
    # Overwatch: orange and hero blue on slate.
    "Payload": {
        "accent": "#f99e1a", "base": "#182233",
        "channels": {"Mic": "#f99e1a", "Game": "#218ffe", "Chat": "#e8eef5", "Media": "#3fd1c6"},
    },
}
CUSTOM_THEME = "Custom"
BLUE_HUES = (0.52, 0.66)
NEUTRAL_SATURATION = 0.45  # below: a grey or background; above: a highlight
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_PlainColor = QColor
_plain_set_style_sheet = QWidget.setStyleSheet
_theme = dict(DEFAULT_THEME)
_color_cache = {}


def clean_theme(value, name=None):
    """A complete theme from stored or typed data; bad parts are dropped."""
    value = value if isinstance(value, dict) else {}

    def colour(text):
        text = str(text or "").lower()
        return text if _HEX_COLOR.fullmatch(text) else ""

    channels = value.get("channels")
    channels = channels if isinstance(channels, dict) else {}
    return {
        "name": str(name or value.get("name") or DEFAULT_THEME["name"])[:40],
        "light": value.get("light") is True,
        "accent": colour(value.get("accent")),
        "base": colour(value.get("base")),
        "channels": {
            channel: colour(channels[channel])
            for channel in STRIP_COLORS
            if colour(channels.get(channel))
        },
    }


# Lightness in the dark theme -> lightness in the light theme. It always
# falls, so a pair such as white text on a blue button keeps its contrast.
# The ends are pulled in (a soft grey background, not white), and the middle
# is flat, so the channel colours (0.5 to 0.77) stay vivid at 0.36 to 0.47,
# dark enough to read on a light background, instead of turning dark as
# they would with plain inversion.
LIGHT_LIGHTNESS = (
    (0.00, 0.96),  # window backgrounds
    (0.25, 0.80),  # borders, hover backgrounds
    (0.40, 0.50),
    (0.75, 0.40),  # accents and grey secondary text
    (0.85, 0.22),
    (1.00, 0.10),  # pale text
)


def light_lightness(lightness):
    """Lightness (0-1) in the light theme of a colour from the dark theme."""
    for (x0, y0), (x1, y1) in zip(LIGHT_LIGHTNESS, LIGHT_LIGHTNESS[1:]):
        if lightness <= x1:
            return y0 + (y1 - y0) * (lightness - x0) / (x1 - x0)
    return LIGHT_LIGHTNESS[-1][1]


def theme_color(code, theme=DEFAULT_THEME):
    """Translate one "#rrggbb" colour of the dark theme."""
    code = code.lower()
    hue, saturation, lightness, _alpha = _PlainColor(code).getHslF()
    changed = False
    for channel, picked in theme["channels"].items():
        defaults = STRIP_COLORS[channel]
        if code == defaults["accent"]:
            return picked  # exactly what the user chose, in any theme
        if code in (defaults["border"], defaults["header"]):
            picked_hue, picked_saturation, _l, _a = _PlainColor(picked).getHslF()
            hue = picked_hue
            saturation = min(saturation, picked_saturation)
            changed = True
            break
    else:
        if BLUE_HUES[0] <= hue <= BLUE_HUES[1]:
            # The dark theme's greys and backgrounds are faintly blue; its
            # highlights are strongly blue.
            neutral = saturation < NEUTRAL_SATURATION
            if neutral and theme.get("base"):
                base_hue, base_saturation, _l, _a = _PlainColor(theme["base"]).getHslF()
                hue = max(base_hue, 0.0)
                saturation = min(saturation, base_saturation)
                changed = True
            elif theme["accent"]:
                hue = _PlainColor(theme["accent"]).getHslF()[0]
                changed = True
    if theme["light"]:
        lightness = min(1.0, max(0.0, light_lightness(lightness)))
        changed = True
    if not changed:
        return code
    return _PlainColor.fromHslF(max(hue, 0.0), saturation, lightness).name()


def translate_colors(text):
    """The colours in a style sheet or drawing, in the current theme."""

    def translate(match):
        code = match.group(0)
        if code not in _color_cache:
            _color_cache[code] = theme_color(code, _theme)
        return _color_cache[code]

    return _HEX_COLOR.sub(translate, text)


class QColor(_PlainColor):
    """QColor that reads "#rrggbb" as a colour of the dark theme."""

    def __init__(self, *args):
        if len(args) == 1 and isinstance(args[0], str):
            args = (translate_colors(args[0]),)
        super().__init__(*args)


def _set_style_sheet(widget, text):
    # Kept on the widget so apply_theme can translate it again.
    widget.setProperty("themeSource", text)
    _plain_set_style_sheet(widget, translate_colors(text))


# shortcut: patches Qt for the whole program instead of a styled() helper at
# each of the 65 call sites; switch to the helper if a widget ever needs a
# style sheet that the theme must not translate.
QWidget.setStyleSheet = _set_style_sheet


def set_mono_icon(widget, name, size):
    """Show a drawn icon on a button or label; follows theme changes."""
    widget.setProperty("themeIcon", f"{name}|{size}")
    icon = mono_icon(name, size)
    if isinstance(widget, QLabel):
        widget.setPixmap(icon.pixmap(size, size))
    else:
        widget.setIcon(icon)


def apply_theme(theme):
    """Switch to a theme now, restyling every widget that exists."""
    _theme.clear()
    _theme.update(clean_theme(theme))
    _color_cache.clear()
    if QApplication.instance() is None:
        return
    for widget in QApplication.allWidgets():
        source = widget.property("themeSource")
        if source:
            _plain_set_style_sheet(widget, translate_colors(source))
        icon = widget.property("themeIcon")
        if icon:
            name, size = icon.split("|")
            set_mono_icon(widget, name, int(size))
        widget.update()


def stored_dict(settings, key):
    """A dict saved as JSON under a settings key; {} if missing or broken."""
    try:
        value = json.loads(settings.value(key, "") or "null")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def store_dict(settings, key, value):
    settings.setValue(key, json.dumps(value, sort_keys=True))
    settings.sync()


def theme_settings(settings):
    """The stored theme; anything unreadable is the default."""
    return clean_theme(stored_dict(settings, "theme"))


def saved_themes(settings):
    """The user's own themes, by name."""
    stored = stored_dict(settings, "themes")
    return {
        str(name)[:40]: clean_theme(value, name)
        for name, value in stored.items()
        if str(name).strip() and name not in BUILTIN_THEMES
    }


class ColorButton(QPushButton):
    """A swatch that opens a colour picker. color is "" until one is chosen."""

    changed = Signal()

    def __init__(self, default):
        super().__init__()
        self.default = default
        self.color = ""
        self.setFixedSize(64, 24)
        self.clicked.connect(self.pick)
        self.set_color("")

    def set_color(self, color):
        self.color = color
        # Not translated: the swatch shows the colour itself.
        _plain_set_style_sheet(
            self,
            f"QPushButton {{ background: {color or self.default}; "
            "border: 1px solid #8ba0b5; border-radius: 4px; }",
        )

    def pick(self):
        chosen = QColorDialog.getColor(
            _PlainColor(self.color or self.default), self, "Choose a colour"
        )
        if chosen.isValid():
            self.set_color(chosen.name())
            self.changed.emit()


# Updates. FaderDeck asks GitHub for its latest release. An update is that
# release's installer, checked against the SHA-256 that GitHub publishes for
# it before it runs.
APP_VERSION = "1.14.0"
UPDATE_URL = (
    "https://api.github.com/repos/GuyliandeJong/FaderDeck/releases/latest"
)
INSTALLER_ASSET = "FaderDeck-Setup.exe"
INSTALLER_OPTIONS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART")

Update = namedtuple("Update", "version url size sha256 page")


def version_tuple(text):
    """(1, 6, 0) for "v1.6.0"; () when the text is not a version."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(text or "").strip())
    if not match:
        return ()
    return tuple(int(part or 0) for part in match.groups())


def available_update(release, current=APP_VERSION):
    """The installer of a release newer than `current`, or None.

    `release` is GitHub's answer for the latest release. Without an
    installer, or without a SHA-256 to check it against, there is no update.
    """
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    version = version_tuple(release.get("tag_name"))
    if not version or version <= version_tuple(current):
        return None
    for asset in release.get("assets") or ():
        if not isinstance(asset, dict) or asset.get("name") != INSTALLER_ASSET:
            continue
        url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "").lower()
        if (
            urlsplit(url).scheme != "https"
            or urlsplit(url).hostname != "github.com"
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            return None
        return Update(
            ".".join(str(part) for part in version),
            url,
            int(asset.get("size") or 0),
            digest.split(":", 1)[1],
            str(release.get("html_url") or ""),
        )
    return None


def _open_url(url, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"FaderDeck/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_latest_release():
    with _open_url(UPDATE_URL, 10) as response:
        return json.loads(response.read().decode("utf-8"))


def installer_environment(environment=None):
    """The environment to start the installer with.

    A one-file PyInstaller program records its unpacked folder in its
    environment. The installer, and the FaderDeck it starts, would inherit
    that, and the new FaderDeck would look for its files in the folder this
    one deletes when it quits ("Failed to load Python DLL").
    """
    environment = dict(os.environ if environment is None else environment)
    for key in list(environment):
        if key.upper().startswith("_PYI_") or key.upper() == "_MEIPASS2":
            del environment[key]
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def remove_old_downloads():
    """Delete installers left from earlier updates."""
    folder = tempfile.gettempdir()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.startswith("faderdeck-update-"):
            shutil.rmtree(os.path.join(folder, name), ignore_errors=True)


def download_update(update, progress=lambda done, total: True):
    """Download the installer and check it. Returns its path.

    `progress` is called as the file comes in; returning False stops it.
    """
    folder = tempfile.mkdtemp(prefix="faderdeck-update-")
    path = os.path.join(folder, INSTALLER_ASSET)
    digest = hashlib.sha256()
    done = 0
    try:
        with _open_url(update.url, 30) as response, open(path, "wb") as handle:
            while chunk := response.read(256 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if not progress(done, update.size):
                    raise InterruptedError("The download was cancelled.")
        if digest.hexdigest() != update.sha256:
            raise ValueError(
                "The download does not match the release, so it was not "
                "installed. Try again later."
            )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return path


class UpdateChecker(QObject):
    """Checks for and downloads updates on a background thread."""

    found = Signal(object)  # Update
    latest = Signal()
    failed = Signal(str)
    progressed = Signal(int, int)
    downloaded = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.cancelled = False

    def _run(self, work):
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                work()
            except Exception as e:
                log.warning(f"Update failed: {type(e).__name__}: {e}")
                self.failed.emit(str(e) or type(e).__name__)
            finally:
                self.busy = False

        threading.Thread(target=run, name="FaderDeckUpdate", daemon=True).start()

    def check(self):
        def work():
            remove_old_downloads()
            update = available_update(fetch_latest_release())
            if update is None:
                self.latest.emit()
            else:
                log.info(f"Update available: {update.version}")
                self.found.emit(update)

        self._run(work)

    def download(self, update):
        self.cancelled = False

        def progress(done, total):
            self.progressed.emit(done, total)
            return not self.cancelled

        self._run(lambda: self.downloaded.emit(download_update(update, progress)))


# Mute sounds: two soft notes, falling when the microphone is muted and
# rising when it is unmuted. Each note is a chime: a warm overtone, a natural
# fade and a slight drop onto its pitch, rather than a flat beep. They are
# played through winmm's waveOut, which, unlike winsound, can play on a
# chosen device: the user's headphones rather than something the stream
# captures.
MUTE_SOUND_NOTES = {True: (784, 523), False: (523, 784)}  # Hz, by muted
MUTE_SOUND_SHAPE = {"step_ms": 85, "decay_ms": 110, "drop": 0.02, "overtone": 0.25}
SOUND_RATE = 44100
SOUND_CHECK_SECONDS = 5
_mute_sounds = {}


def chime_samples(
    notes, step_ms=70, decay_ms=60, drop=0.06, overtone=0.12,
    volume=0.35, rate=SOUND_RATE,
):
    """Mono 16-bit samples of the notes, each starting step_ms apart.

    decay_ms: how fast a note fades. drop: how far sharp a note starts
    (0.06 is 6 %). overtone: loudness of the octave above, for warmth.
    """
    step = rate * step_ms // 1000
    tail = rate * decay_ms * 6 // 1000  # until about -50 dB
    attack = max(1, rate * 3 // 1000)
    mix = [0.0] * (step * (len(notes) - 1) + tail)
    for index, frequency in enumerate(notes):
        start = index * step
        phase = 0.0
        for i in range(tail):
            seconds = i / rate
            pitch = frequency * (1 + drop * math.exp(-seconds / 0.015))
            phase += 2 * math.pi * pitch / rate
            envelope = min(1.0, i / attack) * math.exp(-seconds * 1000 / decay_ms)
            mix[start + i] += envelope * (
                math.sin(phase) + overtone * math.sin(2 * phase)
            )
    peak = max(abs(value) for value in mix) or 1.0
    return array.array(
        "h", (int(32767 * volume * value / peak) for value in mix)
    ).tobytes()


WAVE_MAPPER = 0xFFFFFFFF  # waveOut's id for the Windows default device
WHDR_DONE = 0x00000001


class _WaveFormat(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.wintypes.WORD),
        ("nChannels", ctypes.wintypes.WORD),
        ("nSamplesPerSec", ctypes.wintypes.DWORD),
        ("nAvgBytesPerSec", ctypes.wintypes.DWORD),
        ("nBlockAlign", ctypes.wintypes.WORD),
        ("wBitsPerSample", ctypes.wintypes.WORD),
        ("cbSize", ctypes.wintypes.WORD),
    ]


class _WaveHeader(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.wintypes.DWORD),
        ("dwBytesRecorded", ctypes.wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("dwLoops", ctypes.wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


class _WaveOutCaps(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.wintypes.WORD),
        ("wPid", ctypes.wintypes.WORD),
        ("vDriverVersion", ctypes.c_uint),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", ctypes.wintypes.DWORD),
        ("wChannels", ctypes.wintypes.WORD),
        ("wReserved1", ctypes.wintypes.WORD),
        ("dwSupport", ctypes.wintypes.DWORD),
    ]


def _winmm():
    winmm = ctypes.WinDLL("winmm")
    handle = ctypes.c_void_p
    for name, argtypes in (
        ("waveOutGetDevCapsW", (ctypes.c_size_t, ctypes.POINTER(_WaveOutCaps), ctypes.c_uint)),
        ("waveOutOpen", (ctypes.POINTER(handle), ctypes.c_uint, ctypes.POINTER(_WaveFormat),
                         ctypes.c_size_t, ctypes.c_size_t, ctypes.wintypes.DWORD)),
        ("waveOutPrepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveOutWrite", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveOutUnprepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveOutClose", (handle,)),
    ):
        function = getattr(winmm, name)
        function.argtypes = argtypes
        function.restype = ctypes.c_uint
    winmm.waveOutGetNumDevs.restype = ctypes.c_uint
    return winmm


def sound_devices():
    """Names of the devices Windows can play a sound on.

    waveOut keeps only the first 31 characters of a name.
    """
    winmm = _winmm()
    names = []
    for index in range(winmm.waveOutGetNumDevs()):
        caps = _WaveOutCaps()
        if winmm.waveOutGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def wave_header(data):
    """A buffer holding the samples, and a waveOut header pointing at it.

    Keep the buffer alive until the sound has played.
    """
    buffer = ctypes.create_string_buffer(data, len(data))
    # The raw address: a c_char_p here would point at a copy, and the
    # device would play that instead (silence).
    return buffer, _WaveHeader(ctypes.addressof(buffer), len(data))


def play_samples(data, device=""):
    """Play mono 16-bit samples on a device, by name, without waiting.

    An empty or unknown name plays on the Windows default device.
    """

    def run():
        winmm = _winmm()
        names = sound_devices()
        device_id = names.index(device) if device in names else WAVE_MAPPER
        sound_format = _WaveFormat(1, 1, SOUND_RATE, SOUND_RATE * 2, 2, 16, 0)
        handle = ctypes.c_void_p()
        if winmm.waveOutOpen(ctypes.byref(handle), device_id,
                             ctypes.byref(sound_format), 0, 0, 0):
            log.debug(f"Could not open {device or 'the default device'} for a sound")
            return
        buffer, header = wave_header(data)
        size = ctypes.sizeof(header)
        try:
            winmm.waveOutPrepareHeader(handle, ctypes.byref(header), size)
            winmm.waveOutWrite(handle, ctypes.byref(header), size)
            deadline = time.monotonic() + 5
            while not header.dwFlags & WHDR_DONE and time.monotonic() < deadline:
                time.sleep(0.02)
            winmm.waveOutUnprepareHeader(handle, ctypes.byref(header), size)
        finally:
            winmm.waveOutClose(handle)

    def guarded():
        try:
            run()
        except Exception as e:
            log.debug(f"Could not play a sound: {e}")

    threading.Thread(target=guarded, name="FaderDeckSound", daemon=True).start()


class _WaveInCaps(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.wintypes.WORD),
        ("wPid", ctypes.wintypes.WORD),
        ("vDriverVersion", ctypes.c_uint),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", ctypes.wintypes.DWORD),
        ("wChannels", ctypes.wintypes.WORD),
        ("wReserved1", ctypes.wintypes.WORD),
    ]


def _winmm_in():
    winmm = ctypes.WinDLL("winmm")
    handle = ctypes.c_void_p
    for name, argtypes in (
        ("waveInGetDevCapsW", (ctypes.c_size_t, ctypes.POINTER(_WaveInCaps), ctypes.c_uint)),
        ("waveInOpen", (ctypes.POINTER(handle), ctypes.c_uint, ctypes.POINTER(_WaveFormat),
                        ctypes.c_size_t, ctypes.c_size_t, ctypes.wintypes.DWORD)),
        ("waveInPrepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveInAddBuffer", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveInStart", (handle,)),
        ("waveInReset", (handle,)),
        ("waveInUnprepareHeader", (handle, ctypes.POINTER(_WaveHeader), ctypes.c_uint)),
        ("waveInClose", (handle,)),
    ):
        function = getattr(winmm, name)
        function.argtypes = argtypes
        function.restype = ctypes.c_uint
    winmm.waveInGetNumDevs.restype = ctypes.c_uint
    return winmm


def recording_devices():
    """Names of the devices Windows can record from (cut at 31 characters)."""
    winmm = _winmm_in()
    names = []
    for index in range(winmm.waveInGetNumDevs()):
        caps = _WaveInCaps()
        if winmm.waveInGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def sound_check_device(names, output="B1"):
    """A recording device that carries the processed microphone.

    "VoiceMeeter Out B1" first. People rename these in Windows ("Stream
    Microphone"), so next any VoiceMeeter device that is not one of the
    hardware outputs A1-A5, preferring one that is called a microphone.
    The raw microphone itself would skip the processing.
    """
    wanted = f"out {output}".casefold()
    for name in names:
        if wanted in name.casefold():
            return name
    virtual = [
        name for name in names
        if "vb-audio" in name.casefold()
        and not re.search(r"out a\d", name.casefold())
    ]
    for name in virtual:
        if name.casefold().startswith("microphone"):
            return name
    return virtual[0] if virtual else ""


def record_samples(device, seconds):
    """Record mono 16-bit samples from a device, by name. Waits: call it
    off the GUI thread. Raises OSError when the device cannot be opened."""
    winmm = _winmm_in()
    names = recording_devices()
    if device not in names:
        raise OSError(f"{device or 'No device'} is not connected")
    sound_format = _WaveFormat(1, 1, SOUND_RATE, SOUND_RATE * 2, 2, 16, 0)
    handle = ctypes.c_void_p()
    if winmm.waveInOpen(ctypes.byref(handle), names.index(device),
                        ctypes.byref(sound_format), 0, 0, 0):
        raise OSError(f"{device} could not be opened for recording")
    buffer, header = wave_header(bytes(SOUND_RATE * 2 * seconds))
    size = ctypes.sizeof(header)
    try:
        winmm.waveInPrepareHeader(handle, ctypes.byref(header), size)
        winmm.waveInAddBuffer(handle, ctypes.byref(header), size)
        winmm.waveInStart(handle)
        deadline = time.monotonic() + seconds + 3
        while not header.dwFlags & WHDR_DONE and time.monotonic() < deadline:
            time.sleep(0.05)
        winmm.waveInReset(handle)
        winmm.waveInUnprepareHeader(handle, ctypes.byref(header), size)
        return ctypes.string_at(buffer, header.dwBytesRecorded)
    finally:
        winmm.waveInClose(handle)


def sound_check(device, seconds, play_on):
    """Record the processed microphone, then play it back. Returns a short
    report for the settings window."""
    samples = record_samples(device, seconds)
    if not samples:
        return "Nothing was recorded. Is the microphone routed to that output?"
    play_samples(samples, play_on)
    return "Playing back what voice chat and your stream hear."


def play_mute_sound(muted, device=""):
    if muted not in _mute_sounds:
        _mute_sounds[muted] = chime_samples(
            MUTE_SOUND_NOTES[muted], **MUTE_SOUND_SHAPE
        )
    play_samples(_mute_sounds[muted], device)


# Global hotkeys: they work while FaderDeck is in the background, through
# Win32 RegisterHotKey. A registered combination is taken away from every
# other program for as long as FaderDeck runs.
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
HOTKEY_MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "meta": 0x0008}
HOTKEY_MIC_MUTE = 1  # id passed to RegisterHotKey
DEFAULT_MIC_MUTE_HOTKEY = "Ctrl+Shift+M"
# Mute hotkey of each strip: (RegisterHotKey id, settings key, default).
MUTE_HOTKEYS = {
    "Mic": (HOTKEY_MIC_MUTE, "hotkey_mic_mute", DEFAULT_MIC_MUTE_HOTKEY),
    "Game": (2, "hotkey_game_mute", ""),
    "Chat": (3, "hotkey_chat_mute", ""),
    "Media": (4, "hotkey_media_mute", ""),
}

# One press of a volume hotkey; holding the keys repeats it.
HOTKEY_GAIN_STEP_DB = 1.0

# Every global hotkey: its RegisterHotKey id, its settings key, how it is
# listed in the settings window, and what it does (see MainWindow.on_hotkey).
HotkeyAction = namedtuple(
    "HotkeyAction", "id key group label default repeats action argument"
)


def _hotkey_actions():
    names = {"Mic": "microphone", "Game": "Game", "Chat": "Chat", "Media": "Media"}
    actions = []
    for strip, (hotkey_id, key, default) in MUTE_HOTKEYS.items():
        actions.append(HotkeyAction(
            hotkey_id, key, "MUTE", f"Mute {names[strip]}", default,
            False, "mute", strip,
        ))
    for index, strip in enumerate(MUTE_HOTKEYS):
        lower = strip.lower()
        title = names[strip][0].upper() + names[strip][1:]
        actions.append(HotkeyAction(
            11 + index * 2, f"hotkey_{lower}_up", "VOLUME",
            f"{title} louder", "", True, "gain", (strip, HOTKEY_GAIN_STEP_DB),
        ))
        actions.append(HotkeyAction(
            12 + index * 2, f"hotkey_{lower}_down", "VOLUME",
            f"{title} quieter", "", True, "gain", (strip, -HOTKEY_GAIN_STEP_DB),
        ))
    # Push to talk and hold to mute last as long as the keys are held.
    for hotkey_id, key, label, action in (
        (21, "hotkey_mic_push_to_talk", "Push to talk", "push_to_talk"),
        (22, "hotkey_mic_hold_mute", "Hold to mute", "hold_mute"),
        (24, "hotkey_mic_stream_mute", "Mute stream", "stream_mute"),
    ):
        actions.append(HotkeyAction(
            hotkey_id, key, "MICROPHONE", label, "", False, action, "Mic",
        ))
    actions.append(HotkeyAction(
        31, "hotkey_profile_next", "SETUP PROFILES",
        "Next profile", "", False, "profile", 1,
    ))
    actions.append(HotkeyAction(
        32, "hotkey_profile_previous", "SETUP PROFILES",
        "Previous profile", "", False, "profile", -1,
    ))
    return tuple(actions)


HOTKEYS = _hotkey_actions()


def parse_hotkey(text):
    """Return (modifiers, virtual key) for text such as "Ctrl+Shift+M".

    Returns None when it cannot be a global hotkey: it needs at least one
    modifier, and the key must be a letter, a digit or F1-F24.
    """
    parts = [part.strip() for part in (text or "").split("+") if part.strip()]
    if len(parts) < 2:
        return None

    modifiers = 0
    for name in parts[:-1]:
        flag = HOTKEY_MODIFIERS.get(name.casefold())
        if flag is None:
            return None
        modifiers |= flag

    key = parts[-1].upper()
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key)
    if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", key):
        return modifiers, 0x6F + int(key[1:])  # VK_F1 is 0x70
    return None


# Only one FaderDeck runs at a time: a second copy could not register the
# hotkey and would fight the first over the mixer. Starting it again asks the
# running one to show its window, which may be hidden in the tray.
# The packaged program and a run from source use different names, so the
# installed FaderDeck does not block development. installer/faderdeck.iss
# checks the packaged name to see whether FaderDeck runs; change both.
SINGLE_INSTANCE_NAME = (
    "FaderDeck.SingleInstance"
    if getattr(sys, "frozen", False)
    else "FaderDeck.SingleInstance.Source"
)
ERROR_ALREADY_EXISTS = 183
HWND_BROADCAST = 0xFFFF


def show_window_message(name=SINGLE_INSTANCE_NAME):
    """Id of the Windows message that asks a running FaderDeck to show up."""
    return ctypes.windll.user32.RegisterWindowMessageW(f"{name}.Show")


def acquire_single_instance(name=SINGLE_INSTANCE_NAME):
    """Claim the right to be the running FaderDeck.

    Returns a handle to keep for as long as the program runs, or None when
    another FaderDeck already holds it.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR
    )
    kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Could not ask Windows; running twice beats not running at all.
        return -1
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def ask_running_instance_to_show(name=SINGLE_INSTANCE_NAME):
    ctypes.windll.user32.PostMessageW(
        HWND_BROADCAST, show_window_message(name), 0, 0
    )


def quit_message(name=SINGLE_INSTANCE_NAME):
    """Id of the Windows message that asks a running FaderDeck to quit."""
    return ctypes.windll.user32.RegisterWindowMessageW(f"{name}.Quit")


def ask_running_instance_to_quit(name=SINGLE_INSTANCE_NAME):
    """Used by `FaderDeck.exe --quit`, for scripts such as the build.

    The running program quits the way its tray menu's Quit does, so it logs
    out of VoiceMeeter. Stopping the process by force cannot do that and
    leaves a stale client behind in VoiceMeeter.
    """
    ctypes.windll.user32.PostMessageW(
        HWND_BROADCAST, quit_message(name), 0, 0
    )


# Local API: lets other programs on this PC (a Stream Deck plugin, an OBS
# script, curl) control FaderDeck over HTTP. Off unless switched on in the
# settings window.
API_DEFAULT_PORT = 8765
API_TOKEN_HEADER = "X-FaderDeck-Token"


class ApiCall:
    """One request, handed from the server thread to the GUI thread."""

    def __init__(self, method, parts, params):
        self.method = method
        self.parts = parts
        self.params = params
        self.future = concurrent.futures.Future()


class ApiServer(ThreadingHTTPServer):
    """HTTP server that insists on having its port to itself.

    The standard server sets SO_REUSEADDR, which on Windows lets a second
    program listen on the same port and take the requests. The token would
    then be sent to that program.
    """

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class LocalApi(QObject):
    """A small HTTP server that is reachable from this computer only.

    It listens on 127.0.0.1, so nothing on the network can connect. Every
    request needs the token from the settings window. Requests coming from a
    web page (they carry an Origin header) and requests addressed to any
    other host name are refused, so a site open in a browser cannot reach
    the mixer either.

    Requests arrive on server threads. They are passed to the GUI thread
    through call_requested and wait there for the answer; nothing in this
    class touches a widget or VoiceMeeter.
    """

    call_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = None
        self.thread = None
        self.token = ""
        self.port = 0

    def start(self, port, token):
        """Start listening. Raises OSError when the port cannot be used."""
        self.stop()
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FaderDeck"

            def log_message(self, *args):
                pass

            def do_GET(self):
                api.serve(self, "GET")

            def do_POST(self):
                api.serve(self, "POST")

        self.server = ApiServer(("127.0.0.1", int(port)), Handler)
        self.port = self.server.server_address[1]
        self.token = token
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.1},  # stop() then returns quickly
            name="FaderDeck-LocalApi",
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        server, thread = self.server, self.thread
        self.server = self.thread = None
        self.port = 0
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=1.0)

    def serve(self, handler, method):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            if length:
                handler.rfile.read(min(length, 65536))
            status, body = self.answer(handler, method)
        except Exception as e:
            log.error(f"Local API request failed: {type(e).__name__}: {e}")
            status, body = 500, {"error": "Internal error."}
        data = json.dumps(body).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)

    def answer(self, handler, method):
        url = urlsplit(handler.path)
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}

        if handler.headers.get("Origin"):
            return 403, {"error": "Requests from web pages are not accepted."}
        host = (handler.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if host not in ("127.0.0.1", "localhost"):
            return 403, {"error": "Only 127.0.0.1 and localhost are accepted."}

        supplied = (
            handler.headers.get(API_TOKEN_HEADER)
            or params.pop("token", "")
        )
        if not self.token or not hmac.compare_digest(
            supplied.encode("utf-8"), self.token.encode("utf-8")
        ):
            return 401, {"error": "Missing or wrong token."}

        parts = [unquote(part) for part in url.path.split("/") if part]
        if not parts or parts[0] != "api":
            return 404, {"error": "Unknown address."}

        call = ApiCall(method, parts[1:], params)
        self.call_requested.emit(call)
        try:
            return call.future.result(timeout=3.0)
        except Exception:
            return 503, {"error": "FaderDeck did not answer in time."}


# The phone and tablet remote: a web page that FaderDeck serves on the home
# network, separate from the local API above, which stays on 127.0.0.1. A
# device pairs once with a short code shown in Settings and then sends its
# own token with every request. Only the hash of a token is kept.
REMOTE_DEFAULT_PORT = 8766
REMOTE_PAGE = "remote.html"
REMOTE_PAIR_SECONDS = 120
REMOTE_PAIR_TRIES = 5


def lan_address():
    """This PC's address on the home network, or an empty string."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # sends nothing
            return probe.getsockname()[0]
    except OSError:
        return ""


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def remote_manifest():
    return json.dumps({
        "name": "FaderDeck",
        "short_name": "FaderDeck",
        "start_url": "/remote",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "icons": [
            {"src": "/remote/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/remote/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }).encode("utf-8")


def logo_png(size):
    """The logo as PNG bytes. Call on the GUI thread."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(LOGO_SVG.encode("utf-8"))).render(
        painter, QRectF(0, 0, size, size)
    )
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


class PhoneRemote(QObject):
    """Serves the remote page and its requests to devices on the home network.

    Like LocalApi, requests are answered on the GUI thread through
    call_requested; a newly paired device is announced through paired.
    """

    call_requested = Signal(object)
    paired = Signal(str)  # the hash of a new device token

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files  # path -> (content type, bytes)
        self.server = None
        self.thread = None
        self.port = 0
        self.devices = set()
        self.lock = threading.Lock()
        self.code = ""
        self.code_until = 0.0
        self.tries = 0

    def start(self, port, devices, host="0.0.0.0"):
        """Start listening on every network. Raises OSError on a busy port."""
        self.stop()
        remote = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FaderDeck"

            def log_message(self, *args):
                pass

            def do_GET(self):
                remote.serve(self, "GET")

            def do_POST(self):
                remote.serve(self, "POST")

        self.server = ApiServer((host, int(port)), Handler)
        self.port = self.server.server_address[1]
        with self.lock:
            self.devices = set(devices)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="FaderDeck-PhoneRemote",
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        server, thread = self.server, self.thread
        self.server = self.thread = None
        self.port = 0
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=1.0)

    def set_devices(self, devices):
        with self.lock:
            self.devices = set(devices)

    def new_code(self):
        """A fresh six-digit pairing code, valid for a short while."""
        with self.lock:
            self.code = f"{secrets.randbelow(10 ** 6):06d}"
            self.code_until = time.monotonic() + REMOTE_PAIR_SECONDS
            self.tries = 0
            return self.code

    def pair(self, code):
        """A new device token for the right code, or None."""
        with self.lock:
            if not self.code or time.monotonic() > self.code_until:
                return None
            self.tries += 1
            right = hmac.compare_digest(str(code).encode(), self.code.encode())
            if not right:
                if self.tries >= REMOTE_PAIR_TRIES:
                    self.code = ""  # too many guesses: ask for a new code
                return None
            self.code = ""  # one device per code
            token = secrets.token_urlsafe(24)
            self.devices.add(token_hash(token))
        self.paired.emit(token_hash(token))
        return token

    def serve(self, handler, method):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            body = handler.rfile.read(min(length, 65536)) if length else b""
            status, content_type, data = self.answer(handler, method, body)
        except Exception as e:
            log.error(f"Phone remote request failed: {type(e).__name__}: {e}")
            status, content_type, data = 500, "application/json", b'{"error": "Internal error."}'
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(data)

    @staticmethod
    def json_answer(status, body):
        return status, "application/json; charset=utf-8", json.dumps(body).encode("utf-8")

    def answer(self, handler, method, body):
        client = ipaddress.ip_address(handler.client_address[0])
        if not (client.is_private or client.is_loopback):
            return self.json_answer(403, {"error": "Only devices on your own network."})
        url = urlsplit(handler.path)
        path = url.path.rstrip("/") or "/"

        if method == "GET" and path in ("/", "/remote") or path in self.files:
            name = "/remote" if path == "/" else path
            if method != "GET" or name not in self.files:
                return self.json_answer(404, {"error": "Unknown address."})
            content_type, data = self.files[name]
            return 200, content_type, data

        # A page on another site must not drive the mixer from this browser.
        origin = handler.headers.get("Origin")
        if origin and urlsplit(origin).netloc != handler.headers.get("Host"):
            return self.json_answer(403, {"error": "Requests from other sites are not accepted."})

        if path == "/remote/pair" and method == "POST":
            try:
                code = str(json.loads(body or b"{}").get("code", "")).strip()
            except (ValueError, AttributeError):
                code = ""
            token = self.pair(code)
            if token is None:
                return self.json_answer(403, {
                    "error": "That code is wrong or has run out. Press \"Pair a "
                    "device\" in FaderDeck for a new one."})
            log.info(f"Phone remote: paired a device at {client}")
            return self.json_answer(200, {"token": token})

        supplied = handler.headers.get(API_TOKEN_HEADER, "")
        with self.lock:
            known = bool(supplied) and token_hash(supplied) in self.devices
        if not known:
            return self.json_answer(401, {"error": "This device is not paired."})

        parts = [unquote(part) for part in path.split("/") if part]
        if parts[:2] != ["remote", "api"]:
            return self.json_answer(404, {"error": "Unknown address."})
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}
        call = ApiCall(method, parts[2:], params)
        self.call_requested.emit(call)
        try:
            status, answer = call.future.result(timeout=3.0)
        except Exception:
            status, answer = 503, {"error": "FaderDeck did not answer in time."}
        return self.json_answer(status, answer)


# Windows Firewall blocks phones from reaching the remote until a rule
# allows it, and adding one needs administrator rights. FaderDeck asks Windows
# to run one PowerShell command as administrator (the user sees the usual
# prompt) that allows exactly this program, on the remote's port, on private
# networks only. Firewall rules are read through PowerShell objects, whose
# names do not change with the Windows language.
FIREWALL_RULE = "FaderDeck phone remote"


def firewall_program():
    """The program Windows sees listening: FaderDeck.exe, or the real Python
    behind a virtual environment when run from source."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return getattr(sys, "_base_executable", None) or sys.executable


def _powershell_text(value):
    return "'" + str(value).replace("'", "''") + "'"


def firewall_rule_command(program, port):
    """PowerShell that replaces FaderDeck's rule with one for this program
    and port, on private networks."""
    name = _powershell_text(FIREWALL_RULE)
    return (
        f"Remove-NetFirewallRule -DisplayName {name} -ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName {name} -Direction Inbound "
        f"-Program {_powershell_text(program)} -Protocol TCP "
        f"-LocalPort {int(port)} -Profile Private -Action Allow -ErrorAction Stop | Out-Null"
    )


def firewall_status_command():
    """PowerShell that prints 'program|port' of FaderDeck's rule, if any."""
    name = _powershell_text(FIREWALL_RULE)
    return (
        f"$r = Get-NetFirewallRule -DisplayName {name} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Allow' } | Select-Object -First 1; "
        "if ($r) { $a = $r | Get-NetFirewallApplicationFilter; "
        "$p = $r | Get-NetFirewallPortFilter; "
        "Write-Output ($a.Program + '|' + $p.LocalPort) }"
    )


def firewall_allows(program, port):
    """True when FaderDeck's rule lets this program in on this port, False
    when not, None when it could not be read. Takes a second: not on the
    GUI thread."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             firewall_status_command()],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = result.stdout.strip()
    if not found:
        return False
    rule_program, _, rule_port = found.rpartition("|")
    return (
        os.path.normcase(os.path.abspath(rule_program))
        == os.path.normcase(os.path.abspath(program))
        and rule_port.strip() == str(int(port))
    )


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.wintypes.LPCWSTR),
        ("lpFile", ctypes.wintypes.LPCWSTR),
        ("lpParameters", ctypes.wintypes.LPCWSTR),
        ("lpDirectory", ctypes.wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.wintypes.LPCWSTR),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


def run_powershell_as_admin(command):
    """Run a PowerShell command as administrator after Windows asks the user.

    Waits for it, so call it off the GUI thread. Returns its exit code, or
    None when the user said no to the prompt.
    """
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS: hand back the process
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = (
        "-NoProfile -NonInteractive -WindowStyle Hidden -Command "
        f"\"{command}; if (-not $?) {{ exit 1 }}\""
    )
    info.nShow = 0  # SW_HIDE
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return None  # declined, or Windows could not ask
    kernel32 = ctypes.windll.kernel32
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = ctypes.wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


class BackgroundJob(QObject):
    """Run a slow function on a thread and hand the result to the GUI thread."""

    finished = Signal(object)

    def start(self, function, *args):
        def run():
            try:
                result = function(*args)
            except Exception as e:
                log.warning(f"{getattr(function, '__name__', 'job')} failed: {e}")
                result = None
            try:
                self.finished.emit(result)
            except RuntimeError:
                pass  # the window that asked has been closed meanwhile

        threading.Thread(target=run, daemon=True).start()


class HotkeyFilter(QAbstractNativeEventFilter):
    """Pass this application's own Windows messages to callbacks: global
    hotkeys, and the request of a second start to show the window."""

    def __init__(self, callback, show_callback=None, quit_callback=None):
        super().__init__()
        self.callback = callback
        self.show_callback = show_callback
        self.quit_callback = quit_callback
        self.show_message = show_window_message()
        self.quit_message = quit_message()
        # The request is broadcast, so every window of this program gets a
        # copy (the tray icon has one too). Act on the main window's only.
        self.window_handle = None

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.callback(int(msg.wParam))
                return True, 0
            if msg.message == self.show_message and self.show_callback:
                if self.window_handle in (None, msg.hWnd):
                    self.show_callback()
                return True, 0
            if msg.message == self.quit_message and self.quit_callback:
                if self.window_handle in (None, msg.hWnd):
                    self.quit_callback()
                return True, 0
        return False, 0


# VoiceMeeter Potato has five hardware inputs (strips 0-4); the microphone
# can be on any of them. Chosen in the settings window, used from the next
# start (see set_mic_strip).
HARDWARE_INPUTS = 5


def set_mic_strip(index):
    """Choose which hardware input is the Mic strip. Call before the window
    is built: the strip, its processing controls and the level worker all
    read STRIPS["Mic"] when they are created."""
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    if not 0 <= index < HARDWARE_INPUTS:
        index = 0
    STRIPS["Mic"] = index

# Hide/unhide scope meaning "every virtual channel".
ALL_CHANNELS = "*"

# Drag and drop of an application between channel columns.
DRAG_MIME = "application/x-faderdeck-application"

# Mic strip: meters sit to the left of the (centered) fader.
MIC_METER_GAP = 47      # pixels between the meters and the fader
MIC_METER_SPACING = 6   # pixels between the two meters

# Mixer layout dimensions — adjust these when fine-tuning the UI.
# The mixer and the lower panels share the window height through a
# draggable splitter, so these are minimums and starting sizes, not fixed sizes.
MIXER_CARD_MIN_HEIGHT = 330
# Compact view: the four strips with fader, meters and MUTE only.
COMPACT_CARD_MIN_HEIGHT = 190
COMPACT_HEADER_HEIGHT = 34
COMPACT_FADER_WIDTH = 44
COMPACT_METER_WIDTH = 12
NORMAL_METER_WIDTH = 28
WINDOW_MIN_SIZE = (820, 680)
WINDOW_DEFAULT_SIZE = (960, 900)
COMPACT_MIN_SIZE = (520, 300)
COMPACT_DEFAULT_SIZE = (580, 380)
DEFAULT_MIXER_PANE_HEIGHT = 655
CHANNEL_HEADER_HEIGHT = 58
CHANNEL_FADER_MIN_HEIGHT = 100
FADER_TO_GAIN_GAP = 5
MIXER_BUTTON_HEIGHT = 28
ROUTING_LABEL_HEIGHT = 14
ROUTING_BUTTON_HEIGHT = 24
APPLICATION_PANEL_HEIGHT = 300
APPLICATION_PANEL_MIN_HEIGHT = 140

# "On" colours of the mixer toggles. A solid red fill is reserved for MUTE,
# the only toggle that silences audio (see the QPushButton:checked rule in
# MainWindow). Every other toggle shows "on" as an outline in its own colour:
# SOLO uses the colour below, MONO and the routing buttons use the strip accent.
TOGGLE_COLORS = {
    "solo": "#f5b83d",
}


def outline_toggle_style(color):
    """Checked style for a toggle that is on but does not silence audio."""
    return (
        f"QPushButton:checked {{ background: #141d27; color: {color}; "
        f"border: 2px solid {color}; font-weight: bold; }}"
    )


# Key under which a mixer profile keeps the mic processing blocks, next to
# its strips.
PROFILE_PROCESSING = "processing"
PROFILE_HOLDS = "Faders, buttons and mic processing."


def profile_states_match(stored, current):
    """True if the mixer (current) is as a stored profile says.

    Only what the stored profile holds is compared, so an older profile
    without mic processing is not "changed" by a processing change. Numbers
    are compared to two decimals: VoiceMeeter hands them back as 32-bit
    floats.
    """

    def same(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return all(key in b and same(value, b[key]) for key, value in a.items())
        if isinstance(a, bool) or isinstance(b, bool):
            return bool(a) == bool(b)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(float(a), 2) == round(float(b), 2)
        return a == b

    return same(stored, current)

# Routing buttons of every strip, and the VoiceMeeter bus behind each one.
# VoiceMeeter Potato's outputs. A1-A5 are hardware outputs: a device you
# hear, such as headphones. B1-B3 are virtual outputs: Windows shows them as
# recording devices ("VoiceMeeter Out B1") that programs such as Discord and
# OBS take their sound from.
ALL_OUTPUTS = ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3")
HARDWARE_OUTPUTS = ALL_OUTPUTS[:5]
VIRTUAL_OUTPUTS = ALL_OUTPUTS[5:]
ROUTE_BUS = {output: bus for bus, output in enumerate(ALL_OUTPUTS)}
OUTPUT_NAME_MAX = 8  # more does not fit a routing button
CLASSIC_OUTPUTS = ("A1", "A2", "A3", "B1", "B2", "B3")  # when the mixer cannot say


def output_device(vm, output):
    """The device chosen in VoiceMeeter for a hardware output, or ""."""
    if output not in HARDWARE_OUTPUTS or vm is None:
        return ""
    try:
        return str(vm.bus[ROUTE_BUS[output]].device.name or "").strip()
    except Exception:
        return ""


def available_outputs(vm):
    """The outputs that do something: hardware outputs with a device, and
    every virtual output (it is there for a program to pick)."""
    if vm is None:
        return list(CLASSIC_OUTPUTS)
    hardware = [output for output in HARDWARE_OUTPUTS if output_device(vm, output)]
    return hardware + list(VIRTUAL_OUTPUTS)


def output_name(output, settings=None):
    """The user's own name for an output, or ""."""
    value = (settings or app_settings()).value(f"output_name_{output}", "")
    return str(value or "").strip()[:OUTPUT_NAME_MAX]


def route_name(vm, output, settings=None):
    """(button text, tooltip) for a routing button.

    "B2" means little unless you know VoiceMeeter. A name given in FaderDeck
    ("Call") comes first, then one given in VoiceMeeter; the code and, for
    a hardware output, its device are in the tooltip.
    """
    hardware = output in HARDWARE_OUTPUTS
    kind = "hardware output" if hardware else "virtual output: a program takes it"
    device = output_device(vm, output)
    detail = f"{kind}, {device}" if device else kind
    name = output_name(output, settings)
    if not name:
        try:
            name = str(vm.bus[ROUTE_BUS[output]].label or "").strip()
        except Exception:
            name = ""
        if len(name) > OUTPUT_NAME_MAX:
            name = name[:OUTPUT_NAME_MAX - 1] + "…"
    if name:
        return name, f"{name} ({output}, {detail})"
    return output, f"{output} ({detail})"


def output_label(output, settings=None):
    """How an output is named in text: its own name, or its code."""
    return output_name(output, settings) or output


# Styles used in more than one place.
SMALL_HEADING_STYLE = "color: #8ba0b5; font-size: 11px; font-weight: bold;"
EYE_BUTTON_STYLE = (
    "QPushButton { background: #18232e; border: 1px solid #314558; "
    "border-radius: 6px; padding: 0 3px; color: #aebdca; "
    "font-size: 11px; font-weight: bold; }"
    "QPushButton:checked { background: #243b52; border-color: #58a6ff; }"
)
HEADER_BUTTON_STYLE = (
    "QPushButton { background: #18232e; border: 1px solid #314558; "
    "border-radius: 6px; padding: 0; }"
    "QPushButton:hover { background: #243b52; }"
    "QPushButton:checked { background: #243b52; border-color: #58a6ff; }"
)

# A theme recolours a channel by its colour values, so no other part of the
# window may use them. These look the same but are one step off.
PANEL_BORDER = "#24566c"
ALERT_BORDER = "#69353d"
COMPRESSOR_MARK = "#35c8fe"

STRIP_COLORS = {
    "Mic": {"accent": "#35c8ff", "border": "#24566b", "header": "#102b38"},
    "Game": {"accent": "#ff626b", "border": "#69353c", "header": "#321c22"},
    "Chat": {"accent": "#a68aff", "border": "#504273", "header": "#241e37"},
    "Media": {"accent": "#24d6a0", "border": "#236450", "header": "#102a24"},
}


class Wordmark(QWidget):
    """The program's name in the header.

    "Fader" is heavy and white; "Deck" is light and carries the logo's
    gradient, so the name reads as a mark and not as a line of text. A
    stylesheet cannot colour text with a gradient, hence the painting.
    """

    WORDS = (("Fader", QFont.Weight.ExtraBold), ("Deck", QFont.Weight.Normal))
    PIXEL_SIZE = 18

    def __init__(self):
        super().__init__()
        self._fonts = []
        width = 0.0
        height = 0.0
        for _text, weight in self.WORDS:
            font = QFont("Segoe UI")
            font.setPixelSize(self.PIXEL_SIZE)
            font.setWeight(weight)
            self._fonts.append(font)
        for (text, _weight), font in zip(self.WORDS, self._fonts):
            metrics = QFontMetricsF(font)
            width += metrics.horizontalAdvance(text)
            height = max(height, metrics.height())
        self.setFixedSize(int(width) + 2, int(height) + 2)
        self.setToolTip("FaderDeck")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        x = 0.0
        last = len(self.WORDS) - 1
        for index, ((text, _weight), font) in enumerate(
            zip(self.WORDS, self._fonts)
        ):
            advance = QFontMetricsF(font).horizontalAdvance(text)
            if index == last:
                # The gradient runs across this word only, and diagonally like
                # the tile's: blue at the top left, purple at the bottom right.
                metrics = QFontMetricsF(font)
                middle = self.height() / 2
                top = middle - metrics.capHeight() / 2
                bottom = middle + metrics.capHeight() / 2
                # A true 45 degree slope, as on the tile: the colour depends
                # on x + y, and the run is long enough to cover the word.
                run = (advance + (bottom - top)) / 2
                gradient = QLinearGradient(x, top, x + run, top + run)
                gradient.setColorAt(0.0, _PlainColor(LOGO_GRADIENT[0]))
                gradient.setColorAt(1.0, _PlainColor(LOGO_GRADIENT[1]))
                painter.setPen(QPen(QBrush(gradient), 1))
            else:
                painter.setPen(QColor("#e6edf3"))
            painter.setFont(font)
            painter.drawText(
                QRectF(x, 0, advance + 1, self.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            x += advance
        painter.end()


class VMEventBridge(QObject):

    """
    Bridges VoiceMeeter's background event thread
    to Qt's main thread.
    """

    event_received = Signal(str)


class VMObserver:
    """Receives VoiceMeeter API events."""

    def __init__(self, bridge):
        self.bridge = bridge

    def on_update(self, event):
        # Mic levels are sampled by StripLevelWorker, so level events are not
        # forwarded to the GUI thread at all. Never read levels here: this
        # runs on VoiceMeeter's own update thread.
        if event != "ldirty":
            self.bridge.event_received.emit(event)


class VUMeter(QProgressBar):

    """Simple vertical VU meter."""

    def __init__(self, label=""):
        super().__init__()
        self._label = label


        self.setOrientation(Qt.Orientation.Vertical)

        # Keep the progress-bar value itself in dBFS. 0 dBFS is the top.
        # The previous build used -60..12 and then normalized the dB value
        # into that range a second time, which made the visual position wrong.
        self.setRange(-60, 0)

        self.setValue(-60)


        self.setTextVisible(False)

        self.setMinimumWidth(NORMAL_METER_WIDTH)
        self.setMaximumWidth(NORMAL_METER_WIDTH)

        # Height is flexible: the Mic meters follow the fader length.
        self.setMinimumHeight(40)


        # Vertical meters should rise from the bottom as the signal increases.
        self.setInvertedAppearance(False)
        self._display_level = float(self.minimum())
        self._target_level = float(self.minimum())
        self._last_animation = time.monotonic()


    def paintEvent(self, event):
        """Draw a bottom-up meter with color thresholds fixed to dB scale."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor("#303a45"), 1))
        painter.setBrush(QColor("#111820"))
        painter.drawRoundedRect(outer, 5, 5)

        inner = outer.adjusted(2, 2, -2, -2)
        span = max(1, self.maximum() - self.minimum())
        fraction = max(0.0, min(1.0, (self.value() - self.minimum()) / span))
        filled_height = inner.height() * fraction
        if filled_height <= 0:
            self._draw_scale(painter, inner)
            painter.end()
            return

        gradient = QLinearGradient(0, inner.bottom(), 0, inner.top())
        # Anchor the warning colors to dBFS values rather than normalized
        # bar height, so 0 dBFS remains the red/clipping threshold.
        def db_position(db):
            return max(0.0, min(1.0, (db - self.minimum()) / span))

        gradient.setColorAt(db_position(-60), QColor("#27c76f"))
        gradient.setColorAt(db_position(-18), QColor("#54db39"))
        gradient.setColorAt(db_position(-10.8), QColor("#a5e52b"))
        gradient.setColorAt(db_position(-6), QColor("#f5df27"))
        gradient.setColorAt(db_position(-2.4), QColor("#ff9637"))
        gradient.setColorAt(db_position(0), QColor("#ff514b"))
        gradient.setColorAt(1.00, QColor("#ff514b"))

        fill = QRectF(
            inner.left(),
            inner.bottom() - filled_height,
            inner.width(),
            filled_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(fill, QBrush(gradient))
        self._draw_scale(painter, inner)
        painter.end()

    def _draw_scale(self, painter, inner):
        """Draw faint dB ticks and the channel letter, visible at silence."""
        span = max(1, self.maximum() - self.minimum())
        painter.setPen(QPen(QColor(255, 255, 255, 46), 1))
        for db in (-48, -36, -24, -12, -6):
            y = inner.bottom() - inner.height() * (db - self.minimum()) / span
            painter.drawLine(
                QPointF(inner.left() + 3, y), QPointF(inner.right() - 3, y)
            )
        # A slim (compact view) meter has no room for the letter.
        if self._label and self.width() >= NORMAL_METER_WIDTH:
            font = painter.font()
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#8ba0b5"))
            painter.drawText(
                QRectF(inner.left(), inner.top() + 2, inner.width(), 14),
                Qt.AlignmentFlag.AlignCenter,
                self._label,
            )


    def set_level(self, level):
        """Set the latest target level from the audio worker."""
        try:
            level = float(level)
        except (TypeError, ValueError):
            level = float(self.minimum())

        minimum = float(self.minimum())

        if level <= -199.0:
            target = minimum
            self.setToolTip("-∞ dB")
        else:
            target = max(minimum, min(0.0, level))
            self.setToolTip(f"{level:.1f} dB")

        self._target_level = target

    def _update_visual_level(self, display):
        """Apply the current animated dB level to the meter widget."""
        minimum = float(self.minimum())
        display = max(minimum, min(0.0, float(display)))
        self._display_level = display

        # The widget range is already dBFS, so do not normalize and then
        # convert back into the progress-bar range. Write the displayed dB
        # directly. paintEvent() converts that dB value to a fill fraction.
        self.setValue(int(round(display)))

    def animate_level(self):
        """Smoothly animate the displayed level toward the latest sample."""
        now = time.monotonic()
        elapsed = min(now - self._last_animation, 0.05)
        self._last_animation = now

        minimum = float(self.minimum())
        display = float(self._display_level)
        target = float(self._target_level)

        # Fast attack so short mic taps are visible immediately without
        # stepping from one 33 ms sample directly to another.
        if target > display:
            attack_speed = 500.0
            display += attack_speed * elapsed
            if display > target:
                display = target

        # Controlled release. A continuous worker sample means we no longer
        # need an event-timeout to force the meter down.
        elif target < display:
            release_speed = 110.0
            display -= release_speed * elapsed
            if display < target:
                display = target

        if display < minimum:
            display = minimum
        elif display > 0.0:
            display = 0.0

        self._display_level = display
        self._update_visual_level(display)

class NumericEdit(QLineEdit):
    """Editable numeric field that selects its contents when focused."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QLineEdit { background: #0d141b; border: 1px solid #314558; "
            "border-radius: 4px; padding: 2px 5px; }"
            "QLineEdit:hover { border-color: #4b6179; }"
            "QLineEdit:focus { border-color: #58a6ff; background: #101c28; }"
        )

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()


# How each kind of Mic processing value is shown next to its slider.
# "time" values switch between ms and s, see format_parameter().
PARAMETER_FORMATS = {
    "plain": "{:.1f}",
    "fine": "{:.2f}",
    "ratio": "{:.1f}:1",
    "gain": "{:+.1f} dB",
    "db": "{:.1f} dB",
    "hz": "{:.0f} Hz",
}


def format_parameter(kind, actual):
    """Return the display text for a processing value in VoiceMeeter units."""
    if kind == "time":
        if actual >= 1000:
            return f"{actual / 1000:.2f} s"
        return f"{actual:.1f} ms"
    return PARAMETER_FORMATS[kind].format(actual)


def parse_parameter(kind, text):
    """Return the value the user typed, in VoiceMeeter units (time in ms)."""
    # The displayed units are accepted as well as a bare number, for example
    # "4:1", "-18 dB", "500 Hz", "150 ms" or "1.5 s".
    value = text.strip().lower()
    if kind == "ratio":
        value = value.replace(":1", "").strip()
    elif kind in ("gain", "db"):
        value = value.replace("db", "").strip()
    elif kind == "hz":
        value = value.replace("hz", "").strip()
    elif kind == "time":
        if value.endswith("ms"):
            value = value[:-2].strip()
        elif value.endswith("s"):
            return float(value[:-1].strip()) * 1000.0
    return float(value)


class MicLevelBar(QWidget):
    """Horizontal Mic input level with the processing thresholds marked.

    Thresholds only mean something next to the level they are compared with,
    so the Mic Processing window shows both on one scale.
    """

    MIN_DB = -60.0

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.setToolTip(
            "Mic input level (before processing) with the gate and "
            "compressor thresholds"
        )
        self._markers = []
        self._target = self.MIN_DB
        self._display = self.MIN_DB
        self._last_animation = time.monotonic()

    def add_marker(self, label, color, getter):
        """Mark a threshold; getter returns its current value in dB."""
        self._markers.append((label, color, getter))

    def set_level(self, level):
        self._target = max(self.MIN_DB, min(0.0, float(level)))

    def animate(self):
        """Fast attack, slower release, like the Mic strip meters."""
        now = time.monotonic()
        elapsed = min(now - self._last_animation, 0.05)
        self._last_animation = now
        display = self._display
        if self._target > display:
            display = min(self._target, display + 500.0 * elapsed)
        elif self._target < display:
            display = max(self._target, display - 110.0 * elapsed)
        if display != self._display:
            self._display = display
            self.update()

    def _x(self, bar, db):
        fraction = (db - self.MIN_DB) / -self.MIN_DB
        return bar.left() + bar.width() * max(0.0, min(1.0, fraction))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(1, 5, self.width() - 2, 14)

        painter.setPen(QPen(QColor("#303a45"), 1))
        painter.setBrush(QColor("#111820"))
        painter.drawRoundedRect(bar, 4, 4)

        inner = bar.adjusted(2, 2, -2, -2)
        filled = self._x(inner, self._display) - inner.left()
        if filled > 0:
            gradient = QLinearGradient(inner.left(), 0, inner.right(), 0)
            gradient.setColorAt(0.0, QColor("#27c76f"))
            gradient.setColorAt(0.7, QColor("#54db39"))
            gradient.setColorAt(0.9, QColor("#f5df27"))
            gradient.setColorAt(1.0, QColor("#ff514b"))
            painter.fillRect(
                QRectF(inner.left(), inner.top(), filled, inner.height()),
                QBrush(gradient),
            )

        font = painter.font()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        markers = []
        for label, color, getter in self._markers:
            try:
                markers.append((float(getter()), label, QColor(color)))
            except Exception:
                continue
        markers.sort(key=lambda marker: marker[0])
        for index, (db, label, color) in enumerate(markers):
            x = self._x(inner, db)
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, bar.top() - 3), QPointF(x, bar.bottom() + 3))
            # Text of the lowest threshold goes left of its line and the
            # others right, so two nearby thresholds stay readable.
            text = f"{label} {db:.0f} dB"
            if index == 0 and len(markers) > 1:
                rect = QRectF(x - 124, bar.bottom() + 4, 120, 14)
                align = Qt.AlignmentFlag.AlignRight
            else:
                rect = QRectF(x + 4, bar.bottom() + 4, 120, 14)
                align = Qt.AlignmentFlag.AlignLeft
            painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()


class PanelSlider(QSlider):
    """Horizontal slider of a Mic processing parameter.

    It ignores the mouse wheel until it has been clicked, so scrolling over
    the window cannot change the live microphone by accident, and it can show
    a notch at a reference value.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(26)
        self._mark = None

    def set_mark(self, value):
        self._mark = value
        self.update()

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        span = self.maximum() - self.minimum()
        if self._mark is None or span <= 0:
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        travel = groove.width() - handle.width()
        x = (
            groove.left()
            + handle.width() / 2
            + travel * (self._mark - self.minimum()) / span
        )
        y = self.height() / 2
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#8ba0b5"), 2))
        painter.drawLine(QPointF(x, y + 8), QPointF(x, y + 12))
        painter.end()


# Time sliders are logarithmic: hearing works in ratios, and a linear track
# up to 5 s would squeeze the useful 5-300 ms range into a few pixels.
TIME_SLIDER_STEPS = 1000
TIME_CURVE_MS = 20.0  # smaller gives the short times more of the track


class ProcessingPanel(QWidget):
    """Sliders with editable value fields for one Mic processing block.

    Subclasses describe their block. Every control maps directly to the
    matching VoiceMeeter parameter of the Mic strip.
    """

    LABEL = ""        # name used in log messages
    ATTRIBUTE = ""    # voicemeeterlib attribute on the strip
    SCRIPT_NAME = ""  # VoiceMeeter script name, used for SCRIPT_KEYS
    # (label, key, slider minimum, slider maximum, scale, kind)
    PARAMETERS = ()
    # Timing parameters. The generic float setter can trigger a native access
    # violation for these with some VoiceMeeter/Python combinations, so they
    # are sent through VoiceMeeter's own script parser. Do not replace this.
    SCRIPT_KEYS = ()
    # One-line explanation per parameter key, shown as a tooltip.
    HELP = {}

    def __init__(self, vm):
        super().__init__()
        self.vm = vm
        self.strip_index = STRIPS["Mic"]
        self.target = getattr(vm.strip[self.strip_index], self.ATTRIBUTE)
        self.setVisible(False)
        self.controls = {}
        self.settings = app_settings()
        self._snapshot = {}
        # State to restore when bypass is switched off, or None.
        self._bypassed = None
        # State from before Amount was moved, for UNDO; None when there is
        # nothing to undo. See _before_amount_change().
        self._amount_undo = None
        self.amount_notice = None
        self._sync_hold_until = 0.0

        self.panel_layout = QVBoxLayout(self)
        self.panel_layout.setContentsMargins(6, 6, 6, 6)

        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        self.bypass_button = QPushButton("Bypass")
        self.bypass_button.setCheckable(True)
        self.bypass_button.setFixedHeight(26)
        self.bypass_button.setStyleSheet(
            "QPushButton { padding: 2px 12px; }"
            + outline_toggle_style(TOGGLE_COLORS["solo"])
        )
        self.bypass_button.setToolTip(
            f"Switch the {self.LABEL} off and remember all its values, "
            "so you can compare with and without"
        )
        self.bypass_button.clicked.connect(self.on_bypass_clicked)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setFixedHeight(26)
        self.reset_button.setStyleSheet("QPushButton { padding: 2px 12px; }")
        self.reset_button.setToolTip(
            "Restore the values from when this window was opened "
            "(marked by the notch under each slider)"
        )
        self.reset_button.clicked.connect(self.reset)
        tools.addWidget(self.bypass_button)
        tools.addStretch(1)
        tools.addWidget(self.reset_button)
        self.panel_layout.addLayout(tools)

        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(6)
        row = 0
        for parameter in self.PARAMETERS:
            self.add_slider(grid, row, *parameter)
            row += 1
            if parameter[1] == "knob" and len(self.PARAMETERS) > 1:
                grid.addWidget(self._build_amount_notice(), row, 0)
                row += 1
                # Amount is VoiceMeeter's one-knob control; the rest fine-tune.
                heading = QLabel("ADVANCED")
                heading.setStyleSheet(
                    SMALL_HEADING_STYLE + " "
                    "padding-top: 6px;"
                )
                grid.addWidget(heading, row, 0)
                row += 1
        self.panel_layout.addLayout(grid)

        self.build_extras()
        self.panel_layout.addStretch(1)
        self._restore_bypass()
        self.sync_from_voicemeeter()

    # Amount is a preset dial in VoiceMeeter: moving it replaces the advanced
    # values with VoiceMeeter's own for that amount. That cannot be switched
    # off, so the panel says what happened and offers the way back.

    def _build_amount_notice(self):
        self.amount_notice = QWidget()
        self.amount_notice.setObjectName("amountNotice")
        self.amount_notice.setStyleSheet(
            "QWidget#amountNotice { background: #2a2413; "
            "border: 1px solid #6b5a24; border-radius: 5px; }"
        )
        layout = QHBoxLayout(self.amount_notice)
        layout.setContentsMargins(8, 3, 4, 3)
        text = QLabel(
            "Amount replaced the advanced values with VoiceMeeter's preset."
        )
        text.setStyleSheet("color: #e8d9a6; font-size: 11px;")
        text.setToolTip(
            "In VoiceMeeter, Amount is a preset dial: every position has its "
            "own ratio, threshold, attack and release. Your own advanced "
            "values are replaced when it moves."
        )
        self.amount_notice.setFixedHeight(30)
        undo = QPushButton("Undo")
        undo.setFixedHeight(22)
        undo.setStyleSheet("QPushButton { padding: 1px 10px; font-size: 11px; }")
        undo.setToolTip("Bring back Amount and the advanced values from before")
        undo.clicked.connect(self.undo_amount)
        layout.addWidget(text, 1)
        layout.addWidget(undo)
        self.amount_notice.setVisible(False)
        return self.amount_notice

    def _before_amount_change(self, key):
        """Remember the values the first time Amount is moved by hand."""
        if key != "knob" or self.amount_notice is None:
            return
        if self._amount_undo is None and self._bypassed is None:
            try:
                self._amount_undo = self._read_state()
            except Exception:
                self._amount_undo = None

    def _after_change(self, key):
        if self.amount_notice is None:
            return
        if key == "knob":
            self.amount_notice.setVisible(self._amount_undo is not None)
        else:
            # Changing an advanced value means carrying on from here.
            self._forget_amount_undo()

    def _forget_amount_undo(self):
        self._amount_undo = None
        if self.amount_notice is not None:
            self.amount_notice.setVisible(False)

    def undo_amount(self):
        state = self._amount_undo
        self._forget_amount_undo()
        if not state:
            return
        try:
            self._restore_state(state)
        except Exception as e:
            log.error(
                f"Failed to undo {self.LABEL} Amount: {type(e).__name__}: {e}"
            )
            self.sync_from_voicemeeter()

    def build_extras(self):
        """Add controls that are not sliders. Nothing by default."""

    def sync_extras(self):
        """Synchronize the controls added by build_extras()."""

    def read_extras(self):
        """Return the values of the build_extras() controls for a snapshot."""
        return {}

    def apply_extras(self, values):
        """Restore values returned by read_extras()."""

    def add_slider(self, grid, row, name, key, minimum, maximum, scale, kind):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        name_label = QLabel(name)
        name_label.setMinimumWidth(76)

        value_edit = NumericEdit()
        value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        value_edit.setFixedWidth(74)
        value_edit.setToolTip("Click and type a value, then press Enter.")
        value_edit.editingFinished.connect(
            lambda k=key: self.on_value_edit_finished(k)
        )

        logarithmic = kind == "time"
        slider = PanelSlider()
        if logarithmic:
            slider.setRange(0, TIME_SLIDER_STEPS)
        else:
            slider.setRange(minimum, maximum)
        slider.setMinimumWidth(36)
        slider.valueChanged.connect(
            lambda value, k=key: self.on_slider_changed(k, value)
        )

        help_text = self.HELP.get(key, "")
        if help_text:
            name_label.setToolTip(help_text)
            slider.setToolTip(help_text)
        if key == "knob":
            name_label.setStyleSheet("font-weight: bold;")

        layout.addWidget(name_label)
        layout.addWidget(slider, 1)
        layout.addWidget(value_edit)
        grid.addWidget(container, row, 0)

        self.controls[key] = {
            "slider": slider,
            "edit": value_edit,
            "scale": scale,
            "kind": kind,
            "logarithmic": logarithmic,
            "minimum": minimum / scale,
            "maximum": maximum / scale,
        }

    def format_actual(self, key, actual):
        return format_parameter(self.controls[key]["kind"], actual)

    def _to_slider(self, key, actual):
        """Slider position for a value in VoiceMeeter units."""
        control = self.controls[key]
        if not control["logarithmic"]:
            return int(round(actual * control["scale"]))
        full = math.log1p(control["maximum"] / TIME_CURVE_MS)
        fraction = math.log1p(max(0.0, actual) / TIME_CURVE_MS) / full
        return int(round(max(0.0, min(1.0, fraction)) * TIME_SLIDER_STEPS))

    def _from_slider(self, key, value):
        """Value in VoiceMeeter units for a slider position."""
        control = self.controls[key]
        if not control["logarithmic"]:
            return value / control["scale"]
        full = math.log1p(control["maximum"] / TIME_CURVE_MS)
        actual = TIME_CURVE_MS * math.expm1(value / TIME_SLIDER_STEPS * full)
        return round(min(control["maximum"], max(0.0, actual)), 1)

    def set_parameter(self, key, actual):
        """Set a parameter through the safest API path."""
        if key in self.SCRIPT_KEYS:
            try:
                self.vm.sendtext(
                    f"Strip[{self.strip_index}].{self.SCRIPT_NAME}."
                    f"{key.capitalize()}={actual:.6f}"
                )
            except OSError:
                # VoiceMeeter's native call can raise a Windows
                # access-violation exception after the command has already
                # been accepted, so this is not an invalid user value. The
                # next pdirty event brings the authoritative value back.
                pass
            return

        setattr(self.target, key, actual)

    def _set_slider(self, key, actual):
        slider = self.controls[key]["slider"]
        slider.blockSignals(True)
        slider.setValue(self._to_slider(key, actual))
        slider.blockSignals(False)

    def _apply(self, key, actual):
        """Send a value to VoiceMeeter and show it."""
        self.set_parameter(key, actual)
        self._set_slider(key, actual)
        self.controls[key]["edit"].setText(self.format_actual(key, actual))

    def on_value_edit_finished(self, key):
        control = self.controls[key]
        edit = control["edit"]
        try:
            actual = parse_parameter(control["kind"], edit.text())
            if not math.isfinite(actual):
                raise ValueError("Value must be finite.")
            if actual < control["minimum"] or actual > control["maximum"]:
                raise ValueError(
                    f"Value must be between {control['minimum']:g} "
                    f"and {control['maximum']:g}."
                )
            self._before_amount_change(key)
            self._set_slider(key, actual)
            edit.setText(self.format_actual(key, actual))
            self.set_parameter(key, actual)
            self._amount_changed(key, actual)
            self._after_change(key)
        except Exception as e:
            log.error(
                f"Invalid {self.LABEL} {key} value: {type(e).__name__}: {e}"
            )
            # Restore the current VoiceMeeter value instead of leaving an
            # invalid value in the field.
            try:
                edit.setText(
                    self.format_actual(key, getattr(self.target, key))
                )
            except Exception as e:
                log.debug(f"Could not read {key} back from the mixer: {e}")
                pass

    def on_slider_changed(self, key, value):
        actual = self._from_slider(key, value)
        self.controls[key]["edit"].setText(self.format_actual(key, actual))
        try:
            self._before_amount_change(key)
            self.set_parameter(key, actual)
            self._amount_changed(key, actual)
            self._after_change(key)
        except Exception as e:
            log.error(
                f"Failed to set {self.LABEL} {key}: {type(e).__name__}: {e}"
            )

    # Bypass: Amount 0 switches a block off. VoiceMeeter rewrites the advanced
    # values whenever Amount changes (Amount is a preset dial), so bypass keeps
    # the whole state, also across restarts, and puts all of it back.

    def _bypass_setting(self):
        return f"bypass_state_{self.LABEL}"

    def _read_state(self):
        """Every value of this block as VoiceMeeter has it now."""
        return {
            "values": {
                key: float(getattr(self.target, key))
                for key in self.controls
            },
            "extras": self.read_extras(),
        }

    def _restore_state(self, state):
        """Send a state from _read_state() back to VoiceMeeter."""
        values = state["values"]
        self._forget_amount_undo()
        # VoiceMeeter reports in-between values while a batch of changes is
        # being applied (Release has been seen at 0). Show the values being
        # sent and read back once things have settled.
        self._hold_sync(0.6)
        # Amount first: setting it replaces the advanced values, which are
        # then overwritten with the ones that belong to this state. When
        # Amount is already right it is left alone, so the advanced values
        # are not disturbed, on screen or in the sound.
        if abs(float(self.target.knob) - values["knob"]) > 0.001:
            self._apply("knob", values["knob"])
        for key, actual in values.items():
            if key != "knob":
                self._apply(key, actual)
        self.apply_extras(state.get("extras", {}))

    def _hold_sync(self, seconds):
        """Ignore VoiceMeeter's change events briefly, then read once."""
        self._sync_hold_until = time.monotonic() + seconds
        # With this panel as context the call is dropped if the panel is gone.
        QTimer.singleShot(
            int(seconds * 1000) + 100, self, self.sync_from_voicemeeter
        )

    def _restore_bypass(self):
        stored = self.settings.value(self._bypass_setting(), None)
        if stored is None:
            return
        try:
            state = json.loads(stored)
            if state["values"]["knob"] > 0 and float(self.target.knob) == 0:
                self._bypassed = state
                self.bypass_button.setChecked(True)
                return
        except Exception as e:
            log.debug(f"Could not restore the bypassed {self.ATTRIBUTE}: {e}")
            pass
        self.settings.remove(self._bypass_setting())

    def _clear_bypass(self):
        self._bypassed = None
        self.bypass_button.setChecked(False)
        self.settings.remove(self._bypass_setting())

    def _amount_changed(self, key, actual):
        """Turning Amount up by hand ends a bypass."""
        if key == "knob" and actual > 0 and self._bypassed is not None:
            self._clear_bypass()

    def on_bypass_clicked(self, checked):
        try:
            if checked:
                state = self._read_state()
                if state["values"]["knob"] <= 0:
                    # Already off and nothing to remember.
                    self.bypass_button.setChecked(False)
                    return
                self._bypassed = state
                self._forget_amount_undo()
                self.settings.setValue(
                    self._bypass_setting(), json.dumps(state)
                )
                self._hold_sync(0.6)
                self._apply("knob", 0.0)
            else:
                state = self._bypassed
                self._clear_bypass()
                if state:
                    self._restore_state(state)
        except Exception as e:
            log.error(
                f"Failed to bypass {self.LABEL}: {type(e).__name__}: {e}"
            )
            self.sync_from_voicemeeter()

    # Presets: a stored state of this block, applied like Reset.

    def preset_state(self):
        """The state a preset should store: the real values, also while
        bypassed (bypass is a temporary switch, not part of a preset)."""
        state = self._bypassed or self._read_state()
        return {"values": dict(state["values"]), "extras": dict(state["extras"])}

    def apply_preset(self, state):
        """Apply a stored state. Returns False if it is not usable.

        Presets come from a settings file, so unknown parameters are skipped
        and values are kept inside the slider ranges.
        """
        try:
            stored = state["values"]
            values = {}
            for key, control in self.controls.items():
                if key in stored:
                    actual = float(stored[key])
                    if not math.isfinite(actual):
                        return False
                    values[key] = max(
                        control["minimum"], min(control["maximum"], actual)
                    )
            if "knob" not in values:
                return False
            if self._bypassed is not None:
                self._clear_bypass()
            applied = {
                "values": values,
                "extras": dict(state.get("extras") or {}),
            }
            self._restore_state(applied)
            self.set_reference(applied)
            return True
        except Exception as e:
            log.error(
                f"Failed to apply {self.LABEL} preset: {type(e).__name__}: {e}"
            )
            self.sync_from_voicemeeter()
            return False

    # Reset: go back to the values the window was opened with.

    def take_snapshot(self):
        """Remember the current values as the target of RESET."""
        try:
            # While bypassed, the state to return to is the one bypass kept.
            self.set_reference(self._bypassed or self._read_state())
        except Exception as e:
            log.error(
                f"Failed to read {self.LABEL}: {type(e).__name__}: {e}"
            )

    def set_reference(self, state):
        """Make a state the one RESET returns to and the ticks point at.

        That is the state the window opened with, until a preset or profile
        is loaded or saved: from then on that one is the reference.
        """
        values = dict((self._snapshot or {}).get("values", {}))
        values.update(state["values"])
        self._snapshot = {
            "values": values,
            "extras": dict(state.get("extras") or {}),
        }
        for key, actual in values.items():
            if key in self.controls:
                self.controls[key]["slider"].set_mark(
                    self._to_slider(key, actual)
                )

    def reset(self):
        if not self._snapshot:
            return
        try:
            if self._bypassed is not None:
                self._clear_bypass()
            self._restore_state(self._snapshot)
        except Exception as e:
            log.error(
                f"Failed to reset {self.LABEL}: {type(e).__name__}: {e}"
            )
            self.sync_from_voicemeeter()

    def sync_from_voicemeeter(self):
        """Synchronize every control from VoiceMeeter."""
        if time.monotonic() < self._sync_hold_until:
            return
        try:
            values = {
                key: getattr(self.target, key)
                for key in self.controls
            }
            if self._bypassed is not None and values["knob"] > 0:
                # Switched back on from VoiceMeeter itself.
                self._clear_bypass()
            for key, actual in values.items():
                self._set_slider(key, actual)
                # Do not overwrite text while the user is typing in the field.
                edit = self.controls[key]["edit"]
                if not edit.hasFocus():
                    edit.setText(self.format_actual(key, actual))
            self.sync_extras()
        except Exception as e:
            log.error(
                f"Failed to synchronize {self.LABEL}: {type(e).__name__}: {e}"
            )


class CompressorControl(ProcessingPanel):
    """Compressor controls for the Mic strip (mic.comp)."""

    LABEL = "compressor"
    ATTRIBUTE = "comp"
    SCRIPT_NAME = "Comp"
    # VoiceMeeter ranges: knob 0..10, gains -24..24 dB, ratio 1..8,
    # threshold -40..-3 dB, attack 0..200 ms, release 0..5000 ms, knee 0..1.
    PARAMETERS = (
        ("Amount", "knob", 0, 100, 10, "plain"),
        ("Input Gain", "gainin", -240, 240, 10, "gain"),
        ("Ratio", "ratio", 10, 80, 10, "ratio"),
        ("Threshold", "threshold", -400, -30, 10, "db"),
        ("Attack", "attack", 0, 2000, 10, "time"),
        ("Release", "release", 0, 50000, 10, "time"),
        ("Knee", "knee", 0, 100, 100, "fine"),
        ("Output Gain", "gainout", -240, 240, 10, "gain"),
    )
    SCRIPT_KEYS = ("attack", "release")
    HELP = {
        "knob": "How much compression is applied, 0 to 10. 0 switches the compressor off. Moving it replaces the advanced values below with VoiceMeeter's preset for that amount.",
        "gainin": "Level change before the compressor.",
        "ratio": "How strongly sound above the threshold is turned down. 4:1 lets 1 dB through for every 4 dB over.",
        "threshold": "Level above which the compressor starts working. Compare with the Mic input bar above.",
        "attack": "How quickly the compressor reacts when you get loud.",
        "release": "How quickly it lets go again when you get quieter.",
        "knee": "How gradually compression sets in around the threshold. 0 is abrupt, 1 is smooth.",
        "gainout": "Level change after the compressor.",
    }

    def build_extras(self):
        self.makeup_checkbox = QCheckBox("Auto Makeup")
        self.makeup_checkbox.setToolTip(
            "Raise the level automatically to make up for what the "
            "compressor turned down"
        )
        self.makeup_checkbox.stateChanged.connect(self.on_makeup_changed)
        self.panel_layout.addWidget(
            self.makeup_checkbox,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )

    def sync_extras(self):
        makeup = self.target.makeup
        self.makeup_checkbox.blockSignals(True)
        self.makeup_checkbox.setChecked(makeup)
        self.makeup_checkbox.blockSignals(False)

    def read_extras(self):
        return {"makeup": bool(self.target.makeup)}

    def apply_extras(self, values):
        if "makeup" in values:
            self.target.makeup = bool(values["makeup"])
        self.sync_extras()

    def on_makeup_changed(self, state):
        enabled = state == Qt.CheckState.Checked.value
        self._forget_amount_undo()
        try:
            self.target.makeup = enabled
        except Exception as e:
            log.error(
                f"Failed to set compressor makeup: {type(e).__name__}: {e}"
            )


class GateControl(ProcessingPanel):
    """Gate controls for the Mic strip (mic.gate)."""

    LABEL = "gate"
    ATTRIBUTE = "gate"
    SCRIPT_NAME = "Gate"
    PARAMETERS = (
        ("Amount", "knob", 0, 100, 10, "plain"),
        ("Threshold", "threshold", -600, -100, 10, "db"),
        ("Damping", "damping", -600, -100, 10, "db"),
        ("Sidechain", "bpsidechain", 100, 4000, 1, "hz"),
        ("Attack", "attack", 0, 10000, 10, "time"),
        ("Hold", "hold", 0, 50000, 10, "time"),
        ("Release", "release", 0, 50000, 10, "time"),
    )
    SCRIPT_KEYS = ("attack", "hold", "release")
    HELP = {
        "knob": "How strongly the gate works, 0 to 10. 0 switches the gate off.",
        "threshold": "Level below which the gate closes. Set it just above your room noise; compare with the Mic input bar above.",
        "damping": "How far the signal is turned down while the gate is closed.",
        "bpsidechain": "Centre frequency the gate listens at when deciding to open.",
        "attack": "How quickly the gate opens when you start talking.",
        "hold": "How long the gate stays open after you stop.",
        "release": "How quickly the gate closes after the hold time.",
    }


class DenoiserControl(ProcessingPanel):
    """Denoiser control for the Mic strip (mic.denoiser)."""

    LABEL = "denoiser"
    ATTRIBUTE = "denoiser"
    PARAMETERS = (
        ("Amount", "knob", 0, 100, 10, "plain"),
    )
    HELP = {
        "knob": "How much steady background noise is removed, 0 to 10. 0 switches the denoiser off.",
    }


class FineControlSlider(QSlider):
    """Slider with predictable, one-step-per-wheel-notch adjustments."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._wheel_remainder = 0
        # Step of one wheel notch; None means singleStep(). With Shift held
        # the wheel moves by shift_step, or singleStep() when that is None.
        self.wheel_step = None
        self.shift_step = None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return

        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.singleStep()
        if shift and self.shift_step is not None:
            step = self.shift_step
        elif self.wheel_step is not None and not shift:
            step = self.wheel_step

        self._wheel_remainder += delta
        notches = int(self._wheel_remainder / 120)
        if notches:
            self._wheel_remainder -= notches * 120
            self.setValue(self.value() + notches * step)
        event.accept()


class MixerFader(FineControlSlider):
    """Vertical gain fader with a dB scale beside its track."""

    SCALE_DB = (12, 0, -12, -24, -36, -48, -60)
    UNITS_PER_DB = 100
    WIDTH = 100  # leaves room for the scale labels; the track stays centered
    show_labels = True

    def mouseDoubleClickEvent(self, event):
        # A double right-click puts the fader back at 0 dB; a single one
        # does nothing, so a stray click cannot reset it.
        if event.button() == Qt.MouseButton.RightButton:
            self.setValue(0)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        travel = groove.height() - handle.height()
        span = self.maximum() - self.minimum()
        if travel <= 0 or span <= 0:
            return

        center = self.width() / 2
        painter = QPainter(self)
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        for db in self.SCALE_DB:
            value = db * self.UNITS_PER_DB
            y = (
                groove.top()
                + handle.height() / 2
                + travel * (self.maximum() - value) / span
            )
            unity = db == 0
            length = 8 if unity else 4
            painter.setPen(QPen(QColor("#e6edf3" if unity else "#4b5a6b"), 1))
            painter.drawLine(
                QPointF(center - 14 - length, y), QPointF(center - 14, y)
            )
            painter.drawLine(
                QPointF(center + 14, y), QPointF(center + 14 + length, y)
            )
            if not self.show_labels:
                continue
            painter.setPen(QColor("#e6edf3" if unity else "#7d8ea0"))
            painter.drawText(
                QRectF(center + 25, y - 7, 24, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{db:+d}" if db else "0",
            )
        painter.end()


class MicFaderArea(QWidget):
    """Mic fader and meters.

    The fader is centered with the same stretch layout the other strips use,
    so it lines up exactly with the gain readout and the other faders. The two
    input meters are positioned relative to the fader instead of being part of
    the layout, so they can never push the fader off center.
    """

    def __init__(self, fader, meters):
        super().__init__()
        self.fader = fader
        self.meters = list(meters)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addWidget(fader)
        row.addStretch(1)

        for meter in self.meters:
            meter.setParent(self)

        self.setMinimumHeight(CHANNEL_FADER_MIN_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_meters()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_meters()

    def _place_meters(self):
        if not self.meters:
            return
        self.layout().activate()
        widths = [meter.maximumWidth() for meter in self.meters]
        total = sum(widths) + MIC_METER_SPACING * (len(widths) - 1)
        # Keep the usual gap when there is room, and close up to the fader
        # in a narrow card rather than sliding under it.
        gap = min(MIC_METER_GAP, max(4, self.fader.x() - total - 2))
        x = max(0, self.fader.x() - gap - total)
        y = self.fader.y()
        height = self.fader.height()
        for meter, width in zip(self.meters, widths):
            meter.setGeometry(x, y, width, height)
            meter.show()
            x += width + MIC_METER_SPACING


class StripWidget(QWidget):

    def __init__(
        self,
        name,
        vm,
        strip_index,
    ):
        super().__init__()

        self.vm = vm
        self.name = name

        self.strip_index = strip_index

        # VoiceMeeter can emit pdirty with the previous value while a fader
        # write is still being applied. Briefly keep the user's local edit
        # visible instead of snapping the fader back during that round trip.
        self._last_local_gain_change = 0.0

        self.strip = vm.strip[strip_index]


        colors = STRIP_COLORS.get(name, STRIP_COLORS["Mic"])
        accent = colors["accent"]
        border = colors["border"]
        header_color = colors["header"]
        self.setObjectName("mixerStripCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#mixerStripCard {"
            f"background-color: #111923; border: 1px solid {border}; "
            "border-radius: 8px; }"
        )

        self.setMinimumWidth(0)


        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(1)


        self._build_header(
            accent, border, header_color, layout, name, strip_index
        )
        layout.addSpacing(8)
        self._build_fader(accent, layout, name)
        self._build_buttons(accent, layout)
        self._build_routing(accent, layout)

        self.sync_from_voicemeeter()

    def _build_header(
        self, accent, border, header_color, layout, name, strip_index
    ):
        """The coloured card header: icon, channel name and its source."""
        # Two-line source header, following VoiceMeeter's input cards.
        source_names = {
            "Mic": f"Stereo Input {strip_index + 1}",
            "Game": "VAIO",
            "Chat": "VAIO AUX",
            "Media": "VAIO3",
        }
        source_icons = {
            "Mic": "mic",
            "Game": "game",
            "Chat": "chat",
            "Media": "media",
        }
        strip_header = QWidget()
        strip_header.setStyleSheet(
            f"background: {header_color}; border: 1px solid {border}; "
            "border-radius: 6px;"
        )
        strip_header_layout = QHBoxLayout(strip_header)
        strip_header_layout.setContentsMargins(6, 2, 6, 2)
        strip_header_layout.setSpacing(5)
        strip_header_layout.addStretch(1)
        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        set_mono_icon(icon_label, source_icons.get(name, "mic"), 22)
        icon_label.setStyleSheet(
            "background: transparent; border: none;"
        )
        strip_header_layout.addWidget(icon_label)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(0)
        self.name_label = QLabel(channel_label(name))
        self.name_label.setStyleSheet(
            f"color: {accent}; background: transparent; border: none; "
            "font-size: 14px; font-weight: bold;"
        )
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        source_label = QLabel(source_names.get(name, ""))
        source_label.setStyleSheet(
            "color: #9bb0c3; background: transparent; border: none; "
            "font-size: 10px;"
        )
        source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_stack.addWidget(self.name_label)
        title_stack.addWidget(source_label)
        strip_header_layout.addLayout(title_stack)
        strip_header_layout.addStretch(1)
        strip_header.setFixedHeight(CHANNEL_HEADER_HEIGHT)
        layout.addWidget(strip_header)
        self.strip_header = strip_header
        self.source_label = source_label
        self.compact = False

    def _build_fader(self, accent, layout, name):
        """Input meters, the fader with its scale, and the gain readout."""
        # Input level meters. They are placed relative to the fader (see
        # MicFaderArea) so they can never push the fader off center.
        self.vu_meters = [VUMeter("L"), VUMeter("R")]

        # Fader

        self.fader = MixerFader(
            Qt.Orientation.Vertical
        )
        self.fader.setFixedWidth(MixerFader.WIDTH)
        self.fader.setRange(
            -6000,

            1200,

        )
        # Fader units are 0.01 dB. One wheel notch and the arrow keys move
        # 0.1 dB; Shift+wheel and Page Up/Down move 1 dB for bigger jumps.
        self.fader.setSingleStep(10)
        self.fader.setPageStep(100)
        self.fader.wheel_step = 10
        self.fader.shift_step = 100
        self.fader.setToolTip(
            "Mouse wheel: 0.1 dB, with Shift 1 dB. "
            "Arrow keys: 0.1 dB. Page Up/Down: 1 dB. "
            "Double right-click: back to 0 dB."
        )
        self.fader.show_labels = True

        self.fader.setMinimumHeight(CHANNEL_FADER_MIN_HEIGHT)
        self.fader.setStyleSheet(
            "QSlider::groove:vertical { background: #30363d; width: 8px; "
            "border-radius: 4px; }"
            f"QSlider::handle:vertical {{ background: {accent}; height: 22px; "
            "margin: 0 -7px; border-radius: 5px; }"
        )

        self.fader.setValue(

            int(
                self.strip.gain
                * 100
            )
        )

        self.fader.valueChanged.connect(
            self.on_fader_changed

        )


        # The fader is centered in the card; the two input meters sit to
        # its left.
        layout.addWidget(MicFaderArea(self.fader, self.vu_meters), 1)


        # Gain readout
        layout.addSpacing(FADER_TO_GAIN_GAP)

        self.gain_label = QLabel()


        self.gain_label.setAlignment(

            Qt.AlignmentFlag.AlignCenter

        )
        self.gain_label.setStyleSheet(
            "color: #e6edf3; font-size: 14px; font-weight: bold;"
        )


        self.update_gain_label()


        layout.addWidget(
            self.gain_label
        )

    def _build_buttons(self, accent, layout):
        """MUTE, SOLO and MONO."""
        # Buttons

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)


        self.mute_button = QPushButton("Mute")
        self.mute_button.setFixedHeight(MIXER_BUTTON_HEIGHT)

        self.solo_button = QPushButton("Solo")
        self.solo_button.setFixedHeight(MIXER_BUTTON_HEIGHT)

        self.mono_button = QPushButton("Mono")
        self.mono_button.setFixedHeight(MIXER_BUTTON_HEIGHT)
        self.solo_button.setStyleSheet(
            outline_toggle_style(TOGGLE_COLORS["solo"])
        )
        self.mono_button.setStyleSheet(outline_toggle_style(accent))

        self.mute_button.setCheckable(
            True
        )
        self.solo_button.setCheckable(
            True
        )
        self.mono_button.setCheckable(
            True
        )

        self.mute_button.clicked.connect(
            self.on_mute_clicked
        )
        self.solo_button.clicked.connect(
            self.on_solo_clicked
        )
        self.mono_button.clicked.connect(
            self.on_mono_clicked
        )

        # MUTE is used constantly, SOLO and MONO rarely: give it the room.
        button_layout.addWidget(self.mute_button, 2)
        button_layout.addWidget(self.solo_button, 1)
        button_layout.addWidget(self.mono_button, 1)

        layout.addLayout(
            button_layout
        )

        layout.addSpacing(8)

    def _build_routing(self, accent, layout):
        """The A1-B3 routing buttons."""
        routing_title = QLabel("ROUTING")
        routing_title.setFixedHeight(ROUTING_LABEL_HEIGHT)
        routing_title.setStyleSheet(SMALL_HEADING_STYLE)
        layout.addWidget(routing_title)
        self.routing_title = routing_title
        layout.addSpacing(2)
        routing_layout = QGridLayout()
        routing_layout.setContentsMargins(0, 0, 0, 0)
        routing_layout.setHorizontalSpacing(5)
        routing_layout.setVerticalSpacing(2)
        self.route_buttons = {}
        self.routing_layout = routing_layout
        self.visible_routes = []
        for output in ALL_OUTPUTS:
            self._add_route_button(routing_layout, output, 0, 0, accent)
        layout.addLayout(routing_layout)
        self.place_routes(available_outputs(self.vm))

    def place_routes(self, outputs):
        """Show the routing buttons of these outputs, at most four in a row:
        for headphones on A1 and the three virtual outputs, one row."""
        for button in self.route_buttons.values():
            self.routing_layout.removeWidget(button)
            button.setVisible(False)
        per_row = 4 if len(outputs) <= 4 else (len(outputs) + 1) // 2
        for index, output in enumerate(outputs):
            button = self.route_buttons[output]
            self.routing_layout.addWidget(button, index // per_row, index % per_row)
            button.setVisible(not self.compact)
        self.visible_routes = list(outputs)

    def rename_routes(self):
        for output, button in self.route_buttons.items():
            text, tooltip = route_name(self.vm, output)
            button.setText(text)
            button.setToolTip(tooltip)

    def _add_route_button(self, layout, output, row, column, accent):
        text, tooltip = route_name(self.vm, output)
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setFixedHeight(ROUTING_BUTTON_HEIGHT)
        button.setStyleSheet(
            "QPushButton { padding: 1px 4px; }" + outline_toggle_style(accent)
        )
        button.clicked.connect(
            lambda checked, name=output: self.on_route_clicked(name, checked)
        )
        layout.addWidget(button, row, column)
        self.route_buttons[output] = button

    def set_compact(self, compact):
        """Compact view keeps the fader, the meters, the level and MUTE.

        Everything else is hidden, not removed: profiles, hotkeys and
        VoiceMeeter's own changes still reach the hidden buttons.
        """
        self.compact = bool(compact)
        for widget in (
            self.source_label,
            self.solo_button,
            self.mono_button,
            self.routing_title,
            *(self.route_buttons[output] for output in self.visible_routes),
        ):
            widget.setVisible(not compact)
        self.strip_header.setFixedHeight(
            COMPACT_HEADER_HEIGHT if compact else CHANNEL_HEADER_HEIGHT
        )
        self.fader.setFixedWidth(
            COMPACT_FADER_WIDTH if compact else MixerFader.WIDTH
        )
        self.fader.show_labels = not compact
        width = COMPACT_METER_WIDTH if compact else NORMAL_METER_WIDTH
        for meter in self.vu_meters:
            meter.setMinimumWidth(width)
            meter.setMaximumWidth(width)
        self.setMinimumHeight(
            COMPACT_CARD_MIN_HEIGHT if compact else MIXER_CARD_MIN_HEIGHT
        )
        self.fader.update()

    # The stream mix. A VoiceMeeter strip has a volume per output (a gain
    # layer) as well as its own volume, and writing its own volume resets
    # every layer to it. So once the stream has an output of its own, the
    # fader writes layers: YOU sets every output but the stream's, STREAM
    # only the stream's. Without a stream output it is the strip's volume.
    stream_buses = ()  # VoiceMeeter bus indexes of the stream's outputs
    mix = "you"
    # Outputs that get the YOU volume plus an offset in dB: the Mic strip's
    # monitor output, so you can hear yourself quieter than others hear you.
    offsets = {}

    def layered(self):
        return bool(self.stream_buses) or bool(self.offsets)

    def set_mix(self, stream_buses, mix):
        self.stream_buses = tuple(stream_buses)
        self.mix = mix if self.stream_buses else "you"
        # Show the other mix at once, even right after a fader move.
        self._last_local_gain_change = 0.0
        self.sync_from_voicemeeter()

    def set_offsets(self, offsets):
        """Give some outputs the YOU volume plus an offset, from now on."""
        you = self.mix_gain("you")
        self.offsets = dict(offsets)
        self.set_mix_gain(you, "you")

    def mix_gain(self, mix=None):
        mix = mix or self.mix
        if not self.layered():
            return self.strip.gain
        if mix == "stream" and self.stream_buses:
            # The stream output this channel goes to, if it goes to one.
            routed = [
                bus for bus, output in zip(self.stream_buses, self.stream_outputs())
                if self.route_buttons.get(output) is not None
                and self.route_buttons[output].isChecked()
            ]
            return self.strip.gainlayer[(routed or self.stream_buses)[0]].gain
        # Any output that is neither the stream's nor offset carries YOU.
        own = next(
            bus for bus in range(len(self.strip.gainlayer))
            if bus not in self.stream_buses and bus not in self.offsets
        )
        return self.strip.gainlayer[own].gain

    def set_mix_gain(self, gain, mix=None):
        mix = mix or self.mix
        if not self.layered():
            self.strip.gain = gain
        elif mix == "stream" and self.stream_buses:
            for bus in self.stream_buses:
                self.strip.gainlayer[bus].gain = gain
        else:
            for bus, layer in enumerate(self.strip.gainlayer):
                if bus not in self.stream_buses:
                    level = gain + self.offsets.get(bus, 0.0)
                    layer.gain = min(12.0, max(-60.0, level))

    def profile_state(self):
        """What a mixer profile stores for this strip."""
        state = {
            "gain": round(self.mix_gain("you"), 2),
            "mute": self.mute_button.isChecked(),
            "solo": self.solo_button.isChecked(),
            "mono": self.mono_button.isChecked(),
            "routes": {
                output: button.isChecked()
                for output, button in self.route_buttons.items()
            },
        }
        if self.stream_buses:
            state["stream_gain"] = round(self.mix_gain("stream"), 2)
        return state

    def apply_profile(self, state):
        """Apply a stored profile_state(). Returns False if it is not usable.

        Each value goes through the same handler as a click or a fader move,
        so only what differs is sent to VoiceMeeter.
        """
        try:
            wanted = {"you": float(state["gain"])}
            if self.stream_buses and "stream_gain" in state:
                wanted["stream"] = float(state["stream_gain"])
            for mix, gain in wanted.items():
                if not math.isfinite(gain):
                    return False
                gain = min(12.0, max(-60.0, gain))
                # Only what differs is sent to VoiceMeeter.
                if round(self.mix_gain(mix), 2) != round(gain, 2):
                    self.set_mix_gain(gain, mix)
            self.fader.blockSignals(True)
            self.fader.setValue(int(round(self.mix_gain() * 100)))
            self.fader.blockSignals(False)
            self.update_gain_label()
            for key, button, handler in (
                ("mute", self.mute_button, self.on_mute_clicked),
                ("solo", self.solo_button, self.on_solo_clicked),
                ("mono", self.mono_button, self.on_mono_clicked),
            ):
                wanted = bool(state[key])
                if button.isChecked() != wanted:
                    button.setChecked(wanted)
                    handler(wanted)
            for output, wanted in dict(state.get("routes") or {}).items():
                button = self.route_buttons.get(output)
                if button is not None and button.isChecked() != bool(wanted):
                    button.setChecked(bool(wanted))
                    self.on_route_clicked(output, bool(wanted))
            return True
        except Exception as e:
            log.error(
                f"Failed to apply {self.name} profile: {type(e).__name__}: {e}"
            )
            self.sync_from_voicemeeter()
            return False

    def on_route_clicked(self, output, checked):
        try:
            setattr(self.strip, output, bool(checked))
            self.update_gain_label()  # the stream mix may now reach this channel
        except Exception as exc:
            log.error(
                f"Failed to set {self.name} route {output}: "
                f"{type(exc).__name__}: {exc}"
            )
            self.sync_routes()

    def sync_routes(self):
        for output, button in self.route_buttons.items():
            try:
                button.blockSignals(True)
                button.setChecked(bool(getattr(self.strip, output)))
            except Exception as e:
                log.debug(f"Could not read {self.name} route {output}: {e}")
                pass
            finally:
                button.blockSignals(False)
        self.update_gain_label()


    def stream_outputs(self):
        """The routing button names of the stream's outputs."""
        names = {bus: output for output, bus in ROUTE_BUS.items()}
        return [names[bus] for bus in self.stream_buses if bus in names]

    def update_gain_label(self):

        gain = self.fader.value() / 100
        outputs = self.stream_outputs() if self.mix == "stream" else []
        buttons = [self.route_buttons[o] for o in outputs if o in self.route_buttons]
        # In the stream mix, a channel that reaches none of the stream's
        # outputs has no stream volume to set: say so instead.
        off_stream = bool(buttons) and not any(b.isChecked() for b in buttons)
        self.fader.setEnabled(not off_stream)
        if off_stream:
            names = " or ".join(output_label(o) for o in outputs)
            self.gain_label.setText(f"not sent to {names}")
            self.gain_label.setToolTip(
                f"Your stream hears {names}, and this channel is not routed "
                f"there. Click {output_label(outputs[-1])} below to send it to "
                "your stream."
            )
        else:
            self.gain_label.setText(f"{gain:+.2f} dB")
            self.gain_label.setToolTip("")

    def on_fader_changed(self, value):
        gain = value / 100
        self._last_local_gain_change = time.monotonic()

        try:
            self.set_mix_gain(gain)
        except Exception as e:
            log.error(
                f"Failed to set {self.name} gain: "
                f"{type(e).__name__}: {e}"
            )
            return

        self.update_gain_label()

    def on_mute_clicked(self, checked, chime=True):
        try:
            self.strip.mute = checked
        except Exception as e:
            log.error(
                f"Failed to set {self.name} mute: "
                f"{type(e).__name__}: {e}"
            )
            return
        # Every way of muting comes here: button, hotkey, tray, API, profile.
        settings = app_settings()
        if chime and self.name == "Mic" and setting_bool(settings, "mute_sound", True):
            play_mute_sound(
                checked, str(settings.value("mute_sound_device", "") or "")
            )

    def on_solo_clicked(self, checked):
        try:
            self.strip.solo = checked
        except Exception as e:
            log.error(
                f"Failed to set {self.name} solo: "
                f"{type(e).__name__}: {e}"
            )

    def on_mono_clicked(self, checked):
        try:
            self.strip.mono = checked
        except Exception as e:
            log.error(
                f"Failed to set {self.name} mono: "
                f"{type(e).__name__}: {e}"

            )


    def set_channel_levels(self, levels):
        """Apply already-read levels to the UI without any VM I/O."""
        for meter, level in zip(self.vu_meters, levels):
            meter.set_level(level)


    def animate_level(self):
        """Advance the meter animation without VoiceMeeter I/O."""
        for meter in self.vu_meters:
            meter.animate_level()


    def sync_from_voicemeeter(self):

        """
        Synchronize all strip parameters from VoiceMeeter.
        """

        try:

            gain = self.mix_gain()


            # The event observer may report a stale value immediately after a
            # local wheel/drag update. Ignore that gain echo briefly; later
            # events still reconcile external VoiceMeeter changes normally.
            if time.monotonic() - self._last_local_gain_change >= 0.5:
                self.fader.blockSignals(True)
                self.fader.setValue(int(round(gain * 100)))
                self.fader.blockSignals(False)


            self.update_gain_label()


            mute = self.strip.mute
            solo = self.strip.solo
            mono = self.strip.mono

            self.mute_button.blockSignals(
                True
            )
            self.mute_button.setChecked(
                mute
            )
            self.mute_button.blockSignals(
                False
            )

            self.solo_button.blockSignals(
                True
            )
            self.solo_button.setChecked(
                solo
            )
            self.solo_button.blockSignals(
                False
            )

            self.mono_button.blockSignals(
                True
            )
            self.mono_button.setChecked(
                mono
            )
            self.mono_button.blockSignals(
                False
            )
            self.sync_routes()

        except Exception as e:
            log.error(
                f"Failed to synchronize {self.name}: "
                f"{type(e).__name__}: {e}"
            )


class LiveVolumeSlider(FineControlSlider):
    """Volume slider with the live session peak drawn on its track.

    Clicking or dragging anywhere on the track directly sets the volume,
    rather than requiring the user to grab the small thumb first.
    """

    thumb_color = "#58a6ff"

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._audio_level = 0.0

    def _set_value_from_position(self, x):
        margin = 8
        usable_width = max(1, self.width() - (margin * 2))
        position = max(0, min(usable_width, int(x) - margin))
        value = QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            position,
            usable_width,
            False,
        )
        self.setValue(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_value_from_position(event.position().x())
            self.setSliderDown(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton:
            self._set_value_from_position(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._set_value_from_position(event.position().x())
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_audio_level(self, level):
        self._audio_level = max(0.0, min(1.0, float(level)))
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(
            groove.left() + 8,
            handle.center().y() - 3,
            max(1, groove.width() - 16),
            6,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#30363d"))
        painter.drawRoundedRect(track, 3, 3)

        if self._audio_level > 0.0:
            live_track = QRectF(
                track.left(),
                track.top(),
                max(1.0, track.width() * self._audio_level),
                track.height(),
            )
            painter.setBrush(QColor("#3fb950"))
            painter.drawRoundedRect(live_track, 3, 3)

        # Draw the volume thumb on the exact same centerline as the meter.
        handle_width = max(14, handle.width())
        handle_height = 14
        thumb = QRectF(
            handle.center().x() - handle_width / 2,
            track.center().y() - handle_height / 2,
            handle_width,
            handle_height,
        )
        thumb_color = QColor(self.thumb_color)
        if self.isSliderDown():
            thumb_color = thumb_color.lighter(125)
        painter.setBrush(thumb_color)
        painter.drawRoundedRect(thumb, 4, 4)
        painter.end()


class ApplicationAudioWorker(QObject):
    """Own all pycaw/COM work on a dedicated worker thread.

    Windows can expose multiple audio sessions for one application. FaderDeck
    groups those sessions by application and VoiceMeeter bus so the UI shows
    one row per application while volume, mute, and live metering still apply
    to every underlying session.
    """

    topology_updated = Signal(object)
    peaks_updated = Signal(object)
    states_updated = Signal(object)
    route_finished = Signal(str)
    error = Signal(str)
    finished = Signal()

    FRIENDLY_NAMES = {
        "steam.exe": "Steam",
        "steamwebhelper.exe": "Steam Client Web",
        "discord.exe": "Discord",
        "signalrgb.exe": "SignalRGB",
        "signalrgbcore.exe": "SignalRGB Core",
        "brave.exe": "Brave Browser",
        "chatgpt.exe": "ChatGPT",
        "ms-teams.exe": "Microsoft Teams",
        "msteams.exe": "Microsoft Teams",
        "teams.exe": "Microsoft Teams",
        "msedgewebview2.exe": "Microsoft Edge WebView2",
        "msedge.exe": "Microsoft Edge",
        "chrome.exe": "Google Chrome",
        "firefox.exe": "Mozilla Firefox",
        "obs64.exe": "OBS Studio",
        "obs32.exe": "OBS Studio",
        "spotify.exe": "Spotify",
        "vlc.exe": "VLC media player",
        "explorer.exe": "Windows Explorer",
        "code.exe": "Visual Studio Code",
        "devenv.exe": "Visual Studio",
        "notepad.exe": "Notepad",
        "discordptb.exe": "Discord PTB",
        "discordcanary.exe": "Discord Canary",
    }

    def __init__(self):
        super().__init__()
        self.sessions = {}
        self.refresh_timer = None
        self.state_timer = None
        self._peak_thread = None
        self._peak_stop = threading.Event()
        self._session_lock = threading.RLock()
        self._com_initialized = False
        self._last_peak_emit = 0.0
        self._held_peaks = {}
        # Applications just moved to another channel, waiting for Windows to
        # re-bind their audio: {(exe name, exe path): {target, deadline, name}}
        self._pending_moves = {}
        self._fast_timer = None
        self._fast_scans_left = 0

    @staticmethod
    def friendly_name(app_name, display_name=""):
        """Return a stable human-friendly application name.

        Prefer a known executable mapping. If the executable is unknown, use
        a meaningful Windows session display name when available, otherwise
        turn the executable filename into a readable name rather than exposing
        a raw .exe filename.
        """
        raw = (app_name or "").strip()
        key = raw.casefold()
        mapped = ApplicationAudioWorker.FRIENDLY_NAMES.get(key)
        if mapped:
            return mapped

        session_name = (display_name or "").strip()
        if session_name and session_name.casefold() not in {key, f"{key}.exe"}:
            return session_name.removesuffix(".exe")

        base = os.path.splitext(raw)[0]
        # Drop build suffixes such as "warframe.x64" or "game-win64-shipping".
        base = re.sub(
            r"([ ._-]+(x64|x86|win64|win32|64bit|32bit|shipping))+$",
            "",
            base,
            flags=re.IGNORECASE,
        )
        base = re.sub(r"[._-]+", " ", base)
        base = " ".join(base.split())
        if not base:
            return "Unknown Application"
        return base.title()

    @Slot()
    def start(self):
        if not PYCAW_AVAILABLE:
            return

        try:
            import comtypes
            comtypes.CoInitialize()
            self._com_initialized = True
        except Exception as exc:
            self.error.emit(
                f"Audio worker COM initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self.refresh_sessions)
        self.refresh_timer.start()

        self._peak_stop.clear()
        self._peak_thread = threading.Thread(
            target=self._peak_loop,
            name="FaderDeck-AppPeakSampler",
            daemon=True,
        )
        self._peak_thread.start()

        self.state_timer = QTimer(self)
        self.state_timer.setInterval(500)
        self.state_timer.timeout.connect(self.update_states)
        self.state_timer.start()

        self.refresh_sessions()

    def _peak_loop(self):
        """Sample application peaks using a dedicated monotonic sleep loop."""
        next_sample = time.monotonic()
        interval = 0.010

        while not self._peak_stop.is_set():
            now = time.monotonic()
            if now < next_sample:
                self._peak_stop.wait(next_sample - now)
                continue

            self.update_peaks()
            next_sample += interval

            if next_sample < time.monotonic() - interval:
                next_sample = time.monotonic() + interval

    @Slot()
    def refresh_now(self):
        self.refresh_sessions()

    @staticmethod
    def bus_for_device(friendly_name):
        return ApplicationControl.bus_for_device(friendly_name)

    @staticmethod
    def _get_device_sessions(device):
        result = []
        try:
            manager = device.AudioSessionManager
            enumerator = manager.GetSessionEnumerator()
            count = enumerator.GetCount()
            for index in range(count):
                control = enumerator.GetSession(index)
                if control is None:
                    continue
                try:
                    from pycaw.pycaw import AudioSession
                    from pycaw.api.audiopolicy import IAudioSessionControl2
                    from pycaw.api.endpointvolume import IAudioMeterInformation

                    control2 = control.QueryInterface(IAudioSessionControl2)
                    session = AudioSession(control2)

                    meter = None
                    for meter_source in (control, control2):
                        try:
                            meter = meter_source.QueryInterface(
                                IAudioMeterInformation
                            )
                            if meter is not None:
                                break
                        except Exception:
                            continue

                    result.append((session, meter))
                except Exception:
                    continue
        except Exception as e:
            log.debug(f"Could not list the sessions of a device: {e}")
            return []
        return result

    @staticmethod
    def _session_key(bus, device, session, process):
        instance_id = getattr(session, "InstanceIdentifier", "") or ""
        endpoint_id = str(getattr(device, "id", "") or "")
        if instance_id:
            return (bus, instance_id)
        return (
            bus,
            endpoint_id,
            getattr(process, "pid", None),
            getattr(session, "Identifier", "") or "",
            getattr(session, "DisplayName", "") or "",
        )

    @staticmethod
    def _group_key(bus, app_name, executable_path):
        path = (executable_path or "").strip().casefold()
        if path:
            return (bus, app_name.casefold(), path)
        return (bus, app_name.casefold())

    @staticmethod
    def _find_bus_device(bus):
        """Return the active VoiceMeeter output device for a channel."""
        for device in war.list_output_devices():
            if ApplicationAudioWorker.bus_for_device(device.name) == bus:
                return device
        return None

    @staticmethod
    def _session_pid(session):
        try:
            pid = int(getattr(session, "ProcessId", 0) or 0)
            if pid:
                return pid
        except Exception:
            pass
        try:
            return int(session.Process.pid)
        except Exception:
            return 0

    @Slot(object, str)
    def route_application(self, session_key, target_bus):
        """Move an application's audio to another VoiceMeeter input.

        This sets Windows' per-app output device (the same setting as
        Settings > Sound > Volume mixer), so it persists until changed again.
        """
        with self._session_lock:
            info = self.sessions.get(session_key)
        if info is None or info["bus"] == target_bus:
            return
        name = info["display_name"]
        app_id = (
            info["app_name"],
            (info.get("executable_path") or "").casefold(),
        )
        if not APP_ROUTING_AVAILABLE:
            self.route_finished.emit(
                "Moving applications needs the winappaudiorouter package: "
                "pip install winappaudiorouter"
            )
            return
        try:
            device = self._find_bus_device(target_bus)
            if device is None:
                self.route_finished.emit(
                    f"Could not find the {target_bus} VoiceMeeter input device."
                )
                return
            pids = sorted({
                pid
                for pid in (
                    self._session_pid(member["session"])
                    for member in info.get("sessions", [])
                )
                if pid
            })
            if not pids:
                self.route_finished.emit(
                    f"{name} is no longer running, so it cannot be moved."
                )
                return
            moved = 0
            last_error = ""
            for pid in pids:
                try:
                    war.set_app_output_device(
                        process_id=pid,
                        device=device.id,
                    )
                    moved += 1
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
            if moved:
                self._pending_moves[app_id] = {
                    "target": target_bus,
                    "deadline": time.monotonic() + 300.0,
                    "name": name,
                }
                self.route_finished.emit(
                    f"Moving {name} to {target_bus}. Windows switches it when "
                    "the app next starts playback; its audio is not interrupted."
                )
            else:
                self.route_finished.emit(
                    f"Could not move {name} to {target_bus}: {last_error}"
                )
        except Exception as exc:
            self.route_finished.emit(
                f"Could not move {name} to {target_bus}: "
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            # Apps re-bind their audio on their own schedule, so keep
            # scanning for a while and update the moment it happens.
            self._start_fast_scans()

    def _drop_stale_sessions(self, found):
        """Resolve an application that shows on two channels after a move.

        Windows keeps an application's old session on the previous channel
        until the app next starts playback on the new one, so right after a
        move the same application can appear twice. A channel entry that is
        not playing is dropped when the same application is playing on, or
        was just moved to, another channel. An application that is still
        playing on its old channel stays visible there (that is where its
        audio really is) and is marked as moving until Windows switches it.
        """
        now = time.monotonic()
        pending = self._pending_moves
        for app_id in [k for k, v in pending.items() if v["deadline"] < now]:
            del pending[app_id]

        by_app = {}
        for group_key, info in found.items():
            app_id = (
                info["app_name"],
                (info.get("executable_path") or "").casefold(),
            )
            by_app.setdefault(app_id, []).append(group_key)

        for app_id, keys in by_app.items():
            move = pending.get(app_id)
            target = move["target"] if move else None

            if len(keys) > 1:
                active = [
                    k for k in keys
                    if any(m.get("state") == 1 for m in found[k]["sessions"])
                ]
                if len(active) == 1:
                    keep = set(active)
                elif not active and any(found[k]["bus"] == target for k in keys):
                    keep = {k for k in keys if found[k]["bus"] == target}
                else:
                    # Playing on several channels, or nothing to go on.
                    keep = set(keys)
                for k in keys:
                    if k not in keep:
                        del found[k]
                keys = [k for k in keys if k in keep]

            if move is None:
                continue
            if {found[k]["bus"] for k in keys} == {target}:
                self.route_finished.emit(f"{move['name']} is now on {target}.")
                del pending[app_id]
            else:
                for k in keys:
                    if found[k]["bus"] != target:
                        found[k]["moving_to"] = target

    def _start_fast_scans(self, count=90, interval_ms=1000):
        """Scan every second for a while after a move, then go back to normal.

        Scanning only reads the Windows session list; it never touches audio.
        """
        self._fast_scans_left = count
        if self._fast_timer is None:
            self._fast_timer = QTimer(self)
            self._fast_timer.timeout.connect(self._fast_scan)
        self._fast_timer.setInterval(interval_ms)
        self._fast_timer.start()
        QTimer.singleShot(300, self.refresh_sessions)

    def _fast_scan(self):
        self._fast_scans_left -= 1
        if self._fast_scans_left <= 0 or not self._pending_moves:
            self._fast_timer.stop()
        self.refresh_sessions()

    @staticmethod
    def _read_state(session):
        try:
            volume = float(session.SimpleAudioVolume.GetMasterVolume())
            muted = bool(session.SimpleAudioVolume.GetMute())
            return {
                "volume": max(0.0, min(1.0, volume)),
                "muted": muted,
            }
        except Exception:
            return None

    @staticmethod
    def _read_peak(meter):
        if meter is None:
            return None

        try:
            peak = meter.GetPeakValue()
            if isinstance(peak, tuple):
                peak = peak[0]
            return max(0.0, min(1.0, float(peak)))
        except Exception:
            return None

    @Slot()
    def refresh_sessions(self):
        if not PYCAW_AVAILABLE:
            return

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"COMError attempting to get property .*",
                    category=UserWarning,
                    module=r"pycaw\.utils",
                )
                devices = AudioUtilities.GetAllDevices(
                    data_flow=EDataFlow.eAll.value,
                    device_state=DEVICE_STATE.MASK_ALL.value,
                )

            found = {}
            seen_sessions = set()

            for device in devices:
                try:
                    data_flow = AudioUtilities.GetEndpointDataFlow(
                        device.id, outputType=1
                    )
                except Exception:
                    data_flow = EDataFlow.eRender.value

                if data_flow != EDataFlow.eRender.value:
                    continue

                friendly_device_name = getattr(device, "FriendlyName", None) or ""
                bus = self.bus_for_device(friendly_device_name)
                if bus is None:
                    continue

                for session, meter in self._get_device_sessions(device):
                    try:
                        process = session.Process
                        if process is None:
                            continue

                        name = process.name()
                        if not name:
                            continue

                        app_name = name.lower()
                        # This program, also when it runs as python.exe:
                        # the mute sound opens an audio session of its own.
                        if app_name in OWN_EXECUTABLES or process.pid == os.getpid():
                            continue
                        if getattr(session, "State", 1) == 2:
                            continue

                        session_key = self._session_key(
                            bus, device, session, process
                        )
                        if session_key in seen_sessions:
                            continue
                        seen_sessions.add(session_key)

                        try:
                            executable_path = process.exe() or ""
                        except Exception:
                            executable_path = ""

                        group_key = self._group_key(
                            bus,
                            app_name,
                            executable_path,
                        )

                        state = self._read_state(session) or {
                            "volume": 1.0,
                            "muted": False,
                        }

                        if group_key not in found:
                            display_name = self.friendly_name(
                                app_name,
                                getattr(session, "DisplayName", "") or "",
                            )
                            found[group_key] = {
                                "session_key": group_key,
                                "app_name": app_name,
                                "display_name": display_name,
                                "bus": bus,
                                "executable_path": executable_path,
                                "hide_key": stable_hide_key(executable_path, app_name),
                                "sessions": [],
                                "volume": state["volume"],
                                "muted": state["muted"],
                            }

                        found[group_key]["sessions"].append({
                            "session_key": session_key,
                            "session": session,
                            "meter": meter,
                            "volume": state["volume"],
                            "muted": state["muted"],
                            "pid": self._session_pid(session),
                            "state": getattr(session, "State", 1),
                        })
                    except Exception:
                        continue

            self._drop_stale_sessions(found)
            # Keep one stable application entry per executable + VoiceMeeter bus.
            # The individual Windows sessions remain available underneath it.
            for info in found.values():
                members = info["sessions"]
                if members:
                    info["volume"] = float(members[0]["volume"])
                    info["muted"] = all(
                        bool(member["muted"])
                        for member in members
                    )

            with self._session_lock:
                self.sessions = found

            snapshot = [
                {
                    "session_key": key,
                    "app_name": info["app_name"],
                    "display_name": info["display_name"],
                    "bus": info["bus"],
                    "executable_path": info["executable_path"],
                    "hide_key": info["hide_key"],
                    "moving_to": info.get("moving_to", ""),
                    "volume": info["volume"],
                    "muted": info["muted"],
                    "session_count": len(info["sessions"]),
                }
                for key, info in found.items()
            ]

            self.topology_updated.emit(snapshot)
            self.update_states()

        except Exception as exc:
            self.error.emit(
                f"VoiceMeeter application scan failed: "
                f"{type(exc).__name__}: {exc}"
            )

    @Slot()
    def update_peaks(self):
        """Sample every application meter. Runs on the peak thread only."""
        peaks = self._held_peaks
        with self._session_lock:
            session_items = list(self.sessions.items())

        for group_key, info in session_items:
            group_peak = 0.0
            meter_available = False
            for member in info.get("sessions", []):
                peak = self._read_peak(member.get("meter"))
                if peak is None:
                    continue
                meter_available = True
                group_peak = max(group_peak, peak)
            # Sampling is faster than GUI delivery, so keep the highest peak
            # seen since the last emit instead of only the latest sample.
            held = peaks.get(group_key)
            if not meter_available:
                peaks.setdefault(group_key, None)
            elif held is None or group_peak > held:
                peaks[group_key] = group_peak

        now = time.monotonic()
        if now - self._last_peak_emit >= (1.0 / 60.0):
            self._last_peak_emit = now
            self._held_peaks = {}
            self.peaks_updated.emit(peaks)

    @Slot()
    def update_states(self):
        states = {}
        with self._session_lock:
            session_items = list(self.sessions.items())

        for group_key, info in session_items:
            members = info.get("sessions", [])
            if not members:
                continue

            member_states = []
            for member in members:
                state = self._read_state(member["session"])
                if state is None:
                    continue
                member["volume"] = state["volume"]
                member["muted"] = state["muted"]
                member_states.append(state)

            if not member_states:
                continue

            info["volume"] = float(member_states[0]["volume"])
            info["muted"] = all(
                bool(state["muted"])
                for state in member_states
            )
            states[group_key] = {
                "volume": info["volume"],
                "muted": info["muted"],
            }

        if states:
            self.states_updated.emit(states)

    @Slot(object, str, float)
    def set_volume(self, session_key, bus, volume):
        info = self.sessions.get(session_key)
        if not info or info["bus"] != bus:
            return

        try:
            volume = max(0.0, min(1.0, float(volume)))
            successful = 0
            for member in info.get("sessions", []):
                try:
                    member["session"].SimpleAudioVolume.SetMasterVolume(
                        volume,
                        None,
                    )
                    member["volume"] = volume
                    successful += 1
                except Exception as e:
                    log.warning(f"Could not set the volume of one session: {e}")
                    continue

            if successful:
                info["volume"] = volume
                self.states_updated.emit({
                    session_key: {
                        "volume": volume,
                        "muted": bool(info["muted"]),
                    }
                })
        except Exception as exc:
            self.error.emit(
                f"Failed to set {info['display_name']} volume on {bus}: "
                f"{type(exc).__name__}: {exc}"
            )

    @Slot(object, str, bool)
    def set_mute(self, session_key, bus, muted):
        info = self.sessions.get(session_key)
        if not info or info["bus"] != bus:
            return

        try:
            successful = 0
            for member in info.get("sessions", []):
                try:
                    member["session"].SimpleAudioVolume.SetMute(
                        1 if muted else 0,
                        None,
                    )
                    member["muted"] = bool(muted)
                    successful += 1
                except Exception as e:
                    log.warning(f"Could not mute one session: {e}")
                    continue

            if successful:
                info["muted"] = bool(muted)
                self.states_updated.emit({
                    session_key: {
                        "volume": float(info["volume"]),
                        "muted": bool(muted),
                    }
                })
        except Exception as exc:
            self.error.emit(
                f"Failed to mute {info['display_name']} on {bus}: "
                f"{type(exc).__name__}: {exc}"
            )

    @Slot()
    def shutdown(self):
        if self.refresh_timer is not None:
            self.refresh_timer.stop()
        if self.state_timer is not None:
            self.state_timer.stop()
        if self._fast_timer is not None:
            self._fast_timer.stop()

        self._peak_stop.set()
        peak_thread = self._peak_thread
        if peak_thread is not None and peak_thread.is_alive():
            peak_thread.join(timeout=0.25)
        self._peak_thread = None

        with self._session_lock:
            self.sessions.clear()

        if self._com_initialized:
            try:
                import comtypes
                comtypes.CoUninitialize()
            except Exception:
                pass
            self._com_initialized = False

        self.finished.emit()


class ApplicationRow(QWidget):
    """One automatically detected Windows application group."""

    hide_requested = Signal(str, str, bool)

    # Rows are rebuilt whenever the session list changes; reading an icon
    # from its executable touches the disk, so do that once per application.
    _icon_cache = {}

    @classmethod
    def icon_pixmap(cls, executable_path):
        if executable_path not in cls._icon_cache:
            pixmap = None
            try:
                if executable_path and os.path.isfile(executable_path):
                    app_icon = QFileIconProvider().icon(
                        QFileInfo(executable_path)
                    )
                    pixmap = app_icon.pixmap(20, 20)
            except Exception:
                pixmap = None
            cls._icon_cache[executable_path] = pixmap
        return cls._icon_cache[executable_path]

    def __init__(
        self, session_key, app_name, display_name, bus, controller,
        executable_path="", volume=1.0, muted=False, hide_key="", hidden=False,
    ):
        super().__init__()
        self.session_key = session_key
        self.app_name = app_name
        self.display_name = ApplicationAudioWorker.friendly_name(
            self.app_name,
            display_name,
        )
        self.bus = bus
        self.controller = controller
        self.hide_key = hide_key or self.app_name.casefold()
        self.is_hidden = bool(hidden)
        self._drag_start = None
        self._syncing = False
        self._display_peak = 0.0
        self._peak_hold_until = 0.0
        self._last_meter_update = time.monotonic()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(1)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.setMaximumHeight(44)

        self.name_label = QLabel(self.display_name)
        self.name_label.setToolTip(
            f"{self.display_name} — routed to {bus} • drag to another channel to move it"
        )

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setToolTip(self.display_name)
        pixmap = self.icon_pixmap(executable_path)
        if pixmap is not None:
            self.icon_label.setPixmap(pixmap)

        self.volume_slider = LiveVolumeSlider(Qt.Orientation.Horizontal)
        self.volume_slider.thumb_color = STRIP_COLORS[bus]["accent"]
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setMinimumWidth(0)
        self.volume_slider.setFixedHeight(19)
        self.volume_slider.setToolTip(
            "Scroll for 1% volume steps. Blue handle sets app volume; "
            "green fill shows live audio level."
        )
        self.volume_slider.setStyleSheet(
            "QSlider::groove:horizontal { background: transparent; height: 6px; }"
            "QSlider::handle:horizontal { background: #58a6ff; width: 16px; "
            "margin: -5px 0; border-radius: 4px; }"
        )
        self.volume_slider.valueChanged.connect(self.on_volume_changed)

        self.volume_percent = QLabel("100%")
        self.volume_percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.volume_percent.setFixedWidth(36)
        self.volume_percent.setStyleSheet("color: #d6e2ef; font-size: 11px;")

        self.mute_button = QPushButton()
        self.mute_button.setIconSize(QSize(16, 16))
        self.mute_button.setCheckable(True)
        self.mute_button.setFixedSize(28, 24)
        self.mute_button.setStyleSheet(
            "QPushButton { background: #18232e; border: 1px solid #314558; "
            "border-radius: 6px; font-size: 14px; padding: 1px; }"
            "QPushButton:checked { background: #54262c; border-color: #a8434f; }"
        )
        self.mute_button.setToolTip("Mute this application")
        self.mute_button.clicked.connect(self.on_mute_clicked)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(4)
        heading.addWidget(self.icon_label)
        heading.addWidget(self.name_label, 1)
        heading.addWidget(self.mute_button)

        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(0)
        volume_row.addWidget(self.volume_slider, 1)
        volume_row.addWidget(self.volume_percent)

        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(2)
        layout.addLayout(heading)
        layout.addLayout(volume_row)

        self.apply_state({"volume": volume, "muted": muted})

    # Drag an application onto another channel column to move its audio there.
    # Only presses on the name/icon area start a drag; the volume slider and
    # the mute button keep their own mouse handling.
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_start).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            hot_spot = self._drag_start
            self._drag_start = None
            self._start_drag(hot_spot)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _start_drag(self, hot_spot):
        payload = json.dumps({"key": list(self.session_key), "bus": self.bus})
        mime = QMimeData()
        mime.setData(DRAG_MIME, QByteArray(payload.encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(hot_spot)
        self.controller.drag_started()
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.controller.drag_finished()

    def set_moving(self, target):
        """Mark this row as waiting for Windows to move it to another channel."""
        self.name_label.setStyleSheet("color: #d29922; font-style: italic;")
        self.name_label.setToolTip(
            f"{self.display_name} — moving to {target}. Windows switches it "
            "when the app next starts playback; pausing and resuming it "
            "speeds this up. Its audio is not interrupted."
        )

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.is_hidden:
            this_action = menu.addAction(f"Unhide on {channel_label(self.bus)}")
            all_action = menu.addAction("Unhide on all channels")
            hide = False
        else:
            this_action = menu.addAction(f"Hide on {channel_label(self.bus)}")
            all_action = menu.addAction("Hide on all channels")
            hide = True

        chosen = menu.exec(event.globalPos())
        if chosen is this_action:
            self.hide_requested.emit(self.hide_key, self.bus, hide)
        elif chosen is all_action:
            self.hide_requested.emit(self.hide_key, ALL_CHANNELS, hide)

    def _show_mute_icon(self, muted):
        set_mono_icon(
            self.mute_button, "speaker_off" if muted else "speaker", 16
        )

    def on_volume_changed(self, value):
        self.volume_percent.setText(f"{value}%")
        self.volume_slider.setToolTip(
            f"App volume: {value}% • scroll for 1% steps"
        )
        if not self._syncing:
            self.controller.set_app_volume(
                self.session_key,
                self.bus,
                value / 100.0,
            )

    def on_mute_clicked(self, checked):
        self._show_mute_icon(checked)
        if not self._syncing:
            self.controller.set_app_mute(
                self.session_key,
                self.bus,
                checked,
            )

    def apply_state(self, state):
        if state is None:
            return
        self._syncing = True
        try:
            value = int(round(state["volume"] * 100))
            self.volume_slider.setValue(value)
            self.volume_percent.setText(f"{value}%")
            self.mute_button.setChecked(state["muted"])
            self._show_mute_icon(state["muted"])
        finally:
            self._syncing = False

    def set_audio_level(self, peak):
        peak = 0.0 if peak is None else max(0.0, min(1.0, float(peak)))
        now = time.monotonic()
        elapsed = max(0.0, min(0.10, now - self._last_meter_update))
        self._last_meter_update = now

        if peak >= self._display_peak:
            self._display_peak = peak
            if peak > 0.001:
                self._peak_hold_until = now + 0.045
        elif now >= self._peak_hold_until:
            self._display_peak = max(
                peak,
                self._display_peak * math.exp(-elapsed / 0.12),
            )

        level_db = -60.0 if self._display_peak <= 0.001 else 20.0 * math.log10(self._display_peak)
        level_db = max(-60.0, min(0.0, level_db))
        self.volume_slider.set_audio_level(
            (level_db + 60.0) / 60.0
        )


class ApplicationDropColumn(QWidget):
    """One channel column; accepts applications dragged from another channel."""

    application_dropped = Signal(object, str, str)  # key, source bus, target bus

    def __init__(self, bus, colors):
        super().__init__()
        self.bus = bus
        self.setObjectName("applicationBusCard")
        self._normal_style = (
            "QWidget#applicationBusCard {"
            f"background: #101820; border: 1px solid {colors['border']}; "
            "border-radius: 8px; }"
        )
        self._highlight_style = (
            "QWidget#applicationBusCard {"
            f"background: {colors['header']}; border: 1px solid {colors['accent']}; "
            "border-radius: 8px; }"
        )
        self.setStyleSheet(self._normal_style)
        self.setAcceptDrops(True)

    @staticmethod
    def _payload(mime):
        """Return (session_key, source_bus) from a dragged application."""
        if not mime.hasFormat(DRAG_MIME):
            return None
        try:
            data = json.loads(bytes(mime.data(DRAG_MIME)).decode("utf-8"))
            return tuple(data["key"]), str(data["bus"])
        except Exception:
            return None

    def _accepts(self, event):
        payload = self._payload(event.mimeData())
        return payload is not None and payload[1] != self.bus

    def dragEnterEvent(self, event):
        if self._accepts(event):
            self.setStyleSheet(self._highlight_style)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._normal_style)
        event.accept()

    def dropEvent(self, event):
        self.setStyleSheet(self._normal_style)
        payload = self._payload(event.mimeData())
        if payload is None or payload[1] == self.bus:
            event.ignore()
            return
        event.acceptProposedAction()
        self.application_dropped.emit(payload[0], payload[1], self.bus)


class ApplicationControl(QWidget):
    """Detect VoiceMeeter application sessions without blocking the Qt thread."""

    BUS_NAMES = ("Game", "Chat", "Media")

    DEVICE_PATTERNS = {
        "Game": (
            "voicemeeter input",
            "game (vb-audio voicemeeter vaio)",
        ),
        "Chat": (
            "voicemeeter aux input",
            "chat (vb-audio voicemeeter vaio)",
        ),
        "Media": (
            "voicemeeter vaio3 input",
            "media (vb-audio voicemeeter vaio)",
        ),
    }

    refresh_requested = Signal()
    volume_requested = Signal(object, str, float)
    mute_requested = Signal(object, str, bool)
    route_requested = Signal(object, str)
    shutdown_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setVisible(False)
        self.sessions = {}
        self.rows = {name: {} for name in self.BUS_NAMES}
        self.titles = {}
        self._topology_signature = None
        self._closing = False
        # Hiding is per virtual channel: the same application can be hidden
        # on Game but still visible on Chat. "Show hidden" is per channel too.
        self.show_hidden = {bus: False for bus in self.BUS_NAMES}
        self.bus_hidden_buttons = {}
        self._drag_active = False
        self._notice_text = ""
        self._notice_until = 0.0
        self.settings = app_settings()
        self._hidden_needs_save = False
        self.hidden_applications = self._load_hidden_applications()
        if (
            self._hidden_needs_save
            or self.settings.value("hidden_applications_v2", None) is None
        ):
            # First launch of a newer format: store the migrated list.
            self._save_hidden_applications()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 5)
        layout.setSpacing(4)

        if not PYCAW_AVAILABLE:
            missing = QLabel(
                "Application controls require pycaw. Install it with: pip install pycaw"
            )
            missing.setStyleSheet("color: #f0883e;")
            layout.addWidget(missing)
            self.worker_thread = None
            self.worker = None
            return

        self._build_toolbar(layout)
        self._build_columns(layout)
        self._start_worker()

    def _build_toolbar(self, layout):
        """Status line, show-hidden and REFRESH."""
        toolbar = QHBoxLayout()
        self.status_label = QLabel("Scanning VoiceMeeter audio sessions...")
        self.status_label.setStyleSheet("color: #8b949e;")
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.request_refresh)

        self.hidden_button = QPushButton()
        self.hidden_button.setCheckable(True)
        self.hidden_button.setFixedSize(32, 28)
        self.hidden_button.setIcon(reference_eye_icon(20))
        self.hidden_button.setIconSize(QSize(20, 20))
        self.hidden_button.setToolTip("Show hidden applications")
        self.hidden_button.clicked.connect(self.toggle_hidden_visibility)
        self.hidden_button.setStyleSheet(EYE_BUTTON_STYLE)

        toolbar.addWidget(self.status_label, 1)
        toolbar.addWidget(self.hidden_button)
        toolbar.addWidget(refresh_button)
        layout.addLayout(toolbar)

    def _build_columns(self, layout):
        """One drop column per channel, with its title, eye button and list."""
        columns = QHBoxLayout()
        columns.setSpacing(4)
        self.bus_layouts = {}
        self.bus_containers = {}

        for bus in self.BUS_NAMES:
            colors = STRIP_COLORS[bus]
            box = ApplicationDropColumn(bus, colors)
            box.application_dropped.connect(self.on_application_dropped)
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(3, 3, 3, 3)
            box_layout.setSpacing(1)

            endpoint = {
                "Game": "VoiceMeeter VAIO",
                "Chat": "VoiceMeeter VAIO AUX",
                "Media": "VoiceMeeter VAIO3",
            }[bus]
            title = QLabel(f"{channel_label(bus).upper()} APPS")
            self.titles[bus] = title
            title.setToolTip(f"Applications playing on {endpoint}")
            title.setStyleSheet(
                f"color: {colors['accent']}; background: {colors['header']}; "
                f"border: 1px solid {colors['border']}; border-radius: 5px; "
                "padding: 3px 5px; font-weight: bold;"
            )
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(3)
            header_row.addWidget(title, 1)

            bus_eye = QPushButton()
            bus_eye.setCheckable(True)
            bus_eye.setFixedSize(30, 26)
            bus_eye.setIcon(reference_eye_icon(18))
            bus_eye.setIconSize(QSize(18, 18))
            bus_eye.setToolTip(f"Show hidden applications on {bus}")
            bus_eye.setStyleSheet(EYE_BUTTON_STYLE)
            bus_eye.clicked.connect(
                lambda checked, b=bus: self.set_show_hidden(b, checked)
            )
            header_row.addWidget(bus_eye)
            self.bus_hidden_buttons[bus] = bus_eye

            box_layout.addLayout(header_row)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            # Let the column card show through instead of the default grey.
            scroll.setStyleSheet("QScrollArea { background: transparent; }")
            scroll.viewport().setAutoFillBackground(False)

            container = QWidget()
            container.setStyleSheet("background: transparent; border: none;")
            bus_layout = QVBoxLayout(container)
            bus_layout.setContentsMargins(0, 0, 0, 0)
            bus_layout.setSpacing(1)
            bus_layout.addStretch()
            scroll.setWidget(container)

            box_layout.addWidget(scroll, 1)
            columns.addWidget(box, 1)
            self.bus_layouts[bus] = bus_layout
            self.bus_containers[bus] = container

        layout.addLayout(columns, 1)

    def _start_worker(self):
        """Run the session worker on its own thread and connect it."""
        self.worker_thread = QThread(self)
        self.worker = ApplicationAudioWorker()
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.start)
        self.refresh_requested.connect(self.worker.refresh_now)
        self.volume_requested.connect(self.worker.set_volume)
        self.mute_requested.connect(self.worker.set_mute)
        self.route_requested.connect(self.worker.route_application)
        self.worker.route_finished.connect(self.on_route_finished)
        self.shutdown_requested.connect(self.worker.shutdown)

        self.worker.topology_updated.connect(self.on_topology_updated)
        self.worker.peaks_updated.connect(self.on_peaks_updated)
        self.worker.states_updated.connect(self.on_states_updated)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.worker_thread.quit)

        self.worker_thread.start()

    @classmethod
    def bus_for_device(cls, friendly_name):
        name = (friendly_name or "").lower()
        normalized = " ".join(name.split())
        for bus in ("Media", "Chat", "Game"):
            for pattern in cls.DEVICE_PATTERNS[bus]:
                if pattern in normalized:
                    return bus
        return None

    @staticmethod
    def _parse_hidden_setting(raw):
        if isinstance(raw, str):
            try:
                values = json.loads(raw) if raw else []
            except Exception:
                values = []
        elif isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            values = []

        return {
            str(value).casefold()
            for value in values
            if str(value).strip()
        }

    @staticmethod
    def _hide_id(bus, hide_key):
        """Identifier for one application on one virtual channel."""
        return f"{bus}|{(hide_key or '').strip()}".casefold()

    def _is_hidden(self, info):
        base = info.get("hide_key", "") or info.get("app_name", "")
        return self._hide_id(info["bus"], base) in self.hidden_applications

    def _load_hidden_applications(self):
        raw = self.settings.value("hidden_applications_v2", None)
        if raw is not None:
            stored = self._parse_hidden_setting(raw)
            # Entries saved before hide keys ignored version folders are
            # rewritten once, so they keep matching after an update.
            current = set()
            for hide_id in stored:
                bus, _, key = hide_id.partition("|")
                current.add(self._hide_id(bus, stable_hide_key(key)))
            self._hidden_needs_save = current != stored
            return current
        return set()

    def _save_hidden_applications(self):
        self.settings.setValue(
            "hidden_applications_v2",
            json.dumps(sorted(self.hidden_applications)),
        )
        self.settings.sync()

    def toggle_hidden_visibility(self, checked):
        """Master eye button: show or hide hidden applications everywhere."""
        self.set_show_hidden(None, checked)

    def set_show_hidden(self, bus, checked):
        """Show hidden applications on one channel (or all when bus is None)."""
        buses = self.BUS_NAMES if bus is None else (bus,)
        for name in buses:
            self.show_hidden[name] = bool(checked)
        self._sync_hidden_buttons()
        self.rebuild_rows()
        self.update_status()

    def _sync_hidden_buttons(self):
        for name, button in self.bus_hidden_buttons.items():
            shown = self.show_hidden[name]
            button.setChecked(shown)
            button.setToolTip(
                f"Hide hidden applications on {name}"
                if shown
                else f"Show hidden applications on {name}"
            )

        all_shown = all(self.show_hidden.values())
        self.hidden_button.setChecked(all_shown)
        self.hidden_button.setToolTip(
            "Hide hidden applications on all channels"
            if all_shown
            else "Show hidden applications on all channels"
        )

    def on_hide_requested(self, hide_key, scope, hidden):
        """Hide or unhide an application on one channel or on all channels.

        "All channels" covers every channel, including ones the application
        is not routed to right now, so it stays hidden if its routing changes.
        """
        hide_key = str(hide_key or "").strip()
        if not hide_key:
            return

        buses = self.BUS_NAMES if scope == ALL_CHANNELS else (scope,)
        for bus in buses:
            if bus not in self.BUS_NAMES:
                continue
            hide_id = self._hide_id(bus, hide_key)
            if hidden:
                self.hidden_applications.add(hide_id)
            else:
                self.hidden_applications.discard(hide_id)

        self._save_hidden_applications()
        self.rebuild_rows()
        self.update_status()

    def update_status(self):
        if time.monotonic() < self._notice_until:
            self.status_label.setText(self._notice_text)
            return
        visible = [
            info
            for info in self.sessions.values()
            if (
                self.show_hidden[info["bus"]]
                or not self._is_hidden(info)
            )
        ]

        self._show_hidden_counts()

        total = len(visible)
        noun = "application" if total == 1 else "applications"
        self.status_label.setText(f"{total} {noun} routed through VoiceMeeter")

    def _show_hidden_counts(self):
        """Show on each eye button how many applications it would reveal."""
        hidden = {bus: 0 for bus in self.BUS_NAMES}
        for info in self.sessions.values():
            if self._is_hidden(info):
                hidden[info["bus"]] += 1

        for bus, button in self.bus_hidden_buttons.items():
            button.setText(str(hidden[bus]) if hidden[bus] else "")
            button.setFixedWidth(46 if hidden[bus] else 30)

        total = sum(hidden.values())
        self.hidden_button.setText(str(total) if total else "")
        self.hidden_button.setFixedWidth(48 if total else 32)

    def request_refresh(self):
        if not self._closing and self.worker_thread is not None:
            self.status_label.setText("Scanning VoiceMeeter applications...")
            self.refresh_requested.emit()

    def drag_started(self):
        self._drag_active = True

    def drag_finished(self):
        self._drag_active = False

    def _volume_slider_in_use(self):
        return any(
            row.volume_slider.isSliderDown()
            for rows in self.rows.values()
            for row in rows.values()
        )

    def _show_notice(self, text, seconds=8.0):
        """Show a short message in the status line, ahead of the counts."""
        self._notice_text = text
        self._notice_until = time.monotonic() + seconds
        self.status_label.setText(text)

    def on_application_dropped(self, session_key, source_bus, target_bus):
        """An application row was dropped on another channel's column."""
        if self._closing or self.worker_thread is None:
            return
        info = self.sessions.get(session_key)
        if info is None or info["bus"] != source_bus or source_bus == target_bus:
            return
        if not APP_ROUTING_AVAILABLE:
            self._show_notice(
                "Moving applications needs the winappaudiorouter package: "
                "pip install winappaudiorouter"
            )
            return
        self._show_notice(f"Moving {info['display_name']} to {target_bus}...")
        self.route_requested.emit(session_key, target_bus)

    def on_route_finished(self, message):
        if not self._closing:
            self._show_notice(message)

    def on_worker_error(self, message):
        if not self._closing:
            self.status_label.setText(message)
        log.error(message)

    def on_topology_updated(self, snapshot):
        if self._closing:
            return

        self.sessions = {
            item["session_key"]: item
            for item in snapshot
        }

        signature = tuple(
            sorted(
                (key, info["bus"], info.get("moving_to") or "")
                for key, info in self.sessions.items()
            )
        )

        if signature != self._topology_signature:
            if self._drag_active or self._volume_slider_in_use():
                # Never rebuild rows while one is being dragged or its
                # volume slider is held; the next scan applies the change.
                self.update_status()
                return
            self._topology_signature = signature
            self.rebuild_rows()
        else:
            self.sync_rows()

        self.update_status()

    def on_peaks_updated(self, peaks):
        if self._closing or not self.isVisible():
            return
        for bus in self.BUS_NAMES:
            for session_key, row in self.rows[bus].items():
                row.set_audio_level(peaks.get(session_key))

    def on_states_updated(self, states):
        if self._closing:
            return
        for session_key, state in states.items():
            info = self.sessions.get(session_key)
            if info is not None:
                info["volume"] = state["volume"]
                info["muted"] = state["muted"]
            for bus in self.BUS_NAMES:
                row = self.rows[bus].get(session_key)
                if row is not None:
                    row.apply_state(state)
                    break

    def rebuild_rows(self):
        for bus in self.BUS_NAMES:
            self.clear_layout(self.bus_layouts[bus])
            self.rows[bus].clear()

        for session_key, info in sorted(
            self.sessions.items(),
            key=lambda item: (
                item[1]["display_name"].lower(),
                repr(item[0]),
            ),
        ):
            hide_key = info.get("hide_key", "") or info["app_name"]
            hidden = (
                self._hide_id(info["bus"], hide_key) in self.hidden_applications
            )

            if hidden and not self.show_hidden[info["bus"]]:
                continue

            row = ApplicationRow(
                session_key,
                info["app_name"],
                info["display_name"],
                info["bus"],
                self,
                info.get("executable_path", ""),
                info.get("volume", 1.0),
                info.get("muted", False),
                hide_key,
                hidden,
            )
            row.hide_requested.connect(self.on_hide_requested)

            if hidden:
                row.name_label.setStyleSheet(
                    "color: #8b949e; font-style: italic;"
                )
                row.name_label.setToolTip(
                    f"{row.display_name} — hidden application — routed to {row.bus} • drag to move"
                )

            if info.get("moving_to"):
                row.set_moving(info["moving_to"])
            bus = info["bus"]
            self.bus_layouts[bus].insertWidget(
                self.bus_layouts[bus].count() - 1,
                row,
            )
            self.rows[bus][session_key] = row

        for bus in self.BUS_NAMES:
            if not self.rows[bus]:
                hint = QLabel("No applications\nDrag one here to move it")
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hint.setStyleSheet(
                    "color: #6b7c8d; font-size: 11px; padding: 14px 4px;"
                )
                self.bus_layouts[bus].insertWidget(0, hint)

    def clear_layout(self, layout):
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def get_app_state(self, session_key, bus):
        info = self.sessions.get(session_key)
        if not info or info["bus"] != bus:
            return None
        return {
            "volume": float(info.get("volume", 1.0)),
            "muted": bool(info.get("muted", False)),
        }

    def set_app_volume(self, session_key, bus, volume):
        if self.worker_thread is not None and not self._closing:
            self.volume_requested.emit(session_key, bus, float(volume))

    def set_app_mute(self, session_key, bus, muted):
        if self.worker_thread is not None and not self._closing:
            self.mute_requested.emit(session_key, bus, bool(muted))

    def sync_rows(self):
        for bus in self.BUS_NAMES:
            for row in self.rows[bus].values():
                row.apply_state(self.get_app_state(row.session_key, bus))

    def close(self):
        if self._closing:
            return
        self._closing = True

        thread = self.worker_thread
        worker = self.worker
        if thread is None or worker is None:
            self.worker = None
            self.worker_thread = None
            return

        try:
            # Execute shutdown inside the worker thread and wait only for the
            # actual cleanup call to return. This avoids the old pattern of
            # waiting up to two seconds for a queued shutdown request.
            QMetaObject.invokeMethod(
                worker,
                "shutdown",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
        except Exception:
            # If the worker has already stopped, simply make sure its event
            # loop is asked to exit.
            pass

        thread.quit()
        thread.wait(300)

        self.worker = None
        self.worker_thread = None


class StripLevelWorker(QObject):
    """Read the level of every strip on a dedicated worker thread.

    This worker is the only place levels are read; the GUI thread never
    queries VoiceMeeter for them.
    """

    levels_received = Signal(str, float, float)  # strip name, left, right
    error = Signal(str)
    finished = Signal()

    def __init__(self, vm):
        super().__init__()
        self.vm = vm
        self.timer = None
        self._last_levels = {}

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.read_levels)
        self.timer.start()
        self.read_levels()

    @staticmethod
    def _left_right(raw_levels):
        """Reduce VoiceMeeter's per-channel levels to a left/right pair.

        Hardware strips report two channels and virtual strips eight; the
        first two are front left and right.
        """
        if isinstance(raw_levels, (tuple, list)):
            levels = [
                float(value)
                for value in raw_levels
                if isinstance(value, (int, float))
            ]
        elif isinstance(raw_levels, (int, float)):
            levels = [float(raw_levels)]
        else:
            levels = []

        if not levels:
            return -200.0, -200.0
        if len(levels) == 1:
            return levels[0], levels[0]
        return levels[0], levels[1]

    @Slot()
    def read_levels(self):
        try:
            for name, index in STRIPS.items():
                pair = self._left_right(self.vm.strip[index].levels.prefader)
                # VoiceMeeter's level cache refreshes more slowly than this
                # timer, so most reads repeat the previous one.
                if pair != self._last_levels.get(name):
                    self._last_levels[name] = pair
                    self.levels_received.emit(name, pair[0], pair[1])
        except Exception as exc:
            self.error.emit(
                f"Level worker read failed: {type(exc).__name__}: {exc}"
            )

    @Slot()
    def stop(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.finished.emit()


# The streaming setup. New users meet VoiceMeeter's devices in Windows,
# Discord and OBS under names such as "Voicemeeter Out B2" and cannot tell
# which is which, or why. This window explains it, routes it in one go, and
# says what to pick in each program, by the names Windows shows by default.
# Each name says what pressing the routing button does: you hear the channel,
# it goes to your voice call, or to the stream as its mic or into its mix.
STREAM_SETUP_HEAR = "Hear"
STREAM_SETUP_NAMES = {"B1": "Call", "B2": "Str. mic", "B3": "Str. mix"}

STREAM_SETUP_STEPS = """
<p style="margin-top:0"><b>How it works.</b> VoiceMeeter's <b>A outputs</b> are devices
you hear, such as your headphones. Its <b>B outputs</b> are like cables into other
programs: Windows lists them as microphones called <i>Voicemeeter Out B1</i>,
<i>B2</i> and <i>B3</i>, and your call program or OBS picks one.</p>
<table cellspacing="0" cellpadding="3">
<tr><td><b>Your microphone</b></td><td>&rarr; B1 <i>(Call)</i> &rarr; your voice call: Discord, TeamSpeak, Zoom&hellip;</td></tr>
<tr><td></td><td>&rarr; B2 <i>(Str. mic)</i> &rarr; your stream: your voice</td></tr>
<tr><td><b>Game, Chat, Media</b></td><td>&rarr; your headphones <i>(Hear)</i></td></tr>
<tr><td></td><td>&rarr; B3 <i>(Str. mix)</i> &rarr; your stream: game, chat and music</td></tr>
</table>
<p>Your voice and the sound reach the stream separately, so you can filter
your voice alone, mute it for the stream only, and give the stream its own mix.</p>
"""

STREAM_SETUP_PROGRAMS = """
<p style="margin-top:0"><b>Then pick these in your programs</b> (the names Windows
gives them; if you renamed them, look for your name):</p>
<p><b>Windows</b>, Settings, Sound, Output: <i>Voicemeeter Input</i>. Programs
play into the Game channel unless you move them.</p>
<p><b>Your call program</b> (Discord, TeamSpeak, Zoom&hellip;), in its voice or
audio settings:<br>
Input device or microphone: <i>Voicemeeter Out B1</i><br>
Output device or speaker: <i>Voicemeeter AUX Input</i> (the Chat channel)</p>
<p><b>Music or a browser</b>: drag it to the Media column in FaderDeck, or pick
<i>Voicemeeter VAIO3 Input</i> as its output.</p>
<p><b>OBS</b>:<br>
Settings, Audio: set Desktop Audio to <i>Disabled</i>, and remove any
Application Audio Capture sources: OBS would hear everything twice.<br>
Sources, +, Audio Input Capture: <i>Voicemeeter Out B2</i> (your voice).<br>
Sources, +, Audio Input Capture: <i>Voicemeeter Out B3</i> (the sound).</p>
"""


WELCOME = True  # greet a new user; the tests switch it off


class VoicemeeterMissingDialog(QDialog):
    """Shown at start while VoiceMeeter Potato is not installed: FaderDeck
    is a remote for it and can do nothing on its own."""

    def __init__(self, window, state):
        super().__init__(window)
        self.setWindowTitle("VoiceMeeter Potato is missing")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel("It looks like VoiceMeeter Potato is missing")
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        title.setWordWrap(True)
        layout.addWidget(title)

        if state == "other":
            found = (
                "VoiceMeeter is installed on this PC, but not the Potato "
                "edition. FaderDeck needs Potato: it uses its three virtual "
                "inputs (Game, Chat, Media) and its outputs B1 to B3."
            )
        else:
            found = (
                "FaderDeck could not find VoiceMeeter Potato on this PC. "
                "FaderDeck is a remote for it: VoiceMeeter does the mixing, "
                "FaderDeck gives you the faders, mute buttons and routing."
            )
        text = QLabel(
            found + "<br><br>"
            "VoiceMeeter Potato is made by VB-Audio and free to use "
            "(donationware). To set it up:"
            "<ol style='margin-left: -20px;'>"
            "<li>Download and run the VoiceMeeter Potato installer.</li>"
            "<li>Restart your PC: its audio drivers need that.</li>"
            "<li>Start VoiceMeeter Potato. FaderDeck connects by itself.</li>"
            "</ol>"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(text)

        buttons = QDialogButtonBox()
        self.download_button = buttons.addButton(
            "Download VoiceMeeter Potato", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.download_button.setToolTip(VOICEMEETER_DOWNLOAD_URL)
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        self.download_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


# What the mute badge and the tray icon show: (text, colour) per state.
MUTE_INDICATORS = {
    "muted": ("Mic muted", "#f85149"),
    "stream": ("Not on stream", "#f0883e"),
}


def mute_indicator_state(mic_muted, stream_muted):
    """Which warning the badge and the tray icon show: "muted", "stream" or
    None for nothing. stream_muted is None when no stream output is set."""
    if mic_muted:
        return "muted"  # nobody hears you: the bigger warning wins
    if stream_muted:
        return "stream"  # None (no stream output set) is no warning
    return None


def badged_icon(icon, colour, size=32):
    """The tray icon with a coloured dot holding a crossed-out microphone."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, icon.pixmap(size, size))
    dot = size * 0.62
    box = QRectF(size - dot, size - dot, dot, dot)
    painter.setPen(QPen(QColor("#0d1117"), size * 0.06))
    painter.setBrush(QColor(colour))
    painter.drawEllipse(box.adjusted(1, 1, -1, -1))
    mic = dot * 0.62
    QSvgRenderer(QByteArray(
        MONO_ICONS["mic_off"].replace("#d7e1eb", "#ffffff").encode("utf-8")
    )).render(painter, QRectF(box.center().x() - mic / 2,
                              box.center().y() - mic / 2, mic, mic))
    painter.end()
    return QIcon(pixmap)


class MuteBadge(QWidget):
    """A small label that stays on top of other windows while the
    microphone is muted. It never takes the focus, so a game keeps the
    keyboard. Drag it to move it; moved() reports where it was left."""

    moved = Signal(object)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("FaderDeck. Drag to move; turn it off in Settings, Microphone.")
        self.state = None
        self._grab = None
        font = QFont(self.font())
        font.setPointSize(11)
        font.setBold(True)
        self.setFont(font)
        self.icon = _svg_icon(MONO_ICONS["mic_off"].replace("#d7e1eb", "#ffffff"), 18)

    def set_state(self, state):
        self.state = state
        text = MUTE_INDICATORS[state][0]
        width = QFontMetricsF(self.font()).horizontalAdvance(text)
        self.setFixedSize(int(width) + 58, 38)
        self.update()

    def place(self, point=None):
        """Put it at point when that is on a screen; else top centre."""
        screen = QApplication.screenAt(point) if point is not None else None
        if screen is None:
            area = QApplication.primaryScreen().availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.top() + 24)
        else:
            area = screen.availableGeometry()
            self.move(
                min(max(point.x(), area.left()), area.right() - self.width()),
                min(max(point.y(), area.top()), area.bottom() - self.height()),
            )

    def paintEvent(self, _event):
        if self.state is None:
            return
        text, colour = MUTE_INDICATORS[self.state]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(colour)
        fill.setAlpha(235)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 19, 19)
        self.icon.paint(painter, 14, 10, 18, 18)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(40, 0, self.width() - 52, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._grab = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._grab is not None:
            self.move(event.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, _event):
        if self._grab is not None:
            self._grab = None
            self.moved.emit(self.pos())


class WelcomeDialog(QDialog):
    """Shown once, the first time FaderDeck's window opens: not everyone
    goes looking in the settings, and the streaming setup is where most
    people should start."""

    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Welcome to FaderDeck")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(_svg_icon(LOGO_SVG, 40).pixmap(40, 40))
        title_row.addWidget(logo)
        title = QLabel("Welcome to FaderDeck")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_row.addWidget(title, 1)
        layout.addLayout(title_row)

        text = QLabel(
            "FaderDeck controls VoiceMeeter Potato for you: a fader, mute and "
            "routing for your microphone, game, chat and media, without "
            "opening VoiceMeeter.<br><br>"
            "<b>Do you stream, or talk in a voice call?</b> Start with the "
            "streaming setup. In one click it sends your voice to your call "
            "and your stream, and your game, chat and music to your "
            "headphones and your stream. Then it tells you what to pick in "
            "your call program and in OBS."
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(text)

        later = QLabel("You can open it later from Settings, Microphone.")
        later.setObjectName("settingsNote")
        later.setStyleSheet("color: #8ba0b5; font-size: 11px;")
        layout.addWidget(later)

        buttons = QDialogButtonBox()
        self.setup_button = buttons.addButton(
            "Set up for streaming", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton("Not now", QDialogButtonBox.ButtonRole.RejectRole)
        self.setup_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class StreamSetupDialog(QDialog):
    """Explains the streaming routing and sets it up in one go."""

    def __init__(self, window, vm=None):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("FaderDeck — Streaming setup")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        steps = QLabel(STREAM_SETUP_STEPS)
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(steps)

        form = QFormLayout()
        self.headphones = QComboBox()
        for output in available_outputs(vm):
            if output in HARDWARE_OUTPUTS:
                device = output_device(vm, output)
                self.headphones.addItem(f"{output} · {device}" if device else output, output)
        if not self.headphones.count():
            self.headphones.addItem("A1", "A1")
        self.headphones.setCurrentIndex(
            max(0, self.headphones.findData(window.listen_bus_setting()))
        )
        form.addRow("Your headphones are on", self.headphones)
        self.name_outputs = QCheckBox(
            "Name the routing buttons for what they do: Hear, Call, Str. mic, Str. mix"
        )
        self.name_outputs.setChecked(True)
        form.addRow(self.name_outputs)
        layout.addLayout(form)

        self.apply_button = QPushButton("Apply this routing")
        self.apply_button.setStyleSheet("QPushButton { padding: 6px 14px; font-weight: bold; }")
        self.apply_button.clicked.connect(self.apply)
        self.status = QLabel(
            "Changes the routing of all four channels. Your faders and "
            "setup profiles are not touched."
        )
        self.status.setObjectName("settingsNote")
        self.status.setWordWrap(True)
        apply_row = QHBoxLayout()
        apply_row.addWidget(self.apply_button)
        apply_row.addWidget(self.status, 1)
        layout.addLayout(apply_row)

        programs = QLabel(STREAM_SETUP_PROGRAMS)
        programs.setWordWrap(True)
        programs.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(programs)

        sound_settings = QPushButton("Open Windows sound settings")
        sound_settings.setToolTip(
            "To give the VoiceMeeter devices names of your own: Recording, "
            "right-click a device, Properties."
        )
        sound_settings.clicked.connect(
            lambda: subprocess.Popen(["control", "mmsys.cpl"], close_fds=True)
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(sound_settings)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

    def apply(self):
        problem = self.window.apply_stream_setup(
            self.headphones.currentData(), self.name_outputs.isChecked()
        )
        self.status.setText(problem or (
            "Done. Your voice is on B1 and B2, the sound on your headphones "
            "and B3, and the You / Stream switch is in the header. Now pick "
            "the devices below in your programs."
        ))


class SettingsDialog(QDialog):
    """Program settings. values() returns what the user chose."""

    def __init__(self, parent, current, vm=None):
        super().__init__(parent)
        self.setWindowTitle("FaderDeck — Settings")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(560, 520)
        self.setStyleSheet(
            "QLabel#settingsNote { color: #8ba0b5; font-size: 11px; }"
            "QLabel#settingsHeading { color: #8ba0b5; font-size: 11px; "
            "font-weight: bold; padding-top: 8px; }"
            "QTabWidget::pane { border: 1px solid #30363d; "
            "border-radius: 6px; background: #0d141b; }"
            "QTabBar::tab { background: #18232e; color: #aebdca; "
            "border: 1px solid #30363d; padding: 6px 16px; }"
            "QTabBar::tab:selected { background: #1769aa; color: #ffffff; "
            "border-color: #35a7ff; }"
            "QScrollArea, QScrollArea > QWidget > QWidget "
            "{ background: transparent; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._build_general_tab(current, vm)
        self._build_appearance_tab(current)
        self._build_hotkeys_tab(current)
        self._build_remote_tab(current)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #f85149;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # A combo box asks to be as wide as its longest item (a device name),
        # which pushed the rows past the window's edge. Shrink and elide.
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(12)
        self.fit_tabs()

    def tab_content_height(self, page):
        """Height a tab's content needs at the window's width. Wrapped
        notes are taller in a narrow window than Qt's rough estimate."""
        content = page.widget() if isinstance(page, QScrollArea) else page
        width = max(self.width() - 60, 300)  # the page's own width is 640 until shown
        layout = content.layout()
        if layout is not None and layout.hasHeightForWidth():
            return layout.totalHeightForWidth(width)
        return content.sizeHint().height()

    def fit_tabs(self):
        """Open tall enough that every tab but Hotkeys shows without scrolling."""
        tallest = 0
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == "Hotkeys":
                continue  # a long list; it scrolls
            tallest = max(tallest, self.tab_content_height(self.tabs.widget(index)))
        around = (
            self.tabs.tabBar().sizeHint().height()
            + self.sizeHint().height() - self.tabs.sizeHint().height()
            + 24  # the tab frame
        )
        wanted = tallest + around
        screen = self.screen()
        if screen is not None:
            wanted = min(wanted, screen.availableGeometry().height() - 60)
        # Only grow: a status line that changed must not make it jump smaller.
        self.resize(max(self.width(), 560), max(wanted, self.minimumHeight(), self.height()))

    def _build_general_tab(self, current, vm):
        """A Microphone tab (input, listening, stream, chime) and a General
        tab (channel names, window, updates)."""
        self.form = self.add_tab("Microphone", scrolling=True)
        self.add_heading("INPUT")
        self.mic_input = QComboBox()
        for index in range(HARDWARE_INPUTS):
            self.mic_input.addItem(self.input_name(vm, index), index)
        self.mic_input.setCurrentIndex(current["mic_strip"])
        self.form.addRow("Microphone input", self.mic_input)
        self.add_note("The VoiceMeeter input your microphone is on.")
        self.listen_bus = QComboBox()
        self.monitor_button = QPushButton("Monitor")
        self.monitor_button.setCheckable(True)
        self.monitor_button.setStyleSheet(
            "QPushButton { padding: 4px 12px; }"
            + outline_toggle_style(TOGGLE_COLORS["solo"])
        )
        self.monitor_button.clicked.connect(self.toggle_monitor)
        chosen_stream = set(str(current["stream_bus"] or "").split(","))
        self.stream_outputs = {}
        stream_row = QHBoxLayout()
        stream_row.setSpacing(10)
        outputs = available_outputs(vm)
        for output in HARDWARE_OUTPUTS:
            # The one chosen before stays in the list, even without a device.
            if output in outputs or output == current["listen_bus"]:
                text, _tooltip = route_name(vm, output)
                self.listen_bus.addItem(text, output)
        for output in VIRTUAL_OUTPUTS:
            # Only a virtual output can reach the stream software.
            text, tooltip = route_name(vm, output)
            box = QCheckBox(text)
            box.setToolTip(tooltip)
            box.setChecked(output in chosen_stream)
            self.stream_outputs[output] = box
            stream_row.addWidget(box)
        self.listen_bus.setCurrentIndex(
            max(0, self.listen_bus.findData(current["listen_bus"]))
        )
        stream_row.addStretch(1)
        monitor_row = QHBoxLayout()
        monitor_row.addWidget(self.listen_bus, 1)
        monitor_row.addWidget(self.monitor_button)
        self.form.addRow("Monitor on", monitor_row)
        self.add_note(
            "\"Monitor\" sends your microphone to this output so you hear "
            "yourself; press it again to stop. It works at once. VoiceMeeter "
            "adds a little delay."
        )
        self.listen_bus.currentIndexChanged.connect(self.update_monitor_button)
        self.update_monitor_button()
        self.original_monitor_level = current["monitor_level"]
        self.monitor_level = QSlider(Qt.Orientation.Horizontal)
        self.monitor_level.setRange(-30, 0)
        self.monitor_level.setValue(int(current["monitor_level"]))
        self.monitor_level_label = QLabel()
        self.monitor_level_label.setMinimumWidth(52)
        level_row = QHBoxLayout()
        level_row.addWidget(self.monitor_level, 1)
        level_row.addWidget(self.monitor_level_label)
        self.form.addRow("Monitor level", level_row)
        self.add_note(
            "How loud you hear yourself, compared with how loud voice chat "
            "and your stream hear you. Changes are heard at once."
        )
        self.monitor_level.valueChanged.connect(self.on_monitor_level)
        self.on_monitor_level(self.monitor_level.value(), preview=False)

        self.add_heading("STREAM")
        setup_button = QPushButton("Set up for streaming…")
        setup_button.setStyleSheet("QPushButton { padding: 4px 12px; }")
        setup_button.setToolTip(
            "Explains which output goes where, routes everything in one go, "
            "and says what to pick in your call program and OBS"
        )
        setup_button.clicked.connect(self.open_stream_setup)
        setup_row = QHBoxLayout()
        setup_row.addWidget(setup_button)
        setup_row.addStretch(1)
        self.form.addRow(setup_row)
        self.form.addRow("Your stream hears", stream_row)
        self.add_note(
            "Tick every VoiceMeeter output your stream software records, for "
            "example B2 for your voice and B3 for game, chat and media. Only "
            "the virtual outputs B1-B3 can reach it. \"Mute stream\" "
            "takes your microphone off them and the Stream mix sets their "
            "volumes. Keep B1 for your call program, so voice chat still hears you."
        )

        self.add_heading("SOUND CHECK")
        self.add_note(
            f"Records {SOUND_CHECK_SECONDS} seconds of your voice with the "
            "mic processing applied, as voice chat and your stream hear it, "
            "and plays it back where you hear the mute chime."
        )
        self.sound_check_source = QComboBox()
        try:
            sources = recording_devices()
        except Exception:
            sources = []
        for source in sources:
            self.sound_check_source.addItem(
                source + ("…" if len(source) >= 31 else ""), source
            )
        self.sound_check_source.setCurrentIndex(
            max(0, self.sound_check_source.findData(sound_check_device(sources)))
        )
        self.sound_check_button = QPushButton("Record")
        self.sound_check_button.setStyleSheet("QPushButton { padding: 4px 12px; }")
        self.sound_check_button.clicked.connect(self.run_sound_check)
        check_row = QHBoxLayout()
        check_row.addWidget(self.sound_check_source, 1)
        check_row.addWidget(self.sound_check_button)
        self.form.addRow("Record from", check_row)
        self.sound_check_status = QLabel(
            "Speak as you do on stream after pressing \"Record\"."
        )
        self.sound_check_status.setObjectName("settingsNote")
        self.sound_check_status.setWordWrap(True)
        self.form.addRow(self.sound_check_status)
        self.sound_check_job = BackgroundJob(self)
        self.sound_check_job.finished.connect(self.on_sound_check_done)

        self.add_heading("MUTE CHIME")
        self.mute_sound = QCheckBox(
            "Play a chime when the microphone is muted or unmuted"
        )
        self.mute_sound.setChecked(current["mute_sound"])
        self.form.addRow(self.mute_sound)
        self.add_note(
            "A short confirmation for you: falling when muted, rising when "
            "unmuted. It does not pass your voice through."
        )
        self.sound_device = QComboBox()
        self.sound_device.addItem("Windows default output", "")
        try:
            devices = sound_devices()
        except Exception:
            devices = []
        chosen = current["mute_sound_device"]
        if chosen and chosen not in devices:
            devices.append(chosen)  # not connected now; keep the choice
        for device in devices:
            # waveOut cuts names at 31 characters; show that it is cut.
            self.sound_device.addItem(
                device + ("…" if len(device) >= 31 else ""), device
            )
        self.sound_device.setCurrentIndex(max(0, self.sound_device.findData(chosen)))
        self.preview_chime = QPushButton("Preview")
        self.preview_chime.setToolTip("Play the mute chime on this device")
        self.preview_chime.setStyleSheet("QPushButton { padding: 4px 10px; }")
        self.preview_chime.clicked.connect(
            lambda: play_mute_sound(True, self.sound_device.currentData())
        )
        sound_row = QHBoxLayout()
        sound_row.addWidget(self.sound_device, 1)
        sound_row.addWidget(self.preview_chime)
        self.form.addRow("Hear it on", sound_row)
        self.chime_hint = QLabel()
        self.chime_hint.setWordWrap(True)
        self.form.addRow(self.chime_hint)
        self.mute_sound.toggled.connect(self.update_chime_hint)
        self.sound_device.currentIndexChanged.connect(self.update_chime_hint)
        self.update_chime_hint()

        self.add_heading("MUTE INDICATOR")
        self.mute_overlay = QCheckBox(
            "Show a badge on screen while the microphone is muted"
        )
        self.mute_overlay.setChecked(current["mute_overlay"])
        self.form.addRow(self.mute_overlay)
        self.tray_mute_icon = QCheckBox("Show the mute state on the tray icon")
        self.tray_mute_icon.setChecked(current["tray_mute_icon"])
        self.form.addRow(self.tray_mute_icon)
        self.add_note(
            "Red: your microphone is muted. Orange: you are muted for the "
            "stream only, your call still hears you. The badge stays on top "
            "of other windows and games in borderless or windowed mode; "
            "drag it where you want it."
        )

        self.form = self.add_tab("General", scrolling=True)
        self.tabs.tabBar().moveTab(1, 0)  # General first
        self.add_heading("CHANNEL NAMES")
        self.channel_names = {}
        for channel, key in CHANNEL_NAME_KEYS.items():
            edit = QLineEdit(current[key])
            edit.setMaxLength(CHANNEL_NAME_MAX)
            edit.setPlaceholderText(channel)
            self.form.addRow(channel, edit)
            self.channel_names[key] = edit
        self.add_note("Leave a field empty to keep the built-in name.")

        self.add_heading("OUTPUT NAMES")
        self.output_names = {}
        shown = available_outputs(vm)
        for output in ALL_OUTPUTS:
            edit = QLineEdit(current[f"output_name_{output}"])
            edit.setMaxLength(OUTPUT_NAME_MAX)
            self.output_names[output] = edit
            if output not in shown:
                continue  # kept, but an output that does nothing is not listed
            device = output_device(vm, output)
            edit.setPlaceholderText(output)
            label = f"{output} · {device}" if device else f"{output} · virtual"
            if len(label) > 26:
                label = label[:25] + "…"
            self.form.addRow(label, edit)
        self.add_note(
            "Shown on the routing buttons instead of A1 or B2, for example "
            "Hear, Call, Str. mic, Str. mix. Leave empty to keep the code."
        )

        self.add_heading("WINDOW")
        self.close_to_tray = QCheckBox(
            "Keep running in the system tray when the window is closed"
        )
        self.close_to_tray.setChecked(current["close_to_tray"])
        self.form.addRow(self.close_to_tray)
        self.start_minimized = QCheckBox("Start minimised to the tray")
        self.start_minimized.setChecked(current["start_minimized"])
        self.form.addRow(self.start_minimized)
        self.add_note(
            "Click the tray icon to show the window again. "
            "Right-click it to mute the microphone or quit. "
            "Holding Shift while closing the window quits at once."
        )

        self.add_heading("UPDATES")
        self.check_updates = QCheckBox("Check for updates when FaderDeck starts")
        self.check_updates.setChecked(current["check_updates"])
        self.form.addRow(self.check_updates)
        check_now = QPushButton("Check now")
        check_now.setStyleSheet("QPushButton { padding: 4px 10px; }")
        check_now.clicked.connect(
            lambda: self.parent().check_for_updates(quiet=False)
        )
        update_row = QHBoxLayout()
        update_row.addWidget(QLabel(f"Version {APP_VERSION}"), 1)
        update_row.addWidget(check_now)
        self.form.addRow(update_row)

    def _build_appearance_tab(self, current):
        """Theme, accent and channel colours, and saved themes."""
        self.form = self.add_tab("Appearance")
        self.original_theme = current["theme"]
        self.themes = dict(current["themes"])
        self.theme = QComboBox()
        self.theme.activated.connect(self.on_theme_chosen)
        self.form.addRow("Theme", self.theme)
        self.light = QCheckBox("Light background")
        self.light.toggled.connect(self.on_theme_edited)
        self.form.addRow(self.light)
        self.accent = ColorButton("#58a6ff")
        self.accent.changed.connect(self.on_theme_edited)
        self.form.addRow("Accent colour", self.accent)
        self.base = ColorButton("#0d1117")
        self.base.setToolTip("The colour of the window's backgrounds and greys")
        self.base.changed.connect(self.on_theme_edited)
        self.form.addRow("Background colour", self.base)
        self.add_heading("CHANNEL COLOURS")
        self.channel_colors = {}
        for channel, colors in STRIP_COLORS.items():
            button = ColorButton(colors["accent"])
            button.changed.connect(self.on_theme_edited)
            self.form.addRow(channel_label(channel), button)
            self.channel_colors[channel] = button
        save_theme = QPushButton("Save as…")
        save_theme.setToolTip("Keep these colours as a theme of your own")
        save_theme.clicked.connect(self.save_theme)
        self.delete_theme_button = QPushButton("Delete")
        self.delete_theme_button.clicked.connect(self.delete_theme)
        theme_row = QHBoxLayout()
        for button in (save_theme, self.delete_theme_button):
            button.setStyleSheet("QPushButton { padding: 4px 10px; }")
            theme_row.addWidget(button)
        theme_row.addStretch(1)
        self.form.addRow(theme_row)
        self.add_note(
            "Changes show at once. Cancel puts the colours back. The accent "
            "colours the highlights; the background colour the window and "
            "its greys."
        )
        self.show_theme(self.original_theme)

    def _build_hotkeys_tab(self, current):
        """One field per global hotkey, grouped."""
        self.form = self.add_tab("Hotkeys", scrolling=True)
        self.add_note(
            "Click a field and press the keys. Hotkeys work while FaderDeck "
            "is in the background. Other programs cannot use these "
            "combinations while FaderDeck runs. Clear a field to switch "
            "it off."
        )
        self.hotkey_edits = {}
        taken = getattr(self.parent(), "refused_hotkeys", {})
        if taken:
            warning = QLabel(
                "Another program, or another FaderDeck that is running, "
                "already uses "
                + ", ".join(f"{text} ({label})" for text, label in taken.values())
                + ". Pick another combination, or close that program."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #f85149;")
            self.form.addRow(warning)
        group = None
        for action in HOTKEYS:
            if action.group != group:
                group = action.group
                self.add_heading(group)
            edit = QKeySequenceEdit(QKeySequence(current[action.key]))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            label = action.label
            for channel, key in CHANNEL_NAME_KEYS.items():
                label = label.replace(channel, current[key] or channel)
            if action.key in taken:
                edit.setStyleSheet("QLineEdit { border: 1px solid #f85149; }")
                edit.setToolTip("Another program already uses this combination.")
            self.form.addRow(label, edit)
            self.hotkey_edits[action.key] = edit

    def _build_remote_tab(self, current):
        """The local API: on or off, port, token and examples."""
        self.form = self.add_tab("Remote control", scrolling=True)
        self.add_note(
            "Lets other programs on this computer control FaderDeck: a "
            "Stream Deck plugin, an OBS script, a shortcut. Nothing outside "
            "this computer can connect, and every request needs the token "
            "below."
        )
        self.api_enabled = QCheckBox("Allow control by other programs")
        self.api_enabled.setChecked(current["api_enabled"])
        self.form.addRow(self.api_enabled)
        self.api_port = QSpinBox()
        self.api_port.setRange(1024, 65535)
        self.api_port.setValue(current["api_port"])
        self.form.addRow("Port", self.api_port)

        self.api_token = QLineEdit(
            current["api_token"] or secrets.token_urlsafe(16)
        )
        self.api_token.setReadOnly(True)
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.api_token.text())
        )
        new_button = QPushButton("New")
        new_button.setToolTip(
            "Make a new token. Programs using the old one stop working."
        )
        new_button.clicked.connect(
            lambda: self.api_token.setText(secrets.token_urlsafe(16))
        )
        token_row = QHBoxLayout()
        token_row.addWidget(self.api_token, 1)
        for button in (copy_button, new_button):
            button.setStyleSheet("QPushButton { padding: 4px 10px; }")
            token_row.addWidget(button)
        self.form.addRow("Token", token_row)

        self.add_heading("HOW TO USE IT")
        example = QLabel(
            "Send the token in the header X-FaderDeck-Token.\n\n"
            "GET   /api/state\n"
            "GET   /api/profiles\n"
            "POST  /api/mute/mic?state=toggle      (on, off, toggle)\n"
            "POST  /api/gain/game?step=-1          (or db=-6)\n"
            "POST  /api/profile/Streaming\n"
            "POST  /api/profile?step=next          (next, previous)\n"
            "POST  /api/monitor?state=toggle       (on, off, toggle)\n"
            "POST  /api/stream-mute?state=toggle   (on, off, toggle)\n\n"
            "Channels: mic, game, chat, media."
        )
        example.setStyleSheet(
            "color: #aebdca; font-family: Consolas; font-size: 11px;"
        )
        example.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.form.addRow(example)

        self.add_heading("PHONE AND TABLET")
        self.add_note(
            "Control FaderDeck from a phone or tablet on your home network. "
            "Open the address below in its browser, pair it once, then use "
            "'Add to home screen' to keep it as an app."
        )
        self.remote_enabled = QCheckBox("Allow phones and tablets on my home network")
        self.remote_enabled.setChecked(current["remote_enabled"])
        self.form.addRow(self.remote_enabled)
        self.remote_port = QSpinBox()
        self.remote_port.setRange(1024, 65535)
        self.remote_port.setValue(current["remote_port"])
        self.form.addRow("Port", self.remote_port)
        address = lan_address()
        self.remote_address = QLineEdit(
            f"http://{address}:{current['remote_port']}/remote" if address
            else "No home network found"
        )
        self.remote_address.setReadOnly(True)
        self.form.addRow("Address", self.remote_address)
        self.firewall_button = QPushButton("Allow through firewall")
        self.firewall_button.setStyleSheet("QPushButton { padding: 4px 10px; }")
        self.firewall_button.setToolTip(
            "Windows asks for permission once, then lets phones and tablets "
            "on private networks reach FaderDeck on this port."
        )
        self.firewall_button.clicked.connect(self.allow_through_firewall)
        self.firewall_status = QLabel("Checking Windows Firewall…")
        self.firewall_status.setWordWrap(True)
        self.firewall_status.setObjectName("settingsNote")
        firewall_row = QHBoxLayout()
        firewall_row.addWidget(self.firewall_button)
        firewall_row.addWidget(self.firewall_status, 1)
        self.form.addRow("Firewall", firewall_row)
        self.firewall_job = BackgroundJob(self)
        self.firewall_job.finished.connect(self.show_firewall_status)
        self.remote_port.valueChanged.connect(self.check_firewall)
        self.check_firewall()
        pair_button = QPushButton("Pair a device")
        pair_button.clicked.connect(self.show_pairing_code)
        forget_button = QPushButton("Forget paired devices")
        forget_button.clicked.connect(self.forget_devices)
        # The paired devices belong to the running remote, not to this
        # window: OK only clears them when FORGET was pressed.
        self.remote_devices = list(current["remote_devices"])
        self.forget_requested = False
        remote = getattr(self.parent(), "phone_remote", None)
        if remote is not None:
            remote.paired.connect(self.on_device_paired)
        remote_row = QHBoxLayout()
        for button in (pair_button, forget_button):
            button.setStyleSheet("QPushButton { padding: 4px 10px; }")
            remote_row.addWidget(button)
        remote_row.addStretch(1)
        self.form.addRow(remote_row)
        self.remote_count = QLabel()
        self.remote_count.setObjectName("settingsNote")
        self.form.addRow(self.remote_count)
        self.update_remote_count()
        self.add_note(
            "Anyone with a paired device on your network can control the "
            "mixer; forget them when in doubt."
        )

    def check_firewall(self):
        self.firewall_status.setText("Checking Windows Firewall…")
        self.firewall_job.start(
            firewall_allows, firewall_program(), self.remote_port.value()
        )

    def show_firewall_status(self, allowed):
        if allowed is True:
            text, color = (
                f"Allowed: phones can reach port {self.remote_port.value()}.",
                "#3fb950",
            )
        elif allowed is False:
            text, color = (
                "Not allowed yet: phones will time out until you press "
                "this.", "#f0883e",
            )
        else:
            text, color = "Could not read Windows Firewall.", "#8ba0b5"
        self.firewall_button.setEnabled(True)
        self.firewall_status.setText(text)
        self.firewall_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.fit_tabs()

    def allow_through_firewall(self):
        self.firewall_button.setEnabled(False)
        self.firewall_status.setText("Waiting for Windows…")
        command = firewall_rule_command(firewall_program(), self.remote_port.value())
        self.firewall_job.start(self.add_firewall_rule, command)

    @staticmethod
    def add_firewall_rule(command):
        """Runs off the GUI thread; the result goes to show_firewall_status."""
        code = run_powershell_as_admin(command)
        if code is None:
            log.info("Firewall rule: permission was not given")
            return False
        log.info(f"Firewall rule for the phone remote: exit code {code}")
        return firewall_allows(firewall_program(), int(command.split("-LocalPort ")[1].split()[0]))

    def update_remote_count(self):
        count = len(self.remote_devices)
        self.remote_count.setText(
            "No devices paired yet." if not count
            else f"{count} device{'s' if count != 1 else ''} paired."
        )

    def show_pairing_code(self):
        remote = getattr(self.parent(), "phone_remote", None)
        if remote is None or remote.server is None:
            QMessageBox.information(
                self, "FaderDeck",
                "Switch on 'Allow phones and tablets', press OK, and open "
                "Settings again to pair a device.",
            )
            return
        code = remote.new_code()
        QMessageBox.information(
            self, "FaderDeck — Pair a device",
            f"Type this code on your phone or tablet:\n\n{code[:3]} {code[3:]}\n\n"
            f"It works once, for {REMOTE_PAIR_SECONDS // 60} minutes.",
        )

    def on_device_paired(self, device_hash):
        if device_hash not in self.remote_devices:
            self.remote_devices.append(device_hash)
        self.update_remote_count()

    def forget_devices(self):
        self.remote_devices = []
        self.forget_requested = True
        self.update_remote_count()
        self.remote_count.setText("All paired devices are forgotten when you press OK.")

    def on_monitor_level(self, value, preview=True):
        self.monitor_level_label.setText("0 dB" if value == 0 else f"{value} dB")
        window = self.parent()
        if preview and hasattr(window, "set_monitor_level"):
            window.set_monitor_level(value, self.listen_bus.currentData())

    def monitor_route(self):
        """The Mic strip's routing button for the chosen monitor output."""
        window = self.parent()
        mic = getattr(window, "strips", {}).get("Mic")
        if mic is None:
            return None
        return mic.route_buttons.get(self.listen_bus.currentData())

    def update_monitor_button(self):
        route = self.monitor_route()
        connected = bool(getattr(self.parent(), "connected", False))
        self.monitor_button.setEnabled(route is not None and connected)
        self.monitor_button.setChecked(bool(route is not None and route.isChecked()))

    def toggle_monitor(self, checked):
        """Monitor at once, on the output chosen here (even before OK)."""
        output = self.listen_bus.currentData()
        self.parent().set_mic_route(output, checked)
        self.update_monitor_button()

    def run_sound_check(self):
        device = self.sound_check_source.currentData() or ""
        self.sound_check_button.setEnabled(False)
        self.sound_check_status.setText(
            f"Recording… speak now ({SOUND_CHECK_SECONDS} seconds)."
        )
        self.sound_check_job.start(
            self.sound_check_or_problem, device, self.sound_device.currentData()
        )

    @staticmethod
    def sound_check_or_problem(device, play_on):
        """Runs off the GUI thread; the text goes to on_sound_check_done."""
        try:
            return sound_check(device, SOUND_CHECK_SECONDS, play_on)
        except OSError as e:
            return f"Sound check did not work: {e}"

    def on_sound_check_done(self, text):
        self.sound_check_button.setEnabled(True)
        self.sound_check_status.setText(str(text or "Sound check did not work."))

    def open_stream_setup(self):
        window = self.parent()
        if not hasattr(window, "apply_stream_setup"):
            return
        StreamSetupDialog(window, window.vm if window.connected else None).exec()
        # The setup changed settings this window also shows: start afresh.
        self.reject()
        QTimer.singleShot(0, window.open_settings)

    def update_chime_hint(self):
        """Say whether the chosen device keeps the chime off the stream."""
        on = self.mute_sound.isChecked()
        self.sound_device.setEnabled(on)
        self.preview_chime.setEnabled(on)
        device = self.sound_device.currentData() or ""
        if not on:
            text, color = "", "#8ba0b5"
        elif "voicemeeter" in device.casefold():
            text, color = (
                "This is a VoiceMeeter input: the chime goes into your mix "
                "and your stream may hear it. Choose your headphones or "
                "speakers instead.", "#f0883e",
            )
        elif not device:
            text, color = (
                "With VoiceMeeter, the Windows default output is often a "
                "VoiceMeeter input, and then your stream hears the chime. "
                "Choose your headphones or speakers to be sure.", "#f0883e",
            )
        else:
            text, color = (
                "Only you hear it here, unless your stream captures this "
                "device.", "#8ba0b5",
            )
        self.chime_hint.setText(text)
        self.chime_hint.setVisible(bool(text))
        self.chime_hint.setStyleSheet(f"color: {color}; font-size: 11px;")

    def add_tab(self, title, scrolling=False):
        """Add a page and return its form layout."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(12, 10, 12, 10)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        if scrolling:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        else:
            self.tabs.addTab(page, title)
        return form

    @staticmethod
    def input_name(vm, index):
        """Describe a hardware input by what is connected to it.

        "Hardware Input 2" alone says nothing; the audio device selected for
        it in VoiceMeeter, and the name given to the strip there, do.
        """
        text = f"Input {index + 1}"
        if vm is None:
            return text
        try:
            strip = vm.strip[index]
            label = str(strip.label or "").strip()
            device = str(strip.device.name or "").strip()
        except Exception:
            return text
        details = " · ".join(part for part in (label, device) if part)
        return f"{text} — {details or 'no device'}"

    def add_heading(self, text):
        heading = QLabel(text)
        heading.setObjectName("settingsHeading")
        self.form.addRow(heading)

    def add_note(self, text):
        note = QLabel(text)
        note.setObjectName("settingsNote")
        note.setWordWrap(True)
        self.form.addRow(note)

    # Appearance.

    def all_themes(self):
        themes = {
            name: clean_theme(value, name) for name, value in BUILTIN_THEMES.items()
        }
        themes.update(self.themes)
        return themes

    def theme_value(self):
        """The theme as the controls show it."""
        theme = clean_theme({
            "light": self.light.isChecked(),
            "accent": self.accent.color,
            "base": self.base.color,
            "channels": {
                channel: button.color
                for channel, button in self.channel_colors.items()
            },
        }, CUSTOM_THEME)
        for name, known in self.all_themes().items():
            if {**known, "name": ""} == {**theme, "name": ""}:
                theme["name"] = name
        return theme

    def show_theme(self, theme):
        """Put a theme in the controls and name it in the list."""
        self.light.blockSignals(True)
        self.light.setChecked(theme["light"])
        self.light.blockSignals(False)
        self.accent.set_color(theme["accent"])
        self.base.set_color(theme["base"])
        for channel, button in self.channel_colors.items():
            button.set_color(theme["channels"].get(channel, ""))
        name = self.theme_value()["name"]
        self.theme.clear()
        self.theme.addItems(self.all_themes())
        if name == CUSTOM_THEME:
            self.theme.addItem(CUSTOM_THEME)
        self.theme.setCurrentText(name)
        self.delete_theme_button.setEnabled(name in self.themes)

    def on_theme_chosen(self):
        theme = self.all_themes().get(self.theme.currentText())
        if theme is not None:
            self.show_theme(theme)
            apply_theme(theme)

    def on_theme_edited(self):
        theme = self.theme_value()
        self.show_theme(theme)
        apply_theme(theme)

    def save_theme(self):
        name, accepted = QInputDialog.getText(self, "FaderDeck", "Theme name:")
        name = name.strip()[:40]
        if not accepted or not name:
            return
        if name in BUILTIN_THEMES or name == CUSTOM_THEME:
            self.error_label.setVisible(True)
            self.error_label.setText(f"{name} is a built-in name; choose another.")
            return
        self.themes[name] = clean_theme(self.theme_value(), name)
        self.show_theme(self.themes[name])

    def delete_theme(self):
        self.themes.pop(self.theme.currentText(), None)
        self.show_theme(self.theme_value())

    def reject(self):
        window = self.parent()
        if hasattr(window, "set_monitor_level"):
            window.set_monitor_level(self.original_monitor_level)
        apply_theme(self.original_theme)
        super().reject()

    def hotkey_texts(self):
        return {
            key: edit.keySequence().toString(
                QKeySequence.SequenceFormat.PortableText
            )
            for key, edit in self.hotkey_edits.items()
        }

    def hotkey_problem(self):
        """Why the chosen hotkeys cannot be used, or an empty string."""
        chosen = [text for text in self.hotkey_texts().values() if text]
        for text in chosen:
            if parse_hotkey(text) is None:
                return (
                    f"{text} cannot be used as a global hotkey. Use Ctrl, "
                    "Shift or Alt together with a letter, a digit or F1-F24."
                )
        for text in chosen:
            if chosen.count(text) > 1:
                return f"{text} is used for more than one hotkey."
        return ""

    def accept(self):
        problem = self.hotkey_problem()
        if problem:
            self.error_label.setVisible(True)
            self.error_label.setText(problem)
            return
        super().accept()

    def values(self):
        values = {
            "mic_strip": int(self.mic_input.currentData()),
            "listen_bus": self.listen_bus.currentData(),
            "monitor_level": self.monitor_level.value(),
            "stream_bus": ",".join(
                output for output, box in self.stream_outputs.items() if box.isChecked()
            ),
            "theme": self.theme_value(),
            "themes": dict(self.themes),
            "close_to_tray": self.close_to_tray.isChecked(),
            "start_minimized": self.start_minimized.isChecked(),
            "check_updates": self.check_updates.isChecked(),
            "mute_sound": self.mute_sound.isChecked(),
            "mute_overlay": self.mute_overlay.isChecked(),
            "tray_mute_icon": self.tray_mute_icon.isChecked(),
            "mute_sound_device": self.sound_device.currentData(),
            "api_enabled": self.api_enabled.isChecked(),
            "api_port": self.api_port.value(),
            "api_token": self.api_token.text(),
            "remote_enabled": self.remote_enabled.isChecked(),
            "remote_port": self.remote_port.value(),
            "remote_forget": self.forget_requested,
        }
        values.update(self.hotkey_texts())
        values.update(
            (key, edit.text().strip()) for key, edit in self.channel_names.items()
        )
        values.update(
            (f"output_name_{output}", edit.text().strip())
            for output, edit in self.output_names.items()
        )
        return values


class GripSplitterHandle(QSplitterHandle):
    """Splitter handle with a visible grip, so it is obviously draggable."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self._pressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Drag to resize • double-click to reset")

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        splitter = self.splitter()
        if hasattr(splitter, "reset_sizes"):
            splitter.reset_sizes()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(self.rect()).adjusted(0, 3, 0, -3)
        active = self._hover or self._pressed
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#243b52" if active else "#18232e"))
        painter.drawRoundedRect(bar, 3, 3)
        painter.setBrush(QColor("#58a6ff" if active else "#4b6179"))
        center = bar.center()
        for offset in (-14, 0, 14):
            painter.drawEllipse(QPointF(center.x() + offset, center.y()), 2.0, 2.0)


class GripSplitter(QSplitter):
    """Splitter that uses the grip handle and can return to default sizes."""

    def __init__(self, orientation, default_sizes, parent=None):
        super().__init__(orientation, parent)
        self._default_sizes = list(default_sizes)
        self.setHandleWidth(14)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)

    def createHandle(self):
        return GripSplitterHandle(self.orientation(), self)

    def reset_sizes(self):
        self.setSizes(self._default_sizes)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.vm = None
        self.vm_observer = None
        self.connected = False
        self._logged_in = False
        self._exit_lock = threading.Lock()
        atexit.register(self.release_vm_at_exit)
        # Health checks in a row that found VoiceMeeter running while we were
        # disconnected; see check_connection().
        self._seen_running = 0
        self.vm_install_state = voicemeeter_install_state()
        self._missing_shown = False
        self.strips = {}
        self.window_settings = app_settings()
        # Before any strip or processing control exists.
        set_mic_strip(self.window_settings.value("mic_strip", 0))


        # Qt bridge for VoiceMeeter's background event thread.

        self.vm_bridge = VMEventBridge()
        self.mic_level_thread = None
        self.mic_level_worker = None


        self.vm_bridge.event_received.connect(

            self.on_vm_event

        )

        # Keep the visual VU meters updating independently of VoiceMeeter's
        # ldirty event cadence. The event path still gives immediate updates,
        # while this timer lets the existing meter decay smoothly to silence.
        self.level_timer = QTimer(self)
        self.level_timer.setInterval(16)
        self.level_timer.timeout.connect(self.update_mixer_levels)
        self.level_timer.start()


        self.setWindowTitle(

            "FaderDeck"

        )

        # Compact default size fits the open desktop area beside monitoring
        # tools while keeping the window resizable. Restore the last saved
        # geometry when available.
        # Applied once the widgets exist; see the end of __init__.
        self.compact = False
        self.setMinimumSize(*WINDOW_MIN_SIZE)
        self.restore_window_geometry()


        self._apply_window_style()

        central = QWidget()
        self.setCentralWidget(
            central
        )

        main_layout = QVBoxLayout(

            central

        )
        main_layout.setContentsMargins(9, 9, 9, 9)
        main_layout.setSpacing(4)


        self._build_header(main_layout)
        self._build_mixer_area(main_layout)
        self._build_lower_panels()
        self._start_services()

    def _apply_window_style(self):
        """The dark style sheet of the whole window."""
        self.setStyleSheet(

            """
            QMainWindow {
                background: #0d1117;
                color: #e6edf3;
            }

            QWidget {
                color: #e6edf3;
                font-family: "Segoe UI";
                font-size: 9pt;
            }

            QPushButton {
                background: #21262d;
                border: 1px solid #30363d;
                border-radius: 5px;
                padding: 7px;
            }

            QPushButton:hover {
                background: #30363d;
            }

            QPushButton:checked {
                background: #b42318;
                border-color: #d92d20;
            }

            QSlider::groove:horizontal {
                background: #30363d;
                height: 6px;
                border-radius: 3px;
            }

            QSlider::handle:horizontal {
                background: #58a6ff;
                width: 16px;
                margin: -5px 0;
                border-radius: 4px;
            }

            QSlider::groove:vertical {
                background: #30363d;
                width: 8px;
                border-radius: 4px;
            }

            QSlider::handle:vertical {
                background: #58a6ff;
                height: 22px;
                margin: 0 -7px;
                border-radius: 5px;
            }

            QCheckBox {
                spacing: 8px;
            }

            QDialog {
                background: #0d1117;
            }

            QComboBox, QLineEdit {
                background: #18232e;
                border: 1px solid #314558;
                border-radius: 4px;
                padding: 4px 8px;
            }

            QComboBox:focus, QLineEdit:focus {
                border-color: #58a6ff;
            }

            QComboBox QAbstractItemView {
                background: #18232e;
                color: #e6edf3;
                selection-background-color: #243b52;
            }

            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }

            QToolButton {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px;
                text-align: left;
                font-size: 15px;
                font-weight: bold;
            }

            QToolButton:hover {
                background: #21262d;
            }
            """
        )

    def _build_header(self, main_layout):
        """Logo, name, connection status and the header buttons."""
        header = QHBoxLayout()


        logo_mark = QLabel()
        logo_mark.setFixedSize(26, 26)
        logo_mark.setPixmap(_svg_icon(LOGO_SVG, 26).pixmap(26, 26))

        app_title = Wordmark()

        app_subtitle = QLabel("for VoiceMeeter Potato")
        app_subtitle.setStyleSheet(
            "color: #8ba0b5; font-size: 11px; padding-top: 4px;"
        )

        self.status_label = QLabel(

            "● Disconnected"
        )
        self.status_label.setStyleSheet(
            "color: #f85149; font-weight: bold;"

        )


        header.setSpacing(7)
        header.addWidget(logo_mark)
        header.addWidget(app_title)
        header.addWidget(app_subtitle)

        self.settings_button = QPushButton()
        self.settings_button.setFixedSize(32, 26)
        set_mono_icon(self.settings_button, "settings", 18)
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setToolTip("Settings")
        self.settings_button.setStyleSheet(HEADER_BUTTON_STYLE)
        self.settings_button.clicked.connect(self.open_settings)

        self.compact_button = QPushButton()
        self.compact_button.setCheckable(True)
        self.compact_button.setFixedSize(32, 26)
        set_mono_icon(self.compact_button, "compact", 18)
        self.compact_button.setIconSize(QSize(18, 18))
        self.compact_button.setToolTip(
            "Compact view: faders, meters and mute only"
        )
        self.compact_button.setStyleSheet(HEADER_BUTTON_STYLE)
        self.compact_button.clicked.connect(self.set_compact)

        header.addStretch()

        header.addWidget(
            self.status_label
        )
        header.addSpacing(8)
        # Which mix the faders set; shown once the stream has an output.
        self.mix_buttons = {}
        mix_box = QWidget()
        mix_layout = QHBoxLayout(mix_box)
        mix_layout.setContentsMargins(0, 0, 0, 0)
        mix_layout.setSpacing(0)
        for mix, text, tip, color in (
            ("you", "You", "The faders set what you hear", "#58a6ff"),
            ("stream", "Stream", "The faders set what your stream hears", "#f0883e"),
        ):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setFixedHeight(26)
            button.setToolTip(tip)
            button.setStyleSheet(
                "QPushButton { background: #18232e; border: 1px solid #314558; "
                "padding: 0 10px; font-weight: bold; color: #8ba0b5; }"
                f"QPushButton:checked {{ color: #ffffff; border-color: {color}; "
                f"background: {color}; }}"
            )
            button.clicked.connect(lambda _checked, m=mix: self.set_mix(m))
            mix_layout.addWidget(button)
            self.mix_buttons[mix] = button
        self.mix_buttons["you"].setChecked(True)
        self.mix_box = mix_box
        mix_box.setVisible(False)
        header.addWidget(mix_box)
        header.addWidget(self.compact_button)
        header.addWidget(self.settings_button)
        self.app_subtitle = app_subtitle

        main_layout.addLayout(
            header
        )

    def _build_mixer_area(self, main_layout):
        """The strip row, the offline banner and the splitter under them."""
        # The mixer (top) and the Applications / Mic Processing panels
        # (bottom) share the window height through a draggable splitter, so
        # resizing the window never leaves an empty gap between them.
        self.main_splitter = GripSplitter(
            Qt.Orientation.Vertical,
            (DEFAULT_MIXER_PANE_HEIGHT, APPLICATION_PANEL_HEIGHT + 40),
        )
        self.mixer_container = QWidget()
        self.mixer_layout = QHBoxLayout(self.mixer_container)
        self.mixer_layout.setContentsMargins(0, 0, 0, 0)
        self.mixer_layout.setSpacing(4)
        self.main_splitter.addWidget(self.mixer_container)
        self.offline_banner = QWidget()
        self.offline_banner.setObjectName("offlineBanner")
        self.offline_banner.setStyleSheet(
            "QWidget#offlineBanner { background: #2b1516; "
            f"border: 1px solid {ALERT_BORDER}; border-radius: 6px; }}"
        )
        banner_layout = QHBoxLayout(self.offline_banner)
        banner_layout.setContentsMargins(10, 5, 6, 5)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setStyleSheet("color: #f0b6b1; font-weight: bold;")
        self.start_button = QPushButton("Start VoiceMeeter")
        self.start_button.setToolTip("Start VoiceMeeter Potato and connect to it")
        self.start_button.setStyleSheet("QPushButton { padding: 4px 12px; }")
        # Logging in starts VoiceMeeter when it is not running.
        self.start_button.clicked.connect(self.connect_vm)
        self.download_button = QPushButton("Download VoiceMeeter")
        self.download_button.setToolTip(VOICEMEETER_DOWNLOAD_URL)
        self.download_button.setStyleSheet("QPushButton { padding: 4px 12px; }")
        self.download_button.clicked.connect(self.open_voicemeeter_download)
        banner_layout.addWidget(self.banner_text, 1)
        banner_layout.addWidget(self.start_button)
        banner_layout.addWidget(self.download_button)
        self.offline_banner.setVisible(False)
        main_layout.addWidget(self.offline_banner)
        main_layout.addWidget(self.main_splitter, 1)

    def _build_lower_panels(self):
        """Mic processing, setup profiles and the application lists."""
        # Mic processing section. Keep it collapsed by default so the main
        # mixer remains the visual focus, while advanced processing stays one click away.
        self.processing_toggle = QToolButton()
        self.processing_toggle.setText("Mic processing…")
        self.processing_toggle.setToolTip(
            "Open the compressor, gate and denoiser in a separate window"
        )
        self.processing_toggle.setCheckable(True)
        self.processing_toggle.setChecked(False)
        self.processing_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.processing_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.processing_toggle.setStyleSheet(
            "QToolButton { background: #18232e; "
            f"border: 1px solid {PANEL_BORDER}; "
            "border-radius: 6px; padding: 8px; font-size: 15px; "
            "font-weight: bold; text-align: left; }"
            "QToolButton:hover { background: #1d2b38; }"
            "QToolButton:checked { background: #1b2f3b; border-color: #35a7ff; }"
        )
        self.processing_toggle.clicked.connect(self.toggle_processing)


        self.compressor_control = None
        self.gate_control = None
        self.denoiser_control = None
        self.application_control = None

        # Lower panels align with the mixer: mic processing beneath Mic,
        # application sessions beneath the three virtual input strips.
        self.lower_container = QWidget()
        lower_layout = QHBoxLayout(self.lower_container)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(4)

        self.processing_panel = QWidget()
        self.processing_panel.setObjectName("processingPanel")
        self.processing_panel.setStyleSheet(
            "QWidget#processingPanel { background: #101820; "
            f"border: 1px solid {PANEL_BORDER}; border-radius: 8px; }}"
        )
        self.processing_panel_layout = QVBoxLayout(self.processing_panel)
        self.processing_panel_layout.setContentsMargins(5, 5, 5, 5)
        self.processing_panel_layout.setSpacing(4)
        self.processing_panel_layout.addWidget(self.processing_toggle)
        self.processing_tabs = QTabWidget()
        self.processing_tabs.setDocumentMode(True)
        self.processing_tabs.setVisible(False)
        self.processing_tabs.tabBar().setExpanding(True)
        self.processing_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #30363d; "
            "border-radius: 6px; background: #0d141b; }"
            "QTabBar::tab { background: #18232e; color: #aebdca; "
            "border: 1px solid #30363d; padding: 7px 10px; "
            "min-width: 72px; }"
            "QTabBar::tab:selected { background: #1769aa; color: #ffffff; "
            "border-color: #35a7ff; }"
        )
        self.processing_dialog = None
        self.mic_level_bar = None
        self.preset_list = None

        self.applications_panel = QWidget()
        self.applications_panel.setObjectName("applicationsPanel")
        self.applications_panel.setStyleSheet(
            "QWidget#applicationsPanel { background: transparent; "
            "border: none; }"
        )
        self.applications_panel_layout = QVBoxLayout(self.applications_panel)
        self.applications_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.applications_panel_layout.setSpacing(3)

        processing_wrapper = QWidget()
        processing_wrapper_layout = QVBoxLayout(processing_wrapper)
        processing_wrapper_layout.setContentsMargins(0, 35, 0, 0)
        processing_wrapper_layout.setSpacing(6)
        processing_wrapper_layout.addWidget(
            self.processing_panel,
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        # What the mic processing is doing, without opening its window.
        self.processing_summary = QLabel("")
        self.processing_summary.setStyleSheet(
            "color: #aebdca; font-size: 11px; padding: 2px 4px;"
        )
        self.processing_panel_layout.addWidget(self.processing_summary)

        # Mute for the stream only. MONITOR lives in Settings, Microphone,
        # and on a hotkey.
        self.stream_mute_button = QPushButton("Mute stream")
        # The microphone icon says what is muted: your voice, not the stream.
        set_mono_icon(self.stream_mute_button, "mic", 14)
        self.stream_mute_button.setCheckable(True)
        self.stream_mute_button.setFixedHeight(26)
        self.stream_mute_button.setStyleSheet(
            "QPushButton { padding: 2px 6px; }"
            "QPushButton:checked { background: #54262c; "
            "border-color: #a8434f; color: #ffffff; }"
        )
        self.stream_mute_button.clicked.connect(
            lambda _checked: self.toggle_stream_mute()
        )
        self.processing_panel_layout.addWidget(self.stream_mute_button)

        self._build_profile_panel()

        # The profile the mixer was last loaded from or saved to, and its
        # stored content, to tell when the mixer no longer matches it.
        self.active_profile = ""
        self._profile_reference = None
        self._profile_message_until = 0.0
        self._profile_check_timer = QTimer(self)
        self._profile_check_timer.setSingleShot(True)
        # Long enough for VoiceMeeter to settle after a batch of changes.
        self._profile_check_timer.setInterval(900)
        self._profile_check_timer.timeout.connect(self.refresh_profile_state)
        processing_wrapper_layout.addWidget(
            self.profile_panel,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        self.refresh_profile_list()

        lower_layout.addWidget(
            processing_wrapper,
            1,
            Qt.AlignmentFlag.AlignTop,
        )
        lower_layout.addWidget(self.applications_panel, 3)
        self.main_splitter.addWidget(self.lower_container)
        # Extra window height goes to the mixer; the lower panels keep the
        # size the user dragged them to.
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        restored = False
        saved_split = self.window_settings.value("splitter_v1")
        if saved_split is not None:
            try:
                restored = bool(self.main_splitter.restoreState(saved_split))
            except Exception:
                restored = False
        if not restored:
            self.main_splitter.reset_sizes()

    def _build_profile_panel(self):
        """The SETUP PROFILE panel: list, LOAD, SAVE AS, DELETE and status."""
        self.profile_panel = QWidget()
        self.profile_panel.setObjectName("profilePanel")
        self.profile_panel.setStyleSheet(
            "QWidget#profilePanel { background: #101820; "
            f"border: 1px solid {PANEL_BORDER}; border-radius: 8px; }}"
        )
        profile_layout = QVBoxLayout(self.profile_panel)
        profile_layout.setContentsMargins(6, 5, 6, 6)
        profile_layout.setSpacing(4)
        profile_title = QLabel("SETUP PROFILE")
        profile_title.setStyleSheet(SMALL_HEADING_STYLE)
        profile_title.setToolTip(
            "The whole setup under one name: gain, mute, solo, mono and "
            "routing of all four channels, and the mic processing. The "
            "presets in the Mic Processing window change the processing only."
        )
        self.profile_list = QComboBox()
        profile_buttons = QHBoxLayout()
        profile_buttons.setSpacing(4)
        self.profile_load_button = QPushButton("Load")
        self.profile_load_button.clicked.connect(self.on_profile_load)
        profile_save_button = QPushButton("Save as…")
        profile_save_button.clicked.connect(self.on_profile_save)
        self.profile_delete_button = QPushButton("Delete")
        self.profile_delete_button.clicked.connect(self.on_profile_delete)
        for button in (
            self.profile_load_button,
            profile_save_button,
            self.profile_delete_button,
        ):
            button.setFixedHeight(24)
            button.setStyleSheet(
                "QPushButton { padding: 1px 4px; font-size: 11px; }"
            )
            profile_buttons.addWidget(button)
        # One short line: the panel has no room for more. It says what a
        # profile holds, what LOAD did, or that the mixer has moved away from
        # the loaded profile, in which case UPDATE saves it back.
        self.profile_status = QLabel(PROFILE_HOLDS)
        self.profile_status.setStyleSheet("color: #8ba0b5; font-size: 11px;")
        self.profile_update_button = QPushButton("Update")
        self.profile_update_button.setFixedHeight(20)
        self.profile_update_button.setStyleSheet(
            "QPushButton { padding: 0 8px; font-size: 11px; color: #f5b83d; "
            "border-color: #6b5a24; }"
        )
        self.profile_update_button.clicked.connect(self.on_profile_update)
        self.profile_update_button.setVisible(False)
        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        status_row.addWidget(self.profile_status, 1)
        status_row.addWidget(self.profile_update_button)
        profile_layout.addWidget(profile_title)
        profile_layout.addWidget(self.profile_list)
        profile_layout.addLayout(profile_buttons)
        profile_layout.addLayout(status_row)

    def _start_services(self):
        """Tray, hotkeys, the local API and the VoiceMeeter connection."""
        # True once the program is really quitting, as opposed to the window
        # being closed to the tray.
        self._quitting = False
        self.tray = None
        self.tray_icons = {}  # state -> icon, made on first use
        self.mute_badge = None
        self.create_tray()
        # Windows is shutting down or the user is signing out: do not answer
        # that by hiding in the tray, which would hold the shutdown up.
        QApplication.instance().commitDataRequest.connect(
            self.prepare_to_quit
        )

        self.hotkey_filter = HotkeyFilter(
            self.on_hotkey, self.show_from_tray, self.quit_application
        )
        self._held_key = None  # (virtual key, mute state before) while held
        self._held_key_timer = QTimer(self)
        self._held_key_timer.setInterval(20)
        self._held_key_timer.timeout.connect(self.check_held_key)
        if setting_bool(self.window_settings, "compact_mode", False):
            self.set_compact(True, remember_geometry=False)

        self.local_api = LocalApi(self)
        self.local_api.call_requested.connect(self.on_api_call)
        self.restart_api()
        self.phone_remote = PhoneRemote(self.remote_files())
        self.phone_remote.call_requested.connect(self.on_api_call)
        self.phone_remote.paired.connect(self.on_device_paired)
        self.restart_phone_remote()
        self.hotkey_filter.window_handle = int(self.winId())
        QApplication.instance().installNativeEventFilter(self.hotkey_filter)
        if self.register_hotkeys() and self.tray is not None:
            taken = ", ".join(text for text, _label in self.refused_hotkeys.values())
            self.tray.showMessage(
                "FaderDeck",
                f"Another program, or another running FaderDeck, already uses {taken}. "
                "Pick another combination under Settings, Hotkeys.",
                self.tray.icon(),
                8000,
            )

        # Connect to VoiceMeeter, then keep watching: it can be closed and
        # started again while FaderDeck stays open.
        self.connect_vm()
        self.connection_timer = QTimer(self)
        self.connection_timer.setInterval(2000)
        self.connection_timer.timeout.connect(self.check_connection)
        self.connection_timer.start()

        QTimer.singleShot(1200, self.maybe_welcome)
        self.updater = UpdateChecker(self)
        self.updater.found.connect(self.on_update_found)
        self.updater.latest.connect(self.on_update_latest)
        self.updater.failed.connect(self.on_update_failed)
        self.updater.progressed.connect(self.on_update_progress)
        self.updater.downloaded.connect(self.on_update_downloaded)
        self._update_quiet = True
        self._update_dialog = None
        self._pending_update = None
        if self.tray is not None:
            self.tray.messageClicked.connect(self.offer_update)
        # Only the installed program updates itself; a run from source
        # can still check by hand in Settings.
        if getattr(sys, "frozen", False) and setting_bool(
            self.window_settings, "check_updates", True
        ):
            QTimer.singleShot(5000, lambda: self.check_for_updates(quiet=True))


    # Updates.

    def check_for_updates(self, quiet=False):
        """Ask GitHub for a newer release. Quiet: only speak when there is one."""
        self._update_quiet = quiet
        self.updater.check()

    def on_update_found(self, update):
        self._pending_update = update
        if self.isVisible():
            self.offer_update()
        elif self.tray is not None:
            self.tray.showMessage(
                "FaderDeck",
                f"FaderDeck {update.version} is available. Click to install.",
                self.tray.icon(),
                8000,
            )

    def on_update_latest(self):
        if not self._update_quiet:
            QMessageBox.information(
                self, "FaderDeck", f"FaderDeck {APP_VERSION} is the latest version."
            )

    def on_update_failed(self, problem):
        if self._update_dialog is not None:
            self._update_dialog.close()
            self._update_dialog = None
        if not self._update_quiet:
            QMessageBox.warning(
                self, "FaderDeck", f"The update did not work: {problem}"
            )

    def offer_update(self):
        update = self._pending_update
        if update is None:
            return
        self.show_from_tray()
        box = QMessageBox(self)
        box.setWindowTitle("FaderDeck")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"FaderDeck {update.version} is available; you have {APP_VERSION}."
            f"<br><a href=\"{update.page}\">What is new</a>"
        )
        box.setInformativeText(
            "FaderDeck closes while it updates and starts again afterwards."
        )
        install = box.addButton("Install now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not install:
            return
        self._update_quiet = False
        self._update_dialog = QProgressDialog(
            "Downloading the update...", "Cancel", 0, 100, self
        )
        self._update_dialog.setWindowTitle("FaderDeck")
        self._update_dialog.canceled.connect(self.cancel_update)
        self._update_dialog.show()
        self.updater.download(update)

    def cancel_update(self):
        self.updater.cancelled = True

    def on_update_progress(self, done, total):
        if self._update_dialog is not None and total > 0:
            self._update_dialog.setValue(min(100, done * 100 // total))

    def on_update_downloaded(self, path):
        """Start the installer, then quit so it can replace this program."""
        if self._update_dialog is not None:
            self._update_dialog.close()
            self._update_dialog = None
        log.info(f"Starting the installer: {path}")
        subprocess.Popen(
            [path, *INSTALLER_OPTIONS], close_fds=True, env=installer_environment()
        )
        self.quit_application()

    def connect_vm(self):
        """Log in to VoiceMeeter and start the event and level threads.

        Safe to call again after VoiceMeeter was restarted: the same API
        object is reused, so the existing widgets keep working.
        """
        if self.vm is None and load_voicemeeterlib() is None:
            self._show_connection_state()
            return
        try:
            if self.vm is None:
                self.vm = voicemeeterlib.api(
                    "potato",
                    ratelimit=0.05,
                    ldirty=True,
                    pdirty=True,
                )

            self.vm.login()
            self._logged_in = True

            if self.vm_observer is None:
                self.vm_observer = VMObserver(self.vm_bridge)
                self.vm.observer.add(self.vm_observer)

            self.vm.init_thread()
            self.start_mic_level_worker()

            self.create_strips()
            self.refresh_outputs()
            self.apply_stream_mix()
            self.create_processing_controls()
            self.create_applications()

            self.connected = True
            log.info("Connected to VoiceMeeter Potato")

            # After a reconnect the widgets already exist and may be stale.
            for widget in self.strips.values():
                widget.sync_from_voicemeeter()
            self.sync_processing_controls()

        except Exception as e:
            log.error(
                f"VoiceMeeter connection failed: "
                f"{type(e).__name__}: {e}"
            )
            self.release_vm()

        self._show_connection_state()

    def release_vm_at_exit(self):
        """Log out when the program ends without its window being closed:
        Ctrl+C, a closed terminal, an error, Windows signing out.

        VoiceMeeter cannot tell that a client has died. A login that is never
        logged out stays listed there (the "R" marks at the top of its
        window) until VoiceMeeter itself is restarted.
        """
        with self._exit_lock:
            if self.vm is None or not self._logged_in:
                return
            self._logged_in = False
            try:
                self.vm.end_thread()
            except Exception:
                pass
            try:
                self.vm.logout()
                log.info("Logged out of VoiceMeeter at exit")
            except Exception as e:
                log.info(f"VoiceMeeter logout at exit: {type(e).__name__}: {e}")

    def release_vm(self):
        """Stop every thread that talks to VoiceMeeter, then log out.

        The API object is kept: the strip and processing widgets hold on to
        it and are reused when VoiceMeeter comes back.
        """
        self.connected = False
        self.stop_mic_level_worker()
        if self.vm is None:
            return

        try:
            # IMPORTANT: stop and join the updater/producer threads BEFORE
            # logging out.
            self.vm.end_thread()
        except Exception as e:
            log.error(
                f"Failed to stop VoiceMeeter event thread: "
                f"{type(e).__name__}: {e}"
            )

        if self._logged_in:
            self._logged_in = False
            try:
                self.vm.logout()
            except Exception as e:
                # Expected when VoiceMeeter itself has gone away.
                log.info(
                    f"VoiceMeeter logout: {type(e).__name__}: {e}"
                )

    def check_connection(self):
        """Notice VoiceMeeter closing or starting. Runs every two seconds."""
        running = voicemeeter_is_running()

        if self.connected:
            if running:
                self.refresh_outputs()
            if not running:
                log.warning("VoiceMeeter was closed; waiting for it to return")
                if self.processing_dialog is not None:
                    self.processing_dialog.close()
                self.release_vm()
                self._show_connection_state()
            return

        # Only log in while VoiceMeeter is running: logging in would start it,
        # and it may have been closed on purpose. Wait one extra check so its
        # audio engine is up before the first calls.
        self._seen_running = self._seen_running + 1 if running else 0
        if self._seen_running >= 2:
            self._seen_running = 0
            self.connect_vm()

    def _show_connection_state(self):
        if self.connected:
            self.status_label.setText("● Connected to VoiceMeeter Potato")
            self.status_label.setStyleSheet(
                "color: #3fb950; font-weight: bold;"
            )
        else:
            self.status_label.setText("● Disconnected")
            self.status_label.setStyleSheet(
                "color: #f85149; font-weight: bold;"
            )
        self.offline_banner.setVisible(not self.connected)
        if not self.connected:
            self.vm_install_state = voicemeeter_install_state()
        installed = self.vm_install_state == "potato"
        self.banner_text.setText(
            "VoiceMeeter Potato is not running. FaderDeck connects "
            "automatically when it starts." if installed else
            "VoiceMeeter Potato is not installed. FaderDeck needs it to work."
        )
        self.start_button.setVisible(installed)
        self.download_button.setVisible(not installed)
        # Controls that would write to VoiceMeeter are greyed out meanwhile.
        self.mixer_container.setEnabled(self.connected)
        self.processing_toggle.setEnabled(self.connected)
        self.profile_panel.setEnabled(self.connected)
        self.update_processing_summary()
        self.sync_tray()
        if self.connected and not self.active_profile:
            self.restore_active_profile()
        else:
            self.refresh_profile_state()

    def create_strips(self):
        if self.strips:
            return

        for name, index in STRIPS.items():
            widget = StripWidget(
                name,
                self.vm,
                index,
            )


            self.strips[name] = widget


            widget.setMinimumHeight(MIXER_CARD_MIN_HEIGHT)
            widget.set_compact(self.compact)
            widget.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Expanding,
            )
            self.mixer_layout.addWidget(

                widget

            )


    def toggle_processing(self, expanded):
        """Open or close Mic Processing in a separate popup dialog."""
        if expanded:
            first_open = self.processing_dialog is None
            if first_open:
                self._build_processing_dialog()

            self.processing_tabs.setVisible(True)

            # The controls normally exist already (see connect_vm). They are
            # not kept in sync while the popup is closed, so refresh them now.
            self.create_processing_controls()
            self.sync_processing_controls()
            for control in self.processing_blocks().values():
                control.take_snapshot()

            if first_open:
                self._mark_thresholds()
                self.processing_dialog.adjustSize()
                self.processing_dialog.resize(
                    max(560, self.processing_dialog.width()),
                    max(540, self.processing_dialog.height()),
                )
                self._place_processing_dialog()

            self.processing_dialog.show()
            self.processing_dialog.raise_()
            self.processing_dialog.activateWindow()
        else:
            if self.processing_dialog is not None:
                self.processing_dialog.close()

    def _build_processing_dialog(self):
        """The Mic Processing window, made the first time it opens."""
        self.processing_dialog = QDialog(self)
        self.processing_dialog.setWindowTitle("FaderDeck — Mic Processing")
        self.processing_dialog.setWindowIcon(self.windowIcon())
        self.processing_dialog.setModal(False)
        self.processing_dialog.setWindowFlag(
            Qt.WindowType.WindowContextHelpButtonHint, False
        )
        self.processing_dialog.setMinimumSize(560, 540)
        self.processing_dialog.resize(620, 560)

        dialog_layout = QVBoxLayout(self.processing_dialog)
        dialog_layout.setContentsMargins(8, 8, 8, 8)
        dialog_layout.setSpacing(6)

        level_row = QHBoxLayout()
        level_row.setContentsMargins(4, 0, 4, 0)
        level_row.setSpacing(8)
        level_title = QLabel("MIC INPUT")
        level_title.setStyleSheet(
            SMALL_HEADING_STYLE + " "
            "padding-bottom: 14px;"
        )
        self.mic_level_bar = MicLevelBar()
        level_row.addWidget(level_title)
        level_row.addWidget(self.mic_level_bar, 1)
        dialog_layout.addLayout(level_row)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(4, 0, 4, 2)
        preset_row.setSpacing(6)
        preset_title = QLabel("VOICE PRESET")
        preset_title.setStyleSheet(SMALL_HEADING_STYLE)
        self.preset_list = QComboBox()
        self.preset_list.setToolTip(
            "Saved settings of the compressor, gate and denoiser together"
        )
        self.preset_load_button = QPushButton("Load")
        self.preset_load_button.setToolTip(
            "Replace the compressor, gate and denoiser values with "
            "this preset. \"Reset\" brings back the values from when the "
            "window was opened."
        )
        self.preset_load_button.clicked.connect(self.on_preset_load)
        save_button = QPushButton("Save as…")
        save_button.setToolTip("Save the current values as a preset")
        save_button.clicked.connect(self.on_preset_save)
        self.preset_delete_button = QPushButton("Delete")
        self.preset_delete_button.clicked.connect(self.on_preset_delete)
        for button in (
            self.preset_load_button, save_button, self.preset_delete_button
        ):
            button.setFixedHeight(26)
            button.setStyleSheet("QPushButton { padding: 2px 10px; }")
        preset_row.addWidget(preset_title)
        preset_row.addWidget(self.preset_list, 1)
        preset_row.addWidget(self.preset_load_button)
        preset_row.addWidget(save_button)
        preset_row.addWidget(self.preset_delete_button)
        dialog_layout.addLayout(preset_row)
        preset_note = QLabel(
            "Compressor, gate and denoiser only. Setup profiles on "
            "the main screen hold everything."
        )
        preset_note.setStyleSheet(
            "color: #8ba0b5; font-size: 11px; padding: 0 4px 2px 4px;"
        )
        dialog_layout.addWidget(preset_note)
        self.refresh_preset_list()

        self.processing_tabs.setVisible(True)
        dialog_layout.addWidget(self.processing_tabs, 1)

        self.processing_dialog.finished.connect(
            self._processing_dialog_closed
        )

    # Mixer profiles: the state of all four strips and the mic processing
    # under a name, stored as JSON under "mixer_profiles". The presets in the
    # Mic Processing window hold the processing alone.

    def load_profiles(self):
        return stored_dict(self.window_settings, "mixer_profiles")

    def store_profiles(self, profiles):
        store_dict(self.window_settings, "mixer_profiles", profiles)

    def save_profile(self, name):
        name = (name or "").strip()
        if not name or not self.strips:
            return False
        profiles = self.load_profiles()
        profile = {
            strip_name: strip.profile_state()
            for strip_name, strip in self.strips.items()
        }
        # A profile is the whole setup, so the mic processing belongs to it.
        blocks = self.processing_blocks()
        if all(blocks.values()):
            profile[PROFILE_PROCESSING] = {
                label: control.preset_state()
                for label, control in blocks.items()
            }
            for label, control in blocks.items():
                control.set_reference(profile[PROFILE_PROCESSING][label])
        profiles[name] = profile
        self.store_profiles(profiles)
        self.refresh_profile_list(select=name)
        self.set_active_profile(name, profile)
        self.show_profile_status("Saved.")
        return True

    def current_profile_state(self):
        """The mixer as a profile would store it right now."""
        state = {
            strip_name: strip.profile_state()
            for strip_name, strip in self.strips.items()
        }
        blocks = self.processing_blocks()
        if all(blocks.values()):
            try:
                state[PROFILE_PROCESSING] = {
                    label: control.preset_state()
                    for label, control in blocks.items()
                }
            except Exception as e:
                log.debug(f"Mic processing left out of the profile state: {e}")
                pass
        return state

    def set_active_profile(self, name, profile=None):
        """Remember which profile the mixer was last loaded from or saved to."""
        self.active_profile = name or ""
        self._profile_reference = profile if name else None
        self.window_settings.setValue("active_profile", self.active_profile)
        self.refresh_profile_state()

    def restore_active_profile(self):
        """After a start: is the mixer still as the last used profile says?"""
        name = str(self.window_settings.value("active_profile", "") or "")
        profile = self.load_profiles().get(name)
        if isinstance(profile, dict):
            self.active_profile = name
            self._profile_reference = profile
            self.refresh_profile_list(select=name)
        self.refresh_profile_state()

    def profile_is_changed(self):
        """True when the mixer no longer matches the active profile."""
        if not self.active_profile or not self.connected:
            return False
        if not isinstance(self._profile_reference, dict):
            return False
        return not profile_states_match(
            self._profile_reference, self.current_profile_state()
        )

    def refresh_profile_state(self):
        """Show whether the mixer still matches the active profile."""
        changed = self.profile_is_changed()
        self.profile_update_button.setVisible(changed)
        name = self.active_profile
        if changed:
            self.profile_update_button.setToolTip(
                f"Save the mixer as it is now into \u201c{name}\u201d"
            )
            self.profile_status.setText(f"{name}: changed")
            self.profile_status.setToolTip(
                f"The mixer no longer matches \u201c{name}\u201d. \"Load\" brings "
                "the profile back; \"Update\" saves the current state into it."
            )
        elif time.monotonic() >= self._profile_message_until:
            self.profile_status.setText(
                f"{name} is loaded." if name else PROFILE_HOLDS
            )
            self.profile_status.setToolTip("")

    def on_profile_update(self):
        if self.active_profile:
            self.save_profile(self.active_profile)

    def processing_values(self):
        """Current values of the three processing blocks, for comparing."""
        values = {}
        for label, control in self.processing_blocks().items():
            try:
                values[label] = control._read_state() if control else None
            except Exception:
                values[label] = None
        return values

    def apply_profile(self, name):
        """Send a stored profile to VoiceMeeter. False if any strip failed."""
        profile = self.load_profiles().get(name)
        if not isinstance(profile, dict) or not self.connected:
            return False
        before = {
            strip_name: strip.profile_state()
            for strip_name, strip in self.strips.items()
        }
        processing_before = self.processing_values()
        applied = True
        for strip_name, strip in self.strips.items():
            state = profile.get(strip_name)
            if not isinstance(state, dict) or not strip.apply_profile(state):
                applied = False

        # Profiles saved before v1.3.1 have no mic processing in them.
        processing = profile.get(PROFILE_PROCESSING)
        if isinstance(processing, dict):
            for label, control in self.processing_blocks().items():
                if control is None or not control.apply_preset(
                    processing.get(label)
                ):
                    applied = False

        changed = [
            strip_name
            for strip_name, strip in self.strips.items()
            if strip.profile_state() != before[strip_name]
        ]
        if self.processing_values() != processing_before:
            changed.append("Mic processing")
        # A press on LOAD always gets an answer, also when nothing differed.
        self.set_active_profile(name, profile)
        if changed:
            self.show_profile_status(
                f"Loaded. Changed: {', '.join(changed)}."
            )
        else:
            self.show_profile_status("Already matches; nothing to change.")
        self.update_processing_summary()
        self.sync_tray()
        return applied

    def profile_has_processing(self, name):
        profile = self.load_profiles().get(name)
        return isinstance(profile, dict) and isinstance(
            profile.get(PROFILE_PROCESSING), dict
        )

    def show_profile_status(self, text):
        """Show what LOAD or SAVE did; the standing state returns afterwards."""
        self._profile_message_until = time.monotonic() + 4.0
        self.profile_status.setText(text)
        self.profile_status.setToolTip("")
        self.profile_update_button.setVisible(False)
        QTimer.singleShot(4100, self, self.refresh_profile_state)

    def delete_profile(self, name):
        profiles = self.load_profiles()
        if profiles.pop(name, None) is None:
            return False
        self.store_profiles(profiles)
        self.refresh_profile_list()
        if name == self.active_profile:
            self.set_active_profile("")
        return True

    def refresh_profile_list(self, select=None):
        names = sorted(self.load_profiles(), key=str.casefold)
        current = select or self.profile_list.currentText()
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        self.profile_list.addItems(names)
        if current in names:
            self.profile_list.setCurrentText(current)
        self.profile_list.blockSignals(False)
        self.profile_list.setPlaceholderText("No profiles yet")
        self.profile_load_button.setEnabled(bool(names))
        self.profile_delete_button.setEnabled(bool(names))

    def on_profile_load(self):
        name = self.profile_list.currentText()
        if not name:
            return
        if not self.apply_profile(name):
            QMessageBox.warning(
                self,
                "FaderDeck",
                f"The profile \u201c{name}\u201d could not be applied completely.",
            )
        elif not self.profile_has_processing(name):
            QMessageBox.information(
                self,
                "FaderDeck",
                f"\u201c{name}\u201d was saved before profiles included the mic "
                "processing, so the compressor, gate and denoiser were left "
                "as they are.\n\nTo add them, set the mic processing the way "
                "you want it and save the profile again under the same name.",
            )

    def on_profile_save(self):
        name, accepted = QInputDialog.getText(
            self,
            "Save mixer profile",
            "Name of the profile:",
            text=self.profile_list.currentText(),
        )
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.load_profiles():
            answer = QMessageBox.question(
                self, "FaderDeck", f"Replace the profile \u201c{name}\u201d?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.save_profile(name)

    def on_profile_delete(self):
        name = self.profile_list.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self, "FaderDeck", f"Delete the profile \u201c{name}\u201d?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_profile(name)

    def update_processing_summary(self):
        """Show each block's Amount under the button and its state on its tab."""
        blocks = (
            ("Compressor", "Compressor", self.compressor_control),
            ("Gate", "Gate", self.gate_control),
            ("Denoiser", "Denoiser", self.denoiser_control),
        )
        lines = []
        for index, (label, tab, control) in enumerate(blocks):
            if control is None or not self.connected:
                continue
            try:
                amount = float(control.target.knob)
            except Exception as e:
                log.debug(f"Could not read {label} amount: {e}")
                continue
            if control._bypassed is not None:
                state, mark = "bypassed", " · BYPASSED"
            elif amount <= 0:
                state, mark = "off", " · OFF"
            else:
                state, mark = f"{amount:.1f}", ""
            lines.append(f"{label}: {state}")
            if index < self.processing_tabs.count():
                self.processing_tabs.setTabText(index, tab + mark)
        self.processing_summary.setText("\n".join(lines))
        self.processing_summary.setVisible(bool(lines))

    # Mic processing presets: one preset holds the compressor, the gate and
    # the denoiser together, stored as JSON under "processing_presets".

    def processing_blocks(self):
        return {
            "compressor": self.compressor_control,
            "gate": self.gate_control,
            "denoiser": self.denoiser_control,
        }

    def load_presets(self):
        return stored_dict(self.window_settings, "processing_presets")

    def store_presets(self, presets):
        store_dict(self.window_settings, "processing_presets", presets)

    def save_preset(self, name):
        """Store the current values of all three blocks under a name."""
        name = (name or "").strip()
        if not name or not all(self.processing_blocks().values()):
            return False
        presets = self.load_presets()
        presets[name] = {
            label: control.preset_state()
            for label, control in self.processing_blocks().items()
        }
        self.store_presets(presets)
        self.refresh_preset_list(select=name)
        for label, control in self.processing_blocks().items():
            control.set_reference(presets[name][label])
        return True

    def apply_preset(self, name):
        """Send a stored preset to VoiceMeeter. False if any block failed."""
        preset = self.load_presets().get(name)
        if not isinstance(preset, dict) or not self.connected:
            return False
        applied = True
        for label, control in self.processing_blocks().items():
            if control is None or not control.apply_preset(preset.get(label)):
                applied = False
        return applied

    def delete_preset(self, name):
        presets = self.load_presets()
        if presets.pop(name, None) is None:
            return False
        self.store_presets(presets)
        self.refresh_preset_list()
        return True

    def refresh_preset_list(self, select=None):
        if self.preset_list is None:
            return
        names = sorted(self.load_presets(), key=str.casefold)
        current = select or self.preset_list.currentText()
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        self.preset_list.addItems(names)
        if current in names:
            self.preset_list.setCurrentText(current)
        self.preset_list.blockSignals(False)
        self.preset_list.setPlaceholderText("No presets yet")
        self.preset_load_button.setEnabled(bool(names))
        self.preset_delete_button.setEnabled(bool(names))

    def on_preset_load(self):
        name = self.preset_list.currentText()
        if name and not self.apply_preset(name):
            QMessageBox.warning(
                self.processing_dialog,
                "FaderDeck",
                f"The preset \u201c{name}\u201d could not be applied completely.",
            )

    def on_preset_save(self):
        name, accepted = QInputDialog.getText(
            self.processing_dialog,
            "Save preset",
            "Name of the preset:",
            text=self.preset_list.currentText(),
        )
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.load_presets():
            answer = QMessageBox.question(
                self.processing_dialog,
                "FaderDeck",
                f"Replace the preset \u201c{name}\u201d?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.save_preset(name)

    def on_preset_delete(self):
        name = self.preset_list.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self.processing_dialog,
            "FaderDeck",
            f"Delete the preset \u201c{name}\u201d?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_preset(name)

    def _mark_thresholds(self):
        """Show the gate and compressor thresholds on the Mic input bar."""
        for label, color, control in (
            ("Gate", "#f5b83d", self.gate_control),
            ("Comp", COMPRESSOR_MARK, self.compressor_control),
        ):
            slider = control.controls["threshold"]["slider"]
            scale = control.controls["threshold"]["scale"]
            self.mic_level_bar.add_marker(
                label, color, lambda s=slider, k=scale: s.value() / k
            )
            slider.valueChanged.connect(self.mic_level_bar.update)

    def _place_processing_dialog(self):
        """Put the popup where it was last, else beside the main window.

        It must not cover the mixer: the Mic meters are what you watch while
        changing these values.
        """
        saved = self.window_settings.value("processing_geometry_v1")
        if saved is not None:
            try:
                if self.processing_dialog.restoreGeometry(saved):
                    return
            except Exception:
                pass

        dialog = self.processing_dialog.frameGeometry()
        window = self.frameGeometry()
        screen = self.screen().availableGeometry()
        if window.right() + dialog.width() <= screen.right():
            dialog.moveTopLeft(window.topRight())
        elif window.left() - dialog.width() >= screen.left():
            dialog.moveTopRight(window.topLeft())
        else:
            dialog.moveCenter(window.center())
        self.processing_dialog.move(dialog.topLeft())

    def _save_processing_geometry(self):
        if self.processing_dialog is not None:
            self.window_settings.setValue(
                "processing_geometry_v1",
                self.processing_dialog.saveGeometry(),
            )

    def _processing_dialog_closed(self, _result):
        self._save_processing_geometry()
        self.processing_toggle.blockSignals(True)
        self.processing_toggle.setChecked(False)
        self.processing_toggle.blockSignals(False)

    def create_processing_controls(self):
        """Make the compressor, gate and denoiser tabs, once each."""
        for attribute, control_class, title in (
            ("compressor_control", CompressorControl, "Compressor"),
            ("gate_control", GateControl, "Gate"),
            ("denoiser_control", DenoiserControl, "Denoiser"),
        ):
            if getattr(self, attribute) is None:
                setattr(self, attribute, control_class(self.vm))
                self.processing_tabs.addTab(getattr(self, attribute), title)

    def create_applications(self):
        if self.application_control is not None:
            return

        self.application_control = ApplicationControl()
        self.application_control.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.application_control.setMinimumHeight(APPLICATION_PANEL_MIN_HEIGHT)
        self.applications_panel_layout.addWidget(self.application_control, 1)
        self.application_control.setVisible(True)

    def start_mic_level_worker(self):
        """Start continuous Mic level reads away from the Qt GUI thread."""
        if self.vm is None or self.mic_level_thread is not None:
            return

        self.mic_level_thread = QThread(self)
        self.mic_level_worker = StripLevelWorker(self.vm)
        self.mic_level_worker.moveToThread(self.mic_level_thread)

        self.mic_level_thread.started.connect(self.mic_level_worker.start)
        self.mic_level_worker.levels_received.connect(
            self.on_levels_received
        )
        self.mic_level_worker.error.connect(
            lambda message: log.error(message)
        )
        self.mic_level_worker.finished.connect(
            self.mic_level_thread.quit
        )

        self.mic_level_thread.start()

    def stop_mic_level_worker(self):
        """Stop the Mic level worker on its own Qt thread."""
        if self.mic_level_worker is None or self.mic_level_thread is None:
            return

        thread = self.mic_level_thread
        worker = self.mic_level_worker

        try:
            # Run stop() directly on the worker thread and wait for that
            # method to finish. This avoids a queued stop request getting
            # stuck behind shutdown processing and removes the old 2-second
            # wait from the normal close path.
            QMetaObject.invokeMethod(
                worker,
                "stop",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
            thread.quit()
            thread.wait(300)
        except Exception as exc:
            log.error(
                f"Failed to stop Mic level worker: "
                f"{type(exc).__name__}: {exc}"
            )
            thread.quit()
            thread.wait(300)
        finally:
            self.mic_level_worker = None
            self.mic_level_thread = None

    def update_mixer_levels(self):
        """Refresh the visual mixer VU meters on a steady Qt timer."""

        if not self.connected:
            return

        for widget in self.strips.values():
            widget.animate_level()
        if self.mic_level_bar is not None and self.mic_level_bar.isVisible():
            self.mic_level_bar.animate()


    def on_levels_received(self, name, left, right):
        """Receive one strip's levels from StripLevelWorker."""
        strip = self.strips.get(name)
        if strip is not None:
            strip.set_channel_levels((left, right))
        if name == "Mic" and self.mic_level_bar is not None:
            self.mic_level_bar.set_level(max(left, right))


    # The normal and the compact view each remember their own size and place.

    def geometry_setting(self):
        return "geometry_compact" if self.compact else "geometry_v2"

    def save_window_geometry(self):
        self.window_settings.setValue(self.geometry_setting(), self.saveGeometry())

    def restore_window_geometry(self):
        default = COMPACT_DEFAULT_SIZE if self.compact else WINDOW_DEFAULT_SIZE
        saved = self.window_settings.value(self.geometry_setting())
        if saved is not None:
            try:
                if self.restoreGeometry(saved):
                    return
            except Exception:
                pass
        self.resize(*default)

    def set_compact(self, compact, remember_geometry=True):
        """Switch between the full window and the compact strips-only view."""
        compact = bool(compact)
        if remember_geometry and compact != self.compact:
            self.save_window_geometry()
        self.compact = compact
        self.compact_button.setChecked(compact)
        self.compact_button.setToolTip(
            "Back to the full view"
            if compact
            else "Compact view: faders, meters and mute only"
        )
        self.window_settings.setValue("compact_mode", compact)

        for strip in self.strips.values():
            strip.set_compact(compact)
        # Applications, mic processing and profiles live in the lower pane.
        self.lower_container.setVisible(not compact)
        self.app_subtitle.setVisible(not compact)
        self.setMinimumSize(*(COMPACT_MIN_SIZE if compact else WINDOW_MIN_SIZE))
        self.restore_window_geometry()

    def create_tray(self):
        """Add the tray icon with its menu, when the desktop has a tray."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = QApplication.instance().windowIcon()
        if icon.isNull():
            icon = QIcon(resource_path("faderdeck.ico"))
        self.tray = QSystemTrayIcon(icon, self)

        menu = QMenu(self)
        menu.addAction("Show FaderDeck").triggered.connect(
            self.show_from_tray
        )
        self.tray_mute_action = menu.addAction("Mute microphone")
        self.tray_mute_action.setCheckable(True)
        self.tray_mute_action.triggered.connect(self.toggle_mic_mute)
        self.tray_listen_action = menu.addAction("Monitor microphone")
        self.tray_listen_action.setCheckable(True)
        self.tray_listen_action.triggered.connect(self.toggle_mic_listen)
        self.tray_stream_action = menu.addAction("Mute stream (voice chat still hears you)")
        self.tray_stream_action.setCheckable(True)
        self.tray_stream_action.triggered.connect(self.toggle_stream_mute)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self.quit_application)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.setToolTip("FaderDeck")
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_from_tray()

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(600, self.maybe_welcome)

    def sync_tray(self):
        """Show the Mic mute state on the tray icon and in its menu, and
        on the mute badge."""
        self.sync_mic_shortcuts()
        listening, stream_muted = self.mic_shortcut_state()
        mic = self.strips.get("Mic")
        state = None
        if self.connected:
            state = mute_indicator_state(
                bool(mic is not None and mic.mute_button.isChecked()),
                stream_muted,
            )
        self.sync_mute_badge(state)
        if self.tray is None:
            return
        self.sync_tray_icon(state)
        self.tray_listen_action.setChecked(listening)
        self.tray_listen_action.setEnabled(self.connected)
        self.tray_stream_action.setChecked(bool(stream_muted))
        self.tray_stream_action.setEnabled(self.connected and stream_muted is not None)
        mic = self.strips.get("Mic")
        muted = bool(mic is not None and mic.mute_button.isChecked())
        self.tray_mute_action.setChecked(muted)
        self.tray_mute_action.setEnabled(self.connected)
        self.tray.setToolTip(
            "FaderDeck — microphone muted" if muted else "FaderDeck"
        )

    def sync_tray_icon(self, state):
        if not setting_bool(self.window_settings, "tray_mute_icon", True):
            state = None
        if state not in self.tray_icons:
            base = QApplication.instance().windowIcon()
            if base.isNull():
                base = QIcon(resource_path("faderdeck.ico"))
            self.tray_icons[state] = (
                base if state is None
                else badged_icon(base, MUTE_INDICATORS[state][1])
            )
        if self.tray.icon().cacheKey() != self.tray_icons[state].cacheKey():
            self.tray.setIcon(self.tray_icons[state])

    def sync_mute_badge(self, state):
        if not setting_bool(self.window_settings, "mute_overlay", False):
            state = None
        if state is None:
            if self.mute_badge is not None:
                self.mute_badge.hide()
            return
        if self.mute_badge is None:
            self.mute_badge = MuteBadge()
            self.mute_badge.moved.connect(self.save_badge_place)
            self.mute_badge.set_state(state)
            self.mute_badge.place(self.saved_badge_place())
        elif self.mute_badge.state != state:
            self.mute_badge.set_state(state)
        self.mute_badge.show()
        self.mute_badge.raise_()

    def saved_badge_place(self):
        try:
            x, y = str(self.window_settings.value("mute_overlay_pos", "")).split(",")
            return QPoint(int(x), int(y))
        except ValueError:
            return None

    def save_badge_place(self, point):
        self.window_settings.setValue("mute_overlay_pos", f"{point.x()},{point.y()}")

    def close_to_tray_enabled(self):
        return self.tray is not None and setting_bool(
            self.window_settings, "close_to_tray", True
        )

    def start_minimized_enabled(self):
        return self.tray is not None and setting_bool(
            self.window_settings, "start_minimized", False
        )

    @staticmethod
    def shift_is_held():
        """True while a Shift key is down, asked from the keyboard itself."""
        return bool(
            QApplication.queryKeyboardModifiers()
            & Qt.KeyboardModifier.ShiftModifier
        )

    def prepare_to_quit(self, *_args):
        self._quitting = True

    def quit_application(self):
        """Really quit, from the tray menu."""
        self._quitting = True
        self.close()

    def current_settings(self):
        """The stored program settings, with their defaults."""
        settings = self.window_settings
        try:
            mic_strip = int(settings.value("mic_strip", 0))
        except (TypeError, ValueError):
            mic_strip = 0
        if not 0 <= mic_strip < HARDWARE_INPUTS:
            mic_strip = 0
        return {
            "mic_strip": mic_strip,
            "listen_bus": self.listen_bus_setting(),
            "monitor_level": self.monitor_level_setting(),
            "stream_bus": ",".join(self.stream_outputs_setting()),
            "theme": theme_settings(settings),
            "themes": saved_themes(settings),
            "close_to_tray": setting_bool(settings, "close_to_tray", True),
            "start_minimized": setting_bool(settings, "start_minimized", False),
            "check_updates": setting_bool(settings, "check_updates", True),
            "mute_sound": setting_bool(settings, "mute_sound", True),
            "mute_overlay": setting_bool(settings, "mute_overlay", False),
            "tray_mute_icon": setting_bool(settings, "tray_mute_icon", True),
            "mute_sound_device": str(settings.value("mute_sound_device", "") or ""),
            "api_enabled": setting_bool(settings, "api_enabled", False),
            "api_port": self.api_port_setting(),
            "remote_enabled": setting_bool(settings, "remote_enabled", False),
            "remote_port": self.remote_port_setting(),
            "remote_devices": self.remote_devices_setting(),
            "api_token": str(settings.value("api_token", "") or ""),
            **{
                key: str(settings.value(key, "") or "")
                for key in CHANNEL_NAME_KEYS.values()
            },
            **{
                f"output_name_{output}": output_name(output, settings)
                for output in ALL_OUTPUTS
            },
            **{
                action.key: str(settings.value(action.key, action.default) or "")
                for action in HOTKEYS
            },
        }

    def open_settings(self):
        dialog = SettingsDialog(
            self,
            self.current_settings(),
            self.vm if self.connected else None,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_settings(dialog.values())

    def refresh_channel_names(self):
        """Show the channel names from the settings on the strips and lists."""
        for name in CHANNEL_NAME_KEYS:
            label = channel_label(name, self.window_settings)
            if name in self.strips:
                self.strips[name].name_label.setText(label)
            title = self.application_control.titles.get(name)
            if title is not None:
                title.setText(f"{label.upper()} APPS")

    # The stream mix.

    mix = "you"  # which mix the faders set: "you" or "stream"

    def maybe_welcome(self):
        """Greet a new user once, when the window is first on screen.
        Without VoiceMeeter Potato, explain that first (once per start)."""
        if not WELCOME:
            return
        if not self.isVisible() or self.isMinimized():
            return  # started in the tray: show_from_tray asks again
        if self.vm_install_state != "potato":
            if not self._missing_shown:
                self._missing_shown = True
                dialog = VoicemeeterMissingDialog(self, self.vm_install_state)
                if self.run_dialog(dialog) == QDialog.DialogCode.Accepted:
                    self.open_voicemeeter_download()
            return  # the welcome waits until VoiceMeeter is there
        if setting_bool(self.window_settings, "welcome_shown", False):
            return
        self.window_settings.setValue("welcome_shown", True)
        self.window_settings.sync()
        if self.run_dialog(WelcomeDialog(self)) == QDialog.DialogCode.Accepted:
            self.run_dialog(StreamSetupDialog(self, self.vm if self.connected else None))

    def open_voicemeeter_download(self):
        QDesktopServices.openUrl(QUrl(VOICEMEETER_DOWNLOAD_URL))

    def run_dialog(self, dialog):
        """exec() a dialog. Kept apart so tests can answer it."""
        return dialog.exec()

    def apply_stream_setup(self, headphones, name_outputs=True):
        """The streaming routing in one go: the microphone on B1 (voice
        chat) and B2 (the stream's voice), Game, Chat and Media on the
        headphones and B3 (the stream's sound). Returns a problem or ""."""
        if not self.connected or not self.strips:
            return "VoiceMeeter is not connected."
        wanted = {
            "Mic": {"B1": True, "B2": True, "B3": False},
            **{
                name: {headphones: True, "B1": False, "B2": False, "B3": True}
                for name in ("Game", "Chat", "Media")
            },
        }
        for name, routes in wanted.items():
            strip = self.strips.get(name)
            if strip is None:
                continue
            for output, on in routes.items():
                button = strip.route_buttons.get(output)
                if button is not None and button.isChecked() != on:
                    button.setChecked(on)
                    strip.on_route_clicked(output, on)
        settings = self.window_settings
        settings.setValue("stream_bus", "B2,B3")
        settings.setValue("listen_bus", headphones)
        if name_outputs:
            for output, name in {headphones: STREAM_SETUP_HEAR, **STREAM_SETUP_NAMES}.items():
                settings.setValue(f"output_name_{output}", name)
        settings.sync()
        self.refresh_outputs()
        self.apply_stream_mix()
        self.sync_tray()
        log.info(f"Streaming setup applied (headphones on {headphones})")
        return ""

    def refresh_outputs(self):
        """Show the outputs that do something, by their names. Checked every
        two seconds: a device chosen in VoiceMeeter appears by itself."""
        if self.vm is None or not self.strips:
            return
        outputs = available_outputs(self.vm)
        if outputs != getattr(self, "_shown_outputs", None):
            self._shown_outputs = outputs
            for strip in self.strips.values():
                strip.place_routes(outputs)
        for strip in self.strips.values():
            strip.rename_routes()
            strip.update_gain_label()

    def stream_mix_buses(self):
        """VoiceMeeter bus indexes of the stream's outputs."""
        return tuple(ROUTE_BUS[output] for output in self.stream_outputs_setting())

    def apply_stream_mix(self):
        """Give every strip the stream's outputs; show the switch when set."""
        buses = self.stream_mix_buses()
        if not buses:
            self.mix = "you"
        for strip in self.strips.values():
            strip.set_mix(buses, self.mix)
        self.set_monitor_level()
        if hasattr(self, "mix_box"):
            self.mix_box.setVisible(bool(buses))
            for mix, button in self.mix_buttons.items():
                button.setChecked(mix == self.mix)

    def monitor_level_setting(self):
        try:
            level = int(float(self.window_settings.value("monitor_level", 0) or 0))
        except (TypeError, ValueError):
            level = 0
        return min(0, max(-30, level))

    def set_monitor_level(self, level=None, output=None):
        """Hear yourself `level` dB quieter on the monitor output (0: as loud
        as others hear you)."""
        mic = self.strips.get("Mic")
        if mic is None or not self.connected:
            return
        level = self.monitor_level_setting() if level is None else level
        bus = ROUTE_BUS.get(output or self.listen_bus_setting())
        offsets = (
            {bus: float(level)}
            if level and bus is not None and bus not in self.stream_mix_buses()
            else {}
        )
        if offsets != mic.offsets:
            mic.set_offsets(offsets)

    def set_mix(self, mix):
        """Let the faders set YOU (what you hear) or STREAM."""
        if not self.stream_mix_buses():
            mix = "you"
        self.mix = mix if mix in ("you", "stream") else "you"
        self.apply_stream_mix()
        log.info(f"Faders set the {self.mix} mix")

    def set_mic_input(self, index):
        """Move the Mic strip and its processing to another hardware input."""
        previous = STRIPS["Mic"]
        set_mic_strip(index)
        index = STRIPS["Mic"]
        if index == previous or self.vm is None:
            return
        mic = self.strips.get("Mic")
        if mic is not None:
            mic.strip_index = index
            mic.strip = self.vm.strip[index]
            mic.source_label.setText(f"Stereo Input {index + 1}")
        for control in self.processing_blocks().values():
            if control is not None:
                # A bypass keeps values of the old input; do not restore them here.
                control._clear_bypass()
                control.strip_index = index
                control.target = getattr(self.vm.strip[index], control.ATTRIBUTE)
        if self.connected:
            if mic is not None:
                mic.sync_from_voicemeeter()
            self.sync_processing_controls()
            self.update_processing_summary()
        log.info(f"Microphone input is now input {index + 1}")

    def apply_settings(self, values):
        """Store the settings and apply those that can change while running."""
        values = dict(values)
        if values.pop("remote_forget", False):
            self.window_settings.setValue("remote_devices", "[]")
            log.info("Phone remote: forgot every paired device")
        for key, value in values.items():
            if key in ("theme", "themes"):
                value = json.dumps(value)
            self.window_settings.setValue(key, value)
        self.window_settings.sync()
        apply_theme(values["theme"])
        self.set_mic_input(values["mic_strip"])
        self.refresh_outputs()
        self.apply_stream_mix()
        self.sync_tray()
        self.refresh_channel_names()

        problem = self.restart_api() or self.restart_phone_remote()
        if problem:
            QMessageBox.warning(self, "FaderDeck", problem)

        refused = self.register_hotkeys()
        if refused:
            QMessageBox.warning(
                self,
                "FaderDeck",
                f"{', '.join(refused)} could not be registered. "
                "Another program is probably using it already. "
                "Choose a different combination in Settings.",
            )

    # Local API.

    def api_port_setting(self):
        try:
            port = int(self.window_settings.value("api_port", API_DEFAULT_PORT))
        except (TypeError, ValueError):
            port = API_DEFAULT_PORT
        return port if 0 <= port <= 65535 else API_DEFAULT_PORT

    def restart_api(self):
        """Start or stop the local API to match the settings.

        Returns a message when it should run but cannot, else an empty string.
        """
        self.local_api.stop()
        current = self.current_settings()
        if not current["api_enabled"] or not current["api_token"]:
            return ""
        try:
            self.local_api.start(current["api_port"], current["api_token"])
        except OSError as e:
            log.warning(f"Local API could not start: {e}")
            return (
                f"Remote control could not start on port {current['api_port']}. "
                "Another program is probably using that port; choose a "
                "different one in Settings."
            )
        log.info(f"Local API listening on 127.0.0.1:{self.local_api.port}")
        return ""

    # Phone and tablet remote.

    def remote_port_setting(self):
        try:
            port = int(self.window_settings.value("remote_port", REMOTE_DEFAULT_PORT))
        except (TypeError, ValueError):
            port = REMOTE_DEFAULT_PORT
        return port if 1024 <= port <= 65535 else REMOTE_DEFAULT_PORT

    def remote_devices_setting(self):
        """Hashes of the paired devices' tokens."""
        try:
            stored = json.loads(self.window_settings.value("remote_devices", "") or "[]")
        except (TypeError, ValueError):
            stored = []
        if not isinstance(stored, list):
            return []
        return [h for h in stored if isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h)]

    def remote_files(self):
        """What the remote serves without a token: its page and icons."""
        try:
            with open(resource_path(REMOTE_PAGE), "rb") as handle:
                page = handle.read()
        except OSError as e:
            log.warning(f"Phone remote page not found: {e}")
            page = b"<h1>FaderDeck</h1><p>The remote page is missing.</p>"
        # The page reloads itself when FaderDeck serves a different one, so
        # a phone that stayed open picks up an update.
        version = hashlib.sha256(page).hexdigest()[:12]
        self.remote_page_version = version
        page = page.replace(b"{{PAGE_VERSION}}", version.encode("ascii"))
        return {
            "/remote": ("text/html; charset=utf-8", page),
            "/remote/manifest.webmanifest": ("application/manifest+json", remote_manifest()),
            "/remote/icon-192.png": ("image/png", logo_png(192)),
            "/remote/icon-512.png": ("image/png", logo_png(512)),
        }

    def on_device_paired(self, device_hash):
        devices = self.remote_devices_setting()
        if device_hash not in devices:
            devices.append(device_hash)
        self.window_settings.setValue("remote_devices", json.dumps(devices))
        self.window_settings.sync()

    def restart_phone_remote(self):
        """Start or stop the phone remote to match the settings.

        Returns a message when it should run but cannot, else an empty string.
        A remote that already runs as asked keeps running, so pressing OK in
        Settings does not drop the connected phones.
        """
        current = self.current_settings()
        remote = self.phone_remote
        if (
            current["remote_enabled"]
            and remote.server is not None
            and remote.port == current["remote_port"]
        ):
            remote.set_devices(current["remote_devices"])
            return ""
        remote.stop()
        if not current["remote_enabled"]:
            return ""
        try:
            self.phone_remote.start(current["remote_port"], current["remote_devices"])
        except OSError as e:
            log.warning(f"Phone remote could not start: {e}")
            return (
                f"The phone remote could not start on port {current['remote_port']}. "
                "Another program is probably using it; choose a different port "
                "in Settings, Remote control."
            )
        log.info(f"Phone remote listening on port {self.phone_remote.port}")
        return ""

    def on_api_call(self, call):
        """Answer a request from the local API. Runs on the GUI thread."""
        try:
            result = self.handle_api_call(call.method, call.parts, call.params)
        except Exception as e:
            log.error(f"Local API call failed: {type(e).__name__}: {e}")
            result = (500, {"error": "Internal error."})
        if not call.future.done():
            call.future.set_result(result)

    def api_state(self):
        listening, stream_muted = self.mic_shortcut_state()
        return {
            "connected": self.connected,
            "page": getattr(self, "remote_page_version", ""),
            "mix": self.mix,
            "stream_mix": bool(self.stream_mix_buses()),
            "names": {name: channel_label(name, self.window_settings) for name in self.strips},
            "monitor": listening,
            "stream_mute": stream_muted,
            "profile": self.active_profile,
            "profile_changed": self.profile_is_changed(),
            "channels": {
                name: strip.profile_state()
                for name, strip in self.strips.items()
            },
        }

    def handle_api_call(self, method, parts, params):
        """Carry out one API request and return (HTTP status, answer)."""
        reading = (parts == ["state"] or parts == ["profiles"])
        if reading and method != "GET":
            return 405, {"error": "Use GET to read."}
        if not reading and method != "POST":
            return 405, {"error": "Use POST to change something."}

        if parts == ["state"]:
            return 200, self.api_state()
        if parts == ["profiles"]:
            return 200, {
                "profiles": sorted(self.load_profiles(), key=str.casefold),
                "active": self.active_profile,
            }

        if not self.connected:
            return 409, {"error": "VoiceMeeter is not connected."}

        if len(parts) == 2 and parts[0] in ("mute", "gain"):
            channels = {name.casefold(): name for name in self.strips}
            name = channels.get(parts[1].casefold())
            if name is None:
                return 404, {"error": f"Unknown channel: {parts[1]}"}
            strip = self.strips[name]

            if parts[0] == "mute":
                wanted = params.get("state", "toggle").casefold()
                if wanted not in ("on", "off", "toggle"):
                    return 400, {"error": "state must be on, off or toggle."}
                muted = strip.mute_button.isChecked()
                if wanted == "toggle" or (wanted == "on") != muted:
                    self.toggle_strip_mute(name)
                return 200, {"channel": name, "mute": strip.mute_button.isChecked()}

            mix = params.get("mix", "").casefold()
            if mix == "you" and not self.stream_mix_buses():
                mix = ""  # one mix only: the faders are "you"
            if mix and mix not in ("you", "stream"):
                return 400, {"error": "mix must be you or stream."}
            if mix and mix != self.mix:
                if mix == "stream" and not self.stream_mix_buses():
                    return 409, {"error": "Choose the output your stream hears in Settings first."}
                # Another mix than the faders show: set it directly.
                try:
                    if "db" in params:
                        decibels = float(params["db"])
                    elif "step" in params:
                        decibels = strip.mix_gain(mix) + float(params["step"])
                    else:
                        return 400, {"error": "Give db or step."}
                    if not math.isfinite(decibels):
                        raise ValueError
                except ValueError:
                    return 400, {"error": "db and step must be numbers."}
                strip.set_mix_gain(min(12.0, max(-60.0, decibels)), mix)
                return 200, {"channel": name, "mix": mix,
                             "gain": round(strip.mix_gain(mix), 2)}
            try:
                if "db" in params:
                    decibels = float(params["db"])
                    if not math.isfinite(decibels):
                        raise ValueError
                    strip.fader.setValue(int(round(decibels * 100)))
                elif "step" in params:
                    step = float(params["step"])
                    if not math.isfinite(step):
                        raise ValueError
                    self.step_strip_gain(name, step)
                else:
                    return 400, {"error": "Give db or step."}
            except ValueError:
                return 400, {"error": "db and step must be numbers."}
            return 200, {"channel": name, "gain": strip.fader.value() / 100}

        if parts in (["monitor"], ["stream-mute"]):
            wanted = params.get("state", "toggle").casefold()
            if wanted not in ("on", "off", "toggle"):
                return 400, {"error": "state must be on, off or toggle."}
            listening, stream_muted = self.mic_shortcut_state()
            if parts == ["monitor"]:
                if wanted == "toggle" or (wanted == "on") != listening:
                    self.toggle_mic_listen()
                return 200, {"monitor": self.mic_shortcut_state()[0]}
            if stream_muted is None:
                return 409, {"error": "Choose the output your stream hears in Settings first."}
            if wanted == "toggle" or (wanted == "on") != stream_muted:
                self.toggle_stream_mute()
            return 200, {"stream_mute": self.mic_shortcut_state()[1]}

        if parts and parts[0] == "profile" and len(parts) <= 2:
            if len(parts) == 2:
                if parts[1] not in self.load_profiles():
                    return 404, {"error": f"Unknown profile: {parts[1]}"}
                applied = self.apply_profile(parts[1])
                self.refresh_profile_list(select=parts[1])
            else:
                step = params.get("step", "").casefold()
                if step not in ("next", "previous"):
                    return 400, {"error": "Give a profile name, or step=next or previous."}
                if not self.load_profiles():
                    return 404, {"error": "There are no profiles."}
                self.cycle_profile(1 if step == "next" else -1)
                applied = True
            return 200, {"profile": self.active_profile, "applied": bool(applied)}

        return 404, {"error": "Unknown address."}

    def register_hotkeys(self):
        """(Re)register the global hotkeys.

        Returns the combinations Windows refused, usually because another
        program holds them; an empty list means all is well.
        """
        user32 = ctypes.windll.user32
        hwnd = int(self.winId())
        current = self.current_settings()
        refused = []
        self.refused_hotkeys = {}  # settings key -> (combination, label)
        for action in HOTKEYS:
            user32.UnregisterHotKey(hwnd, action.id)
            text = current[action.key]
            parsed = parse_hotkey(text)
            if parsed is None:
                if text:
                    log.warning(f"Ignoring invalid hotkey for {action.label}: {text}")
                continue
            modifiers, virtual_key = parsed
            if not action.repeats:
                # A held mute key must not toggle over and over.
                modifiers |= MOD_NOREPEAT
            if not user32.RegisterHotKey(hwnd, action.id, modifiers, virtual_key):
                log.warning(f"Could not register {text} for {action.label}")
                refused.append(text)
                self.refused_hotkeys[action.key] = (text, action.label)
        return refused

    def unregister_hotkeys(self):
        try:
            hwnd = int(self.winId())
            for action in HOTKEYS:
                ctypes.windll.user32.UnregisterHotKey(hwnd, action.id)
        except Exception:
            pass

    def on_hotkey(self, hotkey_id):
        for action in HOTKEYS:
            if action.id != hotkey_id:
                continue
            if action.action == "mute":
                self.toggle_strip_mute(action.argument)
            elif action.action == "gain":
                self.step_strip_gain(*action.argument)
            elif action.action == "profile":
                self.cycle_profile(action.argument)
            elif action.action == "push_to_talk":
                self.hold_mic_mute(action, muted=False)
            elif action.action == "hold_mute":
                self.hold_mic_mute(action, muted=True)
            elif action.action == "stream_mute":
                self.toggle_stream_mute()

    # The microphone: held keys, listening and the stream.

    def set_mic_mute(self, muted, chime=True):
        mic = self.strips.get("Mic")
        if mic is None or not self.connected:
            return
        if mic.mute_button.isChecked() != muted:
            mic.mute_button.setChecked(muted)
            mic.on_mute_clicked(muted, chime=chime)
        self.sync_tray()

    def hold_mic_mute(self, action, muted):
        """Mute or unmute while the hotkey is held; put it back on release.

        Windows only reports that a hotkey was pressed, so the key is
        watched until it is let go. No chime: it would sound every time.
        """
        if self._held_key is not None or not self.connected:
            return
        parsed = parse_hotkey(self.current_settings()[action.key])
        mic = self.strips.get("Mic")
        if parsed is None or mic is None:
            return
        self._held_key = (parsed[1], mic.mute_button.isChecked())
        self.set_mic_mute(muted, chime=False)
        self._held_key_timer.start()

    def check_held_key(self):
        if self._held_key is None:
            self._held_key_timer.stop()
            return
        virtual_key, before = self._held_key
        if self.key_is_down(virtual_key):
            return
        self._held_key_timer.stop()
        self._held_key = None
        self.set_mic_mute(before, chime=False)

    @staticmethod
    def key_is_down(virtual_key):
        return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def listen_bus_setting(self):
        bus = str(self.window_settings.value("listen_bus", "A1") or "")
        return bus if bus in HARDWARE_OUTPUTS else "A1"

    def stream_outputs_setting(self):
        """The outputs the stream hears, such as ["B2", "B3"]: comma-separated
        in the setting, which held one output before."""
        chosen = str(self.window_settings.value("stream_bus", "") or "").split(",")
        # Only virtual outputs reach stream software; an A chosen before
        # this rule is left out.
        return [output for output in VIRTUAL_OUTPUTS if output in chosen]

    def mic_shortcut_state(self):
        """(listening, muted for the stream); the second is None when the
        stream's output is not set."""
        mic = self.strips.get("Mic")
        if mic is None:
            return False, None
        listen = mic.route_buttons.get(self.listen_bus_setting())
        streams = [
            mic.route_buttons[output] for output in self.stream_outputs_setting()
            if output in mic.route_buttons
        ]
        return (
            bool(listen is not None and listen.isChecked()),
            None if not streams else not any(b.isChecked() for b in streams),
        )

    def set_mic_route(self, output, on):
        mic = self.strips.get("Mic")
        button = None if mic is None else mic.route_buttons.get(output)
        if button is None or not self.connected:
            return
        if button.isChecked() != on:
            button.setChecked(on)
            mic.on_route_clicked(output, on)
        self.sync_tray()

    def toggle_mic_listen(self):
        listening, _stream = self.mic_shortcut_state()
        self.set_mic_route(self.listen_bus_setting(), not listening)

    def toggle_stream_mute(self):
        _listening, stream_muted = self.mic_shortcut_state()
        if stream_muted is None:
            self.sync_tray()
            return
        # Muted for the stream means: routed to none of the stream's outputs.
        # Unmuting puts it back where it was (your voice on B2, not on the
        # game sound on B3).
        mic = self.strips["Mic"]
        outputs = self.stream_outputs_setting()
        if not stream_muted:
            self._stream_mute_outputs = [
                output for output in outputs if mic.route_buttons[output].isChecked()
            ]
            for output in self._stream_mute_outputs:
                self.set_mic_route(output, False)
        else:
            back = [
                output for output in getattr(self, "_stream_mute_outputs", [])
                if output in outputs
            ] or outputs[:1]
            for output in back:
                self.set_mic_route(output, True)

    def sync_mic_shortcuts(self):
        if not hasattr(self, "stream_mute_button"):
            return
        _listening, stream_muted = self.mic_shortcut_state()
        self.stream_mute_button.setChecked(bool(stream_muted))
        self.stream_mute_button.setEnabled(
            self.connected and stream_muted is not None
        )
        if stream_muted is None:
            self.stream_mute_button.setToolTip(
                "Mute your microphone for the stream only; voice chat still "
                "hears you. Choose the output your stream hears under "
                "Settings, Microphone to use this."
            )
        else:
            self.stream_mute_button.setToolTip(
                "Mute your microphone for the stream only; voice chat still "
                "hears you. (Takes it off "
                f"{' and '.join(output_label(o) for o in self.stream_outputs_setting())}.)"
            )

    def step_strip_gain(self, name, decibels):
        """Move a strip's fader, also while the window is hidden."""
        strip = self.strips.get(name)
        if strip is None or not self.connected:
            return
        # The fader clamps to its range and sends the change like a drag.
        strip.fader.setValue(
            strip.fader.value() + int(round(decibels * 100))
        )

    def cycle_profile(self, direction):
        """Load the next or previous setup profile, in the list's order."""
        names = sorted(self.load_profiles(), key=str.casefold)
        if not names or not self.connected:
            return
        if self.active_profile in names:
            index = (names.index(self.active_profile) + direction) % len(names)
        else:
            index = 0 if direction > 0 else len(names) - 1
        name = names[index]
        self.apply_profile(name)
        self.refresh_profile_list(select=name)
        # With the window hidden there is nothing to see otherwise.
        if self.tray is not None and not self.isVisible():
            self.tray.showMessage(
                "FaderDeck", f"Setup profile: {name}", self.tray.icon(), 2000
            )

    def toggle_strip_mute(self, name):
        """Mute or unmute a strip, also while the window is hidden."""
        strip = self.strips.get(name)
        if strip is None or not self.connected:
            return
        muted = not strip.mute_button.isChecked()
        strip.mute_button.setChecked(muted)
        strip.on_mute_clicked(muted)
        self.sync_tray()

    def toggle_mic_mute(self, *_args):
        self.toggle_strip_mute("Mic")

    def on_vm_event(self, event):

        """
        Handle VoiceMeeter events on Qt's main thread.
        """

        if event == "pdirty":
            for widget in self.strips.values():
                widget.sync_from_voicemeeter()

            # The processing controls are only read while their popup is
            # open; opening it synchronizes them (see toggle_processing).
            if (
                self.processing_dialog is not None
                and self.processing_dialog.isVisible()
            ):
                self.sync_processing_controls()
            self.update_processing_summary()
            self.sync_tray()
            # Checked a moment later: during a drag or a load VoiceMeeter
            # sends many events and reports in-between values.
            self._profile_check_timer.start()

    def sync_processing_controls(self):
        for control in (
            self.compressor_control,
            self.gate_control,
            self.denoiser_control,
        ):
            if control is not None:
                control.sync_from_voicemeeter()

    def closeEvent(self, event):

        """
        Shut down the VoiceMeeter event threads before
        logging out of the VoiceMeeter API.

        The event thread must no longer be making C API
        calls when the VoiceMeeter connection is closed.

        With "keep running in the tray" on, closing the window only hides
        it; Quit in the tray menu ends the program, and so does closing the
        window with Shift held.
        """
        if self.shift_is_held():
            self._quitting = True
        if self.close_to_tray_enabled() and not self._quitting:
            event.ignore()
            self.hide()
            if not setting_bool(self.window_settings, "tray_hint_shown", False):
                self.window_settings.setValue("tray_hint_shown", True)
                self.tray.showMessage(
                    "FaderDeck is still running",
                    "It stays in the system tray. Right-click the icon to "
                    "quit, or hold Shift while closing the window.",
                    self.tray.icon(),
                    5000,
                )
            return


        if self.application_control is not None:
            self.application_control.close()
        if self.mute_badge is not None:
            self.mute_badge.close()
            self.mute_badge.deleteLater()
            self.mute_badge = None

        if hasattr(self, "level_timer"):
            self.level_timer.stop()

        if hasattr(self, "connection_timer"):
            self.connection_timer.stop()
        self.unregister_hotkeys()
        self.local_api.stop()
        self.phone_remote.stop()

        if self.vm is not None and self.vm_observer is not None:
            try:
                self.vm.observer.remove(self.vm_observer)
            except Exception:
                pass
        self.release_vm()
        self.vm = None

        self.save_window_geometry()
        if not self.compact:
            self.window_settings.setValue(
                "splitter_v1", self.main_splitter.saveState()
            )
        self._save_processing_geometry()
        self.window_settings.sync()

        if self.tray is not None:
            self.tray.hide()
        event.accept()
        # The tray keeps the program alive without a window, so closing the
        # last window no longer ends it by itself.
        QApplication.instance().quit()


def resource_path(filename):
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, filename)

def install_exit_handlers(window):
    """Leave VoiceMeeter properly on the ways out that skip closeEvent."""

    def quit_from_signal(*_args):
        # Ctrl+C in the terminal: quit like the tray's Quit does.
        QTimer.singleShot(0, window.quit_application)

    for name in ("SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), quit_from_signal)

    # The terminal window being closed, signing out, shutting down. Windows
    # ends the process right after this returns, so log out here and now.
    handler_type = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.DWORD
    )

    def on_console_event(event):
        if event in (2, 5, 6):  # close, logoff, shutdown
            window.release_vm_at_exit()
        return False

    # Kept on the window: Windows calls it later, so it must stay alive.
    window._console_handler = handler_type(on_console_event)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(window._console_handler, True)


def main(arguments=()):
    setup_logging()
    if "--quit" in arguments:
        log.info("Asking the running FaderDeck to quit")
        ask_running_instance_to_quit()
        return
    # Kept until the program ends; Windows releases it then.
    single_instance = acquire_single_instance()
    if single_instance is None:
        log.info("FaderDeck is already running; showing that window")
        ask_running_instance_to_show()
        return
    log.info("FaderDeck starting")
    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(
        sys.argv

    )

    # Use the bundled FaderDeck icon for the application and all windows.
    # This works both from the source tree and from a PyInstaller build.
    icon_path = resource_path("faderdeck.ico")
    app_icon = QIcon(icon_path)

    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # Some Windows Qt styles expose an inherited font with pointSize() == -1
    # (pixel-sized/default font). Give the app a valid point-sized base font.
    base_font = QFont("Segoe UI")
    base_font.setPointSize(9)
    app.setFont(base_font)


    # With a tray icon the program lives on while its window is hidden.
    app.setQuitOnLastWindowClosed(False)

    apply_theme(theme_settings(app_settings()))
    window = MainWindow()

    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    if not window.start_minimized_enabled():
        window.show()
    install_exit_handlers(window)

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main(sys.argv[1:])
