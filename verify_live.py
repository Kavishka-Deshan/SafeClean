"""
Live verification against your real browser profiles.

Fingerprints every credential, session and personal-data file in every installed
browser profile, runs a REAL clean of the browser cache rules, then re-fingerprints
and reports any file that changed.

This is the end-to-end proof that cleaning does not log you out. Run it any time
the guard or the rules change:

    python verify_live.py            # verify only browsers that are closed
    python verify_live.py --list     # just list what would be fingerprinted
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from safeclean import cleaner, processes, rules, scanner  # noqa: E402
from safeclean.scanner import human  # noqa: E402

# Everything that must be byte-identical after a clean.
WATCH_FILES = [
    "Cookies", "Cookies-journal", "Login Data", "Login Data For Account",
    "Web Data", "Preferences", "Secure Preferences", "Bookmarks",
    "Bookmarks.bak", "History", "Favicons", "Top Sites", "Visited Links",
    "TransportSecurity", "Trust Tokens", "Affiliation Database",
    os.path.join("Network", "Cookies"),
    os.path.join("Network", "Network Persistent State"),
    os.path.join("Network", "TransportSecurity"),
]
WATCH_DIRS = [
    "Local Storage", "Session Storage", "IndexedDB", "Extensions",
    "Extension State", "Local Extension Settings", "Sync Data", "Sessions",
    "Service Worker/Database",
]
FIREFOX_FILES = [
    "logins.json", "logins-backup.json", "key4.db", "cert9.db",
    "cookies.sqlite", "places.sqlite", "formhistory.sqlite",
    "permissions.sqlite", "webappsstore.sqlite", "prefs.js",
    "sessionstore.jsonlz4", "extensions.json",
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError as exc:
        return f"<unreadable: {exc}>"
    return h.hexdigest()


def fingerprint(only: set[str] | None = None) -> dict[str, str]:
    """
    Hash every watched file across installed browser profiles.

    ``only`` restricts the sweep to named browsers. This matters: a *running*
    browser rewrites its own LevelDB logs and network state every few seconds,
    so hashing a browser we did not clean produces changes that have nothing to
    do with SafeClean. Verification only means something for browsers that were
    closed and actually cleaned.
    """
    prints: dict[str, str] = {}
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")

    chromium = [
        ("Chrome", Path(local) / r"Google\Chrome\User Data"),
        ("Edge", Path(local) / r"Microsoft\Edge\User Data"),
        ("Brave", Path(local) / r"BraveSoftware\Brave-Browser\User Data"),
        ("Vivaldi", Path(local) / r"Vivaldi\User Data"),
    ]

    for name, user_data in chromium:
        if not user_data.is_dir():
            continue
        if only is not None and name not in only:
            continue
        state = user_data / "Local State"
        if state.exists():
            prints[f"{name}/Local State"] = sha(state)
        for profile in sorted(user_data.iterdir()):
            if not profile.is_dir():
                continue
            if profile.name != "Default" and not profile.name.startswith("Profile "):
                continue
            for rel in WATCH_FILES:
                target = profile / rel
                if target.is_file():
                    prints[f"{name}/{profile.name}/{rel}"] = sha(target)
            for rel in WATCH_DIRS:
                base = profile / rel
                if not base.is_dir():
                    continue
                for dirpath, _d, filenames in os.walk(base):
                    for fname in filenames:
                        full = Path(dirpath) / fname
                        key = f"{name}/{profile.name}/{full.relative_to(profile)}"
                        prints[key] = sha(full)

    firefox = Path(roaming) / "Mozilla" / "Firefox" / "Profiles" if roaming else None
    if only is not None and "Firefox" not in only:
        firefox = None
    if firefox and firefox.is_dir():
        for profile in sorted(firefox.iterdir()):
            if not profile.is_dir():
                continue
            for rel in FIREFOX_FILES:
                target = profile / rel
                if target.is_file():
                    prints[f"Firefox/{profile.name}/{rel}"] = sha(target)
    return prints


# Maps a rule id to the browser name used by fingerprint().
RULE_TO_BROWSER = {
    "browser_chrome": "Chrome",
    "browser_edge": "Edge",
    "browser_brave": "Brave",
    "browser_vivaldi": "Vivaldi",
    "browser_firefox": "Firefox",
}


def main() -> int:
    browser_rules = [r for r in rules.all_rules() if r.category == "Browser"]
    running = processes.running_executables()
    runnable = []
    for rule in browser_rules:
        blockers = processes.blockers_for(rule, running)
        if blockers:
            print(f"  SKIP  {rule.label} - {', '.join(blockers)} is running")
        else:
            runnable.append(rule)

    if not runnable:
        print("\nNo browser is closed. Close one and re-run to verify a real clean.")
        return 1

    # Only verify browsers we are actually cleaning. A running browser rewrites
    # its own state files continuously, which would look like a false failure.
    targets = {RULE_TO_BROWSER[r.id] for r in runnable if r.id in RULE_TO_BROWSER}
    print(f"\nVerifying: {', '.join(sorted(targets))}")

    if "--seed" in sys.argv:
        # Drop marker files into the real cache directories so the run always
        # exercises actual deletion, even when the caches are already empty.
        seeded = 0
        for rule in runnable:
            for root in rule.roots:
                try:
                    marker = Path(root) / "safeclean_verify_marker.tmp"
                    marker.write_bytes(b"S" * 262144)
                    seeded += 1
                except OSError:
                    continue
        print(f"  seeded {seeded} marker files ({seeded * 256} KB) into cache dirs")

    print("Fingerprinting browser login and session data...")
    before = fingerprint(only=targets)
    print(f"  {len(before):,} files fingerprinted\n")

    if "--list" in sys.argv:
        for key in sorted(before):
            print("  ", key)
        return 0

    findings = [scanner.scan_rule(r, running=running) for r in runnable]
    total = sum(f.size for f in findings)
    print(f"\nCleaning for real: {', '.join(f.rule.label for f in findings)}")
    print(f"  {human(total)} of cache\n")

    result = cleaner.clean(findings, dry_run=False)
    print(f"  freed {human(result.freed)} across {result.deleted:,} files")
    print(f"  refused by guard: {result.refused}")
    print(f"  locked/skipped:   {result.locked}\n")

    print("Re-fingerprinting...")
    after = fingerprint(only=targets)

    missing = sorted(set(before) - set(after))
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])

    if missing or changed:
        print("\n*** VERIFICATION FAILED ***")
        for key in missing:
            print(f"  DELETED:  {key}")
        for key in changed:
            print(f"  MODIFIED: {key}")
        return 2

    print(f"\n*** VERIFICATION PASSED ***")
    print(f"All {len(before):,} login/session/personal files are byte-identical.")
    print(f"Freed {human(result.freed)} without touching a single credential.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
