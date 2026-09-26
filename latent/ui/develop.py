"""Stage 3 - Develop: the grading workbench."""
from __future__ import annotations

import os
import time
import tkinter as tk
from dataclasses import replace
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

import cv2
import numpy as np

from .. import theme as T
from ..imaging import io as imgio
from ..imaging import scopes
from ..imaging.filters import FILTER_REGISTRY
from ..imaging.pipeline import EditState, Geometry, apply_geometry, develop
from ..workers import Channel
from .base import View
from .widgets import Button, ColorWheels, ScrollPanel, Section, Segmented, Slider, ToneCurve, Tooltip, rgb_to_photo, bgr_to_photo

# (label, state attribute, display min, display max, neutral state value)
# Displayed value = state value - neutral, so every slider reads 0 at rest.
ADJUSTMENTS = [
    ("LIGHT", True, [("Exposure", "exposure", -50, 50, 100), ("Contrast", "contrast", -50, 50, 100),
                     ("Highlights", "highlights", -50, 50, 100), ("Shadows", "shadows", -50, 50, 100)]),
    ("COLOR", True, [("Temperature", "warmth", -50, 50, 0), ("Tint", "tint", -50, 50, 0),
                     ("Saturation", "saturation", -50, 50, 100)]),
]
EFFECTS = ("DETAIL & EFFECTS", True, [("Sharpening", "sharpness", 0, 5, 0), ("Vignette", "vignette", -100, 100, 0)])
CALIBRATION = ("CALIBRATION", False, [("Red primary", "cal_red", -100, 100, 0), ("Green primary", "cal_green", -100, 100, 0),
                                      ("Blue primary", "cal_blue", -100, 100, 0)])
ADJUSTABLE_ATTRS = [a for _, _, rows in ADJUSTMENTS + [EFFECTS, CALIBRATION] for (_, a, _, _, _) in rows]


class DevelopView(View):
    def __init__(self, app):
        super().__init__(app)
        ui = self.ui
        self.render_channel = Channel(app.dispatcher, "develop")
        self.export_channel = Channel(app.dispatcher, "export")
        self.rendered: Optional[np.ndarray] = None
        self.before: Optional[np.ndarray] = None
        self._photo = None
        self._scope_photo = None
        self.scope_mode = app.settings.get("scope_mode", "histogram")
        self.zoom = 1.0
        self.center: Optional[List[float]] = None
        self.compare = False
        self._compare_release_after = None
        self._pan_start = None
        self._geo_cache = None  # (proxy id, geometry, image) used only on the worker thread
        self.sliders: Dict[str, Slider] = {}
        self.profile_sliders: Dict[str, Slider] = {}
        self._built_profile = None
        self._render_pending = False

        self._build_viewport()
        self._build_panel()

    # =================================================================== UI
    def _build_viewport(self):
        ui = self.ui
        self.canvas = tk.Canvas(self.viewport, bg=T.BG_VIEW, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._pan_begin)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._pan_end)
        self.canvas.bind("<Double-Button-1>", self._toggle_zoom_at)
        self.app.router.register(self.canvas, self._wheel_zoom)

        tk.Frame(self.viewport, bg=T.LINE, height=1).pack(fill="x")
        bar = tk.Frame(self.viewport, bg=T.BG_VIEW)
        bar.pack(fill="x", ipady=ui.px(3))
        f = ui.fonts.label
        Button(bar, ui, "FIT", command=self.zoom_fit, style="toolbar", font=f, padx=10, pady=4,
               tooltip="Fit to screen (Ctrl+0)").pack(side="left", padx=(ui.px(10), 0))
        Button(bar, ui, "−", command=lambda: self.zoom_step(1 / 1.25), style="toolbar", font=f, padx=8, pady=4, tooltip="Zoom out").pack(side="left")
        self.zoom_lbl = tk.Label(bar, text="×1.0", bg=T.BG_VIEW, fg=T.TEXT, font=ui.fonts.mono, width=6)
        self.zoom_lbl.pack(side="left")
        Button(bar, ui, "+", command=lambda: self.zoom_step(1.25), style="toolbar", font=f, padx=8, pady=4, tooltip="Zoom in").pack(side="left")
        tk.Frame(bar, bg=T.LINE, width=1).pack(side="left", fill="y", padx=ui.px(10), pady=ui.px(6))
        self.compare_btn = Button(bar, ui, "◧  BEFORE / AFTER", style="toolbar", font=f, padx=10, pady=4,
                                  tooltip="Hold to see the original (Space)")
        self.compare_btn.pack(side="left")
        self.compare_btn.bind("<ButtonPress-1>", lambda e: self.set_compare(True), add="+")
        self.compare_btn.bind("<ButtonRelease-1>", lambda e: self.set_compare(False), add="+")
        Button(bar, ui, "⟲  CROP & ROTATE", command=self.open_geometry, style="toolbar", font=f, padx=10, pady=4,
               tooltip="Crop, straighten, perspective and resize (C)").pack(side="left", padx=(ui.px(4), 0))
        self.size_lbl = tk.Label(bar, text="", bg=T.BG_VIEW, fg=T.TEXT_FAINT, font=ui.fonts.micro)
        self.size_lbl.pack(side="right", padx=ui.px(12))

    def _build_panel(self):
        ui = self.ui
        top = tk.Frame(self.panel, bg=T.BG_PANEL)
        top.pack(fill="x", padx=ui.px(20), pady=(ui.px(18), 0))

        row = tk.Frame(top, bg=T.BG_PANEL)
        row.pack(fill="x")
        Button(row, ui, "← LOOK", command=lambda: self.app.go("looks"), padx=10, pady=6,
               tooltip="Choose a different film look (Esc)").pack(side="left")
        self.export_btn = Button(row, ui, "EXPORT", command=self.export, style="primary", padx=18, pady=6,
                                 tooltip="Export full resolution (Ctrl+E)")
        self.export_btn.pack(side="right")
        self.redo_btn = Button(row, ui, "REDO", command=self.app.redo, style="ghost", font=ui.fonts.label, padx=8, pady=6, tooltip="Redo (Ctrl+Y)")
        self.redo_btn.pack(side="right", padx=(0, ui.px(8)))
        self.undo_btn = Button(row, ui, "UNDO", command=self.app.undo, style="ghost", font=ui.fonts.label, padx=8, pady=6, tooltip="Undo (Ctrl+Z)")
        self.undo_btn.pack(side="right")

        self.title_lbl = tk.Label(top, text="", bg=T.BG_PANEL, fg=T.TEXT_HI, font=ui.fonts.title, anchor="w")
        self.title_lbl.pack(fill="x", pady=(ui.px(16), 0))
        self.file_lbl = tk.Label(top, text="", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro, anchor="w")
        self.file_lbl.pack(fill="x", pady=(ui.px(2), ui.px(12)))

        self.scope = tk.Canvas(top, height=ui.px(116), bg=T.BG_VIEW, highlightthickness=1, highlightbackground=T.LINE, bd=0)
        self.scope.pack(fill="x")
        self.scope.bind("<Configure>", lambda e: self.request_render())
        srow = tk.Frame(top, bg=T.BG_PANEL)
        srow.pack(fill="x", pady=(ui.px(6), ui.px(4)))
        Segmented(srow, ui, [("histogram", "HISTOGRAM"), ("waveform", "WAVEFORM")], self.scope_mode, self._set_scope_mode).pack(side="left")
        reset = tk.Label(srow, text="RESET ALL", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro, cursor="hand2")
        reset.pack(side="right")
        reset.bind("<Enter>", lambda e: reset.config(fg=T.ACCENT))
        reset.bind("<Leave>", lambda e: reset.config(fg=T.TEXT_FAINT))
        reset.bind("<Button-1>", lambda e: self.reset_all())
        Tooltip(reset, ui, "Reset every adjustment, keep the look and crop")

        tk.Frame(self.panel, bg=T.LINE, height=1).pack(fill="x", pady=(ui.px(6), 0))
        self.scroll = ScrollPanel(self.panel, ui, self.app.router)
        self.scroll.pack(fill="both", expand=True, padx=(ui.px(20), ui.px(8)), pady=(0, ui.px(8)))
        body = self.scroll.inner

        self.look_section = Section(body, ui, "Look", on_reset=self._reset_profile)
        self.look_section.pack(fill="x", padx=(0, ui.px(8)))

        for title, open_, rows in ADJUSTMENTS:
            self._slider_section(body, title, open_, rows)

        sec = Section(body, ui, "Tone curve", on_reset=self._reset_curve)
        sec.pack(fill="x", padx=(0, ui.px(8)))
        self.curve = ToneCurve(sec.body, ui, on_begin=self.app.push_undo, on_change=self._on_curve)
        self.curve.pack(anchor="center", pady=(0, ui.px(4)))

        sec = Section(body, ui, "Color grading", on_reset=self._reset_wheels)
        sec.pack(fill="x", padx=(0, ui.px(8)))
        self.wheels = ColorWheels(sec.body, ui, on_begin=self.app.push_undo, on_change=self._on_wheel)
        self.wheels.pack(anchor="center")

        self._slider_section(body, *EFFECTS)
        self._slider_section(body, *CALIBRATION)
        tk.Frame(body, bg=T.BG_PANEL, height=ui.px(24)).pack(fill="x")

    def _slider_section(self, parent, title, open_, rows):
        attrs = [r[1] for r in rows]
        sec = Section(parent, self.ui, title, on_reset=lambda: self._reset_attrs(attrs), open_=open_)
        sec.pack(fill="x", padx=(0, self.ui.px(8)))
        for label, attr, lo, hi, neutral in rows:
            kind = "float" if attr == "sharpness" else "int"
            s = Slider(sec.body, self.ui, label, lo, hi, 0.0, kind=kind, decimals=1 if kind == "float" else 0,
                       on_begin=self.app.push_undo,
                       on_change=lambda v, a=attr, n=neutral: self._set_attr(a, v + n))
            s.pack(fill="x", pady=(0, self.ui.px(8)))
            s.neutral = neutral
            self.sliders[attr] = s

    def _build_profile_controls(self):
        state = self.app.session.state
        key = state.profile
        body = self.look_section.body
        for w in body.winfo_children():
            w.destroy()
        self.profile_sliders.clear()
        prof = FILTER_REGISTRY[key]
        self.look_section.title.config(text=f"LOOK  ·  {prof.name.upper()}")
        values = state.params_for(key)
        for c in prof.controls:
            s = Slider(body, self.ui, c.label, c.minimum, c.maximum, c.default, value=values[c.label], kind=c.kind,
                       on_begin=self.app.push_undo, on_change=lambda v, lbl=c.label: self._set_profile_param(lbl, v))
            s.pack(fill="x", pady=(0, self.ui.px(8)))
            self.profile_sliders[c.label] = s
        self._built_profile = key

    # ============================================================ state glue
    @property
    def state(self) -> EditState:
        return self.app.session.state

    def _set_attr(self, attr, value):
        setattr(self.state, attr, float(value))
        self.request_render()

    def _set_profile_param(self, label, value):
        self.state.profile_params.setdefault(self.state.profile, {})[label] = float(value)
        self.request_render()

    def _on_curve(self, points):
        self.state.curve = [tuple(p) for p in points]
        self.request_render()

    def _on_wheel(self, idx, pos):
        attr = ("wheel_shadows", "wheel_midtones", "wheel_highlights")[idx]
        setattr(self.state, attr, tuple(pos))
        self.request_render()

    def _reset_attrs(self, attrs):
        default = EditState()
        if all(getattr(self.state, a) == getattr(default, a) for a in attrs):
            return
        self.app.push_undo()
        for a in attrs:
            setattr(self.state, a, getattr(default, a))
        self.sync_from_state()

    def _reset_profile(self):
        if not self.state.profile_params.get(self.state.profile):
            return
        self.app.push_undo()
        self.state.profile_params.pop(self.state.profile, None)
        self.sync_from_state()

    def _reset_curve(self):
        self._reset_attrs(["curve"])

    def _reset_wheels(self):
        self._reset_attrs(["wheel_shadows", "wheel_midtones", "wheel_highlights"])

    def reset_all(self):
        default = EditState()
        s = self.state
        if s.curve == default.curve and not s.profile_params.get(s.profile) and all(
                getattr(s, a) == getattr(default, a) for a in ADJUSTABLE_ATTRS + ["wheel_shadows", "wheel_midtones", "wheel_highlights"]):
            return
        self.app.push_undo()
        fresh = EditState(profile=s.profile, geometry=s.geometry)
        self.app.session.state = fresh
        self.sync_from_state()
        self.app.toast("All adjustments reset")

    def sync_from_state(self):
        """Push the session state into every control (after undo/reset/open)."""
        s = self.state
        if self._built_profile != s.profile:
            self._build_profile_controls()
        else:
            values = s.params_for()
            for label, slider in self.profile_sliders.items():
                slider.set(values[label])
        for attr, slider in self.sliders.items():
            slider.set(getattr(s, attr) - slider.neutral)
        self.curve.set_points(s.curve)
        self.wheels.set_positions([s.wheel_shadows, s.wheel_midtones, s.wheel_highlights])
        self._update_header()
        self.request_render()

    def _update_header(self):
        prof = FILTER_REGISTRY[self.state.profile]
        self.title_lbl.config(text=prof.name.upper())
        path = self.app.session.path or ""
        self.file_lbl.config(text=os.path.basename(path).upper())
        self.undo_btn.set_enabled(bool(self.app.session.undo))
        self.redo_btn.set_enabled(bool(self.app.session.redo))
        self._update_size_label()

    def _update_size_label(self):
        img = self.app.session.image
        if img is None:
            self.size_lbl.config(text="")
            return
        h, w = img.shape[:2]
        ow, oh = self._output_size()
        text = f"{w} × {h} px" if (ow, oh) == (w, h) else f"{w} × {h}  →  {ow} × {oh} px"
        self.size_lbl.config(text=text)

    def _output_size(self):
        img = self.app.session.image
        g = self.state.geometry
        h, w = img.shape[:2]
        if g.quarter_turns % 2:
            w, h = h, w
        if g.resize_w and g.resize_h:
            return int(g.resize_w), int(g.resize_h)
        cw = max(2, int(round(w * (g.crop_r - g.crop_l) / 100.0)))
        ch = max(2, int(round(h * (g.crop_b - g.crop_t) / 100.0)))
        return cw, ch

    # ============================================================= rendering
    def request_render(self):
        session = self.app.session
        if not self.visible or not session.loaded:
            return
        self.undo_btn.set_enabled(bool(session.undo))
        self.redo_btn.set_enabled(bool(session.redo))
        state = session.state.copy()
        proxy = session.proxy
        full_edge = max(session.image.shape[:2])
        scope_mode = self.scope_mode
        sw, sh = max(self.scope.winfo_width() - 2, 64), max(self.scope.winfo_height() - 2, 40)

        def job(_token):
            key = (id(proxy), repr(state.geometry))
            if self._geo_cache and self._geo_cache[0] == key:
                base = self._geo_cache[1]
            else:
                scale = max(proxy.shape[:2]) / float(full_edge)
                base = apply_geometry(proxy, state.geometry, output_scale=scale)
                self._geo_cache = (key, base)
            out = develop(base, state)
            scope = scopes.histogram(out, sw, sh) if scope_mode == "histogram" else scopes.waveform(out, sw, sh)
            luma = cv2.calcHist([cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)], [0], None, [256], [0, 256]).ravel()
            return base, out, scope, luma

        self.render_channel.submit(job, self._render_done, self._render_failed)

    def _render_done(self, result):
        base, out, scope_rgb, luma = result
        if not self.visible:
            return
        self.before, self.rendered = base, out
        self._redraw()
        self._scope_photo = rgb_to_photo(scope_rgb)
        self.scope.delete("all")
        self.scope.create_image(1, 1, image=self._scope_photo, anchor="nw")
        self.curve.set_histogram(np.sqrt(luma))

    def _render_failed(self, exc):
        self.app.toast(f"Render error: {exc}")

    def _set_scope_mode(self, mode):
        self.scope_mode = mode
        self.app.settings.set("scope_mode", mode)
        self.request_render()

    # ------------------------------------------------------------ viewport
    def _display_image(self):
        return self.before if self.compare else self.rendered

    def _fit_scale(self, img):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        pad = self.ui.px(24)
        h, w = img.shape[:2]
        return min((cw - 2 * pad) / w, (ch - 2 * pad) / h)

    def _max_zoom(self, img):
        return max(1.0, 4.0 / max(self._fit_scale(img), 1e-3))

    def _redraw(self):
        img = self._display_image()
        c = self.canvas
        c.delete("all")
        cw, ch = c.winfo_width(), c.winfo_height()
        if img is None or cw < 10 or ch < 10:
            return
        h, w = img.shape[:2]
        self.zoom = min(self.zoom, self._max_zoom(img))
        s = self._fit_scale(img) * self.zoom
        if self.center is None:
            self.center = [w / 2.0, h / 2.0]
        half_w, half_h = cw / (2 * s), ch / (2 * s)
        cx = w / 2.0 if w * s <= cw else min(max(self.center[0], half_w), w - half_w)
        cy = h / 2.0 if h * s <= ch else min(max(self.center[1], half_h), h - half_h)
        self.center = [cx, cy]
        x0, x1 = max(0, int(cx - half_w)), min(w, int(np.ceil(cx + half_w)))
        y0, y1 = max(0, int(cy - half_h)), min(h, int(np.ceil(cy + half_h)))
        crop = img[y0:y1, x0:x1]
        tw, th = max(1, int(round((x1 - x0) * s))), max(1, int(round((y1 - y0) * s)))
        interp = cv2.INTER_AREA if s < 1 else (cv2.INTER_NEAREST if s >= 3 else cv2.INTER_LINEAR)
        disp = cv2.resize(crop, (tw, th), interpolation=interp)
        self._photo = bgr_to_photo(disp)
        dx = cw / 2 - (cx - x0) * s
        dy = ch / 2 - (cy - y0) * s
        c.create_image(int(dx), int(dy), image=self._photo, anchor="nw")
        if self.compare:
            pad = self.ui.px(14)
            c.create_rectangle(pad, pad, pad + self.ui.px(78), pad + self.ui.px(24), fill=T.ACCENT, outline="")
            c.create_text(pad + self.ui.px(39), pad + self.ui.px(12), text="BEFORE", fill=T.ON_ACCENT, font=self.ui.fonts.label)
        self.zoom_lbl.config(text=f"×{self.zoom:.1f}", fg=T.TEXT_DIM if abs(self.zoom - 1.0) < 1e-3 else T.ACCENT)
        zoomed = w * s > cw + 1 or h * s > ch + 1
        c.config(cursor="fleur" if zoomed else "")

    def _zoom_to(self, zoom, anchor=None):
        img = self._display_image()
        if img is None:
            return
        zoom = max(1.0, min(self._max_zoom(img), zoom))
        if anchor is not None and self.center is not None:
            # keep the image point under the cursor fixed
            ax, ay = anchor
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            s_old = self._fit_scale(img) * self.zoom
            s_new = self._fit_scale(img) * zoom
            ix = self.center[0] + (ax - cw / 2) / s_old
            iy = self.center[1] + (ay - ch / 2) / s_old
            self.center = [ix - (ax - cw / 2) / s_new, iy - (ay - ch / 2) / s_new]
        self.zoom = zoom
        if zoom == 1.0:
            self.center = None
        self._redraw()

    def zoom_step(self, factor):
        self._zoom_to(self.zoom * factor)

    def zoom_fit(self):
        self.center = None
        self._zoom_to(1.0)

    def _wheel_zoom(self, notches, e):
        self._zoom_to(self.zoom * (1.15 ** notches), anchor=(e.x_root - self.canvas.winfo_rootx(), e.y_root - self.canvas.winfo_rooty()))

    def _toggle_zoom_at(self, e):
        if self.zoom > 1.01:
            self.zoom_fit()
        else:
            self._zoom_to(2.5, anchor=(e.x, e.y))

    def _pan_begin(self, e):
        self.canvas.focus_set()
        self._pan_start = (e.x, e.y, list(self.center) if self.center else None)

    def _pan_move(self, e):
        img = self._display_image()
        if not self._pan_start or img is None or self._pan_start[2] is None:
            return
        s = self._fit_scale(img) * self.zoom
        x, y, c0 = self._pan_start
        self.center = [c0[0] - (e.x - x) / s, c0[1] - (e.y - y) / s]
        self._redraw()

    def _pan_end(self, _e):
        self._pan_start = None

    def set_compare(self, on: bool):
        if self._compare_release_after:
            self.canvas.after_cancel(self._compare_release_after)
            self._compare_release_after = None
        if on != self.compare:
            self.compare = on
            self.compare_btn.set_active(on)
            self._redraw()

    def _compare_key_released(self):
        # X11 auto-repeat sends release/press pairs; wait briefly before ending.
        if self._compare_release_after:
            self.canvas.after_cancel(self._compare_release_after)
        self._compare_release_after = self.canvas.after(70, lambda: self.set_compare(False))

    # ============================================================= geometry
    def open_geometry(self):
        from .geometry import GeometryDialog
        session = self.app.session
        if not session.loaded:
            return

        def apply(geo: Geometry):
            if geo == self.state.geometry:
                return
            self.app.push_undo()
            self.state.geometry = geo
            self.zoom_fit()
            self._update_size_label()
            self.request_render()

        GeometryDialog(self.app, session.proxy, session.image.shape[1], session.image.shape[0], self.state.geometry, apply)

    # =============================================================== export
    def export(self):
        session = self.app.session
        if not session.loaded:
            return
        prof = FILTER_REGISTRY[self.state.profile]
        stem = os.path.splitext(os.path.basename(session.path))[0]
        suggested = f"{stem}_{prof.name.replace(' ', '-').replace('&', 'and')}.jpg"
        path = filedialog.asksaveasfilename(
            parent=self.app.root, title="Export photo", initialdir=os.path.dirname(session.path),
            initialfile=suggested, defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg *.jpeg"), ("PNG", "*.png"), ("TIFF", "*.tif *.tiff")])
        if not path:
            return
        if os.path.splitext(path)[1].lower() not in imgio.EXPORT_FORMATS:
            path += ".jpg"
        state = self.state.copy()
        image, exif = session.image, session.exif
        overlay = ExportOverlay(self.app, os.path.basename(path))
        self.export_btn.set_enabled(False)
        started = time.time()

        def job(_t):
            out = develop(apply_geometry(image, state.geometry), state)
            imgio.save_image(path, out, exif)
            return out.shape

        def done(shape):
            overlay.close()
            self.export_btn.set_enabled(True)
            secs = time.time() - started
            self.app.toast(f"Exported {os.path.basename(path)}  ·  {shape[1]}×{shape[0]} px  ·  {secs:.1f}s",
                           action=("Show in folder", lambda: self.app.reveal(path)), ms=12000)
            if os.path.dirname(os.path.abspath(path)) == os.path.abspath(self.app.folder):
                self.app.views["library"].load_folder()

        def failed(exc):
            overlay.close()
            self.export_btn.set_enabled(True)
            messagebox.showerror("Export failed", f"The photo could not be saved.\n\n{exc}", parent=self.app.root)

        self.export_channel.submit(job, done, failed)

    # ================================================================ hooks
    def on_photo_changed(self):
        self._geo_cache = None
        self.rendered = self.before = None
        self.zoom, self.center = 1.0, None
        self._built_profile = None

    def on_show(self):
        first_time = self._built_profile is None
        self.sync_from_state()
        if first_time:
            self.scroll.to_top()
        self.canvas.focus_set()

    def on_hide(self):
        self.set_compare(False)

    def refresh_status(self):
        if not self.visible:
            return
        from ..app import MOD_LABEL
        path = self.app.session.path or ""
        self.app.set_status(f"{os.path.basename(path)}  ·  {FILTER_REGISTRY[self.state.profile].name}",
                            f"Hold Space: before/after  ·  Wheel: zoom  ·  C: crop  ·  {MOD_LABEL}E: export")

    def on_key(self, seq, e):
        if seq in ("<KeyPress-space>", "<KeyPress-backslash>"):
            self.set_compare(True)
        elif seq in ("<KeyRelease-space>", "<KeyRelease-backslash>"):
            self._compare_key_released()
        elif seq.endswith("-e>"):
            self.export()
        elif seq.endswith("-0>"):
            self.zoom_fit()
        elif seq.endswith("-equal>") or seq.endswith("-plus>"):
            self.zoom_step(1.25)
        elif seq.endswith("-minus>"):
            self.zoom_step(1 / 1.25)
        elif seq == "<KeyPress-c>":
            self.open_geometry()
        elif seq == "<BackSpace>":
            self.app.go("looks")


class ExportOverlay:
    """Small modal progress window while a full-resolution export runs."""

    def __init__(self, app, name: str):
        ui = app.ui
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.configure(bg=T.LINE_STRONG)
        body = tk.Frame(self.win, bg=T.BG_PANEL)
        body.pack(padx=1, pady=1)
        inner = tk.Frame(body, bg=T.BG_PANEL)
        inner.pack(padx=ui.px(28), pady=ui.px(22))
        tk.Label(inner, text="EXPORTING", bg=T.BG_PANEL, fg=T.ACCENT, font=ui.fonts.label).pack(anchor="w")
        tk.Label(inner, text=name, bg=T.BG_PANEL, fg=T.TEXT_HI, font=ui.fonts.mono_bold).pack(anchor="w", pady=(ui.px(4), ui.px(12)))
        self.bar = tk.Canvas(inner, width=ui.px(320), height=ui.px(4), bg=T.LINE, highlightthickness=0)
        self.bar.pack()
        tk.Label(inner, text="Developing at full resolution…", bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.body_small).pack(anchor="w", pady=(ui.px(10), 0))
        self._t = 0
        self._alive = True
        app._center(self.win)
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self._animate()

    def _animate(self):
        if not self._alive:
            return
        w = int(self.bar.cget("width"))
        seg = w // 4
        x = (self._t * 6) % (w + seg) - seg
        self.bar.delete("all")
        self.bar.create_rectangle(x, 0, x + seg, int(self.bar.cget("height")), fill=T.ACCENT, outline="")
        self._t += 1
        self.win.after(16, self._animate)

    def close(self):
        self._alive = False
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
