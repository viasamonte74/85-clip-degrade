"""Apply one recipe to one reference: stage 1, stage 2, final encode.

Stage 1 (reference resolution -> intermediate): optical blur, resize 1, sensor noise,
JPEG-style blocks. Stage 2 (intermediate -> exact LR size): mild blur, resize 2, a little
noise. Then libx264/libx265 at a web bitrate with a 2-second GOP. Frames stream one at a
time, so frame count and order are preserved by construction and verified afterwards.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from sn85ds.colour import rgb_to_yuv420, yuv420_to_rgb
from sn85ds.degradation import ops
from sn85ds.degradation.recipe import BlurSpec, EncodeSpec, NoiseSpec, Recipe
from sn85ds.media import BT709_TAGS, RawYuv420Writer, Yuv420Reader, fps_str
from sn85ds.util import cmd_str


def encoder_args(e: EncodeSpec) -> list[str]:
    """ffmpeg output arguments for the final encode (CPU encoders only)."""
    min_keyint = max(1, e.gop_frames // 10)  # x264/x265's own default rule, made explicit
    common = ["-pix_fmt", e.pix_fmt, *BT709_TAGS, "-chroma_sample_location", "left", "-movflags", "+faststart"]
    if e.codec == "h264":
        return ["-c:v", "libx264", "-preset", e.preset, "-profile:v", "high",
                "-b:v", f"{e.bitrate_kbps}k", "-maxrate", f"{e.maxrate_kbps}k", "-bufsize", f"{e.bufsize_kbps}k",
                "-g", str(e.gop_frames), "-keyint_min", str(min_keyint),
                "-sc_threshold", "40" if e.scenecut else "0", "-bf", str(e.bframes),
                "-threads", str(e.threads), *common]
    params = ":".join([
        f"keyint={e.gop_frames}", f"min-keyint={min_keyint}", f"scenecut={40 if e.scenecut else 0}",
        f"bframes={e.bframes}", f"vbv-maxrate={e.maxrate_kbps}", f"vbv-bufsize={e.bufsize_kbps}",
        f"pools={e.threads}", "frame-threads=1", "log-level=error",
    ])
    return ["-c:v", "libx265", "-preset", e.preset, "-b:v", f"{e.bitrate_kbps}k", "-x265-params", params,
            "-tag:v", "hvc1", *common]


def _kernel(b: BlurSpec) -> np.ndarray | None:
    if b.kind == "none":
        return None
    if b.kind in ("isotropic", "anisotropic"):
        return ops.gaussian_kernel(b.sigma_x, b.sigma_y, b.theta_rad)
    return ops.line_kernel(b.length_px, b.theta_rad, soften=b.sigma_x)


def _noise(n: NoiseSpec) -> ops.SensorNoise | None:
    if not n.enabled or n.level <= 0:
        return None
    return ops.SensorNoise(level=n.level, shot_fraction=n.shot_fraction, spatial_sigma=n.spatial_sigma,
                           chroma=n.chroma, temporal_rho=n.temporal_rho, seed=n.seed)


def _save_png(path: Path, rgb: np.ndarray) -> None:
    u8 = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), cv2.cvtColor(u8, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 3])


class Degrader:
    """Stateful per-clip degradation (the noise fields carry temporal correlation)."""

    def __init__(self, recipe: Recipe):
        self.r = recipe
        self.k1 = _kernel(recipe.blur1)
        self.k2 = _kernel(recipe.blur2)
        self.n1 = _noise(recipe.noise1)
        self.n2 = _noise(recipe.noise2)

    def stage1(self, rgb: np.ndarray) -> np.ndarray:
        x = rgb
        if self.k1 is not None:
            x = ops.apply_kernel(x, self.k1)
        iw, ih = self.r.intermediate_size
        x = ops.resize(x, iw, ih, self.r.resize1)
        if self.n1 is not None:
            x = self.n1(x)
        if self.r.jpeg.enabled:
            x = ops.jpeg_roundtrip(x, self.r.jpeg.quality)
        return np.clip(x, 0.0, 1.0)

    def stage2(self, x: np.ndarray) -> np.ndarray:
        if self.k2 is not None:
            x = ops.apply_kernel(x, self.k2)
        lw, lh = self.r.lr_size
        x = ops.resize(x, lw, lh, self.r.resize2)
        if self.n2 is not None:
            x = self.n2(x)
        return np.clip(x, 0.0, 1.0)


def degrade_many(reference: str | Path, jobs: list[tuple[Recipe, str | Path]], *,
                 capture_frames: tuple[int, ...] = (), capture_dirs: list[str | Path | None] | None = None,
                 max_frames: int | None = None) -> list[dict]:
    """Make several variants of one reference in a single decode pass.

    The reference is decoded and converted to R'G'B' once; each recipe has its own
    stateful :class:`Degrader` and encoder process. Returns one result dict per job."""
    t0 = time.time()
    reader = Yuv420Reader(reference)
    for recipe, _ in jobs:
        if (reader.w, reader.h) != tuple(recipe.reference_size):
            raise ValueError(f"reference is {reader.w}x{reader.h}, recipe expects {recipe.reference_size}")
    cap = set(capture_frames)
    cdirs = [Path(c) if c else None for c in (capture_dirs or [None] * len(jobs))]
    for c in cdirs:
        if c and cap:
            c.mkdir(parents=True, exist_ok=True)
    outs, tmps, degs, writers = [], [], [], []
    try:
        for recipe, out_path in jobs:
            out = Path(out_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.stem + ".partial.mp4")
            lw, lh = recipe.lr_size
            outs.append(out)
            tmps.append(tmp)
            degs.append(Degrader(recipe))
            writers.append(RawYuv420Writer(tmp, lw, lh, recipe.fps, encoder_args(recipe.encode), container="mp4"))
        n = 0
        for y, u, v in reader:
            if max_frames is not None and n >= max_frames:
                break
            rgb = yuv420_to_rgb(y, u, v)
            for deg, wr, cdir in zip(degs, writers, cdirs):
                s1 = deg.stage1(rgb)
                s2 = deg.stage2(s1)
                wr.write(*rgb_to_yuv420(s2))
                if n in cap and cdir is not None:
                    _save_png(cdir / f"f{n:05d}_0_reference.png", rgb)
                    _save_png(cdir / f"f{n:05d}_1_stage1.png", s1)
                    _save_png(cdir / f"f{n:05d}_2_stage2.png", s2)
            n += 1
        for wr in writers:
            wr.close()
    except BaseException:
        for wr in writers:
            try:
                wr.__exit__(RuntimeError, None, None)
            except Exception:
                pass
        for t in tmps:
            t.unlink(missing_ok=True)
        raise
    results = []
    for (recipe, _), out, tmp, wr in zip(jobs, outs, tmps, writers):
        tmp.replace(out)
        results.append({
            "frames_written": wr.frames,
            "pre_encode_planes_sha256": wr.hash.hexdigest(),
            "encode_command": cmd_str(wr.cmd).replace(str(tmp), str(out)),
            "seconds_total_pass": round(time.time() - t0, 2),
            "variants_in_pass": len(jobs),
            "lr_fps": fps_str(recipe.fps),
        })
    return results


def degrade(reference: str | Path, recipe: Recipe, out_path: str | Path, *,
            capture_frames: tuple[int, ...] = (), capture_dir: str | Path | None = None) -> dict:
    """Write the encoded LR input for one ``recipe`` (see :func:`degrade_many`)."""
    return degrade_many(reference, [(recipe, out_path)], capture_frames=capture_frames,
                        capture_dirs=[capture_dir])[0]
