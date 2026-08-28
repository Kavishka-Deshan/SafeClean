"""
Read-only scanning.

Walks each rule's declared roots, measures how much space they hold, and returns
a :class:`Finding` per rule. Nothing here modifies the filesystem.

Every file counted is also run past the guard, so a file the guard would refuse
is never included in a rule's reported size. What you see in the UI is exactly
what the cleaner is permitted to remove -- the number cannot promise more than
the guard will allow.
"""

from __future__ import annotations

import ctypes
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import guard, processes
from .rules import Risk, Rule


@dataclass
class Finding:
    rule: Rule
    size: int = 0
    file_count: int = 0
    files: list[tuple[str, int]] = field(default_factory=list)
    skipped_protected: int = 0
    blockers: list[str] = field(default_factory=list)
    needs_admin: bool = False
    error: str | None = None

    @property
    def cleanable(self) -> bool:
        return not self.blockers and not self.needs_admin and self.size > 0

    @property
    def status(self) -> str:
        if self.error:
            return self.error
        if self.blockers:
            return f"{', '.join(self.blockers)} is open - close it to clean this"
        if self.needs_admin:
            return "Needs administrator"
        if self.size == 0:
            return "Already clean"
        return "Ready"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:,.0f} {unit}" if unit in ("B", "KB") else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# Keep the per-rule file list bounded -- user Temp alone held 22,000 files.
MAX_PREVIEW_FILES = 400


def _walk_root(
    root: Path,
    allowed_roots: list[Path],
    cancel: threading.Event | None,
) -> tuple[int, int, int, list[tuple[str, int]]]:
    """Return (total_size, file_count, protected_skips, preview_files)."""
    total = 0
    count = 0
    skipped = 0
    preview: list[tuple[str, int]] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        if cancel is not None and cancel.is_set():
            break

        # Never descend into a junction or symlink -- it can point anywhere.
        dirnames[:] = [
            d for d in dirnames
            if not guard._is_reparse_point(os.path.join(dirpath, d))
        ]

        for name in filenames:
            full = os.path.join(dirpath, name)
            if not guard.inspect(full, allowed_roots=allowed_roots).allowed:
                skipped += 1
                continue
            try:
                size = os.lstat(full).st_size
            except OSError:
                continue
            total += size
            count += 1
            if len(preview) < MAX_PREVIEW_FILES:
                preview.append((full, size))
    return total, count, skipped, preview


def _recycle_bin_size() -> tuple[int, int]:
    """Bytes and item count across all fixed drives' recycle bins."""
    total = 0
    count = 0
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        bin_path = Path(f"{letter}:\\$Recycle.Bin")
        if not bin_path.is_dir():
            continue
        try:
            for dirpath, _dirnames, filenames in os.walk(bin_path, followlinks=False):
                for name in filenames:
                    try:
                        total += os.lstat(os.path.join(dirpath, name)).st_size
                        count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count


def scan_rule(
    rule: Rule,
    running: set[str] | None = None,
    is_admin: bool | None = None,
    cancel: threading.Event | None = None,
) -> Finding:
    finding = Finding(rule=rule)
    finding.blockers = processes.blockers_for(rule, running)

    admin = _is_admin() if is_admin is None else is_admin
    finding.needs_admin = rule.needs_admin and not admin

    if rule.special == "recycle_bin":
        try:
            finding.size, finding.file_count = _recycle_bin_size()
        except Exception as exc:  # pragma: no cover - defensive
            finding.error = f"Could not read: {exc}"
        return finding

    for root in rule.roots:
        if cancel is not None and cancel.is_set():
            break
        try:
            size, count, skipped, preview = _walk_root(root, [root], cancel)
        except OSError as exc:
            finding.error = f"Could not read: {exc}"
            continue
        finding.size += size
        finding.file_count += count
        finding.skipped_protected += skipped
        room = MAX_PREVIEW_FILES - len(finding.files)
        if room > 0:
            finding.files.extend(preview[:room])
    return finding


def scan_all(
    rules: list[Rule],
    progress=None,
    cancel: threading.Event | None = None,
) -> list[Finding]:
    """
    Scan every rule. ``progress(done, total, label)`` is called as work proceeds
    and may be used to drive a progress bar.
    """
    running = processes.running_executables()
    admin = _is_admin()
    findings: list[Finding] = []

    for index, rule in enumerate(rules, start=1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(index - 1, len(rules), rule.label)
        findings.append(scan_rule(rule, running=running, is_admin=admin, cancel=cancel))

    if progress:
        progress(len(rules), len(rules), "Done")
    return findings


@dataclass
class ProtectedItem:
    label: str
    path: str
    size: int
    reason: str


def protected_inventory() -> list[ProtectedItem]:
    """
    Enumerate the login/session data SafeClean is actively refusing to touch.

    This exists so the UI can *show* what is being protected rather than just
    silently omitting it. Every entry here is confirmed protected by asking the
    guard, not by assumption.
    """
    items: list[ProtectedItem] = []
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    if not local:
        return items

    chromium = [
        ("Google Chrome", Path(local) / r"Google\Chrome\User Data"),
        ("Microsoft Edge", Path(local) / r"Microsoft\Edge\User Data"),
        ("Brave", Path(local) / r"BraveSoftware\Brave-Browser\User Data"),
        ("Vivaldi", Path(local) / r"Vivaldi\User Data"),
    ]
    watch = [
        ("Cookies", "Website sessions"),
        # Current Chrome/Edge keep cookies under the Network subfolder.
        (os.path.join("Network", "Cookies"), "Website sessions"),
        (os.path.join("Network", "Network Persistent State"), "Network session state"),
        ("Login Data", "Saved passwords"),
        ("Web Data", "Autofill and payment data"),
        ("Local State", "Password encryption key"),
        ("Local Storage", "Site login tokens"),
        ("Session Storage", "Open tab session state"),
        ("IndexedDB", "Offline site data"),
        ("Extensions", "Installed extensions"),
        ("Bookmarks", "Bookmarks"),
        ("History", "Browsing history"),
        ("Preferences", "Browser settings"),
    ]

    def measure(path: Path) -> int:
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total = 0
        try:
            for dirpath, _d, filenames in os.walk(path, followlinks=False):
                for name in filenames:
                    try:
                        total += os.lstat(os.path.join(dirpath, name)).st_size
                    except OSError:
                        continue
        except OSError:
            pass
        return total

    for browser, user_data in chromium:
        if not user_data.is_dir():
            continue
        root_state = user_data / "Local State"
        if root_state.exists():
            items.append(
                ProtectedItem(
                    f"{browser} - Password encryption key",
                    str(root_state),
                    measure(root_state),
                    guard.inspect(root_state).reason,
                )
            )
        for profile in sorted(user_data.iterdir()):
            if not profile.is_dir():
                continue
            if profile.name != "Default" and not profile.name.startswith("Profile "):
                continue
            for name, description in watch:
                target = profile / name
                if not target.exists():
                    continue
                verdict = guard.inspect(target)
                if verdict.allowed:  # pragma: no cover - would be a guard bug
                    continue
                items.append(
                    ProtectedItem(
                        f"{browser} ({profile.name}) - {description}",
                        str(target),
                        measure(target),
                        verdict.reason,
                    )
                )

    firefox = Path(roaming) / "Mozilla" / "Firefox" / "Profiles" if roaming else None
    ff_watch = [
        ("logins.json", "Saved passwords"),
        ("key4.db", "Password encryption key"),
        ("cookies.sqlite", "Website sessions"),
        ("places.sqlite", "Bookmarks and history"),
        ("formhistory.sqlite", "Autofill data"),
        ("extensions.json", "Installed extensions"),
    ]
    if firefox and firefox.is_dir():
        for profile in sorted(firefox.iterdir()):
            if not profile.is_dir():
                continue
            for name, description in ff_watch:
                target = profile / name
                if not target.exists():
                    continue
                verdict = guard.inspect(target)
                if verdict.allowed:  # pragma: no cover
                    continue
                items.append(
                    ProtectedItem(
                        f"Firefox ({profile.name}) - {description}",
                        str(target),
                        measure(target),
                        verdict.reason,
                    )
                )
    return items


def drive_usage(letter: str = "C") -> tuple[int, int]:
    """(free_bytes, total_bytes) for a drive."""
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(f"{letter}:\\"),
        ctypes.byref(free),
        ctypes.byref(total),
        None,
    )
    return free.value, total.value
