"""Stage 2 - Look: compare all film profiles on the mounted photo."""
from __future__ import annotations

import os

import cv2
import tkinter as tk

from .. import theme as T
from ..imaging.filters import PROFILES, FILTER_REGISTRY, PROFILE_KEYS
from ..imaging.pipeline import apply_profile, make_proxy
from ..workers import Channel
from .base import View
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
        self._grid_dirty = True
        self._hover = None
        self._preview_cache = {}

        self.grid = ThumbGrid(self.viewport, ui, app.router, on_select=self._on_select, on_activate=self._on_activate,
                              on_hover=self._on_hover, aspect=1.0, fit_all=True)
        self.grid.pack(fill="both", expand=True)
        self.grid.set_items([p.name.upper() for p in PROFILES], [p.tag.upper() for p in PROFILES],
                            [f"{i + 1:02d}" for i in range(len(PROFILES))])
        self.grid.set_selected(0, ensure_visible=False)

        p = tk.Frame(self.panel, bg=T.BG_PANEL)
        p.pack(fill="both", expand=True, padx=ui.px(20), pady=(ui.px(22), ui.px(20)))
        self.file_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro, anchor="w")
        self.file_lbl.pack(fill="x")
        self.index_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.ACCENT, font=ui.fonts.label, anchor="w")
        self.index_lbl.pack(fill="x", pady=(ui.px(12), 0))
        self.name_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.TEXT_HI, font=ui.fonts.display, anchor="w",
                                 justify="left", wraplength=app.panel_width - ui.px(40))
        self.name_lbl.pack(fill="x", pady=(ui.px(2), ui.px(6)))
        self.desc_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.TEXT, font=ui.fonts.body, anchor="nw", justify="left",
                                 wraplength=app.panel_width - ui.px(40))
        self.desc_lbl.pack(fill="x")
        self.grain_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.micro, anchor="w")
        self.grain_lbl.pack(fill="x", pady=(ui.px(8), ui.px(14)))

        row = tk.Frame(p, bg=T.BG_PANEL)
        row.pack(side="bottom", fill="x")
        Button(row, ui, "←", command=lambda: app.go("library"), padx=12, pady=10, tooltip="Back to library (Esc)").pack(side="left")
        Button(row, ui, "DEVELOP WITH THIS LOOK   →", command=self._develop, style="primary", pady=10).pack(side="left", fill="x", expand=True, padx=(ui.px(6), 0))
        tk.Label(p, text="Hover to preview  ·  Enter to develop", bg=T.BG_PANEL, fg=T.TEXT_FAINT,
                 font=ui.fonts.micro).pack(side="bottom", pady=(ui.px(8), ui.px(8)))

        box = tk.Frame(p, bg=T.BG_VIEW)
        box.pack(fill="both", expand=True)
        box.pack_propagate(False)
        self.preview = tk.Label(box, bg=T.BG_VIEW, fg=T.TEXT_FAINT, font=ui.fonts.body_small)
        self.preview.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.preview.bind("<Double-Button-1>", lambda e: self._develop())
        box.bind("<Configure>", lambda e: self._on_preview_resize())
        self._update_info()

    # --------------------------------------------------------------- data
    def on_photo_changed(self):
        proxy = self.app.session.proxy
        self._thumb_base = make_proxy(proxy, self.ui.px(360))
        self._preview_base = make_proxy(proxy, max(self.ui.px(560), 480))
        self._preview_cache.clear()
        self._grid_dirty = True
        h, w = proxy.shape[:2]
        # cells take the photo's shape so thumbnails fill them without bars
        self.grid.aspect = min(1.6, max(0.75, w / float(h)))
        self.grid.images.clear()
        self.grid._photos.clear()
        key = self.app.session.state.profile
        self.grid.set_selected(PROFILE_KEYS.index(key), ensure_visible=False)
        self.grid.relayout()
        self._hover = None

    def _render_grid(self):
        if self._thumb_base is None:
            return
        base = self._thumb_base
        state = self.app.session.state.copy()
        self._grid_dirty = False
        selected = self.grid.selected or 0

        def job(token):
            # render outward from the selected look so the eye's focus fills in first
            order = sorted(range(len(PROFILE_KEYS)), key=lambda i: abs(i - selected))
            for i in order:
                if token.cancelled:
                    return
                out = apply_profile(base, state, PROFILE_KEYS[i])
                self.app.dispatcher.post(self.grid.set_image, i, out)

        self.grid_channel.submit(job, cancel_running=True)

    # ------------------------------------------------------------ preview
    def _current_key(self):
        i = self._hover if self._hover is not None else self.grid.selected
        return PROFILE_KEYS[i if i is not None else 0]

    def _on_preview_resize(self):
        self._update_preview()

    def _box_size(self):
        return max(self.preview.winfo_width(), 50), max(self.preview.winfo_height(), 50)

    def _update_preview(self):
        if self._preview_base is None:
            return
        # Cache by look *and* box size: a render made before the panel was laid
        # out (or before a resize) must never be shown at the wrong size.
        box = self._box_size()
        key = self._current_key()
        cached = self._preview_cache.get((key, box))
        if cached is not None:
            self._show(cached)
            return
        base = self._preview_base
        state = self.app.session.state.copy()
        box_w, box_h = box

        def job(_t):
            out = apply_profile(base, state, key)
            h, w = out.shape[:2]
            s = min(box_w / w, box_h / h)
            out = cv2.resize(out, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
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
        self.preview.config(image=self._preview_photo, text="")

    def _update_info(self):
        key = self._current_key()
        prof = FILTER_REGISTRY[key]
        i = PROFILE_KEYS.index(key)
        self.index_lbl.config(text=f"{i + 1:02d} / {len(PROFILES):02d}   ·   {prof.tag.upper()}")
        self.name_lbl.config(text=prof.name.upper())
        self.desc_lbl.config(text=prof.description)
        grain = {"fine": "Fine", "midtone": "Midtone", "heavy": "Heavy"}[prof.grain_type]
        self.grain_lbl.config(text=f"GRAIN · {grain.upper()}{'  ·  MONOCHROME' if prof.mono else ''}")
        path = self.app.session.path
        self.file_lbl.config(text=os.path.basename(path).upper() if path else "")

    # ----------------------------------------------------------- interact
    def _on_hover(self, idx):
        self._hover = idx
        self._update_info()
        self._update_preview()

    def _on_select(self, idx):
        self._update_info()
        self._update_preview()

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
        key = self.app.session.state.profile
        self.grid.set_selected(PROFILE_KEYS.index(key), ensure_visible=False)
        # profile parameters may have been edited in Develop
        self._preview_cache.clear()
        self._render_grid()
        self._hover = None
        self._update_info()
        self._update_preview()
        self.grid.canvas.focus_set()

    def refresh_status(self):
        if not self.visible:
            return
        path = self.app.session.path or ""
        self.app.set_status(f"{os.path.basename(path)}  ·  {len(PROFILES)} film looks",
                            "Hover to preview  ·  Enter to develop  ·  Esc back")

    def on_key(self, seq, e):
        moves = {"<Left>": (-1, 0), "<Right>": (1, 0), "<Up>": (0, -1), "<Down>": (0, 1)}
        if seq in moves:
            self._hover = None
            self.grid.move(*moves[seq])
        elif seq in ("<Return>", "<KP_Enter>"):
            self._develop()
        elif seq == "<BackSpace>":
            self.app.go("library")
