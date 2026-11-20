"""ffprobe/ffmpeg wrappers: probing, raw 4:2:0 frame pipes, FFV1 reference writing.

Every pipe is explicit about pixel format, size and rational frame rate so ffmpeg never
inserts a hidden scale, colour conversion or frame-rate change.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterator

import numpy as np

from sn85ds.util import FFMPEG, FFPROBE, nice_prefix

BT709_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


@dataclass(frozen=True)
class VideoInfo:
    path: str
    codec: str
    width: int
    height: int
    pix_fmt: str
    fps: str  # exact rational "num/den"
    frames: int
    duration_s: float
    bit_rate: int | None
    color_space: str
    color_range: str
    color_primaries: str
    color_transfer: str
    chroma_location: str
    field_order: str
    container: str
    size_bytes: int

    @property
    def fps_fraction(self) -> Fraction:
        return Fraction(self.fps)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _ffprobe_json(args: list[str]) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-of", "json", *args], capture_output=True, check=True, timeout=600)
    return json.loads(out.stdout)


def probe(path: str | Path, count_frames: bool = True) -> VideoInfo:
    """Probe the first video stream. ``count_frames`` counts packets (exact for CFR files)."""
    p = str(path)
    extra = ["-count_packets"] if count_frames else []
    d = _ffprobe_json([*extra, "-select_streams", "v:0", "-show_streams", "-show_format", p])
    s = d["streams"][0]
    f = d.get("format", {})
    frames = int(s.get("nb_read_packets") or s.get("nb_frames") or 0)
    rate = s.get("r_frame_rate") or s.get("avg_frame_rate") or "0/1"
    br = s.get("bit_rate") or f.get("bit_rate")
    return VideoInfo(
        path=p,
        codec=s.get("codec_name", ""),
        width=int(s["width"]),
        height=int(s["height"]),
        pix_fmt=s.get("pix_fmt", ""),
        fps=str(Fraction(rate)) if "/" in rate else rate,
        frames=frames,
        duration_s=float(f.get("duration") or s.get("duration") or 0.0),
        bit_rate=int(br) if br not in (None, "N/A") else None,
        color_space=s.get("color_space", "unknown"),
        color_range=s.get("color_range", "unknown"),
        color_primaries=s.get("color_primaries", "unknown"),
        color_transfer=s.get("color_transfer", "unknown"),
        chroma_location=s.get("chroma_location", "unspecified"),
        field_order=s.get("field_order", "unknown"),
        container=f.get("format_name", ""),
        size_bytes=int(f.get("size") or Path(p).stat().st_size),
    )


def fps_str(fps: str | Fraction) -> str:
    """'24' / '30000/1001' form of an exact frame rate (accepted by ffmpeg -framerate)."""
    fr = Fraction(fps)
    return str(fr.numerator) if fr.denominator == 1 else f"{fr.numerator}/{fr.denominator}"


def frame_timestamps(path: str | Path) -> list[float]:
    d = _ffprobe_json(["-select_streams", "v:0", "-show_entries", "frame=best_effort_timestamp_time", str(path)])
    return [float(fr["best_effort_timestamp_time"]) for fr in d.get("frames", []) if fr.get("best_effort_timestamp_time") not in (None, "N/A")]


def keyframe_indices(path: str | Path) -> list[int]:
    d = _ffprobe_json(["-select_streams", "v:0", "-show_entries", "frame=key_frame", str(path)])
    return [i for i, fr in enumerate(d.get("frames", [])) if int(fr.get("key_frame", 0)) == 1]


class Yuv420Reader:
    """Decodes a video to raw 8-bit 4:2:0 planes. The source must already be yuv420p
    (references are); ``allow_convert`` permits ffmpeg's pixel-format conversion for
    inspection-only uses (e.g. 10-bit or 4:2:2 masters)."""

    def __init__(self, path: str | Path, *, allow_convert: bool = False):
        self.info = probe(path)
        if self.info.pix_fmt != "yuv420p" and not allow_convert:
            raise ValueError(f"{path}: pix_fmt {self.info.pix_fmt}, expected yuv420p")
        self.w, self.h = self.info.width, self.info.height
        if self.w % 2 or self.h % 2:
            raise ValueError(f"{path}: odd frame size {self.w}x{self.h}")
        self.path = str(path)

    def __iter__(self) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        w, h = self.w, self.h
        ysz, csz = w * h, (w // 2) * (h // 2)
        cmd = [FFMPEG, "-v", "error", "-nostdin", "-i", self.path, "-map", "0:v:0", "-fps_mode", "passthrough",
               "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=ysz * 2)
        assert proc.stdout is not None
        finished = False
        try:
            while True:
                buf = proc.stdout.read(ysz + 2 * csz)
                if not buf:
                    finished = True
                    break
                if len(buf) != ysz + 2 * csz:
                    raise IOError(f"{self.path}: truncated frame ({len(buf)} bytes)")
                a = np.frombuffer(buf, dtype=np.uint8)
                yield (a[:ysz].reshape(h, w), a[ysz:ysz + csz].reshape(h // 2, w // 2),
                       a[ysz + csz:].reshape(h // 2, w // 2))
        finally:
            if not finished:  # consumer stopped early: stop the decoder quietly
                proc.kill()
            proc.stdout.close()
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            if proc.stderr:
                proc.stderr.close()
            rc = proc.wait()
            if finished and rc != 0:
                raise RuntimeError(f"ffmpeg decode of {self.path} failed ({rc}): {err[-500:]}")


def plane_checksum_update(h: "hashlib._Hash", y: np.ndarray, u: np.ndarray, v: np.ndarray) -> None:
    h.update(np.ascontiguousarray(y).tobytes())
    h.update(np.ascontiguousarray(u).tobytes())
    h.update(np.ascontiguousarray(v).tobytes())


def decoded_checksum(path: str | Path) -> tuple[str, int]:
    """sha256 over every decoded 8-bit 4:2:0 plane in order, and the frame count."""
    h = hashlib.sha256()
    n = 0
    for y, u, v in Yuv420Reader(path):
        plane_checksum_update(h, y, u, v)
        n += 1
    return h.hexdigest(), n


class RawYuv420Writer:
    """Pipes raw 8-bit 4:2:0 frames into an ffmpeg encoder command.

    ``codec_args`` follow the input; the input side is fixed: rawvideo yuv420p at the given
    size and exact rational rate, so frame count and order are exactly what is written."""

    def __init__(self, out_path: str | Path, width: int, height: int, fps: str, codec_args: list[str],
                 *, container: str | None = None, threads_nice: bool = True):
        self.w, self.h = width, height
        self.out_path = str(out_path)
        self.cmd = [*(nice_prefix() if threads_nice else []), FFMPEG, "-v", "error", "-nostdin", "-y",
                    "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{width}x{height}",
                    "-framerate", fps_str(fps), "-i", "-", "-an", *codec_args,
                    *(["-f", container] if container else []), self.out_path]
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.frames = 0
        self.hash = hashlib.sha256()

    def write(self, y: np.ndarray, u: np.ndarray, v: np.ndarray) -> None:
        if y.shape != (self.h, self.w) or u.shape != (self.h // 2, self.w // 2) or v.shape != u.shape:
            raise ValueError(f"plane shapes {y.shape} {u.shape} {v.shape} != {self.w}x{self.h} 4:2:0")
        assert self.proc.stdin is not None
        for p in (y, u, v):
            if p.dtype != np.uint8:
                raise TypeError("planes must be uint8")
        plane_checksum_update(self.hash, y, u, v)
        self.proc.stdin.write(np.ascontiguousarray(y).tobytes())
        self.proc.stdin.write(np.ascontiguousarray(u).tobytes())
        self.proc.stdin.write(np.ascontiguousarray(v).tobytes())
        self.frames += 1

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError(f"encoder failed ({rc}): {err[-2000:]}")

    def __enter__(self) -> "RawYuv420Writer":
        return self

    def __exit__(self, et, ev, tb) -> None:
        if et is None:
            self.close()
        else:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            finally:
                self.proc.kill()
                self.proc.wait()


def ffv1_args(threads: int = 2) -> list[str]:
    """Lossless FFV1 v3 in Matroska, every frame intra, slice CRCs on, BT.709 limited tags."""
    return ["-c:v", "ffv1", "-level", "3", "-g", "1", "-slices", "4", "-slicecrc", "1", "-context", "1",
            "-threads", str(threads), "-pix_fmt", "yuv420p", *BT709_TAGS, "-chroma_sample_location", "left"]
