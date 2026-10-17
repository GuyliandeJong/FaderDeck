"""Dialogs: settings, the streaming setup, the welcome and the window
for a missing VoiceMeeter."""

import secrets
import subprocess

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QKeySequenceEdit,
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import (
    ALL_OUTPUTS,
    BackgroundJob,
    CHANNEL_NAME_KEYS,
    CHANNEL_NAME_MAX,
    HARDWARE_INPUTS,
    HARDWARE_OUTPUTS,
    HOTKEYS,
    OUTPUT_NAME_MAX,
    STRIP_COLORS,
    TOGGLE_COLORS,
    VIRTUAL_OUTPUTS,
    VOICEMEETER_DOWNLOAD_URL,
    available_outputs,
    channel_label,
    log,
    outline_toggle_style,
    output_device,
    parse_hotkey,
    route_name,
)
from themes import (
    BUILTIN_THEMES,
    CUSTOM_THEME,
    ColorButton,
    LOGO_SVG,
    _svg_icon,
    apply_theme,
    clean_theme,
)
from updates import APP_VERSION
from sound import (
    SOUND_CHECK_SECONDS,
    play_mute_sound,
    recording_devices,
    sound_check,
    sound_check_device,
    sound_devices,
)
from web import (
    REMOTE_PAIR_SECONDS,
    firewall_allows,
    firewall_program,
    firewall_rule_command,
    lan_address,
    run_powershell_as_admin,
)


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

        self._build_microphone_tab(current, vm)
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

    def _build_microphone_tab(self, current, vm):
        """Input, monitor, stream, sound check, chime and mute indicator."""
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

    def _build_general_tab(self, current, vm):
        """Channel names, output names, window and updates."""
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
