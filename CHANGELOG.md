# Changelog

## 2.0.0 — ground-up rework

v1 was a single 2,850-line file. v2 splits it into an image engine with no UI code (`latent/imaging`), stage views (`latent/ui`), and a small application shell, with automated tests and a release pipeline.

### Image quality bugs fixed

* **Colour casts from un-normalised power curves.** Astia, Kodachrome, Superia, Fujicolor and Portra applied exponents to raw 0–255 values (`r ** 1.12`). Mid-grey came out as saturated orange (Kodachrome `[61,207,237]`), whites turned magenta (Superia) and skin went red (Astia). All tone curves now work on normalised 0–1 values, so black stays black and white stays white.
* **Crushed blacks, clipped whites.** The Velvia, Xenon Flash and Ektachrome sigmoid curves mapped black to about 10 and white to about 244. The curves are now rescaled to pass through 0 and 1.
* **Kodak Vision3 wrap-around.** Values were cast to `uint8` without clipping, so saturated colours wrapped around to wrong hues.
* **Colour noise in black & white.** Ilford HP5 received per-channel RGB grain. Monochrome stocks now get monochrome grain.
* **Preview ≠ export.** Grain was per-pixel, so a 6000 px export had 4× finer grain than the preview. Its random texture also changed between preview and export. Grain is now seeded and scales with the frame, like grain on a real negative. Halation radius and sharpening radius scale the same way.
* **Straighten left black corners.** Rotation now scales to fill the frame. Added proper 90° turns: v1 rotated 90° inside the old frame and cut off most of the image.
* Calibration results depended on the order of the R/G/B adjustments; they are now independent.

### Stability & backend bugs fixed

* **Thread-safety crashes.** The render thread called Tk (`winfo_width`, `after`) from a background thread, which can crash or freeze on Windows. It also read the slider "snapshot" while the UI was rewriting it. Workers now receive an immutable copy of the edit state, and results go back to the UI through a queue.
* **Lost renders.** A race on `render_thread_active` could drop the final slider position.
* **Folder watcher watched the wrong folder.** It watched the install directory (`.`) instead of the chosen folder, and never re-listed files, so new photos never appeared. Replaced with lightweight polling of the current folder.
* **Photos with non-English paths failed to open or export on Windows** (`cv2.imread`/`imwrite` limitation). File I/O now uses Pillow.
* **Rotated camera photos** (EXIF orientation) showed sideways. They are now shown upright, and exports keep the camera EXIF with orientation reset.
* **Silent 100-file limit** in the library and no sorting. The library is now unlimited, naturally sorted and lazily loaded.
* **Accidental stage jumps.** Double-click was detected with a hand-rolled timer shared across screens, so a quick second click after changing screens jumped straight into the workbench.
* **Zoom memory blow-up.** Zooming resized the whole image up to 10× (a 12000 px bitmap). Only the visible region is drawn now.
* Export ran on the UI thread and froze the app; it now runs in the background with a progress indicator.
* Holding Space in a text field toggled before/after; key auto-repeat made the compare view flicker.
* Undo did not include the tone curve; the tone curve had no editor at all.
* The app opened on the install folder instead of your Pictures folder, and did not remember the last folder.
* Colour wheel generation ran 12,000 per-pixel OpenCV calls at start-up; it is now vectorised.

### Interface & interaction design

* The layout is responsive instead of fixed pixel positions computed from screen width, so it works on 1366×768 laptops, 16:10 and 4K screens. It is DPI-aware on Windows, so text is no longer blurry at 125–200 % scaling.
* The app opens maximised in a normal window rather than forced borderless full screen (F11 toggles full screen).
* A clear three-step flow — **01 Library → 02 Look → 03 Develop** — shown in a stepper you can click.
* The palette comes from the original Illustrator layouts. The two slightly different yellows are unified into one accent, and Courier New is replaced with a crisper monospace (Cascadia/Consolas/Menlo) plus a readable sans for descriptions.
* Hand-drawn sliders fill from their neutral point. Double-click resets a slider; click its value to type a number. Every slider reads 0 at rest.
* Controls are grouped into collapsible sections (Look, Light, Color, Tone curve, Color grading, Detail & effects, Calibration), each with its own reset.
* New interactive tone-curve editor with a histogram backdrop.
* Colour wheels are laid out side by side, show their strength, and reset on double-click.
* Crop & Rotate dialog with aspect presets (with orientation swap), 90° turns, straighten, perspective and linked output size.
* Zoom toolbar, before/after button, output size readout.
* A status bar with context hints and export confirmation ("Show in folder").
* Keyboard navigation everywhere, plus a shortcuts sheet (F1).
* Edits are remembered per photo within a session; the library marks edited photos.

### Install & distribution

* One-click Windows installer (per-user, no admin rights, Start menu and desktop shortcuts, uninstaller, closes a running copy first).
* Portable Windows zip, macOS app and Linux build.
* GitHub Actions builds and smoke-tests every push; tagging `vX.Y.Z` publishes a release with stable download links.
* The source launchers use a private virtual environment instead of installing packages system-wide, and find Python via the `py` launcher.
* Dropped the `watchdog` dependency; switched to `opencv-python-headless`.
