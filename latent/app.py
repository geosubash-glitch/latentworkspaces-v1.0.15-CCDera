"""Application shell: window, stage navigation, session and undo."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import __version__, theme as T
from .imaging import io as imgio
from .imaging.pipeline import EditState, make_proxy
from .settings import Settings, config_dir, default_photo_folder
from .ui.widgets import UI, Button, WheelRouter, Tooltip
from .workers import Channel, Dispatcher

log = logging.getLogger(__name__)

MOD = "Command" if sys.platform == "darwin" else "Control"
MOD_LABEL = "⌘" if sys.platform == "darwin" else "Ctrl+"

STAGES = (("library", "01", "LIBRARY"), ("looks", "02", "LOOK"), ("develop", "03", "DEVELOP"))

SHORTCUTS = [
    ("Library", [("Choose folder", f"{MOD_LABEL}O"), ("Move selection", "Arrow keys"), ("Open photo", "Enter / double-click"),
                 ("Refresh folder", "F5")]),
    ("Look", [("Pick look", "Arrow keys / click"), ("Develop with look", "Enter / double-click"), ("Back", "Esc")]),
    ("Develop", [("Before / after", "Hold Space or \\"), ("Zoom", "Mouse wheel"), ("Pan", "Drag when zoomed"),
                 ("Fit to screen", f"{MOD_LABEL}0"), ("Crop & rotate", "C"), ("Undo / Redo", f"{MOD_LABEL}Z / {MOD_LABEL}Y"),
                 ("Export", f"{MOD_LABEL}E"), ("Reset a slider", "Double-click it"), ("Type a value", "Click the number")]),
    ("Window", [("Full screen", "F11"), ("Shortcuts", "F1 / ?"), ("Quit", f"{MOD_LABEL}Q")]),
]


class Session:
    """The photo being edited plus per-photo edit history."""

    def __init__(self):
        self.path: Optional[str] = None
        self.image: Optional[np.ndarray] = None
        self.proxy: Optional[np.ndarray] = None
        self.exif: Optional[bytes] = None
        self.state = EditState()
        self.undo: List[EditState] = []
        self.redo: List[EditState] = []
        self._memory: Dict[str, Tuple[EditState, list, list]] = {}

    @property
    def loaded(self) -> bool:
        return self.proxy is not None

    def open(self, path: str, image: np.ndarray, exif: Optional[bytes]):
        if self.path:
            self._memory[self.path] = (self.state, self.undo, self.redo)
        self.path, self.image, self.exif = path, image, exif
        self.proxy = make_proxy(image)
        remembered = self._memory.get(path)
        if remembered:
            self.state, self.undo, self.redo = remembered
        else:
            self.state, self.undo, self.redo = EditState(), [], []

    def has_edits_for(self, path: str) -> bool:
        """Whether the photo has been changed from a fresh, untouched edit."""
        if path == self.path:
            state = self.state
        elif path in self._memory:
            state = self._memory[path][0]
        else:
            return False
        return state.to_dict() != EditState().to_dict()

    def push_undo(self):
        self.undo.append(self.state.copy())
        if len(self.undo) > 100:
            self.undo.pop(0)
        self.redo.clear()

    def undo_step(self) -> bool:
        if not self.undo:
            return False
        self.redo.append(self.state.copy())
        self.state = self.undo.pop()
        return True

    def redo_step(self) -> bool:
        if not self.redo:
            return False
        self.undo.append(self.state.copy())
        self.state = self.redo.pop()
        return True


class LatentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.ui = UI(root)
        self.settings = Settings()
        self.dispatcher = Dispatcher(root)
        self.router = WheelRouter(root)
        self.session = Session()
        self.folder = self._initial_folder()
        self.stage = "library"
        self._fullscreen = False
        self._toast_after = None

        root.title("Latent Studio")
        root.configure(bg=T.BG_VIEW)
        root.minsize(self.ui.px(1024), self.ui.px(640))
        root.report_callback_exception = self._report_exception
        self._set_icon()
        self._build_shell()

        from .ui.library import LibraryView
        from .ui.looks import LooksView
        from .ui.develop import DevelopView
        self.views = {
            "library": LibraryView(self),
            "looks": LooksView(self),
            "develop": DevelopView(self),
        }
        self._bind_keys()
        self.go("library")
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # ------------------------------------------------------------------ shell
    def _initial_folder(self) -> str:
        last = self.settings.get("last_folder")
        if last and os.path.isdir(last):
            return last
        return default_photo_folder()

    def _set_icon(self):
        try:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            if sys.platform.startswith("win") and os.path.exists(os.path.join(base, "app_logo.ico")):
                self.root.iconbitmap(default=os.path.join(base, "app_logo.ico"))
            self._icon = tk.PhotoImage(file=os.path.join(base, "app_logo.png"))
            self._icon_small = self._icon.subsample(max(1, self._icon.width() // 64))
            self.root.iconphoto(True, self._icon_small)
        except Exception:
            log.debug("icon not set", exc_info=True)

    def _build_shell(self):
        ui = self.ui
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.viewport_host = tk.Frame(self.root, bg=T.BG_VIEW)
        self.viewport_host.grid(row=0, column=0, sticky="nsew")
        tk.Frame(self.root, bg=T.LINE, width=1).grid(row=0, column=1, sticky="ns")

        sw = self.root.winfo_screenwidth()
        panel_w = max(ui.px(360), min(ui.px(460), int(sw * 0.25)))
        self.panel = tk.Frame(self.root, bg=T.BG_PANEL, width=panel_w)
        self.panel.grid(row=0, column=2, sticky="ns")
        self.panel.grid_propagate(False)
        self.panel.pack_propagate(False)
        self.panel_width = panel_w

        # Brand + stepper
        header = tk.Frame(self.panel, bg=T.BG_PANEL)
        header.pack(fill="x", padx=ui.px(20), pady=(ui.px(16), 0))
        brand = tk.Frame(header, bg=T.BG_PANEL)
        brand.pack(fill="x")
        try:
            from PIL import Image, ImageTk
            logo = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app_logo.png"))
            logo = logo.resize((ui.px(26), ui.px(26)), Image.Resampling.LANCZOS)
            self._brand_logo = ImageTk.PhotoImage(logo)
            tk.Label(brand, image=self._brand_logo, bg=T.BG_PANEL).pack(side="left", padx=(0, ui.px(10)))
        except Exception:
            pass
        tk.Label(brand, text="LATENT", bg=T.BG_PANEL, fg=T.TEXT_HI, font=ui.fonts.brand).pack(side="left")
        tk.Label(brand, text=f"STUDIO  v{__version__}", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro).pack(side="left", padx=(ui.px(8), 0), pady=(ui.px(3), 0))
        help_btn = tk.Label(brand, text="?", bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.mono_bold, cursor="hand2",
                            padx=ui.px(6), highlightthickness=1, highlightbackground=T.LINE_STRONG)
        help_btn.pack(side="right")
        help_btn.bind("<Button-1>", lambda e: self.show_shortcuts())
        Tooltip(help_btn, ui, "Keyboard shortcuts (F1)")

        stepper = tk.Frame(header, bg=T.BG_PANEL)
        stepper.pack(fill="x", pady=(ui.px(16), 0))
        self._steps = {}
        for i, (key, num, label) in enumerate(STAGES):
            cell = tk.Frame(stepper, bg=T.BG_PANEL, cursor="hand2")
            cell.pack(side="left", expand=True, fill="x")
            n = tk.Label(cell, text=num, bg=T.BG_PANEL, font=ui.fonts.micro, anchor="w")
            n.pack(fill="x")
            t = tk.Label(cell, text=label, bg=T.BG_PANEL, font=ui.fonts.mono_bold, anchor="w")
            t.pack(fill="x")
            bar = tk.Frame(cell, height=max(2, ui.px(2)), bg=T.LINE)
            bar.pack(fill="x", pady=(ui.px(6), 0), padx=(0, ui.px(6) if i < 2 else 0))
            for w in (cell, n, t, bar):
                w.bind("<Button-1>", lambda e, k=key: self.go(k))
            self._steps[key] = (n, t, bar, cell)

        self.panel_host = tk.Frame(self.panel, bg=T.BG_PANEL)
        self.panel_host.pack(fill="both", expand=True)

        # Status bar
        self.status = tk.Frame(self.root, bg=T.BG_PANEL, height=ui.px(26))
        self.status.grid(row=1, column=0, columnspan=3, sticky="ew")
        tk.Frame(self.status, bg=T.LINE, height=1).pack(fill="x", side="top")
        self.status_left = tk.Label(self.status, text="", bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.micro, anchor="w")
        self.status_left.pack(side="left", padx=ui.px(12), pady=ui.px(4))
        self.status_action = tk.Label(self.status, text="", bg=T.BG_PANEL, fg=T.ACCENT, font=ui.fonts.micro, cursor="hand2")
        self.status_action.pack(side="left")
        self.status_right = tk.Label(self.status, text="", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=ui.fonts.micro, anchor="e")
        self.status_right.pack(side="right", padx=ui.px(12))

    # ------------------------------------------------------------ navigation
    def can_enter(self, stage: str) -> bool:
        return stage == "library" or self.session.loaded

    def go(self, stage: str):
        if not self.can_enter(stage):
            self.toast("Open a photo from the library first.")
            return
        if stage != self.stage or not getattr(self, "_shown_once", False):
            self.views[self.stage].hide()
            self.stage = stage
            self.views[stage].show()
            self._shown_once = True
        for key, (n, t, bar, cell) in self._steps.items():
            active = key == stage
            enabled = self.can_enter(key)
            color = T.TEXT_HI if active else (T.TEXT_DIM if enabled else T.TEXT_FAINT)
            n.config(fg=T.ACCENT if active else T.TEXT_FAINT)
            t.config(fg=color)
            bar.config(bg=T.ACCENT if active else (T.LINE_STRONG if enabled else T.LINE))
            for w in (cell, n, t, bar):
                w.config(cursor="hand2" if enabled else "arrow")

    def set_status(self, left: str = None, right: str = None):
        if left is not None:
            self.status_left.config(text=left)
        if right is not None:
            self.status_right.config(text=right)

    def toast(self, message: str, action: Optional[Tuple[str, callable]] = None, ms: int = 6000):
        self.status_left.config(text=message, fg=T.TEXT_HI)
        if action:
            label, fn = action
            self.status_action.config(text=f"  {label} ›")
            self.status_action.bind("<Button-1>", lambda e: fn())
        else:
            self.status_action.config(text="")
        if self._toast_after:
            self.root.after_cancel(self._toast_after)

        def clear():
            self._toast_after = None
            self.status_left.config(fg=T.TEXT_DIM)
            self.status_action.config(text="")
            self.views[self.stage].refresh_status()

        self._toast_after = self.root.after(ms, clear)

    # --------------------------------------------------------------- folder
    def choose_folder(self):
        chosen = filedialog.askdirectory(parent=self.root, initialdir=self.folder, title="Choose a folder of photos")
        if chosen:
            self.set_folder(chosen)

    def set_folder(self, folder: str):
        self.folder = os.path.abspath(folder)
        self.settings.set("last_folder", self.folder)
        self.settings.save()
        self.views["library"].load_folder()
        if self.stage != "library":
            self.go("library")

    # ---------------------------------------------------------------- photo
    def open_photo(self, path: str):
        """Load full resolution in the background, then go to Look."""
        loader = getattr(self, "_load_channel", None) or Channel(self.dispatcher, "load")
        self._load_channel = loader
        name = os.path.basename(path)
        self.set_status(f"Opening {name}…")
        self.root.config(cursor="watch")

        def job(_token):
            return imgio.load_image(path)

        def done(result):
            self.root.config(cursor="")
            image, exif = result
            self.session.open(path, image, exif)
            self.views["looks"].on_photo_changed()
            self.views["develop"].on_photo_changed()
            self.go("looks")

        def failed(exc):
            self.root.config(cursor="")
            self.set_status("")
            messagebox.showerror("Can't open photo", f"{name} could not be opened.\n\n{exc}", parent=self.root)

        loader.submit(job, done, failed)

    # ----------------------------------------------------------------- undo
    def push_undo(self):
        self.session.push_undo()

    def undo(self, _e=None):
        if self.stage == "develop" and self.session.undo_step():
            self.views["develop"].sync_from_state()
            self.toast("Undo")

    def redo(self, _e=None):
        if self.stage == "develop" and self.session.redo_step():
            self.views["develop"].sync_from_state()
            self.toast("Redo")

    # ----------------------------------------------------------------- keys
    def _typing(self) -> bool:
        """True when a key press belongs to a text field or an open dialog."""
        try:
            w = self.root.focus_get()
        except (KeyError, tk.TclError):
            return True
        if w is None:
            return False
        if w.winfo_toplevel() is not self.root:
            return True  # dialogs handle their own keys
        return isinstance(w, (tk.Entry, tk.Text)) or w.winfo_class() in ("TEntry", "TCombobox", "Entry")

    def _bind_keys(self):
        r = self.root

        def guarded(fn):
            def handler(e):
                if self._typing():
                    return
                return fn(e)
            return handler

        r.bind_all(f"<{MOD}-o>", lambda e: self.choose_folder())
        r.bind_all(f"<{MOD}-q>", lambda e: self.quit())
        r.bind_all(f"<{MOD}-z>", guarded(self.undo))
        r.bind_all(f"<{MOD}-Z>", guarded(self.redo))
        r.bind_all(f"<{MOD}-Shift-z>", guarded(self.redo))
        r.bind_all(f"<{MOD}-y>", guarded(self.redo))
        r.bind_all("<F11>", lambda e: self.toggle_fullscreen())
        r.bind_all("<F1>", lambda e: self.show_shortcuts())
        r.bind_all("<question>", guarded(lambda e: self.show_shortcuts()))
        r.bind_all("<Escape>", guarded(self._on_escape))
        for seq in ("<Left>", "<Right>", "<Up>", "<Down>", "<Return>", "<KP_Enter>", "<BackSpace>", "<F5>",
                    "<KeyPress-space>", "<KeyRelease-space>", "<KeyPress-backslash>", "<KeyRelease-backslash>",
                    "<KeyPress-c>", f"<{MOD}-e>", f"<{MOD}-0>", f"<{MOD}-equal>", f"<{MOD}-plus>", f"<{MOD}-minus>"):
            r.bind_all(seq, guarded(lambda e, s=seq: self.views[self.stage].on_key(s, e)))

    def _on_escape(self, e):
        if self._fullscreen:
            self.toggle_fullscreen()
        elif self.stage == "develop":
            self.go("looks")
        elif self.stage == "looks":
            self.go("library")

    def toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)

    def show_shortcuts(self):
        ui = self.ui
        win = tk.Toplevel(self.root)
        win.title("Keyboard shortcuts")
        win.configure(bg=T.BG_PANEL)
        win.transient(self.root)
        win.resizable(False, False)
        body = tk.Frame(win, bg=T.BG_PANEL)
        body.pack(padx=ui.px(28), pady=ui.px(24))
        tk.Label(body, text="KEYBOARD SHORTCUTS", bg=T.BG_PANEL, fg=T.TEXT_HI, font=ui.fonts.title).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, ui.px(12)))
        row = 1
        for group, items in SHORTCUTS:
            tk.Label(body, text=group.upper(), bg=T.BG_PANEL, fg=T.ACCENT, font=ui.fonts.label).grid(row=row, column=0, sticky="w", pady=(ui.px(10), ui.px(4)))
            row += 1
            for action, keys in items:
                tk.Label(body, text=action, bg=T.BG_PANEL, fg=T.TEXT, font=ui.fonts.body).grid(row=row, column=0, sticky="w", padx=(0, ui.px(40)))
                tk.Label(body, text=keys, bg=T.BG_PANEL, fg=T.TEXT_DIM, font=ui.fonts.mono).grid(row=row, column=1, sticky="w")
                row += 1
        Button(body, ui, "CLOSE", command=win.destroy).grid(row=row, column=1, sticky="e", pady=(ui.px(18), 0))
        win.bind("<Escape>", lambda e: win.destroy())
        self._center(win)
        win.focus_set()

    def _center(self, win: tk.Toplevel):
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

    # --------------------------------------------------------------- errors
    def _report_exception(self, exc, val, tb):
        log.error("Unhandled UI error", exc_info=(exc, val, tb))
        messagebox.showerror("Something went wrong",
                             f"{val}\n\nDetails were written to:\n{os.path.join(config_dir(), 'latent.log')}",
                             parent=self.root)

    def reveal(self, path: str):
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except OSError:
            log.warning("could not reveal %s", path, exc_info=True)

    def quit(self):
        try:
            self.settings.set("window_state", self.root.state())
            self.settings.save()
        finally:
            self.dispatcher.stop()
            self.root.destroy()


# ---------------------------------------------------------------------------
def _enable_windows_dpi_awareness():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _setup_logging():
    handlers = [logging.StreamHandler(sys.stderr)] if sys.stderr else []
    try:
        handlers.append(logging.FileHandler(os.path.join(config_dir(), "latent.log"), encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_logging()
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    try:
        app = LatentApp(root)
    except Exception:
        log.exception("startup failed")
        messagebox.showerror("Latent Studio could not start", traceback.format_exc())
        return 1
    if argv:
        target = os.path.abspath(argv[0])
        if os.path.isdir(target):
            app.set_folder(target)
        elif os.path.isfile(target):
            app.set_folder(os.path.dirname(target))
            app.open_photo(target)
    root.deiconify()
    _maximize(root)
    root.mainloop()
    return 0


def _maximize(root: tk.Tk):
    # A sensible size first, in case the window manager ignores "zoomed".
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{int(w * 0.9)}x{int(h * 0.85)}+{int(w * 0.05)}+{int(h * 0.05)}")
    try:
        if sys.platform.startswith("win"):
            root.state("zoomed")
        elif sys.platform == "darwin":
            w, h = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{int(w * 0.92)}x{int(h * 0.88)}+{int(w * 0.04)}+{int(h * 0.04)}")
        else:
            root.attributes("-zoomed", True)
    except tk.TclError:
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
