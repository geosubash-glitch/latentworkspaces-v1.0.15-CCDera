# LATENT // Project Overview

## 1. Intent & Vision
**LATENT** is a specialized desktop image processing workstation designed to bridge the gap between tactile analog aesthetics and modern digital workflows. The software takes its name from the *latent image*—the invisible, undeveloped image formed on silver halide photographic film upon exposure to light, waiting to be revealed through chemical processing.

Unlike generic image editors, LATENT is specifically designed and fine-tuned for **CCD sensor cameras**. The film stock simulations and processing pipelines are calibrated directly against the unique, rich spectral responses, color saturation profiles, and pixel dynamics of CCD sensors.

The project is built on the belief that analog film characteristics (color response curves, emulsion grain structure, highlight halation, and organic color calibration) are not merely filters to be overlaid, but cohesive physical processes that must be simulated mathematically.

---

## 2. Purpose: What & Why

### The "What"
LATENT is a three-stage non-destructive image-processing workstation providing:
1. **Pristine Discovery (Explorer)**: A file selection deck aligned with scaled coordinates to quickly preview and select image targets.
2. **Emulsion Profile Evaluation (Grid View)**: An interactive 15-cell grid displaying the mounted image processed through 15 distinct film simulation profiles in real-time.
3. **Advanced Analog Workbench**: A dedicated hardware-simulation console equipped with live Luma Waveforms, interactive cubic spline tone curves, 3-way color grading wheels, CCD-optimized sensor calibration, and geometry corrections.

### The "Why"
Traditional graphic software and massive suites (like Adobe Illustrator, Lightroom, or Photoshop) are incredibly powerful, but they present a massive, unguided canvas. You can do *anything* in them, but you often cannot reach where you want to go because there are too many options, too many sliders, and no clear direction. The user gets lost in infinite choices.

LATENT is designed to solve this "too-muchness" problem. It serves as an opinionated, constrained environment that helps photographers **get to their creative intent faster**. Rather than starting from a blank state, the user leverages authentic emulsion bases and direct hardware-modeled parameters to make decisive, artistic steps immediately.

---

## 3. Core Values: Authenticity & Function-Formed Design

LATENT places a paramount value on **authenticity** in every process, step, and calculation. This design philosophy rejects superficial tricks in favor of function-formed design:

* **No Arbitrary Overlays**: The software completely rejects random grain overlays, flat noise textures, or static image filters.
* **Mathematical Integrity**: Every stage of the pipeline—whether it is the luminosity-weighted silver grain simulation, the tridiagonal matrix spline tone curves, or the Rec. 709 luminance-weighted color wheels—is implemented using precise mathematical equations. These functions model actual physics, optics, and chemical behaviors.
* **Cohesive Pipeline Integration**: Filter stocks are computed natively at the pixel level. By processing color channels, exposure slopes, and chromatic shifts mathematically, the output remains structurally authentic, preserving the underlying integrity of the image data.

---

## 4. Design & Usability Principles

* **Aesthetic Unity**: Built around a high-contrast industrial laboratory theme using monospaced typography (`Courier New`) and clean outline borders matching laboratory hardware consoles.
* **Physical Constraints**: Controls are bounded to mimic real chemical and hardware limits, guiding the user toward realistic outcomes.
* **Zero-Latency GUI**: High-throughput background rendering loop ensures that the interface remains running at 60fps, keeping slider dragging completely fluid.
