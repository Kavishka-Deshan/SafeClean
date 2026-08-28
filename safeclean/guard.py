"""
SafeClean protection layer.

Every single deletion passes through :func:`check`. If it raises, the path is not
touched. Nothing here deletes, moves, or writes -- this module only answers the
question "is this path allowed to be removed?".

Two rules govern the whole design:

1. DEFAULT DENY under browser profiles. A browser file we have never heard of is
   refused, not allowed. New Chrome releases add new files all the time; an
   allowlist stays safe when that happens, a denylist does not.

2. The guard never trusts the caller. Rules in ``rules.py`` declare what they
   want to delete, but the guard re-derives protection independently. A buggy or
   malicious rule cannot talk its way past these checks.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePath

__all__ = [
    "ProtectedPathError",
    "Verdict",
    "check",
    "inspect",
    "is_protected",
    "BROWSER_CACHE_ALLOWLIST",
    "CREDENTIAL_NAMES",
]


class ProtectedPathError(Exception):
    """Raised when a path must not be deleted. Carries a human-readable reason."""

    def __init__(self, path, reason: str) -> None:
        self.path = str(path)
        self.reason = reason
        super().__init__(f"{reason}: {self.path}")


@dataclass(frozen=True)
class Verdict:
    """Result of inspecting a path. ``allowed`` False means never delete it."""

    allowed: bool
    reason: str


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


def _norm(path) -> str:
    """Case-folded, normalised absolute string form, for prefix comparisons."""
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")


def _parts(path) -> tuple[str, ...]:
    """Lower-cased path components, drive stripped."""
    pure = PurePath(os.path.normcase(os.path.abspath(str(path))))
    return tuple(p.strip("\\/") for p in pure.parts[1:] if p.strip("\\/"))


def _is_under(path: str, root: str) -> bool:
    """True if ``path`` is a strict descendant of ``root`` (not equal to it)."""
    if not root:
        return False
    return path.startswith(root + os.sep)


def _is_at_or_under(path: str, root: str) -> bool:
    if not root:
        return False
    return path == root or path.startswith(root + os.sep)


# ---------------------------------------------------------------------------
# Browser protection
# ---------------------------------------------------------------------------

# Roots of every Chromium-family and Firefox profile store we know about. Any
# path under one of these is default-denied unless it matches the cache
# allowlist below.
def _browser_roots() -> tuple[str, ...]:
    local = _env("LOCALAPPDATA")
    roaming = _env("APPDATA")
    roots: list[str] = []

    chromium = [
        (local, r"Google\Chrome\User Data"),
        (local, r"Google\Chrome Beta\User Data"),
        (local, r"Google\Chrome Dev\User Data"),
        (local, r"Google\Chrome SxS\User Data"),
        (local, r"Microsoft\Edge\User Data"),
        (local, r"Microsoft\Edge Beta\User Data"),
        (local, r"Microsoft\Edge Dev\User Data"),
        (local, r"BraveSoftware\Brave-Browser\User Data"),
        (local, r"BraveSoftware\Brave-Browser-Beta\User Data"),
        (local, r"Chromium\User Data"),
        (local, r"Vivaldi\User Data"),
        (local, r"Opera Software"),
        (roaming, r"Opera Software"),
        (local, r"Mozilla\Firefox"),
        (roaming, r"Mozilla\Firefox"),
        (roaming, r"Mozilla\SeaMonkey"),
        (roaming, r"Thunderbird"),
        (local, r"Thunderbird"),
    ]
    for base, tail in chromium:
        if base:
            roots.append(_norm(os.path.join(base, tail)))
    return tuple(dict.fromkeys(roots))


BROWSER_ROOTS: tuple[str, ...] = _browser_roots()

# The ONLY things removable under a browser root. Each entry is a tuple of path
# components, anchored either directly at the browser root or one level down
# (inside a profile directory such as "Default" or "Profile 1").
#
# These hold nothing but re-fetchable HTTP responses, compiled script caches and
# GPU shader blobs. None of them carry cookies, tokens, passwords or session
# state. Everything else under a browser root is PROTECTED.
BROWSER_CACHE_ALLOWLIST: frozenset[tuple[str, ...]] = frozenset(
    {
        # Chromium family
        ("cache",),
        ("cache_data",),
        ("code cache",),
        ("gpucache",),
        ("graphitedawncache",),
        ("dawncache",),
        ("dawngraphitecache",),
        ("dawnwebgpucache",),
        ("shadercache",),
        ("grshadercache",),
        ("media cache",),
        ("application cache",),
        ("service worker", "cachestorage"),
        ("service worker", "scriptcache"),
        # Firefox family
        ("cache2",),
        ("startupcache",),
        ("thumbnails",),
        ("jumplistcache",),
        ("offlinecache",),
    }
)

# Hard stop on these names at ANY depth, under any rule, browser or not.
# Deleting or truncating any one of them can log the user out, drop saved
# passwords, or lose bookmarks and history.
#
# "Local State" deserves special mention: it holds the DPAPI-wrapped key that
# decrypts every saved password. Removing it alone destroys all stored
# credentials even though "Login Data" itself survives untouched.
CREDENTIAL_NAMES: frozenset[str] = frozenset(
    {
        # --- Chromium: sessions, logins, autofill ---
        "cookies",
        "cookies-journal",
        "login data",
        "login data-journal",
        "login data for account",
        "login data for account-journal",
        "web data",
        "web data-journal",
        "local state",
        "affiliation database",
        "affiliation database-journal",
        "trust tokens",
        "trust tokens-journal",
        "device bound sessions",
        "device bound sessions-journal",
        # --- Chromium: state that identifies the browser/session ---
        "preferences",
        "secure preferences",
        "local storage",
        "session storage",
        "indexeddb",
        "databases",
        "file system",
        "sync data",
        "sync app settings",
        "extension state",
        "extension rules",
        "extension scripts",
        "extensions",
        "local extension settings",
        "managed extension settings",
        "platform notifications",
        "shared proto db",
        "sessions",
        "session",
        "current session",
        "current tabs",
        "last session",
        "last tabs",
        "network action predictor",
        "network persistent state",
        "transportsecurity",
        # --- Chromium: user's own content ---
        "bookmarks",
        "bookmarks.bak",
        "history",
        "history-journal",
        "favicons",
        "favicons-journal",
        "top sites",
        "shortcuts",
        "visited links",
        "reading list",
        "webassistdatabase",
        # --- Firefox family ---
        "logins.json",
        "logins-backup.json",
        "key3.db",
        "key4.db",
        "cert9.db",
        "cert8.db",
        "signons.sqlite",
        "cookies.sqlite",
        "cookies.sqlite-wal",
        "cookies.sqlite-shm",
        "places.sqlite",
        "places.sqlite-wal",
        "favicons.sqlite",
        "formhistory.sqlite",
        "permissions.sqlite",
        "webappsstore.sqlite",
        "storage.sqlite",
        "content-prefs.sqlite",
        "prefs.js",
        "user.js",
        "sessionstore.jsonlz4",
        "sessionstore-backups",
        "sessionstore.js",
        "extensions.json",
        "addons.json",
        "addonstartup.json.lz4",
        "storage",
        "storage-sync-v2.sqlite",
        "profiles.ini",
        "installs.ini",
    }
)


def _browser_root_for(norm_path: str) -> str | None:
    for root in BROWSER_ROOTS:
        if _is_at_or_under(norm_path, root):
            return root
    return None


def _matches_cache_allowlist(rel: tuple[str, ...]) -> bool:
    """
    True if ``rel`` (components below the browser root) is, or lives inside, an
    allowlisted cache directory.

    The allowlisted entry must be anchored at the browser root itself or exactly
    one level down (inside a profile directory such as "Default"). This stops a
    crafted path like ``Default/Local Storage/Cache`` from sneaking through by
    burying an allowed name deep inside a protected tree.

    Firefox keeps its profiles one level deeper -- ``Firefox/Profiles/<id>/cache2``
    -- so anchor 2 is permitted only when the first component is "Profiles". It is
    deliberately not allowed in general.
    """
    anchors = [0, 1]
    if rel[:1] == ("profiles",):
        anchors.append(2)

    for anchor in anchors:
        if len(rel) < anchor:
            continue
        tail = rel[anchor:]
        for allowed in BROWSER_CACHE_ALLOWLIST:
            if len(tail) >= len(allowed) and tail[: len(allowed)] == allowed:
                return True
    return False


# ---------------------------------------------------------------------------
# System and personal-data protection
# ---------------------------------------------------------------------------

def _system_drive() -> str:
    """
    The drive Windows is installed on, e.g. ``C:``.

    Never assume C:. Windows is on D: or another letter often enough that
    hardcoding it would silently un-protect the real system folders there.
    """
    drive = _env("SystemDrive")
    if drive:
        return drive.rstrip("\\/")
    root = _env("SystemRoot")
    if root:
        return os.path.splitdrive(root)[0] or "C:"
    return "C:"


def _system_denylist() -> tuple[str, ...]:
    sysdrive = _system_drive()
    windir = _env("SystemRoot") or os.path.join(sysdrive + "\\", "Windows")
    programdata = _env("ProgramData") or os.path.join(sysdrive + "\\", "ProgramData")
    profile = _env("USERPROFILE") or ""
    deny = [
        windir,
        _env("ProgramFiles") or os.path.join(sysdrive + "\\", "Program Files"),
        _env("ProgramFiles(x86)") or os.path.join(sysdrive + "\\", "Program Files (x86)"),
        _env("ProgramW6432") or os.path.join(sysdrive + "\\", "Program Files"),
        os.path.join(programdata, "Microsoft", "Windows", "Start Menu"),
        os.path.join(sysdrive + "\\", "System Volume Information"),
        os.path.join(sysdrive + "\\", "Recovery"),
        os.path.join(sysdrive + "\\", "Boot"),
        os.path.join(sysdrive + "\\", "EFI"),
        os.path.join(sysdrive + "\\", "PerfLogs"),
    ]
    if profile:
        deny += [
            os.path.join(profile, "Documents"),
            os.path.join(profile, "Desktop"),
            os.path.join(profile, "Pictures"),
            os.path.join(profile, "Videos"),
            os.path.join(profile, "Music"),
            os.path.join(profile, "OneDrive"),
            os.path.join(profile, "Favorites"),
            os.path.join(profile, "Contacts"),
            os.path.join(profile, "Saved Games"),
            os.path.join(profile, "Links"),
            os.path.join(profile, "Searches"),
            os.path.join(profile, ".ssh"),
            os.path.join(profile, ".aws"),
            os.path.join(profile, ".config"),
            os.path.join(profile, "AppData", "Roaming", "Microsoft", "Crypto"),
            os.path.join(profile, "AppData", "Roaming", "Microsoft", "Protect"),
            os.path.join(profile, "AppData", "Roaming", "Microsoft", "Credentials"),
            os.path.join(profile, "AppData", "Local", "Microsoft", "Credentials"),
            os.path.join(profile, "AppData", "Local", "Microsoft", "Vault"),
        ]
    return tuple(_norm(p) for p in deny if p)


SYSTEM_DENYLIST: tuple[str, ...] = _system_denylist()

# Narrow exceptions carved back out of C:\Windows. These are the only places
# inside the Windows directory SafeClean may ever remove anything from.
def _windows_exceptions() -> tuple[str, ...]:
    windir = _env("SystemRoot") or os.path.join(_system_drive() + "\\", "Windows")
    return tuple(
        _norm(os.path.join(windir, tail))
        for tail in (
            "Temp",
            r"Logs\CBS",
            r"Logs\DISM",
            r"Logs\WindowsUpdate",
            r"SoftwareDistribution\Download",
            r"SoftwareDistribution\DeliveryOptimization",
            "Prefetch",
            r"System32\LogFiles\HTTPERR",
        )
    )


WINDOWS_EXCEPTIONS: tuple[str, ...] = _windows_exceptions()

# Files that must never be removed regardless of location.
CRITICAL_FILENAMES: frozenset[str] = frozenset(
    {
        "pagefile.sys",
        "swapfile.sys",
        "hiberfil.sys",
        "bootmgr",
        "ntldr",
        "boot.ini",
        "bcd",
        "ntuser.dat",
        "ntuser.ini",
        "usrclass.dat",
        "desktop.ini",
    }
)

# Directory names that signal "this is source code or a repository" -- never
# sweep these up as junk, even when they sit inside a cache-looking tree.
SOURCE_MARKERS: frozenset[str] = frozenset({".git", ".hg", ".svn"})


def _is_drive_root(norm_path: str) -> bool:
    drive, tail = os.path.splitdrive(norm_path)
    return bool(drive) and tail in ("", os.sep, "/")


def _is_reparse_point(path) -> bool:
    """
    True for symlinks, junctions and mount points. Deleting through one of these
    escapes the intended tree, so the guard refuses them outright.
    """
    try:
        st = os.lstat(str(path))
    except (OSError, ValueError):
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inspect(path, allowed_roots=None) -> Verdict:
    """
    Decide whether ``path`` may be deleted. Never raises for policy reasons.

    ``allowed_roots`` is the set of roots the calling rule declared. When given,
    ``path`` must be a strict descendant of one of them -- this keeps a rule
    from wandering outside the tree it advertised.
    """
    raw = str(path)
    if not raw.strip():
        return Verdict(False, "Empty path")

    norm = _norm(raw)
    parts = _parts(raw)

    if not os.path.isabs(raw):
        return Verdict(False, "Refusing a relative path")

    if _is_drive_root(norm):
        return Verdict(False, "Refusing to delete a drive root")

    if len(parts) < 2:
        return Verdict(False, "Refusing to delete a top-level directory")

    # 1. Reparse points -- resolving one could lead anywhere.
    if _is_reparse_point(raw):
        return Verdict(False, "Path is a symlink or junction")

    # 2. Must stay inside the declared rule roots, compared after resolution so
    #    a "..\\.." cannot climb out.
    if allowed_roots:
        resolved = _norm(Path(raw).resolve())
        inside = any(
            _is_under(resolved, _norm(Path(r).resolve())) for r in allowed_roots
        )
        if not inside:
            return Verdict(False, "Path escapes the declared cleanup root")

    lower_parts = set(parts)
    leaf = parts[-1]

    # 3. Never-delete filenames, at any depth.
    if leaf in CRITICAL_FILENAMES:
        return Verdict(False, f"Critical system file ({leaf})")

    # 4. Source repositories.
    if lower_parts & SOURCE_MARKERS:
        return Verdict(False, "Path is inside a source repository")

    # 5. Credential / session / personal browser data, at any depth. This runs
    #    independently of the browser-root check below, so it still fires for a
    #    browser installed somewhere we do not know about.
    hit = lower_parts & CREDENTIAL_NAMES
    if hit:
        return Verdict(
            False, f"Browser login or personal data ({sorted(hit)[0]})"
        )

    # 6. Browser roots: default deny, allowlist only.
    root = _browser_root_for(norm)
    if root is not None:
        if norm == root:
            return Verdict(False, "Refusing to delete a browser profile root")
        rel = tuple(
            p for p in norm[len(root) :].strip(os.sep).split(os.sep) if p
        )
        if not _matches_cache_allowlist(rel):
            return Verdict(
                False,
                "Not on the browser cache allowlist -- treated as login data",
            )
        return Verdict(True, "Browser cache (allowlisted)")

    # 7. Windows directory: denied except for the carved-out temp/log subtrees.
    windir = _norm(_env("SystemRoot") or os.path.join(_system_drive() + "\\", "Windows"))
    if _is_at_or_under(norm, windir):
        for exc in WINDOWS_EXCEPTIONS:
            if _is_under(norm, exc):
                return Verdict(True, "Windows temp or log file")
        return Verdict(False, "Inside the Windows directory")

    # 8. Everything else on the system denylist.
    for denied in SYSTEM_DENYLIST:
        if _is_at_or_under(norm, denied):
            return Verdict(False, f"Protected location ({denied})")

    return Verdict(True, "Allowed")


def check(path, allowed_roots=None) -> None:
    """Raise :class:`ProtectedPathError` unless ``path`` may be deleted."""
    verdict = inspect(path, allowed_roots=allowed_roots)
    if not verdict.allowed:
        raise ProtectedPathError(path, verdict.reason)


def is_protected(path, allowed_roots=None) -> bool:
    return not inspect(path, allowed_roots=allowed_roots).allowed
