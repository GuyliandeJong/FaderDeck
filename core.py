"""Shared basics: logging, settings, VoiceMeeter detection, channels and
outputs, hotkeys, the single running instance and common styles."""

import sys
import ctypes
import ctypes.wintypes
import logging
import os
import re
import threading
from collections import namedtuple
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import (
    Signal,
    QObject,
    QSettings,
    QAbstractNativeEventFilter,
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


def resource_path(filename):
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, filename)
