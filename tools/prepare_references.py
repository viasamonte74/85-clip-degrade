#!/usr/bin/env python3
"""Turn every downloaded / rendered clip of a plan into a verified 1080p FFV1 reference.

Writes data/references/<clip_id>.mkv and upserts metadata/references.jsonl and
metadata/sources.jsonl (provenance + licence + group). Screen clips are rendered straight
into their reference here. Clips with ``trim_to_longest_shot`` are cut to the longest
cut-free run of the downloaded frames (minimum 48 frames = 2 s at 24 fps).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from sn85ds import REFERENCE_VERSION  # noqa: E402
from sn85ds.acquisition.references import write_reference  # noqa: E402
from sn85ds.media import fps_str, probe  # noqa: E402
from sn85ds.util import DATA, METADATA, read_jsonl, sha256_file, upsert_jsonl, utc_now  # noqa: E402
from sn85ds.validation.shots import detect_cuts, shots, thumbnails  # noqa: E402

MIN_SHOT_FRAMES = 48
DROPPABLE = ("frames_http", "zip_j2k", "y4m_range", "ftp_mov_j2k", "commons_window", "blender")
# blender: PNG frames are dropped too (shared disk); the render manifest keeps per-frame sha256, the exact
# arguments and the scene script's sha256, and the FFV1 reference is the immutable artefact (as for screen clips)


def drop_master(base: Path) -> int:
    """Delete downloaded master media under data/downloads/<id>/ but keep manifest.json."""
    freed = 0
    for p in sorted(base.rglob("*"), reverse=True):
        if p.is_file() and p.name != "manifest.json":
            freed += p.stat().st_size
            p.unlink()
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return freed


def master_input(clip: dict, base: Path) -> tuple[list[str], bool, int, int]:
    """ffmpeg input args, whether the master is RGB, and the master's width/height."""
    fps = fps_str(clip["fps"])
    if clip["kind"] == "commons_window":
        f = next(p for p in base.iterdir() if p.name.startswith("source."))
        info = probe(f, count_frames=False)
        if fps_str(info.fps) != fps:
            raise SystemExit(f"{clip['id']}: stream rate {info.fps} != plan {fps}")
        return ["-i", str(f)], False, info.width, info.height
    if clip["kind"] == "y4m_range":
        f = base / "clip.y4m"
        info = probe(f, count_frames=False)
        hdr_rate = fps_str(info.fps)
        if hdr_rate != fps:
            raise SystemExit(f"{clip['id']}: y4m header rate {hdr_rate} != plan {fps}")
        return ["-i", str(f)], False, info.width, info.height
    frames = sorted((base / "frames").iterdir())
    frames = [p for p in frames if p.suffix.lower() in (".png", ".tif", ".tiff", ".j2k", ".jp2")]
    first = frames[0].name
    m = re.match(r"^(.*?)(\d+)(\.\w+)$", first)
    prefix, digits, ext = m.group(1), m.group(2), m.group(3)
    pattern = str(base / "frames" / f"{prefix}%0{len(digits)}d{ext}")
    info = probe(frames[0], count_frames=False)
    rgb = ext.lower() in (".png", ".tif", ".tiff")
    args = ["-framerate", fps, "-start_number", str(int(digits)), "-i", pattern]
    return args, rgb, info.width, info.height


def collection_info(sources_cfg: dict, coll: str) -> dict:
    if coll in sources_cfg["collections"]:
        return sources_cfg["collections"][coll]
    if coll == "own_blender_procedural":
        return {"title": "Procedural Blender render (this project)", "creator": "sn85ds project (rendered locally with Blender 4.5.9 LTS, GPL software; no third-party assets)",
                "licence": "CC0-1.0", "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "evidence": [{"url": "src/sn85ds/blender/procedural_scenes.py", "quote": "procedural geometry and materials only; original work of this project"}],
                "attribution": "none required (CC0)", "commercial_ml_training": True}
    if coll == "own_screen_render":
        return {"title": "Screen content rendered in headless Chromium (this project)", "creator": "sn85ds project",
                "licence": "CC0-1.0", "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "evidence": [{"url": "src/sn85ds/screen/", "quote": "procedurally generated text/numbers; code shown is this project's own source; fonts DejaVu (Bitstream Vera licence), Liberation (OFL 1.1), Ubuntu (Ubuntu Font Licence 1.0) — none restricts rendered output"}],
                "attribution": "none required (CC0)", "commercial_ml_training": True}
    raise KeyError(coll)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(ROOT / "config" / "pilot_clips.yaml"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--kinds", nargs="*", help="only these clip kinds (e.g. frames_http zip_j2k y4m_range blender)")
    ap.add_argument("--drop-masters", action="store_true",
                    help="disk-saving mode: after the reference's decoded planes are re-verified, delete downloaded master "
                         "files (manifest with URLs + per-file sha256 is kept, so the master can be re-fetched and the "
                         "reference rebuilt bit-exactly). Rendered masters (blender, screen) are never dropped.")
    args = ap.parse_args()
    plan = yaml.safe_load(Path(args.plan).read_text())
    sources_cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    done = {r["source_id"] for r in read_jsonl(METADATA / "references.jsonl")}
    for clip in plan["clips"]:
        cid = clip["id"]
        if (args.only and cid not in args.only) or (args.kinds and clip["kind"] not in args.kinds):
            continue
        out = DATA / "references" / f"{cid}.mkv"
        if cid in done and out.exists() and not args.force:
            print("skip", cid)
            continue
        base = DATA / "downloads" / cid
        t0 = time.time()
        coll = collection_info(sources_cfg, clip["collection"])
        if clip["kind"] == "commons_window":  # asset-level licence of this one file (Commons file page metadata)
            coll = {**coll, "title": f"{clip['title']} (Wikimedia Commons)", "creator": clip.get("artist") or "see file page",
                    "licence": clip["licence"], "licence_url": clip.get("licence_url") or coll.get("licence_url"),
                    "evidence": [{"url": clip["commons_page"], "quote": f"Licensing: {clip['licence_short']} (file page metadata, LicenseShortName); "
                                  f"author: {clip.get('artist') or 'n/a'}; SHA-1 {clip['sha1']}"}],
                    "attribution": f"'{clip['title'][5:]}' by {clip.get('artist') or 'unknown'}, {clip['licence_short']}, via Wikimedia Commons ({clip['commons_page']})",
                    "share_alike": "derived clips that are distributed must keep the same licence" if "SA" in clip["licence"] else None}
        provenance: dict = {}
        if clip["kind"] == "screen":
            from sn85ds.screen.render import render_scene
            from sn85ds.screen.scenes import BUILDERS
            scene = BUILDERS[clip["scene"]](clip["seed"], clip["width"], clip["height"])
            res = render_scene(scene, clip["fps"], clip["frames"], out)
            info = probe(out)
            ref = {"frames": res["frames"], "width": info.width, "height": info.height, "fps": fps_str(clip["fps"]),
                   "duration_s": round(float(Fraction(res["frames"]) / Fraction(fps_str(clip["fps"]))), 4),
                   "planes_sha256": res["planes_sha256"], "transform": {"steps": [{"op": "native_render", "viewport": res["viewport"], "device_scale": res["device_scale"]}], "aspect_error": 0.0},
                   "colour_path": "rgb->bt709 (sn85ds.colour)", "renderer": {"chromium": res["chromium"], "args": res["chromium_args"]},
                   "scene": {"subcategory": scene.subcategory, "variant": scene.variant, "params": scene.params}}
            from sn85ds.media import Yuv420Reader
            import numpy as np
            lm, fz, prev = [], 0, None
            for y, _, _ in Yuv420Reader(out):
                s = y[::8, ::8].astype(np.float32)
                lm.append(float(((s - 16) / 219).clip(0, 1).mean()))
                if prev is not None and float(np.abs(s - prev).mean()) < 0.05:
                    fz += 1
                prev = s
            ref.update({"mean_luma": round(float(np.mean(lm)), 4), "black_frames": int(sum(v < 0.02 for v in lm)), "frozen_frame_pairs": fz})
            provenance = {"master": "rendered directly (deterministic: scene seed + HTML + Chromium version)", "screenshots_sha256": res["screenshots_sha256"]}
        else:
            man = base / "manifest.json"
            if not man.exists():
                print("missing master for", cid, "(download / render first)")
                continue
            manifest = json.loads(man.read_text())
            input_args, rgb, w, h = master_input(clip, base)
            frames, offset, trim = clip.get("use_frames", clip["frames"]), 0, None
            yuv_fix = None
            if clip["kind"] == "commons_window":
                offset = int(clip["first"])  # window chosen by tools/commons_select.py (decoded frame index)
                cs, cr = (clip.get("master_colour") or ["unknown", "unknown"])[:2]
                yuv_fix = {"in_range": "pc" if cr == "pc" else "tv", "in_matrix": "bt601" if cs in ("bt470bg", "smpte170m") else "bt709",
                           "assumed": [x for x, v in (("range", cr), ("matrix", cs)) if v in ("unknown", None)]}
            if clip.get("trim_to_longest_shot"):
                # input_args = [..., "-i", <master>]: thumbnails take the master and the options before "-i"
                th = thumbnails(input_args[-1], extra_input_args=input_args[:-2])
                runs = shots(len(th), detect_cuts(th))
                a, b = max(runs, key=lambda r: r[1] - r[0])
                if b - a < MIN_SHOT_FRAMES:
                    print(f"{cid}: longest shot {b - a} frames < {MIN_SHOT_FRAMES}; rejected")
                    continue
                offset, frames, trim = a, b - a, {"runs": runs, "chosen": [a, b]}
            ref = write_reference(input_args=input_args, rgb_master=rgb, src_w=w, src_h=h, fps=clip["fps"], frames=frames,
                                  orientation=clip["orientation"], out_path=out, source_crop=clip.get("source_crop"), frame_offset=offset,
                                  yuv_fix=yuv_fix)
            if trim:
                ref["shot_trim"] = trim
            # download manifests list "files"; Blender render manifests list "frame_sha256"
            mfiles = manifest.get("files") or [{"name": k, "sha256": v} for k, v in sorted(manifest.get("frame_sha256", {}).items())]
            mbytes = manifest.get("bytes") or sum((base / "frames" / f["name"]).stat().st_size for f in mfiles)
            provenance = {"master_files": len(mfiles), "master_bytes": mbytes, "master_manifest": str(man.relative_to(ROOT)),
                          "master_files_sha256_digest": hashlib.sha256("".join(f["sha256"] for f in mfiles).encode()).hexdigest(),
                          "publisher_checksums": manifest.get("publisher_checksums"), "master_size": [w, h], "master_rgb": rgb,
                          "download_urls_sample": manifest.get("urls", [])[:2] + (["..."] if len(manifest.get("urls", [])) > 2 else [])}
            if clip["kind"] == "blender":
                provenance["renderer"] = {k: manifest[k] for k in ("blender", "args", "seconds")}
            for k in ("master_rate", "temporal_step", "master_samples_total", "source_frames_total", "y4m_header", "commons"):
                if k in manifest:
                    provenance[k] = manifest[k]
            if int(manifest.get("temporal_step", 1)) > 1:
                ref["transform"]["steps"].insert(0, {"op": "temporal_decimation", "from_fps": manifest["master_rate"],
                                                     "to_fps": fps_str(clip["fps"]), "keep": f"one of every {manifest['temporal_step']} source frames (source frames first, first+{manifest['temporal_step']}, ...)",
                                                     "interpolation": "none", "source_samples": [manifest["source_samples"][0], manifest["source_samples"][-1]]})
        if args.drop_masters and clip["kind"] in DROPPABLE:
            from sn85ds.media import decoded_checksum
            dec, nfr = decoded_checksum(out)
            if dec != ref["planes_sha256"] or nfr != ref["frames"]:
                raise SystemExit(f"{cid}: reference re-verification failed; master kept")
            freed = drop_master(base)
            if clip["kind"] == "commons_window":  # the selection step's cached copy (hard link of the same file)
                for c in (DATA / "work" / "commons" / "files").glob(cid.split("_")[2].rstrip("p") + ".*"):
                    c.unlink()
            provenance["master_on_disk"] = False
            provenance["master_dropped"] = {"at": utc_now(), "bytes_freed": freed, "reverified_planes_sha256": True}
        th = thumbnails(out)
        cuts = detect_cuts(th)
        ref_row = {
            "source_id": cid, "reference_path": str(out.relative_to(ROOT)), "reference_sha256": sha256_file(out),
            "reference_version": REFERENCE_VERSION, "category": clip["category"], "subcategory": clip["subcategory"],
            "orientation": clip["orientation"], "group_id": clip["group"], "cuts_detected": cuts, "prepared_at": utc_now(),
            "seconds": round(time.time() - t0, 1), "container": "matroska", "codec": "ffv1", "pix_fmt": "yuv420p",
            "color": "bt709/bt709/bt709 limited, chroma left", **ref,
        }
        upsert_jsonl(METADATA / "references.jsonl", ref_row, "source_id")
        src_row = {
            "source_id": cid, "title": coll["title"] + (f" — {clip.get('scene', '')}" if clip.get("scene") else ""),
            "collection": clip["collection"], "category": clip["category"], "subcategory": clip["subcategory"],
            "group_id": clip["group"], "parent_id": clip["group"], "creator": coll["creator"], "licence": coll["licence"],
            "licence_url": coll["licence_url"], "licence_evidence": coll.get("evidence", []),
            "contradiction_note": coll.get("contradiction_note"), "attribution": coll.get("attribution"),
            "share_alike": coll.get("share_alike"), "commercial_ml_training": bool(coll.get("commercial_ml_training")),
            "privacy_flag": bool(clip.get("privacy_flag", False)), "kind": clip["kind"], "plan": clip,
            "provenance": provenance, "download_status": "complete", "verification_status": "reference written",
        }
        upsert_jsonl(METADATA / "sources.jsonl", src_row, "source_id")
        print(cid, ref_row["frames"], "frames", ref_row["fps"], f"{ref_row['width']}x{ref_row['height']}", "cuts", cuts,
              "mean_luma", ref_row["mean_luma"], ref_row["seconds"], "s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
