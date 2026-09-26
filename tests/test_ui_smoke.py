"""Drives the real Tk app through Library -> Look -> Develop -> Export.

Needs a display; CI runs it under xvfb. Skipped automatically otherwise.
"""
import os
import time
import traceback

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    from latent.app import LatentApp
    errors = []
    a = LatentApp(root)
    root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))
    root.geometry("1400x860+0+0")
    a._errors = errors
    yield a
    root.destroy()


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def wait_for(root, cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def make_photos(folder):
    from PIL import Image
    folder.mkdir()
    rng = np.random.default_rng(0)
    for i, name in enumerate(["a.jpg", "b ü.jpg", "c.png"]):
        arr = (rng.random((300, 450, 3)) * 255).astype(np.uint8)
        Image.fromarray(arr).save(folder / name)


def test_full_workflow(app, tmp_path):
    root = app.root
    photos = tmp_path / "photos"
    make_photos(photos)
    app.set_folder(str(photos))
    lib = app.views["library"]
    assert [f.name for f in lib.files] == ["a.jpg", "b ü.jpg", "c.png"]
    assert wait_for(root, lambda: len(lib.grid.images) == 3), "thumbnails did not load"

    lib.grid.set_selected(1)
    lib._open_selected()
    assert wait_for(root, lambda: app.stage == "looks")
    looks = app.views["looks"]
    assert wait_for(root, lambda: len(looks.grid.images) == 15), "look grid did not render"

    looks.grid.set_selected(7)
    looks._develop()
    assert app.stage == "develop"
    dev = app.views["develop"]
    assert wait_for(root, lambda: dev.rendered is not None)
    assert dev.rendered.shape[:2] == (300, 450)

    app.push_undo()
    dev.sliders["exposure"].set(20, notify=True)
    assert app.session.state.exposure == 120
    app.undo()
    assert app.session.state.exposure == 100
    app.redo()
    assert app.session.state.exposure == 120

    from latent.imaging.pipeline import Geometry
    app.session.state.geometry = Geometry(quarter_turns=1, crop_l=10, crop_r=90)
    dev.request_render()
    assert wait_for(root, lambda: dev.rendered is not None and dev.rendered.shape[1] < dev.rendered.shape[0])

    out = tmp_path / "out.jpg"
    import latent.ui.develop as develop_mod
    develop_mod.filedialog.asksaveasfilename = lambda **kw: str(out)
    dev.export()
    assert wait_for(root, lambda: out.exists(), timeout=30)
    pump(root, 0.3)
    from PIL import Image
    with Image.open(out) as im:
        assert im.size == (240, 450)  # rotated, then 80% of the width

    app.go("library")
    assert lib.grid.subtitles[1].endswith("EDITED")
    assert not app._errors, app._errors
