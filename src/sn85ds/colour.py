"""Explicit BT.709 limited-range conversions between 8-bit 4:2:0 and float R'G'B'.

The degradation operates on non-linear R'G'B' in [0, 1] (what a camera or renderer
outputs before encoding). Conversions are written out here, not delegated to ffmpeg's
defaults, so the colour interpretation is fixed and documented:

* matrix BT.709 (Kr = 0.2126, Kb = 0.0722), limited range (Y 16-235, C 16-240);
* 4:2:0 chroma sited "left" (MPEG-2 / H.264 default): co-sited with even luma columns,
  vertically centred between the two luma rows;
* upsampling: linear interpolation at that siting; downsampling: [1, 2, 1] / 4 horizontally
  around the co-sited column, mean of the two rows vertically.
"""

from __future__ import annotations

import cv2
import numpy as np

cv2.setNumThreads(1)

KR, KB = 0.2126, 0.0722
KG = 1.0 - KR - KB

# Fast paths (OpenCV SIMD) implementing exactly the same maths as the reference
# functions below; tests assert equality. Chroma upsampling uses inverse affine maps:
# luma (x, y) samples chroma at (x / 2, y / 2 - 0.25) = left-sited, vertically centred.
_M_UP = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, -0.25]], np.float32)
_A, _C = 1.0 / 219.0, 1.0 / 224.0
_R_CR = 2.0 * (1.0 - KR) * _C
_B_CB = 2.0 * (1.0 - KB) * _C
_G_CB = -KB * 2.0 * (1.0 - KB) * _C / KG
_G_CR = -KR * 2.0 * (1.0 - KR) * _C / KG
_YCC_TO_RGB = np.array([
    [_A, 0.0, _R_CR, -16.0 * _A - 128.0 * _R_CR],
    [_A, _G_CB, _G_CR, -16.0 * _A - 128.0 * (_G_CB + _G_CR)],
    [_A, _B_CB, 0.0, -16.0 * _A - 128.0 * _B_CB],
], np.float32)
_RGB_TO_YCC = np.array([
    [219.0 * KR, 219.0 * KG, 219.0 * KB, 16.0],
    [224.0 * -KR / (2 * (1 - KB)), 224.0 * -KG / (2 * (1 - KB)), 224.0 * (1 - KB) / (2 * (1 - KB)), 128.0],
    [224.0 * (1 - KR) / (2 * (1 - KR)), 224.0 * -KG / (2 * (1 - KR)), 224.0 * -KB / (2 * (1 - KR)), 128.0],
], np.float32)
# 2x3 kernel: mean of the two rows, [1, 2, 1] / 4 around the co-sited column
_DOWN_K = np.array([[1.0, 2.0, 1.0], [1.0, 2.0, 1.0]], np.float32) / 8.0


def yuv420_to_rgb(y: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """8-bit 4:2:0 BT.709 limited -> float32 R'G'B' (H, W, 3), clipped to [0, 1]."""
    h, w = y.shape
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    uu = cv2.warpAffine(u.astype(np.float32), _M_UP, (w, h), flags=flags, borderMode=cv2.BORDER_REPLICATE)
    vv = cv2.warpAffine(v.astype(np.float32), _M_UP, (w, h), flags=flags, borderMode=cv2.BORDER_REPLICATE)
    rgb = cv2.transform(cv2.merge([y.astype(np.float32), uu, vv]), _YCC_TO_RGB)
    return np.clip(rgb, 0.0, 1.0, out=rgb)


def rgb_to_yuv420(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """float R'G'B' (H, W, 3) -> 8-bit 4:2:0 BT.709 limited planes. H and W must be even."""
    h, w = rgb.shape[:2]
    if h % 2 or w % 2:
        raise ValueError(f"odd frame size {w}x{h}")
    ycc = cv2.transform(np.ascontiguousarray(rgb, dtype=np.float32), _RGB_TO_YCC)
    yy, cb, cr = cv2.split(ycc)
    # filter2D anchor (1, 0): out(r, c) = sum_k K[i, j] * in(r + i, c + j - 1)
    cbd = cv2.filter2D(cb, -1, _DOWN_K, anchor=(1, 0), borderType=cv2.BORDER_REPLICATE)[0::2, 0::2]
    crd = cv2.filter2D(cr, -1, _DOWN_K, anchor=(1, 0), borderType=cv2.BORDER_REPLICATE)[0::2, 0::2]
    return _to_u8(yy), _to_u8(cbd), _to_u8(crd)


# ---- reference implementations (plain NumPy; the test oracle for the fast paths) ----


def _up_h_left(c: np.ndarray, width: int) -> np.ndarray:
    """Horizontal 2x upsample for left-sited chroma: even columns copy, odd columns average."""
    out = np.empty((c.shape[0], width), dtype=np.float32)
    out[:, 0::2] = c
    nxt = np.concatenate([c[:, 1:], c[:, -1:]], axis=1)
    out[:, 1::2] = 0.5 * (c + nxt)
    return out


def _up_v_centre(c: np.ndarray, height: int) -> np.ndarray:
    """Vertical 2x upsample for centre-sited rows (bilinear: 3/4 + 1/4 of the neighbours)."""
    prv = np.concatenate([c[:1], c[:-1]], axis=0)
    nxt = np.concatenate([c[1:], c[-1:]], axis=0)
    out = np.empty((height, c.shape[1]), dtype=np.float32)
    out[0::2] = 0.75 * c + 0.25 * prv
    out[1::2] = 0.75 * c + 0.25 * nxt
    return out


def upsample_chroma(c: np.ndarray, width: int, height: int) -> np.ndarray:
    return _up_v_centre(_up_h_left(c.astype(np.float32), width), height)


def downsample_chroma(c: np.ndarray) -> np.ndarray:
    """Full-resolution chroma plane (float) -> 4:2:0 left-sited plane (float)."""
    v = 0.5 * (c[0::2] + c[1::2])
    left = np.concatenate([v[:, :1], v[:, 1:-1:2]], axis=1)  # column 2k-1 (edge-replicated at k=0)
    centre = v[:, 0::2]
    right = v[:, 1::2]
    return 0.25 * left + 0.5 * centre + 0.25 * right


def yuv420_to_rgb_reference(y: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Reference (NumPy) version of :func:`yuv420_to_rgb`."""
    h, w = y.shape
    yf = (y.astype(np.float32) - 16.0) / 219.0
    cb = (upsample_chroma(u, w, h) - 128.0) / 224.0
    cr = (upsample_chroma(v, w, h) - 128.0) / 224.0
    r = yf + 2.0 * (1.0 - KR) * cr
    b = yf + 2.0 * (1.0 - KB) * cb
    g = (yf - KR * r - KB * b) / KG
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0)


def rgb_to_yuv444(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """float R'G'B' -> float Y'CbCr in 8-bit limited-range code values (not rounded)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    yl = KR * r + KG * g + KB * b
    cb = (b - yl) / (2.0 * (1.0 - KB))
    cr = (r - yl) / (2.0 * (1.0 - KR))
    return 16.0 + 219.0 * yl, 128.0 + 224.0 * cb, 128.0 + 224.0 * cr


def _to_u8(p: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(p), 0, 255).astype(np.uint8)


def rgb_to_yuv420_reference(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reference (NumPy) version of :func:`rgb_to_yuv420`."""
    h, w = rgb.shape[:2]
    if h % 2 or w % 2:
        raise ValueError(f"odd frame size {w}x{h}")
    yy, cb, cr = rgb_to_yuv444(rgb.astype(np.float32))
    return _to_u8(yy), _to_u8(downsample_chroma(cb)), _to_u8(downsample_chroma(cr))


def luma_u8_to_float(y: np.ndarray) -> np.ndarray:
    return (y.astype(np.float32) - 16.0) / 219.0
