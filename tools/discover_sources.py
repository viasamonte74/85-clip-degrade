#!/usr/bin/env python3
"""Enumerate candidate clips in the verified collections (config/sources.yaml) and count the
independent source groups available per category.

Writes metadata/candidates.jsonl and reports/source_capacity.md. A candidate is a continuous
segment of a licensed master that could become one reference; it carries the collection's
licence and its group (the split unit). Nothing is downloaded except listings and the Sintel
shot table (computed from the 1080p proxy, see the pilot). Own procedural renders and screen
recordings are unlimited in count but listed per scene type.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sn85ds.acquisition.http import s3_list  # noqa: E402
from sn85ds.util import DATA, METADATA, REPORTS, write_jsonl  # noqa: E402

NF = "https://s3.amazonaws.com/download.opencontent.netflix.com/"
XM = "https://s3.amazonaws.com/xiph-media/"
MIN_FRAMES = 96


def main() -> int:
    cands = []
    # Netflix SDR shot segments (zip per frame range)
    for title, group, fps in (("sparks", "film_sparks", "60000/1001"), ("meridian", "film_meridian", "60000/1001"),
                              ("nocturne", "film_nocturne", "60"), ("sol_levante", "film_sol_levante", "24"), ("cosmos", "film_cosmos_laundromat", "24")):
        _, files = s3_list(NF, f"aom_test_materials/SDR/{title}/")
        for k, size in files:
            m = re.search(r"(\d+)-(\d+)\.zip$", k)
            if not m:
                continue
            n = int(m.group(2)) - int(m.group(1)) + 1
            cat = "real_camera" if title in ("sparks", "meridian", "nocturne") else "3d_rendered"
            note = {"sol_levante": "2D hand-drawn anime: stylized, not 3D-rendered — flagged",
                    "cosmos": "2K (2048x858): below 1080 lines, not usable without upscaling — rejected"}.get(title)
            cands.append({"candidate_id": f"nf_{title}_{m.group(1)}", "collection": "netflix_sdr_segments", "category": cat, "group": group,
                          "access": NF + k, "frames": n, "fps": fps, "bytes": size, "licence": "CC-BY-4.0", "usable": title != "cosmos", "note": note})
    # El Fuente + Chimera y4m sequences (licence file at the folder / tree root)
    for prefix, group, fps in (("ElFuente/", "film_el_fuente", "60"), ("aom_test_materials/ElFuente/", "film_el_fuente", "60"),
                               ("aom_test_materials/Chimera/", "film_chimera", "30000/1001")):
        _, files = s3_list(NF, prefix)
        for k, size in files:
            m = re.search(r"_(\d+)x(\d+)_.*_10bit_(\d+)\.y4m$", k)
            if not m:
                continue
            w, h = int(m.group(1)), int(m.group(2))
            fsize = int(w * h * (1.5 if m.group(3) == "420" else 2.0)) * 2 + 6
            cands.append({"candidate_id": "nf_" + Path(k).stem, "collection": "netflix_elfuente" if "ElFuente" in k else "netflix_chimera_aom",
                          "category": "real_camera", "group": group, "access": NF + k, "frames": int(size // fsize), "fps": fps, "bytes": size,
                          "licence": "CC-BY-4.0", "usable": True, "note": "4:2:2 master" if m.group(3) == "422" else None})
    # BBB 3D 60 fps scenes
    dirs, _ = s3_list(XM, "media.xiph.org/BBB/bbb3d/video/png/", delimiter="/")
    for d in dirs:
        _, files = s3_list(XM, d)
        n = sum(1 for k, _ in files if k.endswith(".png"))
        name = d.rstrip("/").split("/")[-1]
        if n >= MIN_FRAMES and name not in ("black", "00_00", "13_10"):  # 00_00 logo, 13_10 credits
            cands.append({"candidate_id": f"bbb3d_{name}", "collection": "xiph_bbb3d", "category": "3d_rendered", "group": "film_big_buck_bunny",
                          "access": XM + d, "frames": n, "fps": "60", "bytes": sum(s for _, s in files), "licence": "CC-BY-3.0", "usable": True,
                          "note": "scene folder; cut-checked at preparation"})
    # Sintel shots from the proxy shot table (logos and credits excluded)
    shots_file = DATA / "work" / "sintel_shots.json"
    if shots_file.exists():
        s = json.loads(shots_file.read_text())
        for a, b in s["shots"]:
            if b - a >= MIN_FRAMES and a >= 752 and b <= 17858:
                cands.append({"candidate_id": f"sintel_{a}_{b}", "collection": "xiph_sintel4k", "category": "3d_rendered", "group": "film_sintel",
                              "access": f"{XM}media.xiph.org/sintel/sintel-4k-png/ frames {a + 1}-{b}", "frames": b - a, "fps": "24",
                              "licence": "CC-BY-3.0", "usable": True, "note": None})
    cands.append({"candidate_id": "dweebs_8k", "collection": "xiph_dweebs8k", "category": "3d_rendered", "group": "film_daily_dweebs",
                  "access": XM + "media.xiph.org/dweebs/tif_8k_mono/", "frames": 1440, "fps": "24 (inferred)", "licence": "CC-BY-SA-4.0",
                  "usable": True, "note": "short film with many short shots; shots found at preparation"})
    for sc in ("gears", "signs", "ocean", "city"):
        cands.append({"candidate_id": f"own_blender_{sc}", "collection": "own_blender_procedural", "category": "3d_rendered",
                      "group": f"own_blender_{sc}_<seed>", "access": "local render", "frames": None, "fps": "any", "licence": "CC0-1.0",
                      "usable": True, "note": "one group per seed; GPU-time bound"})
    for sc in ("spreadsheet", "code", "terminal", "dashboard", "document"):
        cands.append({"candidate_id": f"own_screen_{sc}", "collection": "own_screen_render", "category": "screen",
                      "group": f"own_screen_{sc}_<seed>", "access": "local render", "frames": None, "fps": "any", "licence": "CC0-1.0",
                      "usable": True, "note": "one group per seed; CPU-time bound"})
    write_jsonl(METADATA / "candidates.jsonl", cands)
    finite = [c for c in cands if c["frames"] and c["usable"]]
    lines = ["# Source capacity (licensed candidates found so far)", "",
             "| category | collection | candidate segments | independent groups | frames available |", "|---|---|---|---|---|"]
    by = {}
    for c in finite:
        k = (c["category"], c["collection"])
        e = by.setdefault(k, {"n": 0, "groups": set(), "frames": 0})
        e["n"] += 1
        e["groups"].add(c["group"])
        e["frames"] += c["frames"]
    for (cat, coll), e in sorted(by.items()):
        lines.append(f"| {cat} | {coll} | {e['n']} | {len(e['groups'])} | {e['frames']} |")
    groups = {}
    for c in finite:
        groups.setdefault(c["category"], set()).add(c["group"])
    lines += ["", "Independent parent works (films) with downloadable licensed masters: " +
              ", ".join(f"{k}: {len(v)}" for k, v in sorted(groups.items())) +
              "; own renders add one group per seed (3D, screen).", "",
              "Shortfall: real-camera material comes from 5 Netflix parent films only. 60 real-camera originals from 5 films "
              "would mean ~12 clips per film, against the diversity rule. More licensed live-action sources (e.g. "
              "Wikimedia Commons CC0/CC BY >=1080p uploads, checked file by file) are needed before Phase B can reach the "
              "real-camera target with adequate diversity. Surveyed route: Wikimedia Commons per-file licences "
              "(config/sources.yaml candidate_collections: 379 allow-listed >=1080p videos found in 8 queries, many 4K at "
              "100+ Mbps); each file still needs privacy / third-party-content review."]
    (REPORTS / "source_capacity.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
