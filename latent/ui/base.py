"""Common base for the three stage views."""
from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

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

    def show(self):
        self.visible = True
        self.viewport.pack(fill="both", expand=True)
        self.panel.pack(fill="both", expand=True)
        self.on_show()
        self.refresh_status()

    def hide(self):
        self.visible = False
        self.viewport.pack_forget()
        self.panel.pack_forget()
        self.on_hide()

    # hooks
    def on_show(self):
        pass

    def on_hide(self):
        pass

    def on_photo_changed(self):
        pass

    def refresh_status(self):
        pass

    def on_key(self, seq: str, event: tk.Event):
        pass

    # helpers
    def pad(self, n=20) -> int:
        return self.ui.px(n)
