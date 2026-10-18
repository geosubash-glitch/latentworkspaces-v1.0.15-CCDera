"""Film emulsion engines.

Every engine takes a BGR ``uint8`` image plus its profile parameters (all
controls except the trailing grain control) and returns a BGR ``uint8`` image.

All tone functions work on normalised values (0..1) so black stays black and
white stays white unless a profile deliberately lifts or tints them.  The v1
engines applied power curves directly to 0..255 values (``r ** 1.12``), which
pushed mid-grey to saturated orange/magenta; see docs/filter_specifications.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Tuple

import cv2
import numpy as np


# --------------------------------------------------------------------------
# Shared maths
# --------------------------------------------------------------------------
def limit_and_cast(img: np.ndarray) -> np.ndarray:
    return np.clip(img, 0, 255).astype(np.uint8)


def gamma(channel: np.ndarray, g: float) -> np.ndarray:
    """Normalised power curve: 0 -> 0, 255 -> 255, midtones bend by ``g``."""
    return 255.0 * np.power(np.clip(channel, 0.0, 255.0) / 255.0, g)


def sigmoid_curve(x01: np.ndarray, slope: float) -> np.ndarray:
    """S-shaped contrast curve rescaled so that 0 -> 0 and 1 -> 1."""
    lo = 1.0 / (1.0 + np.exp(slope * 0.5))
    hi = 1.0 / (1.0 + np.exp(-slope * 0.5))
    s = 1.0 / (1.0 + np.exp(-slope * (x01 - 0.5)))
    return (s - lo) / (hi - lo)


def scale_saturation(img_u8: np.ndarray, factor: float) -> np.ndarray:
    """Scale HSV saturation; returns float32 BGR."""
    if factor == 1.0:
        return img_u8.astype(np.float32)
    hsv = cv2.cvtColor(img_u8, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)


def luma01(bgr: np.ndarray) -> np.ndarray:
    """Rec.601 luma in 0..1 from a BGR image (uint8 or float)."""
    b, g, r = cv2.split(bgr.astype(np.float32))
    return np.clip((0.299 * r + 0.587 * g + 0.114 * b) / 255.0, 0.0, 1.0)


def _merge(b, g, r) -> np.ndarray:
    return limit_and_cast(cv2.merge([b, g, r]))


# --------------------------------------------------------------------------
# Engines
# --------------------------------------------------------------------------
def run_provia(img, exp, sat):
    b, g, r = cv2.split(scale_saturation(img, (sat / 100.0) * 1.05))
    k = exp / 100.0
    return _merge(b * k * 1.04, g * k, r * k)


def run_velvia(img, contrast_slope, saturation_boost):
    curve = sigmoid_curve(img.astype(np.float32) / 255.0, contrast_slope)
    return limit_and_cast(scale_saturation(limit_and_cast(curve * 255.0), saturation_boost))


def run_astia(img, soft_gamma, skin_warmth):
    base = scale_saturation(img, 0.95)
    y = luma01(base)
    mid = 4.0 * y * (1.0 - y)
    b, g, r = cv2.split(gamma(base, 1.0 / soft_gamma))
    return _merge(b - skin_warmth * 0.4 * mid, g, r + skin_warmth * mid)


def run_classic_chrome(img, shadow_crush, desat_rate):
    base = scale_saturation(img, desat_rate / 100.0)
    return limit_and_cast(gamma(base, shadow_crush))


def run_kodachrome(img, yellow_gamma, red_push):
    base = scale_saturation(img, 1.10)
    y = luma01(base)
    b, g, r = cv2.split(base)
    b = gamma(b, yellow_gamma)            # less blue in the mids -> yellow
    g = gamma(g, 0.98)
    r = gamma(r, 0.92) + red_push * y * y  # warm red push in the highlights
    toned = cv2.merge([b, g, r]) / 255.0
    contrast = sigmoid_curve(np.clip(toned, 0.0, 1.0), 5.0)
    return limit_and_cast((0.5 * toned + 0.5 * contrast) * 255.0)


def run_agfa_vista(img, red_saturation, exposure):
    b, g, r = cv2.split(scale_saturation(img, 1.15))
    k = exposure / 100.0
    return _merge(b * k, g * k, r * red_saturation * k)


def run_superia(img, green_gamma, emerald_layer):
    y = luma01(img)
    b, g, r = cv2.split(img.astype(np.float32))
    shadow = (1.0 - y) ** 2
    return _merge(gamma(b, 0.98), gamma(g, green_gamma) + emerald_layer * shadow, gamma(r, 1.04))


def run_ilford_hp5(img, shadow_punch, highlight_gamma):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mono = gamma(gray, highlight_gamma) / 255.0
    mono = 0.5 + (mono - 0.5) * shadow_punch
    mono = limit_and_cast(mono * 255.0)
    return cv2.merge([mono, mono, mono])


def run_vision3(img, shadow_teal, highlight_amber):
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    y, cr, cb = cv2.split(ycrcb)
    dark = (255.0 - y) / 255.0
    bright = y / 255.0
    cr = cr - dark * (shadow_teal * 0.5) + bright * (highlight_amber * 0.7)
    cb = cb + dark * shadow_teal - bright * (highlight_amber * 0.4)
    return cv2.cvtColor(limit_and_cast(cv2.merge([y, cr, cb])), cv2.COLOR_YCrCb2BGR)


def run_ektachrome(img, blue_pop, contrast):
    b, g, r = cv2.split(img.astype(np.float32))
    pop = np.clip(cv2.merge([b * blue_pop, g, r]) / 255.0, 0.0, 1.0)
    return limit_and_cast(sigmoid_curve(pop, contrast) * 255.0)


def run_fujicolor_c200(img, green_shadows, warmth):
    y = luma01(img)
    b, g, r = cv2.split(img.astype(np.float32))
    return _merge(b * 0.96, gamma(g, 0.98) + green_shadows * (1.0 - y) ** 2, r * 1.03 + warmth * y * y)


def run_portra(img, pastel_gamma, skin_tint):
    base = scale_saturation(img, 0.85)
    y = luma01(base)
    mid = 4.0 * y * (1.0 - y)
    b, g, r = cv2.split(gamma(base, 1.0 / pastel_gamma))
    return _merge(b * 0.97, g + skin_tint * 0.35 * mid, r + skin_tint * mid)


def run_halation(img, threshold, size, intensity):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY)
    # Bloom radius is defined for a 1200px frame; keep it proportional.
    k = int(round(size * max(img.shape[:2]) / 1200.0))
    k = max(3, k | 1)
    bloom = cv2.GaussianBlur(mask, (k, k), 0).astype(np.float32) / 255.0
    glow = cv2.merge([bloom * intensity * 0.4, bloom * intensity * 0.2, bloom * intensity])
    return limit_and_cast(img.astype(np.float32) + glow)


def run_xenon_90s(img, curve, saturation):
    curved = sigmoid_curve(img.astype(np.float32) / 255.0, curve)
    return limit_and_cast(scale_saturation(limit_and_cast(curved * 255.0), saturation))


def run_pacific_cold(img, blue, green, desat):
    b, g, r = cv2.split(scale_saturation(img, desat / 100.0))
    return _merge(b + blue, g + green, r - blue / 2.0)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Control:
    label: str
    minimum: float
    maximum: float
    default: float
    kind: str  # "float" or "int"

    def coerce(self, value: float) -> float:
        value = min(self.maximum, max(self.minimum, float(value)))
        return float(int(round(value))) if self.kind == "int" else value


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    tag: str
    engine: Callable[..., np.ndarray]
    grain_type: str
    controls: Tuple[Control, ...]
    description: str
    mono: bool = False

    @property
    def defaults(self) -> dict:
        return {c.label: c.default for c in self.controls}

    def split_params(self, values: dict) -> Tuple[List[float], float]:
        """Return (engine args, grain amount) from a {label: value} dict."""
        vals = [c.coerce(values.get(c.label, c.default)) for c in self.controls]
        return vals[:-1], vals[-1]


def _p(key, name, tag, engine, grain, controls, description, mono=False):
    return Profile(key, name, tag, engine, grain, tuple(Control(*c) for c in controls), description, mono)


PROFILES: Tuple[Profile, ...] = (
    _p("PROVIA STANDARD (CCD)", "Provia Standard", "CCD", run_provia, "fine",
       [("Sensor Exposure Val", 60, 140, 100, "float"), ("Chroma Saturation", 70, 140, 100, "float"), ("Micro Sensor Noise", 0, 15, 3, "int")],
       "Standard color profile with CCD sensor emulation, fine grain characteristics, and baseline exposure response."),
    _p("VELVIA VIVID (SLIDE)", "Velvia Vivid", "Slide", run_velvia, "fine",
       [("Contrast Curve Slope", 4.0, 9.0, 6.2, "float"), ("Velvia Saturation Pop", 1.1, 1.7, 1.35, "float"), ("Slide Fine Grain", 0, 20, 4, "int")],
       "High contrast landscape slide emulation with saturated color reproduction and fine silver halide grain."),
    _p("ASTIA SOFT (PORTRAIT)", "Astia Soft", "Portrait", run_astia, "fine",
       [("Highlights Gamma", 0.8, 1.4, 1.05, "float"), ("Skin Warmth Coefficient", 0, 25, 8, "int"), ("Portrait Micro Grain", 0, 15, 2, "int")],
       "Soft portrait profile with gentle highlight roll-off, optimized skin warmth, and low-contrast fine grain."),
    _p("CLASSIC CHROME (PRINT)", "Classic Chrome", "Print", run_classic_chrome, "midtone",
       [("Shadow Crush Exponential", 1.0, 1.6, 1.25, "float"), ("Chroma Suppression", 40, 95, 65, "int"), ("Print Hard Texture", 0, 25, 8, "int")],
       "Documentary-style print film emulation with crushed shadows, low saturation, and pronounced print texture."),
    _p("KODACHROME 64 (RETRO)", "Kodachrome 64", "Retro", run_kodachrome, "heavy",
       [("Yellow Channel Gamma", 0.8, 1.4, 1.10, "float"), ("Warm Red Push Vector", 0, 20, 8, "int"), ("Vintage Slide Grain", 0, 35, 14, "int")],
       "Warm vintage color slide look with high yellow saturation, warm red bias, and organic heavy grain."),
    _p("AGFA VISTA 400 (COLOR)", "Agfa Vista 400", "Color", run_agfa_vista, "heavy",
       [("Agfa Red Saturation", 1.0, 1.5, 1.25, "float"), ("Negative Print Exposure", 70, 130, 100, "float"), ("Emulsion Silver Grain", 0, 35, 12, "int")],
       "Vibrant color negative emulation with saturated red channels, high latitude, and heavy emulsion grain."),
    _p("SUPERIA X-TRA (LAYER4)", "Superia X-Tra", "Layer 4", run_superia, "fine",
       [("Green Channel Gamma", 0.8, 1.3, 0.92, "float"), ("Emerald Layer Offset", 0, 20, 6, "int"), ("Superia Fine Grain", 0, 20, 6, "int")],
       "Four-layer color negative emulation with emerald green response and balanced fine grain."),
    _p("ILFORD HP5 PLUS (B&W)", "Ilford HP5 Plus", "B&W", run_ilford_hp5, "heavy",
       [("Shadow Contrast Scale", 0.8, 1.4, 1.05, "float"), ("Highlight Latitude Gamma", 0.7, 1.3, 0.95, "float"), ("Pan Metallic Grain", 0, 40, 18, "int")],
       "High-contrast panchromatic monochrome print emulation with shadow latitude and metallic silver grain.", mono=True),
    _p("KODAK VISION3 (CINE)", "Kodak Vision3", "Cine", run_vision3, "fine",
       [("Shadow Teal Injection", 0, 35, 16, "int"), ("Highlight Amber Bleed", 0, 30, 12, "int"), ("Motion Picture Grain", 0, 25, 7, "int")],
       "Modern cinematic film stock with dark-teal shadows, amber-bleed highlights, and fine motion picture grain."),
    _p("EKTACHROME E100 (DIAL)", "Ektachrome E100", "Dial", run_ektachrome, "fine",
       [("Cobalt Blue Multiplier", 1.0, 1.4, 1.12, "float"), ("Contrast Threshold Slope", 4.0, 8.5, 5.8, "float"), ("Fine Saturated Grain", 0, 20, 4, "int")],
       "E6 slide film emulation with cobalt blue saturation, strong contrast, and fine dynamic range."),
    _p("FUJICOLOR C200 (WARM)", "Fujicolor C200", "Warm", run_fujicolor_c200, "heavy",
       [("Green Shadow Bias", 0, 15, 6, "int"), ("Highlight Warmth Push", 0, 20, 8, "int"), ("Nostalgic Paper Grain", 0, 30, 10, "int")],
       "Warm consumer negative stock with green shadow bias, highlight warming, and heavy nostalgic grain."),
    _p("KODAK PORTRA 400 (SOFT)", "Kodak Portra 400", "Soft", run_portra, "fine",
       [("Pastel Midtone Gamma", 0.9, 1.3, 1.08, "float"), ("Organic Skin Warming", 0, 15, 5, "int"), ("Micro Portrait Grain", 0, 15, 3, "int")],
       "Professional portrait film profile with pastel midtones, warm skin tone bias, and organic micro-grain."),
    _p("LOFI HALATION (GLARE)", "Lo-Fi Halation", "Glare", run_halation, "midtone",
       [("Hotspot Cutoff Threshold", 160, 245, 205, "int"), ("Glow Blur Radius Pixels", 11, 55, 27, "int"), ("Bulb Overexposure Power", 5, 45, 25, "int"), ("Scanner Line Base Noise", 0, 35, 12, "int")],
       "Creative style simulating red highlight halation glare, analog bulb overexposure, and scanning line noise."),
    _p("90S XENON DIRECT FLASH", "90s Xenon Flash", "Flash", run_xenon_90s, "heavy",
       [("Sigmoid Flash Contrast", 4.0, 9.5, 6.5, "float"), ("Flash Saturation Pop", 1.0, 1.7, 1.25, "float"), ("Direct Shadow Silver Grain", 0, 40, 15, "int")],
       "High-contrast direct flash style simulating harsh xenon light exposure, direct shadow drop-off, and silver print grain."),
    _p("PACIFIC MISTY COLD", "Pacific Misty Cold", "Cold", run_pacific_cold, "midtone",
       [("Misty Blue Shift Vector", 0, 45, 22, "int"), ("Deep Forest Green Shift", 0, 35, 14, "int"), ("Chroma Desaturation", 25, 95, 50, "int"), ("Damp Atmospheric Grain", 0, 30, 8, "int")],
       "Moody cold-tone atmospheric look with deep forest greens, cyan-blue shadows, and damp mist grain."),
)

FILTER_REGISTRY = {p.key: p for p in PROFILES}
PROFILE_KEYS = [p.key for p in PROFILES]
DEFAULT_PROFILE = PROFILE_KEYS[0]
