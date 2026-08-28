"""
Hand-drawn widgets.

ttk cannot do rounded corners, hover states or a ring chart, so the pieces that
carry the look are drawn on canvases. Each one is a plain tk widget underneath,
so they mix freely with ordinary frames.

Sizes here are written as logical pixels and passed through ``theme.px`` so they
stay physically the same on a scaled display.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from . import theme as t


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    """A rounded rectangle as a smoothed polygon."""
    r = min(r, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class Card(tk.Frame):
    """A surface panel with a hairline border."""

    def __init__(self, parent, padding=None, bg=t.SURFACE, border=t.BORDER, **kw):
        super().__init__(parent, bg=border, highlightthickness=0, bd=0, **kw)
        pad = t.PAD if padding is None else padding
        self.inner = tk.Frame(self, bg=bg, highlightthickness=0, bd=0)
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.body = tk.Frame(self.inner, bg=bg, highlightthickness=0, bd=0)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)


class RoundButton(tk.Canvas):
    """A filled or outlined pill button with hover and press states."""

    def __init__(
        self,
        parent,
        text,
        command=None,
        kind="primary",          # primary | secondary | ghost | danger
        width=None,
        height=None,
        font=None,
        bg=None,
    ):
        self._bg = bg or parent.cget("bg")
        self._font = font or t.font(9, "bold")
        h = t.px(34) if height is None else t.px(height)
        w = (
            t.px(width) if width
            else tkfont.Font(font=self._font).measure(text) + t.px(34)
        )

        super().__init__(
            parent, width=w, height=h,
            bg=self._bg, highlightthickness=0, bd=0,
        )
        self._text = text
        self._command = command
        self._kind = kind
        self._cw, self._ch = w, h
        self._enabled = True
        self._hovered = False
        self._press = False

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def _colors(self):
        if not self._enabled:
            return t.SURFACE_ALT, t.TEXT_FAINT, t.BORDER
        if self._kind == "primary":
            fill = t.ACCENT_PRESS if self._press else (
                t.ACCENT_HOVER if self._hovered else t.ACCENT)
            return fill, "#0b0d12", fill
        if self._kind == "danger":
            fill = t.DANGER if self._hovered else "#c9504a"
            return fill, "#12080a", fill
        if self._kind == "ghost":
            fill = t.SURFACE_HOVER if self._hovered else self._bg
            return fill, t.TEXT_DIM, self._bg
        fill = t.SURFACE_PRESS if self._press else (
            t.SURFACE_HOVER if self._hovered else t.SURFACE_ALT)
        return fill, t.TEXT, t.BORDER_STRONG

    def _draw(self):
        self.delete("all")
        fill, fg, outline = self._colors()
        round_rect(self, 1, 1, self._cw - 1, self._ch - 1, t.RADIUS_SM,
                   fill=fill, outline=outline)
        self.create_text(
            self._cw / 2, self._ch / 2 + 1,
            text=self._text, fill=fg, font=self._font,
        )

    def configure_text(self, text):
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._draw()

    def _on_enter(self, _e):
        if self._enabled:
            self._hovered = True
            self.configure(cursor="hand2")
            self._draw()

    def _on_leave(self, _e):
        self._hovered = self._press = False
        self._draw()

    def _on_press(self, _e):
        if self._enabled:
            self._press = True
            self._draw()

    def _on_release(self, _e):
        if self._enabled and self._press:
            self._press = False
            self._draw()
            if self._command:
                self._command()


class CheckBox(tk.Canvas):
    """A rounded checkbox with three states: unchecked, checked, locked."""

    def __init__(self, parent, command=None, bg=None):
        self._bg = bg or parent.cget("bg")
        self.size = t.px(19)
        super().__init__(
            parent, width=self.size, height=self.size,
            bg=self._bg, highlightthickness=0, bd=0,
        )
        self._checked = False
        self._locked = False
        self._hovered = False
        self._command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self._draw()

    def _set_hover(self, value):
        if not self._locked:
            self._hovered = value
            self.configure(cursor="hand2" if value else "")
            self._draw()

    def _click(self, _e):
        if self._locked:
            return
        self._checked = not self._checked
        self._draw()
        if self._command:
            self._command(self._checked)

    def set_state(self, checked=False, locked=False):
        self._checked, self._locked = checked, locked
        self._draw()

    @property
    def checked(self):
        return self._checked and not self._locked

    def set_background(self, color):
        self._bg = color
        self.configure(bg=color)
        self._draw()

    def _draw(self):
        # Geometry is expressed as fractions of the box so it stays correct at
        # any DPI without a second set of scaled constants.
        self.delete("all")
        s = self.size
        inset = s * 0.105
        radius = s * 0.26

        if self._locked:
            round_rect(self, inset, inset, s - inset, s - inset, radius,
                       fill=t.SURFACE_ALT, outline=t.BORDER_STRONG)
            self.create_line(s * 0.32, s / 2, s - s * 0.32, s / 2,
                             fill=t.TEXT_FAINT, width=max(1, t.px(2)))
            return

        if self._checked:
            round_rect(self, inset, inset, s - inset, s - inset, radius,
                       fill=t.ACCENT, outline=t.ACCENT)
            self.create_line(
                s * 0.29, s * 0.52,
                s * 0.44, s * 0.70,
                s * 0.73, s * 0.31,
                fill="#0b0d12", width=max(1.6, t.px(2.1)),
                capstyle="round", joinstyle="round",
            )
        else:
            outline = t.ACCENT if self._hovered else t.BORDER_STRONG
            round_rect(self, inset, inset, s - inset, s - inset, radius,
                       fill=self._bg, outline=outline)


class Pill(tk.Canvas):
    """A small status badge."""

    def __init__(self, parent, text, fg, fill, bg=None, font=None):
        self._font = font or t.font(8, "bold")
        w = tkfont.Font(font=self._font).measure(text) + t.px(20)
        h = t.px(20)
        super().__init__(
            parent, width=w, height=h,
            bg=bg or parent.cget("bg"), highlightthickness=0, bd=0,
        )
        round_rect(self, 0, 0, w, h, h / 2, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2 + 1, text=text, fill=fg, font=self._font)


class DiskRing(tk.Canvas):
    """Donut chart for drive usage."""

    def __init__(self, parent, size=132, thickness=13, bg=None):
        size = t.px(size)
        super().__init__(
            parent, width=size, height=size,
            bg=bg or parent.cget("bg"), highlightthickness=0, bd=0,
        )
        self._size = size
        self._thickness = t.px(thickness)

    def render(self, used_fraction: float, center_text: str, sub_text: str):
        self.delete("all")
        s, th = self._size, self._thickness
        pad = th / 2 + t.px(2)
        box = (pad, pad, s - pad, s - pad)

        self.create_arc(*box, start=90, extent=-359.999, style="arc",
                        outline=t.TRACK, width=th)

        used_fraction = max(0.0, min(1.0, used_fraction))
        if used_fraction > 0:
            color = t.SAFE if used_fraction < 0.75 else (
                t.CAUTION if used_fraction < 0.9 else t.DANGER
            )
            self.create_arc(
                *box, start=90, extent=-359.999 * used_fraction,
                style="arc", outline=color, width=th,
            )

        self.create_text(s / 2, s / 2 - t.px(9), text=center_text,
                         fill=t.TEXT, font=t.font(17, "bold", display=True))
        self.create_text(s / 2, s / 2 + t.px(12), text=sub_text,
                         fill=t.TEXT_DIM, font=t.font(8))


class Meter(tk.Canvas):
    """A slim rounded progress bar."""

    def __init__(self, parent, width=220, height=6, bg=None):
        width, height = t.px(width), t.px(height)
        super().__init__(
            parent, width=width, height=height,
            bg=bg or parent.cget("bg"), highlightthickness=0, bd=0,
        )
        self._cw, self._ch = width, height
        self.render(0)

    def render(self, fraction: float, color=t.ACCENT):
        self.delete("all")
        round_rect(self, 0, 0, self._cw, self._ch, self._ch / 2,
                   fill=t.TRACK, outline=t.TRACK)
        fraction = max(0.0, min(1.0, fraction))
        if fraction > 0:
            width = max(self._ch, self._cw * fraction)
            round_rect(self, 0, 0, width, self._ch, self._ch / 2,
                       fill=color, outline=color)


class ScrollArea(tk.Frame):
    """A vertically scrolling container with a slim custom scrollbar."""

    def __init__(self, parent, bg=t.BG):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self._bg = bg
        self._bar_w = t.px(8)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.bar = tk.Canvas(self, width=self._bar_w, bg=bg,
                             highlightthickness=0, bd=0)
        self.bar.pack(side="right", fill="y")

        self.content = tk.Frame(self.canvas, bg=bg, highlightthickness=0, bd=0)
        self._window = self.canvas.create_window(
            (0, 0), window=self.content, anchor="nw"
        )

        self.content.bind("<Configure>", self._on_content)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda _e: self._bind_wheel(True))
        self.canvas.bind("<Leave>", lambda _e: self._bind_wheel(False))

    def _bind_wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _wheel(self, event):
        first, last = self.canvas.yview()
        if first <= 0 and last >= 1:
            return
        self.canvas.yview_scroll(int(-event.delta / 60), "units")
        self._draw_bar()

    def _on_content(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._draw_bar()

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._draw_bar()

    def _draw_bar(self):
        self.bar.delete("all")
        first, last = self.canvas.yview()
        height = self.bar.winfo_height()
        if height <= 1 or (first <= 0 and last >= 1):
            return
        top = first * height
        bottom = max(last * height, top + t.px(24))
        inset = t.px(2)
        round_rect(self.bar, inset, top, self._bar_w - inset, bottom, inset,
                   fill=t.BORDER_STRONG, outline=t.BORDER_STRONG)

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)
        self._draw_bar()
