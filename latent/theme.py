"""Design tokens taken from the original LATENT Illustrator layouts.

Everything here was measured from the v1 interface: the 1920x1080 grid
(20px outer margin, 1240px viewport, 620px control column with 580px content),
the near-black surfaces, light 1px outlined buttons, bracketed section titles,
light-grey scrollbars and Courier New throughout.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# Surfaces
BG_VIEW = "#020202"      # viewport / root
BG_PANEL = "#080808"     # control column
BG_WELL = "#050505"      # inset canvases (wheels, curve)
BG_BUTTON = "#121212"
BG_BUTTON_ACTIVE = "#333333"

# Lines
BOX = "#1c1c1c"          # info boxes, section frames
SCOPE_LINE = "#222222"
CELL = "#58595a"         # thumbnail cell borders
BUTTON_LINE = "#d9d9d9"  # 1px outline of buttons

# Text
TEXT_LABEL = "#555555"   # slider / section captions
TEXT_CELL = "#6e6e6e"    # thumbnail captions
TEXT = "#888888"         # readouts, button text
TEXT_READ = "#aaaaaa"    # active readout
TEXT_HI = "#ffffff"

# Accents (two yellows, as in the original)
SELECT = "#ffcc00"       # selection frames, apply
SAVE = "#fff200"         # the SAVE command

# Illustrator scrollbar
SCROLL_TROUGH = "#a7a9ac"
SCROLL_THUMB = "#e6e7e8"
SCROLL_EDGE = "#939598"
SCROLL_ARROW = "#58595b"

SELECT_BGR = (0, 204, 255)

DESIGN_W, DESIGN_H = 1920.0, 1080.0


class Fonts:
    """Courier New everywhere, sized like the v1 layout."""

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

        self.cell = f(7)
        self.label = f(8, "bold")
        self.value = f(8)
        self.readout = f(10)
        self.button = f(11, "bold")
        self.button_small = f(9, "bold")
        self.title = f(12, "bold")
        self.body = f(9)


def style_ttk(root: tk.Misc) -> None:
    """Scrollbars and the combobox, styled like the Illustrator SVGs."""
    from tkinter import ttk
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure("TScrollbar", troughcolor=SCROLL_TROUGH, background=SCROLL_THUMB, bordercolor=SCROLL_EDGE,
                arrowcolor=SCROLL_ARROW, lightcolor=SCROLL_THUMB, darkcolor=SCROLL_THUMB, gripcount=0)
    s.map("TScrollbar", background=[("active", "#ffffff"), ("pressed", "#c0c0c0")])
