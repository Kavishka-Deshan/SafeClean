"""Administrator detection and UAC relaunch."""

from __future__ import annotations

import ctypes
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """
    Re-launch this program through UAC. Returns True if the elevated process was
    started (the caller should then exit). Returns False if the user declined.
    """
    if is_admin():
        return False

    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        executable = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", executable, params, None, 1
    )
    # ShellExecuteW returns > 32 on success; 5 (ACCESS_DENIED) means declined.
    return int(result) > 32
