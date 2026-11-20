#!/usr/bin/env python3
"""Generate the degraded low-resolution inputs for every split reference.

Per reference: ``--variants-per-factor`` independent recipes for x2 and for x4 (default 2 + 2),
drawn from stable seeds (source id, factor, index, config version) and applied in one decode
pass. Outputs: data/degraded/<split>/x<f>/<variant_id>.mp4 and metadata/variants.jsonl (the
full recipe, the exact encoder command, checksums, probe results and degradation stats).
Resumable; bounded worker processes; every heavy step runs at nice 19.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sn85ds import PIPELINE_VERSION  # noqa: E402
from sn85ds.degradation.pipeline import degrade_many  # noqa: E402
from sn85ds.degradation.recipe import load_config, sample_recipe  # noqa: E402
from sn85ds.media import keyframe_indices, probe  # noqa: E402
from sn85ds.util import DATA, METADATA, REPORTS, read_jsonl, sha256_file, stable_seed, upsert_jsonl, utc_now  # noqa: E402
from sn85ds.validation.degradation_stats import clip_stats  # noqa: E402


def plan_variants(ref: dict, cfg: dict, digest: str, per_factor: int) -> list[tuple[str, object, Path]]:
    out = []
    for factor in (2, 4):
        for idx in range(per_factor):
            vid = f"{ref['source_id']}__x{factor}_v{idx}"
            seed = stable_seed("variant", ref["source_id"], factor, idx, cfg["version"])
            r = sample_recipe(reference_size=(ref["width"], ref["height"]), fps=ref["fps"], factor=factor, seed=seed,
                              mean_luma=ref["mean_luma"], config=cfg, config_digest=digest)
            out.append((vid, r, DATA / "degraded" / ref["split"] / f"x{factor}" / f"{vid}.mp4"))
    return out


def process_reference(ref: dict, per_factor: int, only_vids: set[str] | None = None) -> list[dict]:
    cfg, digest = load_config()
    jobs = [j for j in plan_variants(ref, cfg, digest, per_factor) if only_vids is None or j[0] in only_vids]
    ref_path = ROOT / ref["split_path"]
    mid = ref["frames"] // 2
    cap_dirs = [REPORTS / "contact_sheets" / "frames" / vid for vid, _, _ in jobs]
    t0 = time.time()
    results = degrade_many(ref_path, [(r, p) for _, r, p in jobs], capture_frames=(mid,), capture_dirs=cap_dirs)
    rows = []
    for (vid, r, path), res, cdir in zip(jobs, results, cap_dirs):
        info = probe(path)
        stats = clip_stats(path, ref_path)
        rows.append({
            "input_id": vid, "source_id": ref["source_id"], "split": ref["split"], "category": ref["category"],
            "subcategory": ref["subcategory"], "group_id": ref["group_id"], "reference_path": ref["split_path"],
            "reference_sha256": ref["reference_sha256"], "reference_planes_sha256": ref["planes_sha256"],
            "upscale_factor": r.upscale_factor, "orientation": r.orientation, "difficulty": r.difficulty,
            "lr_size": list(r.lr_size), "intermediate_size": list(r.intermediate_size), "intermediate_scale": r.intermediate_scale,
            "blur1": r.blur1.model_dump(), "resize1": r.resize1, "noise1": r.noise1.model_dump(), "jpeg": r.jpeg.model_dump(),
            "blur2": r.blur2.model_dump(), "resize2": r.resize2, "noise2": r.noise2.model_dump(),
            "codec": r.encode.codec, "encoder": r.encode.encoder, "bitrate_kbps_target": r.encode.bitrate_kbps,
            "gop_frames": r.encode.gop_frames, "preset": r.encode.preset, "pix_fmt": r.encode.pix_fmt,
            "color": "bt709 matrix/primaries/transfer, limited range, chroma left",
            "recipe": r.model_dump(), "seed": r.seed, "pipeline_version": PIPELINE_VERSION, "config_digest": digest,
            "config_version": cfg["version"], "encode_command": res["encode_command"],
            "pre_encode_planes_sha256": res["pre_encode_planes_sha256"], "output_path": str(path.relative_to(ROOT)),
            "output_sha256": sha256_file(path), "output_bytes": info.size_bytes,
            "probe": {"codec": info.codec, "width": info.width, "height": info.height, "fps": info.fps, "frames": info.frames,
                      "pix_fmt": info.pix_fmt, "color_space": info.color_space, "color_range": info.color_range,
                      "color_primaries": info.color_primaries, "color_transfer": info.color_transfer,
                      "duration_s": info.duration_s, "keyframes": keyframe_indices(path)},
            "stats": stats, "contact_frames_dir": str(cdir.relative_to(ROOT)), "contact_frame_index": mid,
            "generated_at": utc_now(), "pass_seconds": round(time.time() - t0, 1),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants-per-factor", type=int, default=2)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg, digest = load_config()
    refs = [r for r in read_jsonl(METADATA / "references.jsonl") if r.get("split")]
    have = {v["input_id"]: v for v in read_jsonl(METADATA / "variants.jsonl")}
    todo = []
    for ref in refs:
        if args.only and ref["source_id"] not in args.only:
            continue
        jobs = plan_variants(ref, cfg, digest, args.variants_per_factor)
        missing = {vid for vid, r, _ in jobs if not (vid in have and (ROOT / have[vid]["output_path"]).exists()
                                                     and have[vid]["seed"] == r.seed and have[vid]["config_digest"] == digest)}
        if not missing:
            continue
        ref["_missing"] = missing
        todo.append(ref)
    print(f"{len(todo)} references to process ({len(refs)} split references)", flush=True)
    if args.dry_run:
        for ref in todo:
            for vid, r, p in plan_variants(ref, cfg, digest, args.variants_per_factor):
                print(vid, r.difficulty, r.encode.codec, r.encode.bitrate_kbps, "kbps", p.relative_to(ROOT))
        return 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_reference, {k: v for k, v in ref.items() if k != "_missing"}, args.variants_per_factor,
                          ref["_missing"]): ref["source_id"] for ref in todo}
        for f in as_completed(futs):
            sid = futs[f]
            try:
                rows = f.result()
            except Exception as exc:  # report and continue with the other references
                print(f"FAILED {sid}: {exc!r}", flush=True)
                continue
            for row in rows:
                upsert_jsonl(METADATA / "variants.jsonl", row, "input_id")
            print(sid, len(rows), "variants", rows[0]["pass_seconds"], "s", f"(elapsed {time.time() - t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
