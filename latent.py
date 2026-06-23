import cv2, numpy as np, os, time, threading, copy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ==========================================
# 1. CORE RECONFIGURABLE PIXEL CALCULATORS
# ==========================================
def limit_and_cast(img):
    return np.clip(img, 0, 255).astype(np.uint8)

def apply_geometry_transforms(img, crop_l, crop_r, crop_t, crop_b, rotate, v_keystone, h_keystone, resize_w=None, resize_h=None):
    h, w = img.shape[:2]
    
    # 1. Perspective Warp (Keystoning)
    max_shift_w = w * 0.15
    max_shift_h = h * 0.15
    
    tl_x, tl_y = 0.0, 0.0
    tr_x, tr_y = float(w - 1), 0.0
    bl_x, bl_y = 0.0, float(h - 1)
    br_x, br_y = float(w - 1), float(h - 1)
    
    if v_keystone > 0:
        shift = (v_keystone / 100.0) * max_shift_w
        tl_x += shift
        tr_x -= shift
    elif v_keystone < 0:
        shift = (-v_keystone / 100.0) * max_shift_w
        bl_x += shift
        br_x -= shift
        
    if h_keystone > 0:
        shift = (h_keystone / 100.0) * max_shift_h
        tl_y += shift
        bl_y -= shift
    elif h_keystone < 0:
        shift = (-h_keystone / 100.0) * max_shift_h
        tr_y += shift
        br_y -= shift
        
    src_pts = np.float32([[0, 0], [w-1, 0], [0, h-1], [w-1, h-1]])
    dst_pts = np.float32([[tl_x, tl_y], [tr_x, tr_y], [bl_x, bl_y], [br_x, br_y]])
    
    M_warp = cv2.getPerspectiveTransform(src_pts, dst_pts)
    img = cv2.warpPerspective(img, M_warp, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0,0,0))
    
    # 2. Rotation
    if rotate != 0.0:
        center = (w // 2, h // 2)
        M_rot = cv2.getRotationMatrix2D(center, rotate, 1.0)
        img = cv2.warpAffine(img, M_rot, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0,0,0))
        
    # 3. Crop
    x1 = int(w * crop_l / 100.0)
    x2 = int(w * crop_r / 100.0)
    y1 = int(h * crop_t / 100.0)
    y2 = int(h * crop_b / 100.0)
    x1 = max(0, min(x1, w - 10))
    x2 = max(x1 + 10, min(x2, w))
    y1 = max(0, min(y1, h - 10))
    y2 = max(y1 + 10, min(y2, h))
    img = img[y1:y2, x1:x2]
    
    # 4. Resize
    if resize_w is not None and resize_h is not None:
        img = cv2.resize(img, (resize_w, resize_h), interpolation=cv2.INTER_AREA)
        
    return img

def apply_luminosity_grain(img, intensity, grain_type="midtone", noise_texture=None):
    if intensity <= 0: return img
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    
    if noise_texture is not None and noise_texture.shape[0] >= h and noise_texture.shape[1] >= w:
        raw_noise = noise_texture[:h, :w].copy() * (intensity * 0.5)
    else:
        raw_noise = np.random.normal(0, intensity * 0.5, img.shape).astype(np.float32)
    
    if grain_type == "midtone":
        weight = 4.0 * gray * (1.0 - gray)
    elif grain_type == "heavy":
        weight = 1.0 - (gray * 0.3)
    else:
        weight = gray * 0.4 + 0.1
        
    raw_noise = raw_noise * weight[..., None]
    return limit_and_cast(img.astype(np.float32) + raw_noise)

def apply_global_adjustments(img, exposure, contrast, saturation, warmth, tint, highlights, shadows, sharpness):
    img_32 = img.astype(np.float32)
    
    if exposure != 100.0:
        img_32 = img_32 * (exposure / 100.0)
        
    if warmth != 0.0 or tint != 0.0:
        b, g, r = cv2.split(img_32)
        r = r + (warmth * 0.3)
        b = b - (warmth * 0.3)
        g = g + (tint * 0.3)
        r = r - (tint * 0.15)
        b = b - (tint * 0.15)
        img_32 = cv2.merge([b, g, r])
        
    if highlights != 100.0 or shadows != 100.0:
        gray = cv2.cvtColor(limit_and_cast(img_32), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        high_mask = gray * gray
        shadow_mask = (1.0 - gray) * (1.0 - gray)
        
        b, g, r = cv2.split(img_32)
        h_factor = (highlights - 100.0) / 100.0 * 50.0
        s_factor = (shadows - 100.0) / 100.0 * 50.0
        
        b = b + (high_mask * h_factor) + (shadow_mask * s_factor)
        g = g + (high_mask * h_factor) + (shadow_mask * s_factor)
        r = r + (high_mask * h_factor) + (shadow_mask * s_factor)
        img_32 = cv2.merge([b, g, r])
        
    if contrast != 100.0:
        factor = contrast / 100.0
        img_32 = 127.5 + factor * (img_32 - 127.5)
        
    if saturation != 100.0:
        temp_bgr = limit_and_cast(img_32)
        hsv = cv2.cvtColor(temp_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:,:,1] = np.clip(hsv[:,:,1] * (saturation / 100.0), 0, 255)
        img_32 = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
        
    img_res = limit_and_cast(img_32)
    
    if sharpness > 0.0:
        blurred = cv2.GaussianBlur(img_res, (5, 5), 1.5)
        diff = img_res.astype(np.float32) - blurred.astype(np.float32)
        img_res = limit_and_cast(img_res.astype(np.float32) + sharpness * diff)
        
    return img_res

def compute_spline_lut(points):
    points = sorted(list(set(points)), key=lambda p: p[0])
    if len(points) < 2:
        return np.arange(256, dtype=np.uint8)
        
    n = len(points) - 1
    x = [float(p[0]) for p in points]
    y = [float(p[1]) for p in points]
    
    # Pad to cover boundaries
    if x[0] > 0:
        x.insert(0, 0.0)
        y.insert(0, y[0])
        n += 1
    if x[-1] < 255:
        x.append(255.0)
        y.append(y[-1])
        n += 1
        
    h = [x[i+1] - x[i] for i in range(n)]
    
    A = np.zeros((n+1, n+1))
    B = np.zeros(n+1)
    
    A[0, 0] = 1.0
    A[n, n] = 1.0
    
    for i in range(1, n):
        A[i, i-1] = h[i-1]
        A[i, i] = 2.0 * (h[i-1] + h[i])
        A[i, i+1] = h[i]
        B[i] = 3.0 * ((y[i+1] - y[i]) / h[i] - (y[i] - y[i-1]) / h[i-1])
        
    try:
        c = np.linalg.solve(A, B)
    except np.linalg.LinAlgError:
        lut = np.interp(np.arange(256), x, y)
        return np.clip(lut, 0, 255).astype(np.uint8)
        
    a = y
    b = []
    d = []
    for i in range(n):
        b.append((y[i+1] - y[i]) / h[i] - h[i] * (2.0 * c[i] + c[i+1]) / 3.0)
        d.append((c[i+1] - c[i]) / (3.0 * h[i]))
        
    vals = np.arange(256, dtype=np.float32)
    intervals = np.clip(np.searchsorted(x, vals) - 1, 0, n - 1)
    
    dx = vals - np.array(x)[intervals]
    a_arr = np.array(a)[intervals]
    b_arr = np.array(b)[intervals]
    c_arr = np.array(c)[intervals]
    d_arr = np.array(d)[intervals]
    
    lut = a_arr + b_arr * dx + c_arr * (dx**2) + d_arr * (dx**3)
    return np.clip(lut, 0, 255).astype(np.uint8)

def apply_3way_color_grading(img, shadows_offset, midtones_offset, highlights_offset):
    # offsets are (B, G, R) float vectors
    if shadows_offset == [0,0,0] and midtones_offset == [0,0,0] and highlights_offset == [0,0,0]:
        return img
    img_32 = img.astype(np.float32)
    b, g, r = cv2.split(img_32)
    
    y = 0.299 * r + 0.587 * g + 0.114 * b
    y_norm = y / 255.0
    
    ws = (1.0 - y_norm) ** 2.0
    wh = y_norm ** 2.0
    wm = 1.0 - ws - wh
    
    b += ws * shadows_offset[0] + wm * midtones_offset[0] + wh * highlights_offset[0]
    g += ws * shadows_offset[1] + wm * midtones_offset[1] + wh * highlights_offset[1]
    r += ws * shadows_offset[2] + wm * midtones_offset[2] + wh * highlights_offset[2]
    
    return limit_and_cast(cv2.merge([b, g, r]))

def apply_vignette(img, strength):
    if strength == 0:
        return img
    h, w = img.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    max_dist = np.sqrt(cx*cx + cy*cy)
    
    x = np.arange(w) - cx
    y = np.arange(h) - cy
    xx, yy = np.meshgrid(x, y)
    dist = np.sqrt(xx*xx + yy*yy) / max_dist
    
    factor = 1.0 + (strength / 100.0) * (dist ** 2.0)
    factor = np.clip(factor, 0.0, 2.0)
    
    img_32 = img.astype(np.float32)
    b, g, r = cv2.split(img_32)
    
    b *= factor
    g *= factor
    r *= factor
    
    return limit_and_cast(cv2.merge([b, g, r]))

def apply_calibration(img, r_sat, g_sat, b_sat):
    if r_sat == 0 and g_sat == 0 and b_sat == 0:
        return img
    img_32 = img.astype(np.float32)
    b, g, r = cv2.split(img_32)
    
    if r_sat != 0:
        diff = r - (g + b) * 0.5
        r = np.clip(r + (r_sat / 100.0) * diff, 0, 255)
    if g_sat != 0:
        diff = g - (r + b) * 0.5
        g = np.clip(g + (g_sat / 100.0) * diff, 0, 255)
    if b_sat != 0:
        diff = b - (r + g) * 0.5
        b = np.clip(b + (b_sat / 100.0) * diff, 0, 255)
        
    return limit_and_cast(cv2.merge([b, g, r]))

def draw_live_histogram(img_bgr, canvas_w=360, canvas_h=120):
    hist_b = cv2.calcHist([img_bgr], [0], None, [256], [0, 256])
    hist_g = cv2.calcHist([img_bgr], [1], None, [256], [0, 256])
    hist_r = cv2.calcHist([img_bgr], [2], None, [256], [0, 256])
    
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    hist_y = cv2.calcHist([gray], [0], None, [256], [0, 256])
    
    max_val = max(hist_b.max(), hist_g.max(), hist_r.max(), hist_y.max())
    if max_val == 0:
        max_val = 1.0
        
    hist_canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8) + 8
    
    for i in range(1, 4):
        x = int(canvas_w * i / 4)
        cv2.line(hist_canvas, (x, 0), (x, canvas_h), (20, 20, 20), 1)
        
    bin_w = float(canvas_w) / 256.0
    
    def draw_curve(hist, color):
        pts = []
        for i in range(256):
            x = int(i * bin_w)
            y = int(canvas_h - (hist[i, 0] / max_val) * (canvas_h - 10) - 2)
            pts.append([x, y])
        pts = np.array(pts, np.int32)
        cv2.polylines(hist_canvas, [pts], False, color, 1, cv2.LINE_AA)
        
    draw_curve(hist_b, (255, 64, 64))
    draw_curve(hist_g, (64, 255, 64))
    draw_curve(hist_r, (64, 64, 255))
    draw_curve(hist_y, (200, 200, 200))
    
    return hist_canvas

def draw_luma_waveform(img_bgr, canvas_w=360, canvas_h=120):
    small = cv2.resize(img_bgr, (160, 120), interpolation=cv2.INTER_AREA)
    
    # Calculate Rec. 709 luma explicitly: Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
    b, g, r = cv2.split(small.astype(np.float32))
    gray = 0.2126 * r + 0.7152 * g + 0.0722 * b
    
    # Base scope canvas (dark grey grid background)
    scope = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8) + 8
    
    scale_x = float(canvas_w - 1) / 159.0
    
    # Add 10px padding top/bottom to prevent clipping/cutoff
    pad_y = 10
    active_h = canvas_h - 2 * pad_y
    scale_y = float(active_h) / 255.0
    
    acc = np.zeros((canvas_h, canvas_w), dtype=np.float32)
    
    gh, gw = gray.shape
    cx = (np.arange(gw) * scale_x).astype(np.int32)
    cy = (canvas_h - pad_y - gray * scale_y).astype(np.int32)
    
    # Clip cy values to valid range
    cy = np.clip(cy, 0, canvas_h - 1)
    
    cx_grid = np.tile(cx, (gh, 1))
    np.add.at(acc, (cy, cx_grid), 1.0)
            
    # Column-wise normalization for clear density trace
    col_max = np.max(acc, axis=0, keepdims=True)
    col_max[col_max == 0] = 1.0
    acc = acc / col_max
        
    glow = cv2.GaussianBlur(acc, (5, 5), 1.0)
    
    scope_g = (glow * 220.0).astype(np.uint8)
    scope_r = (glow * 30.0).astype(np.uint8)
    scope_b = (glow * 100.0).astype(np.uint8)
    
    merged_glow = cv2.merge([scope_b, scope_g, scope_r])
    scope = cv2.add(scope, merged_glow)
    
    # Draw horizontal percentage lines (0%, 25%, 50%, 75%, 100%) and labels inside active area
    for pct in [0, 25, 50, 75, 100]:
        y_pos = int(canvas_h - pad_y - (pct / 100.0) * active_h)
        # Draw dotted/faint reference grid lines
        cv2.line(scope, (0, y_pos), (canvas_w, y_pos), (35, 35, 35), 1)
        # Small text label for percentage scale (offset slightly for clean centering)
        cv2.putText(scope, f"{pct}", (canvas_w - 25, y_pos + 3), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.25, (85, 85, 85), 1, cv2.LINE_AA)
                    
    return scope

def run_provia(img, exp, sat):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * (sat / 100.0) * 1.05, 0, 255)
    bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    b, g, r = cv2.split(bgr)
    return limit_and_cast(cv2.merge([b * (exp/100.0) * 1.04, g * (exp/100.0), r * (exp/100.0)]))

def run_velvia(img, contrast_slope, saturation_boost):
    img_32 = img.astype(np.float32) / 255.0
    curve = 1.0 / (1.0 + np.exp(-contrast_slope * (img_32 - 0.5)))
    hsv = cv2.cvtColor((curve * 255.0).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * saturation_boost, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

def run_astia(img, soft_gamma, skin_warmth):
    b, g, r = cv2.split(img.astype(np.float32))
    return limit_and_cast(cv2.merge([b ** 0.98, g ** 1.02, r ** soft_gamma + skin_warmth]))

def run_classic_chrome(img, shadow_crush, desat_rate):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * (desat_rate / 100.0), 0, 255)
    b, g, r = cv2.split(cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32))
    return limit_and_cast(cv2.merge([255.0*(b/255.0)**shadow_crush, 255.0*(g/255.0)**shadow_crush, 255.0*(r/255.0)**shadow_crush]))

def run_kodachrome(img, yellow_gamma, red_push):
    b, g, r = cv2.split(img.astype(np.float32))
    return limit_and_cast(cv2.merge([b ** 0.88 - 10, g ** yellow_gamma, r ** 1.12 + red_push]))

def run_agfa_vista(img, red_saturation, exposure):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * 1.15, 0, 255)
    b, g, r = cv2.split(cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32))
    return limit_and_cast(cv2.merge([b*(exposure/100.0), g*(exposure/100.0), r*red_saturation*(exposure/100.0)]))

def run_superia(img, green_gamma, emerald_layer):
    b, g, r = cv2.split(img.astype(np.float32))
    return limit_and_cast(cv2.merge([b ** 1.02, g ** green_gamma + emerald_layer, r ** 1.08]))

def run_ilford_hp5(img, shadow_punch, highlight_gamma):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mono = limit_and_cast((255.0 * (gray / 255.0) ** highlight_gamma) * shadow_punch)
    return cv2.merge([mono, mono, mono])

def run_vision3(img, shadow_teal, highlight_amber):
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    y, cr, cb = cv2.split(ycrcb)
    mask_dark = (255.0 - y) / 255.0
    mask_bright = y / 255.0
    cr = cr - (mask_dark * (shadow_teal * 0.5)) + (mask_bright * (highlight_amber * 0.7))
    cb = cb + (mask_dark * shadow_teal) - (mask_bright * (highlight_amber * 0.4))
    return cv2.cvtColor(cv2.merge([y, cr, cb]).astype(np.uint8), cv2.COLOR_YCrCb2BGR)

def run_ektachrome(img, blue_pop, contrast):
    b, g, r = cv2.split(img.astype(np.float32))
    img_32 = cv2.merge([b * blue_pop, g, r]) / 255.0
    return limit_and_cast((1.0 / (1.0 + np.exp(-contrast * (img_32 - 0.5)))) * 255.0)

def run_fujicolor_c200(img, green_shadows, warmth):
    b, g, r = cv2.split(img.astype(np.float32))
    return limit_and_cast(cv2.merge([b * 0.95, g ** 0.98 + green_shadows, r * 1.04 + warmth]))

def run_portra(img, pastel_gamma, skin_tint):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * 0.85, 0, 255)
    b, g, r = cv2.split(cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32))
    return limit_and_cast(cv2.merge([b * 0.96, g * pastel_gamma, r * pastel_gamma + skin_tint]))

def run_halation(img, threshold, size, intensity):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY)
    k = int(size) if int(size) % 2 != 0 else int(size) + 1
    bloom = cv2.GaussianBlur(thresh, (k, k), 0).astype(np.float32) / 255.0
    return limit_and_cast(img.astype(np.float32) + cv2.merge([bloom*(intensity*0.4), bloom*(intensity*0.2), bloom*intensity]))

def run_xenon_90s(img, curve, saturation):
    img_32 = img.astype(np.float32) / 255.0
    hsv = cv2.cvtColor((1.0 / (1.0 + np.exp(-curve * (img_32 - 0.5))) * 255.0).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * saturation, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

def run_pacific_cold(img, blue, green, desat):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * (desat / 100.0), 0, 255)
    b, g, r = cv2.split(cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32))
    return limit_and_cast(cv2.merge([b + blue, g + green, r - (blue // 2)]))

FILTER_REGISTRY = {
    "PROVIA STANDARD (CCD)": { "engine": run_provia, "grain_type": "fine", "controls": [("Sensor Exposure Val", 60, 140, 100, "float"), ("Chroma Saturation", 70, 140, 100, "float"), ("Micro Sensor Noise", 0, 15, 3, "int")] },
    "VELVIA VIVID (SLIDE)": { "engine": run_velvia, "grain_type": "fine", "controls": [("Contrast Curve Slope", 4.0, 9.0, 6.2, "float"), ("Velvia Saturation Pop", 1.1, 1.7, 1.35, "float"), ("Slide Fine Grain", 0, 20, 4, "int")] },
    "ASTIA SOFT (PORTRAIT)": { "engine": run_astia, "grain_type": "fine", "controls": [("Highlights Gamma", 0.8, 1.4, 1.05, "float"), ("Skin Warmth Coefficient", 0, 25, 8, "int"), ("Portrait Micro Grain", 0, 15, 2, "int")] },
    "CLASSIC CHROME (PRINT)": { "engine": run_classic_chrome, "grain_type": "midtone", "controls": [("Shadow Crush Exponential", 1.0, 1.6, 1.25, "float"), ("Chroma Suppression", 40, 95, 65, "int"), ("Print Hard Texture", 0, 25, 8, "int")] },
    "KODACHROME 64 (RETRO)": { "engine": run_kodachrome, "grain_type": "heavy", "controls": [("Yellow Channel Gamma", 0.8, 1.4, 1.10, "float"), ("Warm Red Push Vector", 0, 20, 8, "int"), ("Vintage Slide Grain", 0, 35, 14, "int")] },
    "AGFA VISTA 400 (COLOR)": { "engine": run_agfa_vista, "grain_type": "heavy", "controls": [("Agfa Red Saturation", 1.0, 1.5, 1.25, "float"), ("Negative Print Exposure", 70, 130, 100, "float"), ("Emulsion Silver Grain", 0, 35, 12, "int")] },
    "SUPERIA X-TRA (LAYER4)": { "engine": run_superia, "grain_type": "fine", "controls": [("Green Channel Gamma", 0.8, 1.3, 0.92, "float"), ("Emerald Layer Offset", 0, 20, 6, "int"), ("Superia Fine Grain", 0, 20, 6, "int")] },
    "ILFORD HP5 PLUS (B&W)": { "engine": run_ilford_hp5, "grain_type": "heavy", "controls": [("Shadow Contrast Scale", 0.8, 1.4, 1.05, "float"), ("Highlight Latitude Gamma", 0.7, 1.3, 0.95, "float"), ("Pan Metallic Grain", 0, 40, 18, "int")] },
    "KODAK VISION3 (CINE)": { "engine": run_vision3, "grain_type": "fine", "controls": [("Shadow Teal Injection", 0, 35, 16, "int"), ("Highlight Amber Bleed", 0, 30, 12, "int"), ("Motion Picture Grain", 0, 25, 7, "int")] },
    "EKTACHROME E100 (DIAL)": { "engine": run_ektachrome, "grain_type": "fine", "controls": [("Cobalt Blue Multiplier", 1.0, 1.4, 1.12, "float"), ("Contrast Threshold Slope", 4.0, 8.5, 5.8, "float"), ("Fine Saturated Grain", 0, 20, 4, "int")] },
    "FUJICOLOR C200 (WARM)": { "engine": run_fujicolor_c200, "grain_type": "heavy", "controls": [("Green Shadow Bias", 0, 15, 6, "int"), ("Highlight Warmth Push", 0, 20, 8, "int"), ("Nostalgic Paper Grain", 0, 30, 10, "int")] },
    "KODAK PORTRA 400 (SOFT)": { "engine": run_portra, "grain_type": "fine", "controls": [("Pastel Midtone Gamma", 0.9, 1.3, 1.08, "float"), ("Organic Skin Warming", 0, 15, 5, "int"), ("Micro Portrait Grain", 0, 15, 3, "int")] },
    "LOFI HALATION (GLARE)": { "engine": run_halation, "grain_type": "midtone", "controls": [("Hotspot Cutoff Threshold", 160, 245, 205, "int"), ("Glow Blur Radius Pixels", 11, 55, 27, "int"), ("Bulb Overexposure Power", 5, 45, 25, "int"), ("Scanner Line Base Noise", 0, 35, 12, "int")] },
    "90S XENON DIRECT FLASH": { "engine": run_xenon_90s, "grain_type": "heavy", "controls": [("Sigmoid Flash Contrast", 4.0, 9.5, 6.5, "float"), ("Flash Saturation Pop", 1.0, 1.7, 1.25, "float"), ("Direct Shadow Silver Grain", 0, 40, 15, "int")] },
    "PACIFIC MISTY COLD": { "engine": run_pacific_cold, "grain_type": "midtone", "controls": [("Misty Blue Shift Vector", 0, 45, 22, "int"), ("Deep Forest Green Shift", 0, 35, 14, "int"), ("Chroma Desaturation", 25, 95, 50, "int"), ("Damp Atmospheric Grain", 0, 30, 8, "int")] }
}

PROFILE_DESCRIPTIONS = {
    "PROVIA STANDARD (CCD)": "Standard color profile with CCD sensor emulation, fine grain characteristics, and baseline exposure response.",
    "VELVIA VIVID (SLIDE)": "High contrast landscape slide emulation with saturated color reproduction and fine silver halide grain.",
    "ASTIA SOFT (PORTRAIT)": "Soft portrait profile with gentle highlight roll-off, optimized skin warmth, and low-contrast fine grain.",
    "CLASSIC CHROME (PRINT)": "Documentary-style print film emulation with crushed shadows, low saturation, and pronounced print texture.",
    "KODACHROME 64 (RETRO)": "Warm vintage color slide look with high yellow saturation, warm red bias, and organic heavy grain.",
    "AGFA VISTA 400 (COLOR)": "Vibrant color negative emulation with saturated red channels, high latitude, and heavy emulsion grain.",
    "SUPERIA X-TRA (LAYER4)": "Four-layer color negative emulation with emerald green response and balanced fine grain.",
    "ILFORD HP5 PLUS (B&W)": "High-contrast panchromatic monochrome print emulation with shadow latitude and metallic silver grain.",
    "KODAK VISION3 (CINE)": "Modern cinematic film stock with dark-teal shadows, amber-bleed highlights, and fine motion picture grain.",
    "EKTACHROME E100 (DIAL)": "E6 slide film emulation with cobalt blue saturation, strong contrast, and fine dynamic range.",
    "FUJICOLOR C200 (WARM)": "Warm consumer negative stock with green shadow bias, highlight warming, and heavy nostalgic grain.",
    "KODAK PORTRA 400 (SOFT)": "Professional portrait film profile with pastel midtones, warm skin tone bias, and organic micro-grain.",
    "LOFI HALATION (GLARE)": "Creative style simulating red highlight halation glare, analog bulb overexposure, and scanning line noise.",
    "90S XENON DIRECT FLASH": "High-contrast direct flash style simulating harsh xenon light exposure, direct shadow drop-off, and silver print grain.",
    "PACIFIC MISTY COLD": "Moody cold-tone atmospheric look with deep forest greens, cyan-blue shadows, and damp mist grain."
}

# ==========================================
# 2. HARDWARE WORKSTATION OPERATING VIEW
# ==========================================
class UltimateHardwareStudio:
    def __init__(self, root):
        self.root = root
        self.root.title("LATENT // THREE-STAGE LAB PIPELINE")
        try:
            import os
            import sys
            # Check local file or PyInstaller bundled file
            base_dir = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(base_dir, "app_logo.png")
            if os.path.exists(icon_path):
                icon_img = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, icon_img)
        except Exception:
            pass
        self.root.attributes('-fullscreen', True)  # True borderless fullscreen
        self.root.configure(bg="#020202")
        self.root.update_idletasks()
        # ESC = exit fullscreen (shows taskbar/title bar); Ctrl+Q = quit
        self.root.bind('<Escape>', self._toggle_fullscreen)
        self.root.bind('<Control-q>', lambda e: self.root.destroy())
        self._is_fullscreen = True

        # ---- Layout: dynamic scaling based on 1920x1080 design ----
        SW = self.root.winfo_screenwidth()
        SH = self.root.winfo_screenheight()
        self.SCALE = SW / 1920.0
        
        self.VP_X = int(20 * self.SCALE)
        self.VP_Y = int(20 * self.SCALE)
        self.VP_W = int(1240 * self.SCALE)
        self.SCROLL_W = int(20 * self.SCALE)
        self.PANEL_W = int(620 * self.SCALE)
        self.SCR_X = int(1280 * self.SCALE)
        self.CTRL_X = int(1280 * self.SCALE)
        self.VP_H = int(1040 * self.SCALE)
        self.SH = int(SH)
        
        # Explorer cell grid layout (scaled relative to viewport canvas origin at x=20, y=20)
        self.EX_MARGIN = int(5.2 * self.SCALE)
        self.EX_CELL = int(240 * self.SCALE)
        self.EX_ROW_H = int(246.3 * self.SCALE)
        self.EX_COL_X = [int((5.17 + i * 246.9) * self.SCALE) for i in range(5)]
        
        # Grid cell layout (scaled relative to viewport canvas origin at x=20, y=20: 5 col x 3 rows)
        self.GR_CELL_W = int(247.77 * self.SCALE)
        self.GR_CELL_H = int(346.66 * self.SCALE)
        self.GR_COL_X = [int(i * 247.77 * self.SCALE) for i in range(5)]
        self.GR_ROW_Y = [int(r * 346.66 * self.SCALE) for r in range(3)]
        # ----------------------------------------------------------

        self.raw_source = None
        self.proxy_source = None
        self.geom_raw_source = None
        self.geom_proxy_source = None
        
        # Geometry parameter vars
        self.geom_crop_l = tk.DoubleVar(value=0.0)
        self.geom_crop_r = tk.DoubleVar(value=100.0)
        self.geom_crop_t = tk.DoubleVar(value=0.0)
        self.geom_crop_b = tk.DoubleVar(value=100.0)
        self.geom_rotate = tk.DoubleVar(value=0.0)
        self.geom_v_keystone = tk.DoubleVar(value=0.0)
        self.geom_h_keystone = tk.DoubleVar(value=0.0)
        self.geom_resize_w_val = tk.StringVar(value="")
        self.geom_resize_h_val = tk.StringVar(value="")
        
        self.active_filename = ""
        self.current_directory = os.path.abspath(".")
        self.render_lock = threading.Lock()
        
        # Operational State flags: 'EXPLORER', 'GRID', or 'WORKBENCH'
        self.system_state = 'EXPLORER'
        self.last_click_time = 0
        self.selected_grid_profile = "PROVIA STANDARD (CCD)"
        self.explorer_selected_file = ""
        self.explorer_hovered_file = ""
        self.grid_hovered_profile = ""
        
        # Undo/Redo Stacks
        self.undo_stack = []
        self.redo_stack = []

        # Initialize Filter Parameters dictionary with defaults
        self.filter_parameters = {}
        for p_name, p_data in FILTER_REGISTRY.items():
            self.filter_parameters[p_name] = {}
            for name, mn, mx, df, var_type in p_data["controls"]:
                self.filter_parameters[p_name][name] = df

        # Color Toning & Correction States
        self.global_exposure = tk.DoubleVar(value=100.0)
        self.global_contrast = tk.DoubleVar(value=100.0)
        self.global_saturation = tk.DoubleVar(value=100.0)
        self.global_warmth = tk.DoubleVar(value=0.0)
        self.global_tint = tk.DoubleVar(value=0.0)
        self.global_highlights = tk.DoubleVar(value=100.0)
        self.global_shadows = tk.DoubleVar(value=100.0)
        self.global_sharpness = tk.DoubleVar(value=0.0)
        self.global_vignette = tk.DoubleVar(value=0.0)

        # Tone Curve Points (defaults to linear diagonal)
        self.curve_points = [(0, 0), (255, 255)]
        self.selected_point_idx = None

        # 3-Way Color Wheels BGR Offsets and Position coordinates
        self.shadow_tint = [0.0, 0.0, 0.0]
        self.midtone_tint = [0.0, 0.0, 0.0]
        self.highlight_tint = [0.0, 0.0, 0.0]
        self.shadow_wheel_pos = (0.0, 0.0)
        self.midtone_wheel_pos = (0.0, 0.0)
        self.highlight_wheel_pos = (0.0, 0.0)

        # Pre-generate color wheel PIL image for three-way color grading wheels (radius 55)
        self.wheel_photo = self.pregenerate_color_wheel(55)
        self.noise_texture = np.random.normal(0, 1.0, (1200, 1200, 3)).astype(np.float32)

        # Camera Calibration Saturation Variables
        self.cal_red = tk.DoubleVar(value=0.0)
        self.cal_green = tk.DoubleVar(value=0.0)
        self.cal_blue = tk.DoubleVar(value=0.0)

        # Interactive Scope Mode & Comparison States
        self.scope_mode = 'HISTOGRAM'
        self.show_before_compare = False

        # File explorer cache
        self.explorer_files = []
        self.update_explorer_files()

        # Viewport Zoom & Drag Coordinate Variables
        self.zoom_factor = 1.0
        self.zoom_mode = False
        self.is_dragging_zoom = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_current_x = 0
        self.drag_current_y = 0
        self.zoom_x1 = 0
        self.zoom_y1 = 0
        self.zoom_x2 = 0
        self.zoom_y2 = 0
        self.pan_start_x = 0
        self.pan_start_y = 0

        # Caching & Locking Infrastructure
        self.thumbnail_cache = {}
        self.grid_thumbnail_cache = {}
        self.thumbnail_load_lock = threading.Lock()

        # Left Viewport Box (Scrollable) — sized from screen dimensions
        self.viewport_frame = tk.Frame(root, bg="#020202", bd=0, highlightthickness=0)
        self.viewport_frame.place(x=self.VP_X, y=self.VP_Y, width=self.VP_W, height=self.VP_H)
        
        self.viewport_canvas = tk.Canvas(self.viewport_frame, bg="#020202", highlightthickness=0)
        self.viewport_scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.viewport_canvas.yview)
        self.viewport_scrollbar.place(x=0, y=0, width=int(20 * self.SCALE), height=self.SH)
        
        self.viewport_h_scrollbar = ttk.Scrollbar(self.root, orient="horizontal", command=self.viewport_canvas.xview)
        self.viewport_h_scrollbar.place(x=int(20 * self.SCALE), y=self.SH - int(20 * self.SCALE), width=int(1260 * self.SCALE), height=int(20 * self.SCALE))
        
        self.viewport_corner_square = tk.Frame(self.root, bg="#939598", highlightthickness=0)
        
        self.viewport_canvas.configure(yscrollcommand=self.viewport_scrollbar.set, xscrollcommand=self.viewport_h_scrollbar.set)
        self.viewport_canvas.pack(side="left", fill="both", expand=True)
        
        self.view_label = tk.Label(self.viewport_canvas, bg="#020202", borderwidth=0, highlightthickness=0)
        self.canvas_window_id = self.viewport_canvas.create_window((0, 0), window=self.view_label, anchor="nw")
        
        # Configure viewport gesture bindings
        self.view_label.bind("<Button-1>", self.on_viewport_click)
        self.view_label.bind("<ButtonRelease-1>", self.on_viewport_release)
        self.view_label.bind("<B1-Motion>", self.on_viewport_drag)
        self.view_label.bind("<Button-3>", self.on_viewport_right_click)
        self.view_label.bind("<B3-Motion>", self.on_viewport_pan)
        self.view_label.bind("<Motion>", self.on_mouse_motion)
        self.view_label.bind("<Leave>", self.on_viewport_leave)
        
        # Bind Spacebar comparison keys
        self.root.bind("<KeyPress-space>", self.on_compare_press)
        self.root.bind("<KeyRelease-space>", self.on_compare_release)

        # Right Control Panel Layout Column — anchored to right of scrollbar
        self.control_frame = tk.Frame(root, bg="#080808")
        self.control_frame.place(x=self.CTRL_X, y=self.VP_Y, width=self.PANEL_W, height=self.VP_H)

        # Dynamic Scope Display (static at the top)
        self.hist_canvas = tk.Canvas(self.control_frame, bg="#080808", highlightthickness=1, relief="solid", bd=1, highlightbackground="#222222")
        self.hist_canvas.bind("<Button-1>", self.toggle_scope_mode)

        self.scope_lbl = tk.Label(self.control_frame, text="[ SCOPE MODE: HISTOGRAM // CLICK TO TOGGLE ]", fg="#555555", bg="#080808", font=("Courier New", max(8, int(8 * self.SCALE)), "bold"))

        # Dynamic Status Header Line
        self.meta_lbl = tk.Label(self.control_frame, text="REGISTRY STATUS // IDLE", fg="#555555", bg="#080808", font=("Courier New", max(8, int(8 * self.SCALE)), "bold"), anchor="w")

        # Pipeline Command Center Control Switches
        self.nav_btn = tk.Button(self.control_frame, text="BACK", bg="#121212", fg="#888888",
                                 activebackground="#333333", activeforeground="#ffffff",
                                 font=("Courier New", max(8, int(11 * self.SCALE)), "bold"),
                                 bd=1, relief="solid", cursor="hand2", command=self.regress_to_explorer)
                                 
        self.browse_dir_btn = tk.Button(self.control_frame, text="NAVIGATE", bg="#121212", fg="#888888",
                                        activebackground="#333333", activeforeground="#ffffff",
                                        font=("Courier New", max(8, int(11 * self.SCALE)), "bold"),
                                        bd=1, relief="solid", cursor="hand2", command=self.select_custom_directory)

        # Metadata Descriptor Text Shield Box Frame
        self.info_panel_lbl = tk.Label(self.control_frame, text="NODE READOUT // IDLE", fg="#aaaaaa", bg="#080808",
                                       font=("Courier New", max(8, int(10 * self.SCALE))), bd=1, relief="solid", justify="left", anchor="nw")

        # Scrollable Configuration Control Sliders Node
        self.canvas_rack = tk.Canvas(self.control_frame, bg="#080808", highlightthickness=0)
        self.rack_scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas_rack.yview)
        self.scrollable_inner_rack = tk.Frame(self.canvas_rack, bg="#080808")
        
        self.scrollable_inner_rack.bind("<Configure>", lambda e: self.canvas_rack.configure(scrollregion=self.canvas_rack.bbox("all")))
        self.rack_window_id = self.canvas_rack.create_window((0, 0), window=self.scrollable_inner_rack, anchor="nw", width=int(580 * self.SCALE))
        self.canvas_rack.bind("<Configure>", lambda e: self.canvas_rack.itemconfig(self.rack_window_id, width=e.width))
        self.canvas_rack.configure(yscrollcommand=self.rack_scrollbar.set)

        # Compare button: placed on root, bottom-right of viewport in WORKBENCH
        self.compare_btn = tk.Button(self.root, text="◧", bg="#0a0a0a", fg="#666666",
                                     activebackground="#1a1a1a", activeforeground="#ffffff",
                                     font=("Courier New", max(8, int(11 * self.SCALE))), bd=0, relief="flat",
                                     cursor="hand2")
        self.compare_btn.bind("<ButtonPress-1>", self.on_compare_press)
        self.compare_btn.bind("<ButtonRelease-1>", self.on_compare_release)

        # Workbench Right Sidebar Header Bar (parent: scrollable_inner_rack)
        self.workbench_header_frame = tk.Frame(self.scrollable_inner_rack, bg="#080808", height=int(40 * self.SCALE))
        self.workbench_header_frame.pack_propagate(False)
        self.workbench_header_frame.pack(fill="x", pady=(0, 10 * self.SCALE))
        
        self.wb_back_btn = tk.Button(self.workbench_header_frame, text="BACK", bg="#121212", fg="#888888",
                                     activebackground="#333333", activeforeground="#ffffff",
                                     font=("Courier New", max(8, int(11 * self.SCALE)), "bold"),
                                     bd=1, relief="solid", cursor="hand2", command=self.regress_to_explorer)
        self.wb_back_btn.place(x=5 * self.SCALE, y=5 * self.SCALE, width=100 * self.SCALE, height=30 * self.SCALE)
        
        self.save_btn = tk.Button(self.workbench_header_frame, text="SAVE", bg="#121212", fg="#fff200",
                                  activebackground="#fff200", activeforeground="#080808",
                                  font=("Courier New", max(8, int(11 * self.SCALE)), "bold"),
                                  bd=1, relief="solid", cursor="hand2", command=self.execute_purity_export)
        self.save_btn.place(x=475 * self.SCALE, y=5 * self.SCALE, width=100 * self.SCALE, height=30 * self.SCALE)
        
        self.profile_name_lbl = tk.Label(self.workbench_header_frame, text="", bg="#080808", fg="#aaaaaa",
                                         font=("Courier New", max(8, int(11 * self.SCALE)), "bold"))
        self.profile_name_lbl.place(x=110 * self.SCALE, y=5 * self.SCALE, width=355 * self.SCALE, height=30 * self.SCALE)

        # Workbench Fixed Filter Sliders Frame (parent: scrollable_inner_rack)
        self.filter_sliders_frame = tk.Frame(self.scrollable_inner_rack, bg="#080808", bd=1, relief="solid", highlightthickness=0, height=int(183 * self.SCALE))
        self.filter_sliders_frame.pack_propagate(False)
        self.filter_sliders_frame.pack(fill="x", pady=10 * self.SCALE)

        # Workbench Geometry Transform tab panel button (parent: scrollable_inner_rack via a wrapper frame to maintain exact pixel height)
        self.geom_tab_btn_frame = tk.Frame(self.scrollable_inner_rack, bg="#080808", height=int(40 * self.SCALE))
        self.geom_tab_btn_frame.pack_propagate(False)
        self.geom_tab_btn_frame.pack(fill="x", pady=10 * self.SCALE)
        
        self.geom_tab_btn_panel = tk.Button(self.geom_tab_btn_frame, text="CROP/ROTATE/RESIZE/WRAP", bg="#121212", fg="#888888",
                                            activebackground="#333333", activeforeground="#ffffff",
                                            font=("Courier New", max(8, int(10 * self.SCALE)), "bold"),
                                            bd=1, relief="solid", cursor="hand2", command=self.open_geometry_window)
        self.geom_tab_btn_panel.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        
        # Scrollable Tuning Container (for adjustments, wheels, calibration)
        self.scrollable_tuning_container = tk.Frame(self.scrollable_inner_rack, bg="#080808")
        self.scrollable_tuning_container.pack(fill="x", pady=10 * self.SCALE)
        
        self.profile_keys = list(FILTER_REGISTRY.keys())

        # Local context-specific MouseWheel bindings (prevents scrolling slider menu from zooming)
        self.viewport_canvas.bind("<MouseWheel>", self.on_explorer_mousewheel)
        self.view_label.bind("<MouseWheel>", self.on_viewport_mousewheel)
        self.canvas_rack.bind("<MouseWheel>", self.on_rack_mousewheel)
        self.scrollable_inner_rack.bind("<MouseWheel>", self.on_rack_mousewheel)
        
        # Undo/Redo key bindings
        self.root.bind("<Control-z>", self.perform_undo)
        self.root.bind("<Control-Z>", self.perform_redo)
        self.root.bind("<Control-Shift-z>", self.perform_redo)
        self.root.bind("<Control-Shift-Z>", self.perform_redo)
        self.root.bind("<Control-y>", self.perform_redo)
        self.root.bind("<Control-Y>", self.perform_redo)

        self.render_system_view()

    def _toggle_fullscreen(self, event=None):
        """ESC toggles between true fullscreen and normal windowed mode."""
        self._is_fullscreen = not self._is_fullscreen
        self.root.attributes('-fullscreen', self._is_fullscreen)

    def capture_state(self):
        return {
            "selected_profile": self.selected_grid_profile,
            "filter_parameters": copy.deepcopy(self.filter_parameters),
            
            "exposure": self.global_exposure.get(),
            "contrast": self.global_contrast.get(),
            "saturation": self.global_saturation.get(),
            "warmth": self.global_warmth.get(),
            "tint": self.global_tint.get(),
            "highlights": self.global_highlights.get(),
            "shadows": self.global_shadows.get(),
            "sharpness": self.global_sharpness.get(),
            "vignette": self.global_vignette.get(),
            
            "cal_red": self.cal_red.get(),
            "cal_green": self.cal_green.get(),
            "cal_blue": self.cal_blue.get(),
            
            "crop_l": self.geom_crop_l.get(),
            "crop_r": self.geom_crop_r.get(),
            "crop_t": self.geom_crop_t.get(),
            "crop_b": self.geom_crop_b.get(),
            "rotate": self.geom_rotate.get(),
            "v_keystone": self.geom_v_keystone.get(),
            "h_keystone": self.geom_h_keystone.get(),
            "resize_w": self.geom_resize_w_val.get(),
            "resize_h": self.geom_resize_h_val.get(),
            
            "shadow_wheel_pos": self.shadow_wheel_pos,
            "midtone_wheel_pos": self.midtone_wheel_pos,
            "highlight_wheel_pos": self.highlight_wheel_pos,
        }

    def restore_state(self, state):
        self.selected_grid_profile = state["selected_profile"]
        self.filter_parameters = copy.deepcopy(state["filter_parameters"])
        
        self.global_exposure.set(state["exposure"])
        self.global_contrast.set(state["contrast"])
        self.global_saturation.set(state["saturation"])
        self.global_warmth.set(state["warmth"])
        self.global_tint.set(state["tint"])
        self.global_highlights.set(state["highlights"])
        self.global_shadows.set(state["shadows"])
        self.global_sharpness.set(state["sharpness"])
        self.global_vignette.set(state["vignette"])
        
        self.cal_red.set(state["cal_red"])
        self.cal_green.set(state["cal_green"])
        self.cal_blue.set(state["cal_blue"])
        
        self.geom_crop_l.set(state["crop_l"])
        self.geom_crop_r.set(state["crop_r"])
        self.geom_crop_t.set(state["crop_t"])
        self.geom_crop_b.set(state["crop_b"])
        self.geom_rotate.set(state["rotate"])
        self.geom_v_keystone.set(state["v_keystone"])
        self.geom_h_keystone.set(state["h_keystone"])
        self.geom_resize_w_val.set(state["resize_w"])
        self.geom_resize_h_val.set(state["resize_h"])
        
        self.shadow_wheel_pos = state["shadow_wheel_pos"]
        self.midtone_wheel_pos = state["midtone_wheel_pos"]
        self.highlight_wheel_pos = state["highlight_wheel_pos"]
        
        self.update_tints_from_positions()
        
        if self.raw_source is not None:
            r_w = int(self.geom_resize_w_val.get()) if self.geom_resize_w_val.get().isdigit() else None
            r_h = int(self.geom_resize_h_val.get()) if self.geom_resize_h_val.get().isdigit() else None
            
            self.geom_raw_source = apply_geometry_transforms(
                self.raw_source,
                self.geom_crop_l.get(),
                self.geom_crop_r.get(),
                self.geom_crop_t.get(),
                self.geom_crop_b.get(),
                self.geom_rotate.get(),
                self.geom_v_keystone.get(),
                self.geom_h_keystone.get(),
                r_w, r_h
            )
            
            if r_w is not None and r_h is not None:
                h_raw, w_raw = self.raw_source.shape[:2]
                scale = 1200.0 / max(w_raw, h_raw)
                pr_w = int(r_w * scale)
                pr_h = int(r_h * scale)
            else:
                pr_w, pr_h = None, None
                
            self.geom_proxy_source = apply_geometry_transforms(
                self.proxy_source,
                self.geom_crop_l.get(),
                self.geom_crop_r.get(),
                self.geom_crop_t.get(),
                self.geom_crop_b.get(),
                self.geom_rotate.get(),
                self.geom_v_keystone.get(),
                self.geom_h_keystone.get(),
                pr_w, pr_h
            )
            
        self.zoom_mode = False
        if self.system_state == 'WORKBENCH':
            self.build_calibration_sliders()
        else:
            self.trigger_live_recalculation()

    def push_undo(self):
        self.undo_stack.append(self.capture_state())
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def perform_undo(self, event=None):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.capture_state())
        self.restore_state(self.undo_stack.pop())

    def perform_redo(self, event=None):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.capture_state())
        self.restore_state(self.redo_stack.pop())

    def update_explorer_files(self):
        try:
            files = [f for f in os.listdir(self.current_directory) if f.lower().endswith(('.jpg', '.jpeg', '.png')) and not f.startswith("EXPORT_")]
        except Exception:
            files = []
        self.explorer_files = files[:100]

    def pregenerate_color_wheel(self, radius):
        size = radius * 2
        img = np.zeros((size, size, 4), dtype=np.uint8)
        for y in range(size):
            for x in range(size):
                dy = y - radius
                dx = x - radius
                r = np.sqrt(dx*dx + dy*dy)
                if r <= radius:
                    angle = np.arctan2(dy, dx)
                    hue = int(((angle + np.pi) / (2.0 * np.pi)) * 179.0)
                    sat = int((r / radius) * 255.0)
                    val = 200
                    hsv = np.array([[[hue, sat, val]]], dtype=np.uint8)
                    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)[0, 0]
                    img[y, x, :3] = rgb
                    img[y, x, 3] = 255
                else:
                    img[y, x, :] = [8, 8, 8, 0]
        return ImageTk.PhotoImage(image=Image.fromarray(img))

    def render_system_view(self):
        """Drives global interface architecture logic and tracks state transitions layout configurations."""
        # Unpack/unplace everything to avoid overlap/packing queue bugs
        self.hist_canvas.pack_forget()
        self.scope_lbl.pack_forget()
        self.meta_lbl.pack_forget()
        self.nav_btn.pack_forget()
        self.browse_dir_btn.pack_forget()
        self.info_panel_lbl.pack_forget()
        self.canvas_rack.pack_forget()
        self.rack_scrollbar.pack_forget()
        self.compare_btn.place_forget()
        self.save_btn.place_forget()
        
        self.hist_canvas.place_forget()
        self.scope_lbl.place_forget()
        self.meta_lbl.place_forget()
        self.nav_btn.place_forget()
        self.browse_dir_btn.place_forget()
        self.info_panel_lbl.place_forget()
        self.canvas_rack.place_forget()
        self.rack_scrollbar.place_forget()
        
        if hasattr(self, 'info_panel_border_frame'):
            self.info_panel_border_frame.place_forget()
        if hasattr(self, 'explorer_preview_frame'):
            self.explorer_preview_frame.place_forget()
        self.viewport_scrollbar.place_forget()
        self.viewport_h_scrollbar.place_forget()
        if hasattr(self, 'viewport_corner_square'):
            self.viewport_corner_square.place_forget()
        
        # Workbench layout cleanups
        self.workbench_header_frame.pack_forget()
        self.filter_sliders_frame.pack_forget()
        self.geom_tab_btn_frame.pack_forget()
        self.scrollable_tuning_container.pack_forget()
        self.workbench_header_frame.place_forget()
        self.filter_sliders_frame.place_forget()
        self.geom_tab_btn_frame.place_forget()
        self.geom_tab_btn_panel.place_forget()

        if self.system_state == 'EXPLORER':
            # Create frames if they don't exist
            if not hasattr(self, 'info_panel_border_frame'):
                self.info_panel_border_frame = tk.Frame(self.control_frame, bg="#080808", bd=1, relief="solid", highlightthickness=0, highlightbackground="#58595b")
            
            # Place elements using scaled layout coordinates from SVG
            self.info_panel_border_frame.place(x=40*self.SCALE, y=20*self.SCALE, width=580*self.SCALE, height=158*self.SCALE)
            self.info_panel_lbl.place(x=60*self.SCALE, y=35*self.SCALE, width=540*self.SCALE, height=128*self.SCALE)
            self.info_panel_lbl.config(bg="#080808", bd=0, relief="flat", anchor="nw")
            self.browse_dir_btn.place(x=40*self.SCALE, y=199*self.SCALE, width=580*self.SCALE, height=40*self.SCALE)
            self.info_panel_border_frame.lower()

            # Explorer Image Preview (Box 2)
            if not hasattr(self, 'explorer_preview_frame'):
                self.explorer_preview_frame = tk.Frame(self.control_frame, bg="#080808", bd=1, relief="solid", highlightthickness=0, highlightbackground="#58595b")
                self.explorer_preview_lbl = tk.Label(self.explorer_preview_frame, bg="#080808")
                self.explorer_preview_lbl.place(x=0, y=0, relwidth=1.0, relheight=0.92)
                self.explorer_preview_filename_lbl = tk.Label(self.explorer_preview_frame, bg="#080808", fg="#888888", font=("Courier New", max(8, int(8 * self.SCALE))))
                self.explorer_preview_filename_lbl.place(relx=0.03, rely=0.95, anchor="w")
                
            self.explorer_preview_frame.place(x=40*self.SCALE, y=259*self.SCALE, width=580*self.SCALE, height=802*self.SCALE)
            self.update_explorer_preview()

            self.viewport_canvas.pack_forget()
            self.viewport_canvas.pack(side="left", fill="both", expand=True)
            
            valid_files = self.explorer_files
            num_rows = int(np.ceil(len(valid_files) / 5))
            canvas_h = self.EX_MARGIN + num_rows * self.EX_ROW_H + self.EX_MARGIN
            
            if canvas_h > self.VP_H:
                self.viewport_scrollbar.place(x=self.SCR_X, y=0, width=self.SCROLL_W, height=self.SH)
                self.viewport_scrollbar.lift()
            
            # Print directory details
            clean_path = self.current_directory if len(self.current_directory) < 42 else "..." + self.current_directory[-38:]
            text_log = f"MOUNT TARGET:\n{clean_path}\n\n"
            if self.explorer_selected_file:
                fp = os.path.join(self.current_directory, self.explorer_selected_file)
                try:
                    sz = os.path.getsize(fp) / (1024 * 1024)
                    text_log += f"FILE ID: {self.explorer_selected_file.upper()}\n"
                    text_log += f"ALLOCATION: {sz:.2f} MB"
                except Exception:
                    text_log += "ERROR READING FILE ACCESS"
            else:
                text_log += "VOLUME MOUNTED.\nSELECT SOURCE FILE ELEMENT."
            self.info_panel_lbl.config(text=text_log, fg="#888888")
            
        elif self.system_state == 'GRID':
            if not hasattr(self, 'info_panel_border_frame'):
                self.info_panel_border_frame = tk.Frame(self.control_frame, bg="#080808", bd=1, relief="solid", highlightthickness=0, highlightbackground="#58595b")
            
            # Place grid sidebar layout (scaled)
            self.info_panel_border_frame.place(x=40*self.SCALE, y=20*self.SCALE, width=580*self.SCALE, height=135*self.SCALE)
            self.info_panel_lbl.place(x=60*self.SCALE, y=35*self.SCALE, width=540*self.SCALE, height=105*self.SCALE)
            self.info_panel_lbl.config(bg="#080808", bd=0, relief="flat", anchor="nw")
            self.nav_btn.place(x=40*self.SCALE, y=175*self.SCALE, width=580*self.SCALE, height=40*self.SCALE)
            
            # Explorer Image Preview in grid view
            if not hasattr(self, 'explorer_preview_frame'):
                self.explorer_preview_frame = tk.Frame(self.control_frame, bg="#080808", bd=1, relief="solid", highlightthickness=0, highlightbackground="#58595b")
                self.explorer_preview_lbl = tk.Label(self.explorer_preview_frame, bg="#080808")
                self.explorer_preview_lbl.place(x=0, y=0, relwidth=1.0, relheight=0.92)
                self.explorer_preview_filename_lbl = tk.Label(self.explorer_preview_frame, bg="#080808", fg="#888888", font=("Courier New", max(8, int(8 * self.SCALE))))
                self.explorer_preview_filename_lbl.place(relx=0.03, rely=0.95, anchor="w")
                
            self.explorer_preview_frame.place(x=40*self.SCALE, y=235*self.SCALE, width=580*self.SCALE, height=825*self.SCALE)
            self.update_explorer_preview()
            
            profile = self.grid_hovered_profile if self.grid_hovered_profile else self.selected_grid_profile
            desc = PROFILE_DESCRIPTIONS.get(profile, "")
            text_log = f"ACTIVE LOG: {self.active_filename.upper()}\n"
            text_log += f"FILTER: {profile}\n\n"
            text_log += f"SPEC: {desc}"
            self.info_panel_lbl.config(text=text_log, fg="#aaaaaa")
            
            self.viewport_canvas.pack_forget()
            self.viewport_canvas.pack(side="left", fill="both", expand=True)
            
            # 15 cells grid (5x3) fits on screen, so no viewport scrollbar needed
            self.viewport_canvas.yview_moveto(0)
            self.viewport_canvas.config(scrollregion=(0, 0, self.VP_W, self.VP_H))
            self.viewport_canvas.itemconfig(self.canvas_window_id, width=self.VP_W, height=self.VP_H)
            
        elif self.system_state == 'WORKBENCH':
            # Place workbench layout components
            self.hist_canvas.place(x=20*self.SCALE, y=20*self.SCALE, width=580*self.SCALE, height=196*self.SCALE)
            
            # Pack frames inside scrollable rack inner frame
            self.workbench_header_frame.pack_forget()
            self.filter_sliders_frame.pack_forget()
            self.geom_tab_btn_frame.pack_forget()
            self.scrollable_tuning_container.pack_forget()
            
            self.workbench_header_frame.pack(fill="x", pady=(0, 10 * self.SCALE))
            self.wb_back_btn.place(x=5*self.SCALE, y=5*self.SCALE, width=100*self.SCALE, height=30*self.SCALE)
            self.save_btn.place(x=475*self.SCALE, y=5*self.SCALE, width=100*self.SCALE, height=30*self.SCALE)
            self.profile_name_lbl.place(x=110*self.SCALE, y=5*self.SCALE, width=355*self.SCALE, height=30*self.SCALE)
            self.profile_name_lbl.config(text=self.selected_grid_profile.upper())
            
            self.filter_sliders_frame.pack(fill="x", pady=(0, 10 * self.SCALE))
            
            self.geom_tab_btn_frame.pack(fill="x", pady=(0, 10 * self.SCALE))
            self.geom_tab_btn_panel.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            
            self.scrollable_tuning_container.pack(fill="x", pady=(0, 10 * self.SCALE))
            
            # Place scrollable rack canvas
            self.canvas_rack.place(x=20*self.SCALE, y=228*self.SCALE, width=580*self.SCALE, height=self.SH - 228*self.SCALE - 20*self.SCALE)
            self.rack_scrollbar.place(x=self.root.winfo_screenwidth() - 20*self.SCALE, y=0, width=20*self.SCALE, height=self.SH)
            
            # Place viewport scrollbars for the image viewer
            self.viewport_scrollbar.place(x=0, y=0, width=int(20 * self.SCALE), height=self.SH - int(20 * self.SCALE))
            self.viewport_h_scrollbar.place(x=int(20 * self.SCALE), y=self.SH - int(20 * self.SCALE), width=int(1260 * self.SCALE), height=int(20 * self.SCALE))
            self.viewport_corner_square.place(x=0, y=self.SH - int(20 * self.SCALE), width=int(20 * self.SCALE), height=int(20 * self.SCALE))
            self.viewport_scrollbar.lift()
            self.viewport_h_scrollbar.lift()
            self.viewport_corner_square.lift()
            
            # Place compare button: bottom-right corner of image viewing window
            self.compare_btn.place(x=1280*self.SCALE - 25.34*self.SCALE, y=self.SH - 20*self.SCALE - 25.34*self.SCALE, width=25.34*self.SCALE, height=25.34*self.SCALE)
            self.compare_btn.lift()
            
            self.build_calibration_sliders()
            
            self.viewport_canvas.pack_forget()
            self.viewport_canvas.pack(side="left", fill="both", expand=True)
            self.viewport_canvas.yview_moveto(0)
            
            cw = self.viewport_canvas.winfo_width()
            ch = self.viewport_canvas.winfo_height()
            if cw <= 1: cw = self.VP_W
            if ch <= 1: ch = self.VP_H
            self.viewport_canvas.config(scrollregion=(0, 0, cw, ch))
            self.viewport_canvas.itemconfig(self.canvas_window_id, width=cw, height=ch, anchor="nw")

        self.trigger_live_recalculation()

    def update_explorer_preview(self):
        if not hasattr(self, 'explorer_preview_lbl') or not self.explorer_preview_lbl.winfo_exists():
            return
            
        if self.explorer_selected_file:
            fp = os.path.join(self.current_directory, self.explorer_selected_file)
            try:
                if hasattr(self, 'preview_base_img') and hasattr(self, 'preview_base_filename') and self.preview_base_filename == self.explorer_selected_file and self.preview_base_img is not None:
                    resized = self.preview_base_img.copy()
                else:
                    img = cv2.imread(fp)
                    if img is not None:
                        h, w = img.shape[:2]
                        sc = min(550.0 / w, 700.0 / h)
                        tw = int(w * sc)
                        th = int(h * sc)
                        resized = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
                        self.preview_base_img = resized
                        self.preview_base_filename = self.explorer_selected_file
                    else:
                        resized = None

                if resized is not None:
                    if self.system_state == 'GRID':
                        profile = self.grid_hovered_profile if self.grid_hovered_profile else self.selected_grid_profile
                        if profile in FILTER_REGISTRY:
                            node = FILTER_REGISTRY[profile]
                            p_vals = []
                            for ctrl_name, _, _, _, var_type in node["controls"]:
                                val = self.filter_parameters[profile][ctrl_name]
                                if var_type == "float":
                                    p_vals.append(float(val))
                                else:
                                    p_vals.append(int(val))
                            base_c = node["engine"](resized, *p_vals[:-1])
                            resized = apply_luminosity_grain(base_c, p_vals[-1], node["grain_type"])

                    self.explorer_preview_img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)))
                    self.explorer_preview_lbl.config(image=self.explorer_preview_img)
                else:
                    self.explorer_preview_lbl.config(image="")
            except Exception as e:
                print(f"Error loading explorer preview: {e}")
                self.explorer_preview_lbl.config(image="")
            
            self.explorer_preview_filename_lbl.config(text=self.explorer_selected_file.upper())
        else:
            self.explorer_preview_lbl.config(image="")
            self.explorer_preview_filename_lbl.config(text="")

    def open_geometry_window(self):
        if self.proxy_source is None:
            messagebox.showwarning("WORKSTATION REPORT", "No image is currently loaded.")
            return

        # Create modal Toplevel window
        geom_win = tk.Toplevel(self.root)
        geom_win.title("GEOMETRY TRANSFORMS // CROP - ROTATE - RESIZE - WARP")
        geom_win.geometry("1020x640")
        geom_win.configure(bg="#080808")
        geom_win.resizable(False, False)
        
        # Configure listbox popup colors to match dark mode Courier theme
        geom_win.option_add("*TCombobox*Listbox.background", "#111111")
        geom_win.option_add("*TCombobox*Listbox.foreground", "#ffffff")
        geom_win.option_add("*TCombobox*Listbox.font", ("Courier New", 9))
        
        geom_win.grab_set()
        geom_win.focus_set()

        # Temporary variables for sliders/entries (Geometry parameters)
        rot_var = tk.DoubleVar(value=self.geom_rotate.get())
        vk_var = tk.DoubleVar(value=self.geom_v_keystone.get())
        hk_var = tk.DoubleVar(value=self.geom_h_keystone.get())
        rw_var = tk.StringVar(value=self.geom_resize_w_val.get())
        rh_var = tk.StringVar(value=self.geom_resize_h_val.get())

        # Crop normalized coordinate states (0.0 to 1.0)
        crop_x1 = self.geom_crop_l.get() / 100.0
        crop_x2 = self.geom_crop_r.get() / 100.0
        crop_y1 = self.geom_crop_t.get() / 100.0
        crop_y2 = self.geom_crop_b.get() / 100.0

        base_resized_bgr = None

        # Layouts
        preview_frame = tk.Frame(geom_win, bg="#020202", bd=1, relief="solid")
        preview_frame.place(x=20, y=20, width=600, height=500)
        
        preview_canvas = tk.Canvas(preview_frame, bg="#020202", highlightthickness=0)
        preview_canvas.pack(fill="both", expand=True)

        controls_frame = tk.Frame(geom_win, bg="#080808")
        controls_frame.place(x=640, y=20, width=360, height=600)

        tk.Label(controls_frame, text="GEOMETRY CONTROLS", fg="#ffffff", bg="#080808", font=("Courier New", 12, "bold")).pack(anchor="w", pady=(0, 10))

        # Geometry transformed preview image (snappy preview cache)
        geom_preview_img = None
        img_x, img_y, w_p, h_p = 0, 0, 0, 0
        
        # Interactive Crop State tracking
        active_handle = None  # "top_left", "top_right", "bottom_left", "bottom_right", "move", or None
        drag_start_x, drag_start_y = 0.0, 0.0
        start_x1, start_y1, start_x2, start_y2 = 0.0, 0.0, 0.0, 0.0

        RATIOS = {
            "Free": None,
            "1:1 (Square)": 1.0,
            "4:3 (Landscape)": 4.0/3.0,
            "3:4 (Portrait)": 3.0/4.0,
            "3:2 (Landscape)": 3.0/2.0,
            "2:3 (Portrait)": 2.0/3.0,
            "16:9 (Widescreen)": 16.0/9.0,
            "9:16 (Portrait)": 9.0/16.0,
            "5:4 (Print)": 5.0/4.0,
            "4:5 (Print Portrait)": 4.0/5.0
        }
        current_ratio_key = "Free"

        def get_current_ratio():
            return RATIOS.get(current_ratio_key, None)

        def update_preview_image():
            nonlocal geom_preview_img, img_x, img_y, w_p, h_p, base_resized_bgr
            try:
                # Apply Rotation & Keystone to the proxy image
                transformed = apply_geometry_transforms(
                    self.proxy_source,
                    0.0, 100.0, 0.0, 100.0,  # Crop bounds are overlay-controlled, not pipeline-controlled in live preview
                    rot_var.get(), vk_var.get(), hk_var.get(),
                    None, None
                )
                
                h_p_raw, w_p_raw = transformed.shape[:2]
                if w_p_raw <= 0 or h_p_raw <= 0:
                    return
                scale_preview = min(600.0 / w_p_raw, 500.0 / h_p_raw)
                w_p = int(w_p_raw * scale_preview)
                h_p = int(h_p_raw * scale_preview)
                if w_p > 0 and h_p > 0:
                    base_resized_bgr = cv2.resize(transformed, (w_p, h_p), interpolation=cv2.INTER_AREA)
                    img_x = (600 - w_p) // 2
                    img_y = (500 - h_p) // 2
                    redraw_canvas()
            except Exception as e:
                print(f"Error compiling geometry preview image: {e}")

        def redraw_canvas():
            nonlocal geom_preview_img
            if base_resized_bgr is None:
                return
                
            preview_canvas.delete("all")
            
            # Darken the regions outside crop box using alpha blending in numpy BGR
            canvas_img = base_resized_bgr.copy()
            
            # Calculate pixel crop boundaries
            ix1 = int(max(0.0, min(crop_x1, 1.0)) * w_p)
            ix2 = int(max(0.0, min(crop_x2, 1.0)) * w_p)
            iy1 = int(max(0.0, min(crop_y1, 1.0)) * h_p)
            iy2 = int(max(0.0, min(crop_y2, 1.0)) * h_p)
            
            # Make sure we don't have empty ranges
            ix2 = max(ix1 + 2, ix2)
            iy2 = max(iy1 + 2, iy2)
            
            # Create overlay mask (0.3 for darkened regions)
            mask = np.ones((h_p, w_p, 1), dtype=np.float32) * 0.3
            mask[iy1:iy2, ix1:ix2] = 1.0
            
            canvas_img = (canvas_img.astype(np.float32) * mask).astype(np.uint8)
            geom_preview_img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(canvas_img, cv2.COLOR_BGR2RGB)))
            
            # Keep a reference to prevent garbage collection
            preview_canvas.image = geom_preview_img
            
            # 1. Draw image
            preview_canvas.create_image(img_x, img_y, anchor="nw", image=geom_preview_img)

            # 2. Draw Crop Bounding Box coordinates
            cx1 = img_x + crop_x1 * w_p
            cy1 = img_y + crop_y1 * h_p
            cx2 = img_x + crop_x2 * w_p
            cy2 = img_y + crop_y2 * h_p

            # High-contrast crop frame (2px solid black outline underneath, 1px white dashed line on top)
            preview_canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="#000000", width=3)
            preview_canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="#ffffff", dash=(4, 4), width=1)

            # Rule of Thirds faint gridlines
            x_13 = cx1 + (cx2 - cx1) / 3.0
            x_23 = cx1 + 2.0 * (cx2 - cx1) / 3.0
            y_13 = cy1 + (cy2 - cy1) / 3.0
            y_23 = cy1 + 2.0 * (cy2 - cy1) / 3.0

            preview_canvas.create_line(x_13, cy1, x_13, cy2, fill="#777777", dash=(2, 2))
            preview_canvas.create_line(x_23, cy1, x_23, cy2, fill="#777777", dash=(2, 2))
            preview_canvas.create_line(cx1, y_13, cx2, y_13, fill="#777777", dash=(2, 2))
            preview_canvas.create_line(cx1, y_23, cx2, y_23, fill="#777777", dash=(2, 2))

            # Draw Corner Handles (8x8 white square with yellow border)
            handles_centers = [
                (cx1, cy1),  # top_left
                (cx2, cy1),  # top_right
                (cx1, cy2),  # bottom_left
                (cx2, cy2),  # bottom_right
            ]
            for hx, hy in handles_centers:
                preview_canvas.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill="#ffffff", outline="#ffcc00", width=1)

        # Snap center aspect ratio
        def snap_to_aspect_ratio():
            nonlocal crop_x1, crop_y1, crop_x2, crop_y2
            R = get_current_ratio()
            if R is None:
                return
                
            # Compute dimensions based on ratios
            if w_p / h_p > R:
                h_box = 1.0
                w_box = R * h_p / w_p
            else:
                w_box = 1.0
                h_box = (w_p / R) / h_p
                
            crop_x1 = max(0.0, min(0.5 - w_box / 2.0, 1.0))
            crop_x2 = max(0.0, min(0.5 + w_box / 2.0, 1.0))
            crop_y1 = max(0.0, min(0.5 - h_box / 2.0, 1.0))
            crop_y2 = max(0.0, min(0.5 + h_box / 2.0, 1.0))
            redraw_canvas()

        # Mouse Click Interactions
        def on_canvas_click(event):
            nonlocal active_handle, drag_start_x, drag_start_y, start_x1, start_y1, start_x2, start_y2
            cx1 = img_x + crop_x1 * w_p
            cy1 = img_y + crop_y1 * h_p
            cx2 = img_x + crop_x2 * w_p
            cy2 = img_y + crop_y2 * h_p

            drag_start_x = event.x
            drag_start_y = event.y
            start_x1, start_y1, start_x2, start_y2 = crop_x1, crop_y1, crop_x2, crop_y2

            # Check if clicked near handles (within 8px radius)
            tol = 8
            if abs(event.x - cx1) <= tol and abs(event.y - cy1) <= tol:
                active_handle = "top_left"
            elif abs(event.x - cx2) <= tol and abs(event.y - cy1) <= tol:
                active_handle = "top_right"
            elif abs(event.x - cx1) <= tol and abs(event.y - cy2) <= tol:
                active_handle = "bottom_left"
            elif abs(event.x - cx2) <= tol and abs(event.y - cy2) <= tol:
                active_handle = "bottom_right"
            # Check if inside crop box
            elif cx1 < event.x < cx2 and cy1 < event.y < cy2:
                active_handle = "move"
            else:
                active_handle = None

        def on_canvas_drag(event):
            nonlocal crop_x1, crop_y1, crop_x2, crop_y2
            if active_handle is None:
                return

            dx = (event.x - drag_start_x) / w_p if w_p > 0 else 0
            dy = (event.y - drag_start_y) / h_p if h_p > 0 else 0

            cx1 = img_x + start_x1 * w_p
            cy1 = img_y + start_y1 * h_p
            cx2 = img_x + start_x2 * w_p
            cy2 = img_y + start_y2 * h_p

            R = get_current_ratio()

            if active_handle == "move":
                # Move crop frame
                w_box = start_x2 - start_x1
                h_box = start_y2 - start_y1
                
                new_x1 = max(0.0, min(start_x1 + dx, 1.0 - w_box))
                new_y1 = max(0.0, min(start_y1 + dy, 1.0 - h_box))
                
                crop_x1 = new_x1
                crop_x2 = new_x1 + w_box
                crop_y1 = new_y1
                crop_y2 = new_y1 + h_box

            elif R is None:
                # Free form resizing
                if active_handle == "top_left":
                    crop_x1 = max(0.0, min(start_x1 + dx, start_x2 - 0.05))
                    crop_y1 = max(0.0, min(start_y1 + dy, start_y2 - 0.05))
                elif active_handle == "top_right":
                    crop_x2 = max(start_x1 + 0.05, min(start_x2 + dx, 1.0))
                    crop_y1 = max(0.0, min(start_y1 + dy, start_y2 - 0.05))
                elif active_handle == "bottom_left":
                    crop_x1 = max(0.0, min(start_x1 + dx, start_x2 - 0.05))
                    crop_y2 = max(start_y1 + 0.05, min(start_y2 + dy, 1.0))
                elif active_handle == "bottom_right":
                    crop_x2 = max(start_x1 + 0.05, min(start_x2 + dx, 1.0))
                    crop_y2 = max(start_y1 + 0.05, min(start_y2 + dy, 1.0))

            else:
                # Aspect Ratio Locked resizing with mathematically robust clamping
                if active_handle == "bottom_right":
                    max_w = (img_x + w_p) - cx1
                    max_h = (img_y + h_p) - cy1
                    limit_w = min(max_w, max_h * R)
                    new_w_scr = max(20.0, min(event.x - cx1, limit_w))
                    new_h_scr = new_w_scr / R
                    crop_x2 = (cx1 + new_w_scr - img_x) / w_p
                    crop_y2 = (cy1 + new_h_scr - img_y) / h_p

                elif active_handle == "top_left":
                    max_w = cx2 - img_x
                    max_h = cy2 - img_y
                    limit_w = min(max_w, max_h * R)
                    new_w_scr = max(20.0, min(cx2 - event.x, limit_w))
                    new_h_scr = new_w_scr / R
                    crop_x1 = (cx2 - new_w_scr - img_x) / w_p
                    crop_y1 = (cy2 - new_h_scr - img_y) / h_p

                elif active_handle == "top_right":
                    max_w = (img_x + w_p) - cx1
                    max_h = cy2 - img_y
                    limit_w = min(max_w, max_h * R)
                    new_w_scr = max(20.0, min(event.x - cx1, limit_w))
                    new_h_scr = new_w_scr / R
                    crop_x2 = (cx1 + new_w_scr - img_x) / w_p
                    crop_y1 = (cy2 - new_h_scr - img_y) / h_p

                elif active_handle == "bottom_left":
                    max_w = cx2 - img_x
                    max_h = (img_y + h_p) - cy1
                    limit_w = min(max_w, max_h * R)
                    new_w_scr = max(20.0, min(cx2 - event.x, limit_w))
                    new_h_scr = new_w_scr / R
                    crop_x1 = (cx2 - new_w_scr - img_x) / w_p
                    crop_y2 = (cy1 + new_h_scr - img_y) / h_p

            crop_x1 = max(0.0, min(crop_x1, 1.0))
            crop_x2 = max(0.0, min(crop_x2, 1.0))
            crop_y1 = max(0.0, min(crop_y1, 1.0))
            crop_y2 = max(0.0, min(crop_y2, 1.0))
            redraw_canvas()

        def on_canvas_motion(event):
            # Dynamic Cursor Changes for intuitive UI feedback
            cx1 = img_x + crop_x1 * w_p
            cy1 = img_y + crop_y1 * h_p
            cx2 = img_x + crop_x2 * w_p
            cy2 = img_y + crop_y2 * h_p

            tol = 8
            if abs(event.x - cx1) <= tol and abs(event.y - cy1) <= tol:
                preview_canvas.config(cursor="size_nw_se")
            elif abs(event.x - cx2) <= tol and abs(event.y - cy1) <= tol:
                preview_canvas.config(cursor="size_ne_sw")
            elif abs(event.x - cx1) <= tol and abs(event.y - cy2) <= tol:
                preview_canvas.config(cursor="size_ne_sw")
            elif abs(event.x - cx2) <= tol and abs(event.y - cy2) <= tol:
                preview_canvas.config(cursor="size_nw_se")
            elif cx1 < event.x < cx2 and cy1 < event.y < cy2:
                preview_canvas.config(cursor="size_all")
            else:
                preview_canvas.config(cursor="arrow")

        # Bind mouse gestures
        preview_canvas.bind("<Button-1>", on_canvas_click)
        preview_canvas.bind("<B1-Motion>", on_canvas_drag)
        preview_canvas.bind("<Motion>", on_canvas_motion)

        # Scale slider callback
        def make_cmd(vl, vr):
            return lambda v: (vl.config(text=f"{float(v):.1f}"), vr.set(float(v)), update_preview_image())

        # Double-click slider text editor local helper inside crop modal
        def edit_geom_slider_value(event, val_lbl, slider, var_var):
            val_str = val_lbl.cget("text")
            entry = tk.Entry(val_lbl.master, bg="#111", fg="#fff", insertbackground="white", width=6, font=("Courier New", 9), bd=1, relief="solid", justify="right")
            entry.insert(0, val_str)
            entry.place(in_=val_lbl, relwidth=1.0, relheight=1.0, anchor="nw")
            entry.focus_set()
            entry.select_range(0, tk.END)
            
            def save_val(event=None):
                try:
                    raw_val = float(entry.get())
                    mn = float(slider.cget("from"))
                    mx = float(slider.cget("to"))
                    clamped = max(mn, min(raw_val, mx))
                    slider.set(clamped)
                    var_var.set(clamped)
                    val_lbl.config(text=f"{clamped:.1f}")
                    update_preview_image()
                except ValueError:
                    pass
                entry.destroy()
                
            entry.bind("<Return>", save_val)
            entry.bind("<FocusOut>", lambda e: save_val())

        # 1. Aspect Ratio presets Dropdown Panel
        ratio_lf = tk.LabelFrame(controls_frame, text="[ CROP ASPECT RATIO ]", fg="#ffcc00", bg="#080808", font=("Courier New", 9, "bold"), bd=1, relief="solid", padx=10, pady=10)
        ratio_lf.pack(fill="x", pady=5)
        
        ratio_combo = ttk.Combobox(ratio_lf, values=list(RATIOS.keys()), state="readonly", font=("Courier New", 9))
        ratio_combo.set("Free")
        ratio_combo.pack(fill="x", pady=5)

        def on_ratio_select(event):
            nonlocal current_ratio_key
            current_ratio_key = ratio_combo.get()
            snap_to_aspect_ratio()

        ratio_combo.bind("<<ComboboxSelected>>", on_ratio_select)

        # 2. Rotate Box
        rot_lf = tk.LabelFrame(controls_frame, text="[ ROTATION ]", fg="#888888", bg="#080808", font=("Courier New", 9, "bold"), bd=1, relief="solid", padx=10, pady=5)
        rot_lf.pack(fill="x", pady=5)
        
        f = tk.Frame(rot_lf, bg="#080808")
        f.pack(fill="x", pady=2)
        tk.Label(f, text="Angle (deg)", fg="#888", bg="#080808", font=("Courier New", 9)).pack(side="left")
        val_lbl_r = tk.Label(f, text=f"{rot_var.get():.1f}", fg="#888", bg="#080808", font=("Courier New", 9), width=6, anchor="e")
        val_lbl_r.pack(side="right")
        
        slider_r = ttk.Scale(rot_lf, from_=-180.0, to=180.0, value=rot_var.get(), command=make_cmd(val_lbl_r, rot_var))
        slider_r.pack(fill="x", pady=(0, 5))
        val_lbl_r.bind("<Double-Button-1>", lambda e, l=val_lbl_r, s=slider_r: edit_geom_slider_value(e, l, s, rot_var))

        # 3. Perspective Box
        warp_lf = tk.LabelFrame(controls_frame, text="[ PERSPECTIVE WARP ]", fg="#888888", bg="#080808", font=("Courier New", 9, "bold"), bd=1, relief="solid", padx=10, pady=5)
        warp_lf.pack(fill="x", pady=5)

        # Vertical Keystone
        f_vk = tk.Frame(warp_lf, bg="#080808")
        f_vk.pack(fill="x", pady=2)
        tk.Label(f_vk, text="Vertical Keystone", fg="#888", bg="#080808", font=("Courier New", 9)).pack(side="left")
        val_lbl_vk = tk.Label(f_vk, text=f"{vk_var.get():.1f}", fg="#888", bg="#080808", font=("Courier New", 9), width=5, anchor="e")
        val_lbl_vk.pack(side="right")
        slider_vk = ttk.Scale(warp_lf, from_=-100.0, to=100.0, value=vk_var.get(), command=make_cmd(val_lbl_vk, vk_var))
        slider_vk.pack(fill="x", pady=(0, 5))
        val_lbl_vk.bind("<Double-Button-1>", lambda e, l=val_lbl_vk, s=slider_vk: edit_geom_slider_value(e, l, s, vk_var))

        # Horizontal Keystone
        f_hk = tk.Frame(warp_lf, bg="#080808")
        f_hk.pack(fill="x", pady=2)
        tk.Label(f_hk, text="Horizontal Keystone", fg="#888", bg="#080808", font=("Courier New", 9)).pack(side="left")
        val_lbl_hk = tk.Label(f_hk, text=f"{hk_var.get():.1f}", fg="#888", bg="#080808", font=("Courier New", 9), width=5, anchor="e")
        val_lbl_hk.pack(side="right")
        slider_hk = ttk.Scale(warp_lf, from_=-100.0, to=100.0, value=hk_var.get(), command=make_cmd(val_lbl_hk, hk_var))
        slider_hk.pack(fill="x", pady=(0, 5))
        val_lbl_hk.bind("<Double-Button-1>", lambda e, l=val_lbl_hk, s=slider_hk: edit_geom_slider_value(e, l, s, hk_var))

        # 4. Resize Box
        resize_lf = tk.LabelFrame(controls_frame, text="[ RESIZE (OUTPUT) ]", fg="#888888", bg="#080808", font=("Courier New", 9, "bold"), bd=1, relief="solid", padx=10, pady=5)
        resize_lf.pack(fill="x", pady=5)

        h_orig, w_orig = self.raw_source.shape[:2]
        tk.Label(resize_lf, text=f"Original Size: {w_orig} x {h_orig}", fg="#555", bg="#080808", font=("Courier New", 9)).pack(anchor="w", pady=2)

        f_entry = tk.Frame(resize_lf, bg="#080808")
        f_entry.pack(fill="x", pady=2)

        tk.Label(f_entry, text="Width:", fg="#888", bg="#080808", font=("Courier New", 9)).pack(side="left")
        e_w = tk.Entry(f_entry, textvariable=rw_var, bg="#111", fg="#fff", insertbackground="white", width=8, font=("Courier New", 9), bd=1, relief="solid")
        e_w.pack(side="left", padx=5)

        tk.Label(f_entry, text="Height:", fg="#888", bg="#080808", font=("Courier New", 9)).pack(side="left", padx=(10, 0))
        e_h = tk.Entry(f_entry, textvariable=rh_var, bg="#111", fg="#fff", insertbackground="white", width=8, font=("Courier New", 9), bd=1, relief="solid")
        e_h.pack(side="left", padx=5)

        # Bottom Buttons
        btn_frame = tk.Frame(controls_frame, bg="#080808")
        btn_frame.pack(fill="x", pady=15)

        def on_apply():
            w_str = rw_var.get().strip()
            h_str = rh_var.get().strip()
            r_w, r_h = None, None
            if w_str or h_str:
                if not (w_str.isdigit() and h_str.isdigit()):
                    messagebox.showerror("GEOMETRY ERROR", "Resize width and height must be positive integers.", parent=geom_win)
                    return
                r_w = int(w_str)
                r_h = int(h_str)
                if r_w <= 0 or r_h <= 0:
                    messagebox.showerror("GEOMETRY ERROR", "Resize dimensions must be greater than zero.", parent=geom_win)
                    return
            
            # Push current state to undo stack before applying transforms
            self.push_undo()
            
            # Save variables (multiplied back to 100 for storage compatibility)
            self.geom_crop_l.set(crop_x1 * 100.0)
            self.geom_crop_r.set(crop_x2 * 100.0)
            self.geom_crop_t.set(crop_y1 * 100.0)
            self.geom_crop_b.set(crop_y2 * 100.0)
            self.geom_rotate.set(rot_var.get())
            self.geom_v_keystone.set(vk_var.get())
            self.geom_h_keystone.set(hk_var.get())
            self.geom_resize_w_val.set(w_str)
            self.geom_resize_h_val.set(h_str)
            
            print("    -> Compiling geometry transforms...")
            self.geom_raw_source = apply_geometry_transforms(
                self.raw_source,
                self.geom_crop_l.get(),
                self.geom_crop_r.get(),
                self.geom_crop_t.get(),
                self.geom_crop_b.get(),
                self.geom_rotate.get(),
                self.geom_v_keystone.get(),
                self.geom_h_keystone.get(),
                r_w, r_h
            )
            
            if r_w is not None and r_h is not None:
                h_raw, w_raw = self.raw_source.shape[:2]
                scale = 1200.0 / max(w_raw, h_raw)
                pr_w = int(r_w * scale)
                pr_h = int(r_h * scale)
            else:
                pr_w, pr_h = None, None
                
            self.geom_proxy_source = apply_geometry_transforms(
                self.proxy_source,
                self.geom_crop_l.get(),
                self.geom_crop_r.get(),
                self.geom_crop_t.get(),
                self.geom_crop_b.get(),
                self.geom_rotate.get(),
                self.geom_v_keystone.get(),
                self.geom_h_keystone.get(),
                pr_w, pr_h
            )
            
            self.zoom_mode = False
            self.queue_workbench_render()
            geom_win.destroy()

        def on_reset():
            nonlocal crop_x1, crop_x2, crop_y1, crop_y2, current_ratio_key
            crop_x1 = 0.0
            crop_x2 = 1.0
            crop_y1 = 0.0
            crop_y2 = 1.0
            rot_var.set(0.0)
            vk_var.set(0.0)
            hk_var.set(0.0)
            rw_var.set("")
            rh_var.set("")
            current_ratio_key = "Free"
            ratio_combo.set("Free")
            
            val_lbl_r.config(text="0.0")
            val_lbl_vk.config(text="0.0")
            val_lbl_hk.config(text="0.0")
            
            update_preview_image()

        apply_btn_border = tk.Frame(btn_frame, bg="#ffcc00", bd=0, highlightthickness=0)
        apply_btn = tk.Button(apply_btn_border, text="[ APPLY TRANSFORMS ]", bg="#080808", fg="#ffcc00", activebackground="#ffcc00", activeforeground="#080808", font=("Courier New", 9, "bold"), bd=0, relief="flat", padx=5, pady=8, command=on_apply)
        apply_btn.pack(fill="both", expand=True, padx=1, pady=1)
        apply_btn_border.pack(fill="x", pady=2)

        reset_btn = tk.Button(btn_frame, text="[ RESET TO DEFAULT ]", bg="#080808", fg="#888888", activebackground="#333333", activeforeground="#ffffff", font=("Courier New", 9, "bold"), bd=1, relief="solid", padx=5, pady=6, command=on_reset)
        reset_btn.pack(fill="x", pady=2)

        cancel_btn = tk.Button(btn_frame, text="[ CANCEL ]", bg="#080808", fg="#888888", activebackground="#333333", activeforeground="#ffffff", font=("Courier New", 9, "bold"), bd=1, relief="solid", padx=5, pady=4, command=geom_win.destroy)
        cancel_btn.pack(fill="x", pady=2)

        update_preview_image()

    def create_slider_row(self, parent, name, mn, mx, current_val, on_adjust, var=None, double_click_handler=None):
        frame = tk.Frame(parent, bg="#080808", height=int(52 * self.SCALE))
        frame.pack(fill="x", pady=2 * self.SCALE)
        frame.pack_propagate(False)
        
        lbl = tk.Label(frame, text=name.upper(), fg="#555555", bg="#080808",
                       font=("Courier New", max(8, int(8 * self.SCALE)), "bold"))
        lbl.place(x=8*self.SCALE, y=2*self.SCALE)
        
        val_lbl = tk.Label(frame, text="", fg="#888888", bg="#080808",
                           font=("Courier New", max(8, int(8 * self.SCALE))),
                           width=6, anchor="e")
        val_lbl.place(x=505*self.SCALE, y=22*self.SCALE, width=65*self.SCALE, height=20*self.SCALE)
        
        if var is not None:
            slider = ttk.Scale(frame, from_=mn, to=mx, variable=var,
                               command=lambda v: on_adjust(v, val_lbl))
            val_lbl.config(text=f"{var.get():.1f}")
        else:
            slider = ttk.Scale(frame, from_=mn, to=mx, value=current_val,
                               command=lambda v: on_adjust(v, val_lbl))
            val_lbl.config(text=f"{current_val:.2f}" if isinstance(current_val, float) else f"{int(current_val)}")
            
        slider.place(x=8*self.SCALE, y=22*self.SCALE, width=470*self.SCALE, height=20*self.SCALE)
        
        slider.bind("<Button-1>", lambda e: self.push_undo())
        if double_click_handler is not None:
            val_lbl.bind("<Double-Button-1>", lambda e, l=val_lbl, s=slider: double_click_handler(e, l, s))
            
        return slider, val_lbl

    def build_calibration_sliders(self):
        for widget in self.filter_sliders_frame.winfo_children(): widget.destroy()
        for widget in self.scrollable_tuning_container.winfo_children(): widget.destroy()
        self.active_sliders = {}
        
        # 1. Custom Filter Controls inside self.filter_sliders_frame using exact scaled coordinates
        for idx, (name, mn, mx, df, var_type) in enumerate(FILTER_REGISTRY[self.selected_grid_profile]["controls"]):
            current_val = self.filter_parameters[self.selected_grid_profile][name]
            
            def make_adjust_cb(t, n):
                return lambda v, l: self.on_filter_slider_adjust(v, l, t, n)
            
            def make_double_click_cb(t, n):
                return lambda e, l, s: self.edit_slider_value(e, l, s, t, n)
            
            slider, val_lbl = self.create_slider_row(
                self.filter_sliders_frame,
                name, mn, mx, current_val,
                on_adjust=make_adjust_cb(var_type, name),
                double_click_handler=make_double_click_cb(var_type, name)
            )
            self.active_sliders[name] = (slider, var_type)

        # 2. 3-Way Color Wheels Box (in scrollable rack)
        wheels_box = tk.LabelFrame(self.scrollable_tuning_container, text="[ 3-WAY COLOR WHEELS ]", fg="#888888", bg="#080808", font=("Courier New", 8, "bold"), bd=1, relief="solid", padx=10, pady=10)
        wheels_box.pack(fill="x", pady=5)
        
        self.wheels_canvas = tk.Canvas(wheels_box, width=360, height=440, bg="#050505", highlightthickness=1, highlightbackground="#222222")
        self.wheels_canvas.pack(pady=5)
        self.wheels_canvas.bind("<Button-1>", self.on_wheels_click)
        self.wheels_canvas.bind("<B1-Motion>", self.on_wheels_drag)
        self.wheels_canvas.bind("<Button-3>", self.on_wheels_right_click)

        # 3. Camera Calibration Box (in scrollable rack)
        cal_box = tk.LabelFrame(self.scrollable_tuning_container, text="[ CAMERA CALIBRATION ]", fg="#888888", bg="#080808", font=("Courier New", 8, "bold"), bd=1, relief="solid", padx=10, pady=10)
        cal_box.pack(fill="x", pady=5)
        
        cal_sliders_config = [
            ("Red Primary Saturation", -100.0, 100.0, self.cal_red),
            ("Green Primary Saturation", -100.0, 100.0, self.cal_green),
            ("Blue Primary Saturation", -100.0, 100.0, self.cal_blue),
        ]
        
        for name, mn, mx, var in cal_sliders_config:
            def make_cal_callback(v_var):
                return lambda v, l: (v_var.set(float(v)), l.config(text=f"{float(v):.1f}"), self.trigger_live_recalculation())
            
            self.create_slider_row(
                cal_box,
                name, mn, mx, var.get(),
                on_adjust=make_cal_callback(var),
                var=var,
                double_click_handler=lambda e, l, s: self.edit_slider_value(e, l, s, "float")
            )

        # 4. Global Adjustments Box (named [ ADJUSTMENTS ] without "Global" prefixes)
        global_box = tk.LabelFrame(self.scrollable_tuning_container, text="[ ADJUSTMENTS ]", fg="#888888", bg="#080808", font=("Courier New", 8, "bold"), bd=1, relief="solid", padx=10, pady=10)
        global_box.pack(fill="x", pady=5)
        
        global_sliders_config = [
            ("Exposure", 50.0, 150.0, self.global_exposure),
            ("Contrast", 50.0, 150.0, self.global_contrast),
            ("Saturation", 50.0, 150.0, self.global_saturation),
            ("Temperature", -50.0, 50.0, self.global_warmth),
            ("Tint", -50.0, 50.0, self.global_tint),
            ("Highlights", 50.0, 150.0, self.global_highlights),
            ("Shadows", 50.0, 150.0, self.global_shadows),
            ("Sharpness", 0.0, 5.0, self.global_sharpness),
            ("Vignette", -100.0, 100.0, self.global_vignette),
        ]
        
        for name, mn, mx, var in global_sliders_config:
            def make_adjust_callback(v_var):
                return lambda v, l: (v_var.set(float(v)), l.config(text=f"{float(v):.1f}"), self.trigger_live_recalculation())
            
            self.create_slider_row(
                global_box,
                name, mn, mx, var.get(),
                on_adjust=make_adjust_callback(var),
                var=var,
                double_click_handler=lambda e, l, s: self.edit_slider_value(e, l, s, "float")
            )

        # Render canvas graphics initially
        self.draw_wheels_canvas()
        
        # Recursively bind scroll wheel events to all slider rack children so they can scroll the menu
        self.bind_scrollwheel_to_rack_widgets(self.scrollable_inner_rack)


    def draw_wheels_canvas(self):
        if not hasattr(self, 'wheels_canvas') or not self.wheels_canvas.winfo_exists():
            return
            
        self.wheels_canvas.delete("all")
        
        centers = [
            (180, 75, "SHADOWS", self.shadow_wheel_pos),
            (180, 215, "MIDTONES", self.midtone_wheel_pos),
            (180, 355, "HIGHLIGHTS", self.highlight_wheel_pos)
        ]
        
        for cx, cy, label, pos in centers:
            self.wheels_canvas.create_image(cx - 55, cy - 55, anchor="nw", image=self.wheel_photo)
            self.wheels_canvas.create_oval(cx - 55, cy - 55, cx + 55, cy + 55, outline="#333333", width=1)
            self.wheels_canvas.create_line(cx - 5, cy, cx + 5, cy, fill="#222222")
            self.wheels_canvas.create_line(cx, cy - 5, cx, cy + 5, fill="#222222")
            
            dx, dy = pos
            tx = cx + dx
            ty = cy + dy
            self.wheels_canvas.create_oval(tx - 3, ty - 3, tx + 3, ty + 3, fill="#ffffff", outline="#000000", width=1)
            self.wheels_canvas.create_text(cx, cy + 70, text=label, fill="#888888", font=("Courier New", 8, "bold"))

    def on_wheels_click(self, event):
        self.push_undo()
        self.handle_wheels_interaction(event.x, event.y)
        
    def on_wheels_drag(self, event):
        self.handle_wheels_interaction(event.x, event.y)
        
    def handle_wheels_interaction(self, x, y):
        if y <= 145:
            cx, cy = 180, 75
            wheel_idx = 0
        elif 145 < y <= 285:
            cx, cy = 180, 215
            wheel_idx = 1
        else:
            cx, cy = 180, 355
            wheel_idx = 2
            
        dx = x - cx
        dy = y - cy
        dist = np.sqrt(dx**2 + dy**2)
        
        if dist > 55.0:
            dx = (dx / dist) * 55.0
            dy = (dy / dist) * 55.0
            
        if wheel_idx == 0:
            self.shadow_wheel_pos = (dx, dy)
        elif wheel_idx == 1:
            self.midtone_wheel_pos = (dx, dy)
        else:
            self.highlight_wheel_pos = (dx, dy)
            
        self.update_tints_from_positions()
        self.draw_wheels_canvas()
        self.trigger_live_recalculation()
        
    def on_wheels_right_click(self, event):
        self.push_undo()
        y = event.y
        if y <= 145:
            self.shadow_wheel_pos = (0.0, 0.0)
        elif 145 < y <= 285:
            self.midtone_wheel_pos = (0.0, 0.0)
        else:
            self.highlight_wheel_pos = (0.0, 0.0)
            
        self.update_tints_from_positions()
        self.draw_wheels_canvas()
        self.trigger_live_recalculation()
        
    def update_tints_from_positions(self):
        M = 50.0
        
        def pos_to_tint(pos):
            dx, dy = pos
            r = np.sqrt(dx**2 + dy**2)
            if r == 0:
                return [0.0, 0.0, 0.0]
            theta = np.arctan2(dy, dx)
            amt = (r / 55.0) * M
            
            # Align primary color angles with the generated color wheel
            # Red is at -pi, Green is at -pi/3, Blue is at pi/3
            theta_R = -np.pi
            theta_G = -np.pi / 3.0
            theta_B = np.pi / 3.0
            
            r_off = amt * np.cos(theta - theta_R)
            g_off = amt * np.cos(theta - theta_G)
            b_off = amt * np.cos(theta - theta_B)
            
            return [b_off, g_off, r_off]
            
        self.shadow_tint = pos_to_tint(self.shadow_wheel_pos)
        self.midtone_tint = pos_to_tint(self.midtone_wheel_pos)
        self.highlight_tint = pos_to_tint(self.highlight_wheel_pos)

    def on_rack_adjust(self, val, value_label, var_type):
        value_label.config(text=f"{float(val):.2f}" if var_type == "float" else f"{int(float(val))}")
        self.trigger_live_recalculation()

    def on_filter_slider_adjust(self, val, value_label, var_type, name):
        val_float = float(val)
        self.filter_parameters[self.selected_grid_profile][name] = val_float
        value_label.config(text=f"{val_float:.2f}" if var_type == "float" else f"{int(val_float)}")
        self.trigger_live_recalculation()

    def edit_slider_value(self, event, val_lbl, slider, var_type, name=None):
        val_str = val_lbl.cget("text")
        entry = tk.Entry(val_lbl.master, bg="#111", fg="#fff", insertbackground="white", width=6, font=("Courier New", 9), bd=1, relief="solid", justify="right")
        entry.insert(0, val_str)
        entry.place(in_=val_lbl, relwidth=1.0, relheight=1.0, anchor="nw")
        entry.focus_set()
        entry.select_range(0, tk.END)
        
        def save_val(event=None):
            try:
                raw_val = float(entry.get())
                mn = float(slider.cget("from"))
                mx = float(slider.cget("to"))
                clamped = max(mn, min(raw_val, mx))
                if var_type == "int":
                    clamped = int(clamped)
                self.push_undo()
                slider.set(clamped)
                val_lbl.config(text=f"{clamped:.2f}" if var_type == "float" else f"{clamped}")
                self.trigger_live_recalculation()
            except ValueError:
                pass
            entry.destroy()
            
        entry.bind("<Return>", save_val)
        entry.bind("<FocusOut>", lambda e: save_val())

    def gather_active_parameters(self):
        return [float(sl[0].get()) if sl[1] == "float" else int(sl[0].get()) for sl in self.active_sliders.values()]

    def snapshot_parameters(self):
        self.snapshot_selected_profile = self.selected_grid_profile
        self.snapshot_active_params = self.gather_active_parameters()
        self.snapshot_cal_red = self.cal_red.get()
        self.snapshot_cal_green = self.cal_green.get()
        self.snapshot_cal_blue = self.cal_blue.get()
        self.snapshot_global_exposure = self.global_exposure.get()
        self.snapshot_global_contrast = self.global_contrast.get()
        self.snapshot_global_saturation = self.global_saturation.get()
        self.snapshot_global_warmth = self.global_warmth.get()
        self.snapshot_global_tint = self.global_tint.get()
        self.snapshot_global_highlights = self.global_highlights.get()
        self.snapshot_global_shadows = self.global_shadows.get()
        self.snapshot_global_sharpness = self.global_sharpness.get()
        self.snapshot_global_vignette = self.global_vignette.get()
        self.snapshot_curve_points = copy.deepcopy(self.curve_points)
        self.snapshot_shadow_tint = copy.deepcopy(self.shadow_tint)
        self.snapshot_midtone_tint = copy.deepcopy(self.midtone_tint)
        self.snapshot_highlight_tint = copy.deepcopy(self.highlight_tint)

    def run_grading_pipeline_async(self, source_img):
        params = self.snapshot_active_params
        profile = self.snapshot_selected_profile
        base_calc = FILTER_REGISTRY[profile]["engine"](source_img, *params[:-1])
        
        h, w = source_img.shape[:2]
        if max(h, w) <= 2000:
            if self.noise_texture.shape[0] < h or self.noise_texture.shape[1] < w:
                self.noise_texture = np.random.normal(0, 1.0, (max(1200, h), max(1200, w), 3)).astype(np.float32)
            noise_tex = self.noise_texture
        else:
            noise_tex = None
            
        base_grain = apply_luminosity_grain(base_calc, params[-1], FILTER_REGISTRY[profile]["grain_type"], noise_tex)
        
        lut = compute_spline_lut(self.snapshot_curve_points)
        base_curve = cv2.LUT(base_grain, lut)
        
        base_3way = apply_3way_color_grading(base_curve, self.snapshot_shadow_tint, self.snapshot_midtone_tint, self.snapshot_highlight_tint)
        base_cal = apply_calibration(base_3way, self.snapshot_cal_red, self.snapshot_cal_green, self.snapshot_cal_blue)
        base_vig = apply_vignette(base_cal, self.snapshot_global_vignette)
        
        final_img = apply_global_adjustments(
            base_vig,
            self.snapshot_global_exposure,
            self.snapshot_global_contrast,
            self.snapshot_global_saturation,
            self.snapshot_global_warmth,
            self.snapshot_global_tint,
            self.snapshot_global_highlights,
            self.snapshot_global_shadows,
            self.snapshot_global_sharpness
        )
        return final_img

    def queue_workbench_render(self):
        self.snapshot_parameters()
        self.workbench_render_requested = True
        
        if not getattr(self, 'render_thread_active', False):
            self.render_thread_active = True
            threading.Thread(target=self._async_render_workbench_loop, daemon=True).start()

    def _async_render_workbench_loop(self):
        while True:
            if not getattr(self, 'workbench_render_requested', False) or self.system_state != 'WORKBENCH':
                self.render_thread_active = False
                break
                
            self.workbench_render_requested = False
            
            try:
                if self.geom_proxy_source is None:
                    continue
                    
                if self.show_before_compare:
                    last_rendered_proxy = self.geom_proxy_source.copy()
                    last_rendered_full = self.geom_proxy_source.copy()
                else:
                    last_rendered_full = self.run_grading_pipeline_async(self.geom_proxy_source)
                    last_rendered_proxy = last_rendered_full.copy()
                
                h, w = last_rendered_proxy.shape[:2]
                cw = self.viewport_canvas.winfo_width()
                ch = self.viewport_canvas.winfo_height()
                if cw <= 1: cw = 1240
                if ch <= 1: ch = 1040
                
                scale_fit = min(cw/w, ch/h)
                fit_w = int(w * scale_fit)
                fit_h = int(h * scale_fit)
                
                resized_w = int(fit_w * self.zoom_factor)
                resized_h = int(fit_h * self.zoom_factor)
                
                bgr_resized = cv2.resize(last_rendered_proxy, (resized_w, resized_h), interpolation=cv2.INTER_AREA if self.zoom_factor <= 1.0 else cv2.INTER_LINEAR)
                
                if self.scope_mode == 'HISTOGRAM':
                    bgr_scope = draw_live_histogram(last_rendered_full, canvas_w=int(580 * self.SCALE), canvas_h=int(196 * self.SCALE))
                else:
                    bgr_scope = draw_luma_waveform(last_rendered_full, canvas_w=int(580 * self.SCALE), canvas_h=int(196 * self.SCALE))
                
                self.root.after(0, lambda r=bgr_resized, s=bgr_scope, rw=resized_w, rh=resized_h, lf=last_rendered_full, lp=last_rendered_proxy: 
                    self._apply_workbench_render_results(r, s, rw, rh, lf, lp)
                )
                
            except Exception as e:
                print(f"Error in async render: {e}")
                
            time.sleep(0.012)

    def _apply_workbench_render_results(self, bgr_resized, bgr_scope, resized_w, resized_h, last_rendered_full, last_rendered_proxy):
        if self.system_state != 'WORKBENCH':
            return
            
        self.last_rendered_full = last_rendered_full
        self.last_rendered_proxy = last_rendered_proxy
        self.displayed_image = bgr_resized
        
        self.tk_image_current = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(bgr_resized, cv2.COLOR_BGR2RGB)))
        self.view_label.config(image=self.tk_image_current)
        
        cw = self.viewport_canvas.winfo_width()
        ch = self.viewport_canvas.winfo_height()
        if cw <= 1: cw = 1240
        if ch <= 1: ch = 1040
        
        if resized_w <= cw and resized_h <= ch:
            pad_x = (cw - resized_w) // 2
            pad_y = (ch - resized_h) // 2
            self.viewport_canvas.coords(self.canvas_window_id, pad_x, pad_y)
            self.viewport_canvas.itemconfig(self.canvas_window_id, width=resized_w, height=resized_h, anchor="nw")
            self.viewport_canvas.config(scrollregion=(0, 0, cw, ch))
        else:
            self.viewport_canvas.coords(self.canvas_window_id, 0, 0)
            self.viewport_canvas.itemconfig(self.canvas_window_id, width=resized_w, height=resized_h, anchor="nw")
            self.viewport_canvas.config(scrollregion=(0, 0, resized_w, resized_h))
            
        self.scope_photo = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(bgr_scope, cv2.COLOR_BGR2RGB)))
        self.hist_canvas.delete("all")
        self.hist_canvas.create_image(0, 0, anchor="nw", image=self.scope_photo)

    def regress_to_explorer(self):
        if self.system_state == 'WORKBENCH':
            self.system_state = 'GRID'
            # Clear selected profile from thumbnail cache to force recalculation with edited values
            if self.selected_grid_profile in self.grid_thumbnail_cache:
                del self.grid_thumbnail_cache[self.selected_grid_profile]
        elif self.system_state == 'GRID':
            self.system_state = 'EXPLORER'
        self.zoom_factor = 1.0
        self.zoom_mode = False
        self.render_system_view()

    def select_custom_directory(self):
        chosen = filedialog.askdirectory(initialdir=self.current_directory)
        if chosen:
            self.current_directory = os.path.abspath(chosen)
            self.explorer_selected_file = ""
            self.thumbnail_cache.clear()
            self.grid_thumbnail_cache.clear()
            self.update_explorer_files()
            self.render_system_view()

    def trigger_live_recalculation(self):
        if self.system_state == 'EXPLORER':
            valid_files = self.explorer_files
            
            all_cached = True
            for filename in valid_files:
                fp = os.path.join(self.current_directory, filename)
                try:
                    mtime = os.path.getmtime(fp)
                except Exception:
                    mtime = 0
                if fp not in self.thumbnail_cache or self.thumbnail_cache[fp]['mtime'] != mtime:
                    all_cached = False
                    break
                    
            if all_cached:
                self._draw_explorer_canvas(valid_files)
            else:
                self._draw_explorer_canvas(valid_files)
                threading.Thread(target=self._async_load_explorer_thumbnails, args=(valid_files,), daemon=True).start()
                
        elif self.system_state == 'GRID':
            if len(self.grid_thumbnail_cache) == len(self.profile_keys):
                self._draw_grid_canvas()
            else:
                threading.Thread(target=self._async_render_grid, daemon=True).start()
                
        else:
            self.queue_workbench_render()

    # ==========================================
    # 3. INTERACTION MODEL ROUTING LOGIC
    # ==========================================
    def on_viewport_click(self, event):
        t_current = time.time()
        t_delta = t_current - self.last_click_time
        self.last_click_time = t_current
        is_double_click = (t_delta < 0.35)

        if self.system_state == 'EXPLORER':
            # Exact boundary hit-test — iterate actual cell positions
            C      = self.EX_CELL
            M      = self.EX_MARGIN
            RH     = self.EX_ROW_H
            cols   = self.EX_COL_X
            valid_files = self.explorer_files
            num_rows = max(1, int(np.ceil(len(valid_files) / 5)))

            row = -1
            for r in range(num_rows):
                y0 = M + r * RH
                if y0 <= event.y < y0 + C:
                    row = r
                    break

            col = -1
            for c_i, x0 in enumerate(cols):
                if x0 <= event.x < x0 + C:
                    col = c_i
                    break

            if row < 0 or col < 0:
                return  # clicked in gap between cells — ignore

            idx = row * 5 + col
            
            if 0 <= idx < len(valid_files):
                self.explorer_selected_file = valid_files[idx]
                if is_double_click:
                    target_path = os.path.join(self.current_directory, self.explorer_selected_file)
                    self.raw_source = cv2.imread(target_path)
                    if self.raw_source is not None:
                        h, w = self.raw_source.shape[:2]
                        scale = 1200.0 / max(w, h)
                        self.proxy_source = cv2.resize(self.raw_source, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
                        self.active_filename = self.explorer_selected_file
                        self.grid_thumbnail_cache.clear()
                        
                        # Reset geometry parameter values
                        self.geom_crop_l.set(0.0)
                        self.geom_crop_r.set(100.0)
                        self.geom_crop_t.set(0.0)
                        self.geom_crop_b.set(100.0)
                        self.geom_rotate.set(0.0)
                        self.geom_v_keystone.set(0.0)
                        self.geom_h_keystone.set(0.0)
                        self.geom_resize_w_val.set("")
                        self.geom_resize_h_val.set("")
                        
                        self.geom_raw_source = self.raw_source.copy()
                        self.geom_proxy_source = self.proxy_source.copy()
                        
                        self.system_state = 'GRID'
                self.render_system_view()

        elif self.system_state == 'GRID':
            W      = self.GR_CELL_W
            H      = self.GR_CELL_H
            cols   = self.GR_COL_X
            rows   = self.GR_ROW_Y

            row = -1
            for r in range(3):
                y0 = rows[r]
                if y0 <= event.y < y0 + H:
                    row = r
                    break

            col = -1
            for c_i, x0 in enumerate(cols):
                if x0 <= event.x < x0 + W:
                    col = c_i
                    break

            if row < 0 or col < 0:
                return  # clicked in gap

            idx = row * 5 + col
            
            if 0 <= idx < len(self.profile_keys):
                self.selected_grid_profile = self.profile_keys[idx]
                if is_double_click:
                    self.system_state = 'WORKBENCH'
                self.render_system_view()

        elif self.system_state == 'WORKBENCH':
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            self.drag_current_x = event.x
            self.drag_current_y = event.y
            self.is_dragging_zoom = True

    def on_viewport_release(self, event):
        if self.system_state == 'WORKBENCH' and self.is_dragging_zoom:
            self.is_dragging_zoom = False
            
            sx1 = min(self.drag_start_x, event.x)
            sx2 = max(self.drag_start_x, event.x)
            sy1 = min(self.drag_start_y, event.y)
            sy2 = max(self.drag_start_y, event.y)
            
            if (sx2 - sx1) < 8 or (sy2 - sy1) < 8:
                if self.zoom_factor > 1.0:
                    self.zoom_factor = 1.0
                    self.zoom_mode = False
                    self.trigger_live_recalculation()
                return
                
            if self.geom_proxy_source is not None:
                cw = self.viewport_canvas.winfo_width()
                ch = self.viewport_canvas.winfo_height()
                if cw <= 1: cw = 1240
                if ch <= 1: ch = 1040
                
                sw = sx2 - sx1
                sh = sy2 - sy1
                
                # Image size before zoom
                img_w = self.displayed_image.shape[1]
                img_h = self.displayed_image.shape[0]
                
                # Scroll position before zoom
                left, _ = self.viewport_canvas.xview()
                top, _ = self.viewport_canvas.yview()
                scroll_x = left * img_w if img_w > cw else 0
                scroll_y = top * img_h if img_h > ch else 0
                
                # Centered pad before zoom
                pad_x = (cw - img_w) // 2 if img_w <= cw else 0
                pad_y = (ch - img_h) // 2 if img_h <= ch else 0
                
                # Calculate zoom increase factor
                zoom_inc = min(cw / sw, ch / sh)
                old_zoom = self.zoom_factor
                self.zoom_factor = min(10.0, self.zoom_factor * zoom_inc)
                self.zoom_mode = (self.zoom_factor > 1.0)
                
                # Calculate the center of the drag box relative to the image
                center_x = (sx1 + sx2) / 2
                center_y = (sy1 + sy2) / 2
                
                # Adjust scroll positions after zoom to center the drag box in the viewport
                ratio = self.zoom_factor / old_zoom
                new_scroll_x = (center_x + scroll_x - pad_x) * ratio - (cw / 2)
                new_scroll_y = (center_y + scroll_y - pad_y) * ratio - (ch / 2)
                
                self.trigger_live_recalculation()
                
                # Calculate new dimensions directly
                img_h, img_w = self.geom_proxy_source.shape[:2]
                scale_fit = min(cw / img_w, ch / img_h)
                new_w = int(img_w * scale_fit * self.zoom_factor)
                new_h = int(img_h * scale_fit * self.zoom_factor)

                if new_w > cw:
                    self.viewport_canvas.xview_moveto(max(0.0, min(new_scroll_x / new_w, 1.0)))
                if new_h > ch:
                    self.viewport_canvas.yview_moveto(max(0.0, min(new_scroll_y / new_h, 1.0)))

    def on_viewport_drag(self, event):
        if self.system_state == 'WORKBENCH' and self.is_dragging_zoom:
            self.drag_current_x = event.x
            self.drag_current_y = event.y
            self.redraw_workbench_with_drag_rect()

    def redraw_workbench_with_drag_rect(self):
        if not hasattr(self, 'displayed_image') or self.displayed_image is None:
            return
        canvas = self.displayed_image.copy()
        
        h, w = canvas.shape[:2]
        cw = self.viewport_canvas.winfo_width()
        ch = self.viewport_canvas.winfo_height()
        if cw <= 1: cw = 1240
        if ch <= 1: ch = 1040
        
        pad_x = (cw - w) // 2 if w <= cw else 0
        pad_y = (ch - h) // 2 if h <= ch else 0
        
        cx1 = self.drag_start_x - pad_x
        cy1 = self.drag_start_y - pad_y
        cx2 = self.drag_current_x - pad_x
        cy2 = self.drag_current_y - pad_y
        
        cv2.rectangle(canvas, (cx1, cy1), (cx2, cy2), (0, 255, 255), 1)
        self.tk_image_current = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)))
        self.view_label.config(image=self.tk_image_current)

    def on_viewport_right_click(self, event):
        if self.system_state == 'WORKBENCH':
            cx = event.x_root - self.viewport_canvas.winfo_rootx()
            cy = event.y_root - self.viewport_canvas.winfo_rooty()
            self.viewport_canvas.scan_mark(cx, cy)

    def on_viewport_pan(self, event):
        if self.system_state == 'WORKBENCH':
            cx = event.x_root - self.viewport_canvas.winfo_rootx()
            cy = event.y_root - self.viewport_canvas.winfo_rooty()
            self.viewport_canvas.scan_dragto(cx, cy, gain=1)

    def apply_mousewheel_zoom(self, event):
        if self.geom_proxy_source is None:
            return
            
        old_zoom = self.zoom_factor
        
        cw = self.viewport_canvas.winfo_width()
        ch = self.viewport_canvas.winfo_height()
        if cw <= 1: cw = 1240
        if ch <= 1: ch = 1040

        old_w = self.displayed_image.shape[1]
        old_h = self.displayed_image.shape[0]

        pad_x = (cw - old_w) // 2 if old_w <= cw else 0
        pad_y = (ch - old_h) // 2 if old_h <= ch else 0

        left, _ = self.viewport_canvas.xview()
        top, _ = self.viewport_canvas.yview()
        scroll_x = left * old_w if old_w > cw else 0
        scroll_y = top * old_h if old_h > ch else 0

        mx = event.x
        my = event.y

        if event.delta > 0:
            self.zoom_factor = min(10.0, self.zoom_factor * 1.15)
        else:
            self.zoom_factor = max(1.0, self.zoom_factor / 1.15)

        self.zoom_mode = (self.zoom_factor > 1.0)

        if self.zoom_factor != old_zoom:
            ratio = self.zoom_factor / old_zoom
            
            new_scroll_x = mx * ratio - (mx + pad_x - scroll_x)
            new_scroll_y = my * ratio - (my + pad_y - scroll_y)

            self.queue_workbench_render()

            # Calculate new dimensions directly
            img_h, img_w = self.geom_proxy_source.shape[:2]
            scale_fit = min(cw / img_w, ch / img_h)
            new_w = int(img_w * scale_fit * self.zoom_factor)
            new_h = int(img_h * scale_fit * self.zoom_factor)

            if new_w > cw:
                self.viewport_canvas.xview_moveto(max(0.0, min(new_scroll_x / new_w, 1.0)))
            if new_h > ch:
                self.viewport_canvas.yview_moveto(max(0.0, min(new_scroll_y / new_h, 1.0)))

    def on_explorer_mousewheel(self, event):
        if self.system_state in ('EXPLORER', 'GRID'):
            self.viewport_canvas.yview_scroll(int(-1 * (event.delta / 40)), "units")

    def on_viewport_mousewheel(self, event):
        if self.system_state == 'WORKBENCH' and self.raw_source is not None:
            self.apply_mousewheel_zoom(event)
        elif self.system_state in ('EXPLORER', 'GRID'):
            self.on_explorer_mousewheel(event)

    def on_rack_mousewheel(self, event):
        if self.system_state == 'WORKBENCH':
            self.canvas_rack.yview_scroll(int(-1 * (event.delta / 40)), "units")

    def bind_scrollwheel_to_rack_widgets(self, widget):
        widget.bind("<MouseWheel>", self.on_rack_mousewheel)
        for child in widget.winfo_children():
            self.bind_scrollwheel_to_rack_widgets(child)

    def on_mouse_motion(self, event):
        if self.system_state == 'EXPLORER':
            C      = self.EX_CELL
            M      = self.EX_MARGIN
            RH     = self.EX_ROW_H
            cols   = self.EX_COL_X
            valid_files = self.explorer_files
            num_rows = max(1, int(np.ceil(len(valid_files) / 5)))

            row = -1
            for r in range(num_rows):
                y0 = M + r * RH
                if y0 <= event.y < y0 + C:
                    row = r
                    break
            col = -1
            for c_i, x0 in enumerate(cols):
                if x0 <= event.x < x0 + C:
                    col = c_i
                    break

            hovered_file = ""
            if row >= 0 and col >= 0:
                idx = row * 5 + col
                if 0 <= idx < len(valid_files):
                    hovered_file = valid_files[idx]

            if hovered_file != self.explorer_hovered_file:
                self.explorer_hovered_file = hovered_file
                self._draw_explorer_canvas(valid_files)

        elif self.system_state == 'GRID':
            W      = self.GR_CELL_W
            H      = self.GR_CELL_H
            cols   = self.GR_COL_X
            rows   = self.GR_ROW_Y

            row = -1
            for r in range(3):
                y0 = rows[r]
                if y0 <= event.y < y0 + H:
                    row = r
                    break
            col = -1
            for c_i, x0 in enumerate(cols):
                if x0 <= event.x < x0 + W:
                    col = c_i
                    break

            idx = row * 5 + col if (row >= 0 and col >= 0) else -1
            
            hovered_profile = ""
            if 0 <= idx < len(self.profile_keys):
                hovered_profile = self.profile_keys[idx]
                
            if hovered_profile != self.grid_hovered_profile:
                self.grid_hovered_profile = hovered_profile
                self._draw_grid_canvas()
                
                # Update info panel dynamically on hover
                desc = PROFILE_DESCRIPTIONS.get(hovered_profile if hovered_profile else self.selected_grid_profile, "")
                text_log = f"ACTIVE LOG: {self.active_filename.upper()}\n"
                text_log += f"FILTER: {hovered_profile if hovered_profile else self.selected_grid_profile}\n\n"
                text_log += f"SPEC: {desc}"
                self.info_panel_lbl.config(text=text_log, fg="#aaaaaa", font=("Courier New", 8))
                self.update_explorer_preview()

    def on_viewport_leave(self, event):
        if self.system_state == 'EXPLORER':
            if self.explorer_hovered_file != "":
                self.explorer_hovered_file = ""
                self._draw_explorer_canvas(self.explorer_files)
        elif self.system_state == 'GRID':
            if self.grid_hovered_profile != "":
                self.grid_hovered_profile = ""
                self._draw_grid_canvas()
                
                desc = PROFILE_DESCRIPTIONS.get(self.selected_grid_profile, "")
                text_log = f"ACTIVE LOG: {self.active_filename.upper()}\n"
                text_log += f"FILTER: {self.selected_grid_profile}\n\n"
                text_log += f"SPEC: {desc}"
                self.info_panel_lbl.config(text=text_log, fg="#aaaaaa", font=("Courier New", 8))
                self.update_explorer_preview()

    def toggle_scope_mode(self, event):
        if self.scope_mode == 'HISTOGRAM':
            self.scope_mode = 'WAVEFORM'
            self.scope_lbl.config(text="[ SCOPE MODE: LUMA WAVEFORM // CLICK TO TOGGLE ]")
        else:
            self.scope_mode = 'HISTOGRAM'
            self.scope_lbl.config(text="[ SCOPE MODE: HISTOGRAM // CLICK TO TOGGLE ]")
        self.trigger_live_recalculation()

    def on_compare_press(self, event):
        if self.system_state == 'WORKBENCH' and not self.show_before_compare:
            self.show_before_compare = True
            self.trigger_live_recalculation()

    def on_compare_release(self, event):
        if self.system_state == 'WORKBENCH' and self.show_before_compare:
            self.show_before_compare = False
            self.trigger_live_recalculation()

    # ==========================================
    # 4. BACKGROUND PROCESSING THREAD GROUPS
    # ==========================================
    def _draw_explorer_canvas(self, files_to_show):
        num_files = len(files_to_show)
        cw = self.VP_W
        ch = self.VP_H
        if num_files == 0:
            explorer_canvas = np.zeros((ch, cw, 3), dtype=np.uint8) + 2
            cv2.putText(explorer_canvas, "NO COMPATIBLE IMAGE FILES FOUND IN DIRECTORY",
                        (cw // 4, ch // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1, cv2.LINE_AA)
            self.tk_image_current = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(explorer_canvas, cv2.COLOR_BGR2RGB)))
            self.view_label.config(image=self.tk_image_current)
            self.viewport_canvas.config(scrollregion=(0, 0, cw, ch))
            self.viewport_canvas.itemconfig(self.canvas_window_id, width=cw, height=ch)
            return

        C      = self.EX_CELL
        M      = self.EX_MARGIN
        ROW_H  = self.EX_ROW_H
        cols   = self.EX_COL_X
        num_rows = max(1, int(np.ceil(num_files / 5)))
        canvas_h = max(ch, M + num_rows * ROW_H + M)
        
        explorer_canvas = np.zeros((canvas_h, cw, 3), dtype=np.uint8) + 2
        
        for idx, filename in enumerate(files_to_show):
            fp = os.path.join(self.current_directory, filename)
            thumb_resized = None
            if fp in self.thumbnail_cache:
                thumb_resized = self.thumbnail_cache[fp]['data']
                
            cell_box = np.zeros((C, C, 3), dtype=np.uint8) + 2
            
            if thumb_resized is not None:
                th_s, tw_s = thumb_resized.shape[:2]
                # Scale down if thumbnail is bigger than cell
                if tw_s > C - 4 or th_s > C - 20:
                    scale = min((C - 4) / max(tw_s, 1), (C - 20) / max(th_s, 1))
                    tw_s = max(1, int(tw_s * scale))
                    th_s = max(1, int(th_s * scale))
                    thumb_resized = cv2.resize(thumb_resized, (tw_s, th_s), interpolation=cv2.INTER_AREA)
                py = max(0, (C - 20 - th_s) // 2 + 10)
                px = max(0, (C - tw_s) // 2)
                py2 = min(py + th_s, C)
                px2 = min(px + tw_s, C)
                cell_box[py:py2, px:px2] = thumb_resized[:py2-py, :px2-px]
            else:
                cv2.rectangle(cell_box, (8, 8), (C - 8, C - 25), (12, 12, 12), -1)
                cv2.putText(cell_box, "LOADING...", (C // 2 - 30, C // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (50, 50, 50), 1, cv2.LINE_AA)
                
            if filename == self.explorer_selected_file:
                bc = (0, 204, 255);  bw = 2
            elif filename == self.explorer_hovered_file:
                bc = (255, 255, 255); bw = 1
            else:
                bc = (90, 89, 88);   bw = 1
            cv2.rectangle(cell_box, (0, 0), (C - 1, C - 1), bc, bw)
            
            short_name = filename if len(filename) < 20 else filename[:17] + "..."
            cv2.putText(cell_box, short_name.upper(), (6, C - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (110, 110, 110), 1, cv2.LINE_AA)
            
            row = idx // 5
            col = idx % 5
            gy = M + row * ROW_H
            gx = cols[col]
            avail_w = min(C, cw - gx)
            avail_h = min(C, canvas_h - gy)
            if avail_w > 0 and avail_h > 0:
                explorer_canvas[gy:gy+avail_h, gx:gx+avail_w] = cell_box[:avail_h, :avail_w]
            
        self.tk_image_current = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(explorer_canvas, cv2.COLOR_BGR2RGB)))
        self.view_label.config(image=self.tk_image_current)
        self.viewport_canvas.config(scrollregion=(0, 0, cw, canvas_h))
        self.viewport_canvas.itemconfig(self.canvas_window_id, width=cw, height=canvas_h)

    def _async_load_explorer_thumbnails(self, files_to_show):
        if not self.thumbnail_load_lock.acquire(blocking=False):
            return
        try:
            need_redraw = False
            for filename in files_to_show:
                if self.system_state != 'EXPLORER':
                    break
                    
                fp = os.path.join(self.current_directory, filename)
                try:
                    mtime = os.path.getmtime(fp)
                except Exception:
                    mtime = 0
                    
                if fp in self.thumbnail_cache and self.thumbnail_cache[fp]['mtime'] == mtime:
                    continue
                    
                thumb = cv2.imread(fp)
                if thumb is None:
                    continue
                    
                th, tw = thumb.shape[:2]
                sc = min(220.0 / tw, 190.0 / th)
                tw_s, th_s = int(tw * sc), int(th * sc)
                thumb_resized = cv2.resize(thumb, (tw_s, th_s), interpolation=cv2.INTER_AREA)
                
                self.thumbnail_cache[fp] = {'mtime': mtime, 'data': thumb_resized}
                need_redraw = True
                
                if self.system_state == 'EXPLORER':
                    self.root.after(0, lambda f=files_to_show: self._draw_explorer_canvas(f))
                    
            if need_redraw and self.system_state == 'EXPLORER':
                self.root.after(0, lambda f=files_to_show: self._draw_explorer_canvas(f))
        finally:
            self.thumbnail_load_lock.release()

    def _draw_grid_canvas(self):
        cw = self.VP_W
        ch = self.VP_H
        C  = self.GR_CELL_W
        R  = self.GR_CELL_H
        grid_canvas = np.zeros((ch, cw, 3), dtype=np.uint8) + 2
        
        for idx, p_name in enumerate(self.profile_keys):
            final_c = self.grid_thumbnail_cache.get(p_name)
            cell_box = np.zeros((R, C, 3), dtype=np.uint8) + 2
            
            thumb_area_h = R - 40
            if final_c is not None:
                th_s, tw_s = final_c.shape[:2]
                if tw_s > C - 4 or th_s > thumb_area_h:
                    scale = min((C - 4) / max(tw_s, 1), thumb_area_h / max(th_s, 1))
                    tw_s = max(1, int(tw_s * scale))
                    th_s = max(1, int(th_s * scale))
                    final_c = cv2.resize(final_c, (tw_s, th_s), interpolation=cv2.INTER_AREA)
                padx = max(0, (C - tw_s) // 2)
                pady = max(0, 12 + (thumb_area_h - th_s) // 2)
                py2 = min(pady + th_s, R)
                px2 = min(padx + tw_s, C)
                cell_box[pady:py2, padx:px2] = final_c[:py2-pady, :px2-padx]
            else:
                cv2.rectangle(cell_box, (8, 12), (C - 8, R - 30), (12, 12, 12), -1)
                cv2.putText(cell_box, "CALCULATING...", (C // 2 - 50, R // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (50, 50, 50), 1, cv2.LINE_AA)
                
            if p_name == self.selected_grid_profile:
                bc = (0, 204, 255);  bw = 2
            elif p_name == self.grid_hovered_profile:
                bc = (255, 255, 255); bw = 1
            else:
                bc = (90, 89, 88);   bw = 1
            cv2.rectangle(cell_box, (0, 0), (C - 1, R - 1), bc, bw)
            cv2.putText(cell_box, f"{idx+1:02d}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (120, 120, 120), 1, cv2.LINE_AA)
            # Profile name at the bottom
            short_p = p_name if len(p_name) < 22 else p_name[:19] + "..."
            cv2.putText(cell_box, short_p, (6, R - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (110, 110, 110), 1, cv2.LINE_AA)
            
            row = idx // 5
            col = idx % 5
            y = self.GR_ROW_Y[row]
            x = self.GR_COL_X[col]
            avail_w = min(C, cw - x)
            avail_h = min(R, ch - y)
            if avail_w > 0 and avail_h > 0:
                grid_canvas[y:y+avail_h, x:x+avail_w] = cell_box[:avail_h, :avail_w]
            
        self.tk_image_current = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(grid_canvas, cv2.COLOR_BGR2RGB)))
        self.view_label.config(image=self.tk_image_current)
        self.viewport_canvas.config(scrollregion=(0, 0, cw, ch))
        self.viewport_canvas.itemconfig(self.canvas_window_id, width=cw, height=ch)

    def _async_render_grid(self):
        if not self.render_lock.acquire(blocking=False): return
        try:
            C = self.GR_CELL_W
            R = self.GR_CELL_H
            img_h, img_w = self.proxy_source.shape[:2]
            scale = min((C - 20) / img_w, (R - 40) / img_h)
            target_w, target_h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
            thumb_base = cv2.resize(self.proxy_source, (target_w, target_h), interpolation=cv2.INTER_AREA)
            
            for idx, p_name in enumerate(self.profile_keys):
                if self.system_state != 'GRID':
                    break
                    
                if p_name not in self.grid_thumbnail_cache:
                    node = FILTER_REGISTRY[p_name]
                    p_vals = []
                    for ctrl_name, _, _, _, var_type in node["controls"]:
                        val = self.filter_parameters[p_name][ctrl_name]
                        if var_type == "float":
                            p_vals.append(float(val))
                        else:
                            p_vals.append(int(val))
                    base_c = node["engine"](thumb_base, *p_vals[:-1])
                    final_c = apply_luminosity_grain(base_c, p_vals[-1], node["grain_type"])
                    self.grid_thumbnail_cache[p_name] = final_c
                
                if self.system_state == 'GRID':
                    self.root.after(0, self._draw_grid_canvas)
                    
            if self.system_state == 'GRID':
                self.root.after(0, self._draw_grid_canvas)
        finally:
            self.render_lock.release()

    def run_grading_pipeline(self, source_img):
        params = self.gather_active_parameters()
        
        # 1. Filter engine
        base_calc = FILTER_REGISTRY[self.selected_grid_profile]["engine"](source_img, *params[:-1])
        
        # 2. Grain
        h, w = source_img.shape[:2]
        if max(h, w) <= 2000:
            if self.noise_texture.shape[0] < h or self.noise_texture.shape[1] < w:
                self.noise_texture = np.random.normal(0, 1.0, (max(1200, h), max(1200, w), 3)).astype(np.float32)
            noise_tex = self.noise_texture
        else:
            noise_tex = None
            
        base_grain = apply_luminosity_grain(base_calc, params[-1], FILTER_REGISTRY[self.selected_grid_profile]["grain_type"], noise_tex)
        
        # 3. Tone Curve spline
        lut = compute_spline_lut(self.curve_points)
        base_curve = cv2.LUT(base_grain, lut)
        
        # 4. 3-way color wheels BGR offset
        base_3way = apply_3way_color_grading(base_curve, self.shadow_tint, self.midtone_tint, self.highlight_tint)
        
        # 5. Camera Calibration
        base_cal = apply_calibration(base_3way, self.cal_red.get(), self.cal_green.get(), self.cal_blue.get())
        
        # 6. Vignette
        base_vig = apply_vignette(base_cal, self.global_vignette.get())
        
        # 7. Global adjustments
        final_img = apply_global_adjustments(
            base_vig,
            self.global_exposure.get(),
            self.global_contrast.get(),
            self.global_saturation.get(),
            self.global_warmth.get(),
            self.global_tint.get(),
            self.global_highlights.get(),
            self.global_shadows.get(),
            self.global_sharpness.get()
        )
        return final_img



    def update_scope_display(self):
        if hasattr(self, 'last_rendered_full') and self.last_rendered_full is not None:
            scope_source = self.last_rendered_full
        elif self.last_rendered_proxy is not None:
            scope_source = self.last_rendered_proxy
        else:
            return
            
        cw = self.hist_canvas.winfo_width()
        ch = self.hist_canvas.winfo_height()
        if cw <= 1: cw = int(580 * self.SCALE)
        if ch <= 1: ch = int(196 * self.SCALE)

        if self.scope_mode == 'HISTOGRAM':
            scope_img = draw_live_histogram(scope_source, canvas_w=cw, canvas_h=ch)
        else:
            scope_img = draw_luma_waveform(scope_source, canvas_w=cw, canvas_h=ch)
            
        self.scope_photo = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(scope_img, cv2.COLOR_BGR2RGB)))
        self.hist_canvas.delete("all")
        self.hist_canvas.create_image(0, 0, anchor="nw", image=self.scope_photo)



    def execute_purity_export(self):
        if self.geom_raw_source is None: return
        
        initial_name = f"EXPORT_{self.selected_grid_profile.split(' ')[0]}_{int(time.time())}"
        file_path = filedialog.asksaveasfilename(
            initialdir=self.current_directory,
            initialfile=initial_name,
            defaultextension=".jpg",
            filetypes=[("JPEG Image", "*.jpg;*.jpeg"), ("PNG Image", "*.png"), ("All files", "*.*")]
        )
        if not file_path:
            return
            
        print("    -> Initializing full-resolution pristine export matrix compilation pass...")
        final_file = self.run_grading_pipeline(self.geom_raw_source)
        
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.png':
            cv2.imwrite(file_path, final_file)
        else:
            cv2.imwrite(file_path, final_file, [cv2.IMWRITE_JPEG_QUALITY, 100])
            
        print(f"[+] Export Successful: {file_path}")
        messagebox.showinfo("WORKSTATION REPORT", f"Export Complete!\nSaved graded image as:\n{file_path}")

# ==========================================
# 5. CORE BACKGROUND FILES SCANNERS SERVICE
# ==========================================
class DirectoryScanner(FileSystemEventHandler):
    def __init__(self, ui_app): self.ui_app = ui_app
    def on_created(self, event):
        if event.is_directory: return
        fp = event.src_path
        if fp.lower().endswith(('.jpg', '.jpeg', '.png')) and "output" not in fp:
            time.sleep(0.4)
            # Re-read directory changes live if sitting inside explorer stack view
            if self.ui_app.system_state == 'EXPLORER':
                self.ui_app.root.after(0, self.ui_app.trigger_live_recalculation)

if __name__ == "__main__":
    import glob
    main_window = tk.Tk()
    
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("TScale", background="#080808", troughcolor="#121212", borderwidth=0)
    style.configure("TCombobox", fieldbackground="#111", background="#222", foreground="#fff", borderwidth=1, arrowcolor="#555")
    
    # Custom TScrollbar styling matching Illustrator SVGs
    style.configure("TScrollbar", troughcolor="#a7a9ac", background="#e6e7e8", bordercolor="#939598", arrowcolor="#58595b", lightcolor="#e6e7e8", darkcolor="#e6e7e8")
    style.map("TScrollbar", background=[('active', '#ffffff'), ('pressed', '#c0c0c0')])
    
    studio = UltimateHardwareStudio(main_window)
    observer = Observer()
    observer.schedule(DirectoryScanner(studio), path='.', recursive=False)
    observer.start()

    main_window.mainloop()
    observer.stop()
    observer.join()