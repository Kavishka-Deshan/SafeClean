"""The final confirmation dialog. Nothing is deleted until this returns True."""

from __future__ import annotations

import tkinter as tk

from ..scanner import human
from . import theme as t
from .widgets import Card, RoundButton, ScrollArea


class ConfirmDialog(tk.Toplevel):
    def __init__(self, parent, findings, permanent_ids):
        super().__init__(parent, bg=t.BG)
        self.title("Confirm cleanup")
        self.resizable(False, False)
        self.transient(parent)
        self.result = False

        total = sum(f.size for f in findings)
        files = sum(f.file_count for f in findings)

        wrap = tk.Frame(self, bg=t.BG)
        wrap.pack(fill="both", expand=True, padx=t.px(26), pady=t.px(24))

        tk.Label(
            wrap, text=f"Delete {files:,} files?", bg=t.BG, fg=t.TEXT,
            font=t.font(18, "bold", display=True), anchor="w",
        ).pack(anchor="w")

        tk.Label(
            wrap, text=f"This frees {human(total)}. Review the list before continuing.",
            bg=t.BG, fg=t.TEXT_DIM, font=t.font(9.5), anchor="w",
        ).pack(anchor="w", pady=(t.px(4), t.px(18)))

        card = Card(wrap, padding=0)
        card.pack(fill="both", expand=True)

        listing = ScrollArea(card.body, bg=t.SURFACE)
        listing.configure(height=t.px(min(300, max(90, len(findings) * 52))))
        listing.pack(fill="both", expand=True)
        listing.pack_propagate(False)

        for index, finding in enumerate(
            sorted(findings, key=lambda f: f.size, reverse=True)
        ):
            if index:
                tk.Frame(listing.content, bg=t.BORDER_SOFT, height=1).pack(fill="x")
            permanent = finding.rule.id in permanent_ids
            self._row(listing.content, finding, permanent)

        note = tk.Frame(wrap, bg=t.SAFE_SOFT)
        note.pack(fill="x", pady=(t.px(16), t.px(0)))
        tk.Label(
            note,
            text=(
                "Browser logins, passwords, cookies, autofill, bookmarks, history "
                "and extensions are excluded and cannot be deleted by this tool."
            ),
            bg=t.SAFE_SOFT, fg=t.SAFE, font=t.font(9),
            wraplength=t.px(560), justify="left", anchor="w",
        ).pack(anchor="w", padx=t.px(14), pady=t.px(11))

        buttons = tk.Frame(wrap, bg=t.BG)
        buttons.pack(fill="x", pady=(t.px(20), t.px(0)))
        delete = RoundButton(
            buttons, f"Delete {human(total)}", self._confirm,
            kind="danger", width=180, height=40, bg=t.BG,
            font=t.font(10, "bold"),
        )
        delete.pack(side="right")
        RoundButton(
            buttons, "Cancel", self._cancel, kind="secondary",
            width=110, height=40, bg=t.BG, font=t.font(10, "bold"),
        ).pack(side="right", padx=(t.px(0), t.px(10)))

        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        delete.focus_set()

    def _row(self, parent, finding, permanent):
        row = tk.Frame(parent, bg=t.SURFACE)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=t.SURFACE)
        inner.pack(fill="x", padx=t.px(16), pady=t.px(11))

        text = tk.Frame(inner, bg=t.SURFACE)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(
            text, text=finding.rule.label, bg=t.SURFACE, fg=t.TEXT,
            font=t.font(10), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            text,
            text="Permanent" if permanent else "Recoverable from the Recycle Bin",
            bg=t.SURFACE, fg=t.CAUTION if permanent else t.SAFE,
            font=t.font(8), anchor="w",
        ).pack(anchor="w")

        tk.Label(
            inner, text=human(finding.size), bg=t.SURFACE, fg=t.TEXT,
            font=t.font(10, "bold"), anchor="e", width=11,
        ).pack(side="right")

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


def ask(parent, findings, permanent_ids) -> bool:
    dialog = ConfirmDialog(parent, findings, permanent_ids)
    parent.wait_window(dialog)
    return dialog.result
