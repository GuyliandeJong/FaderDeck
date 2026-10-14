"""Pure logic: no window, no mixer."""

import os
import unittest

from fakes import main


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
                self.assertEqual(main.parse_parameter(kind, text), expected)

    def test_rubbish_raises(self):
        with self.assertRaises(ValueError):
            main.parse_parameter("db", "abc")

    def test_format_matches_what_is_parsed(self):
        for kind, value in (("db", -18.0), ("ratio", 3.0), ("hz", 500.0),
                            ("time", 150.0), ("time", 1500.0), ("gain", 3.0)):
            with self.subTest(kind=kind, value=value):
                shown = main.format_parameter(kind, value)
                self.assertEqual(main.parse_parameter(kind, shown), value)


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
        key = main.stable_hide_key
        edge = r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\{}\msedgewebview2.exe"
        self.assertEqual(key(edge.format("154.0.4258.53")), key(edge.format("155.0.1.2")))
        discord = r"C:\Users\x\AppData\Local\Discord\{}\Discord.exe"
        self.assertEqual(key(discord.format("app-1.0.9163")), key(discord.format("app-1.0.9200")))
        teams = r"C:\Program Files\WindowsApps\MSTeams_{}_x64__8wekyb3d8bbwe\ms-teams.exe"
        self.assertEqual(key(teams.format("25275.2601.4002.2815")), key(teams.format("25300.1.2.3")))

    def test_different_programs_stay_apart(self):
        key = main.stable_hide_key
        self.assertNotEqual(key(r"C:\Games\A\game.exe"), key(r"C:\Games\B\game.exe"))

    def test_ordinary_folders_are_left_alone(self):
        key = main.stable_hide_key
        self.assertEqual(key(r"C:\Program Files\7-Zip\7zFM.exe"), r"c:\program files\7-zip\7zfm.exe")
        self.assertEqual(key(r"C:\Python314\python.exe"), r"c:\python314\python.exe")

    def test_falls_back_to_the_name_and_is_stable(self):
        key = main.stable_hide_key
        self.assertEqual(key("", "Steam.exe"), "steam.exe")
        once = key(r"C:\App\1.2.3\app.exe")
        self.assertEqual(key(once), once)


class NamesTest(unittest.TestCase):
    def test_friendly_names(self):
        name = main.ApplicationAudioWorker.friendly_name
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
        self.assertNotEqual(main.quit_message(), main.show_window_message())

    def test_source_and_packaged_runs_use_different_names(self):
        self.assertTrue(main.SINGLE_INSTANCE_NAME.endswith(".Source"))
        self.assertNotEqual(
            main.show_window_message("FaderDeck.SingleInstance"),
            main.show_window_message(main.SINGLE_INSTANCE_NAME),
        )


class ThemeTest(unittest.TestCase):
    def theme(self, **parts):
        return main.clean_theme(parts)

    def test_the_default_theme_changes_nothing(self):
        for code in ("#0d1117", "#58a6ff", "#35c8ff", "#e6edf3"):
            self.assertEqual(main.theme_color(code), code)

    def test_light_theme_swaps_dark_and_pale_but_keeps_the_hue(self):
        light = self.theme(light=True)
        colour = main._PlainColor
        self.assertGreater(colour(main.theme_color("#0d1117", light)).lightnessF(), 0.8)
        self.assertLess(colour(main.theme_color("#e6edf3", light)).lightnessF(), 0.2)
        self.assertAlmostEqual(
            colour(main.theme_color("#ff514b", light)).hslHueF(),
            colour("#ff514b").hslHueF(), 2)

    def test_light_curve_always_falls_and_keeps_accents_vivid(self):
        values = [main.light_lightness(i / 100) for i in range(101)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))
        game = main._PlainColor(main.theme_color("#ff626b", self.theme(light=True)))
        self.assertGreater(game.lightnessF(), 0.4)

    def test_accent_replaces_blue_only(self):
        green = self.theme(accent="#22cc66")
        colour = main._PlainColor
        self.assertAlmostEqual(
            colour(main.theme_color("#58a6ff", green)).hslHueF(),
            colour("#22cc66").hslHueF(), 2)
        self.assertEqual(main.theme_color("#ff514b", green), "#ff514b")

    def test_channel_colour_is_used_as_chosen_and_tints_its_frame(self):
        theme = self.theme(light=True, channels={"Game": "#00aa00"})
        game = main.STRIP_COLORS["Game"]
        colour = main._PlainColor
        self.assertEqual(main.theme_color(game["accent"], theme), "#00aa00")
        self.assertAlmostEqual(
            colour(main.theme_color(game["border"], theme)).hslHueF(),
            colour("#00aa00").hslHueF(), 2)
        chat = main.STRIP_COLORS["Chat"]["accent"]
        self.assertEqual(
            main.theme_color(chat, self.theme(channels={"Game": "#00aa00"})), chat)

    def test_stored_theme_is_cleaned(self):
        class Stored:
            def __init__(self, text):
                self.text = text

            def value(self, key, default=None):
                return self.text

        self.assertEqual(main.theme_settings(Stored("not json")),
                         main.clean_theme({}))
        stored = Stored(
            '{"light": 1, "accent": "red", "channels": {"Game": "#AA0000", "X": "#000000"}}')
        self.assertEqual(main.theme_settings(stored), {
            "name": "Dark", "light": False, "accent": "",
            "channels": {"Game": "#aa0000"}})
        self.assertEqual(main.saved_themes(Stored('{"Dark": {}, "Mine": {"light": true}}')),
                         {"Mine": main.clean_theme({"light": True}, "Mine")})

    def test_channel_colours_are_used_by_their_channel_only(self):
        with open(main.__file__, encoding="utf-8") as handle:
            source = handle.read().lower()
        for colors in main.STRIP_COLORS.values():
            for code in colors.values():
                self.assertEqual(source.count(code), 1, code)

    def test_built_in_themes_are_valid(self):
        for name, value in main.BUILTIN_THEMES.items():
            clean = main.clean_theme(value, name)
            for key, wanted in value.items():
                self.assertEqual(clean[key], wanted)


class MuteSoundTest(unittest.TestCase):
    def test_wave_header_points_at_the_samples(self):
        import ctypes
        data = main.chime_samples((523, 784))
        buffer, header = main.wave_header(data)
        self.assertEqual(header.dwBufferLength, len(data))
        self.assertEqual(ctypes.string_at(header.lpData, len(data)), data)

    def test_chime_is_short_and_fades_out(self):
        import array
        samples = array.array("h", main.chime_samples(
            (660, 880), step_ms=70, decay_ms=60, rate=44100))
        frames = len(samples)
        self.assertEqual(frames, 44100 * 70 // 1000 + 44100 * 60 * 6 // 1000)
        self.assertLess(frames / 44100, 0.5)  # a short cue, not a jingle
        self.assertLess(max(abs(v) for v in samples[-200:]), 200)  # no click at the end


class FirewallTest(unittest.TestCase):
    def test_rule_allows_one_program_one_port_on_private_networks(self):
        command = main.firewall_rule_command(r"C:\Program Files\Fader's\FaderDeck.exe", 8766)
        self.assertIn("-Program 'C:\\Program Files\\Fader''s\\FaderDeck.exe'", command)
        self.assertIn("-LocalPort 8766", command)
        self.assertIn("-Profile Private", command)
        self.assertIn("-Direction Inbound", command)
        self.assertTrue(command.startswith("Remove-NetFirewallRule"), "replaces an old rule")

    def test_the_program_behind_a_virtual_environment(self):
        self.assertTrue(os.path.isfile(main.firewall_program()))
        self.assertNotIn(os.sep + "Scripts" + os.sep, main.firewall_program())


class UpdateTest(unittest.TestCase):
    DIGEST = "sha256:" + "ab" * 32

    def release(self, tag="v9.0.0", name=None, digest=DIGEST, **extra):
        return {
            "tag_name": tag,
            "html_url": "https://github.com/GuyliandeJong/FaderDeck/releases/tag/" + tag,
            "assets": [{
                "name": name or main.INSTALLER_ASSET,
                "browser_download_url":
                    "https://github.com/GuyliandeJong/FaderDeck/releases/download/"
                    + tag + "/" + main.INSTALLER_ASSET,
                "size": 1000,
                "digest": digest,
            }],
            **extra,
        }

    def test_versions(self):
        self.assertEqual(main.version_tuple("v1.6.0"), (1, 6, 0))
        self.assertEqual(main.version_tuple("1.7"), (1, 7, 0))
        self.assertEqual(main.version_tuple("v1.6.0-beta"), ())
        self.assertLess(main.version_tuple("v1.9.0"), main.version_tuple("v1.10.0"))

    def test_a_newer_release_with_an_installer_is_an_update(self):
        update = main.available_update(self.release(), current="1.6.0")
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
                self.assertIsNone(main.available_update(release, current="1.6.0"))
        other_host = self.release()
        other_host["assets"][0]["browser_download_url"] = "https://example.com/x.exe"
        self.assertIsNone(main.available_update(other_host, current="1.6.0"))

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

        good = main.Update("9.0.0", "https://github.com/x", len(data),
                           hashlib.sha256(data).hexdigest(), "")
        with mock.patch.object(main, "_open_url", lambda url, timeout: Response(data)):
            path = main.download_update(good)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), data)
            main.shutil.rmtree(os.path.dirname(path))
            bad = good._replace(sha256="00" * 32)
            with self.assertRaises(ValueError):
                main.download_update(bad)
            with self.assertRaises(InterruptedError):
                main.download_update(good, lambda done, total: False)


if __name__ == "__main__":
    unittest.main()
