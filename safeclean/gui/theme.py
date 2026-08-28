"""
Design tokens for the SafeClean interface.

Tkinter's stock ttk widgets look like Windows 7, so the UI is drawn by hand on
canvases instead (see widgets.py). Everything visual resolves to a token here so
the whole app stays consistent and can be retuned from one file.
"""

from __future__ import annotations

import ctypes
import tkinter.font as tkfont


# --- DPI ------------------------------------------------------------------
# Tk is DPI-unaware by default, so on a scaled display Windows renders the
# window at 100% and bitmap-stretches it, which makes every glyph soft. Opting
# in to DPI awareness before any window exists gets us real pixels and crisp
# text; the scale factor below then keeps hand-drawn geometry the right size.
#
# This has to run at import time: app.py imports this module before it
# constructs the Tk root, and the awareness call is only honoured beforehand.

def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _detect_scale() -> float:
    for attempt in (
        lambda: ctypes.windll.user32.GetDpiForSystem(),
        lambda: ctypes.windll.gdi32.GetDeviceCaps(
            ctypes.windll.user32.GetDC(0), 88  # LOGPIXELSX
        ),
    ):
        try:
            dpi = attempt()
            if dpi:
                return max(1.0, dpi / 96.0)
        except Exception:
            continue
    return 1.0


_enable_dpi_awareness()
SCALE: float = _detect_scale()
DPI: float = SCALE * 96.0


def px(value: float) -> int:
    """Scale a logical pixel measurement for the current display."""
    return int(round(value * SCALE))


# --- colour ---------------------------------------------------------------
# A cool near-black base with a single indigo accent. Status colours are
# desaturated versions of the usual green/amber/red so they read as information
# rather than as alarms.

BG = "#0b0d12"            # window background
SURFACE = "#12151c"       # cards
SURFACE_ALT = "#171b24"   # rows, inputs
SURFACE_HOVER = "#1d2230" # row hover
SURFACE_PRESS = "#232936"

BORDER = "#232834"        # card outlines
BORDER_SOFT = "#1a1e27"   # subtle dividers
BORDER_STRONG = "#2e3543"

TEXT = "#e9ecf1"          # primary
TEXT_DIM = "#98a1b2"      # secondary
TEXT_FAINT = "#646d7e"    # tertiary / disabled

ACCENT = "#6b8afd"
ACCENT_HOVER = "#8AA2FE"
ACCENT_PRESS = "#5876e0"
ACCENT_SOFT = "#1a2140"   # accent-tinted fill

SAFE = "#46b96a"
SAFE_SOFT = "#12261a"
CAUTION = "#d9a441"
CAUTION_SOFT = "#2a2113"
DANGER = "#e5645c"
DANGER_SOFT = "#2b1618"
PROTECTED = "#7b8496"
PROTECTED_SOFT = "#1a1e27"

TRACK = "#1c212c"         # progress / ring track


# --- type -----------------------------------------------------------------

_FAMILY_CACHE: dict[str, str] = {}


def _pick(*candidates: str) -> str:
    """First installed family from the candidates, falling back to Segoe UI."""
    key = candidates[0]
    if key in _FAMILY_CACHE:
        return _FAMILY_CACHE[key]
    try:
        available = set(tkfont.families())
    except Exception:
        available = set()
    chosen = next((c for c in candidates if c in available), "Segoe UI")
    _FAMILY_CACHE[key] = chosen
    return chosen


def display_family() -> str:
    return _pick("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI")


def text_family() -> str:
    return _pick("Segoe UI Variable Text", "Segoe UI")


def mono_family() -> str:
    return _pick("Cascadia Mono", "Cascadia Code", "Consolas")


def font(size: float = 10, weight: str = "normal", mono: bool = False, display: bool = False):
    """A Tk font spec. Sizes are points, so Tk's scaling factor handles DPI."""
    family = mono_family() if mono else (display_family() if display else text_family())
    return (family, int(round(size)), weight)


# --- metrics --------------------------------------------------------------

# Written as logical pixels, resolved for the display at import.
RADIUS = px(10)
RADIUS_SM = px(7)
RADIUS_LG = px(14)

PAD = px(16)
PAD_LG = px(24)
GAP = px(10)

ROW_HEIGHT = px(46)
