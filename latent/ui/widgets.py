"""Widgets drawn to the LATENT Illustrator artboards (see theme.py)."""
from __future__ import annotations

import math
import sys
import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from .. import theme as T
from ..imaging.pipeline import color_wheel_rgba, compute_spline_lut


class UI:
    """Layout scale relative to the 1920x1080 artboard, plus fonts."""

    def __init__(self, root: tk.Misc):
        self.root = root
        sw = root.winfo_screenwidth()
        self.scale = max(0.6, min(2.5, sw / T.DESIGN_W))
        self.fonts = T.Fonts(root, scale=self.scale)

    def px(self, n: float) -> int:
        return int(round(n * self.scale))


def bgr_to_photo(bgr: np.ndarray) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))


def rgb_to_photo(rgb: np.ndarray) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(Image.fromarray(rgb))


def bordered(master, **kw) -> tk.Frame:
    """Frame with a 1px #58595b outline (focus never changes its colour)."""
    return tk.Frame(master, bg=T.BG, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE, **kw)


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
# Scrollbar (Illustrator style: no arrows, light trough, 5-line grip)
# --------------------------------------------------------------------------
class Scrollbar(tk.Canvas):
    def __init__(self, master, ui: UI, command: Optional[Callable] = None):
        super().__init__(master, width=ui.px(20), bg=T.SCROLL_TROUGH, highlightthickness=0, bd=0)
        self.ui = ui
        self.command = command
        self.first, self.last = 0.0, 1.0
        self._drag = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))

    def configure(self, cnf=None, **kw):  # accept command= like ttk
        if "command" in kw:
            self.command = kw.pop("command")
        if kw or cnf:
            return super().configure(cnf, **kw)

    config = configure

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def _thumb(self):
        h = max(self.winfo_height(), 1)
        frac = self.last - self.first
        if frac >= 0.999:
            # nothing to scroll: a centred thumb, as drawn in the artboards
            size = self.ui.px(139)
            top = (h - size) / 2
            return top, top + size
        size = min(h, max(self.ui.px(139), frac * h))
        span = max(1e-6, 1.0 - frac)
        top = (self.first / span) * (h - size)
        return top, top + size

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        self.create_rectangle(0, 0, w - 1, h - 1, fill=T.SCROLL_TROUGH, outline=T.SCROLL_EDGE)
        y0, y1 = self._thumb()
        self.create_rectangle(0, y0, w - 1, y1, fill=T.SCROLL_THUMB, outline=T.SCROLL_EDGE)
        cy = (y0 + y1) / 2
        for k in (-2, -1, 0, 1, 2):
            gy = cy + k * self.ui.px(2.4)
            self.create_line(self.ui.px(2.5), gy, w - self.ui.px(2.5), gy, fill=T.SCROLL_GRIP)

    def _press(self, e):
        if self.last - self.first >= 0.999:
            return
        y0, y1 = self._thumb()
        if y0 <= e.y <= y1:
            self._drag = (e.y, self.first)
        elif self.command:
            self.command("scroll", -1 if e.y < y0 else 1, "pages")

    def _motion(self, e):
        if not self._drag or not self.command:
            return
        y_start, first0 = self._drag
        h = max(self.winfo_height(), 1)
        y0, y1 = self._thumb()
        travel = max(1.0, h - (y1 - y0))
        span = 1.0 - (self.last - self.first)
        self.command("moveto", max(0.0, min(span, first0 + (e.y - y_start) / travel * span)))


# --------------------------------------------------------------------------
# Buttons
# --------------------------------------------------------------------------
class Button(tk.Canvas):
    """Outlined console button with an optional icon.

    icon: "back" (triangle before the label), "forward" (triangle after) or
    "menu" (yellow down triangle after the label, as on SAVE).
    Hover lightens outline and label; press darkens the fill.
    """

    def __init__(self, master, ui: UI, text: str, command: Optional[Callable] = None, icon: Optional[str] = None,
                 width: Optional[int] = None, height: int = T.BAR_H, font=None, accent: Optional[str] = None, **_):
        self.ui = ui
        self.text, self.command, self.icon = text, command, icon
        self.font = font or ui.fonts.button
        self.accent = accent
        self._hover = self._pressed = self._active = False
        self._enabled = True
        if width:
            req_w = ui.px(width)
        else:  # natural width: label + icon + side padding
            tw = int(ui.root.tk.call("font", "measure", self.font, text))
            req_w = tw + ui.px(28) + (ui.px(22) if icon else 0)
        super().__init__(master, bg=T.BG, highlightthickness=0, bd=0, cursor="hand2",
                         width=req_w, height=ui.px(height))
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, "_" + k, v)
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        lit = (self._hover or self._active) and self._enabled
        line = "#2e2f30" if not self._enabled else (T.HOVER if lit else T.LINE)
        fg = "#2e2f30" if not self._enabled else (T.HOVER if lit else (self.accent or T.TEXT))
        self.create_rectangle(0, 0, w - 1, h - 1, outline=line, fill=T.BG_BUTTON_PRESS if self._pressed else T.BG)
        tw = int(self.ui.root.tk.call("font", "measure", self.font, self.text))
        s = self.ui.px(6.2)
        gap = self.ui.px(8) if self.icon else 0
        icon_w = (s if self.icon in ("back", "forward") else 2 * s) if self.icon else 0
        x = (w - tw - icon_w - gap) / 2
        cy = h / 2
        if self.icon == "back":
            self.create_polygon(x + s, cy - s, x, cy, x + s, cy + s, fill=fg, outline=fg)
            x += s + gap
        self.create_text(x, cy, text=self.text, anchor="w", fill=fg, font=self.font)
        x += tw + gap
        if self.icon == "forward":
            self.create_polygon(x, cy - s, x + s, cy, x, cy + s, fill=fg, outline=fg)
        elif self.icon == "menu":
            color = T.YELLOW if self._enabled else "#2e2f30"
            self.create_polygon(x, cy - s / 2, x + 2 * s, cy - s / 2, x + s, cy + s / 2, fill=color, outline=color)

    def _release(self, e):
        self._set(pressed=False)
        if self._enabled and self.command and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            self.command()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.config(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_active(self, active: bool):
        self._active = active
        self._draw()

    def set_text(self, text: str):
        self.text = text
        self._draw()


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
class Box(tk.Frame):
    """A section frame. While the pointer or a drag is inside it, its
    outline turns yellow (the FILTER SLIDERS box in the artboards)."""

    def __init__(self, master, ui: UI, title: Optional[str] = None, caption_font=None, pad: int = 8, **_):
        super().__init__(master, bg=T.BG, highlightthickness=1, highlightbackground=T.LINE, highlightcolor=T.LINE)
        self.ui = ui
        self._busy = 0
        self.caption = None
        if title:
            self.caption = tk.Label(self, text=title.upper(), bg=T.BG, fg=T.TEXT, font=caption_font or ui.fonts.title, anchor="w")
            self.caption.pack(fill="x", padx=ui.px(pad), pady=(ui.px(6), 0))
        self.body = tk.Frame(self, bg=T.BG)
        self.body.pack(fill="x", padx=ui.px(pad), pady=(ui.px(4), ui.px(10)))
        self._check_after = None
        self.track(self)

    def track(self, widget: tk.Misc):
        widget.bind("<Enter>", lambda e: self._schedule(), add="+")
        widget.bind("<Leave>", lambda e: self._schedule(), add="+")
        for child in widget.winfo_children():
            self.track(child)

    def hold(self, on: bool):
        self._busy = max(0, self._busy + (1 if on else -1))
        self._schedule()

    def _schedule(self):
        if self._check_after:
            self.after_cancel(self._check_after)
        self._check_after = self.after(15, self._check)

    def _check(self):
        self._check_after = None
        try:
            px, py = self.winfo_pointerxy()
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            inside = x0 <= px < x0 + self.winfo_width() and y0 <= py < y0 + self.winfo_height()
        except tk.TclError:
            return
        self.set_active(inside or self._busy > 0)

    def set_active(self, on: bool):
        color = T.YELLOW if on else T.LINE
        self.config(highlightbackground=color, highlightcolor=color)

    def set_title(self, title: str):
        if self.caption is not None:
            self.caption.config(text=title.upper())


# --------------------------------------------------------------------------
# Slider
# --------------------------------------------------------------------------
class Slider(tk.Frame):
    """Caption (11.34px) above a 20px trough, value (22.68px) at the right.

    The thumb is a 40px frame around a filled 15px grip with three lines.
    Hover fills the frame grey; dragging lightens it and turns the value
    yellow; a value away from its default reads light.
    Double-click resets; click the value to type an exact number.
    """

    def __init__(self, master, ui: UI, label: str, minimum: float, maximum: float, default: float,
                 value: Optional[float] = None, kind: str = "float", decimals: Optional[int] = None,
                 on_change: Optional[Callable[[float], None]] = None,
                 on_begin: Optional[Callable[[], None]] = None, box: Optional[Box] = None, bg=T.BG):
        super().__init__(master, bg=bg)
        self.ui, self.minimum, self.maximum, self.default, self.kind = ui, float(minimum), float(maximum), float(default), kind
        span = self.maximum - self.minimum
        self.decimals = decimals if decimals is not None else (0 if kind == "int" else (2 if span <= 5 else 1))
        self.on_change, self.on_begin, self.box = on_change, on_begin, box
        self.value = self._coerce(default if value is None else value)
        self._entry: Optional[tk.Entry] = None
        self._hover = self._dragging = False

        self.name_lbl = tk.Label(self, text=label.upper(), bg=bg, fg=T.TEXT, font=ui.fonts.label, anchor="w")
        self.name_lbl.pack(fill="x")
        row = tk.Frame(self, bg=bg)
        row.pack(fill="x")
        self.value_lbl = tk.Label(row, text="", bg=bg, fg=T.TEXT, font=ui.fonts.value, anchor="e",
                                  width=5, cursor="xterm")
        self.value_lbl.pack(side="right")
        self.canvas = tk.Canvas(row, height=ui.px(20), bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(side="left", fill="x", expand=True, padx=(0, ui.px(20)))

        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", lambda e: self.set(self._v_for(e.x), notify=True))
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.reset(notify=True))
        self.canvas.bind("<Enter>", lambda e: self._set_hover(True), add="+")
        self.canvas.bind("<Leave>", lambda e: self._set_hover(False), add="+")
        self.name_lbl.bind("<Double-Button-1>", lambda e: self.reset(notify=True))
        self.value_lbl.bind("<Button-1>", self._edit)
        self._refresh()

    def _coerce(self, v: float) -> float:
        v = min(self.maximum, max(self.minimum, float(v)))
        return float(int(round(v))) if self.kind == "int" else v

    def _fmt(self, v: float) -> str:
        return f"{v:.{self.decimals}f}"

    def _tw(self) -> float:
        return self.ui.px(40.31)

    def _x_for(self, v: float) -> float:
        w, tw = max(self.canvas.winfo_width(), 20), self._tw()
        return tw / 2 + (v - self.minimum) / (self.maximum - self.minimum) * (w - tw)

    def _v_for(self, x: float) -> float:
        w, tw = max(self.canvas.winfo_width(), 20), self._tw()
        t = (x - tw / 2) / max(1.0, w - tw)
        return self.minimum + max(0.0, min(1.0, t)) * (self.maximum - self.minimum)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height() or self.ui.px(20)
        c.create_rectangle(0, 0, w - 1, h - 1, outline=T.LINE)
        x, tw, gw = self._x_for(self.value), self._tw(), self.ui.px(15)
        frame_fill = T.HOVER if self._dragging else (T.THUMB_FILL if self._hover else "")
        c.create_rectangle(x - tw / 2, 0, x + tw / 2, h - 1, outline=T.THUMB_LINE, fill=frame_fill)
        c.create_rectangle(x - gw / 2, 0, x + gw / 2, h - 1, outline=T.THUMB_LINE, fill=T.THUMB_FILL)
        for k in (-2.6, 0, 2.8):
            gx = x + self.ui.px(k)
            c.create_line(gx, self.ui.px(2.5), gx, h - self.ui.px(2.5), fill=T.GRIP)

    def _refresh(self):
        changed = abs(self.value - self.default) > 1e-9
        fg = T.YELLOW if self._dragging else (T.TEXT_HI if changed else T.TEXT)
        self.value_lbl.config(text=self._fmt(self.value), fg=fg)
        self.name_lbl.config(fg=T.HOVER if (self._hover or self._dragging) else T.TEXT)
        self._draw()

    def _set_hover(self, on: bool):
        if on != self._hover:
            self._hover = on
            self._refresh()

    def _press(self, e):
        if self.on_begin:
            self.on_begin()
        self._dragging = True
        if self.box:
            self.box.hold(True)
        self.set(self._v_for(e.x), notify=True)
        self._refresh()

    def _release(self, _e):
        if self._dragging and self.box:
            self.box.hold(False)
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
                     justify="right", width=5)
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
# Scrolling column
# --------------------------------------------------------------------------
class ScrollPanel(tk.Frame):
    """Scrolls its ``inner`` frame; the scrollbar lives in the app's slot."""

    def __init__(self, master, ui: UI, router: WheelRouter, bar: Scrollbar):
        super().__init__(master, bg=T.BG)
        self.canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=T.BG)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(fill="both", expand=True)
        self.bar = bar
        bar.configure(command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight())))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        router.register(self, lambda n, e: self.canvas.yview_scroll(-int(round(n * 3)) or (-1 if n > 0 else 1), "units"))

    def to_top(self):
        self.canvas.yview_moveto(0)


# --------------------------------------------------------------------------
# Colour wheels: large, stacked HIGHLIGHTS / MIDTONES / SHADOWS
# --------------------------------------------------------------------------
class ColorWheels(tk.Canvas):
    ORDER = (2, 1, 0)                       # displayed top-down; state index 0 = shadows
    LABELS = {0: "SHADOWS", 1: "MIDTONES", 2: "HIGHLIGHTS"}

    def __init__(self, master, ui: UI, on_begin: Callable[[], None], on_change: Callable[[int, Tuple[float, float]], None]):
        self.ui = ui
        self.radius = ui.px(100)
        self.pitch = ui.px(270)
        super().__init__(master, height=self.pitch * 3, bg=T.BG, highlightthickness=0, bd=0)
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

    def _centers(self) -> Dict[int, Tuple[float, float]]:
        cx = max(self.winfo_width(), 2 * self.radius) / 2
        return {idx: (cx, self.ui.px(115) + row * self.pitch) for row, idx in enumerate(self.ORDER)}

    def draw(self):
        self.delete("all")
        r = self.radius
        for idx, (cx, cy) in self._centers().items():
            self.create_image(cx - r, cy - r, image=self._photo, anchor="nw")
            px, py = self.positions[idx]
            tx, ty = cx + px * r, cy + py * r
            k = self.ui.px(6.3)
            if px or py:
                self.create_line(cx, cy, tx, ty, fill=T.LINE)
            self.create_oval(tx - k, ty - k, tx + k, ty + k, fill=T.LINE, outline="#000000")
            self.create_text(cx, cy + self.ui.px(125), text=self.LABELS[idx], fill=T.TEXT, font=self.ui.fonts.label)

    def _hit(self, x, y):
        for idx, (cx, cy) in self._centers().items():
            if abs(y - cy) <= self.pitch / 2:
                return idx
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
        super().__init__(master, height=ui.px(300), bg=T.BG, highlightthickness=0, bd=0, cursor="crosshair")
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
        size = min(w, h) - self.ui.px(10)
        return (w - size) / 2, (h - size) / 2, size

    def _to_screen(self, p):
        x0, y0, s = self._geom()
        return x0 + p[0] / 255.0 * s, y0 + (1 - p[1] / 255.0) * s

    def _to_value(self, x, y):
        x0, y0, s = self._geom()
        return (max(0.0, min(255.0, (x - x0) / max(1, s) * 255.0)),
                max(0.0, min(255.0, (1 - (y - y0) / max(1, s)) * 255.0)))

    def draw(self):
        self.delete("all")
        x0, y0, s = self._geom()
        if self.hist is not None:
            hv = self.hist / max(float(self.hist.max()), 1.0)
            pts = [x0, y0 + s]
            for i, v in enumerate(hv):
                pts += [x0 + i / 255.0 * s, y0 + s - v * s * 0.9]
            pts += [x0 + s, y0 + s]
            self.create_polygon(pts, fill="#1a1a1b", outline="")
        for i in range(1, 4):
            self.create_line(x0 + s * i / 4, y0, x0 + s * i / 4, y0 + s, fill="#232324")
            self.create_line(x0, y0 + s * i / 4, x0 + s, y0 + s * i / 4, fill="#232324")
        self.create_rectangle(x0, y0, x0 + s, y0 + s, outline=T.LINE)
        self.create_line(x0, y0 + s, x0 + s, y0, fill=T.LINE, dash=(2, 3))
        lut = compute_spline_lut(self.points)
        coords = []
        for i in range(65):
            x = i * 255 / 64
            coords += list(self._to_screen((x, float(lut[int(round(x))]))))
        self.create_line(*coords, fill=T.G10, smooth=True)
        r = self.ui.px(4)
        for i, p in enumerate(self.points):
            sx, sy = self._to_screen(p)
            on = i == self._drag_idx
            self.create_rectangle(sx - r, sy - r, sx + r, sy + r, fill=T.YELLOW if on else T.BG,
                                  outline=T.YELLOW if on else T.HOVER)

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
