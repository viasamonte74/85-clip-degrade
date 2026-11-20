#!/usr/bin/env python3
"""Group-aware train / validation / test assignment (80 / 10 / 10 per category).

The unit is the source group (parent film, recording session, scene file): every reference
of a group, and therefore every degraded variant of it, lands in the same split. Within each
category, groups are taken largest first and given to the split that minimises the squared
deviation from 80/10/10 (after validation and test have each received one group of any
category with at least three groups); ties break on a stable hash, so the result is deterministic. Existing assignments
are kept (a group never moves once assigned) unless --reassign is given.

Writes metadata/splits.json and hard-links each reference into data/references/<split>/.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sn85ds.util import DATA, METADATA, read_jsonl, stable_seed, upsert_jsonl, write_json  # noqa: E402

TARGET = {"train": 0.8, "validation": 0.1, "test": 0.1}


def assign(refs: list[dict], previous: dict[str, str]) -> dict[str, str]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for r in refs:
        groups[r["group_id"]].append(r)
    out = dict(previous)
    by_cat: dict[str, list[str]] = collections.defaultdict(list)
    for g, rs in groups.items():
        cats = {r["category"] for r in rs}
        if len(cats) != 1:
            raise SystemExit(f"group {g} spans categories {cats}")
        by_cat[cats.pop()].append(g)
    for cat, gs in by_cat.items():
        counts = collections.Counter()
        for g in gs:
            if g in out:
                counts[out[g]] += len(groups[g])
        todo = sorted((g for g in gs if g not in out), key=lambda g: (-len(groups[g]), stable_seed("split", g)))
        total = sum(len(groups[g]) for g in gs)
        # content mix: with >= 3 groups, validation and test each get one group of the category
        # first (the smallest available, so the training share stays large)
        if len(gs) >= 3:
            for s in ("validation", "test"):
                if counts[s] == 0 and todo:
                    g = min(todo, key=lambda g: (len(groups[g]), stable_seed("seed", g, s)))
                    todo.remove(g)
                    out[g] = s
                    counts[s] += len(groups[g])
        for g in todo:
            n = len(groups[g])

            def err(s: str) -> float:
                """Squared deviation from the 80/10/10 targets if group g went to split s."""
                c = dict(counts)
                c[s] = c.get(s, 0) + n
                return sum(((c.get(k, 0) - TARGET[k] * total) / total) ** 2 for k in TARGET)

            choice = min(TARGET, key=lambda s: (round(err(s), 9), stable_seed(g, s)))
            out[g] = choice
            counts[choice] += n
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reassign", action="store_true")
    ap.add_argument("--plan", help="also allocate the groups of planned (not yet prepared) clips, so the split is balanced up front")
    ap.add_argument("--existing-only", action="store_true",
                    help="assign nothing new: only references of groups that already have a split get linked "
                         "(used while a plan is still growing, so new groups are allocated once, with the full plan)")
    args = ap.parse_args()
    refs = read_jsonl(METADATA / "references.jsonl")
    prev_path = METADATA / "splits.json"
    previous = {} if args.reassign or not prev_path.exists() else json.loads(prev_path.read_text())["groups"]
    pool = list(refs)
    if args.plan:
        import yaml
        have = {r["source_id"] for r in refs}
        pool += [{"source_id": c["id"], "group_id": c["group"], "category": c["category"]}
                 for c in yaml.safe_load(Path(args.plan).read_text())["clips"] if c["id"] not in have]
    if args.existing_only:
        groups = dict(previous)
        refs = [r for r in refs if r["group_id"] in groups]
    else:
        groups = assign(pool, previous)
    splits: dict[str, list[str]] = {s: [] for s in TARGET}
    for r in refs:
        s = groups[r["group_id"]]
        splits[s].append(r["source_id"])
        dst = DATA / "references" / s / f"{r['source_id']}.mkv"
        dst.parent.mkdir(parents=True, exist_ok=True)
        for other in TARGET:  # a reassignment must not leave a stale link in another split
            stale = DATA / "references" / other / f"{r['source_id']}.mkv"
            if other != s and stale.exists():
                stale.unlink()
        src = ROOT / r["reference_path"]
        if dst.exists() and not os.path.samefile(src, dst):  # reference was rebuilt: refresh the link
            dst.unlink()
        if not dst.exists():
            os.link(src, dst)
        r["split"] = s
        r["split_path"] = str(dst.relative_to(ROOT))
        upsert_jsonl(METADATA / "references.jsonl", r, "source_id")
    for row in read_jsonl(METADATA / "sources.jsonl"):
        row["split"] = groups.get(row["group_id"])
        upsert_jsonl(METADATA / "sources.jsonl", row, "source_id")
    summary = collections.Counter((r["category"], groups[r["group_id"]]) for r in refs)
    write_json(prev_path, {"rule": "group-aware, per-category 80/10/10 by clip count; groups never move once assigned",
                           "groups": groups, "splits": {k: sorted(v) for k, v in splits.items()},
                           "counts": {f"{c}/{s}": n for (c, s), n in sorted(summary.items())}})
    for (c, s), n in sorted(summary.items()):
        print(f"{c:12s} {s:10s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
