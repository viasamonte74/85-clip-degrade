#!/usr/bin/env python3
"""Render procedural Blender clips listed in a clip plan (kind: blender) to PNG frames.

Frames land in data/downloads/<clip_id>/frames/; a manifest records the Blender version,
the exact arguments, timing and per-frame sha256. Resumable: a clip whose manifest exists
with the right frame count is skipped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from sn85ds.util import DATA, sha256_file, utc_now  # noqa: E402

BLENDER = ROOT / "third_party" / "blender-4.5.9-linux-x64" / "blender"
SCRIPT = ROOT / "src" / "sn85ds" / "blender" / "procedural_scenes.py"


VRAM_EST = {("forest", "cycles"): 3800, ("terrain", "cycles"): 3000, ("forest", "eevee"): 2600, ("terrain", "eevee"): 2200}


def blender_vram_mb() -> int:
    """VRAM currently held by Blender processes (nvidia-smi per-process usage)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return 0
    tot = 0
    for line in out.strip().splitlines():
        pid, mem = (x.strip() for x in line.split(","))
        try:
            if "blender" in Path(f"/proc/{pid}/cmdline").read_text(errors="replace"):
                tot += int(mem)
        except OSError:
            pass
    return tot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(ROOT / "config" / "pilot_clips.yaml"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--interleave", action="store_true", help="render in round-robin order over scene types")
    ap.add_argument("--shard", default="0/1", help="k/n: render every n-th clip starting at k (parallel queues on one GPU)")
    ap.add_argument("--vram-budget-mb", type=int, default=5800,
                    help="GPU shared with another job: start a clip only when all Blender processes' VRAM plus this clip's "
                         "estimate fits the budget (agreed cap ~6 GB)")
    ap.add_argument("--preview", action="store_true", help="render frames 1 and N/2 only at 50% into data/work/blender_preview/")
    args = ap.parse_args()
    plan = yaml.safe_load(Path(args.plan).read_text())
    clips = plan["clips"]
    if args.interleave:  # round-robin over (scene, subcategory) so every subcategory progresses evenly
        from itertools import zip_longest
        by: dict = {}
        for c in clips:
            if c["kind"] == "blender":
                by.setdefault((c["scene"], c.get("subcategory")), []).append(c)
        clips = [c for grp in zip_longest(*by.values()) for c in grp if c is not None]
    k_sh, n_sh = (int(x) for x in args.shard.split("/"))
    clips = [c for c in clips if c["kind"] == "blender"][k_sh::n_sh]
    for clip in clips:
        if clip["kind"] != "blender" or (args.only and clip["id"] not in args.only):
            continue
        out = DATA / "downloads" / clip["id"] / "frames"
        man = out.parent / "manifest.json"
        if args.preview:
            out = DATA / "work" / "blender_preview" / clip["id"]
            man = out / "preview.json"
        if man.exists() and json.loads(man.read_text()).get("frames") == clip["frames"]:
            print("skip", clip["id"])
            continue
        out.mkdir(parents=True, exist_ok=True)
        done_frames = sorted(out.glob("frame_*.png"))
        if done_frames and not args.preview:  # resume after an interruption: drop the newest (possibly partial) frame
            done_frames[-1].unlink()
        num, den = (clip["fps"].split("/") + ["1"])[:2]
        a = {"scene": clip["scene"], "seed": clip["seed"], "width": clip["width"], "height": clip["height"],
             "fps_num": int(num), "fps_den": int(den), "frames": clip["frames"], "out_dir": str(out),
             "samples": clip.get("samples", 32), "engine": clip.get("engine", "cycles"), "params": clip.get("params", {}),
             **{k: clip[k] for k in ("shutter", "exposure", "bounces") if k in clip}}
        if args.preview:
            a["preview"] = True
        cmd = ["nice", "-n", "19", str(BLENDER), "-b", "--factory-startup", "--python", str(SCRIPT), "--", json.dumps(a)]
        need = VRAM_EST.get((clip["scene"], a["engine"]), 2500)
        while blender_vram_mb() + need > args.vram_budget_mb:
            time.sleep(20)
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True)
        info = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
        if p.returncode != 0 or not info:
            print(p.stdout[-3000:], p.stderr[-3000:])
            print("FAILED", clip["id"], "(left without manifest; retried on the next run)", flush=True)
            continue
        frames = sorted(out.glob("frame_*.png"))
        if args.preview:
            print(clip["id"], "preview", [f.name for f in frames], round(time.time() - t0, 1), "s", flush=True)
            continue
        man.write_text(json.dumps({
            "clip_id": clip["id"], "frames": len(frames), "blender": json.loads(info[-1])["blender"],
            "scene_script_sha256": sha256_file(SCRIPT),
            "args": a, "command": cmd, "seconds": round(time.time() - t0, 1), "rendered_at": utc_now(),
            "frame_sha256": {f.name: sha256_file(f) for f in frames},
            "files": [{"name": f.name, "bytes": f.stat().st_size, "sha256": sha256_file(f)} for f in frames],
            "bytes": sum(f.stat().st_size for f in frames), "complete": True,
        }, indent=1))
        print(clip["id"], len(frames), "frames", round(time.time() - t0, 1), "s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
