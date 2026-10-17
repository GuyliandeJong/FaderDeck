"""The local API: what it does, and who it refuses."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from fakes import FakeSettings, Sandbox, main, pump
import web

TOKEN = "test-token"


class ApiLogicTest(unittest.TestCase):
    """handle_api_call, without a network in between."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)
        self.vm = self.sandbox.vm

    def call(self, method, path, **params):
        parts = [part for part in path.split("/") if part]
        return self.window.handle_api_call(method, parts, params)

    def test_state(self):
        status, body = self.call("GET", "state")
        self.assertEqual(status, 200)
        self.assertTrue(body["connected"])
        self.assertEqual(sorted(body["channels"]), ["Chat", "Game", "Media", "Mic"])
        self.assertEqual(body["channels"]["Mic"]["mute"], False)
        json.dumps(body)                    # must be plain data

    def test_mute(self):
        mic = self.vm.strip[0]
        self.assertEqual(self.call("POST", "mute/mic"), (200, {"channel": "Mic", "mute": True}))
        self.assertTrue(mic.mute)
        self.assertEqual(self.call("POST", "mute/MIC", state="on")[1]["mute"], True)
        self.assertEqual(self.call("POST", "mute/Mic", state="off")[1]["mute"], False)
        self.assertFalse(mic.mute)
        self.assertEqual(self.call("POST", "mute/mic", state="maybe")[0], 400)
        self.assertEqual(self.call("POST", "mute/drums")[0], 404)

    def test_gain(self):
        game = self.vm.strip[5]
        self.assertEqual(self.call("POST", "gain/game", db="-6")[1], {"channel": "Game", "gain": -6.0})
        self.assertEqual(game.gain, -6.0)
        self.assertEqual(self.call("POST", "gain/game", step="1.5")[1]["gain"], -4.5)
        self.assertEqual(self.call("POST", "gain/game", db="999")[1]["gain"], 12.0, "clamped")
        for bad in ({"db": "loud"}, {"db": "nan"}, {"step": "inf"}, {}):
            self.assertEqual(self.call("POST", "gain/game", **bad)[0], 400)
        self.assertEqual(game.gain, 12.0)

    def test_profiles(self):
        window, game = self.window, self.vm.strip[5]
        for name, gain in (("Alpha", -300), ("Beta", -600)):
            window.strips["Game"].fader.setValue(gain)
            window.save_profile(name)
        self.assertEqual(
            self.call("GET", "profiles"),
            (200, {"profiles": ["Alpha", "Beta"], "active": "Beta"}),
        )
        self.assertEqual(self.call("POST", "profile/Alpha")[1], {"profile": "Alpha", "applied": True})
        self.assertEqual(game.gain, -3.0)
        self.assertEqual(self.call("POST", "profile", step="next")[1]["profile"], "Beta")
        self.assertEqual(self.call("POST", "profile", step="previous")[1]["profile"], "Alpha")
        self.assertEqual(self.call("POST", "profile/Nope")[0], 404)
        self.assertEqual(self.call("POST", "profile", step="sideways")[0], 400)

    def test_reading_and_changing_use_different_methods(self):
        self.assertEqual(self.call("POST", "state")[0], 405)
        self.assertEqual(self.call("GET", "mute/mic")[0], 405)
        self.assertFalse(self.vm.strip[0].mute, "a GET must never change anything")
        self.assertEqual(self.call("GET", "profile/Alpha")[0], 405)

    def test_unknown_addresses(self):
        for path in ("", "nothing", "mute", "mute/mic/extra", "profile/a/b"):
            with self.subTest(path=path):
                self.assertEqual(self.call("POST", path)[0], 404)

    def test_changes_are_refused_while_disconnected(self):
        self.sandbox.running = False
        self.window.check_connection()
        self.assertEqual(self.call("POST", "mute/mic")[0], 409)
        self.assertEqual(self.call("GET", "state")[1]["connected"], False)

    def test_off_by_default(self):
        self.assertIsNone(self.window.local_api.server)
        self.assertFalse(self.window.current_settings()["api_enabled"])


class PhoneRemoteTest(unittest.TestCase):
    """The phone remote, on the loopback interface so no firewall asks."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)
        self.remote = self.window.phone_remote
        self.remote.start(0, [], host="127.0.0.1")
        self.addCleanup(self.remote.stop)

    def request(self, method, path, token=None, body=None, headers=None):
        url = f"http://127.0.0.1:{self.remote.port}{path}"
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        request = urllib.request.Request(url, method=method, data=data)
        if token:
            request.add_header(web.API_TOKEN_HEADER, token)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        result = {}

        def send():
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    result["status"], result["type"] = response.status, response.headers["Content-Type"]
                    result["body"] = response.read()
            except urllib.error.HTTPError as error:
                with error:
                    result["status"], result["type"] = error.code, error.headers["Content-Type"]
                    result["body"] = error.read()
            except Exception as error:      # noqa: BLE001 - reported below
                result["error"] = error

        thread = threading.Thread(target=send)
        thread.start()
        while thread.is_alive():
            pump(0.01)
        thread.join()
        self.assertNotIn("error", result, result.get("error"))
        return result

    def pair(self, code):
        result = self.request("POST", "/remote/pair", body={"code": code})
        return result["status"], json.loads(result["body"])

    def test_the_page_and_icons_need_no_token(self):
        page = self.request("GET", "/remote")
        self.assertEqual(page["status"], 200)
        self.assertIn(b"FaderDeck", page["body"])
        self.assertTrue(page["type"].startswith("text/html"))
        icon = self.request("GET", "/remote/icon-192.png")
        self.assertEqual(icon["body"][:4], b"\x89PNG")

    def test_the_page_knows_its_version_so_it_can_reload(self):
        page = self.request("GET", "/remote")["body"].decode()
        version = self.window.remote_page_version
        self.assertIn(f'PAGE_VERSION = "{version}"', page)
        self.assertEqual(self.window.api_state()["page"], version)

    def test_unpaired_devices_are_refused(self):
        result = self.request("GET", "/remote/api/state", token="made-up")
        self.assertEqual(result["status"], 401)

    def test_pairing_gives_a_token_that_works_once_per_code(self):
        self.assertEqual(self.pair("123456")[0], 403)  # no code was shown
        code = self.remote.new_code()
        status, body = self.pair(code)
        self.assertEqual(status, 200)
        token = body["token"]
        self.assertEqual(self.pair(code)[0], 403, "a code pairs one device")
        state = self.request("GET", "/remote/api/state", token=token)
        self.assertEqual(state["status"], 200)
        self.assertIn("Mic", json.loads(state["body"])["names"])
        mute = self.request("POST", "/remote/api/mute/mic?state=on", token=token)
        self.assertEqual(json.loads(mute["body"]), {"channel": "Mic", "mute": True})
        stored = json.loads(self.window.window_settings.value("remote_devices"))
        self.assertEqual(stored, [web.token_hash(token)])
        self.assertNotIn(token, self.window.window_settings.value("remote_devices"))

    def test_guessing_ends_the_code(self):
        code = self.remote.new_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(web.REMOTE_PAIR_TRIES):
            self.assertEqual(self.pair(wrong)[0], 403)
        self.assertEqual(self.pair(code)[0], 403, "too many guesses")

    def test_settings_keep_a_device_paired_while_open_and_forget_on_request(self):
        # OK restarts the remote on every network; keep this one as it is.
        self.window.restart_phone_remote = lambda: ""
        # and do not touch the real hotkeys: a refusal would open a message box.
        self.window.register_hotkeys = lambda: []
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        token = self.pair(self.remote.new_code())[1]["token"]
        pump()
        self.assertIn("1 device paired", dialog.remote_count.text())
        self.window.apply_settings(dialog.values())   # OK
        state = self.request("GET", "/remote/api/state", token=token)
        self.assertNotEqual(state["status"], 401, "OK must not unpair the phone")
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        self.assertIn("1 device paired", dialog.remote_count.text())
        dialog.forget_devices()
        self.window.apply_settings(dialog.values())
        self.assertEqual(self.window.remote_devices_setting(), [])

    def test_ok_keeps_a_running_remote_running(self):
        self.window.register_hotkeys = lambda: []
        self.window.window_settings.setValue("remote_enabled", True)
        self.window.window_settings.setValue("remote_port", self.remote.port)
        server = self.remote.server
        dialog = main.SettingsDialog(self.window, self.window.current_settings())
        self.window.apply_settings(dialog.values())
        self.assertIs(self.remote.server, server)

    def test_other_sites_cannot_use_a_paired_token(self):
        code = self.remote.new_code()
        token = self.pair(code)[1]["token"]
        result = self.request("POST", "/remote/api/mute/mic", token=token,
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(result["status"], 403)


class ApiServerTest(unittest.TestCase):
    """The real server on the loopback interface."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__)
        FakeSettings.store.update(api_enabled=True, api_port=0, api_token=TOKEN)
        self.window = self.sandbox.window()
        self.addCleanup(self.sandbox.close, self.window)
        self.port = self.window.local_api.port
        self.assertTrue(self.port, "the API should be listening")

    def request(self, method, path, token=TOKEN, headers=None, host=None):
        """Send a request from another thread while the GUI thread answers."""
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
        if token is not None:
            request.add_header(web.API_TOKEN_HEADER, token)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if host:
            request.add_header("Host", host)
        result = {}

        def send():
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    result["status"] = response.status
                    result["body"] = json.loads(response.read())
            except urllib.error.HTTPError as error:
                with error:
                    result["status"] = error.code
                    result["body"] = json.loads(error.read())
            except Exception as error:      # noqa: BLE001 - reported below
                result["error"] = error

        thread = threading.Thread(target=send)
        thread.start()
        while thread.is_alive():
            pump(0.01)
        thread.join()
        self.assertNotIn("error", result, result.get("error"))
        return result["status"], result["body"]

    def test_a_request_with_the_token_works(self):
        status, body = self.request("POST", "/api/mute/mic")
        self.assertEqual((status, body), (200, {"channel": "Mic", "mute": True}))
        self.assertTrue(self.sandbox.vm.strip[0].mute)
        status, body = self.request("GET", "/api/state")
        self.assertEqual(body["channels"]["Mic"]["mute"], True)

    def test_token_may_be_given_in_the_address(self):
        status, _ = self.request("GET", f"/api/state?token={TOKEN}", token=None)
        self.assertEqual(status, 200)

    def test_without_or_with_a_wrong_token_nothing_happens(self):
        for token in (None, "", "wrong", TOKEN + "x"):
            with self.subTest(token=token):
                status, _ = self.request("POST", "/api/mute/mic", token=token)
                self.assertEqual(status, 401)
        self.assertFalse(self.sandbox.vm.strip[0].mute)

    def test_a_web_page_is_refused_even_with_the_token(self):
        status, _ = self.request(
            "POST", "/api/mute/mic", headers={"Origin": "https://example.com"}
        )
        self.assertEqual(status, 403)
        self.assertFalse(self.sandbox.vm.strip[0].mute)

    def test_another_host_name_is_refused(self):
        """A site that points its own name at 127.0.0.1 must not get in."""
        status, _ = self.request("POST", "/api/mute/mic", host=f"evil.example:{self.port}")
        self.assertEqual(status, 403)
        self.assertFalse(self.sandbox.vm.strip[0].mute)

    def test_addresses_outside_api_do_not_exist(self):
        self.assertEqual(self.request("GET", "/")[0], 404)
        self.assertEqual(self.request("GET", "/state")[0], 404)

    def test_listens_on_this_computer_only(self):
        self.assertEqual(self.window.local_api.server.server_address[0], "127.0.0.1")

    def test_switching_it_off_closes_the_port(self):
        FakeSettings.store["api_enabled"] = False
        self.assertEqual(self.window.restart_api(), "")
        self.assertIsNone(self.window.local_api.server)
        with self.assertRaises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/state", timeout=2)

    def test_the_port_cannot_be_shared(self):
        """Windows would let a second program listen on the same port and
        receive the token; the server must refuse to share."""
        intruder = main.LocalApi()
        self.addCleanup(intruder.stop)
        with self.assertRaises(OSError):
            intruder.start(self.port, "intruder")

    def test_a_port_in_use_is_reported_not_fatal(self):
        FakeSettings.store["api_port"] = self.port
        other = main.LocalApi()
        self.addCleanup(other.stop)
        self.window.local_api.stop()
        other.start(self.port, "other")
        problem = self.window.restart_api()
        self.assertIn(str(self.port), problem)
        self.assertIsNone(self.window.local_api.server)

    def test_quitting_stops_the_server(self):
        self.sandbox.close(self.window)
        self.assertIsNone(self.window.local_api.server)


if __name__ == "__main__":
    unittest.main()
