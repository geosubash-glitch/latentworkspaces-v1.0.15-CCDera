"""Custom Tk widgets drawn to match the Latent design language.

Native ``tk.Button`` ignores background colours on macOS and ``ttk.Scale``
cannot show a default-centred fill, so the controls here are drawn by hand.
"""
from __future__ import annotations

import math
import sys
import tkinter as tk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from .. import theme as T
from ..imaging.pipeline import color_wheel_rgba, compute_spline_lut


class UI:
    """Shared fonts + pixel scale handed to every view."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.fonts = T.Fonts(root)
        self.scale = T.ui_scale(root)

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
    """Sends wheel events to the scrollable area under the pointer.

    Handles Windows (delta 120), macOS (small deltas) and X11 (Button-4/5).
    """

    def __init__(self, root: tk.Misc):
        self.root = root
        self.handlers: Dict[str, Callable[[float, tk.Event], None]] = {}
        root.bind_all("<MouseWheel>", self._on_wheel, add="+")
        root.bind_all("<Shift-MouseWheel>", self._on_wheel, add="+")
        root.bind_all("<Button-4>", self._on_wheel, add="+")
        root.bind_all("<Button-5>", self._on_wheel, add="+")

    def register(self, widget: tk.Misc, handler: Callable[[float, tk.Event], None]) -> None:
        self.handlers[str(widget)] = handler

    def _on_wheel(self, event: tk.Event):
        if getattr(event, "num", None) == 4:
            notches = 1.0
        elif getattr(event, "num", None) == 5:
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
    STYLES = {
        "primary": (T.ACCENT, T.ON_ACCENT, T.ACCENT_HOVER, T.ON_ACCENT, T.ACCENT),
        "secondary": (T.BG_RAISED, T.TEXT, T.BG_HOVER, T.TEXT_HI, T.LINE_STRONG),
        "ghost": (T.BG_PANEL, T.TEXT_DIM, T.BG_HOVER, T.TEXT_HI, T.BG_PANEL),
        "toolbar": (T.BG_VIEW, T.TEXT_DIM, T.BG_HOVER, T.TEXT_HI, T.BG_VIEW),
    }

    def __init__(self, master, ui: UI, text: str, command: Optional[Callable] = None, style: str = "secondary",
                 font=None, padx: int = 14, pady: int = 7, tooltip: Optional[str] = None, bg_override=None, **kw):
        bg, fg, hbg, hfg, border = self.STYLES[style]
        if bg_override:
            bg = border = bg_override
        self._ui = ui
        self._colors = (bg, fg, hbg, hfg, border)
        self._command = command
        self._enabled = True
        self._active = False
        super().__init__(master, text=text, bg=bg, fg=fg, font=font or ui.fonts.mono_bold,
                         padx=ui.px(padx), pady=ui.px(pady), cursor="hand2", bd=0,
                         highlightthickness=1, highlightbackground=border, highlightcolor=border, **kw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        if tooltip:
            Tooltip(self, ui, tooltip)

    def _paint(self, hover: bool):
        bg, fg, hbg, hfg, border = self._colors
        if not self._enabled:
            if bg == T.ACCENT:  # a disabled call-to-action must not look clickable
                self.config(bg=T.BG_RAISED, fg=T.TEXT_FAINT, highlightbackground=T.LINE, cursor="arrow")
            else:
                self.config(bg=bg, fg=T.TEXT_FAINT, highlightbackground=border, cursor="arrow")
        elif self._active:
            self.config(bg=T.ACCENT_DIM if bg != T.ACCENT else T.ACCENT_HOVER, fg=T.TEXT_HI if bg != T.ACCENT else T.ON_ACCENT,
                        highlightbackground=T.ACCENT, cursor="hand2")
        else:
            self.config(bg=hbg if hover else bg, fg=hfg if hover else fg, highlightbackground=border, cursor="hand2")

    def _enter(self, _e):
        self._paint(True)

    def _leave(self, _e):
        self._paint(False)

    def _press(self, _e):
        if self._enabled:
            self.config(bg=T.BG_INPUT if self._colors[0] != T.ACCENT else T.ACCENT_DIM)

    def _release(self, e):
        if not self._enabled:
            return
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        self._paint(inside)
        if inside and self._command:
            self._command()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._paint(False)

    def set_active(self, active: bool):
        self._active = active
        self._paint(False)

    def set_text(self, text: str):
        self.config(text=text)


class Tooltip:
    def __init__(self, widget: tk.Widget, ui: UI, text: str, delay: int = 450):
        self.widget, self.ui, self.text, self.delay = widget, ui, text, delay
        self._after = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self._tip or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.ui.px(6)
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=T.LINE_STRONG)
        tk.Label(tip, text=self.text, bg=T.BG_RAISED, fg=T.TEXT, font=self.ui.fonts.body_small,
                 padx=self.ui.px(8), pady=self.ui.px(4), justify="left").pack(padx=1, pady=1)
        tip.update_idletasks()
        sw = self.widget.winfo_screenwidth()
        x = min(x, sw - tip.winfo_reqwidth() - 4)
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _e=None):
        self._cancel()
        if self._tip:
            self._tip.destroy()
            self._tip = None


class Segmented(tk.Frame):
    """Row of mutually exclusive options."""

    def __init__(self, master, ui: UI, options: Sequence[Tuple[str, str]], value: str,
                 command: Callable[[str], None], bg=T.BG_PANEL):
        super().__init__(master, bg=bg)
        self._buttons: Dict[str, Button] = {}
        self._command = command
        for key, label in options:
            b = Button(self, ui, label, command=lambda k=key: self.select(k, notify=True), style="ghost",
                       font=ui.fonts.label, padx=8, pady=3)
            b.pack(side="left", padx=(0, ui.px(2)))
            self._buttons[key] = b
        self.select(value)

    def select(self, key: str, notify: bool = False):
        for k, b in self._buttons.items():
            b.set_active(k == key)
        if notify:
            self._command(key)


# --------------------------------------------------------------------------
# Slider
# --------------------------------------------------------------------------
class Slider(tk.Frame):
    """Labelled slider with a fill that grows from the default value.

    * drag or click the track to set
    * double-click the track or label to reset to default
    * click the value to type an exact number
    """

    def __init__(self, master, ui: UI, label: str, minimum: float, maximum: float, default: float,
                 value: Optional[float] = None, kind: str = "float", decimals: Optional[int] = None,
                 on_change: Optional[Callable[[float], None]] = None,
                 on_begin: Optional[Callable[[], None]] = None, bg=T.BG_PANEL):
        super().__init__(master, bg=bg)
        self.ui, self.minimum, self.maximum, self.default, self.kind = ui, float(minimum), float(maximum), float(default), kind
        span = self.maximum - self.minimum
        self.decimals = decimals if decimals is not None else (0 if kind == "int" else (2 if span <= 5 else 1))
        self.on_change, self.on_begin = on_change, on_begin
        self.value = self._coerce(default if value is None else value)
        self._entry: Optional[tk.Entry] = None

        head = tk.Frame(self, bg=bg)
        head.pack(fill="x")
        self.name_lbl = tk.Label(head, text=label.upper(), bg=bg, fg=T.TEXT_DIM, font=ui.fonts.label, anchor="w")
        self.name_lbl.pack(side="left")
        self.value_lbl = tk.Label(head, text="", bg=bg, fg=T.TEXT, font=ui.fonts.value, anchor="e", cursor="xterm")
        self.value_lbl.pack(side="right")
        self.canvas = tk.Canvas(self, height=ui.px(18), bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(fill="x", pady=(ui.px(2), 0))

        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Double-Button-1>", lambda e: self.reset(notify=True))
        self.name_lbl.bind("<Double-Button-1>", lambda e: self.reset(notify=True))
        self.value_lbl.bind("<Button-1>", self._edit)
        Tooltip(self.name_lbl, ui, "Double-click to reset")
        self._refresh_label()

    # value helpers
    def _coerce(self, v: float) -> float:
        v = min(self.maximum, max(self.minimum, float(v)))
        return float(int(round(v))) if self.kind == "int" else v

    def _fmt(self, v: float) -> str:
        return f"{v:.{self.decimals}f}"

    def _x_for(self, v: float) -> float:
        w = max(self.canvas.winfo_width(), 10)
        pad = self.ui.px(7)
        return pad + (v - self.minimum) / (self.maximum - self.minimum) * (w - 2 * pad)

    def _v_for(self, x: float) -> float:
        w = max(self.canvas.winfo_width(), 10)
        pad = self.ui.px(7)
        t = (x - pad) / max(1.0, w - 2 * pad)
        return self.minimum + max(0.0, min(1.0, t)) * (self.maximum - self.minimum)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        h = c.winfo_height() or self.ui.px(18)
        w = c.winfo_width()
        cy = h // 2
        pad = self.ui.px(7)
        c.create_line(pad, cy, w - pad, cy, fill=T.LINE_STRONG, width=max(2, self.ui.px(2)))
        x0, x1 = self._x_for(self.default), self._x_for(self.value)
        changed = abs(self.value - self.default) > 1e-9
        if changed:
            c.create_line(x0, cy, x1, cy, fill=T.ACCENT, width=max(2, self.ui.px(2)))
        c.create_line(x0, cy - self.ui.px(4), x0, cy + self.ui.px(4), fill=T.LINE_FOCUS, width=1)
        r = self.ui.px(6)
        c.create_oval(x1 - r, cy - r, x1 + r, cy + r, fill=T.TEXT_HI if changed else T.TEXT,
                      outline=T.BG_PANEL, width=max(1, self.ui.px(2)))

    def _refresh_label(self):
        changed = abs(self.value - self.default) > 1e-9
        self.value_lbl.config(text=self._fmt(self.value), fg=T.ACCENT if changed else T.TEXT_DIM)
        self.name_lbl.config(fg=T.TEXT if changed else T.TEXT_DIM)
        self._draw()

    # interaction
    def _press(self, e):
        if self.on_begin:
            self.on_begin()
        self._set_from_x(e.x)

    def _drag(self, e):
        self._set_from_x(e.x)

    def _set_from_x(self, x):
        self.set(self._v_for(x), notify=True)

    def set(self, v: float, notify: bool = False):
        v = self._coerce(v)
        if abs(v - self.value) < 1e-12:
            return
        self.value = v
        self._refresh_label()
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
        e = tk.Entry(self.value_lbl.master, bg=T.BG_INPUT, fg=T.TEXT_HI, insertbackground=T.TEXT_HI,
                     font=self.ui.fonts.value, bd=0, highlightthickness=1, highlightcolor=T.ACCENT,
                     highlightbackground=T.LINE_STRONG, justify="right", width=8)
        e.insert(0, self._fmt(self.value))
        e.place(in_=self.value_lbl, relx=1.0, rely=0.5, anchor="e")
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
# Sections & scrolling
# --------------------------------------------------------------------------
class Section(tk.Frame):
    def __init__(self, master, ui: UI, title: str, on_reset: Optional[Callable] = None, open_: bool = True,
                 bg=T.BG_PANEL):
        super().__init__(master, bg=bg)
        self.ui = ui
        self._open = open_
        head = tk.Frame(self, bg=bg, cursor="hand2")
        head.pack(fill="x", pady=(ui.px(10), ui.px(6)))
        self.chev = tk.Label(head, text="▾" if open_ else "▸", bg=bg, fg=T.TEXT_DIM, font=ui.fonts.mono_bold, width=2, anchor="w")
        self.chev.pack(side="left")
        self.title = tk.Label(head, text=title.upper(), bg=bg, fg=T.TEXT_HI, font=ui.fonts.mono_bold, anchor="w")
        self.title.pack(side="left")
        for w in (head, self.chev, self.title):
            w.bind("<Button-1>", lambda e: self.toggle())
        if on_reset:
            r = tk.Label(head, text="RESET", bg=bg, fg=T.TEXT_FAINT, font=ui.fonts.micro, cursor="hand2")
            r.pack(side="right")
            r.bind("<Enter>", lambda e: r.config(fg=T.ACCENT))
            r.bind("<Leave>", lambda e: r.config(fg=T.TEXT_FAINT))
            r.bind("<Button-1>", lambda e: on_reset())
        tk.Frame(self, bg=T.LINE, height=1).pack(fill="x")
        self.body = tk.Frame(self, bg=bg)
        if open_:
            self.body.pack(fill="x", pady=(ui.px(8), ui.px(4)))

    def toggle(self):
        self._open = not self._open
        self.chev.config(text="▾" if self._open else "▸")
        if self._open:
            self.body.pack(fill="x", pady=(self.ui.px(8), self.ui.px(4)))
        else:
            self.body.pack_forget()


class ScrollPanel(tk.Frame):
    """Vertically scrolling container with a slim scrollbar."""

    def __init__(self, master, ui: UI, router: WheelRouter, bg=T.BG_PANEL):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = tk.Canvas(self, width=ui.px(6), bg=bg, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y", padx=(ui.px(4), 0))
        self.inner.bind("<Configure>", lambda e: self._update())
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfigure(self._win, width=e.width), self._update()))
        self.bar.bind("<ButtonPress-1>", self._bar_press)
        self.bar.bind("<B1-Motion>", self._bar_drag)
        router.register(self, lambda n, e: self.scroll(-n))
        self._drag_off = 0.0

    def _update(self):
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        self._draw_bar()

    def _draw_bar(self):
        self.bar.delete("all")
        first, last = self.canvas.yview()
        if last - first >= 0.999:
            return
        h = self.bar.winfo_height()
        w = self.bar.winfo_width()
        self.bar.create_rectangle(0, first * h, w, last * h, fill=T.LINE_STRONG, outline="")

    def scroll(self, notches: float):
        self.canvas.yview_scroll(int(round(notches * 3)) or (1 if notches > 0 else -1), "units")
        self._draw_bar()

    def _bar_press(self, e):
        first, last = self.canvas.yview()
        h = max(1, self.bar.winfo_height())
        pos = e.y / h
        if first <= pos <= last:
            self._drag_off = pos - first
        else:
            self._drag_off = (last - first) / 2
            self._bar_drag(e)

    def _bar_drag(self, e):
        h = max(1, self.bar.winfo_height())
        self.canvas.yview_moveto(max(0.0, e.y / h - self._drag_off))
        self._draw_bar()

    def to_top(self):
        self.canvas.yview_moveto(0)
        self._draw_bar()


# --------------------------------------------------------------------------
# Colour wheels
# --------------------------------------------------------------------------
class ColorWheels(tk.Canvas):
    LABELS = ("SHADOWS", "MIDTONES", "HIGHLIGHTS")

    def __init__(self, master, ui: UI, on_begin: Callable[[], None], on_change: Callable[[int, Tuple[float, float]], None],
                 bg=T.BG_PANEL):
        self.ui = ui
        self.radius = ui.px(46)
        self.gap = ui.px(14)
        width = 3 * 2 * self.radius + 2 * self.gap + ui.px(8)
        super().__init__(master, width=width, height=2 * self.radius + ui.px(42), bg=bg, highlightthickness=0, bd=0)
        self.on_begin, self.on_change = on_begin, on_change
        self.positions: List[Tuple[float, float]] = [(0.0, 0.0)] * 3
        rgba = color_wheel_rgba(self.radius, 170)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgba, "RGBA"))
        self._active = None
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_active", None))
        self.bind("<Double-Button-1>", self._reset_at)
        self.bind("<Button-3>", self._reset_at)
        Tooltip(self, ui, "Drag to tint · double-click to reset a wheel")

    def _centers(self):
        total = 3 * 2 * self.radius + 2 * self.gap
        left = (max(self.winfo_width(), total) - total) / 2 + self.radius
        cy = self.radius + self.ui.px(4)
        return [(left + i * (2 * self.radius + self.gap), cy) for i in range(3)]

    def draw(self):
        self.delete("all")
        for i, (cx, cy) in enumerate(self._centers()):
            r = self.radius
            self.create_image(cx - r, cy - r, image=self._photo, anchor="nw")
            self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=T.LINE_STRONG)
            self.create_line(cx - 4, cy, cx + 4, cy, fill="#2a2a2a")
            self.create_line(cx, cy - 4, cx, cy + 4, fill="#2a2a2a")
            px, py = self.positions[i]
            tx, ty = cx + px * r, cy + py * r
            changed = abs(px) + abs(py) > 1e-6
            if changed:
                self.create_line(cx, cy, tx, ty, fill=T.TEXT_HI)
            k = self.ui.px(5)
            self.create_oval(tx - k, ty - k, tx + k, ty + k, fill=T.TEXT_HI, outline="#000000", width=2)
            self.create_text(cx, cy + r + self.ui.px(12), text=self.LABELS[i], fill=T.TEXT if changed else T.TEXT_DIM,
                             font=self.ui.fonts.label)
            amt = int(round(math.hypot(px, py) * 100))
            self.create_text(cx, cy + r + self.ui.px(26), text=f"{amt}%" if changed else "—", fill=T.ACCENT if changed else T.TEXT_FAINT,
                             font=self.ui.fonts.micro)

    def _hit(self, x, y):
        for i, (cx, cy) in enumerate(self._centers()):
            if math.hypot(x - cx, y - cy) <= self.radius + self.ui.px(8):
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

    def __init__(self, master, ui: UI, on_begin: Callable[[], None], on_change: Callable[[List[Tuple[float, float]]], None],
                 bg=T.BG_PANEL):
        self.ui = ui
        size = ui.px(260)
        super().__init__(master, width=size, height=size, bg=T.BG_VIEW, highlightthickness=1,
                         highlightbackground=T.LINE, bd=0, cursor="crosshair")
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
        Tooltip(self, ui, "Click to add a point · drag to shape · double-click a point to remove")

    # coordinate helpers
    def _geom(self):
        w, h = max(self.winfo_width(), 20), max(self.winfo_height(), 20)
        pad = self.ui.px(8)
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
            self.create_polygon(pts, fill="#161616", outline="")
        for i in range(1, 4):
            self.create_line(pad + w * i / 4, pad, pad + w * i / 4, pad + h, fill=T.LINE)
            self.create_line(pad, pad + h * i / 4, pad + w, pad + h * i / 4, fill=T.LINE)
        self.create_line(pad, pad + h, pad + w, pad, fill=T.LINE_STRONG, dash=(2, 3))
        lut = compute_spline_lut(self.points)
        coords = []
        steps = 64
        for i in range(steps + 1):
            x = i * 255 / steps
            coords += list(self._to_screen((x, float(lut[int(round(x))]))))
        self.create_line(*coords, fill=T.TEXT_HI, width=max(1, self.ui.px(1.5)), smooth=True)
        r = self.ui.px(4)
        for i, p in enumerate(self.points):
            sx, sy = self._to_screen(p)
            fill = T.ACCENT if i == self._drag_idx else T.BG_VIEW
            self.create_rectangle(sx - r, sy - r, sx + r, sy + r, fill=fill, outline=T.TEXT_HI)

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
            lo = self.points[i - 1][0] + 4
            hi = self.points[i + 1][0] - 4
            vx = max(lo, min(hi, vx))
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
