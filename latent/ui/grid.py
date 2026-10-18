"""Thumbnail cells in the original LATENT style.

Library: five columns of square cells with a 1px #58595a frame and the file
name inside the bottom-left corner.  Look: a 5x3 board of adjacent cells that
fills the viewport, numbered in the top-left corner.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .. import theme as T
from .widgets import UI, WheelRouter, bgr_to_photo


class ThumbGrid(tk.Frame):
    def __init__(self, master, ui: UI, router: WheelRouter, *,
                 on_select: Callable[[int], None], on_activate: Callable[[int], None],
                 on_hover: Optional[Callable[[Optional[int]], None]] = None,
                 on_visible: Optional[Callable[[int, int], None]] = None,
                 cols: int = 5, rows: Optional[int] = None, gap: float = T.CELL_GAP, numbered: bool = False,
                 margin: float = T.CELL_INSET, bar=None):
        super().__init__(master, bg=T.BG)
        self.ui = ui
        self.on_select, self.on_activate, self.on_hover, self.on_visible = on_select, on_activate, on_hover, on_visible
        self.cols, self.rows_fixed, self.numbered = cols, rows, numbered
        self.gap = ui.px(gap)
        self.margin = ui.px(margin)
        self.label_h = ui.px(24)

        self.canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0)
        self.bar = bar  # lives in the app's shared scrollbar column
        if bar is not None:
            bar.configure(command=self._scroll_cmd)
        self.canvas.configure(yscrollcommand=self._bar_set)
        self.canvas.pack(fill="both", expand=True)

        self.count = 0
        self.titles: List[str] = []
        self.images: Dict[int, np.ndarray] = {}
        self._photos: Dict[int, Tuple[Tuple[int, int], object]] = {}
        self.selected: Optional[int] = None
        self.hovered: Optional[int] = None
        self.cell_w = self.cell_h = ui.px(240)
        self._layout_after = None
        self._last_size = (0, 0)
        self._laid_out = False

        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Motion>", lambda e: self._set_hover(self.index_at(e.x, e.y)))
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        router.register(self.canvas, self._on_wheel)

    # ------------------------------------------------------------ content
    def set_items(self, titles: List[str], reset_scroll: bool = True):
        self.count = len(titles)
        self.titles = list(titles)
        self.images.clear()
        self._photos.clear()
        if self.selected is not None and self.selected >= self.count:
            self.selected = None
        self.hovered = None
        top = self.canvas.yview()[0]
        self.relayout()
        self.canvas.yview_moveto(0 if reset_scroll else top)

    def clear_images(self):
        self.images.clear()
        self._photos.clear()
        self.relayout()

    def set_image(self, idx: int, bgr: np.ndarray):
        if not 0 <= idx < self.count:
            return
        self.images[idx] = bgr
        self._photos.pop(idx, None)
        self._draw_cell_image(idx)

    def set_selected(self, idx: Optional[int], ensure_visible: bool = True):
        prev, self.selected = self.selected, idx
        for i in (prev, idx):
            if i is not None:
                self._style_border(i)
        if idx is not None and ensure_visible:
            self.ensure_visible(idx)

    # ------------------------------------------------------------- layout
    def _on_configure(self, e):
        if (e.width, e.height) == self._last_size:
            return
        self._last_size = (e.width, e.height)
        if self._layout_after:
            self.after_cancel(self._layout_after)
        self._layout_after = self.after(50, self.relayout)

    def relayout(self):
        self._layout_after = None
        c = self.canvas
        c.delete("all")
        W = max(c.winfo_width(), 200)
        H = max(c.winfo_height(), 200)
        g, m = self.gap, self.margin
        self.cell_w = (W - 2 * m - (self.cols - 1) * g) / self.cols
        if self.rows_fixed:  # fill the viewport exactly
            self.cell_h = (H - 2 * m - (self.rows_fixed - 1) * g) / self.rows_fixed
        else:
            self.cell_h = self.cell_w
        rows = -(-self.count // self.cols) if self.count else 0
        total = 2 * m + rows * self.cell_h + max(0, rows - 1) * g
        c.configure(scrollregion=(0, 0, W, max(H, total)))
        self._laid_out = True
        for i in range(self.count):
            self._create_cell(i)
        self._notify_visible()

    def cell_rect(self, i: int) -> Tuple[int, int, int, int]:
        r, col = divmod(i, self.cols)
        x = self.margin + col * (self.cell_w + self.gap)
        y = self.margin + r * (self.cell_h + self.gap)
        return int(x), int(y), int(x + self.cell_w), int(y + self.cell_h)

    def _image_box(self) -> Tuple[int, int]:
        inset = self.ui.px(12)
        return self.cell_w - 2 * inset, self.cell_h - 2 * self.label_h

    def _create_cell(self, i: int):
        c = self.canvas
        x0, y0, x1, y1 = self.cell_rect(i)
        tag = f"cell{i}"
        pad = self.ui.px(5)
        # file / profile name: 12px, inside the bottom-left corner
        c.create_text(x0 + pad, y1 - pad, text=self._elide(self.titles[i].upper()), anchor="sw", fill=T.TEXT,
                      font=self.ui.fonts.cell, tags=(tag, f"title{i}"))
        if self.numbered:  # 22.68px index, top-left
            c.create_text(x0 + self.ui.px(10), y0 + self.ui.px(8), text=f"{i + 1:02d}", anchor="nw", fill=T.TEXT,
                          font=self.ui.fonts.number, tags=(tag, f"num{i}"))
        c.create_rectangle(x0, y0, x1 - 1, y1 - 1, outline=T.LINE, width=1, tags=(tag, f"border{i}"))
        self._draw_cell_image(i)
        self._style_border(i)

    def _elide(self, text: str) -> str:
        max_chars = max(8, int((self.cell_w - self.ui.px(12)) / max(1, self.ui.px(6.6))))
        return text if len(text) <= max_chars else text[: max_chars - 3] + "..."

    def _draw_cell_image(self, i: int):
        if not self._laid_out or i >= self.count:
            return
        c = self.canvas
        c.delete(f"img{i}")
        x0, y0, x1, y1 = self.cell_rect(i)
        bw, bh = self._image_box()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        bgr = self.images.get(i)
        if bgr is None:  # empty cell until the thumbnail arrives
            return
        cached = self._photos.get(i)
        if cached is None or cached[0] != (bw, bh):
            h, w = bgr.shape[:2]
            s = min(bw / w, bh / h)
            small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))),
                               interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            cached = ((bw, bh), bgr_to_photo(small))
            self._photos[i] = cached
        c.create_image(cx, cy, image=cached[1], anchor="center", tags=(f"cell{i}", f"img{i}"))
        c.tag_raise(f"border{i}")

    def _style_border(self, i: int):
        if i >= self.count:
            return
        if i == self.selected:
            color, width = T.SELECT, max(1, self.ui.px(1.42))
        elif i == self.hovered:
            color, width = T.HOVER, 1
        else:
            color, width = T.LINE, 1
        self.canvas.itemconfigure(f"border{i}", outline=color, width=width)
        text = T.HOVER if i in (self.selected, self.hovered) else T.TEXT
        self.canvas.itemconfigure(f"title{i}", fill=text)
        self.canvas.itemconfigure(f"num{i}", fill=text)
        self.canvas.tag_raise(f"border{i}")

    # ------------------------------------------------------------ interact
    def index_at(self, x: int, y: int) -> Optional[int]:
        if not self.count or not self._laid_out:
            return None
        cx, cy = self.canvas.canvasx(x), self.canvas.canvasy(y)
        col = int((cx - self.margin) // (self.cell_w + self.gap))
        row = int((cy - self.margin) // (self.cell_h + self.gap))
        if not (0 <= col < self.cols) or row < 0:
            return None
        i = row * self.cols + col
        if i >= self.count:
            return None
        x0, y0, x1, y1 = self.cell_rect(i)
        return i if (x0 <= cx <= x1 and y0 <= cy <= y1) else None

    def _set_hover(self, idx):
        if idx == self.hovered:
            return
        prev, self.hovered = self.hovered, idx
        for i in (prev, idx):
            if i is not None:
                self._style_border(i)
        if self.on_hover:
            self.on_hover(idx)

    def _on_click(self, e):
        self.canvas.focus_set()
        i = self.index_at(e.x, e.y)
        if i is not None:
            self.set_selected(i, ensure_visible=False)
            self.on_select(i)

    def _on_double(self, e):
        i = self.index_at(e.x, e.y)
        if i is not None:
            self.on_activate(i)

    def move(self, dx: int, dy: int):
        if not self.count:
            return
        i = 0 if self.selected is None else max(0, min(self.count - 1, self.selected + dx + dy * self.cols))
        self.set_selected(i)
        self.on_select(i)

    # ------------------------------------------------------------- scroll
    def _scroll_cmd(self, *args):
        self.canvas.yview(*args)
        self._notify_visible()

    def _bar_set(self, first, last):
        if self.bar is not None:
            self.bar.set(first, last)

    def _on_wheel(self, notches: float, _e):
        self.canvas.yview_scroll(-int(round(notches * 2)) or (-1 if notches > 0 else 1), "units")
        self._notify_visible()

    def ensure_visible(self, i: int):
        if not self._laid_out:
            return
        _, y0, _, y1 = self.cell_rect(i)
        region = self.canvas.cget("scrollregion").split()
        total = float(region[3]) if len(region) == 4 else 1.0
        h = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if y0 < top:
            self.canvas.yview_moveto(max(0.0, y0 / total))
        elif y1 > top + h:
            self.canvas.yview_moveto(max(0.0, (y1 - h) / total))
        self._notify_visible()

    def visible_range(self) -> Tuple[int, int]:
        if not self.count or not self._laid_out:
            return 0, 0
        top = self.canvas.canvasy(0)
        row_h = self.cell_h + self.gap
        r0 = max(0, int((top - self.margin) // row_h))
        r1 = int((top + self.canvas.winfo_height()) // row_h) + 1
        return r0 * self.cols, min(self.count, (r1 + 1) * self.cols)

    def _notify_visible(self):
        if self.on_visible:
            self.on_visible(*self.visible_range())
