# FaderDeck — Project Handover

## Project

FaderDeck is a Windows desktop controller for VoiceMeeter Potato. It provides a compact custom UI for Mic, Game, Chat and Media instead of cloning the entire VoiceMeeter interface.

Repository: https://github.com/GuylianDeJong/FaderDeck
Current branch: `main`
Current release: `v1.0.2` (published/latest)

## Environment

- Windows
- Python 3.14.6
- Project: `C:\Users\Dutchie_\Documents\Projects\FaderDeck`
- Virtual environment: `.venv`
- PySide6 6.11.2
- voicemeeter-api 2.7.2
- pycaw
- comtypes
- psutil
- winappaudiorouter
- PyInstaller

Dependencies are listed in `requirements.txt`.
- VoiceMeeter Potato 3.1.2.2
- VS Code / PowerShell

## Development Rules

- The primary source file is always `main.py`.
- Do not create renamed variants such as `main_final.py`, `main_popup.py`, etc.
- Prefer complete files when providing code changes.
- Make incremental changes and test each logical change.
- Do not casually rewrite the working audio/threading architecture.

## VoiceMeeter Mapping

```python
STRIPS = {
    "Mic": 0,
    "Game": 5,
    "Chat": 6,
    "Media": 7,
}
```

- Strip 0 = Mic / Hardware Input 1
- Strip 5 = Game / VAIO
- Strip 6 = Chat / VAIO AUX
- Strip 7 = Media / VAIO3
- Mic hardware: Focusrite Scarlett 4i4 4th Gen + Beyerdynamic M 70 PRO X
- Hardware Inputs 2–5 and the output buses themselves are intentionally not exposed.
- Routing buttons: Mic has B1; Game, Chat and Media have A1–A3.

## Main Controls

All four strips expose:

- Gain
- Mute
- Solo
- Mono

Mic additionally exposes:

- Compressor
- Gate
- Denoiser

Microphone processing is shown in a separate popup so opening it does not resize the main window.

## VoiceMeeter API

Connection uses:

```python
voicemeeterlib.api(
    "potato",
    ratelimit=0.05,
    ldirty=True,
    pdirty=True,
)
```

Important findings:

- `vm.login()` does not start the update thread by itself.
- `vm.init_thread()` is required.
- Observer callback signature is `on_update(self, event)`.
- `pdirty=True` enables parameter dirty-state checking.
- VoiceMeeter update/event threads must be stopped before `logout()`.

Shutdown has been tested and is stable.

## Microphone Processing API

Compressor properties:

`knob`, `gainin`, `ratio`, `threshold`, `attack`, `release`, `knee`, `gainout`, `makeup`

Gate properties:

`knob`, `threshold`, `damping`, `bpsidechain`, `attack`, `hold`, `release`

Denoiser:

`knob`

Compressor Attack/Release previously caused native API access violations. A safer native setter implementation (`vm.sendtext`) fixed this, and the gate's Attack/Hold/Release use it too. Do not casually replace it.

Compressor, Gate and Denoiser share one implementation, `ProcessingPanel`. Each block is a small subclass that lists its parameters in `PARAMETERS` and names its `sendtext` parameters in `SCRIPT_KEYS`. Display and typed-value handling live in `format_parameter()` and `parse_parameter()`.

The processing controls are only synchronized while the popup is open, and once when it opens.

Amount (`knob`) is a preset dial in VoiceMeeter: changing it rewrites the advanced values of that block. Bypass therefore stores the whole state of a block (QSettings `bypass_state_<block>`, so it survives a restart) and restores Amount first, then the advanced values. Reset restores the state the window was opened with through the same path (`_read_state` / `_restore_state`). Do not reduce this to remembering Amount only.

The Mic Processing window shows a Mic input bar (`MicLevelBar`) with the gate and compressor thresholds marked. Its sliders (`PanelSlider`) ignore the mouse wheel until clicked; Attack, Hold and Release use a logarithmic track. The window opens beside the main window and remembers its place (`processing_geometry_v1`).

## Settings, Hotkey and Tray

`SettingsDialog` (button in the header) edits the program settings, stored in QSettings and read through `MainWindow.current_settings()`:

- `mic_strip`: hardware input 0-4 of the microphone. Applied by `set_mic_strip()` before the window is built. Changing it in Settings calls `MainWindow.set_mic_input()`, which points the Mic strip and the three processing panels at the new strip and clears a bypass (it holds values of the old input); the level worker reads `STRIPS["Mic"]` on every pass, so it follows by itself.
- `mute_sound_device`: the waveOut name of the device the mute sound plays on; empty is the Windows default. waveOut names are cut to 31 characters, so that is what is stored. An unknown name (device unplugged) plays on the default.
- `hotkey_mic_mute`: global hotkey, `Ctrl+Shift+M` by default, empty to switch off. Registered with Win32 `RegisterHotKey` on the main window and received through `HotkeyFilter`, a native event filter. `parse_hotkey()` accepts a modifier plus a letter, digit or F1-F24. A registered combination is taken from all other programs while FaderDeck runs.
- `close_to_tray` (default on) and `start_minimized` (default off).

The tray icon (`create_tray`) offers Show, Mute microphone and Quit. With close-to-tray on, `closeEvent` only hides the window unless `_quitting` is set, which Quit, Windows' session end (`commitDataRequest`) and closing with Shift held (`shift_is_held`) do. All three are a normal quit that logs out of VoiceMeeter. `main()` switches off quit-on-last-window-closed, so the real `closeEvent` ends with `QApplication.quit()`. Do not remove the session-end hook: without it FaderDeck would hold up a Windows shutdown.

## Presets and Single Instance

A Mic processing preset stores the state of all three blocks together (`save_preset`, `apply_preset`, `delete_preset` on `MainWindow`; QSettings key `processing_presets`, JSON). Blocks hand out and take in a state through `preset_state()` and `apply_preset()`, which reuse the bypass/reset path: Amount first, then the advanced values. A preset saved while a block is bypassed stores the real values, not Amount 0. Stored values are clamped to the slider ranges when applied.

Only one FaderDeck runs at a time. `main()` claims a named mutex (`acquire_single_instance`); a second start broadcasts a registered window message and exits, and the running instance shows its window (handled in `HotkeyFilter`, for the main window's copy of the message only). The packaged program and a run from source use different names on purpose.

## Mixer Profiles, Routing and Hotkeys

A mixer profile stores gain, mute, solo, mono and the routing buttons of all four strips (`save_profile`, `apply_profile`, `delete_profile`; QSettings key `mixer_profiles`, JSON). `StripWidget.apply_profile()` sends each value through the same handler as a click, so only what differs reaches VoiceMeeter. A profile also holds the three mic processing blocks under the key `processing` (`PROFILE_PROCESSING`), because users expect a profile to be the whole setup; profiles saved by v1.3.0 lack it and leave the processing alone. The presets in the Mic Processing window hold the processing only.

Every strip has the routing rows A1–A3 and B1–B3 (`ROUTE_ROWS`). A button shows the bus name from VoiceMeeter when the bus has one (`route_name`).

Each strip has a mute hotkey (`MUTE_HOTKEYS`); only the microphone's has a default. `register_hotkeys()` returns the combinations Windows refused.

The fader's unit is 0.01 dB. One wheel notch moves 0.5 dB, Shift+wheel and the arrow keys 0.1 dB, Page Up/Down 1 dB.

`update_processing_summary()` shows each block's Amount under the MIC PROCESSING button and marks a bypassed or switched-off block on its tab. It reads three values per change event; the full panels are still only synchronized while their window is open.

`FaderDeck.exe --quit` (and `python main.py --quit`) asks the running instance to quit through a registered window message, handled like the tray's Quit.

## Profile State

On screen the two lists are called SETUP PROFILE (main window, everything) and VOICE PRESET (Mic Processing window, processing only). They are stored separately and may share a name; users mixed them up, hence the names and the state line.

`MainWindow.active_profile` is the profile the mixer was last loaded from or saved to (QSettings `active_profile`, restored at start). `profile_is_changed()` compares the stored profile with `current_profile_state()` through `profile_states_match()`, which only looks at what the stored profile holds and compares numbers to two decimals. The check runs 0.9 s after a change event (`_profile_check_timer`), so it does not read the mixer during a drag or see VoiceMeeter's in-between values. When they differ the panel shows "<name>: changed" and UPDATE, which saves the current state into that profile. A bypassed block is compared by its kept values, so bypass is not a change.

## Amount Notice and Reference Ticks

Moving Amount by hand shows a notice under it with UNDO (`_before_amount_change`, `undo_amount`): VoiceMeeter replaces the advanced values when Amount moves and that cannot be switched off. The state from before the first move is kept until UNDO, a change to an advanced value, or any restore.

The tick under each slider marks what RESET returns to (`set_reference`). That is the state the window opened with, until a preset or profile is loaded or saved; from then on that one is the reference. Users read the ticks as "where the values belong", so they must follow a load.

## Hotkey Table, Compact View and Local API

`HOTKEYS` lists every global hotkey as a `HotkeyAction` (id, settings key, group, label, default, repeats, action, argument). The settings window, `register_hotkeys()` and `on_hotkey()` all read it, so a new hotkey is one more entry. Volume hotkeys repeat while held; mute and profile hotkeys are registered with `MOD_NOREPEAT`.

Compact view (`MainWindow.set_compact`, `StripWidget.set_compact`) hides SOLO, MONO, routing and the lower pane; it does not remove them, so profiles, hotkeys and VoiceMeeter's own changes still reach the hidden buttons. Each view keeps its own geometry (`geometry_v2`, `geometry_compact`).

The local API (`LocalApi`, `ApiServer`, `MainWindow.handle_api_call`) is off by default (`api_enabled`). Keep these properties when changing it:

- It binds `127.0.0.1` only and refuses to share its port (`SO_EXCLUSIVEADDRUSE`). Without that, Windows lets a second program listen on the same port and receive the token.
- Every request needs the token, compared with `hmac.compare_digest`.
- A request with an `Origin` header, or a `Host` other than `127.0.0.1` or `localhost`, is refused, so a web page cannot reach the mixer.
- Reads are GET and changes are POST; a GET never changes anything.
- Requests arrive on server threads and are handed to the GUI thread through `call_requested`; the server thread waits for the answer with a timeout. Nothing in `LocalApi` touches a widget or VoiceMeeter.

## Name

The program was called VMStreamer up to v1.4.0 and FaderDeck from v1.5.0. VB-Audio ships its own "VM-Streamer View", and the old name was too close to it. What still carries the old name, on purpose:

- `OLD_SETTINGS_NAME`: `migrate_settings()` copies the QSettings saved under "VMStreamer" to "FaderDeck" the first time the new name has none. The old settings are not deleted.
- `OWN_EXECUTABLES`: both `faderdeck.exe` and `vmstreamer.exe` are left out of the application lists.
- `LEGACY_API_TOKEN_HEADER`: the local API still accepts `X-VMStreamer-Token`.
- The project folder on disk and the earlier releases and tags.

The single-instance name changed with the rename, so an old VMStreamer and FaderDeck can run side by side and will then fight over the hotkeys. Quit the old one first.

## Themes (v1.6.0)

Every colour in `main.py` is written for the dark theme. A theme is a translation of those colours, applied where they reach Qt: `QWidget.setStyleSheet` (patched once at import), the module's own `QColor` subclass for `QColor("#rrggbb")`, and `translate_colors()` for the drawn icons. The default theme translates nothing.

- Live switching: each widget keeps the style sheet it was given in the `themeSource` property; `apply_theme()` translates every one again. Icons shown with `set_mono_icon()` are redrawn the same way. A colour turned into a `QColor` once at build time and kept would not follow a switch: create it where it is painted.
- A channel colour replaces that channel's three `STRIP_COLORS` values, so those values may appear nowhere else. A test checks this. `PANEL_BORDER`, `ALERT_BORDER` and `COMPRESSOR_MARK` exist for that reason: they look the same but are one step off.
- Settings: `theme` holds the active theme as JSON and `themes` the user's saved ones. `clean_theme()` drops anything malformed.
- Channel names (`channel_name_game` and so on) change only what is shown. The built-in names stay the keys for settings, profiles, hotkeys and the local API.

## Logo

The mark is drawn once, as `LOGO_SVG` in `main.py`: three white faders on a blue-to-purple tile. The header shows it next to the name, which `Wordmark` paints: "Fader" in white and "Deck" in the tile's gradient (`LOGO_GRADIENT`). `faderdeck.ico` is generated from the same drawing by `tools/make_icon.py`; run it after changing the drawing, and commit the icon.

## Tests

`tests/` holds unit tests on the standard library's `unittest`; run them with `python -m unittest discover -s tests` before committing a change to `main.py`. `tests/fakes.py` provides a fake mixer (`FakeVM`), an in-memory `QSettings` and a `Sandbox` that swaps them into `main`, so a real `MainWindow` can be built on Qt's offscreen platform without VoiceMeeter.

The fake mixer copies one behaviour of the real one on purpose: changing Amount replaces the advanced values. The bypass bug was invisible to a fake that did not do this.

Not covered, and still to be checked by hand: real audio, meters moving, drag and drop, the actual key press of the hotkey, the real tray icon, and VoiceMeeter really being closed.

## Connection

`check_connection()` runs every two seconds and looks for VoiceMeeter's main window with one Win32 call (`voicemeeter_is_running()`), which is cheap enough for the GUI thread. When VoiceMeeter goes away, `release_vm()` stops the level worker and event threads and logs out; when it returns, the same API object logs in again and the existing widgets are reused. Reconnecting only happens while VoiceMeeter is running, because `login()` would otherwise start it.

## Audio Meter Architecture

### Mic

Level sampling for all four strips runs in one dedicated worker (`StripLevelWorker`) and communicates with Qt through signals. Every strip has L/R meters. With `ldirty=True` voicemeeterlib serves levels from a cache that refreshes every `ratelimit` (50 ms), so the worker only emits when the value changed. `ldirty` events are not forwarded to the GUI thread.

### Applications

Windows application audio sessions are sampled in a dedicated Python loop rather than a GUI-thread QTimer.

Target sampling interval is approximately 10 ms; GUI delivery is approximately 60 FPS. Between two deliveries the highest sampled peak is kept. `update_peaks()` runs on the peak thread only.

This replaced an earlier architecture that produced 400–560 ms sampling stalls and GUI hangs. The dedicated loop fixed the problem.

Do not replace this with GUI-thread pycaw polling without testing.

## VU Meter

A double dB-to-fraction conversion was previously causing incorrect readings.

Correct pipeline:

```text
VoiceMeeter dB
→ target dB
→ display dB
→ QProgressBar dB
→ paint conversion
```

Range is `-60 .. 0 dB`.

Do not reintroduce the double conversion.

## Application Detection

Applications are detected through Windows audio sessions and grouped by actual VoiceMeeter routing/device.

Groups:

- Game / VAIO
- Chat / VAIO AUX
- Media / VAIO3

Multiple Windows sessions may belong to the same application. Do not collapse sessions solely by executable name.

Grouped application controls apply volume/mute to the underlying sessions. The group meter uses the highest active peak.

Friendly names include:

- `ms-teams.exe` → Microsoft Teams
- `msedgewebview2.exe` → Microsoft Edge WebView2
- `steam.exe` → Steam
- `steamwebhelper.exe` → Steam Client Web
- `signalrgbcore.exe` → SignalRGB Core
- `brave.exe` → Brave Browser

## Application UI

Three application columns remain separated by virtual channel:

```text
Game | Chat | Media
```

Rows provide:

- application name
- volume
- percentage
- mute/speaker control
- live green meter

Volume bars support click/drag and scroll-wheel fine adjustment.

Rows are not rebuilt while a row is being dragged or a volume slider is held. Application icons are cached per executable.

## Moving Applications

Dragging a row onto another column sets the per-app output device in Windows through `winappaudiorouter`. Windows re-binds the audio when the app next starts playback, so the row is marked as moving and the session list is scanned every second for a while.

## Application Hiding

Implemented:

- Hiding is per virtual channel, or on all channels at once
- Right-click → Hide on <channel> / Hide on all channels (and the matching Unhide entries)
- Eye button per column, plus one for all channels, toggles hidden applications
- Hidden state persists via QSettings key `hidden_applications_v2`
- The hide key is the executable path with version folders replaced by `*` (`stable_hide_key()`), so an application stays hidden after it updates; older stored entries are rewritten once on load
- Hidden applications are excluded from normal visible counts
- Hidden applications can be shown dimmed

## Main UI

Main mixer cards:

```text
Mic | Game | Chat | Media
```

The UI is a compact dark design with monochrome Mic/Game/Chat/Media icons and the custom eye icon.

Window position and size are persisted. A draggable splitter separates the mixer from the Applications / Mic Processing panels; its position is persisted under `splitter_v1`.

## Logging

Errors go through the `faderdeck` logger, not `print()`: the packaged build is windowed and has no console. `setup_logging()` writes a rotating log to `%LOCALAPPDATA%\FaderDeck\faderdeck.log` and installs hooks so uncaught exceptions are logged too.

## Icon / Packaging

Icon:

`faderdeck.ico`

`main.py` uses a resource helper for source and PyInstaller execution:

```python
def resource_path(filename):
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)
```

The icon is assigned to the QApplication and MainWindow.

Build script:

`build_faderdeck.ps1`

Launcher:

`faderdeck_launcher.py`

PyInstaller must retain both:

```powershell
--icon $icon
--add-data "$icon;."
```

The first sets the Windows EXE icon; the second embeds the ICO so `main.py` can load it from `_MEIPASS`.

Do not add `--collect-all PySide6`: it bundles every Qt module and makes the EXE about 245 MB. PyInstaller's own PySide6 hooks collect what `main.py` imports.

Output:

`dist\FaderDeck.exe`

`dist\` is intentionally ignored by Git.

## Build Notes

`build_faderdeck.ps1` asks a running FaderDeck to quit before it builds (`dist\FaderDeck.exe --quit`), because a running copy locks the EXE and PyInstaller then fails with `PermissionError: [WinError 5]`. If it is still running after ten seconds, quit it from its tray icon and build again.

Do not stop FaderDeck by force (`Stop-Process -Force`, `taskkill /F`, Task Manager). A killed process cannot log out, and VoiceMeeter keeps listing it as a client (an "R" mark at the top of its window) until VoiceMeeter is restarted. `--quit` only works for versions that have it (v1.3.0 and later); older ones must be quit from the tray.

Run the build script plainly. Redirecting its output makes PowerShell 5.1 treat PyInstaller's progress messages as an error.

## Installer and Updates (v1.7.0)

- `installer\faderdeck.iss` (Inno Setup 6) installs per user under `%LOCALAPPDATA%\Programs\FaderDeck`; no administrator rights, so the automatic update can run it silently. `build_faderdeck.ps1` compiles it when ISCC.exe is found, with `/DAppVersion=` taken from `APP_VERSION`.
- The installer finds a running FaderDeck by the `FaderDeck.SingleInstance` mutex and asks it to quit with `--quit`. `CloseApplications=no` on purpose: the Restart Manager would close it without logging out of VoiceMeeter.
- Updates: `UpdateChecker` asks `api.github.com/repos/GuyliandeJong/FaderDeck/releases/latest` on a background thread. Only a newer, non-pre-release with a `FaderDeck-Setup.exe` asset from github.com and a `sha256:` digest is offered. The download is checked against that digest, started with `/SILENT /SUPPRESSMSGBOXES /NORESTART`, and FaderDeck quits; `[Run]` starts it again.
- Bump `APP_VERSION` for every release, and attach both `FaderDeck.exe` and `FaderDeck-Setup.exe`. A release without the installer is never offered as an update.
- Only the packaged program checks by itself; a run from source checks only through Settings, CHECK NOW.

## GitHub Release

v1.0.2 is the latest tag.

Release assets:

- `FaderDeck.exe`
- Source code zip
- Source code tar.gz

The EXE is a GitHub Release asset, not a Git-tracked file.

## Known Development Files

Local development has included:

```text
diagnose_audio.py
main_meter_diagnostic.py
test_vm.py
install_faderdeck_startup.ps1
faderdeck_launcher.py
build_faderdeck.ps1
```

Do not blindly `git add .`; only commit files that belong in the repository.

## Known Historical Bugs

- Naive VoiceMeeter polling caused slider values to reset; event-based synchronization fixed it.
- `levels.postfader` can return tuples; scalar handling must account for this.
- A Qt font warning (`QFont::setPointSize: Point size <= 0`) was addressed by explicitly setting a valid Segoe UI 9pt application font.
- Worker/timer shutdown previously produced cross-thread Qt timer errors; safe thread cleanup fixed this.
- Application QTimer sampling caused large stalls; the dedicated Python sampling loop fixed it.

## Future UI Direction

The draggable divider between the mixer and the lower panels is implemented (see Main UI). The applications section should remain three columns:

`Game | Chat | Media`

## Future Features

Potential roadmap:

- mixer and microphone presets
- profiles
- executable-based routing rules
- pan/balance and additional VoiceMeeter controls
- global hotkeys
- system tray
- start with Windows/minimized
- OBS / Stream Deck integration
- local API / Home Assistant integration
- Android app to remote-control FaderDeck from a tablet or phone
- themes and DPI improvements
- Windows installer
- automatic updates
- release automation

## Recommended Next Session

1. Run the current `main.py`.
2. Verify VoiceMeeter connection.
3. Verify Mic and application meters.
4. Verify mixer controls.
5. Verify Mic Processing popup.
6. Verify application hiding/persistence.
7. Verify window persistence.
8. Only then begin the next feature.

Keep the current audio/threading architecture intact unless there is a demonstrated reason to change it.
