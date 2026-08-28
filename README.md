# SafeClean

A disk cleaner for Windows that will not log you out of anything.

Most cleaners ask you to trust that they picked the right folders. SafeClean is
built the other way round: it assumes a cleanup rule will eventually be wrong,
so the rules never get the final say. Every deletion is checked independently by
a guard layer, and anything that could cost you a login is refused there —
including files the tool has never heard of.

It scans, classifies everything by risk, explains each item in plain language,
and deletes only what you tick and confirm.

```
python main.py
```

---

## Requirements

- Windows 10 or 11
- Python 3.10 or newer, with the Tkinter that ships with it

No third-party packages. `Pillow` is needed only to regenerate the icon.

## Getting it

Download the ZIP from the green **Code** button (or `git clone` the repo), then:

```
cd SafeClean
python main.py
```

Or double-click **`run.bat`**, which finds Python and starts the app without a
console window.

To put it on your Desktop and Start menu:

```
python tools/install.py        # --uninstall removes them
```

## How the protection works

`safeclean/guard.py` is consulted immediately before every file is removed, and
`cleaner._remove_one` is the only function in the codebase that deletes. There
is no bypass flag. Four independent checks must all pass:

**1. Default deny under browser profiles.** Anything inside a browser's
user-data folder is refused unless it matches a short allowlist of cache
directory names — `Cache`, `Code Cache`, `GPUCache`,
`Service Worker/CacheStorage`, Firefox's `cache2`, and a few more. A browser
file the tool has never heard of is refused automatically, so a browser update
cannot silently widen what gets deleted.

**2. A credential blocklist**, matched at any depth regardless of rule:
`Cookies`, `Login Data`, `Web Data`, `Local State`, `Local Storage`,
`Session Storage`, `IndexedDB`, `Extensions`, `Bookmarks`, `History`,
`Preferences`, plus Firefox's `logins.json`, `key4.db`, `cookies.sqlite`,
`places.sqlite` and the rest.

`Local State` is in there for a specific reason: it holds the key that decrypts
every saved password. Deleting it alone loses all of them even though
`Login Data` itself survives untouched.

**3. A system and personal-data denylist.** The Windows directory (except narrow
temp and log subtrees), Program Files, Documents, Desktop, Pictures, OneDrive,
`.ssh`, the DPAPI key stores, `pagefile.sys`, `WinSxS`, any `.git` directory,
and drive roots. These follow `%SystemDrive%`, so they stay correct when Windows
is installed somewhere other than C:.

**4. Traversal safety.** Symlinks and junctions are refused outright, and a path
must resolve to somewhere inside the root its rule declared.

The allowlist is anchored, so a directory called `Cache` buried inside
`Local Storage` does not inherit permission from it.

## Risk levels

| Level | Meaning | Pre-ticked |
|---|---|---|
| `SAFE` | Regenerable junk, no cost | Yes |
| `CAUTION` | Safe, but has a cost (re-download, slower first load) | **No** |
| `REVIEW` | Your own files | **No** |
| `PROTECTED` | Never deletable, shown greyed out with the reason | Cannot be |

Protected items are listed in the window rather than hidden, so you can see what
is being deliberately avoided instead of taking it on faith.

Nothing is deleted without the confirmation dialog. **Preview (dry run)** runs
the identical pipeline, guard checks included, and skips only the final delete
call — so what it reports is exactly what a real run would do.

## What it cleans

**Windows** — user and system temp, crash dumps, error reports, CBS/DISM
servicing logs, the Windows Update download cache, Delivery Optimization,
thumbnail and icon caches, Recycle Bin.

**Developer caches** — npm, pip, Gradle, NuGet, Yarn, Maven, Cargo, Go build,
VS Code.

**Browser caches** — Chrome, Edge, Brave, Vivaldi, Chromium and Firefox, across
*every* profile, and only the allowlisted cache directories. A browser that is
running is skipped with an explanation; SafeClean never terminates a process to
clean it.

## Tests

```
python -m unittest discover -s tests -v
```

33 tests. The three that carry the most weight:

- **`test_unknown_browser_file_is_denied_by_default`** — a browser file not on
  the allowlist is refused. This is what keeps the tool safe against future
  browser releases.
- **`test_overreaching_rule_cannot_touch_credentials`** — builds a fake browser
  profile, points a rule at the **entire profile directory**, runs the real
  cleaner, and asserts every credential file is still byte-identical. It
  simulates a buggy rule and proves the guard, not the rule, is the thing
  protecting you.
- **`test_denylist_follows_system_drive`** — protection tracks `%SystemDrive%`,
  so a Windows install on D: is covered too.

### Live verification

```
python verify_live.py --seed
```

Hashes every credential and session file in your real browser profiles, seeds
marker files into the cache directories, runs a genuine clean, then re-hashes
and reports anything that changed.

It only verifies browsers that are **closed**. A running browser rewrites its
own LevelDB logs and `Network Persistent State` every few seconds, which would
show up as a false failure — confirmed by a control run that fingerprinted a
running browser twice, six seconds apart, with no cleaning at all, and still saw
`Network Persistent State` change on its own.

## Project layout

```
main.py                  entry point, with platform checks
run.bat                  double-click launcher
verify_live.py           live proof against real browser profiles
safeclean/
  guard.py               the protection layer - everything routes through this
  rules.py               declarative cleaner definitions (data, no logic)
  scanner.py             read-only sizing + protected inventory
  cleaner.py             deletion engine; _remove_one is the only delete
  processes.py           running-process detection (never kills anything)
  elevation.py           admin detection and UAC relaunch
  report.py              JSON run log, written to %LOCALAPPDATA%\SafeClean\logs
  gui/theme.py           colour, type and spacing tokens; DPI scaling
  gui/widgets.py         canvas-drawn button, checkbox, pill, ring, scroll area
  gui/app.py             main window
  gui/confirm.py         final confirmation dialog
tests/
  test_guard.py          protection tests
  test_cleaner.py        sandbox deletion tests
tools/
  make_icon.py           generates the icon (needs Pillow)
  install.py             Desktop + Start menu shortcuts
SafeClean.spec           PyInstaller build (see the note below)
```

## Interface notes

The UI is drawn by hand on canvases, because ttk cannot do rounded corners,
hover states or a ring chart. The app also opts in to DPI awareness at import —
without it Windows renders a Tk window at 100% and bitmap-stretches it, which
makes text soft on a scaled display.

## Building an .exe

`SafeClean.spec` produces a standalone `dist/SafeClean.exe` via PyInstaller.

**Be aware that Windows Smart App Control blocks it.** SAC refuses unsigned
binaries with no established reputation, with "An Application Control policy has
blocked this file" (CodeIntegrity event 3077). Self-signing does not help — SAC
wants a signature chaining to a CA it already trusts.

`tools/install.py` handles this: it reads
`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState`
and, when SAC is enforcing, points the shortcuts at Python's own signed
`pythonw.exe` running `main.py` instead. Same app, same icon, no console window.
The `.exe` is used automatically on machines where SAC is off.

Running from source is the recommended path, and the one with no warnings.

## Things it deliberately will not do

- Kill a running process to clean its cache.
- Delete `WinSxS` by hand. Use
  `DISM /Online /Cleanup-Image /StartComponentCleanup` instead.
- Auto-select anything beyond `SAFE`.
- Delete personal files without routing them to the Recycle Bin.
- Touch anything that could sign you out of a website.

## Not built yet

- **Deep scan** for large files and old installers (the `REVIEW` tier). The risk
  level, Recycle Bin routing and UI category exist; the drive-walking scanner
  behind it does not.

## Contributing

Adding a cleaner means adding a `Rule` in `safeclean/rules.py`. You do not need
to touch the guard, and you should not: `rules.audit_rules()` runs at every scan
and aborts if a rule points somewhere the guard refuses.

Pull requests that weaken `guard.py` or remove protection tests will not be
accepted. If a genuine cache is being blocked, add its exact directory name to
`BROWSER_CACHE_ALLOWLIST` and include a test.

## Licence

MIT — see [LICENSE](LICENSE).
