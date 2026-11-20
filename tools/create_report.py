#!/usr/bin/env python3
"""Reports: contact sheets, dataset summary, degradation-vs-practice analysis, licence audit,
source inventory. Reads metadata/*.jsonl, reports/validation.json and the CC0 practice stats.
Also writes a human-readable CSV summary of every variant (metadata/variants_summary.csv).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from sn85ds.report.contact import contact_sheet  # noqa: E402
from sn85ds.util import DATA, METADATA, REPORTS, read_jsonl  # noqa: E402

STAT_KEYS = ["bitrate_kbps", "luma_psnr_vs_area_down", "hf_energy_ratio", "gradient_ratio", "effective_blur_sigma_lr_px",
             "noise_sigma_lr", "temporal_residual_std", "blockiness"]


def _du(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and f.stat().st_nlink >= 1) if p.exists() else 0


def _dur_bucket(d: float) -> str:
    return "<=5 s (~4 s)" if d <= 5 else ("5-9 s (6-8 s)" if d < 9 else "9-10 s (~10 s)")


def summ(vals) -> str:
    v = np.array([x for x in vals if x is not None], float)
    return f"{np.median(v):.2f} [{v.min():.2f}, {v.max():.2f}]" if len(v) else "-"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--tag", default="pilot")
    args = ap.parse_args()
    sources = read_jsonl(METADATA / "sources.jsonl")
    refs = read_jsonl(METADATA / "references.jsonl")
    variants = read_jsonl(METADATA / "variants.jsonl")
    refmap = {r["source_id"]: r for r in refs}
    val = json.loads((REPORTS / "validation.json").read_text()) if (REPORTS / "validation.json").exists() else None
    practice = json.loads((REPORTS / "data" / "practice_cc0_stats.json").read_text())
    sheets = []
    if not args.no_sheets:
        for v in variants:
            ref = refmap[v["source_id"]]
            out = REPORTS / "contact_sheets" / f"{v['input_id']}.jpg"
            if not out.exists():
                contact_sheet(stage_dir=ROOT / v["contact_frames_dir"], frame_index=v["contact_frame_index"], lr_path=ROOT / v["output_path"],
                              ref_size=(ref["width"], ref["height"]),
                              title=f"{v['input_id']} | {v['difficulty']} | x{v['upscale_factor']} | {v['codec']} {v['bitrate_kbps_target']} kbps | " +
                                    (f"blur1 directional {v['blur1']['length_px']:.1f}px" if v['blur1']['kind'] == 'directional' else f"blur1 {v['blur1']['kind']} sigma {v['blur1']['sigma_x']:.2f}") +
                                    f" | m {v['intermediate_scale']} {v['resize1']}->{v['resize2']} | "
                                    f"noise1 {v['noise1']['level']:.2f} | jpeg {v['jpeg']['quality'] if v['jpeg']['enabled'] else '-'}",
                              out_path=out)
            sheets.append(out)
    # ---------------------------------------------------------------- CSV summary
    rows = []
    for v in variants:
        s = v["stats"]
        rows.append({"input_id": v["input_id"], "source_id": v["source_id"], "split": v["split"], "category": v["category"],
                     "subcategory": v["subcategory"], "factor": v["upscale_factor"], "orientation": v["orientation"],
                     "difficulty": v["difficulty"], "codec": v["codec"], "target_kbps": v["bitrate_kbps_target"],
                     "actual_kbps": s["bitrate_kbps"], "fps": v["probe"]["fps"], "frames": v["probe"]["frames"],
                     "blur1": v["blur1"]["kind"], "blur1_sigma": round(v["blur1"]["sigma_x"], 3), "intermediate": "x".join(map(str, v["intermediate_size"])),
                     "resize1": v["resize1"], "noise1_level": round(v["noise1"]["level"], 3) if v["noise1"]["enabled"] else 0,
                     "jpeg_q": v["jpeg"]["quality"] if v["jpeg"]["enabled"] else "", "blur2_sigma": round(v["blur2"]["sigma_x"], 3),
                     "resize2": v["resize2"], "noise2_level": round(v["noise2"]["level"], 3) if v["noise2"]["enabled"] else 0,
                     "psnr_vs_area_down": s["luma_psnr_vs_area_down"], "eff_blur_lr_px": s["effective_blur_sigma_lr_px"],
                     "hf_ratio": s["hf_energy_ratio"], "seed": v["seed"], "output_sha256": v["output_sha256"], "output_path": v["output_path"]})
    df = pd.DataFrame(rows)
    df.to_csv(METADATA / "variants_summary.csv", index=False)
    rdf = pd.DataFrame([{"source_id": r["source_id"], "category": r["category"], "subcategory": r["subcategory"], "split": r.get("split"),
                         "group": r["group_id"], "orientation": r["orientation"], "fps": r["fps"], "frames": r["frames"],
                         "duration_s": r["duration_s"], "mean_luma": r["mean_luma"], "cuts": len(r.get("cuts_detected") or [])} for r in refs])
    rdf.to_csv(METADATA / "references_summary.csv", index=False)

    # ---------------------------------------------------------------- dataset summary
    storage = {k: _du(DATA / k) for k in ("downloads", "references", "degraded")}
    ref_bytes = sum((ROOT / r["reference_path"]).stat().st_size for r in refs)
    lines = [f"# Dataset summary ({args.tag})", ""]
    lines += [f"References: **{len(refs)}** originals from **{rdf['group'].nunique()}** independent source groups; degraded inputs: **{len(variants)}** "
              f"(x2: {int((df.factor == 2).sum()) if len(df) else 0}, x4: {int((df.factor == 4).sum()) if len(df) else 0}).", ""]
    if len(rdf):
        cat = rdf.groupby("category").agg(clips=("source_id", "count"), groups=("group", "nunique")).reset_index()
        cat["share"] = (cat["clips"] / cat["clips"].sum() * 100).round(1).astype(str) + " %"
        lines += ["## By category", "", md_table(cat), ""]
        lines += ["## By subcategory", "", md_table(rdf.groupby(["category", "subcategory"]).size().reset_index(name="clips")), ""]
        sp = rdf.pivot_table(index="category", columns="split", values="source_id", aggfunc="count", fill_value=0).reset_index()
        lines += ["## Splits (group-aware)", "", md_table(sp), ""]
        lines += ["## Orientation, frame rate, duration", "", md_table(rdf.groupby("orientation").size().reset_index(name="clips")), "",
                  md_table(rdf.groupby("fps").size().reset_index(name="clips")), "",
                  md_table(rdf.assign(bucket=rdf["duration_s"].map(_dur_bucket)).groupby("bucket").size().reset_index(name="clips")), ""]
    if len(df):
        lines += ["## Degradation difficulty and codecs", "", md_table(df.groupby(["factor", "difficulty"]).size().reset_index(name="variants")), "",
                  md_table(df.groupby(["factor", "codec"]).size().reset_index(name="variants")), "",
                  md_table(pd.concat([df.groupby("resize1").size().rename("resize1"), df.groupby("resize2").size().rename("resize2")], axis=1).fillna(0).astype(int).reset_index().rename(columns={"index": "filter"})), ""]
        tp = [v["pass_seconds"] / 4 for v in variants]
        lines += ["## Storage and throughput", "",
                  f"- downloads (masters): {storage['downloads'] / 1e9:.2f} GB; references (FFV1): {ref_bytes / 1e9:.2f} GB; degraded inputs: {storage['degraded'] / 1e9:.3f} GB",
                  f"- degradation: median {np.median(tp):.1f} s per variant (4 variants per decode pass, nice 19 on a CPU quota shared with other jobs)",
                  f"- reference preparation: median {np.median([r['seconds'] for r in refs]):.1f} s per reference", ""]
    if val:
        lines += ["## Validation", "", "```", json.dumps(val["summary"], indent=1), "```",
                  f"Split leaks: {len(val['split_leaks'])}; near-duplicate pairs (dHash <= 8 bits): {len(val['near_duplicates'])} "
                  f"(cross-split: {sum(1 for n in val['near_duplicates'] if n['cross_split'])}).", ""]
    (REPORTS / "dataset_summary.md").write_text("\n".join(lines))

    # ---------------------------------------------------------------- degradation analysis vs practice
    a = ["# Degradation analysis: local variants vs CC0 practice-pack-006 inputs", "",
         "Same statistics code for both (sn85ds/validation/degradation_stats.py). Practice items used: p02-p08 only "
         "(CC0); p01/p09/p10 are evaluation-only and were never downloaded. These numbers describe the degradation "
         "distribution; they are not the competition scorer.", "",
         "| factor | metric | practice CC0 median [min, max] | local median [min, max] |", "|---|---|---|---|"]
    for f in (2, 4):
        for m in STAT_KEYS:
            pv = [practice[i][m] for i in practice if practice[i]["factor"] == f]
            lv = [v["stats"][m] for v in variants if v["upscale_factor"] == f]
            a.append(f"| x{f} | {m} | {summ(pv)} | {summ(lv)} |")
    a += ["", "By category (local, median PSNR vs area-downscaled reference / effective blur LR px / HF-energy ratio):", ""]
    if len(df):
        g = df.groupby(["factor", "category"]).agg(psnr=("psnr_vs_area_down", "median"), blur=("eff_blur_lr_px", "median"),
                                                   hf=("hf_ratio", "median"), n=("input_id", "count")).round(3).reset_index()
        a += [md_table(g), ""]
    for tag in ("v1_1", "v1_2"):
        p = REPORTS / "data" / f"calibration_{tag}.json"
        if p.exists():
            a.append(f"- calibration run `{tag}`: {len(json.loads(p.read_text())['rows'])} variants of CC0 references (reports/data/calibration_{tag}.json)")
    notes = REPORTS / "notes" / "degradation_interpretation.md"  # hand-written analysis survives regeneration
    if notes.exists():
        a += ["", notes.read_text()]
    (REPORTS / "degradation_analysis.md").write_text("\n".join(a) + "\n")

    # ---------------------------------------------------------------- licence audit + inventory
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    L = ["# Licence audit", "", "Asset-level evidence for every reference. Quotes were read from the URLs during collection.", "",
         "| source_id | licence | commercial ML training | evidence | flags |", "|---|---|---|---|---|"]
    for s in sorted(sources, key=lambda s: s["source_id"]):
        ev = "; ".join(e["url"] for e in s.get("licence_evidence", []))
        flags = ", ".join(f for f, on in (("privacy review", s.get("privacy_flag")), ("mirror contradiction (BY-NC-ND on Xiph copies)", s.get("contradiction_note")),
                                           ("share-alike", s.get("licence") == "CC-BY-SA-4.0")) if on)
        L.append(f"| {s['source_id']} | {s['licence']} | {'yes' if s['commercial_ml_training'] else 'NO'} | {ev} | {flags} |")
    L += ["", "## Rejected or deferred sources", "", "| what | why | evidence |", "|---|---|---|"]
    for r in cfg.get("rejected", []):
        L.append(f"| {r['what']} | {r['why']} | {r['evidence']} |")
    L += ["", "## Attribution (required for CC BY / BY-SA material)", ""]
    for k, c in cfg["collections"].items():
        L.append(f"- **{c['title']}** — {c['attribution']} ({c['licence_url']})")
    (REPORTS / "license_audit.md").write_text("\n".join(L) + "\n")
    inv = ["# Source inventory", "", "| collection | category | licence | access | master |", "|---|---|---|---|---|"]
    for k, c in cfg["collections"].items():
        inv.append(f"| {k} | {c['category']} | {c['licence']} | {c['access']} | {c['master']} |")
    inv += ["| own_blender_procedural | 3d_rendered | CC0-1.0 (own work) | rendered locally, Blender 4.5.9 LTS | PNG 8-bit sRGB, procedural scenes |",
            "| own_screen_render | screen | CC0-1.0 (own work) | rendered locally, headless Chromium | PNG screenshots, native 1080p |", "",
            "## Clips", "", md_table(rdf) if len(rdf) else "(none)"]
    (REPORTS / "source_inventory.md").write_text("\n".join(inv) + "\n")
    idx = ["# Contact sheets", "", "Columns: original / stage 1 / stage 2 / final LR / LR Lanczos-upscaled; second row: detail crop at the most edge-dense region (nearest-neighbour magnified).", ""]
    idx += [f"- [{p.stem}]({p.name})" for p in sorted((REPORTS / "contact_sheets").glob("*.jpg"))]
    (REPORTS / "contact_sheets" / "README.md").write_text("\n".join(idx) + "\n")
    print("reports written:", len(sheets), "contact sheets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
