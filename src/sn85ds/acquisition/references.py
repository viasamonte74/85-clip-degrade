"""Normalise a downloaded / rendered master into an immutable 1080p FFV1 reference.

Steps (each recorded): optional source crop (e.g. the left eye of a stereo frame) -> centre
crop to the target aspect (16:9 landscape or 9:16 portrait; never smaller than the target,
so nothing is upscaled) -> one high-quality downscale (swscale 'spline', accurate rounding)
-> 8-bit 4:2:0 BT.709 limited range -> FFV1 v3 in Matroska.

Colour: YUV masters (BT.709 10-bit J2K / y4m) stay in Y'CbCr: crop, scale and bit-depth
reduction only, no matrix conversion. RGB masters (renders / PNG / TIFF, sRGB-encoded) are
taken as BT.709 R'G'B' (no transfer conversion, the usual convention for CG output) and
converted with the project's explicit BT.709 matrix (sn85ds.colour).
Converting a lossy master to FFV1 does not recover detail; it only freezes it losslessly.
"""

from __future__ import annotations

import hashlib
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

from sn85ds.colour import rgb_to_yuv420
from sn85ds.media import RawYuv420Writer, ffv1_args, fps_str
from sn85ds.util import FFMPEG, cmd_str, even, nice_prefix

SCALE_FLAGS = "spline+accurate_rnd+full_chroma_int+full_chroma_inp"


def target_size(orientation: str) -> tuple[int, int]:
    return (1920, 1080) if orientation == "landscape" else (1080, 1920)


def aspect_crop(w: int, h: int, orientation: str) -> tuple[int, int, int, int]:
    """Largest centred crop of w x h with the target aspect; returns (cw, ch, x, y)."""
    tw, th = target_size(orientation)
    if w * th > h * tw:  # too wide
        ch = h - (h % 2)
        cw = even(h * tw / th)
    else:
        cw = w - (w % 2)
        ch = even(w * th / tw)
    cw, ch = min(cw, w - w % 2), min(ch, h - h % 2)
    x = ((w - cw) // 2) & ~1
    y = ((h - ch) // 2) & ~1
    return cw, ch, x, y


def build_filter(src_w: int, src_h: int, orientation: str, source_crop: list[int] | None) -> tuple[str, dict]:
    steps = []
    vf = []
    w, h = src_w, src_h
    if source_crop:
        cw, ch, cx, cy = source_crop
        vf.append(f"crop={cw}:{ch}:{cx}:{cy}")
        steps.append({"op": "source_crop", "w": cw, "h": ch, "x": cx, "y": cy})
        w, h = cw, ch
    cw, ch, x, y = aspect_crop(w, h, orientation)
    tw, th = target_size(orientation)
    if cw < tw or ch < th:
        raise ValueError(f"master {w}x{h} too small for a {tw}x{th} reference without upscaling (crop {cw}x{ch})")
    if (cw, ch) != (w, h):
        vf.append(f"crop={cw}:{ch}:{x}:{y}")
        steps.append({"op": "aspect_crop", "w": cw, "h": ch, "x": x, "y": y})
    if (cw, ch) != (tw, th):
        vf.append(f"scale={tw}:{th}:flags={SCALE_FLAGS}")
        steps.append({"op": "downscale", "from": [cw, ch], "to": [tw, th], "filter": "swscale spline (accurate_rnd, full_chroma_int)",
                      "factor": round(cw / tw, 4)})
    aspect_err = abs((cw / ch) - (tw / th)) / (tw / th)
    return ",".join(vf), {"steps": steps, "aspect_error": round(aspect_err, 6)}


def write_reference(*, input_args: list[str], rgb_master: bool, src_w: int, src_h: int, fps: str, frames: int,
                    orientation: str, out_path: Path, source_crop: list[int] | None = None,
                    frame_offset: int = 0, yuv_fix: dict | None = None) -> dict:
    """Decode the master through ffmpeg (crop/scale only) and write the FFV1 reference with
    explicit colour handling. ``frame_offset`` skips leading frames (shot trimming)."""
    vf, info = build_filter(src_w, src_h, orientation, source_crop)
    tw, th = target_size(orientation)
    if yuv_fix and (yuv_fix["in_range"] != "tv" or yuv_fix["in_matrix"] != "bt709"):
        # documented colour normalisation of uploaded Y'CbCr (Commons): full -> limited range and/or
        # BT.601 -> BT.709 matrix, done by swscale in the same pass as the downscale
        conv = f"scale=in_range={yuv_fix['in_range']}:out_range=tv:in_color_matrix={yuv_fix['in_matrix']}:out_color_matrix=bt709"
        vf = f"{vf},{conv}" if vf else conv
        info["steps"].append({"op": "colour_normalise", "from": [yuv_fix["in_range"], yuv_fix["in_matrix"]], "to": ["tv", "bt709"]})
    if yuv_fix and yuv_fix.get("assumed"):
        info["assumed_untagged"] = {k: ("tv" if k == "range" else "bt709") for k in yuv_fix["assumed"]}
    sel = f"select=gte(n\\,{frame_offset})," if frame_offset else ""
    pix = "rgb48le" if rgb_master else "yuv420p"
    cmd = [*nice_prefix(), FFMPEG, "-v", "error", "-nostdin", *input_args,
           "-vf", f"{sel}{vf + ',' if vf else ''}format={pix}", "-fps_mode", "passthrough", "-frames:v", str(frames),
           "-f", "rawvideo", "-pix_fmt", pix, "-"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".partial.mkv")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    fbytes = tw * th * 6 if rgb_master else tw * th * 3 // 2
    luma_means, diffs = [], []
    prev = None
    writer = RawYuv420Writer(tmp, tw, th, fps, ffv1_args())
    with writer:
        while True:
            buf = proc.stdout.read(fbytes)
            if not buf:
                break
            if len(buf) != fbytes:
                raise IOError(f"truncated frame from ffmpeg ({len(buf)} bytes)")
            if rgb_master:
                rgb = np.frombuffer(buf, dtype="<u2").reshape(th, tw, 3).astype(np.float32) / 65535.0
                y, u, v = rgb_to_yuv420(rgb)
            else:
                a = np.frombuffer(buf, np.uint8)
                y = a[: tw * th].reshape(th, tw)
                u = a[tw * th: tw * th * 5 // 4].reshape(th // 2, tw // 2)
                v = a[tw * th * 5 // 4:].reshape(th // 2, tw // 2)
            writer.write(y, u, v)
            small = y[::8, ::8].astype(np.float32)
            luma_means.append(float(((small - 16.0) / 219.0).clip(0, 1).mean()))
            if prev is not None:
                diffs.append(float(np.abs(small - prev).mean()))
            prev = small
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    rc = proc.wait()
    if rc != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg master decode failed ({rc}): {err[-1500:]}")
    if writer.frames != frames:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"wrote {writer.frames} frames, expected {frames}")
    tmp.replace(out_path)
    lm = np.array(luma_means)
    d = np.array(diffs) if diffs else np.zeros(1)
    return {
        "frames": writer.frames, "width": tw, "height": th, "fps": fps_str(fps),
        "duration_s": round(float(Fraction(writer.frames) / Fraction(fps)), 4),
        "planes_sha256": writer.hash.hexdigest(), "mean_luma": round(float(lm.mean()), 4),
        "black_frames": int((lm < 0.02).sum()), "frozen_frame_pairs": int((d < 0.05).sum()),
        "decode_command": cmd_str(cmd), "transform": info, "colour_path": "rgb->bt709 (sn85ds.colour)" if rgb_master else "yuv kept (crop/scale/bit depth only)",
        "encode_command": cmd_str(writer.cmd).replace(str(tmp), str(out_path)),
    }
