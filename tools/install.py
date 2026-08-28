"""
Put SafeClean on the desktop.

Creates a Desktop shortcut and a Start-menu entry pointing at the built
executable.

    python tools/install.py              # install shortcuts
    python tools/install.py --uninstall  # remove them

Shortcut paths come from SHGetKnownFolderPath rather than %USERPROFILE%\\Desktop,
because this account's Desktop is redirected into OneDrive and the literal path
is a stale empty folder.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FOLDERID_Desktop = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
FOLDERID_Programs = "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}"

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "SafeClean.exe"
ICON = ROOT / "safeclean" / "assets" / "icon.ico"


def smart_app_control_enforced() -> bool:
    """
    True when Windows Smart App Control is in enforcing mode.

    SAC blocks unsigned executables that have no established reputation, which
    includes anything PyInstaller just produced on this machine. Signing it
    ourselves does not help -- SAC wants a signature chaining to a CA it already
    trusts, not a self-signed one. So when SAC is on we launch through Python's
    own signed pythonw.exe instead of the bundled binary.
    """
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\CI\Policy",
        ) as key:
            value, _kind = winreg.QueryValueEx(
                key, "VerifiedAndReputablePolicyState"
            )
            return value == 1
    except OSError:
        return False


def launcher() -> tuple[Path, str, str]:
    """(target, arguments, note) for the shortcut."""
    if EXE.exists() and not smart_app_control_enforced():
        return EXE, "", "bundled executable"

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    reason = (
        "Smart App Control is enforced, so the unsigned build is blocked"
        if EXE.exists()
        else "no build found"
    )
    return exe, f'"{ROOT / "main.py"}"', f"pythonw.exe ({reason})"


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


def known_folder(folder_id: str) -> Path | None:
    guid = GUID()
    if ctypes.windll.ole32.CLSIDFromString(
        ctypes.c_wchar_p(folder_id), ctypes.byref(guid)
    ) != 0:
        return None
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(out)
    ) != 0:
        return None
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def make_shortcut(path: Path, target: Path, args: str, icon: Path, desc: str) -> bool:
    """Create a .lnk via WScript.Shell so no COM bindings are needed."""
    script = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{path}')
$s.TargetPath = '{target}'
$s.Arguments = '{args}'
$s.WorkingDirectory = '{target.parent}'
$s.IconLocation = '{icon}'
$s.Description = '{desc}'
$s.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  failed: {result.stderr.strip()}")
        return False
    return path.exists()


def targets() -> list[tuple[str, Path]]:
    desktop = known_folder(FOLDERID_Desktop)
    programs = known_folder(FOLDERID_Programs)
    out = []
    if desktop:
        out.append(("Desktop", desktop / "SafeClean.lnk"))
    if programs:
        out.append(("Start menu", programs / "SafeClean.lnk"))
    return out


def install() -> int:
    target, args, note = launcher()
    if not target.exists():
        print(f"No way to launch SafeClean: {target} is missing")
        return 1

    print(f"  launching via {note}")
    for label, link in targets():
        ok = make_shortcut(
            link, target, args, ICON, "Disk cleanup that keeps you signed in"
        )
        print(f"  {'OK ' if ok else 'FAIL'} {label}: {link}")

    print("\nDone. Launch SafeClean from the Desktop or Start menu.")
    return 0


def uninstall() -> int:
    for label, link in targets():
        if link.exists():
            try:
                link.unlink()
                print(f"  removed {label}: {link}")
            except OSError as exc:
                print(f"  could not remove {link}: {exc}")
        else:
            print(f"  {label} shortcut not present")
    return 0


def main() -> int:
    if "--uninstall" in sys.argv[1:]:
        return uninstall()
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
