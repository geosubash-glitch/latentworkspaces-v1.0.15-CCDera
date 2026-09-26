"""Responsive thumbnail grid used by the Library and Look stages."""
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
                 min_cell: int = 200, aspect: float = 1.0, fit_all: bool = False, fixed_cols: Optional[int] = None):
        super().__init__(master, bg=T.BG_VIEW)
        self.ui = ui
        self.on_select, self.on_activate, self.on_hover, self.on_visible = on_select, on_activate, on_hover, on_visible
        self.min_cell, self.aspect, self.fit_all, self.fixed_cols = ui.px(min_cell), aspect, fit_all, fixed_cols
        self.gap = ui.px(12)
        self.margin = ui.px(20)
        self.label_h = ui.px(34)

        self.canvas = tk.Canvas(self, bg=T.BG_VIEW, highlightthickness=0, bd=0)
        self.bar = tk.Canvas(self, width=ui.px(6), bg=T.BG_VIEW, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")

        self.count = 0
        self.titles: List[str] = []
        self.subtitles: List[str] = []
        self.badges: List[str] = []
        self.images: Dict[int, np.ndarray] = {}
        self._photos: Dict[int, Tuple[Tuple[int, int], object]] = {}
        self.selected: Optional[int] = None
        self.hovered: Optional[int] = None
        self.cols = 1
        self.cell_w = self.cell_h = self.min_cell
        self._layout_after = None
        self._last_size = (0, 0)

        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.bar.bind("<ButtonPress-1>", self._bar_drag)
        self.bar.bind("<B1-Motion>", self._bar_drag)
        router.register(self.canvas, self._on_wheel)

    # ------------------------------------------------------------ content
    def set_items(self, titles: List[str], subtitles: Optional[List[str]] = None, badges: Optional[List[str]] = None,
                  keep_images: bool = False, reset_scroll: bool = True):
        self.count = len(titles)
        self.titles = list(titles)
        self.subtitles = list(subtitles or [""] * self.count)
        self.badges = list(badges or [""] * self.count)
        if not keep_images:
            self.images.clear()
            self._photos.clear()
        if self.selected is not None and self.selected >= self.count:
            self.selected = None
        self.hovered = None
        top = self.canvas.yview()[0]
        self.relayout()
        self.canvas.yview_moveto(0 if reset_scroll else top)
        self._draw_bar()

    def set_image(self, idx: int, bgr: np.ndarray):
        if not 0 <= idx < self.count:
            return
        self.images[idx] = bgr
        self._photos.pop(idx, None)
        self._draw_cell_image(idx)

    def set_subtitle(self, idx: int, text: str):
        if 0 <= idx < self.count:
            self.subtitles[idx] = text
            self.canvas.itemconfigure(f"sub{idx}", text=text)

    def set_selected(self, idx: Optional[int], ensure_visible: bool = True):
        prev = self.selected
        self.selected = idx
        for i in (prev, idx):
            if i is not None:
                self._style_border(i)
        if idx is not None and ensure_visible:
            self.ensure_visible(idx)

    # ------------------------------------------------------------- layout
    def _on_configure(self, e):
        size = (e.width, e.height)
        if size == self._last_size:
            return
        self._last_size = size
        if self._layout_after:
            self.after_cancel(self._layout_after)
        self._layout_after = self.after(60, self.relayout)

    def relayout(self):
        self._layout_after = None
        c = self.canvas
        c.delete("all")
        W = max(c.winfo_width(), 200)
        H = max(c.winfo_height(), 200)
        m, g = self.margin, self.gap
        if self.count == 0:
            c.configure(scrollregion=(0, 0, W, H))
            self._draw_bar()
            return
        if self.fit_all:
            best = None
            for cols in range(2, 8):
                rows = -(-self.count // cols)
                cw = (W - 2 * m - (cols - 1) * g) / cols
                ch_avail = (H - 2 * m - (rows - 1) * g) / rows
                img_h = min(cw / self.aspect, ch_avail - self.label_h)
                cw_eff = img_h * self.aspect
                if best is None or cw_eff > best[0]:
                    best = (cw_eff, cols, img_h)
            _, self.cols, img_h = best
            self.cell_w = int((W - 2 * m - (self.cols - 1) * g) / self.cols)
            self.cell_h = int(img_h + self.label_h)
        else:
            cols = self.fixed_cols or max(1, int((W - 2 * m + g) // (self.min_cell + g)))
            self.cols = cols
            self.cell_w = int((W - 2 * m - (cols - 1) * g) / cols)
            self.cell_h = int(self.cell_w / self.aspect) + self.label_h
        rows = -(-self.count // self.cols)
        total_h = 2 * m + rows * self.cell_h + (rows - 1) * g
        if self.fit_all:
            # centre the block vertically
            self._y0 = max(m, (H - (rows * self.cell_h + (rows - 1) * g)) // 2)
        else:
            self._y0 = m
        c.configure(scrollregion=(0, 0, W, max(H, total_h)))
        for i in range(self.count):
            self._create_cell(i)
        self._draw_bar()
        self._notify_visible()

    def cell_rect(self, i: int) -> Tuple[int, int, int, int]:
        r, col = divmod(i, self.cols)
        x = self.margin + col * (self.cell_w + self.gap)
        y = self._y0 + r * (self.cell_h + self.gap)
        return x, y, x + self.cell_w, y + self.cell_h

    def image_box(self) -> Tuple[int, int]:
        return self.cell_w - self.ui.px(12), self.cell_h - self.label_h - self.ui.px(12)

    def _create_cell(self, i: int):
        c = self.canvas
        x0, y0, x1, y1 = self.cell_rect(i)
        tag = f"cell{i}"
        c.create_rectangle(x0, y0, x1, y1 - self.label_h, fill=T.BG_RAISED, outline="", tags=(tag,))
        ly = y1 - self.label_h + self.ui.px(10)
        fonts = self.ui.fonts
        title = self.titles[i]
        c.create_text(x0 + self.ui.px(2), ly, text=self._elide(title, self.cell_w - self.ui.px(40)), anchor="w",
                      fill=T.TEXT, font=fonts.label, tags=(tag, f"title{i}"))
        c.create_text(x0 + self.ui.px(2), ly + self.ui.px(15), text=self.subtitles[i], anchor="w", fill=T.TEXT_FAINT,
                      font=fonts.micro, tags=(tag, f"sub{i}"))
        if self.badges[i]:
            c.create_text(x1 - self.ui.px(2), ly, text=self.badges[i], anchor="e", fill=T.TEXT_FAINT, font=fonts.micro,
                          tags=(tag, f"badge{i}"))
        c.create_rectangle(x0, y0, x1, y1 - self.label_h, outline=T.LINE, width=1, tags=(tag, f"border{i}"))
        self._draw_cell_image(i)
        self._style_border(i)

    def _elide(self, text: str, width: int) -> str:
        max_chars = max(6, int(width / max(1, self.ui.px(7))))
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def _draw_cell_image(self, i: int):
        if self.count == 0 or not hasattr(self, "_y0"):
            return
        c = self.canvas
        c.delete(f"img{i}")
        c.delete(f"placeholder{i}")
        x0, y0, x1, y1 = self.cell_rect(i)
        bw, bh = self.image_box()
        cx, cy = (x0 + x1) / 2, (y0 + y1 - self.label_h) / 2
        bgr = self.images.get(i)
        if bgr is None:
            c.create_text(cx, cy, text="···", fill=T.TEXT_FAINT, font=self.ui.fonts.mono, tags=(f"cell{i}", f"placeholder{i}"))
            return
        cached = self._photos.get(i)
        if cached is None or cached[0] != (bw, bh):
            h, w = bgr.shape[:2]
            s = min(bw / w, bh / h)
            tw, th = max(1, int(w * s)), max(1, int(h * s))
            small = cv2.resize(bgr, (tw, th), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            cached = ((bw, bh), bgr_to_photo(small))
            self._photos[i] = cached
        c.create_image(cx, cy, image=cached[1], anchor="center", tags=(f"cell{i}", f"img{i}"))
        c.tag_raise(f"border{i}")

    def _style_border(self, i: int):
        if i >= self.count:
            return
        if i == self.selected:
            self.canvas.itemconfigure(f"border{i}", outline=T.ACCENT, width=max(2, self.ui.px(2)))
            self.canvas.itemconfigure(f"title{i}", fill=T.TEXT_HI)
        elif i == self.hovered:
            self.canvas.itemconfigure(f"border{i}", outline=T.LINE_FOCUS, width=1)
            self.canvas.itemconfigure(f"title{i}", fill=T.TEXT_HI)
        else:
            self.canvas.itemconfigure(f"border{i}", outline=T.LINE, width=1)
            self.canvas.itemconfigure(f"title{i}", fill=T.TEXT)

    # ------------------------------------------------------------ interact
    def index_at(self, x: int, y: int) -> Optional[int]:
        if self.count == 0 or not hasattr(self, "_y0"):
            return None
        cx, cy = self.canvas.canvasx(x), self.canvas.canvasy(y)
        col = int((cx - self.margin) // (self.cell_w + self.gap))
        row = int((cy - self._y0) // (self.cell_h + self.gap))
        if col < 0 or col >= self.cols or row < 0:
            return None
        i = row * self.cols + col
        if i >= self.count:
            return None
        x0, y0, x1, y1 = self.cell_rect(i)
        return i if (x0 <= cx <= x1 and y0 <= cy <= y1) else None

    def _on_motion(self, e):
        self._set_hover(self.index_at(e.x, e.y))

    def _set_hover(self, idx):
        if idx == self.hovered:
            return
        prev, self.hovered = self.hovered, idx
        for i in (prev, idx):
            if i is not None:
                self._style_border(i)
        self.canvas.config(cursor="hand2" if idx is not None else "")
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
        if self.count == 0:
            return
        if self.selected is None:
            i = 0
        else:
            i = self.selected + dx + dy * self.cols
            i = max(0, min(self.count - 1, i))
        self.set_selected(i)
        self.on_select(i)

    # ------------------------------------------------------------- scroll
    def _on_wheel(self, notches: float, _e):
        self.canvas.yview_scroll(-int(round(notches * 2)) or (-1 if notches > 0 else 1), "units")
        self._draw_bar()
        self._notify_visible()

    def ensure_visible(self, i: int):
        if not hasattr(self, "_y0"):
            return
        _, y0, _, y1 = self.cell_rect(i)
        region = self.canvas.cget("scrollregion").split()
        total = float(region[3]) if len(region) == 4 else 1.0
        h = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if y0 - self.margin < top:
            self.canvas.yview_moveto(max(0.0, (y0 - self.margin) / total))
        elif y1 + self.margin > top + h:
            self.canvas.yview_moveto(max(0.0, (y1 + self.margin - h) / total))
        self._draw_bar()
        self._notify_visible()

    def _draw_bar(self):
        self.bar.delete("all")
        first, last = self.canvas.yview()
        if last - first >= 0.999:
            return
        h, w = self.bar.winfo_height(), self.bar.winfo_width()
        self.bar.create_rectangle(0, first * h, w, last * h, fill=T.LINE_STRONG, outline="")

    def _bar_drag(self, e):
        first, last = self.canvas.yview()
        h = max(1, self.bar.winfo_height())
        self.canvas.yview_moveto(max(0.0, e.y / h - (last - first) / 2))
        self._draw_bar()
        self._notify_visible()

    def visible_range(self) -> Tuple[int, int]:
        if self.count == 0 or not hasattr(self, "_y0"):
            return 0, 0
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        row_h = self.cell_h + self.gap
        r0 = max(0, int((top - self._y0) // row_h))
        r1 = int((bottom - self._y0) // row_h) + 1
        return r0 * self.cols, min(self.count, (r1 + 1) * self.cols)

    def _notify_visible(self):
        if self.on_visible:
            a, b = self.visible_range()
            self.on_visible(a, b)
