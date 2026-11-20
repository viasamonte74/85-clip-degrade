"""Core numeric checks of the degradation operators, colour maths and recipe sampling."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sn85ds.colour import rgb_to_yuv420, yuv420_to_rgb
from sn85ds.degradation import ops
from sn85ds.degradation.recipe import load_config, lr_size_for, sample_recipe


def _rand_rgb(h=64, w=96, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.random((h // 8, w // 8, 3)).astype(np.float32)
    import cv2
    return np.clip(cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC), 0, 1)


def test_colour_roundtrip_small_error():
    rgb = _rand_rgb()
    y, u, v = rgb_to_yuv420(rgb)
    back = yuv420_to_rgb(y, u, v)
    y2, u2, v2 = rgb_to_yuv420(back)
    # luma survives a 4:2:0 round trip almost exactly; chroma is low-passed a little at
    # sharp chroma edges (linear up + [1,2,1] down is not an exact inverse), which is
    # irrelevant once the frame is downscaled by 2-4x
    # (analytically: one up/down round trip applies [1, 6, 1] / 8 to chroma in each axis)
    assert np.abs(y2.astype(int) - y.astype(int)).max() <= 2
    import scipy.ndimage as ndi
    k = np.array([1.0, 6.0, 1.0]) / 8.0
    for c, c2 in ((u, u2), (v, v2)):
        expect = ndi.convolve1d(ndi.convolve1d(c.astype(np.float64), k, axis=0, mode="nearest"), k, axis=1, mode="nearest")
        assert np.abs(expect - c2.astype(np.float64))[1:-1, 1:-1].max() <= 1.5
    assert np.abs(back - rgb).mean() < 0.02


def test_fast_colour_paths_match_reference():
    from sn85ds.colour import rgb_to_yuv420_reference, yuv420_to_rgb_reference
    rgb = _rand_rgb(72, 128, seed=3)
    y, u, v = rgb_to_yuv420_reference(rgb)
    yf, uf, vf = rgb_to_yuv420(rgb)
    for a, b in ((y, yf), (u, uf), (v, vf)):
        assert np.abs(a.astype(int) - b.astype(int)).max() <= 1  # float rounding at .5 only
    assert np.abs(yuv420_to_rgb_reference(y, u, v) - yuv420_to_rgb(y, u, v)).max() < 1e-4


def test_colour_known_values():
    grey = np.full((4, 4, 3), 0.5, np.float32)
    y, u, v = rgb_to_yuv420(grey)
    assert int(y[0, 0]) == round(16 + 219 * 0.5) and int(u[0, 0]) == 128 and int(v[0, 0]) == 128
    red = np.zeros((4, 4, 3), np.float32); red[..., 0] = 1.0
    y, u, v = rgb_to_yuv420(red)
    assert int(y[0, 0]) == round(16 + 219 * 0.2126)
    assert int(v[0, 0]) == 240  # Cr of pure red is the top of the range


@pytest.mark.parametrize("kind", list(ops.FILTERS))
def test_resize_preserves_constant_and_mean(kind):
    img = np.full((108, 192, 3), 0.37, np.float32)
    out = ops.resize(img, 48, 27, kind)
    assert out.shape == (27, 48, 3)
    assert np.allclose(out, 0.37, atol=1e-5)
    ramp = _rand_rgb(108, 192)
    out = ops.resize(ramp, 64, 36, kind)
    assert abs(float(out.mean()) - float(ramp.mean())) < 0.01


def test_area_resize_is_exact_block_mean():
    img = np.arange(16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3)
    out = ops.resize(img, 4, 4, "area")
    ref = img.reshape(4, 4, 4, 4, 3).mean(axis=(1, 3))
    assert np.allclose(out, ref, atol=1e-3)


def test_gaussian_kernels_normalised():
    for k in (ops.gaussian_kernel(1.0), ops.gaussian_kernel(1.5, 0.5, 0.7), ops.line_kernel(4.0, 0.3)):
        assert abs(float(k.sum()) - 1.0) < 1e-5


def test_noise_level_matches_spec_on_mid_grey():
    grey = np.full((256, 256, 3), 0.5, np.float32)
    for level in (1.0, 3.0):
        n = ops.SensorNoise(level=level, shot_fraction=0.5, spatial_sigma=0.0, chroma=1.0, temporal_rho=0.0, seed=1)
        out = n(grey)
        measured = float((out - 0.5).std() * 255.0)
        assert abs(measured - level) / level < 0.08, measured


def test_noise_stronger_in_darks_and_deterministic():
    dark = np.full((128, 128, 3), 0.1, np.float32)
    bright = np.full((128, 128, 3), 0.8, np.float32)
    a = ops.SensorNoise(level=2.0, shot_fraction=0.6, spatial_sigma=0.5, chroma=0.5, temporal_rho=0.3, seed=7)
    b = ops.SensorNoise(level=2.0, shot_fraction=0.6, spatial_sigma=0.5, chroma=0.5, temporal_rho=0.3, seed=7)
    assert np.array_equal(a(dark), b(dark))
    c = ops.SensorNoise(level=2.0, shot_fraction=0.6, spatial_sigma=0.0, chroma=0.5, temporal_rho=0.0, seed=3)
    assert (c(dark) - 0.1).std() > (c(bright) - 0.8).std()


def test_temporal_correlation():
    grey = np.full((128, 128, 3), 0.5, np.float32)
    n = ops.SensorNoise(level=3.0, shot_fraction=0.0, spatial_sigma=0.0, chroma=1.0, temporal_rho=0.6, seed=2)
    f1 = n(grey) - 0.5
    f2 = n(grey) - 0.5
    corr = float(np.corrcoef(f1.ravel(), f2.ravel())[0, 1])
    assert 0.5 < corr < 0.7


def test_recipe_deterministic_and_within_published_bounds():
    cfg, digest = load_config()
    for factor in (2, 4):
        for seed in range(40):
            r1 = sample_recipe(reference_size=(1920, 1080), fps="30", factor=factor, seed=seed, mean_luma=0.5,
                               config=cfg, config_digest=digest)
            r2 = sample_recipe(reference_size=(1920, 1080), fps="30", factor=factor, seed=seed, mean_luma=0.5,
                               config=cfg, config_digest=digest)
            assert r1 == r2
            lw, lh = lr_size_for(1920, 1080, factor)
            assert r1.lr_size == (lw, lh)
            iw, ih = r1.intermediate_size
            assert lw <= iw <= math.ceil(lw * 1.7) + 2 and iw % 2 == 0 and ih % 2 == 0
            assert abs(iw / ih - lw / lh) < 0.02
            lo, hi = cfg["encode"]["bitrate_kbps"][factor]
            lo = lo * (cfg["encode"]["hevc_low_extension"] if r1.encode.codec == "hevc" else 1)
            assert lo - 1 <= r1.encode.bitrate_kbps <= hi + 1
            assert r1.encode.gop_frames == 60


def test_portrait_and_high_fps():
    cfg, digest = load_config()
    r = sample_recipe(reference_size=(1080, 1920), fps="60000/1001", factor=4, seed=5, mean_luma=0.1,
                      config=cfg, config_digest=digest)
    assert r.orientation == "portrait" and r.lr_size == (270, 480)
    assert r.encode.gop_frames == 120
    assert r.noise1.enabled  # dark clip floor 0.8 -> seed 5 enables it; noise boost recorded
    assert any("dark clip" in n for n in r.notes)
