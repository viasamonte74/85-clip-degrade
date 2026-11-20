"""End-to-end checks on small synthetic media: reference preparation, degradation, determinism,
validation helpers and group-aware splitting."""

from __future__ import annotations

import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from sn85ds.acquisition.references import aspect_crop, build_filter, write_reference
from sn85ds.degradation.pipeline import degrade_many
from sn85ds.degradation.recipe import load_config, sample_recipe
from sn85ds.media import RawYuv420Writer, Yuv420Reader, decoded_checksum, ffv1_args, keyframe_indices, probe
from sn85ds.util import sha256_file
from sn85ds.validation.checks import dhash_frames, hamming, pairing_consistency

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def _synthetic_reference(path: Path, w: int = 384, h: int = 216, frames: int = 30, fps: str = "30") -> Path:
    rng = np.random.default_rng(0)
    base = rng.integers(16, 236, (h * 2, w * 2), dtype=np.uint8)
    with RawYuv420Writer(path, w, h, fps, ffv1_args(), threads_nice=False) as wr:
        for k in range(frames):
            y = np.ascontiguousarray(base[k:k + h, k:k + w])  # moving texture
            u = np.full((h // 2, w // 2), 110 + k % 20, np.uint8)
            v = np.full((h // 2, w // 2), 140, np.uint8)
            wr.write(y, u, v)
    return path


def test_aspect_crop_policy():
    assert aspect_crop(4096, 2160, "landscape") == (3840, 2160, 128, 0)
    cw, ch, x, y = aspect_crop(4000, 2250, "portrait")
    assert ch == 2250 and cw % 2 == 0 and abs(cw / ch - 9 / 16) < 0.002
    assert aspect_crop(1920, 1080, "landscape") == (1920, 1080, 0, 0)
    with pytest.raises(ValueError):
        build_filter(2048, 858, "landscape", None)  # would need upscaling
    vf, info = build_filter(4096, 1744, "landscape", None)
    assert "scale=1920:1080" in vf and info["aspect_error"] < 0.005


def test_write_reference_from_rgb_master(tmp_path):
    src = tmp_path / "m_%03d.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=2560x1440:rate=24", "-frames:v", "12", str(src)], check=True)
    out = tmp_path / "ref.mkv"
    info = write_reference(input_args=["-framerate", "24", "-start_number", "1", "-i", str(src)], rgb_master=True,
                           src_w=2560, src_h=1440, fps="24", frames=12, orientation="landscape", out_path=out)
    p = probe(out)
    assert (p.width, p.height, p.frames, p.codec, p.pix_fmt) == (1920, 1080, 12, "ffv1", "yuv420p")
    assert p.color_space == "bt709" and p.color_range == "tv" and Fraction(p.fps) == 24
    assert decoded_checksum(out) == (info["planes_sha256"], 12)


def test_degradation_end_to_end_and_bit_exact_reproducibility(tmp_path):
    ref = _synthetic_reference(tmp_path / "ref.mkv")
    cfg, digest = load_config()
    recipes = [sample_recipe(reference_size=(384, 216), fps="30", factor=f, seed=s, mean_luma=0.5, config=cfg, config_digest=digest)
               for f, s in ((2, 1), (4, 2))]
    # force both encoders to be exercised
    recipes[0] = recipes[0].model_copy(update={"encode": recipes[0].encode.model_copy(update={"codec": "h264", "encoder": "libx264"})})
    recipes[1] = recipes[1].model_copy(update={"encode": recipes[1].encode.model_copy(update={"codec": "hevc", "encoder": "libx265"})})
    outs1 = [tmp_path / "a_x2.mp4", tmp_path / "a_x4.mp4"]
    outs2 = [tmp_path / "b_x2.mp4", tmp_path / "b_x4.mp4"]
    r1 = degrade_many(ref, list(zip(recipes, outs1)))
    r2 = degrade_many(ref, list(zip(recipes, outs2)))
    for rec, o1, o2, a, b in zip(recipes, outs1, outs2, r1, r2):
        p = probe(o1)
        assert (p.width, p.height) == (384 // rec.upscale_factor, 216 // rec.upscale_factor)
        assert p.frames == 30 and Fraction(p.fps) == 30 and p.pix_fmt == "yuv420p"
        assert p.codec == rec.encode.codec
        assert p.color_space == "bt709" and p.color_range == "tv" and p.color_primaries == "bt709" and p.color_transfer == "bt709"
        assert keyframe_indices(o1)[0] == 0
        assert a["pre_encode_planes_sha256"] == b["pre_encode_planes_sha256"]
        assert sha256_file(o1) == sha256_file(o2), f"{rec.encode.codec} output is not bit-exact across runs"


def test_pairing_consistency_detects_no_shift(tmp_path):
    ref = _synthetic_reference(tmp_path / "ref.mkv", frames=24)
    cfg, digest = load_config()
    r = sample_recipe(reference_size=(384, 216), fps="30", factor=2, seed=5, mean_luma=0.5, config=cfg, config_digest=digest,
                      difficulty="mild")
    out = tmp_path / "x2.mp4"
    degrade_many(ref, [(r, out)])
    pc = pairing_consistency(out, ref, samples=4)
    assert all(o == 0 for o in pc["temporal_offsets"]) and pc["max_spatial_shift_px"] < 0.5 and pc["min_correlation"] > 0.8


def test_dhash_near_duplicates(tmp_path):
    a = _synthetic_reference(tmp_path / "a.mkv", frames=10)
    ha = dhash_frames(a, n=4)
    assert min(hamming(x, y) for x in ha for y in ha) == 0
    assert hamming(0b1011, 0b0010) == 2


def test_group_aware_split_keeps_groups_together():
    from assign_splits import assign
    refs = []
    for g in range(30):
        for k in range(1 + g % 3):
            refs.append({"source_id": f"s{g}_{k}", "group_id": f"g{g}", "category": "3d_rendered" if g % 2 else "screen"})
    a1 = assign(refs, {})
    a2 = assign(refs, {})
    assert a1 == a2  # deterministic
    for g in {r["group_id"] for r in refs}:
        assert a1[g] in ("train", "validation", "test")
    counts = {s: sum(1 for r in refs if a1[r["group_id"]] == s) for s in ("train", "validation", "test")}
    assert counts["train"] > counts["validation"] > 0 and counts["test"] > 0
    assert abs(counts["train"] / len(refs) - 0.8) < 0.12
    # existing assignments never move
    prev = {"g0": "test"}
    assert assign(refs, prev)["g0"] == "test"
