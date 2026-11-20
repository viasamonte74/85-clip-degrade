"""Per-variant degradation recipe: sampled once per clip from a seed, fully recorded.

The recipe is the complete description of what happens to one reference to make one
low-resolution input; re-running the pipeline with the same recipe and reference
reproduces the same frames bit-exactly (encoder threads are fixed).
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, Field

from sn85ds import PIPELINE_VERSION
from sn85ds.util import CONFIG, even, sha256_bytes

Difficulty = Literal["mild", "medium", "heavy"]
ResizeFilter = Literal["area", "bilinear", "bicubic", "lanczos", "spline"]


class BlurSpec(BaseModel):
    kind: Literal["none", "isotropic", "anisotropic", "directional"]
    sigma_x: float = 0.0
    sigma_y: float = 0.0
    theta_rad: float = 0.0
    length_px: float = 0.0


class NoiseSpec(BaseModel):
    enabled: bool = False
    level: float = 0.0
    shot_fraction: float = 0.0
    spatial_sigma: float = 0.0
    chroma: float = 0.0
    temporal_rho: float = 0.0
    seed: int = 0
    dark_boost: float = 1.0


class JpegSpec(BaseModel):
    enabled: bool = False
    quality: int = 100


class EncodeSpec(BaseModel):
    codec: Literal["h264", "hevc"]
    encoder: Literal["libx264", "libx265"]
    bitrate_kbps: int
    maxrate_kbps: int
    bufsize_kbps: int
    gop_frames: int
    scenecut: bool
    bframes: int
    preset: str
    threads: int
    pix_fmt: Literal["yuv420p"] = "yuv420p"
    color: str = "bt709-limited"


class Recipe(BaseModel):
    pipeline_version: str = PIPELINE_VERSION
    config_digest: str
    seed: int
    difficulty: Difficulty
    upscale_factor: Literal[2, 4]
    orientation: Literal["landscape", "portrait"]
    reference_size: tuple[int, int]
    lr_size: tuple[int, int]
    intermediate_scale: float
    intermediate_size: tuple[int, int]
    fps: str
    blur1: BlurSpec
    resize1: ResizeFilter
    noise1: NoiseSpec
    jpeg: JpegSpec
    blur2: BlurSpec
    resize2: ResizeFilter
    noise2: NoiseSpec
    encode: EncodeSpec
    stress_mode: bool = False
    notes: list[str] = Field(default_factory=list)


def load_config(path: str | Path | None = None) -> tuple[dict, str]:
    p = Path(path) if path else CONFIG / "degradation.yaml"
    raw = p.read_bytes()
    return yaml.safe_load(raw), sha256_bytes(raw)


def lr_size_for(ref_w: int, ref_h: int, factor: int) -> tuple[int, int]:
    if ref_w % factor or ref_h % factor:
        raise ValueError(f"reference {ref_w}x{ref_h} is not divisible by {factor}")
    return ref_w // factor, ref_h // factor


def _choice(rng: np.random.Generator, weights: dict[str, float]) -> str:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=np.float64)
    return keys[int(rng.choice(len(keys), p=p / p.sum()))]


def _u(rng: np.random.Generator, lo_hi) -> float:
    lo, hi = float(lo_hi[0]), float(lo_hi[1])
    return lo if hi <= lo else float(rng.uniform(lo, hi))


def _blur(rng, spec: dict, cfg: dict, *, stage: int, stress: bool) -> BlurSpec:
    if rng.random() < spec["p_none"]:
        return BlurSpec(kind="none")
    lo, hi = spec["sigma"]
    if stress and stage == 1:
        hi = max(hi, cfg["stress"]["blur1_sigma_max"])
    sigma = _u(rng, (lo, hi))
    if stage == 1:
        kind = _choice(rng, cfg["blur1_shape"])
    else:
        kind = "anisotropic" if rng.random() < cfg["blur2_anisotropic_share"] else "isotropic"
    if kind == "isotropic":
        return BlurSpec(kind=kind, sigma_x=sigma, sigma_y=sigma)
    if kind == "anisotropic":
        ratio = _u(rng, cfg["anisotropic_ratio"])
        return BlurSpec(kind=kind, sigma_x=sigma, sigma_y=sigma * ratio, theta_rad=float(rng.uniform(0, math.pi)))
    length = _u(rng, cfg["directional_length_px"])
    return BlurSpec(kind="directional", length_px=length, theta_rad=float(rng.uniform(0, math.pi)), sigma_x=0.5)


def _noise(rng, spec: dict, cfg: dict, *, darkness: float, primary: bool, seed: int) -> NoiseSpec:
    nm = cfg["noise_model"]
    p = spec["p"]
    boost = 1.0
    if primary and darkness > 0:
        p = max(p, nm["dark_boost"]["p_min"])
        boost = 1.0 + nm["dark_boost"]["level_gain"] * darkness
    if rng.random() >= p:
        return NoiseSpec(enabled=False)
    spatial = 0.0 if rng.random() < nm["spatial_none_share"] else _u(rng, nm["spatial_sigma"])
    return NoiseSpec(
        enabled=True,
        level=_u(rng, spec["level"]) * boost,
        shot_fraction=_u(rng, nm["shot_fraction"]),
        spatial_sigma=spatial if primary else 0.0,
        chroma=_u(rng, nm["chroma"]),
        temporal_rho=_u(rng, nm["temporal_rho"]) if primary else 0.0,
        seed=seed,
        dark_boost=boost,
    )


def sample_recipe(*, reference_size: tuple[int, int], fps: str, factor: int, seed: int,
                  mean_luma: float, config: dict, config_digest: str,
                  difficulty: Difficulty | None = None) -> Recipe:
    """Draw one recipe. ``mean_luma`` (clip mean of non-linear luma, 0..1) drives the
    dark-clip noise boost."""
    rng = np.random.Generator(np.random.PCG64(seed))
    stress = bool(config.get("stress_mode", False))
    if difficulty is None:
        difficulty = _choice(rng, config["difficulty_shares"])  # type: ignore[assignment]
    d = config["difficulty"][difficulty]
    rw, rh = reference_size
    orientation = "landscape" if rw >= rh else "portrait"
    lw, lh = lr_size_for(rw, rh, factor)
    m = _u(rng, d["intermediate_scale"])
    iw = even(lw * m)
    ih = even(iw * lh / lw)
    iw, ih = min(iw, rw), min(ih, rh)
    nm = config["noise_model"]["dark_boost"]
    darkness = float(np.clip((nm["mean_luma_threshold"] - mean_luma) / nm["mean_luma_threshold"], 0.0, 1.0))

    blur1 = _blur(rng, d["blur1"], config, stage=1, stress=stress)
    resize1 = _choice(rng, config["resize_filters"])
    noise1 = _noise(rng, d["noise1"], config, darkness=darkness, primary=True, seed=(seed * 7919 + 1) % (1 << 63))
    nf = float(config.get("noise_level_by_factor", {}).get(factor, 1.0))  # v1.3; scaling after the draw keeps older recipes identical
    if nf != 1.0 and noise1.enabled:
        noise1 = noise1.model_copy(update={"level": noise1.level * nf})
    jq_lo, jq_hi = d["jpeg"]["quality"]
    if stress:
        jq_lo = min(jq_lo, config["stress"]["jpeg_quality_min"])
    jpeg = JpegSpec(enabled=bool(rng.random() < d["jpeg"]["p"]), quality=int(rng.integers(jq_lo, jq_hi + 1)))
    if not jpeg.enabled:
        jpeg = JpegSpec(enabled=False)
    blur2 = _blur(rng, d["blur2"], config, stage=2, stress=stress)
    resize2 = _choice(rng, config["resize_filters"])
    noise2 = _noise(rng, d["noise2"], config, darkness=0.0, primary=False, seed=(seed * 104729 + 2) % (1 << 63))

    enc = config["encode"]
    codec = _choice(rng, enc["codec_weights"])
    lo, hi = enc["bitrate_kbps"][factor]
    if codec == "hevc":
        lo *= enc["hevc_low_extension"]
    q_lo, q_hi = d["bitrate_quantile"]
    q = _u(rng, (q_lo, q_hi))
    kbps = math.exp(math.log(lo) + q * (math.log(hi) - math.log(lo)))
    fr = Fraction(fps)
    notes = []
    if float(fr) >= enc["high_fps_threshold"]:
        mult = _u(rng, enc["high_fps_multiplier"])
        kbps *= mult
        notes.append(f"high-fps bitrate multiplier {mult:.3f}")
    kbps_i = int(round(kbps))
    gop = max(1, int(round(enc["gop_seconds"] * float(fr))))
    encode = EncodeSpec(
        codec=codec,  # type: ignore[arg-type]
        encoder="libx264" if codec == "h264" else "libx265",
        bitrate_kbps=kbps_i,
        maxrate_kbps=int(round(kbps_i * enc["vbv_maxrate_factor"])),
        bufsize_kbps=int(round(kbps_i * enc["vbv_bufsize_factor"])),
        gop_frames=gop,
        scenecut=bool(enc["scenecut"]),
        bframes=int(enc["bframes"]),
        preset=_choice(rng, enc["preset_weights"]),
        threads=int(enc["threads"]),
    )
    if darkness > 0:
        notes.append(f"dark clip (mean luma {mean_luma:.3f}): noise boost x{noise1.dark_boost:.2f}")
    return Recipe(
        config_digest=config_digest, seed=seed, difficulty=difficulty, upscale_factor=factor,  # type: ignore[arg-type]
        orientation=orientation, reference_size=(rw, rh), lr_size=(lw, lh), intermediate_scale=round(m, 4),
        intermediate_size=(iw, ih), fps=str(fr), blur1=blur1, resize1=resize1, noise1=noise1, jpeg=jpeg,  # type: ignore[arg-type]
        blur2=blur2, resize2=resize2, noise2=noise2, encode=encode, stress_mode=stress, notes=notes,  # type: ignore[arg-type]
    )
