"""Histogram and luma waveform scopes rendered to RGB arrays."""
from __future__ import annotations

import cv2
import numpy as np

BG = (8, 8, 8)
GRID = (30, 30, 30)
LABEL = (90, 90, 90)


def _canvas(w: int, h: int) -> np.ndarray:
    img = np.empty((h, w, 3), np.uint8)
    img[:] = BG
    return img


def histogram(bgr: np.ndarray, w: int, h: int) -> np.ndarray:
    """Thin R, G, B and luma traces on a dark grid (the original LATENT scope)."""
    w, h = max(w, 32), max(h, 32)
    edge = max(bgr.shape[:2])
    small = bgr if edge <= 800 else cv2.resize(bgr, None, fx=800 / edge, fy=800 / edge, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    traces = [(cv2.calcHist([small], [2], None, [256], [0, 256]).ravel(), (255, 64, 64)),   # R
              (cv2.calcHist([small], [1], None, [256], [0, 256]).ravel(), (64, 255, 64)),   # G
              (cv2.calcHist([small], [0], None, [256], [0, 256]).ravel(), (64, 64, 255)),   # B
              (cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel(), (200, 200, 200))]  # luma
    # ignore the two end bins when scaling so clipped frames stay readable
    peak = max(max(t[1:255].max() for t, _ in traces), 1.0)
    img = np.full((h, w, 3), 8, np.uint8)
    for i in range(1, 4):
        x = int(w * i / 4)
        cv2.line(img, (x, 0), (x, h), (20, 20, 20), 1)
    xs = np.linspace(0, 255, w)
    for hist, color in traces:
        vals = np.interp(xs, np.arange(256), np.minimum(hist / peak, 1.0))
        pts = np.stack([np.arange(w), h - 2 - vals * (h - 10)], axis=1).astype(np.int32)
        cv2.polylines(img, [pts], False, color, 1, cv2.LINE_AA)
    return img


def waveform(bgr: np.ndarray, w: int, h: int) -> np.ndarray:
    """Luma waveform (Rec.709) with 0/25/50/75/100 IRE guides."""
    w, h = max(w, 32), max(h, 32)
    cols = min(w, 360)
    sh = int(round(bgr.shape[0] * cols / float(bgr.shape[1])))
    small = cv2.resize(bgr, (cols, max(8, min(sh, 240))), interpolation=cv2.INTER_AREA).astype(np.float32)
    b, g, r = cv2.split(small)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b

    pad = 8
    usable = h - 2 * pad
    acc = np.zeros((h, cols), np.float32)
    ry = np.clip((h - pad - y / 255.0 * usable).astype(np.int32), 0, h - 1)
    cx = np.broadcast_to(np.arange(cols), ry.shape)
    np.add.at(acc, (ry, cx), 1.0)
    acc = np.log1p(acc)
    acc /= max(float(acc.max()), 1e-6)
    acc = cv2.resize(acc, (w, h), interpolation=cv2.INTER_LINEAR)

    img = _canvas(w, h)
    for pct in (0, 25, 50, 75, 100):
        yy = int(h - pad - pct / 100.0 * usable)
        cv2.line(img, (0, yy), (w, yy), GRID, 1)
        cv2.putText(img, str(pct), (w - 22, max(8, yy - 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.28, LABEL, 1, cv2.LINE_AA)
    trace = np.dstack([acc * 170, acc * 235, acc * 150])  # RGB soft green
    return np.clip(img.astype(np.float32) + trace, 0, 255).astype(np.uint8)
