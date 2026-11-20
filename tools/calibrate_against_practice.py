#!/usr/bin/env python3
"""Compare locally generated degradations with the CC0 practice-pack-006 inputs.

Only the CC0 items p02-p08 are used (p01, p09 and p10 are evaluation-only and are never
downloaded or read). For each item, K recipes are drawn from the current config with the
item's own upscale factor, applied to the item's reference (optionally truncated to the
first N frames), and measured with the same statistics as the official input.

Output: reports/data/calibration_<tag>.json and a markdown table on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from sn85ds.degradation.pipeline import degrade_many  # noqa: E402
from sn85ds.degradation.recipe import load_config, sample_recipe  # noqa: E402
from sn85ds.media import Yuv420Reader, probe  # noqa: E402
from sn85ds.util import DATA, REPORTS, stable_seed  # noqa: E402
from sn85ds.validation.degradation_stats import clip_stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_practice_gate import lowres_psnr  # noqa: E402

CC0_ITEMS = ["p02", "p03", "p04", "p05", "p06", "p07", "p08"]
METRICS = ["lowres_psnr_db", "bitrate_kbps", "luma_psnr_vs_area_down", "hf_energy_ratio", "gradient_ratio",
           "effective_blur_sigma_lr_px", "noise_sigma_lr", "temporal_residual_std", "blockiness"]


def mean_luma(path: str, frames: int = 8) -> float:
    vals = []
    for k, (y, _, _) in enumerate(Yuv420Reader(path)):
        if k >= frames:
            break
        vals.append(float(((y.astype(np.float32) - 16) / 219).clip(0, 1).mean()))
    return float(np.mean(vals))


def run_item(item: str, args_variants: int, max_frames: int, tag: str, config_path: str | None, seed_tag: str) -> list[dict]:
    cfg, digest = load_config(config_path)
    work = DATA / "work" / f"calibration_{tag}"
    d = DATA / "practice" / item
    ref = str(d / "reference.mkv")
    factor = json.loads((d / "task.json").read_text())["upscale_factor"]
    info = probe(ref)
    ml = mean_luma(ref)
    jobs = []
    for k in range(args_variants):
        seed = stable_seed("calibration", seed_tag, item, k)
        r = sample_recipe(reference_size=(info.width, info.height), fps=info.fps, factor=factor, seed=seed,
                          mean_luma=ml, config=cfg, config_digest=digest)
        jobs.append((r, work / f"{item}_{k}.mp4"))
    ref_cut = ref
    if max_frames:
        # measure against the same truncated reference
        ref_cut = str(work / f"{item}_ref{max_frames}.mkv")
        if not Path(ref_cut).exists():
            import subprocess
            Path(ref_cut).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", ref, "-frames:v", str(max_frames), "-c:v", "ffv1",
                            "-level", "3", "-g", "1", ref_cut], check=True)
    res = degrade_many(ref, jobs, max_frames=max_frames)
    gate = lowres_psnr(Path(ref_cut), [Path(out) for _, out in jobs])
    rows = []
    for (r, out), rr, g in zip(jobs, res, gate):
        s = clip_stats(out, ref_cut)
        rows.append({"item": item, "factor": factor, "difficulty": r.difficulty, "codec": r.encode.codec,
                     "target_kbps": r.encode.bitrate_kbps, "blur1": r.blur1.kind, "blur1_sigma": round(r.blur1.sigma_x, 2),
                     "blur2_sigma": round(r.blur2.sigma_x, 2),
                     "noise1": round(r.noise1.level, 2) if r.noise1.enabled else 0.0, "jpeg": r.jpeg.quality if r.jpeg.enabled else None,
                     "m": r.intermediate_scale, "resize1": r.resize1, "resize2": r.resize2, "seconds_pass": rr["seconds_total_pass"],
                     "lowres_psnr_db": g["lowres_psnr_db"], **s})
        print(item, r.difficulty, {k: rows[-1][k] for k in METRICS}, flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", type=int, default=4)
    ap.add_argument("--max-frames", type=int, default=48)
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--config", default=None)
    ap.add_argument("--items", nargs="*", default=CC0_ITEMS)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--seed-tag", default=None, help="draw seeds under this tag (default --tag): the same seeds for several configs give a paired comparison")
    args = ap.parse_args()
    cfg, digest = load_config(args.config)
    practice = json.loads((REPORTS / "data" / "practice_cc0_stats.json").read_text())
    for i in CC0_ITEMS:  # the scorer's own number, published per item
        practice[i]["lowres_psnr_db"] = json.loads((DATA / "practice" / i / "meta.json").read_text())[
            "reference_scores"]["reference_itself"]["lowres_psnr_db"]
    out_rows: list[dict] = []
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for rows in ex.map(run_item, args.items, [args.variants] * len(args.items), [args.max_frames] * len(args.items),
                           [args.tag] * len(args.items), [args.config] * len(args.items),
                           [args.seed_tag or args.tag] * len(args.items)):
            out_rows += rows
    (REPORTS / "data").mkdir(parents=True, exist_ok=True)
    (REPORTS / "data" / f"calibration_{args.tag}.json").write_text(json.dumps({"config_digest": digest, "config": args.config,
                                                                             "rows": out_rows}, indent=1))

    def summ(vals):
        v = np.array([x for x in vals if x is not None], float)
        return f"{np.median(v):.2f} [{v.min():.2f}, {v.max():.2f}]" if len(v) else "-"
    print("\n| factor | metric | practice CC0 median [min, max] | local median [min, max] |\n|---|---|---|---|")
    for f in (2, 4):
        for m in METRICS:
            pv = [practice[i][m] for i in args.items if practice[i]["factor"] == f]
            lv = [r[m] for r in out_rows if r["factor"] == f]
            print(f"| x{f} | {m} | {summ(pv)} | {summ(lv)} |")
    # same content: where does each practice input fall inside the local distribution for that item?
    print("\nPercentile of the practice input among the local variants of the same reference (50 % = typical):")
    print("| item | " + " | ".join(METRICS) + " |\n|---|" + "---|" * len(METRICS))
    ranks = {m: [] for m in METRICS}
    for i in args.items:
        rows = [r for r in out_rows if r["item"] == i]
        cells = []
        for m in METRICS:
            a = np.array([r[m] for r in rows if r[m] is not None], float)
            q = float(np.mean(a < practice[i][m]) + 0.5 * np.mean(a == practice[i][m])) if len(a) else float("nan")
            ranks[m].append(q)
            cells.append(f"{practice[i][m]:.2f} / {np.median(a):.2f} ({q:.0%})")
        print(f"| {i} | " + " | ".join(cells) + " |")
    print("| mean rank | " + " | ".join(f"{np.mean(ranks[m]):.0%}" for m in METRICS) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
