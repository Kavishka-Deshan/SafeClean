"""
SafeClean main window.

Flow: Scan -> review -> tick what you want -> Preview (dry run) -> Clean ->
confirm dialog -> deletion. The Clean button never deletes directly; it always
routes through the confirmation dialog.

Scanning and cleaning run on a worker thread and report back through a queue the
Tk main loop drains, so the window stays responsive and cancellable.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox

from .. import cleaner, elevation, report, rules, scanner
from ..rules import Risk
from ..scanner import human
from . import confirm
from . import theme as t
from .widgets import Card, CheckBox, DiskRing, Meter, Pill, RoundButton, ScrollArea

RISK_STYLE = {
    Risk.SAFE: (t.SAFE, t.SAFE_SOFT, "Safe"),
    Risk.CAUTION: (t.CAUTION, t.CAUTION_SOFT, "Caution"),
    Risk.REVIEW: (t.DANGER, t.DANGER_SOFT, "Review"),
}


class RuleRow(tk.Frame):
    """One cleanable item: checkbox, name, status, size."""

    def __init__(self, parent, finding, on_toggle, on_select):
        super().__init__(parent, bg=t.SURFACE, highlightthickness=0, bd=0)
        self.finding = finding
        self.on_toggle = on_toggle
        self.on_select = on_select
        self._selected = False
        self._base = t.SURFACE

        rule = finding.rule
        blocked = not finding.cleanable
        pad = tk.Frame(self, bg=t.SURFACE, height=1)
        pad.pack(fill="x")

        row = tk.Frame(self, bg=t.SURFACE)
        row.pack(fill="x", padx=t.px(14), pady=t.px(9))
        self._row = row

        self.check = CheckBox(row, command=self._toggled, bg=t.SURFACE)
        self.check.set_state(
            checked=finding.rule.risk.preselected and not blocked and finding.size > 0,
            locked=blocked,
        )
        self.check.pack(side="left", padx=(t.px(0), t.px(12)))

        text = tk.Frame(row, bg=t.SURFACE)
        text.pack(side="left", fill="x", expand=True)

        self.name = tk.Label(
            text, text=rule.label, bg=t.SURFACE,
            fg=t.TEXT_FAINT if blocked else t.TEXT,
            font=t.font(10), anchor="w",
        )
        self.name.pack(anchor="w")

        self.status = tk.Label(
            text, text=finding.status, bg=t.SURFACE,
            fg=t.DANGER if blocked and finding.blockers else t.TEXT_FAINT,
            font=t.font(8), anchor="w",
        )
        self.status.pack(anchor="w")

        right = tk.Frame(row, bg=t.SURFACE)
        right.pack(side="right")

        colour, soft, label = RISK_STYLE[rule.risk]
        self.pill = Pill(right, label, colour, soft, bg=t.SURFACE)
        self.pill.pack(side="right", padx=(t.px(12), t.px(0)))

        self.size = tk.Label(
            right, text=human(finding.size), bg=t.SURFACE,
            fg=t.TEXT_FAINT if blocked else t.TEXT,
            font=t.font(10, "bold"), anchor="e", width=10,
        )
        self.size.pack(side="right")

        for widget in (self, row, text, right, self.name, self.status, self.size):
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
            widget.bind("<Button-1>", self._clicked)

    # -- appearance --

    def _paint(self, colour):
        self._base = colour
        for widget in (self, self._row, self.name, self.status, self.size):
            widget.configure(bg=colour)
        for widget in self._row.winfo_children():
            if isinstance(widget, tk.Frame):
                widget.configure(bg=colour)
        self.check.set_background(colour)
        self.pill.configure(bg=colour)

    def _enter(self, _e):
        if not self._selected:
            self._paint(t.SURFACE_HOVER)

    def _leave(self, _e):
        if not self._selected:
            self._paint(t.SURFACE)

    def set_selected(self, value):
        self._selected = value
        self._paint(t.SURFACE_PRESS if value else t.SURFACE)

    def _clicked(self, _e):
        self.on_select(self)

    def _toggled(self, checked):
        self.on_toggle(self.finding.rule.id, checked)

    def set_checked(self, value):
        if self.finding.cleanable:
            self.check.set_state(checked=value, locked=False)


class Section(tk.Frame):
    """A titled group of rows, optionally collapsible."""

    def __init__(self, parent, title, subtitle, collapsible=False, expanded=True):
        super().__init__(parent, bg=t.BG, highlightthickness=0, bd=0)
        self._expanded = expanded
        self._collapsible = collapsible

        head = tk.Frame(self, bg=t.BG)
        head.pack(fill="x", pady=(t.px(0), t.px(8)))

        self.chevron = tk.Label(
            head, text="", bg=t.BG, fg=t.TEXT_DIM, font=t.font(9),
        )
        if collapsible:
            self.chevron.configure(text="▸" if not expanded else "▾")
            self.chevron.pack(side="left", padx=(t.px(0), t.px(6)))

        self.title = tk.Label(
            head, text=title, bg=t.BG, fg=t.TEXT,
            font=t.font(11, "bold", display=True),
        )
        self.title.pack(side="left")

        self.subtitle = tk.Label(
            head, text=subtitle, bg=t.BG, fg=t.TEXT_FAINT, font=t.font(9),
        )
        self.subtitle.pack(side="right")

        self.card = Card(self, padding=0)
        if expanded:
            self.card.pack(fill="x")

        if collapsible:
            for widget in (head, self.title, self.chevron):
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", self._toggle)

    def _toggle(self, _e=None):
        self._expanded = not self._expanded
        self.chevron.configure(text="▾" if self._expanded else "▸")
        if self._expanded:
            self.card.pack(fill="x")
        else:
            self.card.pack_forget()

    @property
    def body(self):
        return self.card.body


def divider(parent):
    return tk.Frame(parent, bg=t.BORDER_SOFT, height=1)


class SafeCleanApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SafeClean")
        self.configure(bg=t.BG)

        # theme.py opted the process in to DPI awareness at import, so Tk now
        # gets real pixels. Point-sized fonts still need the matching scaling
        # factor or they render at 96 DPI sizes on a scaled display.
        self.tk.call("tk", "scaling", t.DPI / 72.0)

        # Fit the screen rather than assuming a size. On a 1536x864 laptop panel
        # a fixed 1200x800 leaves no room for the details column.
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(t.px(1280), int(screen_w * 0.92))
        height = min(t.px(860), int(screen_h * 0.90))
        self._detail_width = t.px(340) if width >= t.px(1180) else t.px(300)
        self.geometry(
            f"{width}x{height}"
            f"+{(screen_w - width) // 2}+{max(0, (screen_h - height) // 2 - 24)}"
        )
        self.minsize(t.px(880), t.px(600))

        self.findings: list[scanner.Finding] = []
        self.protected: list[scanner.ProtectedItem] = []
        self.selected: dict[str, bool] = {}
        self.rows: dict[str, RuleRow] = {}
        self.active_row: RuleRow | None = None
        self.busy = False
        self.cancel_event = threading.Event()
        self.events: queue.Queue = queue.Queue()

        self._build_topbar()
        self._build_main()
        self._build_footer()

        self.after(80, self._drain_events)
        self.after(250, self.start_scan)

    # -- layout ------------------------------------------------------------

    def _build_topbar(self):
        bar = tk.Frame(self, bg=t.BG)
        bar.pack(fill="x", padx=t.PAD_LG, pady=(t.px(20), t.px(8)))

        left = tk.Frame(bar, bg=t.BG)
        left.pack(side="left")

        mark = tk.Frame(left, bg=t.BG)
        mark.pack(anchor="w")
        dot = tk.Canvas(mark, width=10, height=10, bg=t.BG,
                        highlightthickness=0, bd=0)
        dot.create_oval(1, 1, 9, 9, fill=t.ACCENT, outline=t.ACCENT)
        dot.pack(side="left", pady=(t.px(0), t.px(2)), padx=(t.px(0), t.px(9)))
        tk.Label(
            mark, text="SafeClean", bg=t.BG, fg=t.TEXT,
            font=t.font(19, "bold", display=True),
        ).pack(side="left")

        tk.Label(
            left, text="Disk cleanup that keeps you signed in",
            bg=t.BG, fg=t.TEXT_DIM, font=t.font(9),
        ).pack(anchor="w", pady=(t.px(1), t.px(0)))

        right = tk.Frame(bar, bg=t.BG)
        right.pack(side="right")
        self.admin_slot = tk.Frame(right, bg=t.BG)
        self.admin_slot.pack(anchor="e")
        self._refresh_admin()

    def _build_main(self):
        main = tk.Frame(self, bg=t.BG)
        main.pack(fill="both", expand=True, padx=t.PAD_LG)

        # The details column is packed BEFORE the expanding left column. Pack
        # gives space in packing order, so reversing these lets the left column
        # claim everything and clip the details panel off the right edge.
        right = tk.Frame(main, bg=t.BG, width=self._detail_width)
        right.pack(side="right", fill="y", padx=(t.px(20), t.px(0)))
        right.pack_propagate(False)

        self.detail_card = Card(right, padding=18)
        self.detail_card.pack(fill="both", expand=True)
        self._build_details(self.detail_card.body)

        # --- left column ---
        left = tk.Frame(main, bg=t.BG)
        left.pack(side="left", fill="both", expand=True)

        hero = Card(left, padding=18)
        hero.pack(fill="x", pady=(t.px(0), t.px(16)))

        ring_wrap = tk.Frame(hero.body, bg=t.SURFACE)
        ring_wrap.pack(side="left", padx=(t.px(2), t.px(20)))
        self.ring = DiskRing(ring_wrap, bg=t.SURFACE)
        self.ring.pack()

        info = tk.Frame(hero.body, bg=t.SURFACE)
        info.pack(side="left", fill="both", expand=True)

        self.drive_head = tk.Label(
            info, text="", bg=t.SURFACE, fg=t.TEXT,
            font=t.font(15, "bold", display=True), anchor="w",
        )
        self.drive_head.pack(anchor="w")

        self.drive_sub = tk.Label(
            info, text="", bg=t.SURFACE, fg=t.TEXT_DIM,
            font=t.font(9), anchor="w",
        )
        self.drive_sub.pack(anchor="w", pady=(t.px(2), t.px(12)))

        controls = tk.Frame(info, bg=t.SURFACE)
        controls.pack(anchor="w")
        self.scan_button = RoundButton(
            controls, "Scan", self.start_scan, kind="primary",
            width=104, bg=t.SURFACE,
        )
        self.scan_button.pack(side="left")
        self.cancel_button = RoundButton(
            controls, "Cancel", self.cancel, kind="secondary",
            width=90, bg=t.SURFACE,
        )
        self.cancel_button.pack(side="left", padx=t.px(8))
        self.cancel_button.set_enabled(False)

        prog = tk.Frame(info, bg=t.SURFACE)
        prog.pack(anchor="w", fill="x", pady=(t.px(14), t.px(0)))
        self.meter = Meter(prog, width=300, bg=t.SURFACE)
        self.meter.pack(anchor="w")
        self.progress_label = tk.Label(
            prog, text="", bg=t.SURFACE, fg=t.TEXT_FAINT,
            font=t.font(8), anchor="w",
        )
        self.progress_label.pack(anchor="w", pady=(t.px(5), t.px(0)))

        quick = tk.Frame(left, bg=t.BG)
        quick.pack(fill="x", pady=(t.px(0), t.px(12)))
        RoundButton(quick, "Select all safe", self.select_safe,
                    kind="ghost", bg=t.BG).pack(side="left")
        RoundButton(quick, "Clear selection", self.clear_selection,
                    kind="ghost", bg=t.BG).pack(side="left", padx=(t.px(4), t.px(0)))

        self.scroll = ScrollArea(left, bg=t.BG)
        self.scroll.pack(fill="both", expand=True)

    def _build_details(self, parent):
        self.detail_title = tk.Label(
            parent, text="Nothing selected", bg=t.SURFACE, fg=t.TEXT,
            font=t.font(13, "bold", display=True),
            wraplength=self._detail_width - t.px(56), justify="left", anchor="w",
        )
        self.detail_title.pack(anchor="w")

        self.detail_meta = tk.Label(
            parent, text="Pick an item to see what it is",
            bg=t.SURFACE, fg=t.TEXT_DIM, font=t.font(9),
            wraplength=self._detail_width - t.px(56), justify="left", anchor="w",
        )
        self.detail_meta.pack(anchor="w", pady=(t.px(3), t.px(16)))

        def heading(text):
            tk.Label(
                parent, text=text.upper(), bg=t.SURFACE, fg=t.TEXT_FAINT,
                font=t.font(8, "bold"), anchor="w",
            ).pack(anchor="w", pady=(t.px(0), t.px(3)))

        heading("What this is")
        self.detail_what = tk.Label(
            parent, text="—", bg=t.SURFACE, fg=t.TEXT,
            font=t.font(9), wraplength=self._detail_width - t.px(56), justify="left", anchor="w",
        )
        self.detail_what.pack(anchor="w", pady=(t.px(0), t.px(14)))

        heading("What deleting it costs")
        self.detail_cost = tk.Label(
            parent, text="—", bg=t.SURFACE, fg=t.TEXT,
            font=t.font(9), wraplength=self._detail_width - t.px(56), justify="left", anchor="w",
        )
        self.detail_cost.pack(anchor="w", pady=(t.px(0), t.px(14)))

        heading("Locations")
        holder = tk.Frame(parent, bg=t.BORDER)
        holder.pack(fill="both", expand=True, pady=(t.px(0), t.px(12)))
        self.detail_paths = tk.Text(
            holder, height=7, wrap="none", relief="flat", bd=0,
            bg=t.SURFACE_ALT, fg=t.TEXT_DIM, font=t.font(8, mono=True),
            padx=t.px(10), pady=t.px(8), highlightthickness=0,
        )
        self.detail_paths.pack(fill="both", expand=True, padx=1, pady=1)
        self.detail_paths.configure(state="disabled")

        self.preview_button = RoundButton(
            parent, "Preview files", self.preview_files,
            kind="secondary", bg=t.SURFACE,
        )
        self.preview_button.pack(anchor="w")
        self.preview_button.set_enabled(False)

    def _build_footer(self):
        edge = tk.Frame(self, bg=t.BORDER, height=1)
        edge.pack(fill="x", pady=(t.px(16), t.px(0)))

        bar = tk.Frame(self, bg=t.SURFACE)
        bar.pack(fill="x")

        inner = tk.Frame(bar, bg=t.SURFACE)
        inner.pack(fill="x", padx=t.PAD_LG, pady=t.px(14))

        left = tk.Frame(inner, bg=t.SURFACE)
        left.pack(side="left")
        self.summary = tk.Label(
            left, text="Nothing selected", bg=t.SURFACE, fg=t.TEXT,
            font=t.font(14, "bold", display=True), anchor="w",
        )
        self.summary.pack(anchor="w")
        self.summary_sub = tk.Label(
            left, text="Only safe items are ticked for you",
            bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.font(8), anchor="w",
        )
        self.summary_sub.pack(anchor="w")

        right = tk.Frame(inner, bg=t.SURFACE)
        right.pack(side="right")
        self.clean_button = RoundButton(
            right, "Clean selected", self.start_clean,
            kind="primary", width=150, height=38, bg=t.SURFACE,
            font=t.font(10, "bold"),
        )
        self.clean_button.pack(side="right")
        self.dry_button = RoundButton(
            right, "Preview (dry run)", self.start_dry_run,
            kind="secondary", width=150, height=38, bg=t.SURFACE,
            font=t.font(10, "bold"),
        )
        self.dry_button.pack(side="right", padx=(t.px(0), t.px(10)))
        self.clean_button.set_enabled(False)
        self.dry_button.set_enabled(False)

    # -- header state ------------------------------------------------------

    def _refresh_drive(self):
        free, total = scanner.drive_usage("C")
        used = total - free
        fraction = used / total if total else 0
        self.ring.render(fraction, f"{fraction * 100:.0f}%", "used")
        self.drive_head.configure(text=f"{human(free)} free on C:")
        self.drive_sub.configure(
            text=f"{human(used)} used of {human(total)}"
        )

    def _refresh_admin(self):
        for child in self.admin_slot.winfo_children():
            child.destroy()
        if elevation.is_admin():
            Pill(self.admin_slot, "ADMINISTRATOR", t.SAFE, t.SAFE_SOFT,
                 bg=t.BG).pack(anchor="e")
        else:
            Pill(self.admin_slot, "LIMITED ACCESS", t.CAUTION, t.CAUTION_SOFT,
                 bg=t.BG).pack(anchor="e")
            RoundButton(
                self.admin_slot, "Restart as administrator",
                self.restart_admin, kind="secondary", bg=t.BG,
            ).pack(anchor="e", pady=(t.px(7), t.px(0)))

    def restart_admin(self):
        if elevation.relaunch_as_admin():
            self.destroy()
        else:
            messagebox.showinfo(
                "SafeClean",
                "Elevation was declined. Windows Temp, servicing logs and the "
                "Update cache stay unavailable until you restart as administrator.",
                parent=self,
            )

    # -- scanning ----------------------------------------------------------

    def start_scan(self):
        if self.busy:
            return
        self._set_busy(True)
        self.cancel_event.clear()
        for child in self.scroll.content.winfo_children():
            child.destroy()
        self.findings, self.rows, self.selected = [], {}, {}
        self.active_row = None
        self._refresh_drive()
        self._update_summary()

        def work():
            try:
                active = rules.all_rules()
                problems = rules.audit_rules(active)
                if problems:
                    self.events.put(("audit_failed", problems))
                    return
                found = scanner.scan_all(
                    active,
                    progress=lambda d, n, label: self.events.put(
                        ("progress", (d, n, label))
                    ),
                    cancel=self.cancel_event,
                )
                self.events.put(("scan_done", (found, scanner.protected_inventory())))
            except Exception as exc:  # pragma: no cover - defensive
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        self.cancel_event.set()
        self.progress_label.configure(text="Cancelling...")

    def _set_busy(self, busy):
        self.busy = busy
        self.scan_button.set_enabled(not busy)
        self.cancel_button.set_enabled(busy)
        if busy:
            self.clean_button.set_enabled(False)
            self.dry_button.set_enabled(False)
        else:
            self._update_summary()

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    done, total, label = payload
                    self.meter.render(done / total if total else 0)
                    self.progress_label.configure(text=label)
                elif kind == "scan_done":
                    self.findings, self.protected = payload
                    self._populate()
                    self._set_busy(False)
                    self.meter.render(1.0, t.SAFE)
                    self.progress_label.configure(
                        text=f"Scanned {len(self.findings)} locations"
                    )
                elif kind == "clean_done":
                    self._on_clean_done(payload)
                elif kind == "audit_failed":
                    self._set_busy(False)
                    detail = "\n".join(f"{r}: {p}\n  {why}" for r, p, why in payload)
                    messagebox.showerror(
                        "SafeClean stopped",
                        "A cleanup rule points at a location the guard refuses. "
                        "This is a bug and scanning was aborted.\n\n" + detail,
                        parent=self,
                    )
                elif kind == "error":
                    self._set_busy(False)
                    messagebox.showerror("SafeClean", payload, parent=self)
        except queue.Empty:
            pass
        self.after(80, self._drain_events)

    # -- results -----------------------------------------------------------

    def _populate(self):
        for child in self.scroll.content.winfo_children():
            child.destroy()
        self.rows = {}

        grouped: dict[str, list[scanner.Finding]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.rule.category, []).append(finding)

        order = ["Windows", "Developer", "Browser"]
        for category in order + [c for c in grouped if c not in order]:
            items = grouped.get(category)
            if not items:
                continue
            items.sort(key=lambda f: f.size, reverse=True)
            total = sum(f.size for f in items)

            section = Section(
                self.scroll.content,
                category,
                f"{len(items)} items · {human(total)}",
            )
            section.pack(fill="x", pady=(t.px(0), t.px(18)))

            for index, finding in enumerate(items):
                if index:
                    divider(section.body).pack(fill="x")
                row = RuleRow(
                    section.body, finding,
                    on_toggle=self._on_toggle,
                    on_select=self._on_row_select,
                )
                row.pack(fill="x")
                self.rows[finding.rule.id] = row
                self.selected[finding.rule.id] = row.check.checked

        if self.protected:
            total = sum(p.size for p in self.protected)
            section = Section(
                self.scroll.content,
                "Protected — never deleted",
                f"{len(self.protected)} items · {human(total)}",
                collapsible=True,
                expanded=False,
            )
            section.pack(fill="x", pady=(t.px(0), t.px(18)))

            for index, item in enumerate(self.protected):
                if index:
                    divider(section.body).pack(fill="x")
                self._protected_row(section.body, item)

        self.scroll.scroll_to_top()
        self._update_summary()

    def _protected_row(self, parent, item):
        row = tk.Frame(parent, bg=t.SURFACE)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=t.SURFACE)
        inner.pack(fill="x", padx=t.px(14), pady=t.px(7))

        lock = CheckBox(inner, bg=t.SURFACE)
        lock.set_state(locked=True)
        lock.pack(side="left", padx=(t.px(0), t.px(12)))

        text = tk.Frame(inner, bg=t.SURFACE)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=item.label, bg=t.SURFACE, fg=t.TEXT_DIM,
                 font=t.font(9), anchor="w").pack(anchor="w")
        tk.Label(text, text=item.reason, bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.font(8), anchor="w").pack(anchor="w")

        tk.Label(inner, text=human(item.size), bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.font(9), width=10, anchor="e").pack(side="right")

    # -- selection ---------------------------------------------------------

    def _on_toggle(self, rule_id, checked):
        self.selected[rule_id] = checked
        self._update_summary()

    def _on_row_select(self, row):
        if self.active_row is row:
            return
        if self.active_row is not None:
            self.active_row.set_selected(False)
        self.active_row = row
        row.set_selected(True)
        self._show_details(row.finding)

    def select_safe(self):
        for finding in self.findings:
            if finding.rule.risk is Risk.SAFE and finding.cleanable:
                self.selected[finding.rule.id] = True
                self.rows[finding.rule.id].set_checked(True)
        self._update_summary()

    def clear_selection(self):
        for rule_id, row in self.rows.items():
            self.selected[rule_id] = False
            row.set_checked(False)
        self._update_summary()

    def _chosen(self):
        return [
            f for f in self.findings
            if self.selected.get(f.rule.id) and f.cleanable
        ]

    def _update_summary(self):
        chosen = self._chosen()
        total = sum(f.size for f in chosen)
        files = sum(f.file_count for f in chosen)
        if chosen:
            self.summary.configure(text=f"{human(total)} selected")
            self.summary_sub.configure(
                text=f"{files:,} files across {len(chosen)} locations"
            )
        else:
            self.summary.configure(text="Nothing selected")
            self.summary_sub.configure(text="Only safe items are ticked for you")
        enabled = bool(chosen) and not self.busy
        self.clean_button.set_enabled(enabled)
        self.dry_button.set_enabled(enabled)

    # -- details -----------------------------------------------------------

    def _show_details(self, finding):
        rule = finding.rule
        colour, _soft, label = RISK_STYLE[rule.risk]
        self.detail_title.configure(text=rule.label)
        self.detail_meta.configure(
            text=f"{label} · {human(finding.size)} · {finding.file_count:,} files",
            fg=colour,
        )
        self.detail_what.configure(text=rule.what)
        self.detail_cost.configure(text=rule.cost)

        self.detail_paths.configure(state="normal")
        self.detail_paths.delete("1.0", "end")
        if rule.special == "recycle_bin":
            self.detail_paths.insert("end", "All drives' Recycle Bins\n")
        for root in rule.roots:
            self.detail_paths.insert("end", f"{root}\n")
        if finding.skipped_protected:
            self.detail_paths.insert(
                "end",
                f"\n{finding.skipped_protected:,} files inside skipped as protected\n",
            )
        self.detail_paths.configure(state="disabled")
        self.preview_button.set_enabled(bool(finding.files))

    def preview_files(self):
        if self.active_row is None:
            return
        finding = self.active_row.finding
        if not finding.files:
            return

        win = tk.Toplevel(self, bg=t.BG)
        win.title(f"Files — {finding.rule.label}")
        win.geometry("940x560")
        win.configure(bg=t.BG)

        head = tk.Frame(win, bg=t.BG)
        head.pack(fill="x", padx=t.PAD_LG, pady=(t.px(20), t.px(12)))
        tk.Label(
            head, text=finding.rule.label, bg=t.BG, fg=t.TEXT,
            font=t.font(14, "bold", display=True),
        ).pack(anchor="w")
        tk.Label(
            head,
            text=(
                f"Showing {len(finding.files):,} of {finding.file_count:,} files "
                f"· {human(finding.size)} total"
            ),
            bg=t.BG, fg=t.TEXT_DIM, font=t.font(9),
        ).pack(anchor="w")

        holder = tk.Frame(win, bg=t.BORDER)
        holder.pack(fill="both", expand=True, padx=t.PAD_LG, pady=(t.px(0), t.px(20)))
        text = tk.Text(
            holder, wrap="none", relief="flat", bd=0, highlightthickness=0,
            bg=t.SURFACE, fg=t.TEXT_DIM, font=t.font(8, mono=True),
            padx=t.px(14), pady=t.px(12),
        )
        text.pack(fill="both", expand=True, padx=1, pady=1)
        for path, size in finding.files:
            text.insert("end", f"{human(size):>10}   {path}\n")
        text.configure(state="disabled")

    # -- cleaning ----------------------------------------------------------

    def start_dry_run(self):
        self._run_clean(dry_run=True)

    def start_clean(self):
        chosen = self._chosen()
        if not chosen:
            return
        permanent = {f.rule.id for f in chosen if not f.rule.recycle}
        if not confirm.ask(self, chosen, permanent):
            return
        self._run_clean(dry_run=False)

    def _run_clean(self, dry_run):
        chosen = self._chosen()
        if not chosen or self.busy:
            return
        self._set_busy(True)
        self.cancel_event.clear()

        def work():
            try:
                result = cleaner.clean(
                    chosen, dry_run=dry_run,
                    progress=lambda d, n, label: self.events.put(
                        ("progress", (d, n, label))
                    ),
                    cancel=self.cancel_event,
                )
                self.events.put(("clean_done", (result, report.write(result))))
            except Exception as exc:  # pragma: no cover - defensive
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _on_clean_done(self, payload):
        result, log_path = payload
        self._set_busy(False)
        self._refresh_drive()

        lines = [
            f"{'Would free' if result.dry_run else 'Freed'}: {human(result.freed)}",
            f"Files: {result.deleted:,}",
        ]
        if result.locked:
            lines.append(f"Skipped (in use): {result.locked:,}")
        if result.refused:
            lines.append(f"Blocked by the guard: {result.refused:,}")
        lines.append(f"\nLog: {log_path}")
        body = "\n".join(lines)
        if result.dry_run:
            body += "\n\nNothing was deleted. Use 'Clean selected' to do it for real."

        messagebox.showinfo(
            "Dry run complete" if result.dry_run else "Cleanup complete",
            body, parent=self,
        )
        if not result.dry_run:
            self.start_scan()


def main():
    SafeCleanApp().mainloop()


if __name__ == "__main__":
    main()
