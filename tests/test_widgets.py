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
        self.assertEqual(window.current_settings(), {
            "mic_strip": 0,
            "hotkey_mic_mute": "Ctrl+Shift+M",
            "hotkey_game_mute": "",
            "hotkey_chat_mute": "",
            "hotkey_media_mute": "",
            "close_to_tray": True,
            "start_minimized": False,
        })
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

    def test_profiles_are_stored_and_deleted(self):
        window = self.window
        window.save_profile("Streaming")
        window.save_profile(" Gaming ")
        stored = json.loads(FakeSettings.store["mixer_profiles"])
        self.assertEqual(sorted(stored), ["Gaming", "Streaming"])
        self.assertEqual(sorted(stored["Gaming"]), ["Chat", "Game", "Media", "Mic"])
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
        """`VMStreamer.exe --quit` reaches the running program as a message."""
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
