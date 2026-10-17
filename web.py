"""The local API for scripts and the Stream Deck, the phone remote, and
the Windows Firewall rule the phone remote needs."""

import sys
import concurrent.futures
import ctypes
import ctypes.wintypes
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from PySide6.QtCore import (
    Qt,
    Signal,
    QObject,
    QRectF,
    QBuffer,
    QIODevice,
    QByteArray,
)
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from core import log
from themes import LOGO_SVG


# Local API: lets other programs on this PC (a Stream Deck plugin, an OBS
# script, curl) control FaderDeck over HTTP. Off unless switched on in the
# settings window.
API_DEFAULT_PORT = 8765
API_TOKEN_HEADER = "X-FaderDeck-Token"


class ApiCall:
    """One request, handed from the server thread to the GUI thread."""

    def __init__(self, method, parts, params):
        self.method = method
        self.parts = parts
        self.params = params
        self.future = concurrent.futures.Future()


class ApiServer(ThreadingHTTPServer):
    """HTTP server that insists on having its port to itself.

    The standard server sets SO_REUSEADDR, which on Windows lets a second
    program listen on the same port and take the requests. The token would
    then be sent to that program.
    """

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class HttpService(QObject):
    """A small HTTP server on a thread of its own. A subclass answers the
    requests in serve(handler, method); they come in on server threads and
    reach the GUI thread through call_requested."""

    call_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = None
        self.thread = None
        self.port = 0

    def listen(self, host, port, name):
        """Start serving. Raises OSError when the port cannot be used."""
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FaderDeck"

            def log_message(self, *args):
                pass

            def do_GET(self):
                service.serve(self, "GET")

            def do_POST(self):
                service.serve(self, "POST")

        self.server = ApiServer((host, int(port)), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.1},  # stop() then returns quickly
            name=name,
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        server, thread = self.server, self.thread
        self.server = self.thread = None
        self.port = 0
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=1.0)


class LocalApi(HttpService):
    """A small HTTP server that is reachable from this computer only.

    It listens on 127.0.0.1, so nothing on the network can connect. Every
    request needs the token from the settings window. Requests coming from a
    web page (they carry an Origin header) and requests addressed to any
    other host name are refused, so a site open in a browser cannot reach
    the mixer either.

    Requests arrive on server threads. They are passed to the GUI thread
    through call_requested and wait there for the answer; nothing in this
    class touches a widget or VoiceMeeter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = ""

    def start(self, port, token):
        """Start listening. Raises OSError when the port cannot be used."""
        self.stop()
        self.token = token
        self.listen("127.0.0.1", port, "FaderDeck-LocalApi")

    def serve(self, handler, method):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            if length:
                handler.rfile.read(min(length, 65536))
            status, body = self.answer(handler, method)
        except Exception as e:
            log.error(f"Local API request failed: {type(e).__name__}: {e}")
            status, body = 500, {"error": "Internal error."}
        data = json.dumps(body).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)

    def answer(self, handler, method):
        url = urlsplit(handler.path)
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}

        if handler.headers.get("Origin"):
            return 403, {"error": "Requests from web pages are not accepted."}
        host = (handler.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if host not in ("127.0.0.1", "localhost"):
            return 403, {"error": "Only 127.0.0.1 and localhost are accepted."}

        supplied = (
            handler.headers.get(API_TOKEN_HEADER)
            or params.pop("token", "")
        )
        if not self.token or not hmac.compare_digest(
            supplied.encode("utf-8"), self.token.encode("utf-8")
        ):
            return 401, {"error": "Missing or wrong token."}

        parts = [unquote(part) for part in url.path.split("/") if part]
        if not parts or parts[0] != "api":
            return 404, {"error": "Unknown address."}

        call = ApiCall(method, parts[1:], params)
        self.call_requested.emit(call)
        try:
            return call.future.result(timeout=3.0)
        except Exception:
            return 503, {"error": "FaderDeck did not answer in time."}


# The phone and tablet remote: a web page that FaderDeck serves on the home
# network, separate from the local API above, which stays on 127.0.0.1. A
# device pairs once with a short code shown in Settings and then sends its
# own token with every request. Only the hash of a token is kept.
REMOTE_DEFAULT_PORT = 8766
REMOTE_PAGE = "remote.html"
REMOTE_PAIR_SECONDS = 120
REMOTE_PAIR_TRIES = 5


def lan_address():
    """This PC's address on the home network, or an empty string."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # sends nothing
            return probe.getsockname()[0]
    except OSError:
        return ""


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def remote_manifest():
    return json.dumps({
        "name": "FaderDeck",
        "short_name": "FaderDeck",
        "start_url": "/remote",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "icons": [
            {"src": "/remote/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/remote/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }).encode("utf-8")


def logo_png(size):
    """The logo as PNG bytes. Call on the GUI thread."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(LOGO_SVG.encode("utf-8"))).render(
        painter, QRectF(0, 0, size, size)
    )
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


class PhoneRemote(HttpService):
    """Serves the remote page and its requests to devices on the home network.

    Like LocalApi, requests are answered on the GUI thread through
    call_requested; a newly paired device is announced through paired.
    """

    paired = Signal(str)  # the hash of a new device token

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files  # path -> (content type, bytes)
        self.devices = set()
        self.lock = threading.Lock()
        self.code = ""
        self.code_until = 0.0
        self.tries = 0

    def start(self, port, devices, host="0.0.0.0"):
        """Start listening on every network. Raises OSError on a busy port."""
        self.stop()
        with self.lock:
            self.devices = set(devices)
        self.listen(host, port, "FaderDeck-PhoneRemote")

    def set_devices(self, devices):
        with self.lock:
            self.devices = set(devices)

    def new_code(self):
        """A fresh six-digit pairing code, valid for a short while."""
        with self.lock:
            self.code = f"{secrets.randbelow(10 ** 6):06d}"
            self.code_until = time.monotonic() + REMOTE_PAIR_SECONDS
            self.tries = 0
            return self.code

    def pair(self, code):
        """A new device token for the right code, or None."""
        with self.lock:
            if not self.code or time.monotonic() > self.code_until:
                return None
            self.tries += 1
            right = hmac.compare_digest(str(code).encode(), self.code.encode())
            if not right:
                if self.tries >= REMOTE_PAIR_TRIES:
                    self.code = ""  # too many guesses: ask for a new code
                return None
            self.code = ""  # one device per code
            token = secrets.token_urlsafe(24)
            self.devices.add(token_hash(token))
        self.paired.emit(token_hash(token))
        return token

    def serve(self, handler, method):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            body = handler.rfile.read(min(length, 65536)) if length else b""
            status, content_type, data = self.answer(handler, method, body)
        except Exception as e:
            log.error(f"Phone remote request failed: {type(e).__name__}: {e}")
            status, content_type, data = 500, "application/json", b'{"error": "Internal error."}'
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(data)

    @staticmethod
    def json_answer(status, body):
        return status, "application/json; charset=utf-8", json.dumps(body).encode("utf-8")

    def answer(self, handler, method, body):
        client = ipaddress.ip_address(handler.client_address[0])
        if not (client.is_private or client.is_loopback):
            return self.json_answer(403, {"error": "Only devices on your own network."})
        url = urlsplit(handler.path)
        path = url.path.rstrip("/") or "/"

        if method == "GET" and path in ("/", "/remote") or path in self.files:
            name = "/remote" if path == "/" else path
            if method != "GET" or name not in self.files:
                return self.json_answer(404, {"error": "Unknown address."})
            content_type, data = self.files[name]
            return 200, content_type, data

        # A page on another site must not drive the mixer from this browser.
        origin = handler.headers.get("Origin")
        if origin and urlsplit(origin).netloc != handler.headers.get("Host"):
            return self.json_answer(403, {"error": "Requests from other sites are not accepted."})

        if path == "/remote/pair" and method == "POST":
            try:
                code = str(json.loads(body or b"{}").get("code", "")).strip()
            except (ValueError, AttributeError):
                code = ""
            token = self.pair(code)
            if token is None:
                return self.json_answer(403, {
                    "error": "That code is wrong or has run out. Press \"Pair a "
                    "device\" in FaderDeck for a new one."})
            log.info(f"Phone remote: paired a device at {client}")
            return self.json_answer(200, {"token": token})

        supplied = handler.headers.get(API_TOKEN_HEADER, "")
        with self.lock:
            known = bool(supplied) and token_hash(supplied) in self.devices
        if not known:
            return self.json_answer(401, {"error": "This device is not paired."})

        parts = [unquote(part) for part in path.split("/") if part]
        if parts[:2] != ["remote", "api"]:
            return self.json_answer(404, {"error": "Unknown address."})
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}
        call = ApiCall(method, parts[2:], params)
        self.call_requested.emit(call)
        try:
            status, answer = call.future.result(timeout=3.0)
        except Exception:
            status, answer = 503, {"error": "FaderDeck did not answer in time."}
        return self.json_answer(status, answer)


# Windows Firewall blocks phones from reaching the remote until a rule
# allows it, and adding one needs administrator rights. FaderDeck asks Windows
# to run one PowerShell command as administrator (the user sees the usual
# prompt) that allows exactly this program, on the remote's port, on private
# networks only. Firewall rules are read through PowerShell objects, whose
# names do not change with the Windows language.
FIREWALL_RULE = "FaderDeck phone remote"


def firewall_program():
    """The program Windows sees listening: FaderDeck.exe, or the real Python
    behind a virtual environment when run from source."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return getattr(sys, "_base_executable", None) or sys.executable


def _powershell_text(value):
    return "'" + str(value).replace("'", "''") + "'"


def firewall_rule_command(program, port):
    """PowerShell that replaces FaderDeck's rule with one for this program
    and port, on private networks."""
    name = _powershell_text(FIREWALL_RULE)
    return (
        f"Remove-NetFirewallRule -DisplayName {name} -ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName {name} -Direction Inbound "
        f"-Program {_powershell_text(program)} -Protocol TCP "
        f"-LocalPort {int(port)} -Profile Private -Action Allow -ErrorAction Stop | Out-Null"
    )


def firewall_status_command():
    """PowerShell that prints 'program|port' of FaderDeck's rule, if any."""
    name = _powershell_text(FIREWALL_RULE)
    return (
        f"$r = Get-NetFirewallRule -DisplayName {name} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Allow' } | Select-Object -First 1; "
        "if ($r) { $a = $r | Get-NetFirewallApplicationFilter; "
        "$p = $r | Get-NetFirewallPortFilter; "
        "Write-Output ($a.Program + '|' + $p.LocalPort) }"
    )


def firewall_allows(program, port):
    """True when FaderDeck's rule lets this program in on this port, False
    when not, None when it could not be read. Takes a second: not on the
    GUI thread."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             firewall_status_command()],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = result.stdout.strip()
    if not found:
        return False
    rule_program, _, rule_port = found.rpartition("|")
    return (
        os.path.normcase(os.path.abspath(rule_program))
        == os.path.normcase(os.path.abspath(program))
        and rule_port.strip() == str(int(port))
    )


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.wintypes.LPCWSTR),
        ("lpFile", ctypes.wintypes.LPCWSTR),
        ("lpParameters", ctypes.wintypes.LPCWSTR),
        ("lpDirectory", ctypes.wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.wintypes.LPCWSTR),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


def run_powershell_as_admin(command):
    """Run a PowerShell command as administrator after Windows asks the user.

    Waits for it, so call it off the GUI thread. Returns its exit code, or
    None when the user said no to the prompt.
    """
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS: hand back the process
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = (
        "-NoProfile -NonInteractive -WindowStyle Hidden -Command "
        f"\"{command}; if (-not $?) {{ exit 1 }}\""
    )
    info.nShow = 0  # SW_HIDE
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return None  # declined, or Windows could not ask
    kernel32 = ctypes.windll.kernel32
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = ctypes.wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)
