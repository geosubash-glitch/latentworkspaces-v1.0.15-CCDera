# LATENT // Emulsion Profile Specifications & Math Engines

This document contains the exact technical and mathematical specifications for the 15 film simulation profiles implemented in **LATENT**. 

### CCD-Tuned Foundations
Every profile in LATENT is specifically engineered and fine-tuned for the unique response curves of **CCD sensor cameras**. CCD sensors behave fundamentally differently than modern CMOS sensors, featuring higher linear color saturation, specific channel sensitivity biases, and distinct noise properties. The processing math shifts these specific CCD-generated primaries to achieve organic analog film emulation.

### Mathematical Authenticity & Function-Formed Design
LATENT rejects superficial filter layers. Instead of applying random static grain textures or flat color overlays on top of the image, the software simulates chemical processes algorithmically at the pixel level. 
* Grain density is calculated dynamically from local luminance values to replicate silver halide emulsion physics.
* Color transformations are achieved through calibrated HSV and BGR channel calculations.
* Contrast distributions are computed using tridiagonal cubic spline equations.

---

## General Utility: Limit and Cast
All filter outputs are processed through the `limit_and_cast` utility function to clip color values into the valid 8-bit dynamic range $[0, 255]$ and cast the array back to `uint8`:
$$\text{limit\_and\_cast}(I) = \text{clip}(I, 0, 255).\text{astype}(\text{uint8})$$

---

## 1. PROVIA STANDARD (CCD)
- **Engine Function**: `run_provia(img, exp, sat)`
- **Grain Type**: Fine
- **Visual Intent**: Pushes Fujifilm's iconic Provia daylight-balanced slide film look with a neutral color reproduction bias, optimized for classic CCD sensor aesthetics.
- **Parameters**:
  - `Sensor Exposure Val` ($E \in [60, 140]$, default: $100$): Scales exposure coefficients.
  - `Chroma Saturation` ($S \in [70, 140]$, default: $100$): Controls HSV saturation.
  - `Micro Sensor Noise` ($G \in [0, 15]$, default: $3$): Fine sensor-like grain.
- **Mathematical Formula**:
  1. HSV saturation scaling:
     $$I_{hsv} = \text{RGB2HSV}(I)$$
     $$I_{hsv}[:,:,1] = \text{clip}\left(I_{hsv}[:,:,1] \cdot \frac{S}{100.0} \cdot 1.05,\, 0,\, 255\right)$$
     $$I_{bgr} = \text{HSV2RGB}(I_{hsv})$$
  2. BGR channel scaling:
     $$B_{out} = B \cdot \frac{E}{100.0} \cdot 1.04$$
     $$G_{out} = G \cdot \frac{E}{100.0}$$
     $$R_{out} = R \cdot \frac{E}{100.0}$$
     $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 2. VELVIA VIVID (SLIDE)
- **Engine Function**: `run_velvia(img, contrast_slope, saturation_boost)`
- **Grain Type**: Fine
- **Visual Intent**: High-saturation, high-contrast daylight slide profile based on Fujifilm Velvia film. Delivers extremely rich landscapes, deep blacks, and vivid primaries.
- **Parameters**:
  - `Contrast Curve Slope` ($C_s \in [4.0, 9.0]$, default: $6.2$): Slope of the sigmoid curve.
  - `Velvia Saturation Pop` ($S_{pop} \in [1.1, 1.7]$, default: $1.35$): Saturation boost.
  - `Slide Fine Grain` ($G \in [0, 20]$, default: $4$): Fine emulsion grain.
- **Mathematical Formula**:
  1. Sigmoid contrast curve on normalized image:
     $$I_{32} = \frac{I}{255.0}$$
     $$I_{curve} = \frac{1.0}{1.0 + e^{-C_s \cdot (I_{32} - 0.5)}}$$
  2. HSV saturation pop:
     $$I_{hsv} = \text{RGB2HSV}(I_{curve} \cdot 255.0)$$
     $$I_{hsv}[:,:,1] = \text{clip}(I_{hsv}[:,:,1] \cdot S_{pop},\, 0,\, 255)$$
     $$I_{final} = \text{HSV2RGB}(I_{hsv})$$

---

## 3. ASTIA SOFT (PORTRAIT)
- **Engine Function**: `run_astia(img, soft_gamma, skin_warmth)`
- **Grain Type**: Fine
- **Visual Intent**: Fujifilm Astia simulation designed for portraits, fashion, and soft skin tones. Features gentle highlight roll-offs and warm midtone casts.
- **Parameters**:
  - `Highlights Gamma` ($\gamma_s \in [0.8, 1.4]$, default: $1.05$): Softens highlights.
  - `Skin Warmth Coefficient` ($W_{skin} \in [0, 25]$, default: $8$): Warm red tone injection.
  - `Portrait Micro Grain` ($G \in [0, 15]$, default: $2$): Minimal micro grain.
- **Mathematical Formula**:
  Splits channels and applies exponent parameters:
  $$B_{out} = B^{0.98}$$
  $$G_{out} = G^{1.02}$$
  $$R_{out} = R^{\gamma_s} + W_{skin}$$
  $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 4. CLASSIC CHROME (PRINT)
- **Engine Function**: `run_classic_chrome(img, shadow_crush, desat_rate)`
- **Grain Type**: Midtone
- **Visual Intent**: Simulates documentary and editorial print stocks. Delivers desaturated colors, deep shadow contrast, and crushed midtones.
- **Parameters**:
  - `Shadow Crush Exponential` ($C_{crush} \in [1.0, 1.6]$, default: $1.25$): Compresses shadow values.
  - `Chroma Suppression` ($S_{supp} \in [40, 95]$, default: $65$): Saturation scale.
  - `Print Hard Texture` ($G \in [0, 25]$, default: $8$): Midtone texture grain.
- **Mathematical Formula**:
  1. Saturation scale:
     $$I_{hsv} = \text{RGB2HSV}(I)$$
     $$I_{hsv}[:,:,1] = \text{clip}\left(I_{hsv}[:,:,1] \cdot \frac{S_{supp}}{100.0},\, 0,\, 255\right)$$
     $$I_{bgr} = \text{HSV2RGB}(I_{hsv})$$
  2. Exponent shadow crush:
     For each channel $X \in \{B, G, R\}$:
     $$X_{out} = 255.0 \cdot \left(\frac{X}{255.0}\right)^{C_{crush}}$$
     $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 5. KODACHROME 64 (RETRO)
- **Engine Function**: `run_kodachrome(img, yellow_gamma, red_push)`
- **Grain Type**: Heavy
- **Visual Intent**: Pushes Eastman Kodak's legendary archival slide stock look, renowned for its strong yellow saturation, deep warm red highlight bleed, and high archival dye contrast.
- **Parameters**:
  - `Yellow Channel Gamma` ($\gamma_y \in [0.8, 1.4]$, default: $1.10$): Shift in yellow exposure spectrum.
  - `Warm Red Push Vector` ($P_{red} \in [0, 20]$, default: $8$): Adds warm red cast in highlights.
  - `Vintage Slide Grain` ($G \in [0, 35]$, default: $14$): Heavy retro slide grain.
- **Mathematical Formula**:
  $$\text{Adjusted Channels}:$$
  $$B_{out} = B^{0.88} - 10$$
  $$G_{out} = G^{\gamma_y}$$
  $$R_{out} = R^{1.12} + P_{red}$$
  $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 6. AGFA VISTA 400 (COLOR)
- **Engine Function**: `run_agfa_vista(img, red_saturation, exposure)`
- **Grain Type**: Heavy
- **Visual Intent**: Consumer negative film look based on Agfa Vista. Characterized by vibrant warm reds, deep sky blues, and wide overexposure latitude.
- **Parameters**:
  - `Agfa Red Saturation` ($S_{red} \in [1.0, 1.5]$, default: $1.25$): Amplifies red channel saturation.
  - `Negative Print Exposure` ($E_{print} \in [70, 130]$, default: $100$): General print exposure scale.
  - `Emulsion Silver Grain` ($G \in [0, 35]$, default: $12$): Organic silver print grain.
- **Mathematical Formula**:
  1. Saturation boost:
     $$I_{hsv} = \text{RGB2HSV}(I)$$
     $$I_{hsv}[:,:,1] = \text{clip}(I_{hsv}[:,:,1] \cdot 1.15,\, 0,\, 255)$$
     $$I_{bgr} = \text{HSV2RGB}(I_{hsv})$$
  2. Red channel amplification and exposure scaling:
     $$B_{out} = B \cdot \frac{E_{print}}{100.0}$$
     $$G_{out} = G \cdot \frac{E_{print}}{100.0}$$
     $$R_{out} = R \cdot S_{red} \cdot \frac{E_{print}}{100.0}$$
     $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 7. SUPERIA X-TRA (LAYER4)
- **Engine Function**: `run_superia(img, green_gamma, emerald_layer)`
- **Grain Type**: Fine
- **Visual Intent**: Fujifilm Superia multi-layer negative film simulation, incorporating a fourth color layer (cyan) to render natural colors under fluorescent studio lighting.
- **Parameters**:
  - `Green Channel Gamma` ($\gamma_g \in [0.8, 1.3]$, default: $0.92$): Shifts green channel response.
  - `Emerald Layer Offset` ($O_{cyan} \in [0, 20]$, default: $6$): Injects cyan hues in shadows.
  - `Superia Fine Grain` ($G \in [0, 20]$, default: $6$): Fine grain texture.
- **Mathematical Formula**:
  $$B_{out} = B^{1.02}$$
  $$G_{out} = G^{\gamma_g} + O_{cyan}$$
  $$R_{out} = R^{1.08}$$
  $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 8. ILFORD HP5 PLUS (B&W)
- **Engine Function**: `run_ilford_hp5(img, shadow_punch, highlight_gamma)`
- **Grain Type**: Heavy
- **Visual Intent**: Panchromatic monochrome print film emulation. Known for rich midtone gray scaling, heavy contrast shadow punch, and excellent highlight latitude.
- **Parameters**:
  - `Shadow Contrast Scale` ($P_{shadow} \in [0.8, 1.4]$, default: $1.05$): Boosts low-end contrast curves.
  - `Highlight Latitude Gamma` ($\gamma_h \in [0.7, 1.3]$, default: $0.95$): Compresses highlight roll-off.
  - `Pan Metallic Grain` ($G \in [0, 40]$, default: $18$): Heavy silver metallic grain.
- **Mathematical Formula**:
  1. Grayscale luminance conversion:
     $$I_{gray} = \text{RGB2GRAY}(I)$$
  2. Apply latitude exponent and shadow scale:
     $$I_{mono} = 255.0 \cdot \left(\frac{I_{gray}}{255.0}\right)^{\gamma_h} \cdot P_{shadow}$$
  3. Merge back to BGR structure:
     $$I_{final} = \text{limit\_and\_cast}([I_{mono}, I_{mono}, I_{mono}])$$

---

## 9. KODAK VISION3 (CINE)
- **Engine Function**: `run_vision3(img, shadow_teal, highlight_amber)`
- **Grain Type**: Fine
- **Visual Intent**: Motion picture film simulation based on Kodak Vision3. Delivers a wide dynamic cinematic color grading featuring teal shadows and warm amber highlights.
- **Parameters**:
  - `Shadow Teal Injection` ($T_{teal} \in [0, 35]$, default: $16$): Injects teal into shadows.
  - `Highlight Amber Bleed` ($A_{amber} \in [0, 30]$, default: $12$): Warm highlight bleed.
  - `Motion Picture Grain` ($G \in [0, 25]$, default: $7$): Cinematic motion grain.
- **Mathematical Formula**:
  Converts to YCrCb space, shifts color difference signals $Cr, Cb$ based on luminance masks:
  $$I_{ycrcb} = \text{RGB2YCrCb}(I)$$
  $$\text{Masks}: \quad M_{dark} = \frac{255.0 - Y}{255.0}, \quad M_{bright} = \frac{Y}{255.0}$$
  $$Cr_{out} = Cr - M_{dark} \cdot (T_{teal} \cdot 0.5) + M_{bright} \cdot (A_{amber} \cdot 0.7)$$
  $$Cb_{out} = Cb + M_{dark} \cdot T_{teal} - M_{bright} \cdot (A_{amber} \cdot 0.4)$$
  $$I_{final} = \text{YCrCb2RGB}([Y, Cr_{out}, Cb_{out}])$$

---

## 10. EKTACHROME E100 (DIAL)
- **Engine Function**: `run_ektachrome(img, blue_pop, contrast)`
- **Grain Type**: Fine
- **Visual Intent**: Simulates Kodak Ektachrome E100 slide film, popular for landscapes and editorial work. Characterized by high clarity, rich blue pops, and clean slide contrast.
- **Parameters**:
  - `Cobalt Blue Multiplier` ($M_{blue} \in [1.0, 1.4]$, default: $1.12$): Selectively amplifies blue saturation.
  - `Contrast Threshold Slope` ($C_s \in [4.0, 8.5]$, default: $5.8$): Slope of the sigmoid curve.
  - `Fine Saturated Grain` ($G \in [0, 20]$, default: $4$): Subtle fine slide grain.
- **Mathematical Formula**:
  1. Blue channel push:
     $$B_{out} = B \cdot M_{blue}$$
     $$I_{pop} = [B_{out}, G, R]$$
  2. Sigmoid curve mapping:
     $$I_{32} = \frac{I_{pop}}{255.0}$$
     $$I_{final} = \text{limit\_and\_cast}\left(\frac{1.0}{1.0 + e^{-C_s \cdot (I_{32} - 0.5)}} \cdot 255.0\right)$$

---

## 11. FUJICOLOR C200 (WARM)
- **Engine Function**: `run_fujicolor_c200(img, green_shadows, warmth)`
- **Grain Type**: Heavy
- **Visual Intent**: Warm consumer color negative film look (Fujicolor C200). Blends warm highlights with slightly green-biased shadow levels.
- **Parameters**:
  - `Green Shadow Bias` ($B_{green} \in [0, 15]$, default: $6$): Green tones in shadows.
  - `Highlight Warmth Push` ($W_{warm} \in [0, 20]$, default: $8$): Pushes red in highlights.
  - `Nostalgic Paper Grain` ($G \in [0, 30]$, default: $10$): Heavy paper grain.
- **Mathematical Formula**:
  $$B_{out} = B \cdot 0.95$$
  $$G_{out} = G^{0.98} + B_{green}$$
  $$R_{out} = R \cdot 1.04 + W_{warm}$$
  $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 12. KODAK PORTRA 400 (SOFT)
- **Engine Function**: `run_portra(img, pastel_gamma, skin_tint)`
- **Grain Type**: Fine
- **Visual Intent**: Professional color portrait negative stock look. Renowned for natural skin tone warmth, soft pastel midtone contrast, and gentle highlight roll-off.
- **Parameters**:
  - `Pastel Midtone Gamma` ($\gamma_p \in [0.9, 1.3]$, default: $1.08$): Compresses midtone contrast for pastel colors.
  - `Organic Skin Warming` ($T_{skin} \in [0, 15]$, default: $5$): Warm peach skin bias.
  - `Micro Portrait Grain` ($G \in [0, 15]$, default: $3$): Smooth micro grain pattern.
- **Mathematical Formula**:
  1. Desaturate base image slightly:
     $$I_{hsv} = \text{RGB2HSV}(I)$$
     $$I_{hsv}[:,:,1] = \text{clip}(I_{hsv}[:,:,1] \cdot 0.85,\, 0,\, 255)$$
     $$I_{bgr} = \text{HSV2RGB}(I_{hsv})$$
  2. Apply channels exposure curves and tinting:
     $$B_{out} = B \cdot 0.96$$
     $$G_{out} = G \cdot \gamma_p$$
     $$R_{out} = R \cdot \gamma_p + T_{skin}$$
     $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 13. LOFI HALATION (GLARE)
- **Engine Function**: `run_halation(img, threshold, size, intensity)`
- **Grain Type**: Midtone
- **Visual Intent**: Simulates the red halation glare characteristic of analog film backing layers. Delivers a soft, glowing bleed around strong highlight boundaries.
- **Parameters**:
  - `Hotspot Cutoff Threshold` ($T_{thresh} \in [160, 245]$, default: $205$): Activation threshold.
  - `Glow Blur Radius Pixels` ($K_{radius} \in [11, 55]$, default: $27$): Bloom radius.
  - `Bulb Overexposure Power` ($P_{glow} \in [5, 45]$, default: $25$): Glow intensity.
  - `Scanner Line Base Noise` ($G \in [0, 35]$, default: $12$): Analog scanning noise.
- **Mathematical Formula**:
  1. Extract grayscale highlight threshold mask:
     $$I_{gray} = \text{RGB2GRAY}(I)$$
     $$M_{thresh} = \begin{cases} 255 & \text{if } I_{gray} \ge T_{thresh} \\ 0 & \text{otherwise} \end{cases}$$
  2. Gaussian blur the highlight mask:
     $$k = \text{odd}(K_{radius})$$
     $$B_{bloom} = \frac{\text{GaussianBlur}(M_{thresh},\, (k, k),\, 0)}{255.0}$$
  3. Mix bloom selectively into BGR channels:
     $$B_{out} = B + B_{bloom} \cdot (P_{glow} \cdot 0.4)$$
     $$G_{out} = G + B_{bloom} \cdot (P_{glow} \cdot 0.2)$$
     $$R_{out} = R + B_{bloom} \cdot P_{glow}$$
     $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$

---

## 14. 90s XENON DIRECT FLASH
- **Engine Function**: `run_xenon_90s(img, curve, saturation)`
- **Grain Type**: Heavy
- **Visual Intent**: Recreates the look of 1990s direct xenon-flash camera lenses. Features harsh contrast, shadow fall-offs, and bold saturation pops.
- **Parameters**:
  - `Sigmoid Flash Contrast` ($C_f \in [4.0, 9.5]$, default: $6.5$): Sigmoid slope factor.
  - `Flash Saturation Pop` ($S_{pop} \in [1.0, 1.7]$, default: $1.25$): Saturation multiplier.
  - `Direct Shadow Silver Grain` ($G \in [0, 40]$, default: $15$): Heavy direct flash grain.
- **Mathematical Formula**:
  1. Apply sigmoid contrast curve:
     $$I_{32} = \frac{I}{255.0}$$
     $$I_{curve} = \frac{1.0}{1.0 + e^{-C_f \cdot (I_{32} - 0.5)}} \cdot 255.0$$
  2. Apply saturation scaling:
     $$I_{hsv} = \text{RGB2HSV}(I_{curve})$$
     $$I_{hsv}[:,:,1] = \text{clip}(I_{hsv}[:,:,1] \cdot S_{pop},\, 0,\, 255)$$
     $$I_{final} = \text{HSV2RGB}(I_{hsv})$$

---

## 15. PACIFIC MISTY COLD
- **Engine Function**: `run_pacific_cold(img, blue, green, desat)`
- **Grain Type**: Midtone
- **Visual Intent**: A highly stylized landscape profile with moody, cool cyan-blue shadow values, deep pine forest greens, and cold desaturated highlights.
- **Parameters**:
  - `Misty Blue Shift Vector` ($V_{blue} \in [0, 45]$, default: $22$): Blue shift in shadows.
  - `Deep Forest Green Shift` ($V_{green} \in [0, 35]$, default: $14$): Green shift.
  - `Chroma Desaturation` ($S_{desat} \in [25, 95]$, default: $50$): General desaturation.
  - `Damp Atmospheric Grain` ($G \in [0, 30]$, default: $8$): Medium damp grain texture.
- **Mathematical Formula**:
  1. Saturation compression:
     $$I_{hsv} = \text{RGB2HSV}(I)$$
     $$I_{hsv}[:,:,1] = \text{clip}\left(I_{hsv}[:,:,1] \cdot \frac{S_{desat}}{100.0},\, 0,\, 255\right)$$
     $$I_{bgr} = \text{HSV2RGB}(I_{hsv})$$
  2. BGR channel shifts:
     $$B_{out} = B + V_{blue}$$
     $$G_{out} = G + V_{green}$$
     $$R_{out} = R - \left\lfloor\frac{V_{blue}}{2}\right\rfloor$$
     $$I_{final} = \text{limit\_and\_cast}([B_{out}, G_{out}, R_{out}])$$
