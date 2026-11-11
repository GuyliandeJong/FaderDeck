"""The channel strips (Mic, Game, Chat, Media) and the worker that reads
their levels."""

import math
import time

from PySide6.QtCore import Qt, Signal, QObject, QTimer, Slot
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core import (
    ALL_OUTPUTS,
    app_settings,
    available_outputs,
    CHANNEL_FADER_MIN_HEIGHT,
    CHANNEL_HEADER_HEIGHT,
    channel_label,
    COMPACT_CARD_MIN_HEIGHT,
    COMPACT_FADER_WIDTH,
    COMPACT_HEADER_HEIGHT,
    COMPACT_METER_WIDTH,
    FADER_TO_GAIN_GAP,
    HARDWARE_INPUTS,
    log,
    MIXER_BUTTON_HEIGHT,
    MIXER_CARD_MIN_HEIGHT,
    NORMAL_METER_WIDTH,
    outline_toggle_style,
    output_label,
    ROUTE_BUS,
    route_name,
    ROUTING_BUTTON_HEIGHT,
    ROUTING_LABEL_HEIGHT,
    setting_bool,
    SMALL_HEADING_STYLE,
    STRIP_COLORS,
    STRIPS,
    TOGGLE_COLORS,
)
from themes import set_mono_icon
from sound import play_mute_sound
from widgets import MicFaderArea, MixerFader, VUMeter
from PySide6.QtGui import QAction


# VoiceMeeter's three tone knobs on a virtual input (EQGain1-3).
EQ_BANDS = ("bass", "mid", "treble")
EQ_RANGE = 12.0  # dB either way


class ToneDialog(QDialog):
    """Bass, mid and treble for a virtual channel, sent as they move."""

    def __init__(self, strip_widget):
        super().__init__(strip_widget)
        self.strip_widget = strip_widget
        self.setWindowTitle(f"{strip_widget.name_label.text()}: bass, mid, treble")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        grid = QGridLayout(self)
        self.sliders = {}
        for row, band in enumerate(EQ_BANDS):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(int(-EQ_RANGE * 2), int(EQ_RANGE * 2))  # half dB steps
            slider.setMinimumWidth(220)
            value = QLabel()
            value.setMinimumWidth(56)
            slider.valueChanged.connect(
                lambda steps, band=band, value=value: self.on_moved(band, steps, value)
            )
            grid.addWidget(QLabel(band.capitalize()), row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value, row, 2)
            self.sliders[band] = slider
            slider.setValue(int(round(strip_widget.eq_value(band) * 2)))
            self.on_moved(band, slider.value(), value, write=False)
        flat = QPushButton("Flat")
        flat.setToolTip("Set all three to 0 dB")
        flat.clicked.connect(lambda: [s.setValue(0) for s in self.sliders.values()])
        grid.addWidget(flat, len(EQ_BANDS), 2)

    def on_moved(self, band, steps, label, write=True):
        db = steps / 2
        label.setText(f"{db:+.1f} dB")
        if write:
            self.strip_widget.set_eq(band, db)


DUCK_THRESHOLD_DB = -40.0  # the mic above this counts as talking
DUCK_HOLD = 0.6  # seconds of silence before the sound comes back
DUCK_RELEASE_DB = 3.0  # dB back per step (a step is 100 ms)


def next_duck(current, talking, amount):
    """The duck after one step: down at once while talking, back up a
    step at a time after. current and amount are negative dB or 0."""
    if talking:
        return float(amount)
    return min(0.0, current + DUCK_RELEASE_DB)


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
        if self.has_eq():
            # Right-click on the header.
            tone = QAction("Bass, mid and treble…", strip_header)
            tone.triggered.connect(self.open_tone)
            strip_header.addAction(tone)
            strip_header.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
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
        # Fader units are 0.01 dB. The arrow keys move 0.01 dB for fine
        # tuning, one wheel notch 0.1 dB; Shift+wheel and Page Up/Down 1 dB.
        self.fader.setSingleStep(1)
        self.fader.setPageStep(100)
        self.fader.wheel_step = 10
        self.fader.shift_step = 100
        self.fader.setToolTip(
            "Mouse wheel: 0.1 dB, with Shift 1 dB. "
            "Arrow keys: 0.01 dB. Page Up/Down: 1 dB. "
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
    # dB taken off every output while ducking; the faders and profiles
    # never see it.
    duck = 0.0

    def layered(self):
        return bool(self.stream_buses) or bool(self.offsets) or bool(self.duck)

    def set_duck(self, db):
        """Lower every output by -db dB (0: not ducked), faders unmoved."""
        gains = {"you": self.mix_gain("you")}
        if self.stream_buses:
            gains["stream"] = self.mix_gain("stream")
        self.duck = float(db)
        for mix, gain in gains.items():
            self.set_mix_gain(gain, mix)

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
            return self.strip.gainlayer[(routed or self.stream_buses)[0]].gain - self.duck
        # Any output that is neither the stream's nor offset carries YOU.
        own = next(
            bus for bus in range(len(self.strip.gainlayer))
            if bus not in self.stream_buses and bus not in self.offsets
        )
        return self.strip.gainlayer[own].gain - self.duck

    def set_mix_gain(self, gain, mix=None):
        mix = mix or self.mix
        if not self.layered():
            self.strip.gain = gain
        elif mix == "stream" and self.stream_buses:
            for bus in self.stream_buses:
                self.strip.gainlayer[bus].gain = min(12.0, max(-60.0, gain + self.duck))
        else:
            for bus, layer in enumerate(self.strip.gainlayer):
                if bus not in self.stream_buses:
                    level = gain + self.offsets.get(bus, 0.0) + self.duck
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
        if self.has_eq():
            state["eq"] = {band: self.eq_value(band) for band in EQ_BANDS}
        return state

    def has_eq(self):
        return self.strip_index >= HARDWARE_INPUTS  # a virtual input

    def eq_value(self, band):
        try:
            return round(float(getattr(self.strip, band)), 1)
        except Exception:
            return 0.0

    def set_eq(self, band, db):
        db = min(EQ_RANGE, max(-EQ_RANGE, float(db)))
        try:
            setattr(self.strip, band, db)
        except Exception as e:
            log.error(f"Failed to set {self.name} {band}: {type(e).__name__}: {e}")

    def open_tone(self):
        ToneDialog(self).exec()

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
            # Profiles from before v1.16 have no "eq": the tone stays as it is.
            for band, db in dict(state.get("eq") or {}).items():
                if band in EQ_BANDS and math.isfinite(float(db)) and self.has_eq():
                    if self.eq_value(band) != round(float(db), 1):
                        self.set_eq(band, db)
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


CLIP_DB = -1.0  # a stream output at or above this is about to distort


class StripLevelWorker(QObject):
    """Read the level of every strip on a dedicated worker thread.

    This worker is the only place levels are read; the GUI thread never
    queries VoiceMeeter for them.
    """

    levels_received = Signal(str, float, float)  # strip name, left, right
    clipped = Signal(str)  # a stream output, at most twice a second
    error = Signal(str)
    finished = Signal()

    def __init__(self, vm):
        super().__init__()
        self.vm = vm
        self.timer = None
        self._last_levels = {}
        # (output, bus index) pairs to watch; set from the GUI thread, which
        # only ever replaces the whole tuple.
        self.clip_buses = ()
        self._last_clip = {}

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
            now = time.monotonic()
            for output, index in self.clip_buses:
                levels = self.vm.bus[index].levels.all
                if max(levels, default=-200.0) >= CLIP_DB:
                    if now - self._last_clip.get(output, 0.0) >= 0.5:
                        self._last_clip[output] = now
                        self.clipped.emit(output)
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
