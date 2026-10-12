"""Entry point for a packaged FaderDeck executable."""

import csv
import io
import subprocess
import sys
import time


VOICEMEETER_PROCESS_NAMES = (
    "voicemeeter8x64.exe",
    "voicemeeter8.exe",
    "voicemeeter.exe",
)


def voicemeeter_is_running():
    """Check for a running VoiceMeeter process without opening a console."""
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=no_window,
            timeout=5,
        )
        running_names = {
            row[0].casefold()
            for row in csv.reader(io.StringIO(result.stdout))
            if row
        }
        return any(
            name in running_names for name in VOICEMEETER_PROCESS_NAMES
        )
    except (OSError, subprocess.SubprocessError, csv.Error):
        return False


def main():
    arguments = sys.argv[1:]
    # The options are for this entry point only. Do not pass them to Qt.
    sys.argv = [sys.argv[0]]
    from main import main as run_faderdeck

    if "--quit" in arguments:
        # Ask the running FaderDeck to quit, then leave.
        run_faderdeck(["--quit"])
        return

    if "--wait-for-voicemeeter" in arguments:
        while not voicemeeter_is_running():
            time.sleep(1)

    run_faderdeck()


if __name__ == "__main__":
    main()
