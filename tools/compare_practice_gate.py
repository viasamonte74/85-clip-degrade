#!/usr/bin/env python3
"""Degradation strength in the competition scorer's own terms: the low-resolution consistency of the
reference against its degraded input, for the CC0 practice items p02-p08 and for every local pair.

The comp-006 scorer (miner-vidaio vidaio/scoring/upscaling_generative.py, generative_frame_metrics) gates
every output on ``lowres_psnr_db``: each output frame's luma Lanczos-downscaled (cv2 INTER_LANCZOS4) to the
served input's geometry, both sides Gaussian-blurred (sigma 1.0, 7x7, BORDER_REFLECT_101), global PSNR over
all frames, minimum 28 dB. Measured with the REFERENCE as the output it says how far the degradation moved
the input from a clean downscale (lower = heavier), and the practice pack publishes that value per item
(meta.json reference_scores.reference_itself.lowres_psnr_db). Same code for both sides here; the practice
values are first recomputed from the files to check the implementation against the published numbers.

Writes reports/data/practice_gate_compare.json. Evaluation-only items p01/p09/p10 are not read.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sn85ds.util import METADATA, REPORTS, read_jsonl  # noqa: E402

PRACTICE = ROOT / "data" / "practice"
CC0_ITEMS = ("p02", "p03", "p04", "p05", "p06", "p07", "p08")
SIGMA = 1.0
KERNEL = (2 * int(math.ceil(3.0 * SIGMA)) + 1,) * 2


def dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


class Luma:
    """Decode a video to 8-bit 4:2:0 and yield luma planes (the scorer reads I420 frames)."""

    def __init__(self, path: Path):
        self.w, self.h = dims(path)
        self.p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0",
                                   "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                                  stdout=subprocess.PIPE)
        self.frame = self.w * self.h * 3 // 2

    def __iter__(self):
        while True:
            buf = self.p.stdout.read(self.frame)
            if len(buf) < self.frame:
                break
            yield np.frombuffer(buf, np.uint8, self.w * self.h).reshape(self.h, self.w)
        self.p.wait()


def blur(x: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(x, KERNEL, SIGMA, borderType=cv2.BORDER_REFLECT_101)


def lowres_psnr(reference: Path, inputs: list[Path]) -> list[dict]:
    """One reference decode, all of its inputs in lockstep."""
    ref = Luma(reference)
    ins = [Luma(p) for p in inputs]
    sq = [0.0] * len(ins)
    cnt = [0] * len(ins)
    nref = 0
    its = [iter(i) for i in ins]
    nin = [0] * len(ins)
    for rl in ref:
        nref += 1
        rf = rl.astype(np.float32)
        for k, (it, li) in enumerate(zip(its, ins)):
            il = next(it, None)
            if il is None:
                continue
            nin[k] += 1
            down = cv2.resize(rf, (li.w, li.h), interpolation=cv2.INTER_LANCZOS4)
            d = (blur(down) - blur(il.astype(np.float32))).astype(np.float64)
            sq[k] += float((d * d).sum())
            cnt[k] += d.size
    for it in its:  # drain
        for _ in it:
            pass
    out = []
    for k, p in enumerate(inputs):
        mse = sq[k] / max(1, cnt[k])
        out.append({"input": str(p.relative_to(ROOT)), "lowres_psnr_db": round(10 * math.log10(255.0 ** 2 / mse), 3) if mse > 0 else 99.0,
                    "frames_ref": nref, "frames_input": nin[k]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--practice-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N references only (testing)")
    a = ap.parse_args()
    res: dict = {"scorer_definition": "vidaio/scoring/upscaling_generative.py generative_frame_metrics lowres_psnr_db "
                                      "(Lanczos4 down to input size, Gaussian sigma 1.0 both sides, global luma PSNR)",
                 "practice": [], "local": []}
    for it in CC0_ITEMS:
        d = PRACTICE / it
        meta = json.loads((d / "meta.json").read_text())
        r = lowres_psnr(d / "reference.mkv", [d / "input.mp4"])[0]
        res["practice"].append({"item": it, "kind": meta["kind"], "factor": meta["upscale_factor"], "orientation": meta["orientation"],
                                "codec": meta["input"]["codec"], "fps": meta["input"]["fps"], "content": meta["content"],
                                "published_lowres_psnr_db": meta["reference_scores"]["reference_itself"]["lowres_psnr_db"],
                                "recomputed_lowres_psnr_db": r["lowres_psnr_db"]})
        print(it, "published", res["practice"][-1]["published_lowres_psnr_db"], "recomputed", r["lowres_psnr_db"], flush=True)
    if not a.practice_only:
        refs = {r["source_id"]: r for r in read_jsonl(METADATA / "references.jsonl")}
        by_ref: dict = {}
        for v in read_jsonl(METADATA / "variants.jsonl"):
            if (ROOT / v["output_path"]).exists():
                by_ref.setdefault(v["source_id"], []).append(v)
        t0 = time.time()
        for n, (sid, vs) in enumerate(sorted(by_ref.items())):
            if a.limit and n >= a.limit:
                break
            ref = refs[sid]
            rows = lowres_psnr(ROOT / ref["split_path"], [ROOT / v["output_path"] for v in vs])
            for v, r in zip(vs, rows):
                res["local"].append({"input_id": v["input_id"], "source_id": sid, "category": v["category"],
                                     "subcategory": v["subcategory"], "factor": v["upscale_factor"], "difficulty": v["difficulty"],
                                     "codec": v["codec"], "fps": ref["fps"], "bitrate_kbps": v["stats"].get("bitrate_kbps"),
                                     **{k: r[k] for k in ("lowres_psnr_db", "frames_ref", "frames_input")}})
            if n % 10 == 0:
                print(f"{n + 1}/{len(by_ref)} references, {len(res['local'])} pairs, {time.time() - t0:.0f} s", flush=True)
    out = REPORTS / "data" / "practice_gate_compare.json"
    out.write_text(json.dumps(res, indent=1) + "\n")
    print("wrote", out.relative_to(ROOT), len(res["local"]), "local pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
