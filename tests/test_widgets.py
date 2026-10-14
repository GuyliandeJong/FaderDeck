"""Behaviour of the widgets against a fake mixer."""

import json
import unittest

from fakes import COMPRESSOR, FakeSettings, Sandbox, main, pump


def compressor_state(vm):
    comp = vm.strip[0].comp
    return {key: getattr(comp, key) for key in COMPRESSOR}


class ProcessingPanelTest(unittest.TestCase):
    """Bypass and Reset must give back every value.

    VoiceMeeter replaces the advanced values whenever Amount changes; an
    earlier version remembered Amount only and lost the user's settings.
    """

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        self.vm = self.sandbox.vm
        self.panel = main.CompressorControl(self.vm)
        self.panel.take_snapshot()

    def bypass(self, panel, on):
        panel.bypass_button.setChecked(on)
        panel.on_bypass_clicked(on)

    def test_bypass_on_and_off_restores_everything(self):
        self.bypass(self.panel, True)
        self.assertEqual(self.vm.strip[0].comp.knob, 0.0)
        self.assertEqual(self.vm.strip[0].comp.threshold, -40.0, "the preset took over")

        self.bypass(self.panel, False)
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)
        self.assertEqual(FakeSettings.store, {})
        self.assertEqual(self.panel.controls["threshold"]["edit"].text(), "-18.0 dB")
        self.assertEqual(self.panel.controls["release"]["edit"].text(), "150.0 ms")

    def test_bypass_survives_a_restart(self):
        self.bypass(self.panel, True)
        again = main.CompressorControl(self.vm)
        self.assertTrue(again.bypass_button.isChecked())
        again.take_snapshot()
        self.bypass(again, False)
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)

    def test_reset_after_moving_amount(self):
        self.panel.controls["knob"]["slider"].setValue(70)
        self.assertEqual(self.vm.strip[0].comp.threshold, -40.0)
        self.vm.strip[0].comp.makeup = False
        self.panel.reset()
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)

    def test_reset_while_bypassed(self):
        self.bypass(self.panel, True)
        self.panel.reset()
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)
        self.assertFalse(self.panel.bypass_button.isChecked())

    def test_bypass_when_already_off_does_nothing(self):
        self.vm.strip[0].comp.__dict__["_knob"] = 0.0
        self.bypass(self.panel, True)
        self.assertFalse(self.panel.bypass_button.isChecked())
        self.assertIsNone(self.panel._bypassed)

    def test_moving_amount_ends_a_bypass(self):
        self.bypass(self.panel, True)
        self.panel.controls["knob"]["slider"].setValue(40)
        self.assertFalse(self.panel.bypass_button.isChecked())

    def test_moving_amount_can_be_undone(self):
        """Amount replaces the advanced values in VoiceMeeter. The panel says
        so and UNDO brings everything back."""
        panel, comp = self.panel, self.vm.strip[0].comp
        self.assertTrue(panel.amount_notice.isHidden())

        panel.controls["knob"]["slider"].setValue(32)
        self.assertEqual(comp.threshold, -40.0, "VoiceMeeter's preset took over")
        self.assertFalse(panel.amount_notice.isHidden())

        panel.controls["knob"]["slider"].setValue(45)      # keeps the first state
        panel.undo_amount()
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)
        self.assertTrue(panel.amount_notice.isHidden())
        self.assertEqual(panel.controls["knob"]["edit"].text(), "3.1")

    def test_typing_an_amount_can_be_undone_too(self):
        panel = self.panel
        panel.controls["knob"]["edit"].setText("6")
        panel.on_value_edit_finished("knob")
        self.assertFalse(panel.amount_notice.isHidden())
        panel.undo_amount()
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)

    def test_carrying_on_after_amount_drops_the_undo(self):
        panel = self.panel
        panel.controls["knob"]["slider"].setValue(32)
        panel.controls["ratio"]["slider"].setValue(50)      # accepts the new base
        self.assertTrue(panel.amount_notice.isHidden())
        panel.undo_amount()                                 # nothing to undo
        self.assertEqual(self.vm.strip[0].comp.ratio, 5.0)

    def test_reset_and_bypass_leave_nothing_to_undo(self):
        panel = self.panel
        panel.controls["knob"]["slider"].setValue(32)
        panel.reset()
        self.assertTrue(panel.amount_notice.isHidden())
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)

        panel.controls["knob"]["slider"].setValue(32)
        self.bypass(panel, True)
        self.assertTrue(panel.amount_notice.isHidden())

    def test_a_single_slider_block_needs_no_notice(self):
        denoiser = main.DenoiserControl(self.vm)
        self.assertIsNone(denoiser.amount_notice)
        denoiser.controls["knob"]["slider"].setValue(50)
        self.assertEqual(self.vm.strip[0].denoiser.knob, 5.0)

    def test_timing_goes_through_sendtext(self):
        """Do-not-regress: the float setter can crash for these parameters."""
        self.vm.sent.clear()
        self.panel._apply("release", 200.0)
        self.panel._apply("attack", 20.0)
        self.assertEqual(self.vm.sent, [
            "Strip[0].Comp.Release=200.000000",
            "Strip[0].Comp.Attack=20.000000",
        ])

    def test_time_sliders_are_logarithmic_and_cover_the_range(self):
        panel = self.panel
        self.assertEqual(panel._from_slider("release", 0), 0.0)
        self.assertEqual(panel._from_slider("release", main.TIME_SLIDER_STEPS), 5000.0)
        self.assertEqual(panel._from_slider("attack", main.TIME_SLIDER_STEPS), 200.0)
        middle = panel._from_slider("release", main.TIME_SLIDER_STEPS // 2)
        self.assertLess(middle, 500.0, "half the track must not already be seconds")
        for value in (5.0, 150.0, 1000.0):
            back = panel._from_slider("release", panel._to_slider("release", value))
            self.assertAlmostEqual(back, value, delta=value * 0.02 + 0.2)

    def test_typed_value_out_of_range_is_refused(self):
        edit = self.panel.controls["threshold"]["edit"]
        edit.setText("-99")
        self.panel.on_value_edit_finished("threshold")
        self.assertEqual(self.vm.strip[0].comp.threshold, -18.0)
        self.assertEqual(edit.text(), "-18.0 dB")


class HiddenApplicationsTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)

    def test_old_entries_are_rewritten_once(self):
        old = [
            r"chat|c:\edge\application\154.0.4258.53\msedgewebview2.exe",
            r"chat|c:\edge\application\154.0.4258.62\msedgewebview2.exe",
            r"game|c:\users\x\discord\app-1.0.9260\discord.exe",
            "media|steam.exe",
        ]
        FakeSettings.store["hidden_applications_v2"] = json.dumps(old)
        control = main.ApplicationControl()
        self.assertEqual(control.hidden_applications, {
            r"chat|c:\edge\application\*\msedgewebview2.exe",
            r"game|c:\users\x\discord\*\discord.exe",
            "media|steam.exe",
        })
        self.assertEqual(
            set(json.loads(FakeSettings.store["hidden_applications_v2"])),
            control.hidden_applications,
        )
        self.assertFalse(main.ApplicationControl()._hidden_needs_save)

    def test_hidden_on_one_channel_only(self):
        control = main.ApplicationControl()
        # Without Windows audio sessions there are no rows to rebuild.
        control.rebuild_rows = control.update_status = lambda: None
        control.on_hide_requested(r"c:\apps\thing.exe", "Chat", True)
        hidden = lambda bus: control._is_hidden({"bus": bus, "hide_key": r"c:\apps\thing.exe"})
        self.assertTrue(hidden("Chat"))
        self.assertFalse(hidden("Game"))
        control.on_hide_requested(r"c:\apps\thing.exe", main.ALL_CHANNELS, True)
        self.assertTrue(hidden("Game") and hidden("Media"))
        control.on_hide_requested(r"c:\apps\thing.exe", main.ALL_CHANNELS, False)
        self.assertFalse(hidden("Chat"))


class MovedApplicationTest(unittest.TestCase):
    """After a move Windows shows an application on two channels for a while."""

    def entry(self, bus, playing):
        return {
            "app_name": "player.exe",
            "executable_path": r"c:\player\player.exe",
            "display_name": "Player",
            "bus": bus,
            "sessions": [{"state": 1 if playing else 0}],
        }

    def test_the_silent_duplicate_is_dropped(self):
        worker = main.ApplicationAudioWorker()
        found = {"old": self.entry("Game", False), "new": self.entry("Chat", True)}
        worker._drop_stale_sessions(found)
        self.assertEqual(list(found), ["new"])

    def test_still_playing_on_the_old_channel_is_marked_as_moving(self):
        worker = main.ApplicationAudioWorker()
        worker._pending_moves[("player.exe", r"c:\player\player.exe")] = {
            "target": "Chat", "deadline": main.time.monotonic() + 60, "name": "Player",
        }
        found = {"old": self.entry("Game", True)}
        worker._drop_stale_sessions(found)
        self.assertEqual(found["old"]["moving_to"], "Chat")


class MainWindowTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)

    def test_builds_four_strips(self):
        self.assertTrue(self.window.connected)
        self.assertEqual(list(self.window.strips), ["Mic", "Game", "Chat", "Media"])
        self.assertEqual(self.window.strips["Mic"].strip_index, 0)
        self.assertEqual(self.window.strips["Game"].strip_index, 5)

    def test_reconnects_and_reuses_the_widgets(self):
        window, vm = self.window, self.sandbox.vm
        strips_before = dict(window.strips)

        self.sandbox.running = False
        window.check_connection()
        self.assertFalse(window.connected)
        self.assertFalse(vm.logged_in or vm.thread_running)
        self.assertIsNone(window.mic_level_thread)
        self.assertFalse(window.mixer_container.isEnabled())
        self.assertFalse(window.offline_banner.isHidden())

        vm.strip[5].gain = -12.0            # changed while we were away
        self.sandbox.running = True
        window.check_connection()
        self.assertFalse(window.connected, "waits one extra check")
        window.check_connection()
        self.assertTrue(window.connected and vm.logged_in and vm.thread_running)
        self.assertEqual(window.strips, strips_before)
        self.assertEqual(window.mixer_layout.count(), 4)
        self.assertEqual(window.strips["Game"].gain_label.text(), "-12.00 dB")
        self.assertTrue(window.mixer_container.isEnabled())

    def test_logs_out_when_the_program_ends_without_closing_the_window(self):
        window, vm = self.window, self.sandbox.vm
        self.assertTrue(vm.logged_in)
        window.release_vm_at_exit()
        self.assertFalse(vm.logged_in or vm.thread_running)
        vm.logged_in = True                 # a second call must not act again
        window.release_vm_at_exit()
        self.assertTrue(vm.logged_in)
        vm.logged_in = False

    def test_no_logout_at_exit_after_a_normal_close(self):
        window, vm = self.window, self.sandbox.vm
        self.sandbox.close(window)
        self.assertFalse(vm.logged_in)
        vm.logged_in = True
        window.release_vm_at_exit()
        self.assertTrue(vm.logged_in, "already released; nothing to do")
        vm.logged_in = False

    def test_does_not_log_in_while_voicemeeter_is_closed(self):
        window, vm = self.window, self.sandbox.vm
        self.sandbox.running = False
        window.check_connection()
        logins = vm.logins
        for _ in range(5):
            window.check_connection()
        self.assertEqual(vm.logins, logins, "logging in would start VoiceMeeter")

    def test_failed_login_leaves_a_clean_disconnected_state(self):
        window, vm = self.window, self.sandbox.vm
        self.sandbox.running = False
        window.check_connection()
        vm.fail_login = True
        self.sandbox.running = True
        window.check_connection()
        window.check_connection()
        self.assertFalse(window.connected)
        self.assertIsNone(window.mic_level_thread)
        vm.fail_login = False
        window.check_connection()
        window.check_connection()
        self.assertTrue(window.connected)

    def test_levels_reach_every_strip(self):
        vm = self.sandbox.vm
        vm.strip[6].levels.prefader = (-20.0, -24.0, -200.0, -200.0, -200.0, -200.0, -200.0, -200.0)
        pump(0.3)
        chat = self.window.strips["Chat"]
        self.assertEqual([meter._target_level for meter in chat.vu_meters], [-20.0, -24.0])

    def test_hotkey_toggles_the_mic_mute(self):
        window, mic = self.window, self.sandbox.vm.strip[0]
        window.on_hotkey(main.HOTKEY_MIC_MUTE)
        self.assertTrue(mic.mute)
        self.assertTrue(window.strips["Mic"].mute_button.isChecked())
        window.on_hotkey(main.HOTKEY_MIC_MUTE)
        self.assertFalse(mic.mute)
        window.on_hotkey(999)
        self.assertFalse(mic.mute)

    def test_every_channel_has_its_own_mute_hotkey(self):
        window, vm = self.window, self.sandbox.vm
        for name, (hotkey_id, _key, _default) in main.MUTE_HOTKEYS.items():
            with self.subTest(name=name):
                strip = vm.strip[main.STRIPS[name]]
                window.on_hotkey(hotkey_id)
                self.assertTrue(strip.mute)
                window.on_hotkey(hotkey_id)
                self.assertFalse(strip.mute)

    def test_hotkey_ids_and_keys_are_unique(self):
        self.assertEqual(len({a.id for a in main.HOTKEYS}), len(main.HOTKEYS))
        self.assertEqual(len({a.key for a in main.HOTKEYS}), len(main.HOTKEYS))
        self.assertEqual(len({a.label for a in main.HOTKEYS}), len(main.HOTKEYS))

    def hotkey(self, key):
        return next(action.id for action in main.HOTKEYS if action.key == key)

    def test_volume_hotkeys_move_the_fader_by_one_decibel(self):
        window, game = self.window, self.sandbox.vm.strip[5]
        window.on_hotkey(self.hotkey("hotkey_game_up"))
        self.assertEqual(game.gain, 1.0)
        window.on_hotkey(self.hotkey("hotkey_game_down"))
        window.on_hotkey(self.hotkey("hotkey_game_down"))
        self.assertEqual(game.gain, -1.0)
        self.assertEqual(window.strips["Game"].gain_label.text(), "-1.00 dB")
        self.assertEqual(self.sandbox.vm.strip[6].gain, 0.0, "other strips untouched")

    def test_volume_hotkeys_stop_at_the_end_of_the_fader(self):
        window, mic = self.window, self.sandbox.vm.strip[0]
        window.strips["Mic"].fader.setValue(1150)
        window.on_hotkey(self.hotkey("hotkey_mic_up"))
        window.on_hotkey(self.hotkey("hotkey_mic_up"))
        self.assertEqual(mic.gain, 12.0)

    def test_volume_hotkeys_repeat_while_held_but_mute_does_not(self):
        by_key = {action.key: action for action in main.HOTKEYS}
        self.assertTrue(by_key["hotkey_game_up"].repeats)
        self.assertFalse(by_key["hotkey_game_mute"].repeats)
        self.assertFalse(by_key["hotkey_profile_next"].repeats)

    def test_profile_hotkeys_walk_through_the_profiles(self):
        window, game = self.window, self.sandbox.vm.strip[5]
        for name, gain in (("Alpha", -300), ("Beta", -600), ("Gamma", -900)):
            window.strips["Game"].fader.setValue(gain)
            window.save_profile(name)
        self.assertEqual(window.active_profile, "Gamma")

        window.on_hotkey(self.hotkey("hotkey_profile_next"))     # wraps round
        self.assertEqual((window.active_profile, game.gain), ("Alpha", -3.0))
        window.on_hotkey(self.hotkey("hotkey_profile_next"))
        self.assertEqual((window.active_profile, game.gain), ("Beta", -6.0))
        window.on_hotkey(self.hotkey("hotkey_profile_previous"))
        window.on_hotkey(self.hotkey("hotkey_profile_previous"))
        self.assertEqual((window.active_profile, game.gain), ("Gamma", -9.0))
        self.assertEqual(window.profile_list.currentText(), "Gamma")

    def test_profile_hotkey_without_profiles_does_nothing(self):
        self.window.on_hotkey(self.hotkey("hotkey_profile_next"))
        self.assertEqual(self.window.active_profile, "")

    def test_settings_window_lists_every_hotkey(self):
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        self.assertEqual(set(dialog.hotkey_edits), {a.key for a in main.HOTKEYS})
        self.assertEqual(dialog.tabs.tabText(0), "General")
        self.assertEqual(dialog.tabs.tabText(1), "Microphone")
        self.assertEqual(dialog.tabs.tabText(3), "Hotkeys")
        self.assertEqual(set(dialog.values()) - set(dialog.hotkey_edits),
                         {"mic_strip", "close_to_tray", "start_minimized",
                          "api_enabled", "api_port", "api_token",
                          "theme", "themes", "check_updates", "mute_sound",
                          "mute_sound_device", "listen_bus", "stream_bus",
                          "remote_enabled", "remote_port", "remote_devices",
                          *main.CHANNEL_NAME_KEYS.values()})

    def test_own_channel_name_is_shown_but_the_key_stays(self):
        settings = self.window.window_settings
        settings.setValue("channel_name_game", "  Music  ")
        self.window.refresh_channel_names()
        self.assertEqual(self.window.strips["Game"].name_label.text(), "Music")
        self.assertIn("Game", self.window.strips)
        self.assertEqual(
            self.window.current_settings()["channel_name_game"], "  Music  ")
        settings.setValue("channel_name_game", "")
        self.window.refresh_channel_names()
        self.assertEqual(self.window.strips["Game"].name_label.text(), "Game")

    def test_theme_changes_live_and_cancel_puts_it_back(self):
        button = self.window.settings_button
        dark = button.styleSheet()
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        dialog.theme.setCurrentText("Light")
        dialog.on_theme_chosen()
        self.assertNotEqual(button.styleSheet(), dark)
        self.assertTrue(dialog.light.isChecked())
        dialog.channel_colors["Game"].set_color("#00aa00")
        dialog.on_theme_edited()
        self.assertEqual(dialog.theme.currentText(), main.CUSTOM_THEME)
        self.assertIn("#00aa00", self.window.strips["Game"].name_label.styleSheet())
        dialog.themes["Mine"] = main.clean_theme(dialog.theme_value(), "Mine")
        dialog.show_theme(dialog.themes["Mine"])
        self.assertEqual(dialog.values()["theme"]["name"], "Mine")
        self.assertTrue(dialog.delete_theme_button.isEnabled())
        dialog.reject()
        self.assertEqual(button.styleSheet(), dark)

    def test_muting_the_mic_plays_a_sound_unless_switched_off(self):
        sounds = self.sandbox.mute_sounds
        self.window.toggle_mic_mute()
        self.window.window_settings.setValue("mute_sound_device", "Headphones")
        self.window.toggle_mic_mute()
        self.assertEqual(sounds, [(True, ""), (False, "Headphones")])
        self.window.toggle_strip_mute("Game")
        self.window.window_settings.setValue("mute_sound", False)
        self.window.toggle_mic_mute()
        self.assertEqual(len(sounds), 2)

    def test_chime_settings_warn_when_the_stream_may_hear_it(self):
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        dialog.sound_device.addItem("Game (VB-Audio Voicemeeter VAIO…",
                                    "Game (VB-Audio Voicemeeter VAIO")
        dialog.sound_device.addItem("Headphones", "Headphones")
        dialog.sound_device.setCurrentIndex(0)
        self.assertIn("default output", dialog.chime_hint.text())
        dialog.sound_device.setCurrentIndex(dialog.sound_device.findData("Headphones"))
        self.assertIn("Only you hear it", dialog.chime_hint.text())
        dialog.sound_device.setCurrentIndex(
            dialog.sound_device.findData("Game (VB-Audio Voicemeeter VAIO"))
        self.assertIn("VoiceMeeter input", dialog.chime_hint.text())
        self.assertEqual(dialog.values()["mute_sound_device"],
                         "Game (VB-Audio Voicemeeter VAIO")
        dialog.mute_sound.setChecked(False)
        self.assertFalse(dialog.sound_device.isEnabled())
        self.assertEqual(dialog.chime_hint.text(), "")

    def test_settings_window_names_hotkeys_another_program_holds(self):
        self.window.refused_hotkeys = {
            "hotkey_mic_mute": ("Ctrl+Alt+M", "Mute microphone")}
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        texts = [label.text() for label in dialog.findChildren(main.QLabel)]
        self.assertTrue(any("Ctrl+Alt+M (Mute microphone)" in t for t in texts))
        self.assertIn("f85149", dialog.hotkey_edits["hotkey_mic_mute"].styleSheet())
        self.assertEqual(dialog.hotkey_edits["hotkey_game_mute"].styleSheet(), "")

    def test_mic_input_changes_without_a_restart(self):
        self.window.set_mic_input(2)
        mic = self.window.strips["Mic"]
        self.assertEqual(mic.strip_index, 2)
        self.assertIs(mic.strip, self.sandbox.vm.strip[2])
        self.assertEqual(mic.source_label.text(), "Stereo Input 3")
        for control in self.window.processing_blocks().values():
            self.assertEqual(control.strip_index, 2)
            self.assertIs(control.target,
                          getattr(self.sandbox.vm.strip[2], control.ATTRIBUTE))
        self.assertEqual(main.STRIPS["Mic"], 2)

    def hotkey_action(self, key):
        return next(a for a in main.HOTKEYS if a.key == key)

    def test_push_to_talk_unmutes_while_held_and_mutes_again(self):
        mic = self.window.strips["Mic"]
        self.window.set_mic_mute(True)
        self.window.window_settings.setValue("hotkey_mic_push_to_talk", "Ctrl+Alt+T")
        held = [True]
        self.window.key_is_down = lambda key: held[0]
        sounds = len(self.sandbox.mute_sounds)
        self.window.on_hotkey(self.hotkey_action("hotkey_mic_push_to_talk").id)
        self.assertFalse(mic.mute_button.isChecked())
        self.window.check_held_key()
        self.assertFalse(mic.mute_button.isChecked())  # still held
        held[0] = False
        self.window.check_held_key()
        self.assertTrue(mic.mute_button.isChecked())
        self.assertEqual(len(self.sandbox.mute_sounds), sounds)  # no chime

    def test_hold_to_mute_puts_the_old_state_back(self):
        mic = self.window.strips["Mic"]
        self.window.set_mic_mute(False)
        self.window.window_settings.setValue("hotkey_mic_hold_mute", "Ctrl+Alt+H")
        held = [True]
        self.window.key_is_down = lambda key: held[0]
        self.window.on_hotkey(self.hotkey_action("hotkey_mic_hold_mute").id)
        self.assertTrue(mic.mute_button.isChecked())
        held[0] = False
        self.window.check_held_key()
        self.assertFalse(mic.mute_button.isChecked())

    def test_listen_routes_the_mic_to_your_output(self):
        mic = self.window.strips["Mic"]
        self.window.window_settings.setValue("listen_bus", "A2")
        self.window.toggle_mic_listen()
        self.assertTrue(mic.route_buttons["A2"].isChecked())
        self.assertTrue(self.window.listen_button.isChecked())
        self.assertEqual(self.window.handle_api_call("POST", ["listen"], {"state": "off"}),
                         (200, {"listen": False}))
        self.assertFalse(mic.route_buttons["A2"].isChecked())

    def test_stream_mute_needs_the_stream_output_and_takes_the_mic_off_it(self):
        mic = self.window.strips["Mic"]
        status, _answer = self.window.handle_api_call("POST", ["stream-mute"], {})
        self.assertEqual(status, 409)
        self.assertFalse(self.window.stream_mute_button.isEnabled())
        self.window.window_settings.setValue("stream_bus", "B2")
        self.window.set_mic_route("B2", True)
        self.window.toggle_stream_mute()
        self.assertFalse(mic.route_buttons["B2"].isChecked())
        self.assertTrue(self.window.stream_mute_button.isChecked())
        self.assertEqual(self.window.api_state()["stream_mute"], True)
        self.window.toggle_stream_mute()
        self.assertTrue(mic.route_buttons["B2"].isChecked())

    def test_downloaded_update_starts_the_installer_and_quits(self):
        started = []
        saved = main.subprocess.Popen
        main.subprocess.Popen = lambda args, **kwargs: started.append((args, kwargs["env"]))
        try:
            self.window.on_update_downloaded(r"C:\temp\FaderDeck-Setup.exe")
        finally:
            main.subprocess.Popen = saved
        (arguments, environment), = started
        self.assertEqual(arguments, [r"C:\temp\FaderDeck-Setup.exe",
                                     *main.INSTALLER_OPTIONS])
        self.assertEqual(environment["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertTrue(self.window._quitting)

    def test_updates_are_not_checked_when_running_from_source(self):
        self.assertFalse(self.window.updater.busy)

    def test_settings_window_refuses_unusable_and_double_hotkeys(self):
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        self.assertEqual(dialog.hotkey_problem(), "")
        sequence = main.QKeySequence
        game = dialog.hotkey_edits["hotkey_game_mute"]
        game.setKeySequence(sequence("Ctrl+Shift+M"))
        self.assertIn("more than one", dialog.hotkey_problem())
        game.setKeySequence(sequence("G"))
        self.assertIn("cannot be used", dialog.hotkey_problem())
        game.setKeySequence(sequence("Ctrl+Alt+G"))
        self.assertEqual(dialog.hotkey_problem(), "")
        self.assertEqual(dialog.values()["hotkey_game_mute"], "Ctrl+Alt+G")

    def test_compact_view_keeps_fader_meters_and_mute(self):
        window = self.window
        window.show()
        pump()
        self.assertFalse(window.compact)

        window.compact_button.click()
        pump()
        self.assertTrue(window.compact)
        self.assertTrue(FakeSettings.store["compact_mode"])
        self.assertFalse(window.lower_container.isVisible())
        strip = window.strips["Game"]
        for hidden in (strip.solo_button, strip.mono_button, strip.routing_title,
                       strip.route_buttons["A1"], strip.source_label):
            self.assertFalse(hidden.isVisible())
        for shown in (strip.fader, strip.mute_button, strip.gain_label, *strip.vu_meters):
            self.assertTrue(shown.isVisible())
        self.assertEqual(window.minimumSize().width(), main.COMPACT_MIN_SIZE[0])

        window.compact_button.click()
        pump()
        self.assertFalse(window.compact)
        self.assertTrue(window.lower_container.isVisible())
        self.assertTrue(strip.solo_button.isVisible())
        self.assertTrue(window.strips["Mic"].fader.show_labels)
        self.assertEqual(window.minimumSize().width(), main.WINDOW_MIN_SIZE[0])

    def test_compact_view_still_follows_hotkeys_and_profiles(self):
        window, vm = self.window, self.sandbox.vm
        window.strips["Chat"].route_buttons["B1"].click()
        window.save_profile("Main")
        window.set_compact(True)

        window.strips["Chat"].route_buttons["B1"].click()      # hidden, still works
        self.assertFalse(vm.strip[6].B1)
        window.on_hotkey(main.MUTE_HOTKEYS["Game"][0])
        self.assertTrue(vm.strip[5].mute)
        self.assertTrue(window.apply_profile("Main"))
        self.assertTrue(vm.strip[6].B1)
        self.assertFalse(vm.strip[5].mute)

    def test_each_view_remembers_its_own_size(self):
        window = self.window
        window.show()
        window.set_compact(True)
        self.assertIn("geometry_v2", FakeSettings.store)
        window.resize(600, 360)
        window.set_compact(False)
        self.assertIn("geometry_compact", FakeSettings.store)
        self.assertGreaterEqual(window.width(), main.WINDOW_MIN_SIZE[0])
        # (The test screen is smaller than the full window, so only the
        # compact size can be compared exactly.)
        window.set_compact(True)
        self.assertEqual((window.width(), window.height()), (600, 360))

    def test_starts_in_the_view_it_was_closed_in(self):
        self.window.set_compact(True)
        again = self.sandbox.window()
        self.addCleanup(self.sandbox.close, again)
        self.assertTrue(again.compact)
        self.assertTrue(again.compact_button.isChecked())
        self.assertTrue(again.strips["Game"].compact)

    def test_every_strip_has_both_routing_rows(self):
        vm = self.sandbox.vm
        for name, strip in self.window.strips.items():
            with self.subTest(name=name):
                self.assertEqual(
                    list(strip.route_buttons),
                    ["A1", "A2", "A3", "B1", "B2", "B3"],
                )
        self.window.strips["Game"].route_buttons["B1"].click()
        self.assertTrue(vm.strip[5].B1)

    def test_routing_buttons_use_the_bus_names_from_voicemeeter(self):
        vm = self.sandbox.vm
        self.assertEqual(main.route_name(vm, "A2"), ("A2", "A2 (hardware output 2)"))
        vm.bus[5].label = "Stream"
        self.assertEqual(
            main.route_name(vm, "B1"),
            ("Stream", "B1 \u2014 Stream (virtual output)"),
        )
        vm.bus[0].label = "Headphones Left"
        self.assertEqual(main.route_name(vm, "A1")[0], "Headpho\u2026")

    def test_mute_button_is_the_wide_one(self):
        self.window.resize(1000, 900)
        self.window.show()
        pump()
        strip = self.window.strips["Game"]
        self.assertGreater(
            strip.mute_button.width(), strip.solo_button.width() * 1.3
        )

    def test_fader_steps(self):
        fader = self.window.strips["Game"].fader
        self.assertEqual(
            (fader.wheel_step, fader.singleStep(), fader.pageStep()),
            (50, 10, 100),
        )
        self.assertTrue(self.window.strips["Mic"].fader.show_labels)
        self.assertFalse(fader.show_labels)

    def test_summary_and_tabs_show_the_processing_state(self):
        window = self.window
        window.update_processing_summary()
        self.assertEqual(
            window.processing_summary.text(),
            "Compressor: 3.1\nGate: 2.0\nDenoiser: 2.0",
        )
        self.assertEqual(window.processing_tabs.tabText(0), "COMPRESSOR")

        panel = window.compressor_control
        panel.bypass_button.setChecked(True)
        panel.on_bypass_clicked(True)
        window.denoiser_control._apply("knob", 0.0)
        window.update_processing_summary()
        self.assertEqual(
            window.processing_summary.text(),
            "Compressor: bypassed\nGate: 2.0\nDenoiser: off",
        )
        self.assertEqual(window.processing_tabs.tabText(0), "COMPRESSOR \u00b7 BYPASSED")
        self.assertEqual(window.processing_tabs.tabText(2), "DENOISER \u00b7 OFF")

        panel.bypass_button.setChecked(False)
        panel.on_bypass_clicked(False)
        window.update_processing_summary()
        self.assertEqual(window.processing_tabs.tabText(0), "COMPRESSOR")

    def test_start_button_on_the_offline_banner_connects(self):
        window, vm = self.window, self.sandbox.vm
        self.sandbox.running = False
        window.check_connection()
        self.assertFalse(window.connected)
        self.assertFalse(window.profile_panel.isEnabled())
        window.connect_vm()                 # what START VOICEMEETER does
        self.assertTrue(window.connected and vm.logged_in)
        self.assertTrue(window.offline_banner.isHidden())

    def test_hotkey_does_nothing_while_disconnected(self):
        self.sandbox.running = False
        self.window.check_connection()
        self.window.on_hotkey(main.HOTKEY_MIC_MUTE)
        self.assertFalse(self.sandbox.vm.strip[0].mute)

    def test_settings_defaults_and_storage(self):
        window = self.window
        current = window.current_settings()
        self.assertEqual(
            (current["mic_strip"], current["close_to_tray"], current["start_minimized"]),
            (0, True, False),
        )
        # Only the microphone's mute has a hotkey out of the box.
        hotkeys = {key: text for key, text in current.items() if key.startswith("hotkey_")}
        self.assertEqual(len(hotkeys), len(main.HOTKEYS))
        self.assertEqual(
            {key: text for key, text in hotkeys.items() if text},
            {"hotkey_mic_mute": "Ctrl+Shift+M"},
        )
        FakeSettings.store.update(mic_strip="2", close_to_tray="false", hotkey_mic_mute="")
        current = window.current_settings()
        self.assertEqual((current["mic_strip"], current["close_to_tray"], current["hotkey_mic_mute"]), (2, False, ""))

    def test_mic_input_setting_is_used_at_the_next_start(self):
        FakeSettings.store["mic_strip"] = 3
        again = self.sandbox.window()
        self.addCleanup(self.sandbox.close, again)
        self.assertEqual(again.strips["Mic"].strip_index, 3)
        self.assertIs(again.compressor_control.target, self.sandbox.vm.strip[3].comp)


class ProfileTest(unittest.TestCase):
    """A mixer profile holds gain, mute, solo, mono and routing of all strips."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)
        self.vm = self.sandbox.vm

    def mixer(self):
        state = {}
        for name, index in main.STRIPS.items():
            s = self.vm.strip[index]
            state[name] = (
                s.gain, s.mute, s.solo, s.mono,
                s.A1, s.A2, s.A3, s.B1, s.B2, s.B3,
            )
        return state

    def test_save_change_and_load_restores_the_mixer(self):
        window = self.window
        window.strips["Game"].fader.setValue(-1200)
        window.strips["Chat"].route_buttons["B1"].click()
        before = self.mixer()
        self.assertEqual(before["Game"][0], -12.0)
        self.assertTrue(window.save_profile("Streaming"))

        window.strips["Game"].fader.setValue(300)
        window.strips["Mic"].mute_button.click()
        window.strips["Chat"].route_buttons["B1"].click()
        window.strips["Media"].route_buttons["A1"].click()
        window.strips["Media"].mono_button.click()
        self.assertNotEqual(self.mixer(), before)

        self.assertTrue(window.apply_profile("Streaming"))
        self.assertEqual(self.mixer(), before)
        self.assertEqual(window.strips["Game"].gain_label.text(), "-12.00 dB")
        self.assertFalse(window.strips["Mic"].mute_button.isChecked())

    def test_load_always_says_what_it_did(self):
        window = self.window
        window.save_profile("Main")
        self.assertIn("Saved", window.profile_status.text())

        window.profile_load_button.click()
        self.assertEqual(
            window.profile_status.text(), "Already matches; nothing to change."
        )

        window.strips["Game"].fader.setValue(-600)
        window.strips["Media"].mute_button.click()
        window.profile_load_button.click()
        self.assertEqual(
            window.profile_status.text(),
            "Loaded. Changed: Game, Media.",
        )
        self.assertEqual(self.vm.strip[5].gain, 0.0)
        self.assertFalse(self.vm.strip[7].mute)

    def test_a_profile_brings_back_the_mic_processing_too(self):
        """Reported: after changing the compressor, LOAD on the main screen
        said everything matched. A profile is the whole setup."""
        window, mic = self.window, self.vm.strip[0]
        window.save_profile("Main")

        window.compressor_control.controls["knob"]["slider"].setValue(37)
        window.gate_control.controls["knob"]["slider"].setValue(29)
        self.assertEqual(mic.comp.threshold, -40.0)
        self.assertEqual(mic.gate.hold, 500.0)

        window.profile_load_button.click()
        self.assertEqual(compressor_state(self.vm), COMPRESSOR)
        self.assertEqual((mic.gate.knob, mic.gate.threshold, mic.gate.hold), (2.0, -38.0, 120.0))
        self.assertEqual(window.profile_status.text(), "Loaded. Changed: Mic processing.")
        self.assertEqual(
            window.processing_summary.text(),
            "Compressor: 3.1\nGate: 2.0\nDenoiser: 2.0",
        )
        self.assertTrue(window.compressor_control.amount_notice.isHidden())

    def test_a_profile_saved_without_processing_leaves_it_alone(self):
        window, mic = self.window, self.vm.strip[0]
        window.save_profile("Old")
        profiles = window.load_profiles()
        del profiles["Old"]["processing"]          # as saved by v1.3.0
        window.store_profiles(profiles)
        self.assertFalse(window.profile_has_processing("Old"))

        window.compressor_control.controls["knob"]["slider"].setValue(37)
        window.strips["Game"].fader.setValue(-600)
        self.assertTrue(window.apply_profile("Old"))
        self.assertEqual(self.vm.strip[5].gain, 0.0)
        self.assertEqual(mic.comp.knob, 3.7, "processing untouched")
        self.assertEqual(window.profile_status.text(), "Loaded. Changed: Game.")

        window.save_profile("Old")                 # saving again adds it
        self.assertTrue(window.profile_has_processing("Old"))

    def settle(self):
        """What the short timers do: drop the LOAD/SAVE message, re-check."""
        self.window._profile_message_until = 0.0
        self.window.refresh_profile_state()

    def test_shows_when_the_mixer_moves_away_from_the_profile(self):
        window = self.window
        self.assertEqual(window.profile_status.text(), main.PROFILE_HOLDS)
        self.assertTrue(window.profile_update_button.isHidden())

        window.save_profile("Main")
        self.settle()
        self.assertEqual(window.profile_status.text(), "Main is loaded.")
        self.assertTrue(window.profile_update_button.isHidden())

        window.strips["Game"].fader.setValue(-600)
        self.settle()
        self.assertEqual(window.profile_status.text(), "Main: changed")
        self.assertFalse(window.profile_update_button.isHidden())

        window.profile_load_button.click()
        self.settle()
        self.assertEqual(window.profile_status.text(), "Main is loaded.")
        self.assertTrue(window.profile_update_button.isHidden())

    def test_loading_a_voice_preset_marks_the_profile_as_changed(self):
        """The reported confusion: a preset and a profile, both called Main."""
        window = self.window
        window.save_profile("Main")
        window.compressor_control._apply("threshold", -30.0)
        window.save_preset("Loud")
        window.apply_profile("Main")
        self.settle()
        self.assertFalse(window.profile_is_changed())

        window.apply_preset("Loud")
        self.settle()
        self.assertEqual(window.profile_status.text(), "Main: changed")

    def test_update_saves_the_current_mixer_into_the_profile(self):
        window = self.window
        window.save_profile("Main")
        window.strips["Game"].fader.setValue(-600)
        window.gate_control._apply("hold", 250.0)
        self.settle()
        self.assertTrue(window.profile_is_changed())

        window.profile_update_button.click()
        self.settle()
        self.assertFalse(window.profile_is_changed())
        stored = window.load_profiles()["Main"]
        self.assertEqual(stored["Game"]["gain"], -6.0)
        self.assertEqual(stored["processing"]["gate"]["values"]["hold"], 250.0)

    def test_bypass_is_not_a_change_to_the_profile(self):
        window = self.window
        window.save_profile("Main")
        panel = window.compressor_control
        panel.bypass_button.setChecked(True)
        panel.on_bypass_clicked(True)
        self.settle()
        self.assertFalse(window.profile_is_changed())

    def test_an_older_profile_is_not_changed_by_the_processing(self):
        window = self.window
        window.save_profile("Old")
        profiles = window.load_profiles()
        del profiles["Old"]["processing"]
        window.store_profiles(profiles)
        window.apply_profile("Old")
        window.compressor_control._apply("threshold", -30.0)
        self.settle()
        self.assertFalse(window.profile_is_changed())
        window.strips["Chat"].mute_button.click()
        self.settle()
        self.assertTrue(window.profile_is_changed())

    def test_the_loaded_profile_is_remembered_after_a_restart(self):
        self.window.save_profile("Main")
        self.vm.strip[5].gain = -9.0            # changed while FaderDeck was off
        again = self.sandbox.window()
        self.addCleanup(self.sandbox.close, again)
        self.assertEqual(again.active_profile, "Main")
        self.assertEqual(again.profile_list.currentText(), "Main")
        self.assertEqual(again.profile_status.text(), "Main: changed")

    def test_deleting_the_loaded_profile_clears_the_state(self):
        window = self.window
        window.save_profile("Main")
        window.delete_profile("Main")
        self.settle()
        self.assertEqual(window.active_profile, "")
        self.assertEqual(window.profile_status.text(), main.PROFILE_HOLDS)

    def test_numbers_are_compared_the_way_voicemeeter_returns_them(self):
        match = main.profile_states_match
        self.assertTrue(match({"gain": 3.1, "mute": False}, {"gain": 3.0999999046, "mute": 0}))
        self.assertFalse(match({"gain": 3.1}, {"gain": 3.2}))
        self.assertFalse(match({"routes": {"A1": True}}, {"routes": {}}))
        self.assertTrue(match({"Mic": {"gain": 0.0}}, {"Mic": {"gain": 0.0, "extra": 1}, "processing": {}}))

    def test_profiles_are_stored_and_deleted(self):
        window = self.window
        window.save_profile("Streaming")
        window.save_profile(" Gaming ")
        stored = json.loads(FakeSettings.store["mixer_profiles"])
        self.assertEqual(sorted(stored), ["Gaming", "Streaming"])
        self.assertEqual(
            sorted(stored["Gaming"]),
            ["Chat", "Game", "Media", "Mic", "processing"],
        )
        self.assertTrue(window.delete_profile("Gaming"))
        self.assertFalse(window.delete_profile("Gaming"))
        self.assertFalse(window.save_profile("  "))

    def test_damaged_and_unknown_profiles_do_no_harm(self):
        window = self.window
        before = self.mixer()
        self.assertFalse(window.apply_profile("Nope"))
        FakeSettings.store["mixer_profiles"] = "not json"
        self.assertEqual(window.load_profiles(), {})
        FakeSettings.store["mixer_profiles"] = json.dumps({
            "Wild": {
                "Mic": "nonsense",
                "Game": {"gain": "loud"},
                "Chat": {"gain": 999, "mute": 0, "solo": 0, "mono": 0},
            }
        })
        self.assertFalse(window.apply_profile("Wild"))
        after = self.mixer()
        self.assertEqual(after["Mic"], before["Mic"])
        self.assertEqual(after["Game"], before["Game"])
        self.assertEqual(after["Chat"][0], 12.0, "kept inside the fader range")

    def test_not_applied_while_disconnected(self):
        window = self.window
        window.save_profile("Streaming")
        self.sandbox.running = False
        window.check_connection()
        self.assertFalse(window.apply_profile("Streaming"))


class PresetTest(unittest.TestCase):
    """One preset holds the compressor, gate and denoiser together."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)
        self.mic = self.sandbox.vm.strip[0]

    def test_save_change_and_load_restores_all_blocks(self):
        window, mic = self.window, self.mic
        self.assertTrue(window.save_preset("Stream"))

        window.compressor_control.controls["knob"]["slider"].setValue(80)
        window.gate_control._apply("hold", 900.0)
        window.denoiser_control._apply("knob", 7.0)
        mic.comp.makeup = False
        self.assertNotEqual(compressor_state(self.sandbox.vm), COMPRESSOR)

        self.assertTrue(window.apply_preset("Stream"))
        self.assertEqual(compressor_state(self.sandbox.vm), COMPRESSOR)
        self.assertEqual(mic.gate.hold, 120.0)
        self.assertEqual(mic.gate.knob, 2.0)
        self.assertEqual(mic.denoiser.knob, 2.0)
        self.assertEqual(
            window.gate_control.controls["hold"]["edit"].text(), "120.0 ms"
        )

    def test_amount_is_left_alone_when_it_is_already_right(self):
        """Touching Amount makes VoiceMeeter rewrite the other values, which
        shows on screen and is heard, so it is only written when it differs."""
        window, comp = self.window, self.mic.comp
        window.save_preset("Stream")
        window.compressor_control._apply("threshold", -30.0)
        comp.__dict__["knob_writes"] = 0

        self.assertTrue(window.apply_preset("Stream"))
        self.assertEqual(comp.knob_writes, 0)
        self.assertEqual(comp.threshold, -18.0)

    def test_in_between_values_are_not_shown_while_loading(self):
        window, comp = self.window, self.mic.comp
        panel = window.compressor_control
        window.save_preset("Stream")
        window.apply_preset("Stream")

        comp.release = 0.0                  # VoiceMeeter mid-change
        panel.sync_from_voicemeeter()       # the change event that follows
        self.assertEqual(panel.controls["release"]["edit"].text(), "150.0 ms")

        comp.release = 150.0                # settled
        pump(0.9)
        panel.sync_from_voicemeeter()
        self.assertEqual(panel.controls["release"]["edit"].text(), "150.0 ms")
        comp.release = 80.0                 # a later change is shown again
        panel.sync_from_voicemeeter()
        self.assertEqual(panel.controls["release"]["edit"].text(), "80.0 ms")

    def test_ticks_point_at_the_loaded_preset(self):
        """Reported: after LOAD the sliders did not sit on their ticks, which
        read as "not loaded". The ticks mark what RESET returns to, and that
        is the preset once one has been loaded."""
        window = self.window
        panel = window.gate_control
        window.save_preset("Main")
        panel.controls["knob"]["slider"].setValue(29)   # VoiceMeeter's preset values
        panel.take_snapshot()                           # window opened like this
        self.assertNotEqual(
            panel.controls["hold"]["slider"]._mark,
            panel._to_slider("hold", 120.0),
        )

        window.apply_preset("Main")
        for key in ("knob", "threshold", "hold", "release"):
            with self.subTest(key=key):
                slider = panel.controls[key]["slider"]
                self.assertEqual(slider._mark, slider.value())

        panel._apply("hold", 700.0)
        panel.reset()
        self.assertEqual(self.mic.gate.hold, 120.0, "RESET returns to the preset")

    def test_presets_are_stored_as_json_and_can_be_deleted(self):
        window = self.window
        window.save_preset("  Stream  ")
        window.save_preset("Recording")
        stored = json.loads(FakeSettings.store["processing_presets"])
        self.assertEqual(sorted(stored), ["Recording", "Stream"])
        self.assertEqual(sorted(stored["Stream"]), ["compressor", "denoiser", "gate"])
        self.assertEqual(stored["Stream"]["compressor"]["values"]["threshold"], -18.0)

        self.assertTrue(window.delete_preset("Stream"))
        self.assertFalse(window.delete_preset("Stream"))
        self.assertEqual(list(window.load_presets()), ["Recording"])

    def test_empty_name_and_unknown_preset_are_refused(self):
        self.assertFalse(self.window.save_preset("   "))
        self.assertFalse(self.window.apply_preset("Nope"))

    def test_saving_while_bypassed_stores_the_real_values(self):
        window = self.window
        panel = window.compressor_control
        panel.bypass_button.setChecked(True)
        panel.on_bypass_clicked(True)
        self.assertEqual(self.mic.comp.knob, 0.0)

        window.save_preset("Stream")
        values = window.load_presets()["Stream"]["compressor"]["values"]
        self.assertEqual(values["knob"], 3.1)
        self.assertEqual(values["threshold"], -18.0)

    def test_loading_ends_a_bypass(self):
        window = self.window
        window.save_preset("Stream")
        panel = window.compressor_control
        panel.bypass_button.setChecked(True)
        panel.on_bypass_clicked(True)
        self.assertTrue(window.apply_preset("Stream"))
        self.assertFalse(panel.bypass_button.isChecked())
        self.assertEqual(compressor_state(self.sandbox.vm), COMPRESSOR)

    def test_damaged_presets_do_no_harm(self):
        window = self.window
        FakeSettings.store["processing_presets"] = "not json"
        self.assertEqual(window.load_presets(), {})

        FakeSettings.store["processing_presets"] = json.dumps({
            "Wild": {
                "compressor": {"values": {"knob": 99, "threshold": -500, "bogus": 1}},
                "gate": {"values": {"threshold": -38}},      # no Amount
                "denoiser": "nonsense",
            }
        })
        self.assertFalse(window.apply_preset("Wild"), "two blocks are unusable")
        self.assertEqual(self.mic.comp.knob, 10.0, "kept inside the range")
        self.assertEqual(self.mic.comp.threshold, -40.0)
        self.assertEqual(self.mic.gate.knob, 2.0, "an unusable block is left alone")
        self.assertEqual(self.mic.denoiser.knob, 2.0)

    def test_not_applied_while_disconnected(self):
        window = self.window
        window.save_preset("Stream")
        self.sandbox.running = False
        window.check_connection()
        self.assertFalse(window.apply_preset("Stream"))


class RenameTest(unittest.TestCase):
    """The program was VMStreamer up to v1.4.0. Nothing the user saved may be
    lost by the new name."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)

    def open(self):
        window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, window)
        return window

    def test_settings_saved_under_the_old_name_are_taken_over(self):
        FakeSettings.old_store.update({
            "hotkey_mic_mute": "Ctrl+Alt+M",
            "close_to_tray": "false",
            "mic_strip": 2,
            "mixer_profiles": json.dumps({"Main": {"Game": {"gain": -6.0, "mute": False, "solo": False, "mono": False}}}),
            "processing_presets": json.dumps({"Voice": {}}),
            "hidden_applications_v2": json.dumps(["game|steam.exe"]),
            "active_profile": "Main",
        })
        before = dict(FakeSettings.old_store)
        window = self.open()

        current = window.current_settings()
        self.assertEqual(current["hotkey_mic_mute"], "Ctrl+Alt+M")
        self.assertFalse(current["close_to_tray"])
        self.assertEqual(window.strips["Mic"].strip_index, 2)
        self.assertEqual(list(window.load_profiles()), ["Main"])
        self.assertEqual(list(window.load_presets()), ["Voice"])
        self.assertEqual(window.active_profile, "Main")
        self.assertEqual(FakeSettings.store["migrated_from"], "VMStreamer")
        self.assertEqual(FakeSettings.old_store, before, "the old settings stay as they were")

    def test_the_copy_happens_once_only(self):
        FakeSettings.old_store["hotkey_mic_mute"] = "Ctrl+Alt+M"
        first = self.open()
        first.window_settings.setValue("hotkey_mic_mute", "Ctrl+Alt+N")
        FakeSettings.old_store["hotkey_mic_mute"] = "Ctrl+Alt+OLD"   # old program still in use

        again = self.open()
        self.assertEqual(again.current_settings()["hotkey_mic_mute"], "Ctrl+Alt+N")

    def test_a_fresh_installation_starts_with_the_defaults(self):
        window = self.open()
        self.assertEqual(window.current_settings()["hotkey_mic_mute"], "Ctrl+Shift+M")
        self.assertEqual(FakeSettings.store["migrated_from"], "")

    def test_both_program_names_are_left_out_of_the_application_list(self):
        self.assertIn("faderdeck.exe", main.OWN_EXECUTABLES)
        self.assertIn("vmstreamer.exe", main.OWN_EXECUTABLES)

    def test_names_shown_to_the_user(self):
        window = self.open()
        self.assertEqual(window.windowTitle(), "FaderDeck")
        self.assertEqual(main.SETTINGS_NAME, "FaderDeck")
        self.assertTrue(main.log_file_path().endswith("faderdeck.log"))
        self.assertIn("FaderDeck", main.SINGLE_INSTANCE_NAME)


class CloseToTrayTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        # Qt's offscreen platform has no tray; say it has, so the tray code runs.
        self.saved = main.QSystemTrayIcon.isSystemTrayAvailable
        main.QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
        self.addCleanup(setattr, main.QSystemTrayIcon, "isSystemTrayAvailable", self.saved)
        FakeSettings.store["tray_hint_shown"] = True
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)
        self.window.show()

    def test_close_hides_and_keeps_running(self):
        window = self.window
        window.close()
        self.assertFalse(window.isVisible())
        self.assertTrue(window.connected)
        self.assertIsNotNone(window.mic_level_thread)
        window.on_tray_activated(main.QSystemTrayIcon.ActivationReason.Trigger)
        self.assertTrue(window.isVisible())

    def test_quit_from_the_tray_really_quits(self):
        window = self.window
        window.quit_application()
        pump()
        self.assertFalse(window.connected)
        self.assertIsNone(window.vm)
        self.assertFalse(self.sandbox.vm.logged_in)

    def test_closing_with_shift_held_quits_instead_of_hiding(self):
        window = self.window
        window.shift_is_held = lambda: True
        window.close()
        pump()
        self.assertFalse(window.connected)
        self.assertFalse(self.sandbox.vm.logged_in, "a proper quit logs out")

    def test_closing_without_shift_still_hides(self):
        window = self.window
        window.shift_is_held = lambda: False
        window.close()
        self.assertFalse(window.isVisible())
        self.assertTrue(window.connected)

    def test_setting_off_means_close_quits(self):
        FakeSettings.store["close_to_tray"] = False
        self.window.close()
        pump()
        self.assertFalse(self.window.connected)

    def test_windows_shutdown_is_not_answered_by_hiding(self):
        self.window.prepare_to_quit()
        self.window.close()
        pump()
        self.assertFalse(self.window.connected)

    def test_a_second_start_shows_the_hidden_window(self):
        window = self.window
        window.close()
        self.assertFalse(window.isVisible())
        # What the native event filter does when the request arrives.
        window.hotkey_filter.show_callback()
        self.assertTrue(window.isVisible())

    def test_quit_request_from_a_script_really_quits(self):
        """`FaderDeck.exe --quit` reaches the running program as a message."""
        window = self.window
        window.close()                      # hidden in the tray
        self.assertTrue(window.connected)
        window.hotkey_filter.quit_callback()
        pump()
        self.assertFalse(window.connected)
        self.assertFalse(self.sandbox.vm.logged_in)

    def test_tray_shows_the_mute_state(self):
        window = self.window
        window.toggle_mic_mute()
        self.assertTrue(window.tray_mute_action.isChecked())
        self.assertIn("muted", window.tray.toolTip())
        window.toggle_mic_mute()
        self.assertFalse(window.tray_mute_action.isChecked())


if __name__ == "__main__":
    unittest.main()
