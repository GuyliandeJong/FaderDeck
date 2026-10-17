"""Icons, the logo, and the themes: built-in colour sets, light mode and
the translation of the dark colours to the chosen theme."""

import json
import re

from PySide6.QtCore import Qt, Signal, QByteArray
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QLabel,
    QPushButton,
    QWidget,
)

from core import STRIP_COLORS


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
    "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"
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
