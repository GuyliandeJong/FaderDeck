"""Stand-ins that let the tests build FaderDeck's widgets without VoiceMeeter,
Windows audio sessions or the registry.

Import this module before `main`: it selects Qt's offscreen platform and
creates the one QApplication the tests share.
"""

import logging
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep the application log out of the real %LOCALAPPDATA%.
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="faderdeck-tests-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

import main

app = QApplication.instance() or QApplication([])
# The application logs expected failures (a refused hotkey, a lost mixer);
# keep them out of the test output.
logging.getLogger("faderdeck").addHandler(logging.NullHandler())


def pump(seconds=0.05):
    """Let queued signals and timers run for a moment."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


class FakeSettings:
    """In-memory QSettings. Instances with the same name share one store,
    like the real one. `store` is the program's own; `old_store` is what an
    installation from before the rename left behind."""

    store = {}
    old_store = {}

    def __init__(self, organization=None, application=None):
        self._old = organization == main.OLD_SETTINGS_NAME

    @property
    def _data(self):
        return FakeSettings.old_store if self._old else FakeSettings.store

    def value(self, key, default=None):
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value

    def remove(self, key):
        self._data.pop(key, None)

    def allKeys(self):
        return list(self._data)

    def sync(self):
        pass


class FakeBlock:
    """A processing block (compressor, gate or denoiser).

    Like the real mixer, changing Amount (`knob`) replaces the advanced
    values with a preset.
    """

    def __init__(self, values, preset=None):
        self.__dict__["_preset"] = dict(preset or {})
        self.__dict__["_knob"] = values.pop("knob")
        self.__dict__.update(values)

    @property
    def knob(self):
        return self._knob

    @knob.setter
    def knob(self, value):
        self.__dict__["_knob"] = value
        self.__dict__["knob_writes"] = self.__dict__.get("knob_writes", 0) + 1
        self.__dict__.update(self._preset)


COMPRESSOR = dict(
    knob=3.1, gainin=0.0, ratio=3.0, threshold=-18.0, attack=15.0,
    release=150.0, knee=0.5, gainout=0.0, makeup=True,
)
COMPRESSOR_PRESET = dict(ratio=1.9, threshold=-40.0, attack=10.0, release=50.0)
GATE = dict(
    knob=2.0, threshold=-38.0, damping=-60.0, bpsidechain=500.0,
    attack=8.0, hold=120.0, release=300.0,
)
GATE_PRESET = dict(threshold=-50.0, attack=0.0, hold=500.0, release=1000.0)


class FakeLevels:
    def __init__(self, channels):
        self.prefader = tuple([-200.0] * channels)


class FakeDevice:
    name = ""
    sr = 48000


class FakeStrip:
    def __init__(self, index):
        self.gain = 0.0
        self.mute = False
        self.solo = False
        self.mono = False
        self.A1 = True
        self.A2 = False
        self.A3 = False
        self.B1 = index == 0
        self.B2 = False
        self.B3 = False
        self.label = ""
        self.device = FakeDevice()
        self.levels = FakeLevels(2 if index < 5 else 8)
        self.comp = FakeBlock(dict(COMPRESSOR), COMPRESSOR_PRESET)
        self.gate = FakeBlock(dict(GATE), GATE_PRESET)
        self.denoiser = FakeBlock(dict(knob=2.0))


class FakeBus:
    def __init__(self):
        self.label = ""


class FakeObserver:
    def __init__(self):
        self.observers = []

    def add(self, observer):
        self.observers.append(observer)

    def remove(self, observer):
        self.observers.remove(observer)


class FakeVM:
    """The parts of voicemeeterlib's API object that FaderDeck uses."""

    def __init__(self):
        self.strip = [FakeStrip(index) for index in range(8)]
        self.bus = [FakeBus() for _ in range(8)]
        self.observer = FakeObserver()
        self.sent = []
        self.logged_in = False
        self.thread_running = False
        self.logins = 0
        self.fail_login = False

    def login(self):
        if self.fail_login:
            raise RuntimeError("VoiceMeeter is not running")
        self.logged_in = True
        self.logins += 1

    def logout(self):
        self.logged_in = False

    def init_thread(self):
        self.thread_running = True

    def end_thread(self):
        self.thread_running = False

    def stopped(self):
        return not self.thread_running

    def sendtext(self, text):
        """Apply "Strip[0].Comp.Release=150.000000" like VoiceMeeter does."""
        self.sent.append(text)
        match = re.fullmatch(r"Strip\[(\d+)\]\.(\w+)\.(\w+)=([-\d.]+)", text)
        block = {"Comp": "comp", "Gate": "gate"}[match.group(2)]
        target = getattr(self.strip[int(match.group(1))], block)
        setattr(target, match.group(3).lower(), float(match.group(4)))


class Sandbox:
    """Swap main's outside world for the fakes, and put it back afterwards."""

    def __init__(self):
        self.vm = FakeVM()
        self.running = True
        self._saved = {}

    def __enter__(self):
        FakeSettings.store = {}
        FakeSettings.old_store = {}
        self._patch("QSettings", FakeSettings)
        self._patch("PYCAW_AVAILABLE", False)
        self._patch("voicemeeter_is_running", lambda: self.running)
        self._patch("MIC_STRIP", 0)
        self._saved_api = main.voicemeeterlib.api
        main.voicemeeterlib.api = lambda *args, **kwargs: self.vm
        self._saved_strips = dict(main.STRIPS)
        return self

    def _patch(self, name, value):
        self._saved[name] = getattr(main, name)
        setattr(main, name, value)

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(main, name, value)
        main.voicemeeterlib.api = self._saved_api
        main.STRIPS.clear()
        main.STRIPS.update(self._saved_strips)

    def window(self):
        """A MainWindow connected to the fake mixer, with its timers stopped
        so the test decides when things happen."""
        window = main.MainWindow()
        window.connection_timer.stop()
        return window

    @staticmethod
    def close(window):
        window._quitting = True
        window.close()
        pump()
