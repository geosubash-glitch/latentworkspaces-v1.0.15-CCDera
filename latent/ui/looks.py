"""Stage 2 - Grid: evaluate all emulsion profiles on the mounted photo."""
from __future__ import annotations

import os

import cv2
import tkinter as tk

from .. import theme as T
from ..imaging.filters import PROFILES, FILTER_REGISTRY, PROFILE_KEYS
from ..imaging.pipeline import apply_profile, make_proxy
from ..workers import Channel
from .base import PreviewBox, ReadoutBox, View, gap
from .grid import ThumbGrid
from .widgets import Button, bgr_to_photo


class LooksView(View):
    def __init__(self, app):
        super().__init__(app)
        ui = self.ui
        self.grid_channel = Channel(app.dispatcher, "looks-grid")
        self.preview_channel = Channel(app.dispatcher, "looks-preview")
        self._thumb_base = None
        self._preview_base = None
        self._preview_photo = None
        self._hover = None
        self._preview_cache = {}

        # viewport: 5 x 3 board of numbered cells filling the frame
        self.grid = ThumbGrid(self.viewport, ui, app.router, on_select=lambda i: self._refresh(),
                              on_activate=self._on_activate, on_hover=self._on_hover,
                              cols=5, rows=3, numbered=True, bar=self.bar)
        self.grid.pack(fill="both", expand=True)
        self.grid.set_items([p.key for p in PROFILES])
        self.grid.set_selected(0, ensure_visible=False)

        self.top = ReadoutBox(self.panel, ui)
        self.top.pack(fill="x")
        self.readout, self.notice_lbl = self.top.text, self.top.notice
        Button(self.top.actions, ui, "WORKBENCH", command=self._develop).pack(side="right")
        Button(self.top.actions, ui, "BACK", command=lambda: app.go("library")).pack(side="right", padx=(0, ui.px(10)))
        self.previewbox = PreviewBox(self.panel, ui)
        self.previewbox.pack(fill="both", expand=True, pady=(gap(ui), 0))
        self.preview, self.preview_name = self.previewbox.image, self.previewbox.name
        self.preview.bind("<Double-Button-1>", lambda e: self._develop())
        self.previewbox.bind("<Configure>", lambda e: self._update_preview())

    # --------------------------------------------------------------- data
    def on_photo_changed(self):
        proxy = self.app.session.proxy
        self._thumb_base = make_proxy(proxy, self.ui.px(360))
        self._preview_base = make_proxy(proxy, max(self.ui.px(620), 560))
        self._preview_cache.clear()
        self.grid.set_selected(PROFILE_KEYS.index(self.app.session.state.profile), ensure_visible=False)
        self.grid.clear_images()
        self._hover = None

    def _render_grid(self):
        if self._thumb_base is None:
            return
        base, state = self._thumb_base, self.app.session.state.copy()
        selected = self.grid.selected or 0

        def job(token):
            # outward from the selected cell so the area in focus fills in first
            for i in sorted(range(len(PROFILE_KEYS)), key=lambda k: abs(k - selected)):
                if token.cancelled:
                    return
                self.app.dispatcher.post(self.grid.set_image, i, apply_profile(base, state, PROFILE_KEYS[i]))

        self.grid_channel.submit(job, cancel_running=True)

    # ------------------------------------------------------------ preview
    def _current_key(self):
        i = self._hover if self._hover is not None else self.grid.selected
        return PROFILE_KEYS[i if i is not None else 0]

    def _box_size(self):
        return self.previewbox.inner_size()

    def _update_preview(self):
        if self._preview_base is None:
            return
        # keyed by look and box size: a render made before layout or a resize
        # must never be shown at the wrong size
        box, key = self._box_size(), self._current_key()
        cached = self._preview_cache.get((key, box))
        if cached is not None:
            self._show(cached)
            return
        base, state = self._preview_base, self.app.session.state.copy()
        bw, bh = box

        def job(_t):
            out = apply_profile(base, state, key)
            h, w = out.shape[:2]
            s = min(bw / w, bh / h)
            out = cv2.resize(out, (max(1, int(w * s)), max(1, int(h * s))),
                             interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            return (key, box), out

        def done(res):
            cache_key, img = res
            if len(self._preview_cache) > 40:
                self._preview_cache.clear()
            self._preview_cache[cache_key] = img
            if cache_key == (self._current_key(), self._box_size()):
                self._show(img)

        self.preview_channel.submit(job, done)

    def _show(self, bgr):
        self._preview_photo = bgr_to_photo(bgr)
        self.preview.config(image=self._preview_photo)

    def _refresh(self):
        key = self._current_key()
        prof = FILTER_REGISTRY[key]
        path = self.app.session.path or ""
        stem = os.path.splitext(os.path.basename(path))[0].upper()
        self.readout.config(text=f"FILE:{stem}\nFILTER:{key}\n\nSPEC:{prof.description}")
        self.preview_name.config(text=f"{stem} // {key}")
        self._update_preview()

    # ----------------------------------------------------------- interact
    def _on_hover(self, idx):
        self._hover = idx
        self._refresh()

    def _on_activate(self, idx):
        self.grid.set_selected(idx)
        self._develop()

    def _develop(self):
        i = self.grid.selected
        if i is None:
            return
        key = PROFILE_KEYS[i]
        session = self.app.session
        if session.state.profile != key:
            session.push_undo()
            session.state.profile = key
        self.app.go("develop")

    # --------------------------------------------------------------- hooks
    def on_show(self):
        self.grid.set_selected(PROFILE_KEYS.index(self.app.session.state.profile), ensure_visible=False)
        self._preview_cache.clear()  # profile parameters may have changed in the workbench
        self._render_grid()
        self._hover = None
        self._refresh()
        self.grid.canvas.focus_set()

    def on_key(self, seq, e):
        moves = {"<Left>": (-1, 0), "<Right>": (1, 0), "<Up>": (0, -1), "<Down>": (0, 1)}
        if seq in moves:
            self._hover = None
            self.grid.move(*moves[seq])
        elif seq in ("<Return>", "<KP_Enter>"):
            self._develop()
        elif seq == "<BackSpace>":
            self.app.go("library")
