"""Widgets drawn in the LATENT console style (see theme.py)."""
from __future__ import annotations

import math
import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from .. import theme as T
from ..imaging.pipeline import color_wheel_rgba, compute_spline_lut


class UI:
    """Layout scale (relative to the 1920x1080 design) and fonts."""

    def __init__(self, root: tk.Misc):
        self.root = root
        sw = root.winfo_screenwidth()
        self.scale = max(0.6, min(2.5, sw / T.DESIGN_W))
        self.fonts = T.Fonts(root, scale=max(0.85, min(1.5, self.scale)))

    def px(self, n: float) -> int:
        return int(round(n * self.scale))


def bgr_to_photo(bgr: np.ndarray) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))


def rgb_to_photo(rgb: np.ndarray) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(Image.fromarray(rgb))


# --------------------------------------------------------------------------
# Mouse-wheel routing
# --------------------------------------------------------------------------
class WheelRouter:
    """Sends wheel events to the scrollable area under the pointer
    (Windows delta 120, macOS small deltas, X11 Button-4/5)."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.handlers: Dict[str, Callable[[float, tk.Event], None]] = {}
        for seq in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(seq, self._on_wheel, add="+")

    def register(self, widget: tk.Misc, handler: Callable[[float, tk.Event], None]) -> None:
        self.handlers[str(widget)] = handler

    def _on_wheel(self, event: tk.Event):
        num = getattr(event, "num", None)
        if num == 4:
            notches = 1.0
        elif num == 5:
            notches = -1.0
        elif sys.platform == "darwin":
            notches = float(event.delta)
        else:
            notches = event.delta / 120.0
        if not notches:
            return
        try:
            w = self.root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        while w is not None:
            h = self.handlers.get(str(w))
            if h is not None:
                h(notches, event)
                return "break"
            w = getattr(w, "master", None)


# --------------------------------------------------------------------------
# Buttons
# --------------------------------------------------------------------------
class Button(tk.Label):
    """Outlined console button.

    Rest: grey outline and text. Hover: outline and text lighten.
    Press: fill darkens. ``accent`` sets the text colour (SAVE is yellow).
    """

    def __init__(self, master, ui: UI, text: str, command: Optional[Callable] = None,
                 accent: Optional[str] = None, outline: Optional[str] = None, font=None, **kw):
        self._fg = accent or T.G55
        self._outline = outline or T.LINE
        self._command = command
        self._enabled = True
        self._active = False
        self._hover = False
        kw.setdefault("padx", ui.px(10))
        kw.setdefault("pady", ui.px(5))
        super().__init__(master, text=text, bg=T.BG_BUTTON, fg=self._fg, font=font or ui.fonts.button,
                         cursor="hand2", bd=0, highlightthickness=1, highlightbackground=self._outline,
                         highlightcolor=self._outline, **kw)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonPress-1>", lambda e: self._enabled and self.config(bg=T.BG_BUTTON_PRESS))
        self.bind("<ButtonRelease-1>", self._release)

    def _set_hover(self, on: bool):
        self._hover = on
        self._paint()

    def _paint(self):
        if not self._enabled:
            self.config(bg=T.BG_BUTTON, fg="#2e2f30", highlightbackground="#2e2f30", cursor="arrow")
            return
        lit = self._hover or self._active
        accent = self._fg not in (T.G55,)
        self.config(bg=T.BG_BUTTON, cursor="hand2",
                    fg=self._fg if accent else (T.G10 if lit else T.G55),
                    highlightbackground=(T.YELLOW if self._active else T.G35) if lit else self._outline)

    def _release(self, e):
        if not self._enabled:
            return
        self._paint()
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() and self._command:
            self._command()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._paint()

    def set_active(self, active: bool):
        self._active = active
        self._paint()


# --------------------------------------------------------------------------
# Boxes
# --------------------------------------------------------------------------
class Box(tk.Frame):
    """Section with a bracketed caption: ``[ ADJUSTMENTS ]``."""

    def __init__(self, master, ui: UI, title: Optional[str] = None, title_color: str = T.TEXT, bg=T.BG):
        super().__init__(master, bg=bg)
        if title:
            self.caption = tk.Label(self, text=f"[ {title.upper()} ]", bg=bg, fg=title_color, font=ui.fonts.label, anchor="w")
            self.caption.pack(fill="x", pady=(0, ui.px(6)))
        self.frame = tk.Frame(self, bg=bg, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE)
        self.frame.pack(fill="x")
        self.body = tk.Frame(self.frame, bg=bg)
        self.body.pack(fill="x", padx=ui.px(12), pady=ui.px(12))

    def set_title(self, title: str):
        self.caption.config(text=f"[ {title.upper()} ]")


# --------------------------------------------------------------------------
# Slider
# --------------------------------------------------------------------------
class Slider(tk.Frame):
    """Caption, trough with a grip thumb, value at the right.

    States: hover lightens caption and thumb; dragging turns the thumb
    yellow; a value away from its default reads near-white.
    Double-click resets to default; click the value to type a number.
    """

    def __init__(self, master, ui: UI, label: str, minimum: float, maximum: float, default: float,
                 value: Optional[float] = None, kind: str = "float", decimals: Optional[int] = None,
                 on_change: Optional[Callable[[float], None]] = None,
                 on_begin: Optional[Callable[[], None]] = None, bg=T.BG):
        super().__init__(master, bg=bg)
        self.ui, self.minimum, self.maximum, self.default, self.kind = ui, float(minimum), float(maximum), float(default), kind
        span = self.maximum - self.minimum
        self.decimals = decimals if decimals is not None else (0 if kind == "int" else (2 if span <= 5 else 1))
        self.on_change, self.on_begin = on_change, on_begin
        self.value = self._coerce(default if value is None else value)
        self._entry: Optional[tk.Entry] = None
        self._hover = False
        self._dragging = False

        self.name_lbl = tk.Label(self, text=label.upper(), bg=bg, fg=T.TEXT, font=ui.fonts.label, anchor="w")
        self.name_lbl.pack(fill="x")
        row = tk.Frame(self, bg=bg)
        row.pack(fill="x", pady=(ui.px(3), 0))
        self.value_lbl = tk.Label(row, text="", bg=bg, fg=T.G55, font=ui.fonts.value, anchor="e", width=6, cursor="xterm")
        self.value_lbl.pack(side="right")
        self.canvas = tk.Canvas(row, height=ui.px(16), bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(side="left", fill="x", expand=True, padx=(0, ui.px(12)))

        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", lambda e: self.set(self._v_for(e.x), notify=True))
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.reset(notify=True))
        for w in (self, self.name_lbl, self.canvas, self.value_lbl):
            w.bind("<Enter>", lambda e: self._set_hover(True), add="+")
            w.bind("<Leave>", lambda e: self._set_hover(False), add="+")
        self.name_lbl.bind("<Double-Button-1>", lambda e: self.reset(notify=True))
        self.value_lbl.bind("<Button-1>", self._edit)
        self._refresh()

    def _coerce(self, v: float) -> float:
        v = min(self.maximum, max(self.minimum, float(v)))
        return float(int(round(v))) if self.kind == "int" else v

    def _fmt(self, v: float) -> str:
        return f"{v:.{self.decimals}f}"

    def _thumb_w(self) -> int:
        return self.ui.px(22)

    def _x_for(self, v: float) -> float:
        w = max(self.canvas.winfo_width(), 20)
        tw = self._thumb_w()
        return tw / 2 + (v - self.minimum) / (self.maximum - self.minimum) * (w - tw)

    def _v_for(self, x: float) -> float:
        w = max(self.canvas.winfo_width(), 20)
        tw = self._thumb_w()
        t = (x - tw / 2) / max(1.0, w - tw)
        return self.minimum + max(0.0, min(1.0, t)) * (self.maximum - self.minimum)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height() or self.ui.px(16)
        lit = self._hover or self._dragging
        c.create_rectangle(0, 0, w - 1, h - 1, fill=T.BG, outline=T.G35 if lit else T.LINE)
        x, tw = self._x_for(self.value), self._thumb_w()
        thumb = T.YELLOW if self._dragging else (T.G10 if self._hover else T.G55)
        c.create_rectangle(x - tw / 2, 2, x + tw / 2, h - 3, fill=T.BG, outline=thumb)
        for k in (-3, 0, 3):
            gx = x + self.ui.px(k)
            c.create_line(gx, h * 0.3, gx, h * 0.7, fill=thumb)

    def _refresh(self):
        changed = abs(self.value - self.default) > 1e-9
        lit = self._hover or self._dragging
        self.value_lbl.config(text=self._fmt(self.value), fg=T.YELLOW if self._dragging else (T.G10 if changed else T.G55))
        self.name_lbl.config(fg=T.G35 if lit else T.TEXT)
        self._draw()

    def _set_hover(self, on: bool):
        if on != self._hover:
            self._hover = on
            self._refresh()

    def _press(self, e):
        if self.on_begin:
            self.on_begin()
        self._dragging = True
        self.set(self._v_for(e.x), notify=True)
        self._refresh()

    def _release(self, _e):
        self._dragging = False
        self._refresh()

    def set(self, v: float, notify: bool = False):
        v = self._coerce(v)
        if abs(v - self.value) < 1e-12:
            return
        self.value = v
        self._refresh()
        if notify and self.on_change:
            self.on_change(v)

    def reset(self, notify: bool = False):
        if abs(self.value - self.default) < 1e-12:
            return
        if notify and self.on_begin:
            self.on_begin()
        self.set(self.default, notify=notify)

    def _edit(self, _e=None):
        if self._entry is not None:
            return
        e = tk.Entry(self.value_lbl.master, bg=T.BG, fg=T.G10, insertbackground=T.G10, font=self.ui.fonts.value,
                     bd=0, highlightthickness=1, highlightbackground=T.YELLOW, highlightcolor=T.YELLOW,
                     justify="right", width=6)
        e.insert(0, self._fmt(self.value))
        e.place(in_=self.value_lbl, relwidth=1.0, relheight=1.0)
        e.focus_set()
        e.select_range(0, "end")
        self._entry = e

        def commit(_ev=None):
            if self._entry is None:
                return
            text = e.get().strip()
            self._entry = None
            e.destroy()
            try:
                v = float(text)
            except ValueError:
                return
            if self.on_begin:
                self.on_begin()
            self.set(v, notify=True)

        def cancel(_ev=None):
            self._entry = None
            e.destroy()

        e.bind("<Return>", commit)
        e.bind("<KP_Enter>", commit)
        e.bind("<FocusOut>", commit)
        e.bind("<Escape>", cancel)


# --------------------------------------------------------------------------
# Scrolling column with the light-grey scrollbar
# --------------------------------------------------------------------------
class ScrollPanel(tk.Frame):
    def __init__(self, master, ui: UI, router: WheelRouter, scrollbar_parent=None, bg=T.BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(scrollbar_parent or self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        if scrollbar_parent is None:
            self.bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight())))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        router.register(self, lambda n, e: self.canvas.yview_scroll(-int(round(n * 3)) or (-1 if n > 0 else 1), "units"))

    def to_top(self):
        self.canvas.yview_moveto(0)


# --------------------------------------------------------------------------
# Colour wheels (stacked, as in the original workbench)
# --------------------------------------------------------------------------
class ColorWheels(tk.Canvas):
    LABELS = ("SHADOWS", "MIDTONES", "HIGHLIGHTS")

    def __init__(self, master, ui: UI, on_begin: Callable[[], None], on_change: Callable[[int, Tuple[float, float]], None]):
        self.ui = ui
        self.radius = ui.px(55)
        self.pitch = ui.px(140)
        super().__init__(master, width=ui.px(360), height=self.pitch * 3 + ui.px(20), bg=T.BG,
                         highlightthickness=0, bd=0)
        self.on_begin, self.on_change = on_begin, on_change
        self.positions: List[Tuple[float, float]] = [(0.0, 0.0)] * 3
        self._photo = ImageTk.PhotoImage(Image.fromarray(color_wheel_rgba(self.radius, 200), "RGBA"))
        self._active = None
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_active", None))
        self.bind("<Double-Button-1>", self._reset_at)
        self.bind("<Button-3>", self._reset_at)

    def _centers(self):
        cx = max(self.winfo_width(), self.ui.px(360)) / 2
        return [(cx, self.ui.px(75) + i * self.pitch) for i in range(3)]

    def draw(self):
        self.delete("all")
        r = self.radius
        for i, (cx, cy) in enumerate(self._centers()):
            self.create_image(cx - r, cy - r, image=self._photo, anchor="nw")
            self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.LINE)
            self.create_line(cx - 5, cy, cx + 5, cy, fill="#222222")
            self.create_line(cx, cy - 5, cx, cy + 5, fill="#222222")
            px, py = self.positions[i]
            tx, ty = cx + px * r, cy + py * r
            self.create_oval(tx - 3, ty - 3, tx + 3, ty + 3, fill="#ffffff", outline="#000000")
            self.create_text(cx, cy + r + self.ui.px(15), text=self.LABELS[i], fill=T.TEXT, font=self.ui.fonts.label)

    def _hit(self, x, y):
        for i, (cx, cy) in enumerate(self._centers()):
            if abs(y - cy) <= self.pitch / 2:
                return i
        return None

    def _press(self, e):
        i = self._hit(e.x, e.y)
        self._active = i
        if i is not None:
            self.on_begin()
            self._move(i, e.x, e.y)

    def _drag(self, e):
        if self._active is not None:
            self._move(self._active, e.x, e.y)

    def _move(self, i, x, y):
        cx, cy = self._centers()[i]
        dx, dy = (x - cx) / self.radius, (y - cy) / self.radius
        d = math.hypot(dx, dy)
        if d > 1.0:
            dx, dy = dx / d, dy / d
        self.positions[i] = (dx, dy)
        self.draw()
        self.on_change(i, (dx, dy))

    def _reset_at(self, e):
        i = self._hit(e.x, e.y)
        if i is None or self.positions[i] == (0.0, 0.0):
            return
        self.on_begin()
        self.positions[i] = (0.0, 0.0)
        self.draw()
        self.on_change(i, (0.0, 0.0))

    def set_positions(self, positions):
        self.positions = [tuple(p) for p in positions]
        self.draw()


# --------------------------------------------------------------------------
# Tone curve
# --------------------------------------------------------------------------
class ToneCurve(tk.Canvas):
    MAX_POINTS = 12

    def __init__(self, master, ui: UI, on_begin: Callable[[], None], on_change: Callable[[List[Tuple[float, float]]], None]):
        self.ui = ui
        super().__init__(master, width=ui.px(360), height=ui.px(280), bg=T.BG, highlightthickness=0,
                         bd=0, cursor="crosshair")
        self.on_begin, self.on_change = on_begin, on_change
        self.points: List[Tuple[float, float]] = [(0.0, 0.0), (255.0, 255.0)]
        self.hist: Optional[np.ndarray] = None
        self._drag_idx: Optional[int] = None
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_idx", None))
        self.bind("<Double-Button-1>", self._remove)
        self.bind("<Button-3>", self._remove)

    def _geom(self):
        w, h = max(self.winfo_width(), 20), max(self.winfo_height(), 20)
        pad = self.ui.px(10)
        return pad, w - 2 * pad, h - 2 * pad

    def _to_screen(self, p):
        pad, w, h = self._geom()
        return pad + p[0] / 255.0 * w, pad + (1 - p[1] / 255.0) * h

    def _to_value(self, x, y):
        pad, w, h = self._geom()
        vx = (x - pad) / max(1, w) * 255.0
        vy = (1 - (y - pad) / max(1, h)) * 255.0
        return max(0.0, min(255.0, vx)), max(0.0, min(255.0, vy))

    def draw(self):
        self.delete("all")
        pad, w, h = self._geom()
        if self.hist is not None:
            hv = self.hist / max(float(self.hist.max()), 1.0)
            pts = [pad, pad + h]
            for i, v in enumerate(hv):
                pts += [pad + i / 255.0 * w, pad + h - v * h * 0.9]
            pts += [pad + w, pad + h]
            self.create_polygon(pts, fill="#161617", outline="")
        for i in range(1, 4):
            self.create_line(pad + w * i / 4, pad, pad + w * i / 4, pad + h, fill="#1c1c1c")
            self.create_line(pad, pad + h * i / 4, pad + w, pad + h * i / 4, fill="#1c1c1c")
        self.create_rectangle(pad, pad, pad + w, pad + h, outline=T.LINE)
        self.create_line(pad, pad + h, pad + w, pad, fill=T.LINE, dash=(2, 3))
        lut = compute_spline_lut(self.points)
        coords = []
        for i in range(65):
            x = i * 255 / 64
            coords += list(self._to_screen((x, float(lut[int(round(x))]))))
        self.create_line(*coords, fill=T.G10, smooth=True)
        r = self.ui.px(4)
        for i, p in enumerate(self.points):
            sx, sy = self._to_screen(p)
            self.create_rectangle(sx - r, sy - r, sx + r, sy + r, fill=T.YELLOW if i == self._drag_idx else T.BG,
                                  outline=T.YELLOW if i == self._drag_idx else T.G35)

    def _nearest(self, x, y):
        tol = self.ui.px(9)
        best, best_d = None, tol
        for i, p in enumerate(self.points):
            sx, sy = self._to_screen(p)
            d = math.hypot(sx - x, sy - y)
            if d <= best_d:
                best, best_d = i, d
        return best

    def _press(self, e):
        idx = self._nearest(e.x, e.y)
        self.on_begin()
        if idx is None:
            if len(self.points) >= self.MAX_POINTS:
                return
            vx, vy = self._to_value(e.x, e.y)
            if any(abs(p[0] - vx) < 6 for p in self.points):
                return
            self.points.append((vx, vy))
            self.points.sort()
            idx = self.points.index((vx, vy))
            self.on_change(list(self.points))
        self._drag_idx = idx
        self.draw()

    def _drag(self, e):
        i = self._drag_idx
        if i is None:
            return
        vx, vy = self._to_value(e.x, e.y)
        if i == 0:
            vx = 0.0
        elif i == len(self.points) - 1:
            vx = 255.0
        else:
            vx = max(self.points[i - 1][0] + 4, min(self.points[i + 1][0] - 4, vx))
        self.points[i] = (vx, vy)
        self.draw()
        self.on_change(list(self.points))

    def _remove(self, e):
        idx = self._nearest(e.x, e.y)
        if idx is None or idx in (0, len(self.points) - 1):
            return
        self.on_begin()
        del self.points[idx]
        self._drag_idx = None
        self.draw()
        self.on_change(list(self.points))

    def set_points(self, points):
        self.points = sorted((float(x), float(y)) for x, y in points)
        self.draw()

    def set_histogram(self, hist: Optional[np.ndarray]):
        self.hist = hist
        self.draw()
