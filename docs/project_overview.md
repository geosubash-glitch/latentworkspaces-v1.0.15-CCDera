# LATENT // Project Overview

## 1. Intent & Vision
**LATENT** is a specialized desktop image processing workstation designed to bridge the gap between tactile analog aesthetics and modern digital workflows. The software takes its name from the *latent image*—the invisible, undeveloped image formed on silver halide photographic film upon exposure to light, waiting to be revealed through chemical processing.

Unlike generic image editors, LATENT is specifically designed and fine-tuned for **CCD sensor cameras**. The film stock simulations and processing pipelines are calibrated directly against the unique, rich spectral responses, color saturation profiles, and pixel dynamics of CCD sensors.

The project is built on the belief that analog film characteristics (color response curves, emulsion grain structure, highlight halation, and organic color calibration) are not merely filters to be overlaid, but cohesive physical processes that must be simulated mathematically.

---

## 2. Purpose: What & Why

### The "What"
LATENT is a three-stage non-destructive image-processing workstation providing:
1. **01 Library**: a responsive photo browser with a large preview and file details.
2. **02 Look**: the photo rendered through all 15 film profiles side by side, with a large hover preview.
3. **03 Develop**: a grading workbench with histogram and luma waveform scopes, an interactive cubic-spline tone curve, 3-way colour wheels, CCD sensor calibration, crop/straighten/perspective, and full-resolution export.

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

* **Aesthetic unity**: a high-contrast laboratory-console look taken from the original Illustrator layouts: near-black surfaces (`#020202` viewport, `#080808` panels), hairline rules, monospaced labels, and a single yellow accent (`#ffcc00`) reserved for the current step, the primary action and values you have changed.
* **Guided, not unbounded**: three numbered stages, each with one obvious next action. Controls are bounded to realistic chemical and hardware limits.
* **Always know what changed**: every slider rests at 0 and highlights when moved; sections, wheels and the curve each reset on their own; undo covers every gesture.
* **Direct manipulation**: drag on the image to pan, scroll to zoom, hold Space to compare, drag crop handles, click to type exact values.
* **Zero-latency GUI**: rendering runs off the UI thread with frame coalescing, so dragging stays fluid and the window never freezes, even during export.
* **Works everywhere**: responsive layout, DPI-aware text, keyboard navigation, Unicode file paths and camera EXIF orientation.
