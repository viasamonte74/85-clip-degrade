"""Descriptive statistics of a degraded LR input against its 1080p reference.

Used both on the CC0 practice-pack inputs (p02-p08) and on locally generated variants, so
the two distributions can be compared with identical code. These describe the
degradation; they are not the competition scorer and say nothing about upscaling quality.

All luma measurements are on 8-bit Y' (limited range) of the decoded frames; the
reference is area-downscaled to the LR geometry with an exact box filter.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from sn85ds.degradation.ops import gaussian_kernel, resize
from sn85ds.media import Yuv420Reader, keyframe_indices, probe

cv2.setNumThreads(1)


def _luma_down(y: np.ndarray, w: int, h: int) -> np.ndarray:
    return resize(y.astype(np.float32)[..., None], w, h, "area")[..., 0]


def immerkaer_sigma(img: np.ndarray) -> float:
    """Immerkaer (1996) fast noise standard deviation estimate (8-bit units)."""
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    conv = cv2.filter2D(img.astype(np.float32), -1, k, borderType=cv2.BORDER_REFLECT_101)[1:-1, 1:-1]
    h, w = img.shape
    return float(math.sqrt(math.pi / 2.0) / (6.0 * (w - 2) * (h - 2)) * np.abs(conv).sum())


def _lap_energy(img: np.ndarray) -> float:
    return float((cv2.Laplacian(img.astype(np.float32), cv2.CV_32F, ksize=1) ** 2).mean())


def _grad_mag(img: np.ndarray) -> float:
    gx = cv2.Sobel(img.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(img.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return float(np.sqrt(gx * gx + gy * gy).mean())


def blockiness(img: np.ndarray, block: int = 8) -> float:
    """Mean |horizontal + vertical step| on block boundaries over the mean elsewhere (1 = none)."""
    f = img.astype(np.float32)
    dx = np.abs(np.diff(f, axis=1))
    dy = np.abs(np.diff(f, axis=0))
    bx = dx[:, block - 1 :: block].mean()
    by = dy[block - 1 :: block, :].mean()
    mx = np.delete(dx, np.s_[block - 1 :: block], axis=1).mean()
    my = np.delete(dy, np.s_[block - 1 :: block], axis=0).mean()
    return float((bx + by) / max(1e-6, mx + my))


SIGMA_GRID = np.round(np.arange(0.0, 2.01, 0.1), 2)


def effective_blur_sigma(ref_down: np.ndarray, lr: np.ndarray) -> float:
    """Gaussian sigma (LR pixels) that, applied to the downscaled reference, best matches the
    LR frame in MSE: a coarse 'how soft is this input' number (noise and coding included)."""
    best, best_s = float("inf"), 0.0
    for s in SIGMA_GRID:
        cand = ref_down if s == 0 else cv2.filter2D(ref_down, -1, gaussian_kernel(float(s)), borderType=cv2.BORDER_REFLECT_101)
        e = float(((cand - lr) ** 2)[4:-4, 4:-4].mean())
        if e < best:
            best, best_s = e, float(s)
    return best_s


def clip_stats(lr_path: str | Path, reference_path: str | Path, *, max_frames: int = 24) -> dict:
    lr_info = probe(lr_path)
    ref_info = probe(reference_path)
    lw, lh = lr_info.width, lr_info.height
    n = min(lr_info.frames, ref_info.frames)
    pick = set(np.unique(np.linspace(1, max(1, n - 1), num=min(max_frames, max(1, n - 1)), dtype=int)).tolist())
    lr_reader = Yuv420Reader(lr_path, allow_convert=True)
    ref_reader = Yuv420Reader(reference_path)
    mse_sum = 0.0
    px = 0
    sharp, grads, sig, nz_lr, nz_ref, blk, blk_ref, temporal = [], [], [], [], [], [], [], []
    prev_res = None
    for k, ((ly, _, _), (ry, _, _)) in enumerate(zip(lr_reader, ref_reader)):
        if k not in pick and (k + 1) not in pick:
            prev_res = None
            continue
        lrf = ly.astype(np.float32)
        rd = _luma_down(ry, lw, lh)
        res = lrf - rd
        if k in pick:
            mse_sum += float((res**2).sum())
            px += res.size
            el_ref = _lap_energy(rd)
            sharp.append(_lap_energy(lrf) / max(1e-6, el_ref))
            grads.append(_grad_mag(lrf) / max(1e-6, _grad_mag(rd)))
            if len(sig) < 6:
                sig.append(effective_blur_sigma(rd, lrf))
            nz_lr.append(immerkaer_sigma(lrf))
            nz_ref.append(immerkaer_sigma(rd))
            blk.append(blockiness(lrf))
            blk_ref.append(blockiness(rd))
            if prev_res is not None:
                temporal.append(float((res - prev_res).std()))
        prev_res = res
    mse = mse_sum / max(1, px)
    keys = keyframe_indices(lr_path)
    gaps = np.diff(keys).tolist() if len(keys) > 1 else []
    fps = float(lr_info.fps_fraction) if lr_info.fps not in ("0", "0/1") else 0.0
    return {
        "lr_codec": lr_info.codec,
        "lr_size": [lw, lh],
        "fps": lr_info.fps,
        "frames": lr_info.frames,
        "bitrate_kbps": round((lr_info.size_bytes * 8 / max(1e-6, lr_info.duration_s)) / 1000.0, 1),
        "keyframes": len(keys),
        "max_gop_frames": int(max(gaps)) if gaps else int(lr_info.frames),
        "gop_seconds_max": round((max(gaps) if gaps else lr_info.frames) / fps, 3) if fps else None,
        "luma_psnr_vs_area_down": round(10 * math.log10(255.0**2 / mse), 3) if mse > 0 else 99.0,
        "hf_energy_ratio": round(float(np.median(sharp)), 4),
        "gradient_ratio": round(float(np.median(grads)), 4),
        "effective_blur_sigma_lr_px": round(float(np.median(sig)), 2),
        "noise_sigma_lr": round(float(np.median(nz_lr)), 3),
        "noise_sigma_ref_down": round(float(np.median(nz_ref)), 3),
        "noise_sigma_added": round(float(np.median(nz_lr) - np.median(nz_ref)), 3),
        "temporal_residual_std": round(float(np.median(temporal)), 3) if temporal else None,
        "blockiness": round(float(np.median(blk)), 4),
        "blockiness_ref_down": round(float(np.median(blk_ref)), 4),
        "frames_measured": len(sharp),
    }
