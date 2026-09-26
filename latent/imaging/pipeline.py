"""The 7-stage non-destructive development pipeline.

Stage order (see docs/pipeline_architecture.md):
    geometry -> 1 emulsion -> 2 grain -> 3 tone curve -> 4 colour wheels
    -> 5 calibration -> 6 vignette -> 7 global adjustments & sharpening

Everything the pipeline needs lives in :class:`EditState`, a plain value
object.  The UI hands a copy to the render thread, so the worker never touches
Tk variables.
"""
from __future__ import annotations

import copy
import math
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .filters import FILTER_REGISTRY, DEFAULT_PROFILE, limit_and_cast, luma01

# Long edge of the preview proxy. Grain and blur radii are defined for this
# size and scaled for other resolutions so preview and export match.
PROXY_EDGE = 1400
REFERENCE_EDGE = 1200.0
WHEEL_MAX_OFFSET = 50.0

Point = Tuple[float, float]


@dataclass
class Geometry:
    crop_l: float = 0.0     # percent of width/height
    crop_r: float = 100.0
    crop_t: float = 0.0
    crop_b: float = 100.0
    quarter_turns: int = 0  # clockwise 90-degree turns, applied first
    rotate: float = 0.0     # straighten angle in degrees, clockwise positive
    v_keystone: float = 0.0  # -100..100
    h_keystone: float = 0.0
    resize_w: Optional[int] = None  # final output size in pixels
    resize_h: Optional[int] = None

    def is_identity(self) -> bool:
        return self == Geometry()


@dataclass
class EditState:
    profile: str = DEFAULT_PROFILE
    profile_params: Dict[str, Dict[str, float]] = field(default_factory=dict)

    exposure: float = 100.0
    contrast: float = 100.0
    saturation: float = 100.0
    warmth: float = 0.0
    tint: float = 0.0
    highlights: float = 100.0
    shadows: float = 100.0
    sharpness: float = 0.0
    vignette: float = 0.0

    cal_red: float = 0.0
    cal_green: float = 0.0
    cal_blue: float = 0.0

    curve: List[Point] = field(default_factory=lambda: [(0.0, 0.0), (255.0, 255.0)])
    # Colour wheel positions, normalised to the unit disc (x right, y down).
    wheel_shadows: Point = (0.0, 0.0)
    wheel_midtones: Point = (0.0, 0.0)
    wheel_highlights: Point = (0.0, 0.0)

    geometry: Geometry = field(default_factory=Geometry)

    def params_for(self, profile: Optional[str] = None) -> Dict[str, float]:
        key = profile or self.profile
        values = dict(FILTER_REGISTRY[key].defaults)
        values.update(self.profile_params.get(key, {}))
        return values

    def copy(self) -> "EditState":
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
def apply_geometry(img: np.ndarray, geo: Geometry, output_scale: float = 1.0) -> np.ndarray:
    """Keystone, rotate, crop and resize.

    ``output_scale`` scales the requested resize dimensions; the preview proxy
    passes ``proxy_edge / full_edge`` so it keeps the export's aspect ratio.
    """
    if geo.is_identity():
        return img
    turns = geo.quarter_turns % 4
    if turns:
        img = np.ascontiguousarray(np.rot90(img, k=-turns))
    h, w = img.shape[:2]

    if geo.v_keystone or geo.h_keystone:
        sw, sh = w * 0.15, h * 0.15
        tl, tr = [0.0, 0.0], [w - 1.0, 0.0]
        bl, br = [0.0, h - 1.0], [w - 1.0, h - 1.0]
        if geo.v_keystone > 0:
            s = geo.v_keystone / 100.0 * sw
            tl[0] += s; tr[0] -= s
        elif geo.v_keystone < 0:
            s = -geo.v_keystone / 100.0 * sw
            bl[0] += s; br[0] -= s
        if geo.h_keystone > 0:
            s = geo.h_keystone / 100.0 * sh
            tl[1] += s; bl[1] -= s
        elif geo.h_keystone < 0:
            s = -geo.h_keystone / 100.0 * sh
            tr[1] += s; br[1] -= s
        src = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
        dst = np.float32([tl, tr, bl, br])
        m = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    if geo.rotate:
        # Scale so the rotated frame still covers the canvas: no black corners.
        m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -geo.rotate, straighten_scale(w, h, geo.rotate))
        img = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    x1 = int(round(w * geo.crop_l / 100.0)); x2 = int(round(w * geo.crop_r / 100.0))
    y1 = int(round(h * geo.crop_t / 100.0)); y2 = int(round(h * geo.crop_b / 100.0))
    x1 = max(0, min(x1, w - 2)); x2 = max(x1 + 2, min(x2, w))
    y1 = max(0, min(y1, h - 2)); y2 = max(y1 + 2, min(y2, h))
    img = img[y1:y2, x1:x2]

    if geo.resize_w and geo.resize_h:
        tw = max(1, int(round(geo.resize_w * output_scale)))
        th = max(1, int(round(geo.resize_h * output_scale)))
        interp = cv2.INTER_AREA if tw * th < img.shape[0] * img.shape[1] else cv2.INTER_CUBIC
        img = cv2.resize(img, (tw, th), interpolation=interp)
    return np.ascontiguousarray(img)


def straighten_scale(w: int, h: int, degrees: float) -> float:
    t = math.radians(abs(degrees) % 180.0)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    return max(c + s * h / float(w), c + s * w / float(h))


# --------------------------------------------------------------------------
# Stage 2: luminosity-weighted grain
# --------------------------------------------------------------------------
_noise_cache: Dict[tuple, np.ndarray] = {}
_noise_lock = threading.Lock()


def _grain_field(h: int, w: int, channels: int, seed: int = 7) -> np.ndarray:
    """Unit-variance noise whose grain size is proportional to the frame.

    Film grain is a property of the negative, so a 6000px export must show the
    same grain structure as the 1400px preview.  Noise is generated at
    reference resolution and upsampled for bigger frames.
    """
    key = (h, w, channels, seed)
    with _noise_lock:
        cached = _noise_cache.get(key)
    if cached is not None:
        return cached
    factor = max(1.0, max(h, w) / REFERENCE_EDGE)
    gh, gw = max(1, int(math.ceil(h / factor))), max(1, int(math.ceil(w / factor)))
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal((gh, gw, channels), dtype=np.float32)
    if factor > 1.0:
        noise = cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)
        if noise.ndim == 2:
            noise = noise[..., None]
        noise /= max(float(noise.std()), 1e-6)
    with _noise_lock:
        if len(_noise_cache) > 6:
            _noise_cache.clear()
        _noise_cache[key] = noise
    return noise


def apply_grain(img: np.ndarray, intensity: float, grain_type: str = "midtone", mono: bool = False) -> np.ndarray:
    if intensity <= 0:
        return img
    h, w = img.shape[:2]
    y = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    if grain_type == "midtone":
        weight = 4.0 * y * (1.0 - y)
    elif grain_type == "heavy":
        weight = 1.0 - 0.3 * y
    else:  # fine
        weight = 0.4 * y + 0.1
    noise = _grain_field(h, w, 1 if mono else 3)
    grain = noise * (intensity * 0.5) * weight[..., None]
    return limit_and_cast(img.astype(np.float32) + grain)


# --------------------------------------------------------------------------
# Stage 3: tone curve
# --------------------------------------------------------------------------
def compute_spline_lut(points) -> np.ndarray:
    """Natural cubic spline through the control points, baked into a LUT."""
    pts = sorted({(float(x), float(y)) for x, y in points})
    # keep one point per x
    dedup: Dict[float, float] = {}
    for x, y in pts:
        dedup[x] = y
    pts = sorted(dedup.items())
    if len(pts) < 2:
        return np.arange(256, dtype=np.uint8)
    x = [p[0] for p in pts]
    y = [p[1] for p in pts]
    if x[0] > 0:
        x.insert(0, 0.0); y.insert(0, y[0])
    if x[-1] < 255:
        x.append(255.0); y.append(y[-1])
    n = len(x) - 1
    if n == 1:
        lut = np.interp(np.arange(256), x, y)
        return np.clip(np.round(lut), 0, 255).astype(np.uint8)

    h = [x[i + 1] - x[i] for i in range(n)]
    a_mat = np.zeros((n + 1, n + 1))
    rhs = np.zeros(n + 1)
    a_mat[0, 0] = a_mat[n, n] = 1.0
    for i in range(1, n):
        a_mat[i, i - 1] = h[i - 1]
        a_mat[i, i] = 2.0 * (h[i - 1] + h[i])
        a_mat[i, i + 1] = h[i]
        rhs[i] = 3.0 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1])
    try:
        c = np.linalg.solve(a_mat, rhs)
    except np.linalg.LinAlgError:
        lut = np.interp(np.arange(256), x, y)
        return np.clip(np.round(lut), 0, 255).astype(np.uint8)

    b = [(y[i + 1] - y[i]) / h[i] - h[i] * (2.0 * c[i] + c[i + 1]) / 3.0 for i in range(n)]
    d = [(c[i + 1] - c[i]) / (3.0 * h[i]) for i in range(n)]
    vals = np.arange(256, dtype=np.float64)
    idx = np.clip(np.searchsorted(x, vals, side="right") - 1, 0, n - 1)
    dx = vals - np.asarray(x)[idx]
    lut = (np.asarray(y)[idx] + np.asarray(b)[idx] * dx + np.asarray(c)[idx] * dx ** 2
           + np.asarray(d)[idx] * dx ** 3)
    return np.clip(np.round(lut), 0, 255).astype(np.uint8)


def curve_is_identity(points) -> bool:
    return all(abs(px - py) < 1e-6 for px, py in points)


# --------------------------------------------------------------------------
# Stage 4: three-way colour wheels
# --------------------------------------------------------------------------
# Hue angles (screen coordinates, y down) of the primaries on the wheel image
# generated by ``color_wheel_rgba``: red at 180deg, green at -60deg, blue at 60deg.
_PRIMARY_ANGLES = {"r": -math.pi, "g": -math.pi / 3.0, "b": math.pi / 3.0}


def wheel_to_offset(pos: Point) -> List[float]:
    """Map a normalised wheel position to a BGR offset (sums to zero)."""
    dx, dy = pos
    r = math.hypot(dx, dy)
    if r < 1e-6:
        return [0.0, 0.0, 0.0]
    r = min(r, 1.0)
    theta = math.atan2(dy, dx)
    amt = r * WHEEL_MAX_OFFSET
    return [amt * math.cos(theta - _PRIMARY_ANGLES["b"]),
            amt * math.cos(theta - _PRIMARY_ANGLES["g"]),
            amt * math.cos(theta - _PRIMARY_ANGLES["r"])]


def apply_color_wheels(img: np.ndarray, shadows: Point, midtones: Point, highlights: Point) -> np.ndarray:
    so, mo, ho = wheel_to_offset(shadows), wheel_to_offset(midtones), wheel_to_offset(highlights)
    if not any(so + mo + ho):
        return img
    f = img.astype(np.float32)
    b, g, r = cv2.split(f)
    yn = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    ws = (1.0 - yn) ** 2
    wh = yn ** 2
    wm = 1.0 - ws - wh
    b = b + ws * so[0] + wm * mo[0] + wh * ho[0]
    g = g + ws * so[1] + wm * mo[1] + wh * ho[1]
    r = r + ws * so[2] + wm * mo[2] + wh * ho[2]
    return limit_and_cast(cv2.merge([b, g, r]))


def color_wheel_rgba(radius: int, value: int = 200) -> np.ndarray:
    """RGBA image of the hue/saturation disc used by the wheel widget."""
    size = radius * 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = xx - radius + 0.5, yy - radius + 0.5
    r = np.sqrt(dx * dx + dy * dy)
    angle = np.arctan2(dy, dx)
    hue = ((angle + np.pi) / (2.0 * np.pi) * 179.0).astype(np.uint8)
    sat = np.clip(r / radius * 255.0, 0, 255).astype(np.uint8)
    val = np.full_like(hue, value)
    rgb = cv2.cvtColor(cv2.merge([hue, sat, val]), cv2.COLOR_HSV2RGB)
    alpha = np.clip((radius - r) * 2.0, 0, 1) * 255.0
    return np.dstack([rgb, alpha.astype(np.uint8)])


# --------------------------------------------------------------------------
# Stages 5-7
# --------------------------------------------------------------------------
def apply_calibration(img: np.ndarray, r_sat: float, g_sat: float, b_sat: float) -> np.ndarray:
    if not (r_sat or g_sat or b_sat):
        return img
    b, g, r = cv2.split(img.astype(np.float32))
    # All differences come from the original channels so the order of the
    # three adjustments doesn't matter.
    nr = r + (r_sat / 100.0) * (r - (g + b) * 0.5)
    ng = g + (g_sat / 100.0) * (g - (r + b) * 0.5)
    nb = b + (b_sat / 100.0) * (b - (r + g) * 0.5)
    return limit_and_cast(cv2.merge([nb, ng, nr]))


_vignette_cache: Dict[tuple, np.ndarray] = {}


def apply_vignette(img: np.ndarray, strength: float) -> np.ndarray:
    if not strength:
        return img
    h, w = img.shape[:2]
    dist2 = _vignette_cache.get((h, w))
    if dist2 is None:
        cx, cy = w / 2.0, h / 2.0
        xs = (np.arange(w, dtype=np.float32) - cx) ** 2
        ys = (np.arange(h, dtype=np.float32) - cy) ** 2
        dist2 = (ys[:, None] + xs[None, :]) / (cx * cx + cy * cy)
        if len(_vignette_cache) > 4:
            _vignette_cache.clear()
        _vignette_cache[(h, w)] = dist2
    factor = np.clip(1.0 + (strength / 100.0) * dist2, 0.0, 2.0)
    return limit_and_cast(img.astype(np.float32) * factor[..., None])


def apply_global_adjustments(img, exposure, contrast, saturation, warmth, tint,
                             highlights, shadows, sharpness, sharpen_scale: float = 1.0):
    f = img.astype(np.float32)
    if exposure != 100.0:
        f *= exposure / 100.0
    if warmth or tint:
        b, g, r = cv2.split(f)
        r = r + warmth * 0.3 - tint * 0.15
        b = b - warmth * 0.3 - tint * 0.15
        g = g + tint * 0.3
        f = cv2.merge([b, g, r])
    if highlights != 100.0 or shadows != 100.0:
        y = luma01(np.clip(f, 0, 255))
        delta = (y * y) * ((highlights - 100.0) / 2.0) + ((1.0 - y) ** 2) * ((shadows - 100.0) / 2.0)
        f = f + delta[..., None]
    if contrast != 100.0:
        f = 127.5 + (contrast / 100.0) * (f - 127.5)
    out = limit_and_cast(f)
    if saturation != 100.0:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (saturation / 100.0), 0, 255)
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    if sharpness > 0:
        sigma = 1.5 * max(1.0, sharpen_scale)
        blurred = cv2.GaussianBlur(out, (0, 0), sigma)
        out = cv2.addWeighted(out, 1.0 + sharpness, blurred, -sharpness, 0)
    return out


# --------------------------------------------------------------------------
# Full renders
# --------------------------------------------------------------------------
def apply_profile(img: np.ndarray, state: EditState, profile: Optional[str] = None, grain: bool = True) -> np.ndarray:
    key = profile or state.profile
    prof = FILTER_REGISTRY[key]
    args, grain_amount = prof.split_params(state.params_for(key))
    out = prof.engine(img, *args)
    if grain:
        out = apply_grain(out, grain_amount, prof.grain_type, prof.mono)
    return out


def develop(img: np.ndarray, state: EditState) -> np.ndarray:
    """Run stages 1-7 on an image that already has geometry applied."""
    out = apply_profile(img, state)
    if not curve_is_identity(state.curve):
        out = cv2.LUT(out, compute_spline_lut(state.curve))
    out = apply_color_wheels(out, state.wheel_shadows, state.wheel_midtones, state.wheel_highlights)
    out = apply_calibration(out, state.cal_red, state.cal_green, state.cal_blue)
    out = apply_vignette(out, state.vignette)
    scale = max(out.shape[:2]) / REFERENCE_EDGE
    return apply_global_adjustments(out, state.exposure, state.contrast, state.saturation,
                                    state.warmth, state.tint, state.highlights, state.shadows,
                                    state.sharpness, sharpen_scale=scale)


def make_proxy(img: np.ndarray, edge: int = PROXY_EDGE) -> np.ndarray:
    h, w = img.shape[:2]
    scale = edge / float(max(h, w))
    if scale >= 1.0:
        return img.copy()
    return cv2.resize(img, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                      interpolation=cv2.INTER_AREA)


def fit_size(w: int, h: int, max_w: int, max_h: int, upscale: bool = False) -> Tuple[int, int]:
    s = min(max_w / float(w), max_h / float(h))
    if not upscale:
        s = min(s, 1.0)
    return max(1, int(w * s)), max(1, int(h * s))
