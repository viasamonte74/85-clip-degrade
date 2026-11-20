#!/usr/bin/env python3
"""Prove reproducibility on a sample: regenerate variants and rebuild references into a scratch
directory and compare checksums with the stored metadata.

Variants: the recipe is re-sampled from (source id, factor, index, config version) and must equal
the stored recipe; the regenerated pre-encode planes and the encoded file must match
pre_encode_planes_sha256 and output_sha256 bit for bit.
References (disk-saving mode): the reference is rebuilt from its master (frames on disk) and its
decoded planes must match planes_sha256. Screen references are re-rendered from their seed.

Writes reports/data/reproducibility.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from sn85ds.acquisition.references import write_reference  # noqa: E402
from sn85ds.degradation.pipeline import degrade_many  # noqa: E402
from sn85ds.degradation.recipe import Recipe, load_config, sample_recipe  # noqa: E402
from sn85ds.media import decoded_checksum  # noqa: E402
from sn85ds.util import METADATA, REPORTS, read_jsonl, sha256_file, stable_seed, utc_now, write_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", type=int, default=6)
    ap.add_argument("--references", type=int, default=3)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--plans", nargs="*", default=["config/pilot_clips.yaml", "config/phase_b_clips.yaml"])
    ap.add_argument("--refetch", nargs="*", default=[],
                    help="clip ids whose downloaded master was dropped (disk-saving mode): re-download into a scratch dir "
                         "from the manifest and rebuild the reference")
    ap.add_argument("--only-variants", nargs="*", help="check these variant ids instead of a random sample")
    ap.add_argument("--out", default=str(REPORTS / "data" / "reproducibility.json"))
    args = ap.parse_args()
    cfg, digest = load_config()
    refs = {r["source_id"]: r for r in read_jsonl(METADATA / "references.jsonl")}
    variants = read_jsonl(METADATA / "variants.jsonl")
    rng = random.Random(args.seed)
    out = {"checked_at": utc_now(), "config_digest": digest, "variants": [], "references": []}
    with tempfile.TemporaryDirectory(dir=str(ROOT / "data" / "work")) as tmp:
        tmp = Path(tmp)
        sample = [v for v in variants if v["input_id"] in set(args.only_variants)] if args.only_variants else \
            rng.sample(variants, min(args.variants, len(variants)))
        for v in sample:
            ref = refs[v["source_id"]]
            idx = int(v["input_id"].rsplit("_v", 1)[1])
            seed = stable_seed("variant", ref["source_id"], v["upscale_factor"], idx, cfg["version"])
            r = sample_recipe(reference_size=(ref["width"], ref["height"]), fps=ref["fps"], factor=v["upscale_factor"], seed=seed,
                              mean_luma=ref["mean_luma"], config=cfg, config_digest=digest)
            recipe_ok = r == Recipe(**v["recipe"])
            res = degrade_many(ROOT / ref["split_path"], [(r, tmp / f"{v['input_id']}.mp4")])[0]
            row = {"input_id": v["input_id"], "recipe_equal": recipe_ok,
                   "pre_encode_planes_equal": res["pre_encode_planes_sha256"] == v["pre_encode_planes_sha256"],
                   "output_equal": sha256_file(tmp / f"{v['input_id']}.mp4") == v["output_sha256"], "codec": v["codec"]}
            out["variants"].append(row)
            print("variant", row, flush=True)
        plan = {}
        for pf in args.plans:
            plan.update({c["id"]: c for c in yaml.safe_load((ROOT / pf).read_text())["clips"]})
        on_disk = [refs[k] for k in sorted(refs) if k in plan and (plan[k]["kind"] == "screen" or any((ROOT / "data" / "downloads" / k).glob("*/*"))
                                                                    or any((ROOT / "data" / "downloads" / k).glob("clip.y4m")))]
        pick = rng.sample(on_disk, min(args.references, len(on_disk))) + [refs[k] for k in args.refetch if k in refs]
        from prepare_references import master_input  # noqa: E402
        for ref in pick:
            clip = plan[ref["source_id"]]
            dst = tmp / f"{ref['source_id']}.mkv"
            if clip["kind"] == "screen":
                from sn85ds.screen.render import render_scene
                from sn85ds.screen.scenes import BUILDERS
                res = render_scene(BUILDERS[clip["scene"]](clip["seed"], clip["width"], clip["height"]), clip["fps"], clip["frames"], dst)
                digest_planes = res["planes_sha256"]
            else:
                base = ROOT / "data" / "downloads" / ref["source_id"]
                if ref["source_id"] in args.refetch:  # master was dropped: fetch it again from the recorded source
                    import download_sources as ds
                    base = tmp / f"refetch_{ref['source_id']}"
                    if clip["kind"] == "frames_http":
                        ds.fetch_frames_http(clip, base / "frames", 6)
                    elif clip["kind"] == "zip_j2k":
                        ds.fetch_zip(clip, base / "frames", 6)
                    elif clip["kind"] == "y4m_range":
                        ds.fetch_y4m(clip, base / "clip.y4m", 6)
                    elif clip["kind"] == "ftp_mov_j2k":
                        ds.fetch_ftp_mov(clip, base / "frames", 3)
                    man_files = json.loads((ROOT / "data" / "downloads" / ref["source_id"] / "manifest.json").read_text())["files"]
                    got = sorted(sha256_file(p) for p in (base.rglob("*")) if p.is_file())
                    want = sorted(f["sha256"] for f in man_files)
                    print("refetched", ref["source_id"], "files match manifest:", got == want, flush=True)
                input_args, rgb, w, h = master_input(clip, base)
                offset = (ref.get("shot_trim") or {}).get("chosen", [0])[0]
                info = write_reference(input_args=input_args, rgb_master=rgb, src_w=w, src_h=h, fps=clip["fps"], frames=ref["frames"],
                                       orientation=clip["orientation"], out_path=dst, source_crop=clip.get("source_crop"), frame_offset=offset)
                digest_planes = info["planes_sha256"]
            decoded, n = decoded_checksum(dst)
            equal = digest_planes == ref["planes_sha256"] == decoded
            row = {"source_id": ref["source_id"], "kind": clip["kind"], "planes_equal": equal, "frames": n, "status": "exact" if equal else "mismatch"}
            if not equal:  # measure how different, frame by frame (luma)
                import numpy as np
                from sn85ds.media import Yuv420Reader
                diffs = []
                for k, ((ya, _, _), (yb, _, _)) in enumerate(zip(Yuv420Reader(ROOT / ref["reference_path"]), Yuv420Reader(dst))):
                    if not np.array_equal(ya, yb):
                        diffs.append({"frame": k, "pixels": int((ya != yb).sum()), "max_abs": int(np.abs(ya.astype(int) - yb).max())})
                row["differing_frames"] = diffs[:20]
                row["n_differing_frames"] = len(diffs)
                # rendered (screen) masters: Chromium rasterisation can differ by +-1 code value on rare frames
                if clip["kind"] == "screen" and diffs and max(d["max_abs"] for d in diffs) <= 1 and len(diffs) <= max(1, n // 100):
                    row["status"] = "near_exact_renderer"
            out["references"].append(row)
            print("reference", row, flush=True)
    write_json(Path(args.out), out)
    ok = all(v["recipe_equal"] and v["pre_encode_planes_equal"] and v["output_equal"] for v in out["variants"]) and \
        all(r["status"] != "mismatch" for r in out["references"])
    exact = ok and all(r["status"] == "exact" for r in out["references"])
    print("ALL REPRODUCED (bit-exact)" if exact else ("REPRODUCED (screen re-render within +-1 code value on rare frames)" if ok else "MISMATCH FOUND"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
