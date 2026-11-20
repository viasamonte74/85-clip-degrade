"""Degradation operators on float32 R'G'B' frames (H, W, 3) in [0, 1].

* blur kernels: isotropic Gaussian, anisotropic (rotated) Gaussian, directional line blur;
* resampling: separable, antialiased (the kernel is widened by the scale factor when
  downscaling, as Pillow and ffmpeg/swscale do) for the five filter families the practice
  pack names: area, bilinear, bicubic, Lanczos, spline;
* sensor-like noise: Poisson-Gaussian in (approximately) linear light, so darker regions
  get relatively stronger noise once gamma-encoded, with optional spatial, cross-channel
  and AR(1) temporal correlation, from a seeded generator;
* JPEG-style blocking via libjpeg (OpenCV).

Which of these the hidden set uses, and with which parameters, is not public. The kernel
shapes are standard textbook definitions; every parameter is chosen by the recipe sampler
and recorded with the variant.
"""

from __future__ import annotations

import math
from functools import lru_cache

import cv2
import numpy as np
import scipy.sparse as sp

cv2.setNumThreads(1)

# ---------------------------------------------------------------------------------------
# blur kernels


def gaussian_kernel(sigma_x: float, sigma_y: float | None = None, theta: float = 0.0) -> np.ndarray:
    """Normalised (rotated) 2-D Gaussian. ``theta`` rotates the x axis (radians)."""
    sigma_y = sigma_x if sigma_y is None else sigma_y
    smax = max(sigma_x, sigma_y)
    r = max(1, int(math.ceil(3.0 * smax)))
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1].astype(np.float64)
    c, s = math.cos(theta), math.sin(theta)
    u = c * xx + s * yy
    v = -s * xx + c * yy
    k = np.exp(-0.5 * ((u / sigma_x) ** 2 + (v / sigma_y) ** 2))
    return (k / k.sum()).astype(np.float32)


def line_kernel(length: float, angle: float, soften: float = 0.5) -> np.ndarray:
    """Directional (motion-like) blur: a line of ``length`` px at ``angle``, softened by a
    small Gaussian so it is not aliased."""
    r = max(1, int(math.ceil(length / 2.0 + 3.0 * soften)))
    size = 2 * r + 1
    k = np.zeros((size, size), np.float32)
    n = max(2, int(math.ceil(length * 4)))
    for t in np.linspace(-length / 2.0, length / 2.0, n):
        x = r + t * math.cos(angle)
        y = r + t * math.sin(angle)
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - x0, y - y0
        for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            if 0 <= x0 + dx < size and 0 <= y0 + dy < size:
                k[y0 + dy, x0 + dx] += w
    if soften > 0:
        k = cv2.GaussianBlur(k, (0, 0), soften)
    return k / k.sum()


def apply_kernel(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    return cv2.filter2D(img, -1, kernel, borderType=cv2.BORDER_REFLECT_101)


# ---------------------------------------------------------------------------------------
# resampling


def _box(x: np.ndarray) -> np.ndarray:
    return ((x >= -0.5) & (x < 0.5)).astype(np.float64)


def _triangle(x: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - np.abs(x), 0.0, None)


def _keys_cubic(x: np.ndarray, a: float = -0.5) -> np.ndarray:
    x = np.abs(x)
    out = np.zeros_like(x)
    m1 = x < 1
    m2 = (x >= 1) & (x < 2)
    out[m1] = (a + 2) * x[m1] ** 3 - (a + 3) * x[m1] ** 2 + 1
    out[m2] = a * x[m2] ** 3 - 5 * a * x[m2] ** 2 + 8 * a * x[m2] - 4 * a
    return out


def _lanczos3(x: np.ndarray) -> np.ndarray:
    out = np.sinc(x) * np.sinc(x / 3.0)
    out[np.abs(x) >= 3.0] = 0.0
    return out


def _spline36(x: np.ndarray) -> np.ndarray:
    """Spline36 (the Avisynth / zimg 'spline36' kernel)."""
    x = np.abs(x)
    out = np.zeros_like(x)
    a = x < 1
    b = (x >= 1) & (x < 2)
    c = (x >= 2) & (x < 3)
    xa = x[a]
    out[a] = ((13.0 / 11.0 * xa - 453.0 / 209.0) * xa - 3.0 / 209.0) * xa + 1.0
    xb = x[b] - 1.0
    out[b] = ((-6.0 / 11.0 * xb + 270.0 / 209.0) * xb - 156.0 / 209.0) * xb
    xc = x[c] - 2.0
    out[c] = ((1.0 / 11.0 * xc - 45.0 / 209.0) * xc + 26.0 / 209.0) * xc
    return out


FILTERS = {
    "area": (_box, 0.5),
    "bilinear": (_triangle, 1.0),
    "bicubic": (_keys_cubic, 2.0),
    "lanczos": (_lanczos3, 3.0),
    "spline": (_spline36, 3.0),
}


@lru_cache(maxsize=256)
def resample_matrix(n_in: int, n_out: int, kind: str) -> sp.csr_matrix:
    """(n_out x n_in) weights of a pixel-centre-aligned, antialiased 1-D resample."""
    fn, support = FILTERS[kind]
    scale = n_in / n_out
    fscale = max(scale, 1.0)
    sup = support * fscale
    rows, cols, vals = [], [], []
    for i in range(n_out):
        centre = (i + 0.5) * scale
        lo = int(math.floor(centre - sup))
        hi = int(math.ceil(centre + sup))
        j = np.arange(lo, hi + 1)
        w = fn((j + 0.5 - centre) / fscale)
        if w.sum() == 0:
            w = np.ones_like(w)
        w = w / w.sum()
        jj = np.clip(j, 0, n_in - 1)  # edge replication
        nz = w != 0
        rows.extend([i] * int(nz.sum()))
        cols.extend(jj[nz].tolist())
        vals.extend(w[nz].tolist())
    m = sp.coo_matrix((vals, (rows, cols)), shape=(n_out, n_in), dtype=np.float32)
    return m.tocsr()  # duplicates (clipped edge taps) are summed


def resize(img: np.ndarray, width: int, height: int, kind: str) -> np.ndarray:
    """Separable antialiased resize of an (H, W, C) float32 image."""
    h, w, c = img.shape
    if (w, h) == (width, height):
        return img.copy()
    mh = resample_matrix(h, height, kind)
    mw = resample_matrix(w, width, kind)
    tmp = mh @ img.reshape(h, w * c)  # (height, w*c)
    tmp = tmp.reshape(height, w, c).transpose(1, 0, 2).reshape(w, height * c)
    out = (mw @ tmp).reshape(width, height, c).transpose(1, 0, 2)
    return np.ascontiguousarray(out, dtype=np.float32)


# ---------------------------------------------------------------------------------------
# sensor-like noise

GAMMA = 2.2  # approximate camera transfer used to place the noise in linear light (assumption)


class SensorNoise:
    """Temporally varying Poisson-Gaussian noise with optional correlations.

    ``level`` is the noise standard deviation in 8-bit code values on a mid-grey
    (non-linear 0.5) patch; ``shot_fraction`` is the share of that variance which is
    signal-dependent (shot) noise. Noise is added in linear light (gamma ``GAMMA``), so
    after re-encoding it is relatively stronger in dark regions, as on real sensors.
    ``spatial_sigma`` correlates neighbouring pixels (demosaic/processing), ``chroma``
    mixes a shared (luma-like) component with independent per-channel noise (0 = luma
    only, 1 = fully independent RGB), and ``temporal_rho`` is the AR(1) correlation of the
    noise field between consecutive frames (0 = independent every frame).
    """

    def __init__(self, *, level: float, shot_fraction: float, spatial_sigma: float, chroma: float,
                 temporal_rho: float, seed: int):
        self.level = float(level)
        self.shot_fraction = float(shot_fraction)
        self.spatial_sigma = float(spatial_sigma)
        self.chroma = float(np.clip(chroma, 0.0, 1.0))
        self.rho = float(np.clip(temporal_rho, 0.0, 0.95))
        self.rng = np.random.Generator(np.random.PCG64(seed))
        mid_lin = 0.5**GAMMA
        slope = (1.0 / GAMMA) * mid_lin ** (1.0 / GAMMA - 1.0)  # d(nonlinear)/d(linear) at mid grey
        sigma_lin = (self.level / 255.0) / slope
        var = sigma_lin**2
        self.a = self.shot_fraction * var / mid_lin  # shot: var = a * I_lin
        self.b = (1.0 - self.shot_fraction) * var  # read: constant var
        self._prev: np.ndarray | None = None

    def _field(self, shape: tuple[int, int, int]) -> np.ndarray:
        h, w, _ = shape
        shared = self.rng.standard_normal((h, w, 1), dtype=np.float32)
        indep = self.rng.standard_normal((h, w, 3), dtype=np.float32)
        z = math.sqrt(1.0 - self.chroma) * shared + math.sqrt(self.chroma) * indep
        if self.spatial_sigma > 0.05:
            ks = 2 * int(math.ceil(3.0 * self.spatial_sigma)) + 1
            z = cv2.GaussianBlur(z, (ks, ks), self.spatial_sigma, borderType=cv2.BORDER_REFLECT_101)
            # restore unit variance: a separable kernel k scales white-noise variance by (sum k^2)^2
            k1 = cv2.getGaussianKernel(ks, self.spatial_sigma).ravel()
            z = z / float((k1**2).sum())
        if self._prev is not None and self._prev.shape == z.shape and self.rho > 0:
            z = self.rho * self._prev + math.sqrt(1.0 - self.rho**2) * z
        self._prev = z
        return z

    def __call__(self, img: np.ndarray) -> np.ndarray:
        lin = cv2.pow(np.clip(img, 0.0, 1.0).astype(np.float32, copy=False), GAMMA)
        sigma = cv2.sqrt(lin * np.float32(self.a) + np.float32(self.b))
        lin = np.clip(lin + sigma * self._field(img.shape), 0.0, 1.0)
        return cv2.pow(lin.astype(np.float32, copy=False), 1.0 / GAMMA)


# ---------------------------------------------------------------------------------------
# JPEG-style blocking


def jpeg_roundtrip(img: np.ndarray, quality: int) -> np.ndarray:
    """Encode/decode one frame as baseline JPEG (4:2:0, OpenCV/libjpeg defaults)."""
    u8 = np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(u8, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    out = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return out.astype(np.float32) / 255.0
