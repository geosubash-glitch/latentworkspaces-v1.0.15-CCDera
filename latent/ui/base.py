"""Common base for the three stage views."""
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
        self.viewport = tk.Frame(app.viewport_host, bg=T.BG_VIEW)
        self.panel = tk.Frame(app.panel_host, bg=T.BG_PANEL)
        self.visible = False
        self.notice_lbl: Optional[tk.Label] = None
        self._notice_after = None

    def show(self):
        self.visible = True
        self.viewport.pack(fill="both", expand=True)
        self.panel.pack(fill="both", expand=True)
        self.on_show()

    def hide(self):
        self.visible = False
        self.viewport.pack_forget()
        self.panel.pack_forget()
        self.on_hide()

    def notice(self, message: str, ms: int = 5000):
        """One-line message in the view's readout area (replaces a status bar)."""
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
# Panel building blocks shared by the stages (original v1 layout)
# --------------------------------------------------------------------------
def readout_box(parent, ui, height: int):
    """Bordered text readout ("MOUNT TARGET: ...")."""
    box = tk.Frame(parent, bg=T.BG_PANEL, highlightthickness=1, highlightbackground=T.BOX, height=ui.px(height))
    box.pack_propagate(False)
    lbl = tk.Label(box, text="", bg=T.BG_PANEL, fg=T.TEXT, font=ui.fonts.readout, justify="left", anchor="nw")
    lbl.pack(fill="both", expand=True, padx=ui.px(20), pady=(ui.px(15), ui.px(4)))
    notice = tk.Label(box, text="", bg=T.BG_PANEL, fg=T.SELECT, font=ui.fonts.label, anchor="w")
    notice.pack(fill="x", padx=ui.px(20), pady=(0, ui.px(8)))
    box.bind("<Configure>", lambda e: lbl.config(wraplength=max(50, e.width - ui.px(44))))
    return box, lbl, notice


def preview_box(parent, ui):
    """Bordered preview well with the file name in the bottom-left corner."""
    box = tk.Frame(parent, bg=T.BG_PANEL, highlightthickness=1, highlightbackground=T.BOX)
    box.pack_propagate(False)
    img = tk.Label(box, bg=T.BG_PANEL, bd=0)
    img.place(relx=0, rely=0, relwidth=1, relheight=0.94)
    name = tk.Label(box, text="", bg=T.BG_PANEL, fg=T.TEXT, font=ui.fonts.value, anchor="w")
    name.place(relx=0.03, rely=0.97, anchor="w")
    return box, img, name
