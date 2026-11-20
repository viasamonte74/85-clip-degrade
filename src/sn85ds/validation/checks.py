"""Dataset validation checks (licences, references, variants, pairing consistency, leakage)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from sn85ds.degradation.ops import resize
from sn85ds.media import Yuv420Reader, decoded_checksum, probe
from sn85ds.util import sha256_file

cv2.setNumThreads(1)

LICENCE_ALLOW = {"CC0-1.0", "PD", "CC-BY-2.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0",
                 "CC-BY-SA-2.0", "CC-BY-SA-2.5", "CC-BY-SA-3.0", "CC-BY-SA-4.0"}
FPS_ALLOW = {Fraction(24), Fraction(25), Fraction(30), Fraction(30000, 1001), Fraction(50), Fraction(60), Fraction(60000, 1001),
             Fraction(24000, 1001)}
REF_SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920)}


class Report:
    def __init__(self, item: str, kind: str):
        self.item, self.kind = item, kind
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: dict = {}

    def check(self, ok: bool, msg: str, *, warn: bool = False) -> None:
        if not ok:
            (self.warnings if warn else self.errors).append(msg)

    @property
    def status(self) -> str:
        return "fail" if self.errors else ("warn" if self.warnings else "pass")

    def as_dict(self) -> dict:
        return {"item": self.item, "kind": self.kind, "status": self.status, "errors": self.errors,
                "warnings": self.warnings, **({"info": self.info} if self.info else {})}


def check_source(src: dict) -> Report:
    r = Report(src["source_id"], "source")
    r.check(src.get("licence") in LICENCE_ALLOW, f"licence {src.get('licence')} not on the allow-list")
    r.check(bool(src.get("commercial_ml_training")), "commercial ML training not verified")
    r.check(bool(src.get("licence_evidence")), "no licence evidence recorded")
    r.check(not src.get("contradiction_note"), "licence contradiction on other mirrors: confirm before redistribution", warn=True)
    r.check(not src.get("privacy_flag"), "identifiable people: personality/privacy review before redistribution", warn=True)
    r.check(src.get("licence") != "CC-BY-SA-4.0", "share-alike: derived clips must stay CC BY-SA 4.0 if distributed", warn=True)
    return r


def check_reference(ref: dict, root: Path, *, deep: bool = True) -> Report:
    r = Report(ref["source_id"], "reference")
    p = root / ref["reference_path"]
    r.check(p.exists(), "reference file missing")
    if not p.exists():
        return r
    r.check(sha256_file(p) == ref["reference_sha256"], "reference file sha256 changed")
    info = probe(p)
    r.check((info.width, info.height) == REF_SIZES[ref["orientation"]], f"size {info.width}x{info.height} wrong for {ref['orientation']}")
    r.check(info.codec == "ffv1" and info.pix_fmt == "yuv420p", f"codec/pix_fmt {info.codec}/{info.pix_fmt}")
    r.check(info.color_space == "bt709" and info.color_range == "tv", f"colour tags {info.color_space}/{info.color_range}")
    fr = Fraction(ref["fps"])  # exact rational rate (metadata); Matroska stores 1 ms timestamps only
    r.check(fr in FPS_ALLOW, f"frame rate {ref['fps']} not in the allowed set")
    r.check(abs(float(Fraction(info.fps)) / float(fr) - 1.0) < 1e-4,
            f"container frame rate {info.fps} disagrees with the exact rate {ref['fps']}")
    r.check(info.frames == ref["frames"], f"frame count {info.frames} != metadata {ref['frames']}")
    dur = Fraction(info.frames) / fr
    r.check(dur <= 10, f"duration {float(dur):.2f}s > 10 s")
    r.check(dur >= 2, f"duration {float(dur):.2f}s < 2 s", warn=True)
    r.check(ref.get("black_frames", 0) == 0, f"{ref.get('black_frames')} black frames")
    frozen = ref.get("frozen_frame_pairs", 0)
    r.check(frozen <= max(2, info.frames // 20), f"{frozen} frozen frame pairs", warn=ref["category"] == "screen")
    r.check(not ref.get("cuts_detected"), f"hard cuts inside the clip at {ref.get('cuts_detected')}", warn=True)
    r.check(ref["transform"]["aspect_error"] < 0.005, f"aspect error {ref['transform']['aspect_error']}")
    if deep:
        digest, n = decoded_checksum(p)
        r.check(digest == ref["planes_sha256"] and n == ref["frames"], "decoded planes checksum mismatch")
    r.info = {"fps": info.fps, "frames": info.frames, "duration_s": round(float(dur), 3)}
    return r


def _area_luma(y: np.ndarray, w: int, h: int) -> np.ndarray:
    return resize(y.astype(np.float32)[..., None], w, h, "area")[..., 0]


def pairing_consistency(lr_path: Path, ref_path: Path, *, samples: int = 8) -> dict:
    """Temporal offset, spatial shift and similarity between the LR input and its reference."""
    li = probe(lr_path)
    n = li.frames
    pick = set(np.unique(np.linspace(3, max(3, n - 4), samples, dtype=int)).tolist())
    need = set()
    for k in pick:
        need.update(range(k - 2, k + 3))
    lr_f, ref_f = {}, {}
    for k, (y, _, _) in enumerate(Yuv420Reader(lr_path, allow_convert=True)):
        if k in pick:
            lr_f[k] = y.astype(np.float32)
    for k, (y, _, _) in enumerate(Yuv420Reader(ref_path)):
        if k in need:
            ref_f[k] = _area_luma(y, li.width, li.height)
    offsets, shifts, psnrs, corrs, ambiguous = [], [], [], [], 0
    total = {d: 0.0 for d in range(-2, 3)}
    for k in sorted(pick):
        if k not in lr_f:
            continue
        errs = {d: float(((lr_f[k] - ref_f[k + d]) ** 2).mean()) for d in range(-2, 3) if (k + d) in ref_f}
        for d, e in errs.items():
            total[d] += e
        motion = min(float(((ref_f[k] - ref_f[k + d]) ** 2).mean()) for d in (-1, 1) if (k + d) in ref_f)
        best = min(errs, key=errs.get)
        if motion < 0.25 * errs.get(0, 0.0):
            # the reference barely changes between neighbouring frames compared with the
            # degradation error: the offset is not identifiable from this sample
            ambiguous += 1
            offsets.append(0)
        else:
            # a real one-frame offset raises the error by roughly the inter-frame difference
            # ('motion'); offset 0 is consistent if its excess error is well below that
            excess = errs.get(0, 1e9) - errs[best]
            offsets.append(0 if excess <= max(0.25 * motion, 0.01 * errs[best]) + 1e-6 else best)
        mse = errs.get(0, 1e9)
        psnrs.append(10 * np.log10(255.0**2 / max(mse, 1e-6)))
        # alignment and scene identity on low frequencies (heavy blur/noise on fine text must not
        # read as 'another scene'); flat frames (fades, empty screens) carry no alignment signal
        a = cv2.GaussianBlur(lr_f[k], (0, 0), 2.0)
        b = cv2.GaussianBlur(ref_f[k], (0, 0), 2.0)
        if b.std() < 3.0:
            continue
        (dx, dy), response = cv2.phaseCorrelate(b.astype(np.float64), a.astype(np.float64))
        if response >= 0.2:  # below this the correlation peak is not meaningful (dark / low texture)
            shifts.append(float(np.hypot(dx, dy)))
        corrs.append(float(np.corrcoef(a.ravel(), b.ravel())[0, 1]))
    global_offset = min(total, key=total.get) if any(total.values()) else 0
    if total.get(0, 0) <= total[global_offset] * 1.005:
        global_offset = 0
    return {"temporal_offsets": offsets, "ambiguous_samples": ambiguous, "global_offset": global_offset,
            "max_spatial_shift_px": round(max(shifts), 3) if shifts else 0.0, "flat_samples_skipped": len(offsets) - len(shifts),
            "min_psnr_db": round(float(min(psnrs)), 2), "median_psnr_db": round(float(np.median(psnrs)), 2),
            "min_correlation": round(float(min(corrs)), 4) if corrs else 1.0}


def check_variant(v: dict, ref: dict, root: Path, *, deep: bool = True) -> Report:
    r = Report(v["input_id"], "variant")
    p = root / v["output_path"]
    r.check(p.exists(), "output missing")
    if not p.exists():
        return r
    r.check(sha256_file(p) == v["output_sha256"], "output sha256 changed")
    r.check(v["split"] == ref["split"], f"variant split {v['split']} != reference split {ref['split']}")
    r.check(v["reference_sha256"] == ref["reference_sha256"], "variant points at a different reference version")
    info = probe(p)
    f = v["upscale_factor"]
    want = (ref["width"] // f, ref["height"] // f)
    r.check((info.width, info.height) == want, f"LR size {info.width}x{info.height} != {want}")
    r.check(info.codec in ("h264", "hevc"), f"codec {info.codec}")
    r.check(info.pix_fmt == "yuv420p", f"pix_fmt {info.pix_fmt}")
    r.check(info.frames == ref["frames"], f"frames {info.frames} != reference {ref['frames']}")
    r.check(Fraction(info.fps) == Fraction(ref["fps"]), f"fps {info.fps} != reference {ref['fps']}")
    r.check(info.color_space == "bt709" and info.color_range == "tv" and info.color_primaries == "bt709" and info.color_transfer == "bt709",
            f"colour tags {info.color_space}/{info.color_range}/{info.color_primaries}/{info.color_transfer}")
    keys = v["probe"]["keyframes"]
    gaps = np.diff(keys) if len(keys) > 1 else np.array([info.frames])
    r.check(keys[:1] == [0], "first frame is not a key frame")
    r.check(int(gaps.max()) <= v["gop_frames"] or len(keys) == 1 and info.frames <= v["gop_frames"],
            f"GOP gap {int(gaps.max())} > {v['gop_frames']}")
    st = v["stats"]
    r.check(st["luma_psnr_vs_area_down"] < 50.0, "degradation not visible (PSNR vs area-downscaled reference >= 50 dB)")
    r.check(st["luma_psnr_vs_area_down"] >= 20.0, f"implausibly strong degradation (PSNR {st['luma_psnr_vs_area_down']} dB)",
            warn=ref["category"] == "screen")
    r.check(st["effective_blur_sigma_lr_px"] <= 1.8, f"effective blur {st['effective_blur_sigma_lr_px']} LR px is implausibly strong", warn=True)
    if deep:
        pc = pairing_consistency(p, root / ref["split_path"])
        r.info["pairing"] = pc
        r.check(all(o == 0 for o in pc["temporal_offsets"]) and pc["global_offset"] == 0,
                f"temporal offset/order mismatch {pc['temporal_offsets']} (global {pc['global_offset']})")
        r.check(pc["max_spatial_shift_px"] < 0.5, f"spatial shift {pc['max_spatial_shift_px']} px")
        r.check(pc["min_correlation"] > 0.8, f"low correlation with the reference ({pc['min_correlation']}): different scene?")
    return r


def dhash_frames(path: Path, n: int = 8) -> list[int]:
    """64-bit difference hashes of n evenly spaced frames (for near-duplicate detection)."""
    info = probe(path)
    pick = set(np.unique(np.linspace(0, info.frames - 1, n, dtype=int)).tolist())
    out = []
    for k, (y, _, _) in enumerate(Yuv420Reader(path)):
        if k in pick:
            small = cv2.resize(y, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
            if small.std() < 2.0:  # near-flat frame: its hash is noise, not content
                continue
            bits = (small[:, 1:] > small[:, :-1]).ravel()
            out.append(int("".join("1" if b else "0" for b in bits), 2))
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
