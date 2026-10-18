"""Stage 1 - Explorer: mount a folder and pick a photo."""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from typing import List, Optional

import cv2
import tkinter as tk

from .. import theme as T
from ..imaging import io as imgio
from ..workers import Channel
from .base import View, preview_box, readout_box
from .grid import ThumbGrid
from .widgets import Button, bgr_to_photo

THUMB_CACHE_LIMIT = 800
POLL_MS = 2000


class LibraryView(View):
    def __init__(self, app):
        super().__init__(app)
        ui = self.ui
        self.files: List[imgio.ImageInfo] = []
        self.dims = {}
        self.cache: "OrderedDict[str, tuple]" = OrderedDict()
        self.thumb_channel = Channel(app.dispatcher, "thumbs")
        self.preview_channel = Channel(app.dispatcher, "preview")
        self._signature = None
        self._poll_after = None
        self._preview_photo = None
        self._generation = 0
        self._loaded_folder = None

        # viewport: five columns of square cells
        self.grid = ThumbGrid(self.viewport, ui, app.router, on_select=lambda i: self._update_selection_panel(),
                              on_activate=self._on_activate, on_visible=self._request_thumbs, cols=5, gap=7)
        self.grid.pack(fill="both", expand=True)
        self.empty = tk.Label(self.viewport, text="NO COMPATIBLE IMAGE FILES FOUND IN DIRECTORY", bg=T.BG_VIEW,
                              fg="#646464", font=ui.fonts.value)

        # control column
        p = tk.Frame(self.panel, bg=T.BG_PANEL)
        p.pack(fill="both", expand=True, padx=(ui.px(40), 0), pady=(ui.px(20), 0))
        box, self.readout, self.notice_lbl = readout_box(p, ui, 158)
        box.pack(fill="x")
        Button(p, ui, "NAVIGATE", command=app.choose_folder).pack(fill="x", pady=(ui.px(20), ui.px(20)), ipady=ui.px(4))
        self.preview_frame, self.preview, self.preview_name = preview_box(p, ui)
        self.preview_frame.pack(fill="both", expand=True)
        self.preview.bind("<Double-Button-1>", lambda e: self._open_selected())
        self.preview_frame.bind("<Configure>", lambda e: self._update_preview())

        self.load_folder()

    # --------------------------------------------------------------- folder
    def load_folder(self):
        folder = self.app.folder
        self._generation += 1
        self.thumb_channel.cancel()
        prev_path = self.selected_path
        same_folder = self._loaded_folder == folder
        self._loaded_folder = folder
        self.files = imgio.list_images(folder)
        self._signature = self._folder_signature(self.files)
        paths = [f.path for f in self.files]
        self.grid.set_items([f.name for f in self.files], reset_scroll=not same_folder)
        for i, f in enumerate(self.files):
            hit = self.cache.get(f.path)
            if hit and hit[0] == f.mtime:
                self.grid.set_image(i, hit[1])
        if prev_path in paths:
            self.grid.set_selected(paths.index(prev_path), ensure_visible=not same_folder)
        else:
            self.grid.set_selected(None)
        if self.files:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self._update_selection_panel()

    @staticmethod
    def _folder_signature(files):
        return tuple((f.name, f.mtime, f.size_bytes) for f in files)

    def _poll(self):
        self._poll_after = None
        if not self.visible:
            return
        if self._folder_signature(imgio.list_images(self.app.folder)) != self._signature:
            self.load_folder()
        self._poll_after = self.viewport.after(POLL_MS, self._poll)

    # ------------------------------------------------------------ thumbnails
    def _request_thumbs(self, first: int, last: int):
        if not self.files:
            return
        span = max(1, last - first)
        lo, hi = max(0, first - span), min(len(self.files), last + span * 2)
        wanted = []
        for i in list(range(first, last)) + list(range(lo, first)) + list(range(last, hi)):
            f = self.files[i]
            hit = self.cache.get(f.path)
            if not hit or hit[0] != f.mtime:
                wanted.append((i, f.path, f.mtime))
        if not wanted:
            return
        gen, edge = self._generation, self.ui.px(320)

        def job(token):
            for i, path, mtime in wanted:
                if token.cancelled:
                    return
                try:
                    bgr, w, h = imgio.load_thumbnail(path, edge)
                except Exception:
                    continue
                self.app.dispatcher.post(self._thumb_ready, gen, i, path, mtime, bgr, (w, h))

        self.thumb_channel.submit(job, cancel_running=True)

    def _thumb_ready(self, gen, i, path, mtime, bgr, dims):
        if gen != self._generation:
            return
        self.cache[path] = (mtime, bgr)
        self.cache.move_to_end(path)
        while len(self.cache) > THUMB_CACHE_LIMIT:
            self.cache.popitem(last=False)
        self.dims[path] = dims
        if i < len(self.files) and self.files[i].path == path:
            self.grid.set_image(i, bgr)
            if i == self.grid.selected:
                self._update_selection_panel()

    # -------------------------------------------------------------- select
    @property
    def selected_path(self) -> Optional[str]:
        i = self.grid.selected
        return self.files[i].path if i is not None and i < len(self.files) else None

    def _on_activate(self, i):
        self.grid.set_selected(i)
        self._open_selected()

    def _open_selected(self):
        if self.selected_path:
            self.app.open_photo(self.selected_path)

    def _update_selection_panel(self):
        folder = self.app.folder
        path_txt = folder if len(folder) < 52 else "..." + folder[-49:]
        text = f"MOUNT TARGET:\n{path_txt}\n\n"
        i = self.grid.selected
        if i is None or i >= len(self.files):
            n = len(self.files)
            text += f"VOLUME MOUNTED. {n} FILE{'S' if n != 1 else ''}.\nSELECT SOURCE FILE ELEMENT."
        else:
            f = self.files[i]
            d = self.dims.get(f.path)
            text += f"FILE ID: {f.name.upper()}\nALLOCATION: {f.size_bytes / (1024 * 1024):.2f} MB"
            if d:
                text += f"\nDIMENSIONS: {d[0]} x {d[1]}"
            if self.app.session.has_edits_for(f.path):
                text += "\nSTATE: GRADED (SESSION)"
        self.readout.config(text=text)
        self._update_preview()

    def _update_preview(self):
        f = self.files[self.grid.selected] if self.grid.selected is not None and self.grid.selected < len(self.files) else None
        if f is None:
            self._preview_photo = None
            self.preview.config(image="")
            self.preview_name.config(text="")
            return
        self.preview_name.config(text=f.name.upper())
        hit = self.cache.get(f.path)
        if hit:
            self._show_preview(hit[1])
        path = f.path
        edge = max(self.preview.winfo_width(), self.preview.winfo_height(), 200)

        def job(_t):
            return path, imgio.load_thumbnail(path, edge)[0]

        def done(res):
            if res[0] == self.selected_path:
                self._show_preview(res[1])

        self.preview_channel.submit(job, done)

    def _show_preview(self, bgr):
        bw = max(self.preview.winfo_width() - self.ui.px(30), 50)
        bh = max(self.preview.winfo_height() - self.ui.px(30), 50)
        h, w = bgr.shape[:2]
        s = min(bw / w, bh / h)
        img = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        self._preview_photo = bgr_to_photo(img)
        self.preview.config(image=self._preview_photo)

    # --------------------------------------------------------------- hooks
    def on_show(self):
        self._update_selection_panel()
        if self._poll_after is None:
            self._poll_after = self.viewport.after(POLL_MS, self._poll)
        self.grid.canvas.focus_set()

    def on_hide(self):
        if self._poll_after:
            self.viewport.after_cancel(self._poll_after)
            self._poll_after = None

    def on_key(self, seq, e):
        moves = {"<Left>": (-1, 0), "<Right>": (1, 0), "<Up>": (0, -1), "<Down>": (0, 1)}
        if seq in moves:
            self.grid.move(*moves[seq])
        elif seq in ("<Return>", "<KP_Enter>"):
            self._open_selected()
        elif seq == "<F5>":
            self.load_folder()
