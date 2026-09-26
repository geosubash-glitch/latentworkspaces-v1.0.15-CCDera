"""Stage 1 - Library: pick a folder and a photo."""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from typing import List, Optional

import tkinter as tk

from .. import theme as T
from ..imaging import io as imgio
from ..workers import Channel
from .base import View
from .grid import ThumbGrid
from .widgets import Button, bgr_to_photo

THUMB_CACHE_LIMIT = 800
POLL_MS = 2000


class LibraryView(View):
    def __init__(self, app):
        super().__init__(app)
        ui = self.ui
        self.files: List[imgio.ImageInfo] = []
        self.dims = {}  # path -> (w, h)
        self.cache: "OrderedDict[str, tuple]" = OrderedDict()  # path -> (mtime, bgr)
        self.thumb_channel = Channel(app.dispatcher, "thumbs")
        self.preview_channel = Channel(app.dispatcher, "preview")
        self._signature = None
        self._poll_after = None
        self._preview_photo = None
        self._generation = 0

        # viewport
        self.grid = ThumbGrid(self.viewport, ui, app.router, on_select=self._on_select, on_activate=self._on_activate,
                              on_visible=self._request_thumbs, min_cell=190, aspect=1.25)
        self.grid.pack(fill="both", expand=True)
        self.empty = tk.Frame(self.viewport, bg=T.BG_VIEW)
        tk.Label(self.empty, text="NO PHOTOS HERE", bg=T.BG_VIEW, fg=T.TEXT_HI, font=ui.fonts.title).pack()
        self.empty_detail = tk.Label(self.empty, text="", bg=T.BG_VIEW, fg=T.TEXT_DIM, font=ui.fonts.body, justify="center")
        self.empty_detail.pack(pady=(ui.px(8), ui.px(18)))
        Button(self.empty, ui, "CHOOSE FOLDER…", command=app.choose_folder, style="primary").pack()

        # panel
        p = tk.Frame(self.panel, bg=T.BG_PANEL)
        p.pack(fill="both", expand=True, padx=ui.px(20), pady=(ui.px(22), ui.px(20)))

        tk.Label(p, text="FOLDER", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.label, anchor="w").pack(fill="x")
        self.folder_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.TEXT, font=ui.fonts.mono, anchor="w", justify="left",
                                   wraplength=app.panel_width - ui.px(40))
        self.folder_lbl.pack(fill="x", pady=(ui.px(4), 0))
        self.count_lbl = tk.Label(p, text="", bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.micro, anchor="w")
        self.count_lbl.pack(fill="x", pady=(ui.px(2), ui.px(10)))
        row = tk.Frame(p, bg=T.BG_PANEL)
        row.pack(fill="x")
        Button(row, ui, "CHOOSE FOLDER…", command=app.choose_folder, tooltip=f"Open a folder of photos").pack(side="left", fill="x", expand=True)
        Button(row, ui, "↻", command=self.load_folder, style="secondary", padx=10, tooltip="Refresh (F5)").pack(side="left", padx=(ui.px(6), 0))

        tk.Frame(p, bg=T.LINE, height=1).pack(fill="x", pady=ui.px(18))

        self.open_btn = Button(p, ui, "OPEN PHOTO   →", command=self._open_selected, style="primary", pady=10)
        self.open_btn.pack(side="bottom", fill="x")
        self.hint = tk.Label(p, text="Double-click a photo or press Enter", bg=T.BG_PANEL, fg=T.TEXT_FAINT,
                             font=ui.fonts.micro)
        self.hint.pack(side="bottom", pady=(0, ui.px(8)))

        self.meta = tk.Frame(p, bg=T.BG_PANEL)
        self.meta.pack(side="bottom", fill="x", pady=(ui.px(14), ui.px(18)))
        self.meta_rows = {}
        for key in ("NAME", "DIMENSIONS", "FILE SIZE", "MODIFIED"):
            r = tk.Frame(self.meta, bg=T.BG_PANEL)
            r.pack(fill="x", pady=ui.px(2))
            tk.Label(r, text=key, bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro, width=12, anchor="w").pack(side="left")
            v = tk.Label(r, text="—", bg=T.BG_PANEL, fg=T.TEXT, font=ui.fonts.mono, anchor="w")
            v.pack(side="left", fill="x", expand=True)
            self.meta_rows[key] = v

        # Fixed-size box so the preview image never pushes the panel layout around.
        box = tk.Frame(p, bg=T.BG_VIEW)
        box.pack(fill="both", expand=True)
        box.pack_propagate(False)
        self.preview = tk.Label(box, bg=T.BG_VIEW, text="Select a photo to preview", fg=T.TEXT_FAINT, font=ui.fonts.body_small)
        self.preview.place(relx=0, rely=0, relwidth=1, relheight=1)
        box.bind("<Configure>", lambda e: self._update_selection_panel())
        self.preview.bind("<Double-Button-1>", lambda e: self._open_selected())

        self.load_folder()

    # --------------------------------------------------------------- folder
    def load_folder(self):
        folder = self.app.folder
        self._generation += 1
        self.thumb_channel.cancel()
        prev_path = self.selected_path
        same_folder = getattr(self, "_loaded_folder", None) == folder
        self._loaded_folder = folder
        self.files = imgio.list_images(folder)
        self._signature = self._folder_signature()
        paths = [f.path for f in self.files]
        self.grid.set_items([f.name for f in self.files], [self._subtitle(f) for f in self.files],
                            reset_scroll=not same_folder)
        for i, f in enumerate(self.files):
            hit = self.cache.get(f.path)
            if hit and hit[0] == f.mtime:
                self.grid.set_image(i, hit[1])
        if prev_path in paths:
            self.grid.set_selected(paths.index(prev_path), ensure_visible=not same_folder)
        elif self.files:
            self.grid.set_selected(0, ensure_visible=False)
        else:
            self.grid.set_selected(None)

        pretty = folder.replace(os.path.expanduser("~"), "~", 1)
        self.folder_lbl.config(text=pretty)
        n = len(self.files)
        self.count_lbl.config(text=f"{n} photo{'s' if n != 1 else ''}")
        if n == 0:
            self.empty_detail.config(text=f"{pretty}\n\nLatent opens JPEG, PNG, TIFF, WebP and BMP files.")
            self.empty.place(relx=0.5, rely=0.45, anchor="center")
        else:
            self.empty.place_forget()
        self._update_selection_panel()
        self.refresh_status()

    def _folder_signature(self):
        return tuple((f.name, f.mtime, f.size_bytes) for f in self.files)

    def _subtitle(self, f: imgio.ImageInfo) -> str:
        d = self.dims.get(f.path)
        size = imgio.human_size(f.size_bytes)
        tag = "  ·  EDITED" if self.app.session.has_edits_for(f.path) else ""
        return f"{d[0]}×{d[1]}  ·  {size}{tag}" if d else f"{size}{tag}"

    def _poll(self):
        self._poll_after = None
        if not self.visible:
            return
        current = tuple((f.name, f.mtime, f.size_bytes) for f in imgio.list_images(self.app.folder))
        if current != self._signature:
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
        gen = self._generation
        edge = self.ui.px(320)

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
            self.grid.set_subtitle(i, self._subtitle(self.files[i]))
            if i == self.grid.selected:
                self._update_selection_panel()

    # -------------------------------------------------------------- select
    @property
    def selected_path(self) -> Optional[str]:
        i = self.grid.selected
        return self.files[i].path if i is not None and i < len(self.files) else None

    def _on_select(self, _i):
        self._update_selection_panel()

    def _on_activate(self, i):
        self.grid.set_selected(i)
        self._open_selected()

    def _open_selected(self):
        path = self.selected_path
        if path:
            self.app.open_photo(path)

    def _update_selection_panel(self):
        i = self.grid.selected
        self.open_btn.set_enabled(i is not None)
        if i is None or i >= len(self.files):
            for v in self.meta_rows.values():
                v.config(text="—")
            self._preview_photo = None
            self.preview.config(image="", text="Select a photo to preview")
            return
        f = self.files[i]
        d = self.dims.get(f.path)
        self.meta_rows["NAME"].config(text=self._elide(f.name, 34))
        self.meta_rows["DIMENSIONS"].config(text=f"{d[0]} × {d[1]} px" if d else "…")
        self.meta_rows["FILE SIZE"].config(text=imgio.human_size(f.size_bytes))
        self.meta_rows["MODIFIED"].config(text=time.strftime("%d %b %Y  %H:%M", time.localtime(f.mtime)))

        box_w = max(self.preview.winfo_width(), self.app.panel_width - self.ui.px(40))
        box_h = max(self.preview.winfo_height(), self.ui.px(200))
        hit = self.cache.get(f.path)
        if hit:
            self._show_preview(hit[1], box_w, box_h)
        path, edge = f.path, max(box_w, box_h)

        def job(_t):
            return path, imgio.load_thumbnail(path, edge)[0]

        def done(res):
            p, bgr = res
            if p == self.selected_path:
                self._show_preview(bgr, max(self.preview.winfo_width(), 50), max(self.preview.winfo_height(), 50))

        self.preview_channel.submit(job, done)

    def _show_preview(self, bgr, box_w, box_h):
        import cv2
        h, w = bgr.shape[:2]
        s = min(box_w / w, box_h / h)
        img = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        self._preview_photo = bgr_to_photo(img)
        self.preview.config(image=self._preview_photo, text="")

    @staticmethod
    def _elide(text, n):
        return text if len(text) <= n else text[: n - 1] + "…"

    # --------------------------------------------------------------- hooks
    def on_show(self):
        for i, f in enumerate(self.files):
            self.grid.set_subtitle(i, self._subtitle(f))
        if self._poll_after is None:
            self._poll_after = self.viewport.after(POLL_MS, self._poll)
        self.grid.canvas.focus_set()

    def on_hide(self):
        if self._poll_after:
            self.viewport.after_cancel(self._poll_after)
            self._poll_after = None

    def refresh_status(self):
        if not self.visible:
            return
        n = len(self.files)
        self.app.set_status(f"{n} photo{'s' if n != 1 else ''}  ·  {self.app.folder}",
                            "Double-click or Enter to open  ·  F1 shortcuts")

    def on_key(self, seq, e):
        moves = {"<Left>": (-1, 0), "<Right>": (1, 0), "<Up>": (0, -1), "<Down>": (0, 1)}
        if seq in moves:
            self.grid.move(*moves[seq])
        elif seq in ("<Return>", "<KP_Enter>"):
            self._open_selected()
        elif seq == "<F5>":
            self.load_folder()
