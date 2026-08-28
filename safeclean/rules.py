"""
Declarative cleaner definitions.

This module is data, not logic. It describes *what could be cleaned* and how
risky each item is. It never deletes anything and never decides whether a path
is safe -- ``guard.py`` has the final word on that, and it re-checks every path
independently of whatever a rule here claims.

Adding a cleaner means adding a Rule below. If the new rule points somewhere it
should not, the guard still blocks it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import guard


class Risk(Enum):
    """How much care an item needs before it is removed."""

    SAFE = "SAFE"        # regenerable junk, no user-visible cost
    CAUTION = "CAUTION"  # safe, but has a cost (re-download, slower first load)
    REVIEW = "REVIEW"    # the user's own files -- decide individually

    @property
    def preselected(self) -> bool:
        """Only SAFE is ever ticked for you. CAUTION and REVIEW never are."""
        return self is Risk.SAFE


@dataclass
class Rule:
    id: str
    label: str
    category: str
    risk: Risk
    what: str
    cost: str
    roots: list[Path] = field(default_factory=list)
    needs_admin: bool = False
    blocked_by: tuple[str, ...] = ()
    recycle: bool = False
    special: str | None = None

    def existing_roots(self) -> list[Path]:
        return [p for p in self.roots if p.exists()]


def _p(*parts) -> Path | None:
    if not parts or not parts[0]:
        return None
    return Path(os.path.join(*[str(x) for x in parts]))


LOCAL = os.environ.get("LOCALAPPDATA", "")
ROAMING = os.environ.get("APPDATA", "")
PROFILE = os.environ.get("USERPROFILE", "")
SYSDRIVE = os.environ.get("SystemDrive", "C:").rstrip("\\/")
WINDIR = os.environ.get("SystemRoot") or os.path.join(SYSDRIVE + "\\", "Windows")
PROGRAMDATA = os.environ.get("ProgramData") or os.path.join(SYSDRIVE + "\\", "ProgramData")


def _paths(*candidates) -> list[Path]:
    return [p for p in candidates if p is not None]


# ---------------------------------------------------------------------------
# Windows junk
# ---------------------------------------------------------------------------

def _windows_rules() -> list[Rule]:
    return [
        Rule(
            id="user_temp",
            label="User temporary files",
            category="Windows",
            risk=Risk.SAFE,
            what="Scratch files left behind by installers and applications in your "
                 "personal temp folder. Windows never cleans these up on its own.",
            cost="Nothing. Anything still in use is locked and gets skipped.",
            roots=_paths(_p(LOCAL, "Temp")),
        ),
        Rule(
            id="windows_temp",
            label="Windows temporary files",
            category="Windows",
            risk=Risk.SAFE,
            what="The system-wide temp folder, used by Windows Update and installers.",
            cost="Nothing.",
            roots=_paths(_p(WINDIR, "Temp")),
            needs_admin=True,
        ),
        Rule(
            id="crash_dumps",
            label="Application crash dumps",
            category="Windows",
            risk=Risk.SAFE,
            what="Memory snapshots written when an app crashed. Only useful to a "
                 "developer debugging that specific crash.",
            cost="Nothing, unless you are actively debugging a crash.",
            roots=_paths(_p(LOCAL, "CrashDumps")),
        ),
        Rule(
            id="error_reporting",
            label="Windows Error Reporting queue",
            category="Windows",
            risk=Risk.SAFE,
            what="Crash reports queued to send to Microsoft.",
            cost="Nothing.",
            roots=_paths(
                _p(LOCAL, r"Microsoft\Windows\WER"),
                _p(PROGRAMDATA, r"Microsoft\Windows\WER"),
            ),
        ),
        Rule(
            id="cbs_logs",
            label="Windows servicing logs (CBS/DISM)",
            category="Windows",
            risk=Risk.SAFE,
            what="Verbose logs from Windows Update and component servicing.",
            cost="Nothing. Windows recreates them as needed.",
            roots=_paths(
                _p(WINDIR, r"Logs\CBS"),
                _p(WINDIR, r"Logs\DISM"),
            ),
            needs_admin=True,
        ),
        Rule(
            id="update_cache",
            label="Windows Update download cache",
            category="Windows",
            risk=Risk.SAFE,
            what="Installer payloads for updates that have already been applied.",
            cost="Nothing. Pending updates re-download if still needed.",
            roots=_paths(
                _p(WINDIR, r"SoftwareDistribution\Download"),
                _p(WINDIR, r"SoftwareDistribution\DeliveryOptimization"),
            ),
            needs_admin=True,
        ),
        Rule(
            id="thumbnail_cache",
            label="Thumbnail and icon cache",
            category="Windows",
            risk=Risk.SAFE,
            what="Pre-rendered thumbnails for File Explorer.",
            cost="Folders redraw thumbnails once, slightly slower the first time.",
            roots=_paths(_p(LOCAL, r"Microsoft\Windows\Explorer")),
        ),
        Rule(
            id="inetcache",
            label="Internet cache (WebView / legacy IE)",
            category="Windows",
            risk=Risk.SAFE,
            what="Cached web content for apps that embed the Windows web view.",
            cost="Nothing. This is not your browser's cache and holds no logins.",
            roots=_paths(_p(LOCAL, r"Microsoft\Windows\INetCache")),
        ),
        Rule(
            id="recycle_bin",
            label="Recycle Bin",
            category="Windows",
            risk=Risk.CAUTION,
            what="Files you have already deleted, still recoverable until emptied.",
            cost="Permanent. Anything in the bin can no longer be restored.",
            special="recycle_bin",
        ),
    ]


# ---------------------------------------------------------------------------
# Developer caches
# ---------------------------------------------------------------------------

def _developer_rules() -> list[Rule]:
    return [
        Rule(
            id="npm_cache",
            label="npm package cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded copies of npm packages, kept to speed up installs.",
            cost="The next 'npm install' re-downloads packages. Needs internet.",
            roots=_paths(_p(LOCAL, "npm-cache")),
        ),
        Rule(
            id="pip_cache",
            label="pip package cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded Python wheels kept for reinstalls.",
            cost="The next 'pip install' re-downloads. Needs internet.",
            roots=_paths(_p(LOCAL, r"pip\Cache")),
        ),
        Rule(
            id="gradle_cache",
            label="Gradle build cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded Java/Android dependencies and build outputs.",
            cost="Your next Android or Java build re-downloads dependencies and "
                 "will take noticeably longer.",
            roots=_paths(_p(PROFILE, r".gradle\caches")),
        ),
        Rule(
            id="nuget_cache",
            label="NuGet package cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded .NET packages.",
            cost="The next 'dotnet restore' re-downloads.",
            roots=_paths(_p(PROFILE, r".nuget\packages")),
        ),
        Rule(
            id="yarn_cache",
            label="Yarn package cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded Yarn packages.",
            cost="The next 'yarn install' re-downloads.",
            roots=_paths(_p(LOCAL, r"Yarn\Cache")),
        ),
        Rule(
            id="maven_cache",
            label="Maven repository cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded Java artifacts in the local Maven repository.",
            cost="The next Maven build re-downloads dependencies.",
            roots=_paths(_p(PROFILE, r".m2\repository")),
        ),
        Rule(
            id="cargo_cache",
            label="Cargo registry cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Downloaded Rust crates.",
            cost="The next 'cargo build' re-downloads crates.",
            roots=_paths(_p(PROFILE, r".cargo\registry\cache")),
        ),
        Rule(
            id="go_cache",
            label="Go build cache",
            category="Developer",
            risk=Risk.CAUTION,
            what="Compiled Go build artifacts.",
            cost="The next 'go build' recompiles from scratch.",
            roots=_paths(_p(LOCAL, r"go-build")),
        ),
        Rule(
            id="vscode_cache",
            label="VS Code caches",
            category="Developer",
            risk=Risk.CAUTION,
            what="Compiled script caches and web caches for VS Code. Not your "
                 "settings, extensions, or open files.",
            cost="VS Code is slightly slower on its next launch.",
            roots=_paths(
                _p(ROAMING, r"Code\Cache"),
                _p(ROAMING, r"Code\CachedData"),
                _p(ROAMING, r"Code\GPUCache"),
                _p(ROAMING, r"Code\Code Cache"),
            ),
            blocked_by=("code.exe",),
        ),
    ]


# ---------------------------------------------------------------------------
# Browser caches -- allowlisted directories only
# ---------------------------------------------------------------------------

# The leaf directory names we look for inside each browser profile. Every one of
# these must also pass guard.inspect() before it can be deleted, so this list
# cannot widen what is reachable -- it can only narrow it.
_CHROMIUM_CACHE_DIRS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GraphiteDawnCache",
    "Media Cache",
    os.path.join("Service Worker", "CacheStorage"),
    os.path.join("Service Worker", "ScriptCache"),
)

_CHROMIUM_ROOT_CACHE_DIRS = ("ShaderCache", "GrShaderCache", "GraphiteDawnCache")

_FIREFOX_CACHE_DIRS = ("cache2", "startupCache", "thumbnails", "jumpListCache")


def _chromium_profiles(user_data: Path) -> list[Path]:
    """Every profile directory in a Chromium user-data folder."""
    if not user_data.is_dir():
        return []
    out = []
    for entry in user_data.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name == "Default" or name.startswith("Profile ") or name.endswith(" Profile"):
            out.append(entry)
    return out


def _chromium_cache_roots(user_data: Path) -> list[Path]:
    roots: list[Path] = []
    for profile in _chromium_profiles(user_data):
        for tail in _CHROMIUM_CACHE_DIRS:
            candidate = profile / tail
            if candidate.is_dir():
                roots.append(candidate)
    for tail in _CHROMIUM_ROOT_CACHE_DIRS:
        candidate = user_data / tail
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _firefox_cache_roots(firefox_local: Path) -> list[Path]:
    profiles_dir = firefox_local / "Profiles"
    if not profiles_dir.is_dir():
        return []
    roots: list[Path] = []
    for profile in profiles_dir.iterdir():
        if not profile.is_dir():
            continue
        for tail in _FIREFOX_CACHE_DIRS:
            candidate = profile / tail
            if candidate.is_dir():
                roots.append(candidate)
    return roots


_BROWSERS = (
    ("chrome", "Google Chrome", r"Google\Chrome\User Data", "chrome.exe"),
    ("edge", "Microsoft Edge", r"Microsoft\Edge\User Data", "msedge.exe"),
    ("brave", "Brave", r"BraveSoftware\Brave-Browser\User Data", "brave.exe"),
    ("chromium", "Chromium", r"Chromium\User Data", "chromium.exe"),
    ("vivaldi", "Vivaldi", r"Vivaldi\User Data", "vivaldi.exe"),
)

_BROWSER_COST = (
    "Websites reload their images and scripts once, so the first visit to each "
    "site is slightly slower. You stay signed in everywhere -- cookies, saved "
    "passwords, autofill, bookmarks, history and extensions are never touched."
)


def _browser_rules() -> list[Rule]:
    rules: list[Rule] = []
    if not LOCAL:
        return rules

    for rule_id, label, tail, exe in _BROWSERS:
        user_data = Path(LOCAL) / tail
        roots = _chromium_cache_roots(user_data)
        if not roots:
            continue
        rules.append(
            Rule(
                id=f"browser_{rule_id}",
                label=f"{label} cache",
                category="Browser",
                risk=Risk.CAUTION,
                what=f"Cached images, scripts and shader data for {label}, across "
                     f"all {len(_chromium_profiles(user_data))} profile(s). Only the "
                     f"allowlisted cache folders are included.",
                cost=_BROWSER_COST,
                roots=roots,
                blocked_by=(exe,),
            )
        )

    firefox_local = Path(LOCAL) / "Mozilla" / "Firefox"
    ff_roots = _firefox_cache_roots(firefox_local)
    if ff_roots:
        rules.append(
            Rule(
                id="browser_firefox",
                label="Firefox cache",
                category="Browser",
                risk=Risk.CAUTION,
                what="Cached web content for Firefox. Only cache2 and startup "
                     "caches are included -- never logins.json, key4.db or cookies.",
                cost=_BROWSER_COST,
                roots=ff_roots,
                blocked_by=("firefox.exe",),
            )
        )
    return rules


# ---------------------------------------------------------------------------

def all_rules() -> list[Rule]:
    """Every rule that has at least one existing path on this machine."""
    rules = _windows_rules() + _developer_rules() + _browser_rules()
    keep = []
    for rule in rules:
        if rule.special:
            keep.append(rule)
            continue
        rule.roots = rule.existing_roots()
        if rule.roots:
            keep.append(rule)
    return keep


def audit_rules(rules: list[Rule] | None = None) -> list[tuple[str, str, str]]:
    """
    Self-check: ask the guard about every declared root.

    Any rule pointing somewhere the guard would refuse is a bug in this file.
    Returns a list of (rule_id, path, reason) for every root that fails.
    """
    problems = []
    for rule in rules if rules is not None else all_rules():
        for root in rule.roots:
            probe = root / "__safeclean_probe__"
            verdict = guard.inspect(probe, allowed_roots=[root])
            if not verdict.allowed:
                problems.append((rule.id, str(root), verdict.reason))
    return problems
