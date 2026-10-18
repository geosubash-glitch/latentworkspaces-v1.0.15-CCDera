"""Stage 3 - Workbench: grading, scopes and export."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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
from .widgets import Box, Button, ColorWheels, ScrollPanel, Slider, ToneCurve, bgr_to_photo, rgb_to_photo

# (label, state attribute, display min, display max, neutral state value).
# Displayed value = state value - neutral, so every slider reads 0 at rest.
CALIBRATION = [("Red Primary Saturation", "cal_red", -100, 100, 0),
               ("Green Primary Saturation", "cal_green", -100, 100, 0),
               ("Blue Primary Saturation", "cal_blue", -100, 100, 0)]
ADJUSTMENTS = [("Exposure", "exposure", -50, 50, 100), ("Contrast", "contrast", -50, 50, 100),
               ("Saturation", "saturation", -50, 50, 100), ("Temperature", "warmth", -50, 50, 0),
               ("Tint", "tint", -50, 50, 0), ("Highlights", "highlights", -50, 50, 100),
               ("Shadows", "shadows", -50, 50, 100), ("Sharpness", "sharpness", 0, 5, 0),
               ("Vignette", "vignette", -100, 100, 0)]
SCOPE_CAPTION = {"histogram": "[ SCOPE MODE: HISTOGRAM // CLICK TO TOGGLE ]",
                 "waveform": "[ SCOPE MODE: LUMA WAVEFORM // CLICK TO TOGGLE ]"}


class DevelopView(View):
    def __init__(self, app):
        super().__init__(app)
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
        self._geo_cache = None  # used only on the worker thread
        self.sliders: Dict[str, Slider] = {}
        self.profile_sliders: Dict[str, Slider] = {}
        self._built_profile = None
        self._exporting = False

        self._build_viewport()
        self._build_panel()

    # =================================================================== UI
    def _build_viewport(self):
        ui = self.ui
        sb = ui.px(20)
        self.vbar = ttk.Scrollbar(self.viewport, orient="vertical", command=lambda *a: self._scrollbar("y", *a))
        self.hbar = ttk.Scrollbar(self.viewport, orient="horizontal", command=lambda *a: self._scrollbar("x", *a))
        self.canvas = tk.Canvas(self.viewport, bg=T.BG_VIEW, highlightthickness=0, bd=0)
        self.viewport.grid_columnconfigure(1, weight=1)
        self.viewport.grid_rowconfigure(0, weight=1)
        self.vbar.grid(row=0, column=0, sticky="ns")
        self.canvas.grid(row=0, column=1, sticky="nsew")
        self.hbar.grid(row=1, column=1, sticky="ew")
        tk.Frame(self.viewport, bg=T.SCROLL_EDGE, width=sb, height=sb).grid(row=1, column=0)
        self.compare_btn = Button(self.viewport, ui, "◧", font=ui.fonts.value, padx=ui.px(4), pady=0, outline=T.BG_VIEW)
        self.compare_btn.place(relx=1.0, rely=1.0, x=-1, y=-sb - 1, anchor="se")
        self.compare_btn.bind("<ButtonPress-1>", lambda e: self.set_compare(True), add="+")
        self.compare_btn.bind("<ButtonRelease-1>", lambda e: self.set_compare(False), add="+")

        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._pan_begin)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_pan_start", None))
        self.canvas.bind("<Double-Button-1>", self._toggle_zoom_at)
        self.app.router.register(self.canvas, self._wheel_zoom)

    def _build_panel(self):
        ui = self.ui
        top = tk.Frame(self.panel, bg=T.BG_PANEL)
        top.pack(fill="x", padx=ui.px(20), pady=(ui.px(20), 0))
        self.scope = tk.Canvas(top, height=ui.px(196), bg=T.BG_PANEL, highlightthickness=1,
                               highlightbackground=T.SCOPE_LINE, bd=0, cursor="hand2")
        self.scope.pack(fill="x")
        self.scope.bind("<Configure>", lambda e: self.request_render())
        self.scope.bind("<Button-1>", lambda e: self._toggle_scope())
        cap = tk.Frame(top, bg=T.BG_PANEL)
        cap.pack(fill="x", pady=(ui.px(4), ui.px(6)))
        self.scope_lbl = tk.Label(cap, text=SCOPE_CAPTION[self.scope_mode], bg=T.BG_PANEL, fg=T.TEXT_LABEL, font=ui.fonts.label)
        self.scope_lbl.pack(side="left")
        self.notice_lbl = tk.Label(cap, text="", bg=T.BG_PANEL, fg=T.SELECT, font=ui.fonts.label)
        self.notice_lbl.pack(side="right")

        self.scroll = ScrollPanel(self.panel, ui, self.app.router, scrollbar_parent=self.app.scroll_strip)
        self.scroll.pack(fill="both", expand=True, padx=ui.px(20))
        body = self.scroll.inner

        head = tk.Frame(body, bg=T.BG_PANEL)
        head.pack(fill="x", pady=(ui.px(4), ui.px(10)))
        Button(head, ui, "BACK", command=lambda: self.app.go("looks"), width=8).pack(side="left")
        self.save_btn = Button(head, ui, "SAVE", command=self.export, accent=T.SAVE, width=8)
        self.save_btn.pack(side="right")
        self.title_lbl = tk.Label(head, text="", bg=T.BG_PANEL, fg=T.TEXT_READ, font=ui.fonts.button)
        self.title_lbl.pack(side="left", fill="x", expand=True)

        self.look_box = Box(body, ui)
        self.look_box.pack(fill="x", pady=(0, ui.px(10)))

        Button(body, ui, "CROP/ROTATE/RESIZE/WARP", command=self.open_geometry, font=ui.fonts.button_small).pack(
            fill="x", pady=(ui.px(10), ui.px(10)), ipady=ui.px(4))

        box = Box(body, ui, "Tone Curve")
        box.pack(fill="x", pady=ui.px(5))
        self.curve = ToneCurve(box.body, ui, on_begin=self.app.push_undo, on_change=self._on_curve)
        self.curve.pack(pady=ui.px(5))

        box = Box(body, ui, "3-Way Color Wheels")
        box.pack(fill="x", pady=ui.px(5))
        self.wheels = ColorWheels(box.body, ui, on_begin=self.app.push_undo, on_change=self._on_wheel)
        self.wheels.pack(pady=ui.px(5))

        self._slider_box(body, "Camera Calibration", CALIBRATION)
        self._slider_box(body, "Adjustments", ADJUSTMENTS)
        tk.Frame(body, bg=T.BG_PANEL, height=ui.px(20)).pack(fill="x")

    def _slider_box(self, parent, title, rows):
        box = Box(parent, self.ui, title)
        box.pack(fill="x", pady=self.ui.px(5))
        for label, attr, lo, hi, neutral in rows:
            kind = "float" if attr == "sharpness" else "int"
            s = Slider(box.body, self.ui, label, lo, hi, 0.0, kind=kind, decimals=1 if kind == "float" else 0,
                       on_begin=self.app.push_undo, on_change=lambda v, a=attr, n=neutral: self._set_attr(a, v + n))
            s.pack(fill="x", pady=(0, self.ui.px(6)))
            s.neutral = neutral
            self.sliders[attr] = s

    def _build_profile_controls(self):
        state = self.app.session.state
        key = state.profile
        body = self.look_box.body
        for w in body.winfo_children():
            w.destroy()
        self.profile_sliders.clear()
        values = state.params_for(key)
        for c in FILTER_REGISTRY[key].controls:
            s = Slider(body, self.ui, c.label, c.minimum, c.maximum, c.default, value=values[c.label], kind=c.kind,
                       on_begin=self.app.push_undo, on_change=lambda v, lbl=c.label: self._set_profile_param(lbl, v))
            s.pack(fill="x", pady=(0, self.ui.px(6)))
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
        setattr(self.state, ("wheel_shadows", "wheel_midtones", "wheel_highlights")[idx], tuple(pos))
        self.request_render()

    def sync_from_state(self):
        """Push the session state into every control (after undo or opening a photo)."""
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
        self.title_lbl.config(text=s.profile)
        self.request_render()

    # ============================================================= rendering
    def request_render(self):
        session = self.app.session
        if not self.visible or not session.loaded:
            return
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
                base = apply_geometry(proxy, state.geometry, output_scale=max(proxy.shape[:2]) / float(full_edge))
                self._geo_cache = (key, base)
            out = develop(base, state)
            scope = scopes.histogram(out, sw, sh) if scope_mode == "histogram" else scopes.waveform(out, sw, sh)
            luma = cv2.calcHist([cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)], [0], None, [256], [0, 256]).ravel()
            return base, out, scope, luma

        self.render_channel.submit(job, self._render_done, lambda exc: self.notice(f"RENDER ERROR: {exc}"))

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

    def _toggle_scope(self):
        self.scope_mode = "waveform" if self.scope_mode == "histogram" else "histogram"
        self.scope_lbl.config(text=SCOPE_CAPTION[self.scope_mode])
        self.app.settings.set("scope_mode", self.scope_mode)
        self.request_render()

    # ------------------------------------------------------------ viewport
    def _display_image(self):
        return self.before if self.compare else self.rendered

    def _fit_scale(self, img):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        h, w = img.shape[:2]
        return min(cw / w, ch / h)

    def _max_zoom(self, img):
        return max(1.0, 4.0 / max(self._fit_scale(img), 1e-3))

    def _redraw(self):
        img = self._display_image()
        c = self.canvas
        c.delete("all")
        cw, ch = c.winfo_width(), c.winfo_height()
        if img is None or cw < 10 or ch < 10:
            self.vbar.set(0, 1)
            self.hbar.set(0, 1)
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
        tw, th = max(1, int(round((x1 - x0) * s))), max(1, int(round((y1 - y0) * s)))
        interp = cv2.INTER_AREA if s < 1 else (cv2.INTER_NEAREST if s >= 3 else cv2.INTER_LINEAR)
        self._photo = bgr_to_photo(cv2.resize(img[y0:y1, x0:x1], (tw, th), interpolation=interp))
        c.create_image(int(cw / 2 - (cx - x0) * s), int(ch / 2 - (cy - y0) * s), image=self._photo, anchor="nw")
        # light-grey scrollbars mirror the visible part of the frame
        self.hbar.set(max(0.0, (cx - half_w) / w), min(1.0, (cx + half_w) / w))
        self.vbar.set(max(0.0, (cy - half_h) / h), min(1.0, (cy + half_h) / h))
        zoomed = w * s > cw + 1 or h * s > ch + 1
        c.config(cursor="fleur" if zoomed else "")

    def _scrollbar(self, axis, *args):
        img = self._display_image()
        if img is None or self.center is None:
            return
        h, w = img.shape[:2]
        size = w if axis == "x" else h
        s = self._fit_scale(img) * self.zoom
        view = (self.canvas.winfo_width() if axis == "x" else self.canvas.winfo_height()) / s
        i = 0 if axis == "x" else 1
        if args[0] == "moveto":
            self.center[i] = float(args[1]) * size + view / 2
        elif args[0] == "scroll":
            step = view * (0.9 if args[2] == "pages" else 0.1)
            self.center[i] += int(args[1]) * step
        self._redraw()

    def _zoom_to(self, zoom, anchor=None):
        img = self._display_image()
        if img is None:
            return
        zoom = max(1.0, min(self._max_zoom(img), zoom))
        if anchor is not None and self.center is not None:
            ax, ay = anchor  # keep the image point under the cursor fixed
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            s_old, s_new = self._fit_scale(img) * self.zoom, self._fit_scale(img) * zoom
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
        self._zoom_to(self.zoom * (1.15 ** notches),
                      anchor=(e.x_root - self.canvas.winfo_rootx(), e.y_root - self.canvas.winfo_rooty()))

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
            self.request_render()

        GeometryDialog(self.app, session.proxy, session.image.shape[1], session.image.shape[0], self.state.geometry, apply)

    # =============================================================== export
    def export(self):
        session = self.app.session
        if not session.loaded or self._exporting:
            return
        stem = os.path.splitext(os.path.basename(session.path))[0]
        initial = f"EXPORT_{stem}_{self.state.profile.split(' ')[0]}.jpg"
        path = filedialog.asksaveasfilename(
            parent=self.app.root, initialdir=os.path.dirname(session.path), initialfile=initial, defaultextension=".jpg",
            filetypes=[("JPEG Image", "*.jpg *.jpeg"), ("PNG Image", "*.png"), ("TIFF Image", "*.tif *.tiff")])
        if not path:
            return
        if os.path.splitext(path)[1].lower() not in imgio.EXPORT_FORMATS:
            path += ".jpg"
        state, image, exif = self.state.copy(), session.image, session.exif
        self._exporting = True
        self.save_btn.set_enabled(False)
        self.notice("EXPORTING // FULL-RESOLUTION PASS ...", ms=600000)

        def job(_t):
            out = develop(apply_geometry(image, state.geometry), state)
            imgio.save_image(path, out, exif)
            return out.shape

        def done(shape):
            self._exporting = False
            self.save_btn.set_enabled(True)
            self.notice(f"EXPORT COMPLETE // {shape[1]} x {shape[0]}")
            if os.path.dirname(os.path.abspath(path)) == os.path.abspath(self.app.folder):
                self.app.views["library"].load_folder()
            if messagebox.askyesno("WORKSTATION REPORT",
                                   f"Export Complete!\nSaved graded image as:\n{path}\n\nOpen the containing folder?",
                                   parent=self.app.root):
                self.app.reveal(path)

        def failed(exc):
            self._exporting = False
            self.save_btn.set_enabled(True)
            self.notice("")
            messagebox.showerror("WORKSTATION REPORT", f"Export failed.\n\n{exc}", parent=self.app.root)

        self.export_channel.submit(job, done, failed)

    # ================================================================ hooks
    def on_photo_changed(self):
        self._geo_cache = None
        self.rendered = self.before = None
        self.zoom, self.center = 1.0, None
        self._built_profile = None

    def on_show(self):
        first_time = self._built_profile is None
        self.scroll.bar.pack(fill="y", expand=True)
        self.sync_from_state()
        if first_time:
            self.scroll.to_top()
        self.canvas.focus_set()

    def on_hide(self):
        self.scroll.bar.pack_forget()
        self.set_compare(False)

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
