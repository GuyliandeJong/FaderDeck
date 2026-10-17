import sys
import math
import atexit
import ctypes
import ctypes.wintypes
import hashlib
import json
import re
import signal
import subprocess
import time
import threading

from PySide6.QtCore import (
    QPoint,
    QUrl,
    Qt,
    QTimer,
    QThread,
    QMetaObject,
    QSize,
    qInstallMessageHandler,
)
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QDialog,
    QMenu,
    QSystemTrayIcon,
    QPushButton,
    QProgressDialog,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import (
    ALERT_BORDER,
    ALL_OUTPUTS,
    APPLICATION_PANEL_HEIGHT,
    APPLICATION_PANEL_MIN_HEIGHT,
    CHANNEL_NAME_KEYS,
    COMPACT_DEFAULT_SIZE,
    COMPACT_MIN_SIZE,
    COMPRESSOR_MARK,
    DEFAULT_MIXER_PANE_HEIGHT,
    HARDWARE_INPUTS,
    HARDWARE_OUTPUTS,
    HEADER_BUTTON_STYLE,
    HOTKEYS,
    HotkeyFilter,
    MIXER_CARD_MIN_HEIGHT,
    MOD_NOREPEAT,
    PANEL_BORDER,
    PROFILE_HOLDS,
    PROFILE_PROCESSING,
    ROUTE_BUS,
    SMALL_HEADING_STYLE,
    STRIPS,
    VIRTUAL_OUTPUTS,
    VMEventBridge,
    VMObserver,
    VOICEMEETER_DOWNLOAD_URL,
    WINDOW_DEFAULT_SIZE,
    WINDOW_MIN_SIZE,
    _qt_message_handler,
    acquire_single_instance,
    app_settings,
    ask_running_instance_to_quit,
    ask_running_instance_to_show,
    available_outputs,
    channel_label,
    load_voicemeeterlib,
    log,
    output_label,
    output_name,
    parse_hotkey,
    profile_states_match,
    resource_path,
    set_mic_strip,
    setting_bool,
    setup_logging,
    voicemeeter_install_state,
    voicemeeter_is_running,
)
from themes import (
    LOGO_SVG,
    _svg_icon,
    apply_theme,
    saved_themes,
    set_mono_icon,
    store_dict,
    stored_dict,
    theme_settings,
)
from updates import (
    APP_VERSION,
    INSTALLER_OPTIONS,
    UpdateChecker,
    installer_environment,
)
from web import (
    API_DEFAULT_PORT,
    LocalApi,
    PhoneRemote,
    REMOTE_DEFAULT_PORT,
    REMOTE_PAGE,
    logo_png,
    remote_manifest,
)
from widgets import (
    GripSplitter,
    MUTE_INDICATORS,
    MicLevelBar,
    MuteBadge,
    Wordmark,
    badged_icon,
    mute_indicator_state,
)
from processing import CompressorControl, DenoiserControl, GateControl
from strips import StripLevelWorker, StripWidget
from applications import ApplicationControl
from dialogs import (
    STREAM_SETUP_HEAR,
    STREAM_SETUP_NAMES,
    SettingsDialog,
    StreamSetupDialog,
    VoicemeeterMissingDialog,
    WELCOME,
    WelcomeDialog,
)


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
                self.vm = load_voicemeeterlib().api(
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
