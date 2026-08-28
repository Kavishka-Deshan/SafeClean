"""
SafeClean entry point.

    python main.py

Checks the platform and Python version before importing anything else, so
someone running this on the wrong system gets a sentence they can act on
instead of an ImportError traceback from deep inside ctypes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_PYTHON = (3, 10)


def _fail(title: str, message: str) -> int:
    """Report a startup problem on the console and, if possible, in a dialog."""
    print(f"{title}\n\n{message}", file=sys.stderr)
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass
    return 1


def main() -> int:
    if sys.platform != "win32":
        return _fail(
            "SafeClean requires Windows",
            "SafeClean cleans Windows-specific locations (AppData, the Windows\n"
            "servicing logs, the Recycle Bin) and relies on Windows APIs, so it\n"
            f"cannot run on {sys.platform}.",
        )

    if sys.version_info < MIN_PYTHON:
        current = ".".join(str(p) for p in sys.version_info[:3])
        return _fail(
            "Python is too old",
            f"SafeClean needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.\n"
            f"This is Python {current}.\n\n"
            "Get a newer build from https://python.org/downloads",
        )

    try:
        import tkinter  # noqa: F401
    except ImportError:
        return _fail(
            "Tkinter is missing",
            "SafeClean's interface needs Tkinter, which normally ships with\n"
            "Python on Windows. Reinstall Python and make sure the\n"
            '"tcl/tk and IDLE" component is selected.',
        )

    from safeclean.gui.app import main as run

    return run() or 0


if __name__ == "__main__":
    raise SystemExit(main())
