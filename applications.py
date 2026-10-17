"""Applications playing audio: the worker that finds them and moves them
between channels, and the panel that lists them."""

import math
import json
import os
import re
import time
import warnings
import threading

from PySide6.QtCore import (
    Qt,
    Signal,
    QObject,
    QTimer,
    QFileInfo,
    QThread,
    Slot,
    QMetaObject,
    QByteArray,
    QSize,
    QMimeData,
)
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core import (
    ALL_CHANNELS,
    APP_ROUTING_AVAILABLE,
    AudioUtilities,
    DEVICE_STATE,
    DRAG_MIME,
    EDataFlow,
    EYE_BUTTON_STYLE,
    OWN_EXECUTABLES,
    PYCAW_AVAILABLE,
    STRIP_COLORS,
    _STORE_FOLDER,
    _VERSION_FOLDER,
    app_settings,
    channel_label,
    log,
    war,
)
from themes import reference_eye_icon, set_mono_icon
from widgets import LiveVolumeSlider


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
