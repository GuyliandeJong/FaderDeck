"""Pure logic: no window, no mixer."""

import os
import unittest

from fakes import main, project_modules
import applications
import core
import processing
import sound
import themes
import web
import updates


class ParseParameterTest(unittest.TestCase):
    def test_bare_numbers_and_units(self):
        cases = [
            ("ratio", "4:1", 4.0), ("ratio", "4", 4.0),
            ("gain", "+3 dB", 3.0), ("db", "-18 dB", -18.0), ("db", "-18", -18.0),
            ("hz", "500 Hz", 500.0),
            ("time", "150 ms", 150.0), ("time", "1.5 s", 1500.0), ("time", "150", 150.0),
            ("plain", " 3.1 ", 3.1), ("fine", "0.50", 0.5),
        ]
        for kind, text, expected in cases:
            with self.subTest(kind=kind, text=text):
                self.assertEqual(processing.parse_parameter(kind, text), expected)

    def test_rubbish_raises(self):
        with self.assertRaises(ValueError):
            processing.parse_parameter("db", "abc")

    def test_format_matches_what_is_parsed(self):
        for kind, value in (("db", -18.0), ("ratio", 3.0), ("hz", 500.0),
                            ("time", 150.0), ("time", 1500.0), ("gain", 3.0)):
            with self.subTest(kind=kind, value=value):
                shown = processing.format_parameter(kind, value)
                self.assertEqual(processing.parse_parameter(kind, shown), value)


class HotkeyTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(main.parse_hotkey("Ctrl+Shift+M"), (0x2 | 0x4, ord("M")))
        self.assertEqual(main.parse_hotkey("ctrl+alt+f5"), (0x2 | 0x1, 0x74))
        self.assertEqual(main.parse_hotkey("Alt+1"), (0x1, ord("1")))
        self.assertEqual(main.parse_hotkey("Meta+Shift+F24"), (0x8 | 0x4, 0x87))

    def test_invalid(self):
        for text in ("M", "", None, "Ctrl+", "Ctrl+Shift", "Hyper+M",
                     "Ctrl+F25", "Ctrl+Space", "Ctrl+é"):
            with self.subTest(text=text):
                self.assertIsNone(main.parse_hotkey(text))


class HideKeyTest(unittest.TestCase):
    def test_version_folders_are_ignored(self):
        key = applications.stable_hide_key
        edge = r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\{}\msedgewebview2.exe"
        self.assertEqual(key(edge.format("154.0.4258.53")), key(edge.format("155.0.1.2")))
        discord = r"C:\Users\x\AppData\Local\Discord\{}\Discord.exe"
        self.assertEqual(key(discord.format("app-1.0.9163")), key(discord.format("app-1.0.9200")))
        teams = r"C:\Program Files\WindowsApps\MSTeams_{}_x64__8wekyb3d8bbwe\ms-teams.exe"
        self.assertEqual(key(teams.format("25275.2601.4002.2815")), key(teams.format("25300.1.2.3")))

    def test_different_programs_stay_apart(self):
        key = applications.stable_hide_key
        self.assertNotEqual(key(r"C:\Games\A\game.exe"), key(r"C:\Games\B\game.exe"))

    def test_ordinary_folders_are_left_alone(self):
        key = applications.stable_hide_key
        self.assertEqual(key(r"C:\Program Files\7-Zip\7zFM.exe"), r"c:\program files\7-zip\7zfm.exe")
        self.assertEqual(key(r"C:\Python314\python.exe"), r"c:\python314\python.exe")

    def test_falls_back_to_the_name_and_is_stable(self):
        key = applications.stable_hide_key
        self.assertEqual(key("", "Steam.exe"), "steam.exe")
        once = key(r"C:\App\1.2.3\app.exe")
        self.assertEqual(key(once), once)


class NamesTest(unittest.TestCase):
    def test_friendly_names(self):
        name = applications.ApplicationAudioWorker.friendly_name
        self.assertEqual(name("steam.exe"), "Steam")
        self.assertEqual(name("warframe.x64.exe"), "Warframe")
        self.assertEqual(name("game-win64-shipping.exe"), "Game")
        self.assertEqual(name("my_cool-app.exe"), "My Cool App")
        self.assertEqual(name("thing.exe", "Nice Name"), "Nice Name")
        self.assertEqual(name(""), "Unknown Application")

    def test_devices_map_to_channels(self):
        bus = main.ApplicationControl.bus_for_device
        self.assertEqual(bus("Voicemeeter Input (VB-Audio Voicemeeter VAIO)"), "Game")
        self.assertEqual(bus("Voicemeeter AUX Input (VB-Audio Voicemeeter AUX VAIO)"), "Chat")
        self.assertEqual(bus("Voicemeeter VAIO3 Input (VB-Audio Voicemeeter VAIO3)"), "Media")
        self.assertIsNone(bus("Speakers (Realtek Audio)"))
        self.assertIsNone(bus(None))


class SettingsValuesTest(unittest.TestCase):
    def test_setting_bool(self):
        class Stored:
            def __init__(self, value):
                self._value = value

            def value(self, key, default):
                return default if self._value is None else self._value

        self.assertFalse(main.setting_bool(Stored("false"), "x", True))
        self.assertTrue(main.setting_bool(Stored("true"), "x", False))
        self.assertTrue(main.setting_bool(Stored(None), "x", True))
        self.assertFalse(main.setting_bool(Stored(False), "x", True))

    def test_set_mic_strip_rejects_bad_values(self):
        saved = main.STRIPS["Mic"]
        try:
            for value, expected in ((2, 2), ("3", 3), (9, 0), (None, 0), ("x", 0), (-1, 0)):
                with self.subTest(value=value):
                    main.set_mic_strip(value)
                    self.assertEqual(main.STRIPS["Mic"], expected)
        finally:
            main.set_mic_strip(saved)


class LevelsTest(unittest.TestCase):
    def test_left_right(self):
        pair = main.StripLevelWorker._left_right
        self.assertEqual(pair((-10.0, -12.0)), (-10.0, -12.0))
        self.assertEqual(pair((-10.0, -12.0, -200.0, -200.0, -200.0, -200.0, -200.0, -200.0)), (-10.0, -12.0))
        self.assertEqual(pair(-7.0), (-7.0, -7.0))
        self.assertEqual(pair(()), (-200.0, -200.0))
        self.assertEqual(pair(None), (-200.0, -200.0))


class SingleInstanceTest(unittest.TestCase):
    NAME = "FaderDeck.Tests.SingleInstance"

    def test_second_claim_is_refused_until_the_first_is_released(self):
        first = main.acquire_single_instance(self.NAME)
        self.assertTrue(first)
        try:
            self.assertIsNone(main.acquire_single_instance(self.NAME))
        finally:
            main.ctypes.windll.kernel32.CloseHandle(main.ctypes.c_void_p(first))
        again = main.acquire_single_instance(self.NAME)
        self.assertTrue(again)
        main.ctypes.windll.kernel32.CloseHandle(main.ctypes.c_void_p(again))

    def test_quit_and_show_are_different_messages(self):
        self.assertNotEqual(core.quit_message(), core.show_window_message())

    def test_source_and_packaged_runs_use_different_names(self):
        self.assertTrue(core.SINGLE_INSTANCE_NAME.endswith(".Source"))
        self.assertNotEqual(
            core.show_window_message("FaderDeck.SingleInstance"),
            core.show_window_message(core.SINGLE_INSTANCE_NAME),
        )


class ThemeTest(unittest.TestCase):
    def theme(self, **parts):
        return themes.clean_theme(parts)

    def test_the_default_theme_changes_nothing(self):
        for code in ("#0d1117", "#58a6ff", "#35c8ff", "#e6edf3"):
            self.assertEqual(themes.theme_color(code), code)

    def test_light_theme_swaps_dark_and_pale_but_keeps_the_hue(self):
        light = self.theme(light=True)
        colour = themes._PlainColor
        self.assertGreater(colour(themes.theme_color("#0d1117", light)).lightnessF(), 0.8)
        self.assertLess(colour(themes.theme_color("#e6edf3", light)).lightnessF(), 0.2)
        self.assertAlmostEqual(
            colour(themes.theme_color("#ff514b", light)).hslHueF(),
            colour("#ff514b").hslHueF(), 2)

    def test_light_curve_always_falls_and_keeps_accents_vivid(self):
        values = [themes.light_lightness(i / 100) for i in range(101)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))
        game = themes._PlainColor(themes.theme_color("#ff626b", self.theme(light=True)))
        self.assertGreater(game.lightnessF(), 0.4)

    def test_accent_replaces_blue_only(self):
        green = self.theme(accent="#22cc66")
        colour = themes._PlainColor
        self.assertAlmostEqual(
            colour(themes.theme_color("#58a6ff", green)).hslHueF(),
            colour("#22cc66").hslHueF(), 2)
        self.assertEqual(themes.theme_color("#ff514b", green), "#ff514b")

    def test_channel_colour_is_used_as_chosen_and_tints_its_frame(self):
        theme = self.theme(light=True, channels={"Game": "#00aa00"})
        game = core.STRIP_COLORS["Game"]
        colour = themes._PlainColor
        self.assertEqual(themes.theme_color(game["accent"], theme), "#00aa00")
        self.assertAlmostEqual(
            colour(themes.theme_color(game["border"], theme)).hslHueF(),
            colour("#00aa00").hslHueF(), 2)
        chat = core.STRIP_COLORS["Chat"]["accent"]
        self.assertEqual(
            themes.theme_color(chat, self.theme(channels={"Game": "#00aa00"})), chat)

    def test_stored_theme_is_cleaned(self):
        class Stored:
            def __init__(self, text):
                self.text = text

            def value(self, key, default=None):
                return self.text

        self.assertEqual(main.theme_settings(Stored("not json")),
                         themes.clean_theme({}))
        stored = Stored(
            '{"light": 1, "accent": "red", "channels": {"Game": "#AA0000", "X": "#000000"}}')
        self.assertEqual(main.theme_settings(stored), {
            "name": "Dark", "light": False, "accent": "", "base": "",
            "channels": {"Game": "#aa0000"}})
        self.assertEqual(main.saved_themes(Stored('{"Dark": {}, "Mine": {"light": true}}')),
                         {"Mine": themes.clean_theme({"light": True}, "Mine")})

    def test_channel_colours_are_used_by_their_channel_only(self):
        source = ""
        for module in project_modules():  # main and the modules it loads
            with open(module.__file__, encoding="utf-8") as handle:
                source += handle.read().lower()
        for colors in core.STRIP_COLORS.values():
            for code in colors.values():
                self.assertEqual(source.count(code), 1, code)

    def test_base_makes_greys_neutral_and_leaves_highlights_to_the_accent(self):
        theme = self.theme(accent="#ff0033", base="#0f0f0f")
        colour = themes._PlainColor
        background = colour(themes.theme_color("#0d1117", theme))
        self.assertLess(background.hslSaturationF(), 0.05, "near-black, not red")
        grey_text = colour(themes.theme_color("#8ba0b5", theme))
        self.assertLess(grey_text.hslSaturationF(), 0.05, "grey text stays grey")
        highlight = colour(themes.theme_color("#58a6ff", theme))
        self.assertAlmostEqual(highlight.hslHueF(), colour("#ff0033").hslHueF(), 2)
        self.assertGreater(highlight.hslSaturationF(), 0.9)

    def test_without_a_base_the_accent_tints_everything_as_before(self):
        colour = themes._PlainColor
        theme = self.theme(accent="#22cc66")
        self.assertAlmostEqual(
            colour(themes.theme_color("#0d1117", theme)).hslHueF(),
            colour("#22cc66").hslHueF(), 2)

    def test_built_in_themes_are_valid(self):
        for name, value in themes.BUILTIN_THEMES.items():
            clean = themes.clean_theme(value, name)
            for key, wanted in value.items():
                self.assertEqual(clean[key], wanted)


class MuteSoundTest(unittest.TestCase):
    def test_wave_header_points_at_the_samples(self):
        import ctypes
        data = sound.chime_samples((523, 784))
        buffer, header = sound.wave_header(data)
        self.assertEqual(header.dwBufferLength, len(data))
        self.assertEqual(ctypes.string_at(header.lpData, len(data)), data)

    def test_chime_is_short_and_fades_out(self):
        import array
        samples = array.array("h", sound.chime_samples(
            (660, 880), step_ms=70, decay_ms=60, rate=44100))
        frames = len(samples)
        self.assertEqual(frames, 44100 * 70 // 1000 + 44100 * 60 * 6 // 1000)
        self.assertLess(frames / 44100, 0.5)  # a short cue, not a jingle
        self.assertLess(max(abs(v) for v in samples[-200:]), 200)  # no click at the end


class FirewallTest(unittest.TestCase):
    def test_rule_allows_one_program_one_port_on_private_networks(self):
        command = web.firewall_rule_command(r"C:\Program Files\Fader's\FaderDeck.exe", 8766)
        self.assertIn("-Program 'C:\\Program Files\\Fader''s\\FaderDeck.exe'", command)
        self.assertIn("-LocalPort 8766", command)
        self.assertIn("-Profile Private", command)
        self.assertIn("-Direction Inbound", command)
        self.assertTrue(command.startswith("Remove-NetFirewallRule"), "replaces an old rule")

    def test_the_program_behind_a_virtual_environment(self):
        self.assertTrue(os.path.isfile(web.firewall_program()))
        self.assertNotIn(os.sep + "Scripts" + os.sep, web.firewall_program())


class SoundCheckTest(unittest.TestCase):
    def test_picks_the_processed_microphone(self):
        pick = sound.sound_check_device
        self.assertEqual(pick(["Mic (USB)", "Voicemeeter Out B1 (VB-Audio Vo"]),
                         "Voicemeeter Out B1 (VB-Audio Vo")
        renamed = ["Analogue 1 + 2 (2- Focusrite US", "Voicemeeter Out A1 (VB-Audio Vo",
                   "Stream Microphone (VB-Audio Voi", "Microphone (VB-Audio Voicemeete"]
        self.assertEqual(pick(renamed), "Microphone (VB-Audio Voicemeete")
        self.assertEqual(pick(["Voicemeeter Out A1 (VB-Audio Vo", "Focusrite"]), "",
                         "never a hardware output or the raw mic")


class MuteIndicatorTest(unittest.TestCase):
    def test_mic_mute_wins_and_no_stream_set_is_no_warning(self):
        state = main.mute_indicator_state
        self.assertEqual(state(True, True), "muted")
        self.assertEqual(state(True, None), "muted")
        self.assertEqual(state(False, True), "stream")
        self.assertIsNone(state(False, False))
        self.assertIsNone(state(False, None))


class VoicemeeterInstallTest(unittest.TestCase):
    def state(self, files, registered=True):
        import tempfile
        import winreg
        from unittest import mock
        with tempfile.TemporaryDirectory() as folder:
            for name in files:
                open(os.path.join(folder, name), "w").close()
            uninstaller = os.path.join(folder, "Voicemeeter8Setup.exe")

            def open_key(root, key):
                if not registered:
                    raise FileNotFoundError(key)
                return mock.MagicMock()
            with mock.patch.object(winreg, "OpenKey", open_key),                     mock.patch.object(winreg, "QueryValueEx",
                                      lambda key, name: (f'"{uninstaller}"', 1)):
                return main.voicemeeter_install_state()

    def test_potato_banana_and_none(self):
        self.assertEqual(self.state(["voicemeeter8x64.exe", "voicemeeterpro.exe"]), "potato")
        self.assertEqual(self.state(["voicemeeterpro.exe", "voicemeeter.exe"]), "other")
        self.assertEqual(self.state([], registered=False), "missing")


class UpdateTest(unittest.TestCase):
    DIGEST = "sha256:" + "ab" * 32

    def release(self, tag="v9.0.0", name=None, digest=DIGEST, **extra):
        return {
            "tag_name": tag,
            "html_url": "https://github.com/GuyliandeJong/FaderDeck/releases/tag/" + tag,
            "assets": [{
                "name": name or updates.INSTALLER_ASSET,
                "browser_download_url":
                    "https://github.com/GuyliandeJong/FaderDeck/releases/download/"
                    + tag + "/" + updates.INSTALLER_ASSET,
                "size": 1000,
                "digest": digest,
            }],
            **extra,
        }

    def test_versions(self):
        self.assertEqual(updates.version_tuple("v1.6.0"), (1, 6, 0))
        self.assertEqual(updates.version_tuple("1.7"), (1, 7, 0))
        self.assertEqual(updates.version_tuple("v1.6.0-beta"), ())
        self.assertLess(updates.version_tuple("v1.9.0"), updates.version_tuple("v1.10.0"))

    def test_a_newer_release_with_an_installer_is_an_update(self):
        update = updates.available_update(self.release(), current="1.6.0")
        self.assertEqual(update.version, "9.0.0")
        self.assertEqual(update.sha256, "ab" * 32)

    def test_no_update_without_a_reason_to_trust_it(self):
        for release in (
            self.release(tag="v1.6.0"),                 # not newer
            self.release(name="FaderDeck.exe"),         # no installer
            self.release(digest=""),                    # nothing to check it with
            self.release(digest="md5:abc"),
            self.release(prerelease=True),
            {"assets": "nonsense"},
            None,
        ):
            with self.subTest(release=release):
                self.assertIsNone(updates.available_update(release, current="1.6.0"))
        other_host = self.release()
        other_host["assets"][0]["browser_download_url"] = "https://example.com/x.exe"
        self.assertIsNone(updates.available_update(other_host, current="1.6.0"))

    def test_installer_does_not_inherit_the_unpacked_folder(self):
        environment = main.installer_environment({
            "PATH": r"C:\Windows",
            "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI123",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_MEIPASS2": r"C:\Temp\_MEI123",
        })
        self.assertEqual(environment, {
            "PATH": r"C:\Windows", "PYINSTALLER_RESET_ENVIRONMENT": "1"})

    def test_download_is_checked_against_the_digest(self):
        import hashlib, io
        from unittest import mock
        data = b"installer" * 1000

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        good = updates.Update("9.0.0", "https://github.com/x", len(data),
                           hashlib.sha256(data).hexdigest(), "")
        with mock.patch.object(updates, "_open_url", lambda url, timeout: Response(data)):
            path = updates.download_update(good)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), data)
            updates.shutil.rmtree(os.path.dirname(path))
            bad = good._replace(sha256="00" * 32)
            with self.assertRaises(ValueError):
                updates.download_update(bad)
            with self.assertRaises(InterruptedError):
                updates.download_update(good, lambda done, total: False)


if __name__ == "__main__":
    unittest.main()
