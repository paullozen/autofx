"""Cross-platform auditory notifications."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from contextlib import suppress


def _try_windows_beep() -> bool:
    """Use winsound when running on native Windows."""
    if platform.system().lower() != "windows":
        return False
    with suppress(ImportError):
        import winsound  # type: ignore

        for _ in range(3):
            winsound.Beep(1000, 200)
            time.sleep(0.1)
        return True
    return False


def _try_wsl_beep() -> bool:
    """Trigger the Windows console bell when running under WSL."""
    release = platform.release().lower()
    if "microsoft" not in release and not os.environ.get("WSL_DISTRO_NAME"):
        return False
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "[console]::beep(1000,200);Start-Sleep -Milliseconds 100;"
        "[console]::beep(1000,200);Start-Sleep -Milliseconds 100;"
        "[console]::beep(1000,200)",
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def _terminal_bell() -> bool:
    """Fallback to the terminal bell character."""
    try:
        sys.stdout.write("\a" * 3)
        sys.stdout.flush()
        return True
    except Exception:
        return False


def ring_bell(message: str | None = None):
    """Emit a short audible notification across Windows, macOS, Linux, and WSL."""
    print("\n" + "-" * 60)
    print("🔔")
    if not (_try_windows_beep() or _try_wsl_beep()):
        _terminal_bell()
    if message:
        print(message)
