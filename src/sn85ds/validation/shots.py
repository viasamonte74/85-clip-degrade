"""Hard-cut detection on small luma thumbnails (used for shot picking and as a QC check).

A cut is a frame whose thumbnail difference to the previous frame is both large in
absolute terms and a strong outlier against the local median (so fast motion that is
uniformly large does not register as a cut). Fades and dissolves are not detected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from sn85ds.util import FFMPEG, nice_prefix

TW, TH = 96, 54


def thumbnails(path: str | Path, *, extra_input_args: list[str] | None = None, max_frames: int | None = None) -> np.ndarray:
    """(N, TH, TW) uint8 luma thumbnails of every frame (area downscale by ffmpeg)."""
    cmd = [*nice_prefix(), FFMPEG, "-v", "error", "-nostdin", *(extra_input_args or []), "-i", str(path),
           "-map", "0:v:0", "-fps_mode", "passthrough", *(["-frames:v", str(max_frames)] if max_frames else []),
           "-vf", f"scale={TW}:{TH}:flags=area,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, TH, TW)


def frame_diffs(th: np.ndarray) -> np.ndarray:
    if len(th) < 2:
        return np.zeros(0)
    a = th.astype(np.float32)
    return np.abs(a[1:] - a[:-1]).mean(axis=(1, 2))


def detect_cuts(th: np.ndarray, *, abs_min: float = 12.0, ratio: float = 4.0, window: int = 12) -> list[int]:
    """Indices k (>= 1) where frame k starts a new shot."""
    d = frame_diffs(th)
    cuts = []
    for i, v in enumerate(d):
        lo, hi = max(0, i - window), min(len(d), i + window + 1)
        neigh = np.delete(d[lo:hi], i - lo)
        base = float(np.median(neigh)) if len(neigh) else 0.0
        if v >= abs_min and v >= ratio * max(base, 1.0):
            cuts.append(i + 1)
    return cuts


def shots(n_frames: int, cuts: list[int]) -> list[tuple[int, int]]:
    """[start, end) frame ranges between cuts."""
    edges = [0, *sorted(c for c in cuts if 0 < c < n_frames), n_frames]
    return [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b > a]
