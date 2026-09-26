# LATENT // Emulsion Profile Specifications

The 15 film profiles live in `latent/imaging/filters.py`. Every engine takes a BGR `uint8` image plus its parameters and returns a BGR `uint8` image. Grain (the last control of every profile) is applied afterwards by the pipeline (see `pipeline_architecture.md`).

### CCD-tuned foundations
The profiles are tuned for the response of **CCD sensor cameras**: higher linear colour saturation, particular channel biases and distinctive noise. The maths shifts those CCD primaries toward the look of each emulsion.

### Function-formed design
No texture overlays or LUT images: every look is computed from the pixels (channel curves, HSV/YCrCb transforms, luminance masks), and grain density follows local luminance like silver halide.

---

## Shared functions

| Symbol | Definition |
|---|---|
| $\text{clip}(I)$ | $\min(\max(I, 0), 255)$, cast to `uint8` (`limit_and_cast`) |
| $\Gamma_g(X)$ | $255\,(X/255)^{g}$ — **normalised** power curve: $0\to0$, $255\to255$ |
| $\sigma_s(x)$ | $\dfrac{S(x)-S(0)}{S(1)-S(0)}$ with $S(x) = \dfrac{1}{1+e^{-s(x-0.5)}}$ — S-curve through 0 and 1 |
| $\text{Sat}_k(I)$ | multiply HSV saturation by $k$ |
| $y$ | Rec.601 luma in $[0,1]$: $(0.299R + 0.587G + 0.114B)/255$ |
| $M_{mid}$ | $4y(1-y)$ — midtone mask |
| $M_{sh}$, $M_{hi}$ | $(1-y)^2$, $y^2$ — shadow / highlight masks |

> **v1 → v2 correction.** v1 applied exponents to raw values ($R^{1.12}$ on 0–255). That is not a tone curve: $128^{1.12} = 228$ and $255^{0.88} = 131$, so neutral grey turned orange (Kodachrome), magenta (Superia) or red (Astia). v2 uses $\Gamma_g$. v1's sigmoids mapped black to ≈10 and white to ≈244; v2 uses the rescaled $\sigma_s$.

---

| # | Profile | Engine | Grain | Controls (default) |
|---|---|---|---|---|
| 1 | Provia Standard · CCD | `run_provia` | fine | Exposure 60–140 (100), Saturation 70–140 (100), Grain 0–15 (3) |
| 2 | Velvia Vivid · Slide | `run_velvia` | fine | Contrast Slope 4–9 (6.2), Saturation Pop 1.1–1.7 (1.35), Grain 0–20 (4) |
| 3 | Astia Soft · Portrait | `run_astia` | fine | Midtone Softness 0.8–1.4 (1.05), Skin Warmth 0–25 (8), Grain 0–15 (2) |
| 4 | Classic Chrome · Print | `run_classic_chrome` | midtone | Shadow Crush 1.0–1.6 (1.25), Chroma 40–95 (65), Grain 0–25 (8) |
| 5 | Kodachrome 64 · Retro | `run_kodachrome` | heavy | Yellow Bias 0.8–1.4 (1.10), Red Push 0–20 (8), Grain 0–35 (14) |
| 6 | Agfa Vista 400 · Color | `run_agfa_vista` | heavy | Red Saturation 1.0–1.5 (1.25), Print Exposure 70–130 (100), Grain 0–35 (12) |
| 7 | Superia X-Tra · Layer 4 | `run_superia` | fine | Green Gamma 0.8–1.3 (0.92), Emerald Shadows 0–20 (6), Grain 0–20 (6) |
| 8 | Ilford HP5 Plus · B&W | `run_ilford_hp5` | heavy, mono | Contrast 0.8–1.4 (1.05), Highlight Gamma 0.7–1.3 (0.95), Grain 0–40 (18) |
| 9 | Kodak Vision3 · Cine | `run_vision3` | fine | Shadow Teal 0–35 (16), Highlight Amber 0–30 (12), Grain 0–25 (7) |
| 10 | Ektachrome E100 · Dial | `run_ektachrome` | fine | Blue Pop 1.0–1.4 (1.12), Contrast Slope 4–8.5 (5.8), Grain 0–20 (4) |
| 11 | Fujicolor C200 · Warm | `run_fujicolor_c200` | heavy | Green Shadows 0–15 (6), Highlight Warmth 0–20 (8), Grain 0–30 (10) |
| 12 | Kodak Portra 400 · Soft | `run_portra` | fine | Pastel Midtones 0.9–1.3 (1.08), Skin Warmth 0–15 (5), Grain 0–15 (3) |
| 13 | Lo-Fi Halation · Glare | `run_halation` | midtone | Glow Threshold 160–245 (205), Glow Radius 11–55 (27), Glow Power 5–45 (25), Grain 0–35 (12) |
| 14 | 90s Xenon Flash · Flash | `run_xenon_90s` | heavy | Flash Contrast 4–9.5 (6.5), Saturation Pop 1.0–1.7 (1.25), Grain 0–40 (15) |
| 15 | Pacific Misty Cold · Cold | `run_pacific_cold` | midtone | Blue Mist 0–45 (22), Forest Green 0–35 (14), Chroma 25–95 (50), Grain 0–30 (8) |

## Formulas

**1. Provia** — $I' = \text{Sat}_{1.05\,S/100}(I)$; $\;B = 1.04\,B'E/100,\; G = G'E/100,\; R = R'E/100$.

**2. Velvia** — $I' = 255\,\sigma_{C_s}(I/255)$; $\;I_{out} = \text{Sat}_{S_{pop}}(I')$.

**3. Astia** — $I' = \Gamma_{1/\gamma_s}(\text{Sat}_{0.95}(I))$ (γ>1 lifts and softens the midtones);
$R = R' + W\,M_{mid}$, $B = B' - 0.4\,W\,M_{mid}$.

**4. Classic Chrome** — $I_{out} = \Gamma_{C_{crush}}(\text{Sat}_{S/100}(I))$.

**5. Kodachrome** — $I' = \text{Sat}_{1.1}(I)$; $B = \Gamma_{\gamma_y}(B')$ (less blue in the mids → golden yellows), $G = \Gamma_{0.98}(G')$, $R = \Gamma_{0.92}(R') + P\,M_{hi}$;
the result is blended 50/50 with $\sigma_5$ of itself for archival dye contrast.

**6. Agfa Vista** — $I' = \text{Sat}_{1.15}(I)$; all channels × $E/100$, red additionally × $S_{red}$.

**7. Superia** — $B = \Gamma_{0.98}(B)$, $G = \Gamma_{\gamma_g}(G) + O\,M_{sh}$, $R = \Gamma_{1.04}(R)$.

**8. Ilford HP5** — $m = \Gamma_{\gamma_h}(\text{gray})/255$; $\;m' = 0.5 + (m - 0.5)\,P$; output $[m', m', m']$. Grain is monochrome.

**9. Vision3** — in YCrCb with $d = (255-Y)/255$, $b = Y/255$:
$Cr' = Cr - 0.5\,T\,d + 0.7\,A\,b$, $\;Cb' = Cb + T\,d - 0.4\,A\,b$, clipped before conversion back.

**10. Ektachrome** — $B' = B\,M_{blue}$; $\;I_{out} = 255\,\sigma_{C_s}(\text{clip}_{0..1}(I'/255))$.

**11. Fujicolor C200** — $B = 0.96B$, $G = \Gamma_{0.98}(G) + B_g M_{sh}$, $R = 1.03R + W M_{hi}$.

**12. Portra** — $I' = \Gamma_{1/\gamma_p}(\text{Sat}_{0.85}(I))$; $R = R' + T\,M_{mid}$, $G = G' + 0.35\,T\,M_{mid}$, $B = 0.97B'$.

**13. Halation** — mask $= [\text{gray} \ge T]$; $k = \text{odd}(K \cdot \text{edge}/1200)$ so the glow keeps its size at any resolution;
$\beta = \text{GaussianBlur}_k(\text{mask})/255$; $\;B \mathrel{+}= 0.4P\beta,\; G \mathrel{+}= 0.2P\beta,\; R \mathrel{+}= P\beta$.

**14. 90s Xenon Flash** — $I_{out} = \text{Sat}_{S_{pop}}(255\,\sigma_{C_f}(I/255))$.

**15. Pacific Misty Cold** — $I' = \text{Sat}_{S/100}(I)$; $B = B' + V_b$, $G = G' + V_g$, $R = R' - V_b/2$ (intentionally lifted, misty blacks).

All outputs pass through $\text{clip}$.
