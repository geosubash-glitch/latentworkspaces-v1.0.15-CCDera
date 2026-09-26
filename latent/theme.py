"""Design tokens: colour, type and spacing.

Palette is taken from the original Illustrator layouts (#020202 viewport,
#080808 panels, #58595b rules, #939598 / #e6e7e8 greys).  The two slightly
different accent yellows used in v1 (#fff200 and #ffcc00) are unified into
one accent.
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont

# Surfaces
BG_VIEW = "#020202"
BG_PANEL = "#080808"
BG_RAISED = "#101010"
BG_INPUT = "#151515"
BG_HOVER = "#1c1c1c"

# Lines
LINE = "#1f1f1f"
LINE_STRONG = "#3a3b3c"
LINE_FOCUS = "#58595b"

# Text
TEXT_FAINT = "#56575a"
TEXT_DIM = "#8a8b8e"
TEXT = "#c4c5c8"
TEXT_HI = "#f0f0f0"

# Accent & status
ACCENT = "#ffcc00"
ACCENT_HOVER = "#ffd940"
ACCENT_DIM = "#6b5600"
ON_ACCENT = "#080808"
DANGER = "#ff5a4f"
OK = "#5fd38d"

ACCENT_BGR = (0, 204, 255)


class Fonts:
    """Resolved font tuples; created once a Tk root exists."""

    mono_family = "Courier New"
    sans_family = "Helvetica"

    def __init__(self, root: tk.Misc):
        families = {f.lower(): f for f in tkfont.families(root)}

        def pick(*names):
            for n in names:
                if n.lower() in families:
                    return families[n.lower()]
            return names[-1]

        self.mono_family = pick("Cascadia Mono", "Consolas", "SF Mono", "Menlo", "JetBrains Mono",
                                "DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier")
        self.sans_family = pick("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Cantarell",
                                "DejaVu Sans", "Liberation Sans", "Arial", "Helvetica")
        base = 9 if sys.platform.startswith("win") else (12 if sys.platform == "darwin" else 9)
        self.base = base

        m, s = self.mono_family, self.sans_family
        self.micro = (m, base - 1)
        self.label = (m, base - 1, "bold")
        self.value = (m, base)
        self.mono = (m, base)
        self.mono_bold = (m, base, "bold")
        self.body = (s, base)
        self.body_small = (s, base - 1)
        self.title = (m, base + 3, "bold")
        self.display = (m, base + 7, "bold")
        self.brand = (m, base + 2, "bold")


def ui_scale(root: tk.Misc) -> float:
    """Pixel scale relative to a 96-dpi display."""
    try:
        dpi = root.winfo_fpixels("1i")
    except tk.TclError:
        dpi = 96.0
    return max(1.0, min(3.0, dpi / 96.0))
