"""Common base for the three stages and the shared panel blocks."""
from __future__ import annotations

import tkinter as tk
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
        from .widgets import Scrollbar
        self.bar = Scrollbar(app.scroll_strip, app.ui)
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
# Panel blocks on the shared rows: top box 20..210, bar 230..270, content 290..1060
# --------------------------------------------------------------------------
class ReadoutBox(tk.Frame):
    """Top box: the 22.68px Courier readout (PATH: / FILTER: ...)."""

    def __init__(self, parent, ui):
        super().__init__(parent, bg=T.BG, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE,
                         height=ui.px(T.TOP_BOX_H))
        self.pack_propagate(False)
        pad = ui.px(13)
        self.text = tk.Label(self, text="", bg=T.BG, fg=T.TEXT, font=ui.fonts.readout, justify="left", anchor="nw")
        self.text.pack(fill="both", expand=True, padx=pad, pady=(ui.px(12), 0))
        self.notice = tk.Label(self, text="", bg=T.BG, fg=T.YELLOW, font=ui.fonts.label)
        self.notice.place(relx=1.0, rely=1.0, x=-pad, y=-ui.px(6), anchor="se")
        self.bind("<Configure>", lambda e: self.text.config(wraplength=max(50, e.width - 2 * pad - 4)))


class PreviewBox(tk.Frame):
    """Content box: image well with the file name in the bottom-left corner."""

    def __init__(self, parent, ui):
        super().__init__(parent, bg=T.BG, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE)
        self.pack_propagate(False)
        self.ui = ui
        self.name = tk.Label(self, text="", bg=T.BG, fg=T.TEXT, font=ui.fonts.cell, anchor="w")
        self.name.pack(side="bottom", fill="x", padx=ui.px(13), pady=(0, ui.px(8)))
        self.image = tk.Label(self, bg=T.BG, bd=0)
        self.image.pack(fill="both", expand=True, padx=ui.px(14), pady=(ui.px(14), ui.px(4)))

    def inner_size(self):
        return max(self.image.winfo_width(), 50), max(self.image.winfo_height(), 50)


def gap(ui) -> int:
    return ui.px(T.GUTTER)
