# LATENT // User Workflow & Task Flow

LATENT is structured as a linear, three-stage workflow. Each stage has a distinct user role and technical implementation.

---

## Stage 1: Explorer (Mount & Mounting Deck)
### User Task Flow
1. **Launch**: The application starts in full-screen mode showing a clean, dark-themed mounting deck.
2. **Mount Directory**: The user clicks `NAVIGATE` to select a folder on their system. The mounting deck scans the folder for image files (`.jpg`, `.jpeg`, `.png`, `.dng`).
3. **Pristine Discovery**: The files are displayed in a 5-column grid. The user single-clicks any file to see its metadata readout (Filename and allocation size in MB) and a clean, unfiltered preview on the left panel.
4. **Transition**: Double-clicking any image cell mounts it as the active image and transitions to **Stage 2 (Grid View)**.

### Technical Implementation
- **Directory Scanning**: Uses a background thread to generate and cache thumbnails asynchronously to prevent disk-I/O from freezing the mounting deck.
- **FS Event Observer**: Uses the `watchdog` library to monitor folder changes in real-time, automatically refreshing the deck if new files are added.
- **Pristine Previews**: Caches the base resized preview image in memory to make selection previews instant.

---

## Stage 2: Filter Grid (Emulsion Profile Evaluation)
### User Task Flow
1. **Evaluation**: The user sees the active image processed through 15 different film simulation profiles arranged in a 5x3 grid.
2. **Dynamic Previewing**: Hovering the mouse over any grid cell updates the left-hand preview panel instantly with that filter's characteristics.
3. **Selection**: Single-clicking a grid cell selects it as the active profile.
4. **Transition**: Double-clicking a grid cell commits the profile selection and enters **Stage 3 (Workbench)** for advanced grading.

### Technical Implementation
- **Parallel Thumbnail Generation**: Renders the 15 grid cells asynchronously using a multi-threaded rendering lock (`self.render_lock`).
- **Sub-Millisecond Preview Caching**: When hovering, the app avoids reading the source image from disk again. It pulls the cached resized base image from memory, runs the selected filter's CPU engine, and displays the result with <2ms latency.

---

## Stage 3: Workbench (Analog Calibration Lab)
### User Task Flow
1. **Spline Tone Mapping**: The user opens the Geometry Transforms window or adjusts tone curve points directly to modify luminance distributions.
2. **Color Grading**: Dragging the crosshairs on the 3-Way Color Wheels offsets the shadow, midtone, and highlight regions to apply custom split-toning.
3. **Camera Calibration**: Fine-tunes Red, Green, and Blue primary sensor saturation to calibrate raw color response.
4. **Global Correction**: Adjusts Exposure, Contrast, Saturation, Temperature, Tint, Highlights, Shadows, Sharpness, and Vignetting.
5. **Compare**: Holding the `Spacebar` or clicking the compare button shows the before/after state instantly.
6. **Export**: Clicking the export icon exports a high-resolution, full-frame image with the complete grading pipeline applied.

### Technical Implementation
- **Main-Thread Parameter Snapshotting**: Captures all slider, wheel, and curve points into plain Python objects, ensuring thread safety.
- **Asynchronous Background Grading Loop**: Offloads all heavy image calculations to a background worker thread, keeping the GUI thread fully responsive.
- **Frame Coalescing**: If the user drags a slider rapidly, the rendering thread skips intermediate frames and only renders the latest position, avoiding event queue backups.
- **Native Canvas Panning**: Employs Tkinter's native `scan_mark` and `scan_dragto` canvas methods for smooth, hardware-accelerated viewport navigation.
