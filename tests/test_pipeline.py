import os

import numpy as np
import pytest

from latent.imaging import filters, io, pipeline, scopes
from latent.imaging.pipeline import EditState, Geometry


def gradient(w=256, h=16):
    row = np.linspace(0, 255, w).astype(np.uint8)
    return np.dstack([np.tile(row, (h, 1))] * 3)


def photo(w=320, h=200, seed=1):
    rng = np.random.default_rng(seed)
    base = cv2_resize(rng.integers(0, 256, (10, 16, 3), dtype=np.uint8), w, h)
    return base


def cv2_resize(img, w, h):
    import cv2
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC)


@pytest.mark.parametrize("profile", filters.PROFILES, ids=lambda p: p.name)
def test_engines_return_valid_images(profile):
    img = photo()
    args, _ = profile.split_params(profile.defaults)
    out = profile.engine(img, *args)
    assert out.shape == img.shape and out.dtype == np.uint8


@pytest.mark.parametrize("profile", filters.PROFILES, ids=lambda p: p.name)
def test_engines_stay_near_neutral_on_grey(profile):
    """v1 bug: un-normalised power curves turned mid-grey orange/magenta."""
    if profile.key in ("PACIFIC MISTY COLD", "KODAK VISION3 (CINE)"):
        pytest.skip("deliberately tinted look")
    grey = np.full((8, 8, 3), 128, np.uint8)
    args, _ = profile.split_params(profile.defaults)
    out = profile.engine(grey, *args).astype(int)[0, 0]
    assert out.max() - out.min() <= 40, out


@pytest.mark.parametrize("key", ["VELVIA VIVID (SLIDE)", "90S XENON DIRECT FLASH", "EKTACHROME E100 (DIAL)", "ILFORD HP5 PLUS (B&W)"])
def test_contrast_curves_keep_black_and_white(key):
    p = filters.FILTER_REGISTRY[key]
    args, _ = p.split_params(p.defaults)
    out = p.engine(gradient(), *args)
    assert out[0, 0].max() <= 3
    assert out[0, -1].min() >= 250


def test_default_edit_is_identity_apart_from_profile():
    img = photo()
    state = EditState()
    prof = pipeline.apply_profile(img, state)
    assert np.array_equal(pipeline.develop(img, state), prof)


def test_grain_is_deterministic_and_scales_with_frame():
    img = np.full((600, 900, 3), 128, np.uint8)
    a = pipeline.apply_grain(img, 20, "midtone")
    b = pipeline.apply_grain(img, 20, "midtone")
    assert np.array_equal(a, b)
    big = np.full((2400, 3600, 3), 128, np.uint8)
    g_big = pipeline.apply_grain(big, 20, "midtone").astype(np.float32)
    # grain amplitude is preserved when the frame is larger than reference
    assert abs(g_big.std() - a.astype(np.float32).std()) < 2.5


def test_mono_grain_has_no_colour():
    img = np.full((100, 100, 3), 128, np.uint8)
    out = pipeline.apply_grain(img, 30, "heavy", mono=True)
    assert np.array_equal(out[..., 0], out[..., 1]) and np.array_equal(out[..., 1], out[..., 2])


def test_spline_lut_identity_and_monotone_s_curve():
    assert np.array_equal(pipeline.compute_spline_lut([(0, 0), (255, 255)]), np.arange(256, dtype=np.uint8))
    lut = pipeline.compute_spline_lut([(0, 0), (64, 48), (192, 208), (255, 255)])
    assert lut[0] == 0 and lut[255] == 255 and lut[64] == 48 and lut[192] == 208


def test_wheel_offsets_are_luminance_neutral():
    for pos in [(1, 0), (0, 1), (-0.5, 0.5)]:
        assert abs(sum(pipeline.wheel_to_offset(pos))) < 1e-6
    # pushing toward the red hue adds red
    b, g, r = pipeline.wheel_to_offset((-1.0, 0.0))
    assert r > 0 and r > g and r > b


def test_geometry_crop_and_resize():
    img = photo(400, 200)
    geo = Geometry(crop_l=25, crop_r=75, crop_t=0, crop_b=100)
    assert pipeline.apply_geometry(img, geo).shape[:2] == (200, 200)
    geo.resize_w, geo.resize_h = 100, 80
    assert pipeline.apply_geometry(img, geo).shape[:2] == (80, 100)
    assert pipeline.apply_geometry(img, geo, output_scale=0.5).shape[:2] == (40, 50)


def test_full_edit_runs():
    img = photo()
    s = EditState(profile="KODAK PORTRA 400 (SOFT)", exposure=110, contrast=120, saturation=90, warmth=10,
                  tint=-5, highlights=80, shadows=120, sharpness=1.0, vignette=-40, cal_red=20,
                  curve=[(0, 10), (128, 140), (255, 245)], wheel_shadows=(0.3, 0.2))
    out = pipeline.develop(img, s)
    assert out.shape == img.shape and out.dtype == np.uint8


def test_scopes_render():
    img = photo()
    assert scopes.histogram(img, 300, 120).shape == (120, 300, 3)
    assert scopes.waveform(img, 300, 120).shape == (120, 300, 3)


def test_io_roundtrip_unicode_path_and_exif_orientation(tmp_path):
    from PIL import Image
    folder = tmp_path / "фото café"
    folder.mkdir()
    src = folder / "sample ü.jpg"
    rgb = np.zeros((40, 80, 3), np.uint8)
    rgb[:, :40] = (255, 0, 0)
    im = Image.fromarray(rgb)
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90 CW on display
    im.save(src, exif=exif.tobytes(), quality=95)

    listed = io.list_images(str(folder))
    assert [i.name for i in listed] == ["sample ü.jpg"]

    bgr, exif_bytes = io.load_image(str(src))
    assert bgr.shape[:2] == (80, 40)  # upright
    thumb, fw, fh = io.load_thumbnail(str(src), 20)
    assert (fw, fh) == (40, 80) and thumb.shape[0] > thumb.shape[1]

    out = folder / "exported ✓.jpg"
    io.save_image(str(out), bgr, exif_bytes)
    with Image.open(out) as check:
        assert check.size == (40, 80)
        assert check.getexif().get(0x0112, 1) == 1
    with pytest.raises(ValueError):
        io.save_image(str(folder / "bad.xyz"), bgr)
