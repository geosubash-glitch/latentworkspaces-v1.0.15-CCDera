"""Design tokens from the LATENT Illustrator layouts.

Grid (at 1920x1080): 20px gutters everywhere. A 1240px framed viewport
(20..1260), a 20px light scrollbar between viewport and controls
(1280..1300), and a 580px control column (1320..1900). Panel boxes align with
the viewport frame: the top box spans y 20..259 and the bottom box 279..1060.

Colour: pure black ground, Illustrator greys for every line and label, and a
single process yellow (#fff200) for selection, active state and SAVE.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# Ground
BG = "#000000"
BG_VIEW = BG
BG_PANEL = BG
BG_BUTTON = "#000000"
BG_BUTTON_PRESS = "#1a1a1a"

# Illustrator greys (K%)
G85 = "#434446"   # lines: frames, cells, boxes, slider troughs
G75 = "#58595b"   # text: readouts, captions, labels
G55 = "#808285"   # values at rest
G35 = "#a7a9ac"   # hover
G10 = "#e6e7e8"   # changed values, hover text
WHITE = "#ffffff"

LINE = G85
TEXT = G75
TEXT_HI = G10

YELLOW = "#fff200"    # selection, drag, SAVE
SELECT = YELLOW
SAVE = YELLOW

# Illustrator scrollbar
SCROLL_TROUGH = "#a7a9ac"
SCROLL_THUMB = "#e6e7e8"
SCROLL_EDGE = "#939598"
SCROLL_ARROW = "#58595b"

DESIGN_W, DESIGN_H = 1920.0, 1080.0
GUTTER = 20
TOP_BOX_H = 239       # y 20..259
CELL_INSET = 5
CELL_GAP = 7


class Fonts:
    """Courier New everywhere."""

    def __init__(self, root: tk.Misc, scale: float = 1.0):
        families = {f.lower(): f for f in tkfont.families(root)}
        family = "Courier New"
        for name in ("Courier New", "Courier", "FreeMono", "Courier 10 Pitch", "Liberation Mono"):
            if name.lower() in families:
                family = families[name.lower()]
                break
        self.family = family

        def f(size, *style):
            return (family, max(7, int(round(size * scale))), *style)

        self.cell = f(8)            # names inside thumbnail cells
        self.label = f(8)           # slider / section captions
        self.value = f(8)           # slider values
        self.button = f(10)         # BACK / SAVE / NAVIGATE
        self.title = f(11)          # profile name, dialog title
        self.readout = f(15)        # PATH: / FILE: / SIZE:


def style_ttk(root: tk.Misc) -> None:
    from tkinter import ttk
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure("TScrollbar", troughcolor=SCROLL_TROUGH, background=SCROLL_THUMB, bordercolor=SCROLL_EDGE,
                arrowcolor=SCROLL_ARROW, lightcolor=SCROLL_THUMB, darkcolor=SCROLL_THUMB)
    s.map("TScrollbar", background=[("active", "#ffffff"), ("pressed", "#d1d3d4")])
