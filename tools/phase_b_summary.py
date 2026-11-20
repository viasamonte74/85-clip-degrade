#!/usr/bin/env python3
"""Phase B status report: planned vs prepared vs degraded, coverage tables (category, subcategory,
orientation, frame rate, duration bucket, licence, source groups, splits), Commons review outcome,
storage and throughput. Writes reports/phase_b_report.md; hand-written notes from
reports/notes/phase_b_notes.md are appended verbatim."""
from __future__ import annotations

import collections
import json
import shutil
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import yaml  # noqa: E402

from sn85ds.util import DATA, METADATA, REPORTS, read_jsonl, utc_now  # noqa: E402

TARGET_SUB = {
    "3d_rendered": {"natural_environment": 24, "mechanical_rotating": 24, "architecture_signs_text": 18, "fast_motion": 18,
                    "reflective_particles_fluids": 18, "cartoon_stylized": 18},
    "screen": {"spreadsheet": 15, "code_editor": 15, "terminal_logs": 9, "dashboard_charts_tables": 12, "documents_ui": 9},
    "real_camera": {"people_hands_activity": 12, "animals_foliage_nature": 12, "water_rain_reflections": 12, "urban_vehicles": 12,
                    "low_light_motion_blur": 12},
}


def bucket(sec: float) -> str:
    return "~4 s (<5)" if sec < 5 else ("6-8 s (5-9)" if sec < 9 else "~10 s (9-10)")


def table(title: str, counter: collections.Counter, total: int, target: dict | None = None) -> list[str]:
    out = [f"| {title} | clips | share |" + (" target |" if target else ""), "|---|---|---|" + ("---|" if target else "")]
    for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        out.append(f"| {k} | {v} | {100 * v / max(1, total):.1f} % |" + (f" {target.get(k, '-')} |" if target else ""))
    return out


def main() -> int:
    plans = []
    for f in ("pilot_clips.yaml", "phase_b_clips.yaml"):
        plans += [dict(c, plan_file=f) for c in yaml.safe_load((ROOT / "config" / f).read_text())["clips"]]
    refs = {r["source_id"]: r for r in read_jsonl(METADATA / "references.jsonl")}
    srcs = {r["source_id"]: r for r in read_jsonl(METADATA / "sources.jsonl")}
    vars_ = read_jsonl(METADATA / "variants.jsonl")
    vcount = collections.Counter(v["source_id"] for v in vars_)
    splits = json.loads((METADATA / "splits.json").read_text()) if (METADATA / "splits.json").exists() else {"groups": {}}
    L = [f"# Phase B report — toward 240 originals / 960 pairs ({utc_now()[:16]}Z)", ""]
    done = [c for c in plans if c["id"] in refs]
    full = [c for c in done if vcount[c["id"]] >= 4]
    L += ["## Progress", "", "| stage | clips |", "|---|---|",
          f"| planned (pilot + Phase B) | {len(plans)} |", f"| reference prepared | {len(done)} |",
          f"| 4 degraded variants | {len(full)} ({sum(vcount.values())} variants) |", ""]
    by_cat_plan = collections.Counter(c["category"] for c in plans)
    by_cat_done = collections.Counter(c["category"] for c in done)
    L += ["## Coverage (planned; prepared in brackets)", "", "| category | planned | prepared | target |", "|---|---|---|---|"]
    for cat, tgt in (("3d_rendered", 120), ("screen", 60), ("real_camera", 60)):
        L.append(f"| {cat} | {by_cat_plan[cat]} | {by_cat_done[cat]} | {tgt} |")
    L.append("")
    for cat, tg in TARGET_SUB.items():
        sub = collections.Counter(c["subcategory"] for c in plans if c["category"] == cat)
        L += [f"**{cat}**", ""] + table("subcategory", sub, sum(sub.values()), tg) + [""]

    def sec(c):
        r = refs.get(c["id"])
        if r:
            return float(r["duration_s"])
        return float(Fraction(c.get("use_frames", c["frames"])) / Fraction(c["fps"]))
    L += table("orientation", collections.Counter(c["orientation"] for c in plans), len(plans)) + [""]
    L += table("frame rate", collections.Counter(str(c["fps"]) for c in plans), len(plans)) + [""]
    L += table("duration (prepared length where available)", collections.Counter(bucket(sec(c)) for c in plans), len(plans)) + [""]
    lic = collections.Counter()
    for c in plans:
        s = srcs.get(c["id"])
        lic[(s or {}).get("licence") or c.get("licence") or {"own_blender_procedural": "CC0-1.0", "own_screen_render": "CC0-1.0"}.get(c["collection"], c["collection"])] += 1
    L += table("licence", lic, len(plans)) + [""]
    groups = collections.defaultdict(set)
    for c in plans:
        groups[c["category"]].add(c["group"])
    big = collections.Counter(c["group"] for c in plans)
    L += ["## Source diversity", "", "| category | independent groups | largest groups |", "|---|---|---|"]
    for cat in ("3d_rendered", "screen", "real_camera"):
        top = sorted(((n, g) for g, n in big.items() if g in groups[cat]), reverse=True)[:5]
        L.append(f"| {cat} | {len(groups[cat])} | " + ", ".join(f"{g} ({n})" for n, g in top) + " |")
    L.append("")
    sp = collections.Counter()
    for c in plans:
        s = splits["groups"].get(c["group"])
        sp[(c["category"], s or "unassigned")] += 1
    L += ["## Splits (by clip, groups never cross splits)", "", "| category | train | validation | test | unassigned |", "|---|---|---|---|---|"]
    for cat in ("3d_rendered", "screen", "real_camera"):
        L.append(f"| {cat} | " + " | ".join(str(sp[(cat, s)]) for s in ("train", "validation", "test", "unassigned")) + " |")
    L.append("")
    rev = read_jsonl(METADATA / "commons_review.jsonl")
    if rev:
        dec = collections.Counter(r["decision"] for r in rev)
        L += ["## Wikimedia Commons review", "",
              f"Shortlisted files reviewed one by one: {len(rev)} recorded decisions ({dict(dec)}). Rejections and reasons: "
              "`metadata/commons_review.jsonl`; all decisions: `config/commons_review.yaml`.", ""]
    du = {p.name: sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) for p in (DATA / "references", DATA / "degraded", DATA / "downloads")}
    free = shutil.disk_usage(str(DATA)).free
    L += ["## Storage", "", "| directory | GB |", "|---|---|"] + [f"| data/{k} | {v / 1e9:.1f} |" for k, v in du.items()] + [f"| free | {free / 1e9:.0f} |", ""]
    secs = [r.get("seconds") for r in refs.values() if r.get("seconds")]
    if secs:
        secs.sort()
        L += [f"Reference preparation: median {secs[len(secs) // 2]:.0f} s per clip (n={len(secs)}).", ""]
    notes = REPORTS / "notes" / "phase_b_notes.md"
    if notes.exists():
        L += [notes.read_text()]
    (REPORTS / "phase_b_report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
