"""Common base for the three stages and the shared panel blocks."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Optional

from .. import theme as T

if TYPE_CHECKING:  # pragma: no cover
    from ..app import LatentApp


class View:
    def __init__(self, app: "LatentApp"):
        self.app = app
        self.ui = app.ui
        self.viewport = tk.Frame(app.viewport_host, bg=T.BG)
        self.panel = tk.Frame(app.panel_host, bg=T.BG)
        # every stage shows a scrollbar in the shared slot, scrolling or not
        self.bar = ttk.Scrollbar(app.scroll_strip, orient="vertical")
        self.bar.set(0.0, 1.0)
        self.visible = False
        self.notice_lbl: Optional[tk.Label] = None
        self._notice_after = None

    def show(self):
        self.visible = True
        self.viewport.pack(fill="both", expand=True)
        self.panel.pack(fill="both", expand=True)
        self.bar.pack(fill="both", expand=True)
        self.on_show()

    def hide(self):
        self.visible = False
        self.viewport.pack_forget()
        self.panel.pack_forget()
        self.bar.pack_forget()
        self.on_hide()

    def notice(self, message: str, ms: int = 5000):
        """One-line message at the foot of the top box."""
        if self.notice_lbl is None:
            return
        self.notice_lbl.config(text=message.upper())
        if self._notice_after:
            self.notice_lbl.after_cancel(self._notice_after)
        self._notice_after = self.notice_lbl.after(ms, lambda: self.notice_lbl.config(text=""))

    # hooks
    def on_show(self):
        pass

    def on_hide(self):
        pass

    def on_photo_changed(self):
        pass

    def on_key(self, seq: str, event: tk.Event):
        pass


# --------------------------------------------------------------------------
# Panel blocks: the top box (y 20..259) and the bottom box (279..1060)
# --------------------------------------------------------------------------
class ReadoutBox(tk.Frame):
    """Top box: large readout text, a notice line and an action row."""

    def __init__(self, parent, ui):
        super().__init__(parent, bg=T.BG, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE, height=ui.px(T.TOP_BOX_H))
        self.pack_propagate(False)
        pad = ui.px(13)
        self.actions = tk.Frame(self, bg=T.BG)
        self.actions.pack(side="bottom", fill="x", padx=pad, pady=(0, pad))
        self.notice = tk.Label(self, text="", bg=T.BG, fg=T.YELLOW, font=ui.fonts.label, anchor="w")
        self.notice.pack(side="bottom", fill="x", padx=pad, pady=(0, ui.px(6)))
        self.text = tk.Label(self, text="", bg=T.BG, fg=T.TEXT, font=ui.fonts.readout, justify="left", anchor="nw")
        self.text.pack(fill="both", expand=True, padx=pad, pady=(ui.px(10), 0))
        self.bind("<Configure>", lambda e: self.text.config(wraplength=max(50, e.width - 2 * pad - 4)))


class PreviewBox(tk.Frame):
    """Bottom box: an image well with the file name in the bottom-left corner."""

    def __init__(self, parent, ui):
        super().__init__(parent, bg=T.BG, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE)
        self.pack_propagate(False)
        self.ui = ui
        self.name = tk.Label(self, text="", bg=T.BG, fg=T.TEXT, font=ui.fonts.cell, anchor="w")
        self.name.pack(side="bottom", fill="x", padx=ui.px(13), pady=(0, ui.px(10)))
        self.image = tk.Label(self, bg=T.BG, bd=0)
        self.image.pack(fill="both", expand=True, padx=ui.px(13), pady=(ui.px(13), ui.px(4)))

    def inner_size(self):
        return max(self.image.winfo_width(), 50), max(self.image.winfo_height(), 50)


def gap(ui) -> int:
    return ui.px(T.GUTTER)
