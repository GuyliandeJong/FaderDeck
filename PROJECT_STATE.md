# FaderDeck — Project State

State date: 2026-10-12
Current release: `v1.0.2`
Branch: `main`
Repository: https://github.com/GuylianDeJong/FaderDeck

## Primary Source

`main.py` is the authoritative application source filename. Do not create renamed `main_*` variants.

## Environment

- Windows
- Python 3.14.6
- PySide6 6.11.2
- voicemeeter-api 2.7.2
- pycaw
- comtypes
- winappaudiorouter
- PyInstaller

Dependencies are listed in `requirements.txt`.
- VoiceMeeter Potato 3.1.2.2

Project:

`C:\Users\Dutchie_\Documents\Projects\FaderDeck`

## VoiceMeeter

```text
Strip 0 → Mic
Strip 5 → Game
Strip 6 → Chat
Strip 7 → Media
```

Main controls:

- Gain
- Mute
- Solo
- Mono
- Routing buttons A1–A3 and B1–B3 on every strip
- Mixer profiles (`mixer_profiles`)

Mic processing:

- Compressor
- Gate
- Denoiser

VoiceMeeter uses event-based bidirectional synchronization. `vm.init_thread()` is required and update threads must stop before logout.

## Audio

Level sampling for all four strips uses one dedicated worker (`StripLevelWorker`), which emits only when a level changed. Every strip has L/R meters.

FaderDeck reconnects by itself when VoiceMeeter is closed and started again (`check_connection`, `release_vm`).

A settings window (`SettingsDialog`) sets the microphone's hardware input (used after a restart), the global mic mute hotkey (`Ctrl+Shift+M` by default) and the tray behaviour (close to tray on by default, start minimised off).

Application audio uses a dedicated Python sampling loop at roughly 10 ms with GUI updates around 60 FPS.

This architecture fixed severe stalls from the previous QTimer/GUI-thread implementation.

VU meter range:

`-60 .. 0 dB`

Do not double-convert dB values.

## Applications

Application sessions are grouped by actual VoiceMeeter routing:

```text
Game | Chat | Media
```

Grouped volume/mute control applies to underlying Windows audio sessions. Group meter uses the highest active peak.

Friendly names are used for known executables, including Microsoft Teams, Steam, Steam Client Web, SignalRGB Core, Brave Browser and Edge WebView2.

Application hiding is per channel (or all channels) and persisted with QSettings (`hidden_applications_v2`).

Applications can be dragged to another column to move their audio (`winappaudiorouter`).

## UI

Main cards:

`Mic | Game | Chat | Media`

Applications remain split into:

`Game | Chat | Media`

Application rows contain name, volume, percentage, mute control and live meter.

Application sliders support click/drag.

Mic Processing opens in a popup. Compressor, Gate and Denoiser share `ProcessingPanel`. The popup has a Mic input bar with threshold markers, and Bypass and Reset per block. Amount is a preset dial in VoiceMeeter, so Bypass and Reset restore every value, not Amount alone.

A draggable splitter separates the mixer from the lower panels (`splitter_v1`).

Errors are logged to `%LOCALAPPDATA%\FaderDeck\faderdeck.log`.

Window position/size persists.

Icons are monochrome.

## Icon / Build

Icon:

`faderdeck.ico`

Build script:

`build_faderdeck.ps1`

Launcher:

`faderdeck_launcher.py`

Required PyInstaller icon options:

```powershell
--icon $icon
--add-data "$icon;."
```

Output:

`dist\FaderDeck.exe`

`dist\` is ignored by Git.

## Release

`v1.0.2` is the latest tag.

Assets:

- `FaderDeck.exe`
- Source code zip
- Source code tar.gz

The EXE is distributed as a GitHub Release asset and is not committed to Git.

## Important Stability Areas

Do not regress:

- VoiceMeeter event synchronization
- dedicated application audio loop
- dedicated level worker (`StripLevelWorker`)
- reconnect without restarting VoiceMeeter on its own
- Bypass and Reset restoring the whole processing state
- version-independent hide keys
- the unit tests in `tests/` passing
- the local API's protections (loopback only, token, no web pages, exclusive port)
- quitting on Windows session end instead of hiding in the tray
- correct dB conversion
- safe VoiceMeeter shutdown
- compressor and gate timing setter (`sendtext`, `SCRIPT_KEYS`)
- file logging (no `print()`)
- application grouping
- application hiding
- QSettings persistence
- Mic Processing popup
- valid Qt base font
- `resource_path()` icon loading
- PyInstaller `--add-data`
- no `--collect-all PySide6` in the build

## Build Locking

The build script asks a running FaderDeck to quit (`FaderDeck.exe --quit`) before building. Never stop it by force: a killed process stays listed as a client in VoiceMeeter until VoiceMeeter is restarted.

## Future UI

The draggable divider is implemented. Applications remain three columns: Game, Chat, Media.

## Future Work

Potential areas:

- application routing rules
- presets/profiles
- installer and signed EXE
- custom names for the Game, Chat and Media channels
- VoiceMeeter Banana and standard edition
- volume persistence
- pan/balance
- additional VoiceMeeter controls
- global hotkeys
- system tray
- OBS/Stream Deck
- local API/Home Assistant
- phone and tablet remote (done in v1.10.0, as a web page served by FaderDeck)
- themes/DPI improvements
- installer
- automatic updates
- release automation

## Development Files

Known local support/debug files:

```text
diagnose_audio.py
main_meter_diagnostic.py
test_vm.py
install_faderdeck_startup.ps1
faderdeck_launcher.py
build_faderdeck.ps1
```

Do not blindly commit every untracked file.

## Next Session

Keep the released behaviour stable. Run and verify the existing application before starting a new feature. Make incremental changes and keep `main.py` as the single primary source file.
