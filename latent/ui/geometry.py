"""Crop, straighten, perspective and output-size dialog."""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from typing import Callable, Optional, Tuple

import cv2
import numpy as np

from .. import theme as T
from ..imaging.pipeline import Geometry, apply_geometry, make_proxy
from .widgets import Button, Section, Segmented, Slider, bgr_to_photo

RATIOS = [("free", "FREE", None), ("original", "ORIGINAL", "orig"), ("1:1", "1:1", 1.0), ("4:5", "4:5", 4 / 5),
          ("3:2", "3:2", 3 / 2), ("16:9", "16:9", 16 / 9)]
HANDLE_TOL = 10
MIN_BOX = 24


class GeometryDialog:
    def __init__(self, app, proxy: np.ndarray, full_w: int, full_h: int, geometry: Geometry,
                 on_apply: Callable[[Geometry], None]):
        self.app, self.ui = app, app.ui
        self.full_w, self.full_h = full_w, full_h
        self.on_apply = on_apply
        self.base = make_proxy(proxy, 1100)
        self.geo = replace(geometry)
        self.ratio_key = "free"
        self.portrait = False
        self.photo = None
        self.transformed: Optional[np.ndarray] = None
        self.disp = (0, 0, 1, 1)  # x, y, w, h of the displayed image on the canvas
        self.box = [0.0, 0.0, 1.0, 1.0]  # normalised crop within the transformed frame
        self._drag = None
        self._resize_lock = False

        ui = self.ui
        win = self.win = tk.Toplevel(app.root)
        win.title("Crop & Rotate")
        win.configure(bg=T.BG_PANEL)
        win.transient(app.root)
        rw, rh = app.root.winfo_width(), app.root.winfo_height()
        win.geometry(f"{max(ui.px(900), int(rw * 0.82))}x{max(ui.px(600), int(rh * 0.85))}"
                     f"+{app.root.winfo_rootx() + int(rw * 0.09)}+{app.root.winfo_rooty() + int(rh * 0.06)}")
        win.minsize(ui.px(860), ui.px(560))

        side = tk.Frame(win, bg=T.BG_PANEL, width=ui.px(320))
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        tk.Frame(win, bg=T.LINE, width=1).pack(side="right", fill="y")
        self.canvas = tk.Canvas(win, bg=T.BG_VIEW, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._refresh_image())
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))

        body = tk.Frame(side, bg=T.BG_PANEL)
        body.pack(fill="both", expand=True, padx=ui.px(20), pady=ui.px(14))
        tk.Label(body, text="CROP & ROTATE", bg=T.BG_PANEL, fg=T.TEXT_HI, font=ui.fonts.title, anchor="w").pack(fill="x", pady=(ui.px(4), 0))

        sec = Section(body, ui, "Aspect ratio")
        sec.pack(fill="x")
        grid = tk.Frame(sec.body, bg=T.BG_PANEL)
        grid.pack(fill="x")
        self.ratio_buttons = {}
        for i, (key, label, _) in enumerate(RATIOS):
            b = Button(grid, ui, label, command=lambda k=key: self.set_ratio(k), style="secondary", font=ui.fonts.label, padx=6, pady=5)
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, ui.px(4)), pady=(0, ui.px(4)))
            self.ratio_buttons[key] = b
        for col in range(3):
            grid.grid_columnconfigure(col, weight=1)
        self.orient_btn = Button(sec.body, ui, "⇄  SWAP ORIENTATION", command=self.swap_orientation, style="ghost",
                                 font=ui.fonts.label, pady=4)
        self.orient_btn.pack(fill="x")

        sec = Section(body, ui, "Rotate")
        sec.pack(fill="x")
        row = tk.Frame(sec.body, bg=T.BG_PANEL)
        row.pack(fill="x", pady=(0, ui.px(10)))
        Button(row, ui, "↺ 90°", command=lambda: self.turn(-1), font=ui.fonts.label, pady=5).pack(side="left", fill="x", expand=True)
        Button(row, ui, "↻ 90°", command=lambda: self.turn(1), font=ui.fonts.label, pady=5).pack(side="left", fill="x", expand=True, padx=(ui.px(4), 0))
        self.straighten = Slider(sec.body, ui, "Straighten", -45, 45, 0, value=self.geo.rotate, decimals=1,
                                 on_change=lambda v: self._set("rotate", v))
        self.straighten.pack(fill="x")

        sec = Section(body, ui, "Perspective")
        sec.pack(fill="x")
        self.vk = Slider(sec.body, ui, "Vertical", -100, 100, 0, value=self.geo.v_keystone, kind="int",
                         on_change=lambda v: self._set("v_keystone", v))
        self.vk.pack(fill="x", pady=(0, ui.px(8)))
        self.hk = Slider(sec.body, ui, "Horizontal", -100, 100, 0, value=self.geo.h_keystone, kind="int",
                         on_change=lambda v: self._set("h_keystone", v))
        self.hk.pack(fill="x")

        sec = Section(body, ui, "Output size")
        sec.pack(fill="x")
        row = tk.Frame(sec.body, bg=T.BG_PANEL)
        row.pack(fill="x")
        self.w_var = tk.StringVar(value=str(self.geo.resize_w or ""))
        self.h_var = tk.StringVar(value=str(self.geo.resize_h or ""))
        for label, var in (("W", self.w_var), ("H", self.h_var)):
            tk.Label(row, text=label, bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.label).pack(side="left", padx=(0, ui.px(6)))
            e = tk.Entry(row, textvariable=var, width=7, bg=T.BG_INPUT, fg=T.TEXT_HI, insertbackground=T.TEXT_HI,
                         font=ui.fonts.mono, bd=0, highlightthickness=1, highlightbackground=T.LINE_STRONG,
                         highlightcolor=T.ACCENT, justify="right")
            e.pack(side="left", padx=(0, ui.px(12)), ipady=ui.px(3))
        tk.Label(row, text="px", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro).pack(side="left")
        self.size_hint = tk.Label(sec.body, text="", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro, anchor="w", justify="left")
        self.size_hint.pack(fill="x", pady=(ui.px(6), 0))
        self.w_var.trace_add("write", lambda *a: self._link_size("w"))
        self.h_var.trace_add("write", lambda *a: self._link_size("h"))

        foot = tk.Frame(side, bg=T.BG_PANEL)
        Button(foot, ui, "APPLY", command=self.apply, style="primary", pady=9).pack(fill="x")
        row = tk.Frame(foot, bg=T.BG_PANEL)
        row.pack(fill="x", pady=(ui.px(6), 0))
        Button(row, ui, "RESET", command=self.reset, style="ghost", font=ui.fonts.label).pack(side="left", fill="x", expand=True)
        Button(row, ui, "CANCEL", command=self.win.destroy, style="secondary", font=ui.fonts.label).pack(side="left", fill="x", expand=True, padx=(ui.px(6), 0))
        foot.pack(side="bottom", fill="x", padx=ui.px(20), pady=ui.px(18), before=body)

        win.bind("<Return>", lambda e: self.apply() if not isinstance(win.focus_get(), tk.Entry) else self._entry_enter())
        win.bind("<Escape>", lambda e: win.destroy())

        # initial crop from geometry
        g = self.geo
        self.box = [g.crop_l / 100.0, g.crop_t / 100.0, g.crop_r / 100.0, g.crop_b / 100.0]
        self._paint_ratio_buttons()
        self._rebuild_transform(keep_box=True)
        win.after(10, self._grab)

    def _grab(self):
        try:
            self.win.grab_set()
            self.win.focus_set()
        except tk.TclError:
            pass

    # ---------------------------------------------------------- transform
    def _set(self, attr, value):
        setattr(self.geo, attr, float(value))
        self._rebuild_transform(keep_box=True)

    def turn(self, direction: int):
        self.geo.quarter_turns = (self.geo.quarter_turns + direction) % 4
        self.box = [0.0, 0.0, 1.0, 1.0]
        self._rebuild_transform(keep_box=False)
        self._link_size("w")

    def _rebuild_transform(self, keep_box: bool):
        g = Geometry(quarter_turns=self.geo.quarter_turns, rotate=self.geo.rotate,
                     v_keystone=self.geo.v_keystone, h_keystone=self.geo.h_keystone)
        self.transformed = apply_geometry(self.base, g)
        if not keep_box:
            self._snap_ratio()
        self._refresh_image()

    def _frame_aspect(self) -> float:
        w, h = self.full_w, self.full_h
        if self.geo.quarter_turns % 2:
            w, h = h, w
        return w / float(h)

    # -------------------------------------------------------------- ratio
    def _ratio(self) -> Optional[float]:
        """Chosen width/height ratio, oriented like the frame unless swapped."""
        val = dict((k, v) for k, _, v in RATIOS)[self.ratio_key]
        if val is None:
            return None
        if val == "orig":
            r = self._frame_aspect()
        else:
            landscape_form = max(val, 1.0 / val)
            r = landscape_form if self._frame_aspect() >= 1 else 1.0 / landscape_form
        return 1.0 / r if self.portrait else r

    def set_ratio(self, key):
        self.ratio_key = key
        self.portrait = False
        self._paint_ratio_buttons()
        self._snap_ratio()
        self._refresh_image()

    def swap_orientation(self):
        if self.ratio_key == "free":
            return
        self.portrait = not self.portrait
        self._snap_ratio()
        self._refresh_image()

    def _paint_ratio_buttons(self):
        for k, b in self.ratio_buttons.items():
            b.set_active(k == self.ratio_key)
        self.orient_btn.set_enabled(self.ratio_key not in ("free", "1:1"))

    def _snap_ratio(self):
        """Largest box of the chosen ratio centred on the current crop."""
        r = self._ratio()
        if r is None:
            return
        fa = self._frame_aspect()
        # ratio in normalised units: (bw * fa) / bh = r
        x1, y1, x2, y2 = self.box
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        bw, bh = 1.0, fa / r
        if bh > 1.0:
            bh, bw = 1.0, r / fa
        cx = min(max(cx, bw / 2), 1 - bw / 2)
        cy = min(max(cy, bh / 2), 1 - bh / 2)
        self.box = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]
        self._link_size("w")

    # ------------------------------------------------------------ drawing
    def _refresh_image(self):
        c = self.canvas
        cw, ch = c.winfo_width(), c.winfo_height()
        if self.transformed is None or cw < 20 or ch < 20:
            return
        pad = self.ui.px(36)
        h, w = self.transformed.shape[:2]
        s = min((cw - 2 * pad) / w, (ch - 2 * pad) / h)
        dw, dh = max(1, int(w * s)), max(1, int(h * s))
        self.disp = ((cw - dw) // 2, (ch - dh) // 2, dw, dh)
        self._scaled = cv2.resize(self.transformed, (dw, dh), interpolation=cv2.INTER_AREA)
        self._draw()

    def _box_px(self):
        x, y, dw, dh = self.disp
        b = self.box
        return x + b[0] * dw, y + b[1] * dh, x + b[2] * dw, y + b[3] * dh

    def _draw(self):
        c = self.canvas
        c.delete("all")
        x, y, dw, dh = self.disp
        img = self._scaled.copy()
        bx1, by1, bx2, by2 = [int(round(v)) for v in (self.box[0] * dw, self.box[1] * dh, self.box[2] * dw, self.box[3] * dh)]
        dim = (img.astype(np.float32) * 0.28).astype(np.uint8)
        dim[by1:by2, bx1:bx2] = img[by1:by2, bx1:bx2]
        self.photo = bgr_to_photo(dim)
        c.create_image(x, y, image=self.photo, anchor="nw")
        x1, y1, x2, y2 = self._box_px()
        for i in (1, 2):
            gx = x1 + (x2 - x1) * i / 3
            gy = y1 + (y2 - y1) * i / 3
            c.create_line(gx, y1, gx, y2, fill="#8a8a8a", dash=(2, 4))
            c.create_line(x1, gy, x2, gy, fill="#8a8a8a", dash=(2, 4))
        c.create_rectangle(x1, y1, x2, y2, outline=T.TEXT_HI, width=1)
        L = self.ui.px(14)
        t = max(3, self.ui.px(3))
        for hx, hy, sx, sy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
            c.create_line(hx, hy, hx + sx * L, hy, fill=T.ACCENT, width=t)
            c.create_line(hx, hy, hx, hy + sy * L, fill=T.ACCENT, width=t)
        for hx, hy in (((x1 + x2) / 2, y1), ((x1 + x2) / 2, y2), (x1, (y1 + y2) / 2), (x2, (y1 + y2) / 2)):
            c.create_rectangle(hx - 5, hy - 5, hx + 5, hy + 5, fill=T.ACCENT, outline="")
        ow, oh = self._crop_pixels()
        c.create_text(x1 + 6, y2 - 8, text=f"{ow} × {oh}", anchor="sw", fill=T.TEXT_HI, font=self.ui.fonts.micro)
        self._update_size_hint()

    def _crop_pixels(self) -> Tuple[int, int]:
        fw, fh = self.full_w, self.full_h
        if self.geo.quarter_turns % 2:
            fw, fh = fh, fw
        return max(2, int(round((self.box[2] - self.box[0]) * fw))), max(2, int(round((self.box[3] - self.box[1]) * fh)))

    # ------------------------------------------------------------ interaction
    def _handle_at(self, ex, ey) -> Optional[str]:
        x1, y1, x2, y2 = self._box_px()
        tol = self.ui.px(HANDLE_TOL)
        near = lambda a, b: abs(a - b) <= tol
        on_x = x1 - tol <= ex <= x2 + tol
        on_y = y1 - tol <= ey <= y2 + tol
        horiz = "w" if near(ex, x1) else ("e" if near(ex, x2) else "")
        vert = "n" if near(ey, y1) else ("s" if near(ey, y2) else "")
        if horiz and vert:
            return vert + horiz
        if vert and on_x:
            return vert
        if horiz and on_y:
            return horiz
        if x1 < ex < x2 and y1 < ey < y2:
            return "move"
        return None

    CURSORS = {"nw": "top_left_corner", "ne": "top_right_corner", "sw": "bottom_left_corner", "se": "bottom_right_corner",
               "n": "top_side", "s": "bottom_side", "w": "left_side", "e": "right_side", "move": "fleur"}

    def _hover(self, e):
        h = self._handle_at(e.x, e.y)
        self.canvas.config(cursor=self.CURSORS.get(h, "crosshair"))

    def _press(self, e):
        h = self._handle_at(e.x, e.y)
        if h is None:
            return
        self._drag = (h, e.x, e.y, list(self._box_px()))

    def _drag_move(self, e):
        if not self._drag:
            return
        handle, sx, sy, (x1, y1, x2, y2) = self._drag
        X, Y, dw, dh = self.disp
        ex = min(max(e.x, X), X + dw)
        ey = min(max(e.y, Y), Y + dh)
        r = self._ratio()
        mn = self.ui.px(MIN_BOX)
        if handle == "move":
            bw, bh = x2 - x1, y2 - y1
            nx = min(max(x1 + (e.x - sx), X), X + dw - bw)
            ny = min(max(y1 + (e.y - sy), Y), Y + dh - bh)
            x1, y1, x2, y2 = nx, ny, nx + bw, ny + bh
        elif r is None:
            if "w" in handle: x1 = min(ex, x2 - mn)
            if "e" in handle: x2 = max(ex, x1 + mn)
            if "n" in handle: y1 = min(ey, y2 - mn)
            if "s" in handle: y2 = max(ey, y1 + mn)
        elif len(handle) == 2:
            ax = x2 if "w" in handle else x1
            ay = y2 if "n" in handle else y1
            w, h = max(mn, abs(ex - ax)), max(mn, abs(ey - ay))
            if w / h > r: w = h * r
            else: h = w / r
            max_w = (ax - X) if "w" in handle else (X + dw - ax)
            max_h = (ay - Y) if "n" in handle else (Y + dh - ay)
            if w > max_w: w, h = max_w, max_w / r
            if h > max_h: h, w = max_h, max_h * r
            x1, x2 = (ax - w, ax) if "w" in handle else (ax, ax + w)
            y1, y2 = (ay - h, ay) if "n" in handle else (ay, ay + h)
        else:
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if handle in ("e", "w"):
                w = max(mn, (ex - x1) if handle == "e" else (x2 - ex))
                h = min(w / r, dh)
                w = h * r
                if handle == "e": x2 = min(x1 + w, X + dw)
                else: x1 = max(x2 - w, X)
                w = x2 - x1; h = w / r
                y1 = min(max(cy - h / 2, Y), Y + dh - h); y2 = y1 + h
            else:
                h = max(mn, (ey - y1) if handle == "s" else (y2 - ey))
                w = min(h * r, dw)
                h = w / r
                if handle == "s": y2 = min(y1 + h, Y + dh)
                else: y1 = max(y2 - h, Y)
                h = y2 - y1; w = h * r
                x1 = min(max(cx - w / 2, X), X + dw - w); x2 = x1 + w
        self.box = [(x1 - X) / dw, (y1 - Y) / dh, (x2 - X) / dw, (y2 - Y) / dh]
        self.box = [min(max(v, 0.0), 1.0) for v in self.box]
        self._draw()
        self._link_size("w")

    # ------------------------------------------------------------ output size
    def _crop_aspect(self) -> float:
        w, h = self._crop_pixels()
        return w / float(h)

    def _link_size(self, changed: str):
        if self._resize_lock:
            return
        self._resize_lock = True
        try:
            src, dst = (self.w_var, self.h_var) if changed == "w" else (self.h_var, self.w_var)
            text = src.get().strip()
            if not text:
                dst.set("")
            elif text.isdigit() and int(text) > 0:
                a = self._crop_aspect()
                val = int(text) / a if changed == "w" else int(text) * a
                dst.set(str(max(1, int(round(val)))))
        finally:
            self._resize_lock = False
        self._update_size_hint()

    def _update_size_hint(self):
        ow, oh = self._crop_pixels()
        custom = self.w_var.get().strip()
        self.size_hint.config(text=f"Crop: {ow} × {oh} px" + ("" if custom else "  ·  leave empty to keep"))

    def _entry_enter(self):
        self.win.focus_set()
        return "break"

    # ----------------------------------------------------------------- actions
    def reset(self):
        self.geo = Geometry()
        self.ratio_key, self.portrait = "free", False
        self.box = [0.0, 0.0, 1.0, 1.0]
        for s in (self.straighten, self.vk, self.hk):
            s.set(0)
        self.w_var.set("")
        self._paint_ratio_buttons()
        self._rebuild_transform(keep_box=True)

    def apply(self):
        w, h = self.w_var.get().strip(), self.h_var.get().strip()
        rw = rh = None
        if w or h:
            if not (w.isdigit() and h.isdigit()) or not (0 < int(w) <= 30000 and 0 < int(h) <= 30000):
                self.size_hint.config(text="Output size must be whole numbers between 1 and 30000.", fg=T.DANGER)
                return
            rw, rh = int(w), int(h)
        b = self.box
        geo = Geometry(crop_l=b[0] * 100, crop_t=b[1] * 100, crop_r=b[2] * 100, crop_b=b[3] * 100,
                       quarter_turns=self.geo.quarter_turns, rotate=self.geo.rotate,
                       v_keystone=self.geo.v_keystone, h_keystone=self.geo.h_keystone,
                       resize_w=rw, resize_h=rh)
        if abs(geo.crop_l) < 1e-6 and abs(geo.crop_t) < 1e-6 and abs(geo.crop_r - 100) < 1e-6 and abs(geo.crop_b - 100) < 1e-6:
            geo.crop_l, geo.crop_t, geo.crop_r, geo.crop_b = 0.0, 0.0, 100.0, 100.0
        self.win.destroy()
        self.on_apply(geo)
