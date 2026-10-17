"""Automatic updates: ask GitHub for the latest release, then download
and check its installer."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.request
import threading
from collections import namedtuple
from urllib.parse import urlsplit

from PySide6.QtCore import Signal, QObject

from core import log


# Updates. FaderDeck asks GitHub for its latest release. An update is that
# release's installer, checked against the SHA-256 that GitHub publishes for
# it before it runs.
APP_VERSION = "1.14.0"
UPDATE_URL = (
    "https://api.github.com/repos/GuyliandeJong/FaderDeck/releases/latest"
)
INSTALLER_ASSET = "FaderDeck-Setup.exe"
INSTALLER_OPTIONS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART")

Update = namedtuple("Update", "version url size sha256 page")


def version_tuple(text):
    """(1, 6, 0) for "v1.6.0"; () when the text is not a version."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(text or "").strip())
    if not match:
        return ()
    return tuple(int(part or 0) for part in match.groups())


def available_update(release, current=APP_VERSION):
    """The installer of a release newer than `current`, or None.

    `release` is GitHub's answer for the latest release. Without an
    installer, or without a SHA-256 to check it against, there is no update.
    """
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    version = version_tuple(release.get("tag_name"))
    if not version or version <= version_tuple(current):
        return None
    for asset in release.get("assets") or ():
        if not isinstance(asset, dict) or asset.get("name") != INSTALLER_ASSET:
            continue
        url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "").lower()
        if (
            urlsplit(url).scheme != "https"
            or urlsplit(url).hostname != "github.com"
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            return None
        return Update(
            ".".join(str(part) for part in version),
            url,
            int(asset.get("size") or 0),
            digest.split(":", 1)[1],
            str(release.get("html_url") or ""),
        )
    return None


def _open_url(url, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"FaderDeck/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_latest_release():
    with _open_url(UPDATE_URL, 10) as response:
        return json.loads(response.read().decode("utf-8"))


def installer_environment(environment=None):
    """The environment to start the installer with.

    A one-file PyInstaller program records its unpacked folder in its
    environment. The installer, and the FaderDeck it starts, would inherit
    that, and the new FaderDeck would look for its files in the folder this
    one deletes when it quits ("Failed to load Python DLL").
    """
    environment = dict(os.environ if environment is None else environment)
    for key in list(environment):
        if key.upper().startswith("_PYI_") or key.upper() == "_MEIPASS2":
            del environment[key]
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def remove_old_downloads():
    """Delete installers left from earlier updates."""
    folder = tempfile.gettempdir()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.startswith("faderdeck-update-"):
            shutil.rmtree(os.path.join(folder, name), ignore_errors=True)


def download_update(update, progress=lambda done, total: True):
    """Download the installer and check it. Returns its path.

    `progress` is called as the file comes in; returning False stops it.
    """
    folder = tempfile.mkdtemp(prefix="faderdeck-update-")
    path = os.path.join(folder, INSTALLER_ASSET)
    digest = hashlib.sha256()
    done = 0
    try:
        with _open_url(update.url, 30) as response, open(path, "wb") as handle:
            while chunk := response.read(256 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if not progress(done, update.size):
                    raise InterruptedError("The download was cancelled.")
        if digest.hexdigest() != update.sha256:
            raise ValueError(
                "The download does not match the release, so it was not "
                "installed. Try again later."
            )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return path


class UpdateChecker(QObject):
    """Checks for and downloads updates on a background thread."""

    found = Signal(object)  # Update
    latest = Signal()
    failed = Signal(str)
    progressed = Signal(int, int)
    downloaded = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.cancelled = False

    def _run(self, work):
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                work()
            except Exception as e:
                log.warning(f"Update failed: {type(e).__name__}: {e}")
                self.failed.emit(str(e) or type(e).__name__)
            finally:
                self.busy = False

        threading.Thread(target=run, name="FaderDeckUpdate", daemon=True).start()

    def check(self):
        def work():
            remove_old_downloads()
            update = available_update(fetch_latest_release())
            if update is None:
                self.latest.emit()
            else:
                log.info(f"Update available: {update.version}")
                self.found.emit(update)

        self._run(work)

    def download(self, update):
        self.cancelled = False

        def progress(done, total):
            self.progressed.emit(done, total)
            return not self.cancelled

        self._run(lambda: self.downloaded.emit(download_update(update, progress)))
