"""
The deletion engine.

There is exactly one function in SafeClean that removes a file --
:func:`_remove_one` -- and its first statement is a guard check. There is no
code path around it. If the guard raises, the file stays and the refusal is
recorded in the result so it shows up in the report.

Dry-run mode runs the identical pipeline, guard checks included, and simply
does not call the delete syscall at the end. What a dry run reports is exactly
what a real run would do.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import guard
from .rules import Rule
from .scanner import Finding

# --- Shell file operations (Recycle Bin) -----------------------------------

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_SILENT = 0x0004
FOF_NOCONFIRMMKDIR = 0x0200

SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND),
        ("wFunc", wt.UINT),
        ("pFrom", wt.LPCWSTR),
        ("pTo", wt.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wt.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wt.LPCWSTR),
    ]


def _send_to_recycle_bin(path: str) -> None:
    """Move a single path to the Recycle Bin. Raises OSError on failure."""
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    # pFrom is a double-NUL-terminated list of NUL-separated paths.
    op.pFrom = path + "\0\0"
    op.pTo = None
    op.fFlags = (
        FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI
        | FOF_SILENT | FOF_NOCONFIRMMKDIR
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0:
        raise OSError(f"SHFileOperation failed with code {result}")


def empty_recycle_bin() -> None:
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    # 0 = success, -2147418113 (E_UNEXPECTED) is returned when already empty.
    if result not in (0, -2147418113, 0x8000FFFF):
        raise OSError(f"SHEmptyRecycleBin failed with code {result}")


# --- Results ---------------------------------------------------------------


@dataclass
class RuleResult:
    rule_id: str
    label: str
    freed: int = 0
    deleted: int = 0
    locked: int = 0
    refused: int = 0
    refusals: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class CleanResult:
    dry_run: bool
    rules: list[RuleResult] = field(default_factory=list)

    @property
    def freed(self) -> int:
        return sum(r.freed for r in self.rules)

    @property
    def deleted(self) -> int:
        return sum(r.deleted for r in self.rules)

    @property
    def refused(self) -> int:
        return sum(r.refused for r in self.rules)

    @property
    def locked(self) -> int:
        return sum(r.locked for r in self.rules)


# --- The single deletion path ----------------------------------------------


def _remove_one(
    path: str,
    allowed_roots: list[Path],
    result: RuleResult,
    dry_run: bool,
    recycle: bool,
) -> int:
    """
    Remove one file. Returns bytes freed (0 if it was not removed).

    This is the only place in SafeClean that deletes. The guard check below is
    not optional and has no bypass flag.
    """
    try:
        guard.check(path, allowed_roots=allowed_roots)
    except guard.ProtectedPathError as exc:
        result.refused += 1
        if len(result.refusals) < 50:
            result.refusals.append((exc.path, exc.reason))
        return 0

    try:
        size = os.lstat(path).st_size
    except OSError:
        return 0

    if dry_run:
        result.deleted += 1
        result.freed += size
        return size

    try:
        if recycle:
            _send_to_recycle_bin(path)
        else:
            os.chmod(path, 0o666)
            os.remove(path)
    except PermissionError:
        result.locked += 1
        return 0
    except OSError as exc:
        result.locked += 1
        if len(result.errors) < 20:
            result.errors.append(f"{path}: {exc}")
        return 0

    result.deleted += 1
    result.freed += size
    return size


def _prune_empty_dirs(root: Path, allowed_roots: list[Path]) -> None:
    """Remove directories left empty after their files were deleted."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if Path(dirpath) == root:
            continue  # never remove the rule's own root
        if dirnames or filenames:
            continue
        if guard.is_protected(dirpath, allowed_roots=allowed_roots):
            continue
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


def clean_rule(
    rule: Rule,
    dry_run: bool = True,
    cancel: threading.Event | None = None,
) -> RuleResult:
    result = RuleResult(rule_id=rule.id, label=rule.label)

    if rule.special == "recycle_bin":
        if not dry_run:
            try:
                empty_recycle_bin()
            except OSError as exc:
                result.errors.append(str(exc))
        return result

    for root in rule.roots:
        allowed = [root]
        if cancel is not None and cancel.is_set():
            break
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            if cancel is not None and cancel.is_set():
                break
            dirnames[:] = [
                d for d in dirnames
                if not guard._is_reparse_point(os.path.join(dirpath, d))
            ]
            for name in filenames:
                _remove_one(
                    os.path.join(dirpath, name),
                    allowed,
                    result,
                    dry_run,
                    rule.recycle,
                )
        if not dry_run:
            _prune_empty_dirs(root, allowed)

    return result


def clean(
    findings: list[Finding],
    dry_run: bool = True,
    progress=None,
    cancel: threading.Event | None = None,
) -> CleanResult:
    """Clean every finding handed in. Callers pass only what the user ticked."""
    out = CleanResult(dry_run=dry_run)
    for index, finding in enumerate(findings, start=1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(index - 1, len(findings), finding.rule.label)
        out.rules.append(clean_rule(finding.rule, dry_run=dry_run, cancel=cancel))
    if progress:
        progress(len(findings), len(findings), "Done")
    return out
