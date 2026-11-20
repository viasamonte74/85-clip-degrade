"""Contact sheets: reference / stage 1 / stage 2 / final LR / Lanczos-upscaled LR, plus detail crops."""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from sn85ds.util import FFMPEG

PANEL_W = 384
LABELS = ["1 original reference", "2 stage 1 (intermediate)", "3 stage 2 (LR, pre-encode)", "4 final LR input (decoded)",
          "5 LR Lanczos-upscaled"]


def decode_frame(path: Path, index: int, scale_to: tuple[int, int] | None = None) -> np.ndarray:
    vf = f"select=eq(n\\,{index})"
    if scale_to:
        vf += f",scale={scale_to[0]}:{scale_to[1]}:flags=lanczos"
    raw = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-i", str(path), "-vf", vf, "-fps_mode", "passthrough", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    if scale_to:
        w, h = scale_to
    else:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
        w, h = int(p[0]), int(p[1])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def detail_box(ref_bgr: np.ndarray, frac: float = 0.2) -> tuple[int, int, int, int]:
    """Box (x, y, w, h) with the highest edge density, frac of the width, frame aspect."""
    h, w = ref_bgr.shape[:2]
    bw = int(w * frac) & ~7
    bh = int(bw * h / w) & ~7
    g = cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    e = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    integ = cv2.integral(e)
    best, bx, by = -1.0, 0, 0
    for y in range(0, h - bh + 1, max(8, bh // 4)):
        for x in range(0, w - bw + 1, max(8, bw // 4)):
            s = integ[y + bh, x + bw] - integ[y, x + bw] - integ[y + bh, x] + integ[y, x]
            if s > best:
                best, bx, by = s, x, y
    return bx, by, bw, bh


def _label(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 20), (0, 0, 0), -1)
    cv2.putText(out, text, (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def _fit(img: np.ndarray, w: int, h: int, nearest: bool = False) -> np.ndarray:
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_AREA)


def contact_sheet(*, stage_dir: Path, frame_index: int, lr_path: Path, ref_size: tuple[int, int], title: str, out_path: Path) -> dict:
    ref = cv2.imread(str(stage_dir / f"f{frame_index:05d}_0_reference.png"))
    s1 = cv2.imread(str(stage_dir / f"f{frame_index:05d}_1_stage1.png"))
    s2 = cv2.imread(str(stage_dir / f"f{frame_index:05d}_2_stage2.png"))
    final = decode_frame(lr_path, frame_index)
    up = decode_frame(lr_path, frame_index, scale_to=ref_size)
    imgs = [ref, s1, s2, final, up]
    rw, rh = ref_size
    ph = int(PANEL_W * rh / rw)
    row1 = [_label(_fit(im, PANEL_W, ph), lab) for im, lab in zip(imgs, LABELS)]
    x, y, bw, bh = detail_box(ref)
    crops = []
    for im, lab in zip(imgs, LABELS):
        sx = im.shape[1] / rw
        sy = im.shape[0] / rh
        c = im[int(y * sy): int((y + bh) * sy), int(x * sx): int((x + bw) * sx)]
        crops.append(_label(_fit(c, PANEL_W, ph, nearest=True), lab.split(" ", 1)[1] + " (detail)"))
    sheet = np.vstack([np.hstack(row1), np.hstack(crops)])
    head = np.zeros((28, sheet.shape[1], 3), np.uint8)
    cv2.putText(head, title, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    sheet = np.vstack([head, sheet])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {"detail_box": [x, y, bw, bh], "path": str(out_path)}
