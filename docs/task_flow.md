# LATENT // User Workflow & Task Flow

LATENT is a linear, three-stage workflow shown as a stepper at the top of the side panel: **01 Library → 02 Look → 03 Develop**. You can always step back; later stages unlock once a photo is open.

## 01 Library — choose a photo
1. The app opens on the last folder you used (first run: your Pictures folder).
2. **Choose folder…** (`Ctrl+O`) mounts a folder. Photos appear in a responsive grid, sorted naturally (`IMG_2` before `IMG_10`), with size and dimensions.
3. Click (or use arrow keys) to select; the side panel shows a large preview, dimensions, file size and date.
4. **Open photo** / double-click / `Enter` loads it at full resolution in the background and moves to Look.

*Implementation:* thumbnails load lazily for the visible rows first, on a worker thread, with a bounded cache. The folder is re-scanned every 2 s while the Library is visible, so new files show up automatically.

## 02 Look — compare film stocks
1. All 15 profiles render on your photo. Cells take the photo's shape.
2. Hover any cell: the side panel shows it large, with its description and grain type.
3. Click to select, double-click / `Enter` / **Develop with this look** to continue. `Esc` goes back.

*Implementation:* the grid renders outward from the selected look so the area you are looking at fills in first; the large preview is cached per look and panel size.

## 03 Develop — grade and export
Side panel, top to bottom:
* **← Look**, **Undo / Redo**, **Export**
* Histogram / waveform scope and **Reset all**
* **Look** — the profile's own controls
* **Light** — exposure, contrast, highlights, shadows
* **Color** — temperature, tint, saturation
* **Tone curve** — click to add a point, drag to shape, double-click a point to remove
* **Color grading** — shadows / midtones / highlights wheels
* **Detail & effects** — sharpening, vignette
* **Calibration** — red, green, blue primary saturation (collapsed by default)

Every slider rests at 0 and fills from 0 toward its value. Double-click resets; click the number to type.

Viewport toolbar: fit, zoom − / +, **Before / After** (or hold `Space`), **Crop & Rotate** (`C`), output size.

**Export** (`Ctrl+E`) asks for a file name (JPEG, PNG or TIFF), develops at full resolution in the background and offers **Show in folder** when done. The original is never modified.
