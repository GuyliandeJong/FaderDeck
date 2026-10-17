"""Mic processing: the compressor, gate and denoiser panel."""

import math
import json
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import (
    SMALL_HEADING_STYLE,
    STRIPS,
    TOGGLE_COLORS,
    app_settings,
    log,
    outline_toggle_style,
)
from widgets import NumericEdit, PanelSlider


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
