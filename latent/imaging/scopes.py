"""Histogram and luma waveform scopes rendered to RGB arrays."""
from __future__ import annotations

import cv2
import numpy as np

BG = (10, 10, 10)
GRID = (30, 30, 30)
LABEL = (90, 90, 90)


def _canvas(w: int, h: int) -> np.ndarray:
    img = np.empty((h, w, 3), np.uint8)
    img[:] = BG
    return img


def histogram(bgr: np.ndarray, w: int, h: int) -> np.ndarray:
    """RGB-parade style histogram: additive channel fills plus a luma line."""
    w, h = max(w, 32), max(h, 32)
    small = bgr if max(bgr.shape[:2]) <= 800 else cv2.resize(bgr, None, fx=800 / max(bgr.shape[:2]), fy=800 / max(bgr.shape[:2]), interpolation=cv2.INTER_AREA)
    hists = [cv2.calcHist([small], [c], None, [256], [0, 256]).ravel() for c in range(3)]
    luma = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)], [0], None, [256], [0, 256]).ravel()
    # Ignore the extreme bins when normalising so clipped images stay readable.
    peak = max(max(hh[1:255].max() for hh in hists), luma[1:255].max(), 1.0)
    xs = np.linspace(0, 255, w)
    pad = 4
    usable = h - 2 * pad

    out = np.zeros((h, w, 3), np.float32)
    rows = np.arange(h, dtype=np.float32)[:, None]
    colors = {0: (0.25, 0.45, 1.0), 1: (0.35, 1.0, 0.45), 2: (1.0, 0.35, 0.3)}  # RGB tints for B, G, R
    for c, hh in enumerate(hists):
        vals = np.interp(xs, np.arange(256), np.minimum(hh / peak, 1.0))
        top = h - pad - vals * usable
        mask = (rows >= top[None, :]).astype(np.float32) * 0.55
        tint = colors[c]
        for k in range(3):
            out[:, :, k] += mask * tint[k]
    out = np.clip(out, 0, 1) * 200
    img = _canvas(w, h).astype(np.float32)
    img = np.clip(img + out, 0, 255).astype(np.uint8)

    for i in range(1, 4):
        x = int(w * i / 4)
        cv2.line(img, (x, 0), (x, h), GRID, 1)
    lvals = np.interp(xs, np.arange(256), np.minimum(luma / peak, 1.0))
    pts = np.stack([np.arange(w), h - pad - lvals * usable], axis=1).astype(np.int32)
    cv2.polylines(img, [pts], False, (215, 215, 215), 1, cv2.LINE_AA)

    # Clipping indicators
    total = float(small.shape[0] * small.shape[1])
    if luma[0] / total > 0.01:
        cv2.rectangle(img, (0, 0), (5, 5), (90, 160, 255), -1)
    if luma[255] / total > 0.01:
        cv2.rectangle(img, (w - 6, 0), (w - 1, 5), (255, 90, 90), -1)
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
