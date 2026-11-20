#!/usr/bin/env python3
"""Plan the locally generated clips of Phase B (procedural Blender renders and screen renders)
and append them to config/phase_b_clips.yaml.

Counts per subcategory fill the gap between the coverage plan (prompt sections 3.1 / 3.2) and
the clips already planned from films and recordings. Durations are drawn so the whole dataset
approaches 50 % ~4 s / 30 % 6-8 s / 20 % ~10 s; about 20 % of the generated clips are portrait.
Every clip has its own seed and is its own split group. Deterministic (fixed RNG seed).
"""
from __future__ import annotations

import random
import sys
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "config" / "phase_b_clips.yaml"

# (scene, subcategory, count, engine, fps choices, portrait share, extra params)
BLENDER = [
    ("forest", "natural_environment", 10, "cycles", ["24", "25", "30", "30"], 0.3, {}),
    ("terrain", "natural_environment", 7, "cycles", ["24", "25", "30"], 0.15, {"speed_range": [8, 16]}),
    ("gears", "mechanical_rotating", 7, "cycles", ["25", "30", "60"], 0.15, {}),
    ("machine", "mechanical_rotating", 7, "cycles", ["24", "30", "60"], 0.15, {}),
    ("clock", "mechanical_rotating", 6, "cycles", ["25", "30", "60"], 0.3, {}),
    ("signs", "architecture_signs_text", 5, "cycles", ["25", "30", "60"], 0.2, {}),
    ("interior", "architecture_signs_text", 6, "mixed", ["24", "25", "30"], 0.2, {}),
    ("city", "architecture_signs_text", 3, "cycles", ["24", "30"], 0.0, {"slow": True}),
    ("city", "fast_motion", 4, "cycles", ["30", "60", "60"], 0.25, {}),
    ("tunnel", "fast_motion", 5, "cycles", ["30", "60", "60"], 0.2, {}),
    ("terrain", "fast_motion", 4, "cycles", ["30", "60"], 0.0, {"speed_range": [40, 80]}),
    ("chrome", "reflective_particles_fluids", 5, "cycles", ["24", "30", "60"], 0.2, {}),
    ("ocean", "reflective_particles_fluids", 3, "cycles", ["25", "30"], 0.34, {}),
    ("particles", "reflective_particles_fluids", 4, "cycles", ["25", "30", "60"], 0.25, {"kinds": ["sparks", "snow", "sparks", "confetti"]}),
    ("toon", "cartoon_stylized", 6, "eevee", ["24", "24", "25", "30"], 0.2, {}),
]
SCREEN = [
    ("spreadsheet", "spreadsheet", 8, 0.15), ("ledger", "spreadsheet", 6, 0.0),
    ("code", "code_editor", 9, 0.2), ("notebook", "code_editor", 5, 0.2),
    ("terminal", "terminal_logs", 5, 0.4), ("sysmon", "terminal_logs", 3, 0.0),
    ("dashboard", "dashboard_charts_tables", 6, 0.0), ("multiples", "dashboard_charts_tables", 5, 0.4),
    ("document", "documents_ui", 4, 0.5), ("mail", "documents_ui", 3, 0.0),
]


def main() -> int:
    plan = yaml.safe_load(PLAN.read_text())
    if any(c["kind"] in ("blender", "screen") for c in plan["clips"]):
        print("generated clips already planned; nothing to do")
        return 0
    rng = random.Random(20261120)
    pilot = yaml.safe_load((ROOT / "config" / "pilot_clips.yaml").read_text())["clips"]
    existing = pilot + plan["clips"]

    def secs(c):
        n = c.get("use_frames", c["frames"])
        return float(Fraction(n) / Fraction(c["fps"])) * (1 if c["kind"] != "ftp_mov_j2k" else 1)

    def bucket(s):
        return "4s" if s < 5.0 else ("6-8s" if s < 9.0 else "10s")

    have = {"4s": 0, "6-8s": 0, "10s": 0}
    for c in existing:
        have[bucket(secs(c))] += 1
    total = 240
    need = {"4s": round(0.5 * total) - have["4s"], "6-8s": round(0.3 * total) - have["6-8s"], "10s": round(0.2 * total) - have["10s"]}
    n_gen = sum(x[2] for x in BLENDER) + sum(x[2] for x in SCREEN)
    reserved = 35  # real-camera clips still to come from Wikimedia Commons share the remaining deficit
    tot_need = sum(max(0, v) for v in need.values())
    share = {k: max(0, v) * n_gen / max(1, tot_need) for k, v in need.items()}
    alloc = {k: int(share[k]) for k in share}
    for k in sorted(share, key=lambda k: share[k] - int(share[k]), reverse=True)[: n_gen - sum(alloc.values())]:
        alloc[k] += 1
    pool = [k for k in ("4s", "6-8s", "10s") for _ in range(alloc[k])]
    print("deficit", need, "reserved for Commons", reserved)
    rng.shuffle(pool)
    print("existing duration buckets", have, "-> generated", {k: pool.count(k) for k in have})

    def dur_frames(b, fps):
        f = float(Fraction(fps))
        sec = {"4s": rng.choice([3.0, 4.0, 4.0, 4.0, 4.5]), "6-8s": rng.choice([6.0, 7.0, 8.0]), "10s": rng.choice([9.5, 10.0])}[b]
        if b == "10s":  # keep <= 10 s exactly
            return int(min(10.0 * f, round(sec * f)))
        return int(round(sec * f))

    out = []
    seed = 3000
    for scene, sub, n, engine, fpss, pshare, extra in BLENDER:
        n_port = round(n * pshare)
        for i in range(n):
            seed += 1
            fps = rng.choice(fpss)
            b = pool.pop()
            frames = dur_frames(b, fps)
            portrait = i < n_port
            eng = engine if engine != "mixed" else ("eevee" if i % 2 else "cycles")
            params = {}
            if "speed_range" in extra:
                params["speed"] = round(rng.uniform(*extra["speed_range"]), 1)
            if extra.get("slow"):
                params["speed"] = round(rng.uniform(4, 9), 1)
            if "kinds" in extra:
                params["kind"] = extra["kinds"][i % len(extra["kinds"])]
            cid = f"r3d_own_{scene}_{seed}" + ("p" if portrait else "")
            c = {"id": cid, "category": "3d_rendered", "subcategory": sub, "collection": "own_blender_procedural",
                 "group": f"own_blender_{scene}_s{seed}", "kind": "blender", "scene": scene, "seed": seed,
                 "width": 1080 if portrait else 1920, "height": 1920 if portrait else 1080, "fps": fps, "frames": frames,
                 "samples": 32 if eng == "eevee" else 24, "engine": eng, "orientation": "portrait" if portrait else "landscape"}
            if params:
                c["params"] = params
            out.append(c)
    seed = 5000
    for scene, sub, n, pshare in SCREEN:
        n_port = round(n * pshare)
        for i in range(n):
            seed += 1
            fps = rng.choice(["24", "25", "30", "30", "60", "60"])
            b = pool.pop()
            frames = dur_frames(b, fps)
            portrait = i < n_port
            cid = f"scr_{scene}_{seed}" + ("p" if portrait else "")
            out.append({"id": cid, "category": "screen", "subcategory": sub, "collection": "own_screen_render",
                        "group": f"own_screen_{scene}_s{seed}", "kind": "screen", "scene": scene, "seed": seed,
                        "width": 1080 if portrait else 1920, "height": 1920 if portrait else 1080, "fps": fps, "frames": frames,
                        "orientation": "portrait" if portrait else "landscape"})
    lines = ["", "  # ================================================================== generated (tools/plan_generated.py)",
             "  # procedural Blender renders (CC0, one group per seed) and screen renders (CC0, one group per seed)"]
    for c in out:
        lines.append("  - " + yaml.safe_dump(c, default_flow_style=True, sort_keys=False, width=400).strip())
    with PLAN.open("a") as f:
        f.write("\n".join(lines) + "\n")
    print(len(out), "generated clips appended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
