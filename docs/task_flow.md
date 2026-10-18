# LATENT // User Workflow & Task Flow

LATENT is a linear, three-stage workflow: **Explorer → Emulsion Grid → Workbench**. BACK (or Esc) steps back one stage.

## Stage 1: Explorer (mounting deck)
1. The app opens on the last folder you used (first run: your Pictures folder).
2. **NAVIGATE** (`Ctrl+O`) mounts a folder. Files appear in a five-column grid, sorted naturally (`IMG_2` before `IMG_10`).
3. Single-click a file to see its readout (MOUNT TARGET, FILE ID, ALLOCATION, DIMENSIONS) and a clean preview.
4. Double-click (or `Enter`) mounts it as the active image and moves to the Emulsion Grid.

*Implementation:* thumbnails load lazily, visible rows first, on a worker thread with a bounded cache. The folder is re-scanned every 2 s while the Explorer is visible, so new files show up automatically.

## Stage 2: Emulsion Grid (profile evaluation)
1. The active image is rendered through all 15 profiles on a 5×3 board.
2. Hovering a cell updates the readout (ACTIVE LOG, FILTER, SPEC) and the large preview.
3. Click to select; double-click, `Enter` or **WORKBENCH** opens the Workbench.

*Implementation:* the board renders outward from the selected cell; the preview is cached per profile and panel size.

## Stage 3: Workbench (analog calibration lab)
* **Scope**: click it to toggle histogram ↔ luma waveform.
* **BACK / profile name / SAVE**
* **Profile sliders**: the selected emulsion's own controls.
* **CROP/ROTATE/RESIZE/WARP** opens GEOMETRY CONTROLS (aspect presets, ±90°, angle, keystone, output size).
* **[ TONE CURVE ]**: click to add a point, drag to shape, double-click a point to remove it.
* **[ 3-WAY COLOR WHEELS ]**: drag to tint; double-click or right-click to reset a wheel.
* **[ CAMERA CALIBRATION ]** and **[ ADJUSTMENTS ]**.

Double-click any slider to reset it; click its value to type a number. Hold `Space` (or the ◧ button) to compare with the original. Scroll to zoom, drag or use the scrollbars to pan. `Ctrl+Z` / `Ctrl+Y` undo and redo. **SAVE** (`Ctrl+E`) exports at full resolution in the background; the original is never modified.
