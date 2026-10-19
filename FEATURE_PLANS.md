# Feature Plans

Plans for the next features, written on 2026-10-20 after v1.15.0, so work can
start without researching again. Each plan names where the code goes (see the
Source Layout in HANDOVER.md), what VoiceMeeter or Windows offers for it,
how to test it and what is still open. Ordered by recommendation: most useful
for the least work first.

Release rule: every merge to main is released as the next minor version.

| # | Feature | Effort | New dependency |
|---|---|---|---|
| 1 | Ducking | medium | none |
| 2 | Back up and restore settings | small | none |
| 3 | Make a channel Windows' default output | small | none (pycaw has it) |
| 4 | Bass, mid and treble per channel | small | none |
| 5 | Clip guard | small–medium | none |
| 6 | OBS scenes switch profiles | medium | none (QtWebSockets is in PySide6) |
| 7 | Soundboard | medium | none (QtMultimedia is in PySide6) |
| 8 | More channels through VB-CABLE | large | none |
| 9 | VoiceMeeter Banana and Standard | large, after 8 | none |
| 10 | MIDI controllers | medium–large | none (winmm through ctypes) |

Done already: mute indicator on screen and in the tray (v1.14.0).
Postponed: a signed EXE (waits until the developer brings it up). Deferred:
renaming Windows devices from FaderDeck.

Small leftovers from the v1.14.0 review, for any next change:
- A test that the settings window's combo boxes stay narrow
  (`dialogs.SettingsDialog`, the `AdjustToMinimumContentsLengthWithIcon`
  loop). The full "content fits the page" check does not work in the
  sandbox, whose offscreen fonts are about twice as wide.
- `MainWindow.sync_tray` reads the mic mute twice; compute it once at the top.

---

## 1. Ducking

**Goal.** Game and media get quieter by themselves while you talk, and come
back when you stop. Streamers ask for this; VoiceMeeter has no simple form
of it.

**How.**
- The mic level is already read on a worker thread: `strips.StripLevelWorker`
  emits `levels_received(name, left, right)` in dB. Ducking listens to the
  "Mic" levels on the GUI thread; nothing new reads VoiceMeeter.
- Lowering must not move the user's faders or break the stream mix. Reuse the
  offset mechanism the monitor level already uses: `StripWidget.set_offsets`
  adds an offset per output when the gain layers are written
  (`layered()`/`set_mix_gain()`). Ducking adds a temporary negative offset to
  the chosen channels, and writes the layers again.
- A pure function decides the state, so it can be tested without Qt:
  `duck_amount(level_db, now, state) -> (offset_db, state)` with threshold,
  attack (~50 ms), hold (~500 ms) and release (~400 ms) ramps.
  Write the layers only when the offset changes by 0.5 dB or more, so
  VoiceMeeter is not flooded (the worker runs about 20 times a second).

**Settings** (Microphone tab, new section "DUCKING"): on/off, which
channels (Game, Chat, Media checkboxes; default Game and Media), how much
(-6 to -30 dB, default -12), and which mix: what you hear, the stream, or
both (default: both). Threshold follows the mic gate if it is on, else
-40 dB.

**Tests.** `duck_amount` over a scripted level sequence (talk, pause shorter
than hold, long pause). A sandbox test that the fake gain layers drop by the
set amount on the chosen outputs only and come back.

**Open.** Duck Chat by default? Probably not: a call partner talking over
you should stay audible.

## 2. Back up and restore settings

**Goal.** One file with everything: profiles, presets, names, themes,
hotkeys, colours. For a new PC, a reinstall, or sharing a setup.

**How.**
- `core.app_settings()` holds everything in one QSettings group. Export
  `allKeys()` to JSON. `QByteArray` values (window geometry, splitter) are
  skipped: they belong to this PC's screens.
- Never export secrets: `api_token` and `remote_devices` (the paired phones'
  token hashes). An imported setup pairs its own phones.
- Import: read the JSON, check it is a dict with a `faderdeck_version` key,
  show what will change and ask, write the keys, then run
  `MainWindow.apply_settings(current_settings())` and reload the profile list.
- Buttons in Settings, General, a new section "BACKUP": "Save to file…" and
  "Load from file…" (QFileDialog).

**Tests.** Round trip through the fake settings; secrets are absent from the
export; a file with a wrong shape is refused without changing anything.

## 3. Make a channel Windows' default output

**Goal.** One click makes "Game" (or Chat, Media) the Windows default output,
without opening the sound settings. Useful after Windows resets it.

**How.**
- pycaw has it: `AudioUtilities.SetDefaultDevice(device_id, roles)` through
  `IPolicyConfig`. Find the device by name with `AudioUtilities.GetAllDevices()`;
  the names per channel are the ones `applications.py` already uses to move
  applications ("VoiceMeeter VAIO3" and so on, around `BUS_NAMES`).
- Run it in a `core.BackgroundJob`: COM calls must not block the GUI thread.
- UI: right-click on a channel's header, "Make default output". Optional
  setting "Make Game the default output when FaderDeck starts" (off).

**Tests.** The device lookup by name as a pure function over a fake device
list. Setting the default itself needs a real PC: check by hand.

## 4. Bass, mid and treble per channel

**Goal.** Simple tone control for Game, Chat and Media.

**How.**
- voicemeeterlib has `strip.bass`, `strip.mid`, `strip.treble` (VoiceMeeter's
  EQGain1–3, -12 to +12 dB) on the virtual strips. The Mic already has its
  processing panel; leave it out.
- UI: three small knobs or sliders, shown in a popup from a small "EQ"
  button on the strip (keeps the strip compact). Double right-click resets
  to 0, like the faders.
- Store the values in setup profiles: add them to the strip's profile state
  (`StripWidget` profile dict and `apply_profile`), and keep old profiles
  working (missing keys mean 0).

**Tests.** Sandbox: the fake strip gets bass/mid/treble; a profile saves and
restores them; an old profile without them leaves the EQ alone.

## 5. Clip guard

**Goal.** No distorted stream when everything is loud at once.

**How.**
- Per channel: Potato's input limiter, `strip.limit` in voicemeeterlib.
  Setting "Limit each channel at -1 dB" (on by default for new users?)
  writes `limit` on Game, Chat and Media.
- Warning: the stream outputs (B2/B3) can still clip from the sum. Read their
  bus levels in `StripLevelWorker` (the only place levels are read) and
  emit a peak per stream output. If it passes -1 dBFS, light a small red
  "CLIP" in the header for two seconds.

**Tests.** Sandbox: limit values are written; a scripted peak lights and
then clears the warning.

**Open.** Check on the live mixer how Potato's limit behaves on virtual
strips before choosing the default.

## 6. OBS scenes switch profiles

**Goal.** Changing scene in OBS loads the FaderDeck profile with the same
name: "Just chatting" loads a profile without game sound.

**How.**
- OBS 28 and newer has obs-websocket v5 built in. PySide6 ships
  `QtWebSockets.QWebSocket`, so no new dependency, and it is asynchronous
  on the GUI thread (no blocking).
- Protocol: receive Hello (op 0), send Identify (op 1) with
  `eventSubscriptions` for scenes; with a password, the authentication is
  `base64(sha256(base64(sha256(password + salt)) + challenge))`. Then listen
  for `CurrentProgramSceneChanged` (op 5) and call `apply_profile(name)` when
  a profile with exactly that name exists. No mapping table: the names are
  the mapping.
- New class `ObsLink(QObject)` in web.py; reconnect every 10 s while OBS is
  closed, quietly.
- Settings, Remote control, section "OBS": on/off, port (4455), password.

**Tests.** The authentication string against the example in the
obs-websocket docs; a fake socket that sends Hello and a scene change, and
the profile gets applied.

## 7. Soundboard

**Goal.** Short clips (alerts, jingles) at a key press, into the stream and
your ears.

**How.**
- PySide6 has QtMultimedia. `QSoundEffect` plays WAV with low delay on a
  chosen device (`QMediaDevices.audioOutputs()`); pick the VoiceMeeter input
  of the Media channel, so the routing decides who hears it.
- WAV only at first. MP3 needs `QMediaPlayer` and Qt's FFmpeg backend, which
  makes the EXE bigger: measure first.
- Pads: a list of (name, file, hotkey) in the settings, at most 12.
  `core.HOTKEYS` is a fixed list now; pads need their own hotkey ids
  (start at 200) registered next to it in `MainWindow.register_hotkeys`.
- Later: a Stream Deck action "Play sound" through the local API
  (`/api/sound/<name>`).

**Tests.** Settings round trip for the pad list; hotkey ids do not clash with
`core.HOTKEYS`. Playback itself: by hand.

**Open.** Check how much QtMultimedia adds to FaderDeck.exe (now 54 MB).

## 8. More channels through VB-CABLE

**Goal.** More than Game, Chat and Media, for example "Music" or "Alerts".
Potato has exactly three virtual inputs, but its five hardware inputs are
mostly unused: one is the microphone. A VB-CABLE (free, or the A+B and C+D
packs, donationware) on a free hardware input adds a channel. At most Mic +
3 virtual + 4 = 8 channels.

**How.**
- First the channel model: today Game, Chat and Media are fixed in
  `core.STRIPS`, `core.CHANNEL_NAME_KEYS`, `core.STRIP_COLORS`,
  `core.MUTE_HOTKEYS`, `applications.ApplicationControl.BUS_NAMES` and the
  Windows device names in applications.py. Make a channel a record:
  `{name, strip index, Windows playback device, colour}`, stored in the
  settings, with today's three as the default.
- A hardware strip has no Windows device of its own: store which VB-CABLE
  playback device ("CABLE Input") belongs to it, so moving applications
  still works.
- Theme channel colours, profiles, hotkeys, the stream mix and the streaming
  setup loop over the channel list instead of the fixed names. The phone
  remote and the Stream Deck plugin already read the channels from the API.
- Settings, General, "CHANNELS": add a channel (pick a free hardware input
  and its cable), rename, remove, reorder.
- Migration: existing settings keep exactly today's three channels.

**Tests.** Most of today's tests should pass unchanged with the default
model. Add: a fourth channel on hardware input 2 appears, routes, saves in a
profile, and survives a restart.

**Effort.** About as big as the stream mix work: 2–3 sessions.

## 9. VoiceMeeter Banana and Standard

**Goal.** Run on the free editions most people start with.

**How (after 8, which makes channels flexible).**
- Layouts from voicemeeterlib's kind maps: Standard 2 hardware + 1 virtual
  input, A1 and B1; Banana 3 + 2, A1–A3 and B1–B2; Potato 5 + 3, A1–A5 and
  B1–B3.
- Detect the running edition: `core.voicemeeter_install_state()` already
  tells Potato from the others. After login, ask the API for the type and
  create the API object with the matching kind.
- Default channels per edition: Banana has Game and Chat only (VAIO, AUX);
  Standard has one virtual input.
- `core.ALL_OUTPUTS`, `HARDWARE_OUTPUTS` and `VIRTUAL_OUTPUTS` come from the
  edition instead of being fixed.
- Streaming setup: Banana has B1 and B2, so the stream gets one output
  (voice and sound together) and Mute stream works on B2; say so in the
  setup text. Standard: no separate stream mix.
- `VoicemeeterMissingDialog` no longer blocks Banana and Standard.

**Tests.** The fake mixer gets a kind; run the window tests for each kind.

## 10. MIDI controllers

**Goal.** Physical faders and buttons (Korg nanoKONTROL, Behringer X-Touch
Mini) control FaderDeck.

**How.**
- No dependency: Windows' winmm through ctypes, as sound.py does for audio.
  `midiInGetNumDevs`, `midiInGetDevCapsW`, `midiInOpen` with a
  `CALLBACK_FUNCTION`, `midiInStart`. The callback runs on a winmm thread:
  only emit a Qt signal there (queued to the GUI thread).
- Learn mode: Settings, a new "MIDI" tab. Pick the device, press "Learn" next
  to an action (a channel's volume, mute, push to talk, a profile), move a
  control. Store `{action: (status, number)}`.
- Faders: CC value 0–127 to dB with the same curve as the on-screen fader.
  Buttons: note on or CC 127 toggles.
- Optional: send the mute state back (note on with velocity) so the
  controller's lights follow.

**Testing without hardware.** Install loopMIDI (free, a virtual MIDI port)
and VMPK (free virtual keyboard that sends notes and CC) and point VMPK at
the loopMIDI port. That covers learn mode, faders and buttons.

**Tests.** The message parser and the CC-to-dB curve as pure functions;
learn mode with a fake message source.
