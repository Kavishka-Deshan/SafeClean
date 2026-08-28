"""
Running-process detection.

Used to block cache rules while their application is open. Deleting a cache out
from under a running browser can corrupt its cache index, and locked files fail
to delete anyway.

SafeClean never terminates a process. It reports what is running and waits for
the user to close it.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

__all__ = ["running_executables", "blockers_for", "friendly_name"]

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


_FRIENDLY = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "brave.exe": "Brave",
    "firefox.exe": "Firefox",
    "chromium.exe": "Chromium",
    "vivaldi.exe": "Vivaldi",
    "opera.exe": "Opera",
    "code.exe": "VS Code",
}


def friendly_name(exe: str) -> str:
    return _FRIENDLY.get(exe.lower(), exe)


def running_executables() -> set[str]:
    """Lower-cased names of every running process. Empty set if enumeration fails."""
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return set()

    names: set[str] = set()
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return set()
        while True:
            names.add(entry.szExeFile.lower())
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return names


def blockers_for(rule, running: set[str] | None = None) -> list[str]:
    """Friendly names of the processes currently blocking ``rule``."""
    if not rule.blocked_by:
        return []
    active = running if running is not None else running_executables()
    return [friendly_name(exe) for exe in rule.blocked_by if exe.lower() in active]
