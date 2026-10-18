"""Design tokens taken from the LATENT Illustrator files (1920x1080 artboards).

Layout (shared by all three screens):
    viewport frame  x 20..1260, y 20..1060
    scrollbar slot  x 1280..1300, full height (no arrows, 5-line grip)
    control column  x 1320..1900
    rows            top box 20..210 | command bar 230..270 | content 290..1060

Type: Courier New at 22.68px for readouts, buttons and values, and at
11.34px for slider and wheel captions. Myriad Pro 12px for file names and
22.68px for the grid numbers.
Colour: black ground, #58595b for every line and label, #fff200 for
selection, the active section and the SAVE menu marker.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

BG = "#000000"
BG_VIEW = BG
BG_PANEL = BG

LINE = "#58595b"          # every 0.85px stroke in the artboards
TEXT = "#58595b"
THUMB_LINE = "#6d6e71"    # slider thumb outline
THUMB_FILL = "#939598"    # slider grip / hovered thumb
GRIP = "#414042"
HOVER = "#a7a9ac"
TEXT_HI = "#d1d3d4"       # a value away from its default
YELLOW = "#fff200"
SELECT = YELLOW
SAVE = YELLOW
G35 = HOVER
G10 = "#e6e7e8"
WHITE = "#ffffff"
BG_BUTTON = BG
BG_BUTTON_PRESS = "#141414"

SCROLL_TROUGH = "#a7a9ac"
SCROLL_THUMB = "#e6e7e8"
SCROLL_EDGE = "#939598"
SCROLL_GRIP = "#a7a9ac"

DESIGN_W, DESIGN_H = 1920.0, 1080.0
GUTTER = 20
TOP_BOX_H = 190           # y 20..210
BAR_H = 40                # y 230..270
CELL_INSET = 5            # explorer cells sit 5px inside the frame
CELL_GAP = 7


class Fonts:
    """Pixel-sized fonts (negative Tk sizes) matching the artboards."""

    def __init__(self, root: tk.Misc, scale: float = 1.0):
        families = {f.lower(): f for f in tkfont.families(root)}

        def pick(*names):
            for n in names:
                if n.lower() in families:
                    return families[n.lower()]
            return names[0]

        self.mono_family = pick("Courier New", "Courier", "FreeMono", "Courier 10 Pitch", "Liberation Mono")
        self.sans_family = pick("Myriad Pro", "Segoe UI", "Helvetica Neue", "Arial", "Liberation Sans", "DejaVu Sans")
        m, s = self.mono_family, self.sans_family

        def px(size):
            return -max(8, int(round(size * scale)))

        self.readout = (m, px(22.68))      # PATH: / FILTER: / values / buttons
        self.button = (m, px(22.68))
        self.value = (m, px(22.68))
        self.title = (m, px(22.68))
        self.label = (m, px(11.34))        # slider and wheel captions
        self.small = (m, px(11.34))
        self.cell = (s, px(12))            # DSCF00000
        self.number = (s, px(22.68))       # 01..15
        self.body = (m, px(11.34))


def style_ttk(root: tk.Misc) -> None:
    """Only used by a few native widgets (entries in dialogs)."""
    from tkinter import ttk
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
