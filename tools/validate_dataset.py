#!/usr/bin/env python3
"""Validate sources, references, variants and split isolation; write reports/validation.json.

Failing items are listed in metadata/quarantine.jsonl (nothing is deleted). Exit status 1 if
any error remains. --quick skips the full-decode checks (plane checksums, pairing alignment).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sn85ds.util import METADATA, REPORTS, read_jsonl, utc_now, write_json, write_jsonl  # noqa: E402
from sn85ds.validation import checks  # noqa: E402


def _ref(args):
    ref, deep = args
    return checks.check_reference(ref, ROOT, deep=deep).as_dict()


def _var(args):
    v, ref, deep = args
    return checks.check_variant(v, ref, ROOT, deep=deep).as_dict()


def _hash(ref):
    return ref["source_id"], checks.dhash_frames(ROOT / ref["reference_path"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--near-dup-bits", type=int, default=8)
    args = ap.parse_args()
    deep = not args.quick
    sources = read_jsonl(METADATA / "sources.jsonl")
    refs = {r["source_id"]: r for r in read_jsonl(METADATA / "references.jsonl")}
    variants = read_jsonl(METADATA / "variants.jsonl")
    results = [checks.check_source(s).as_dict() for s in sources]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        results += list(ex.map(_ref, [(r, deep) for r in refs.values()]))
        results += list(ex.map(_var, [(v, refs[v["source_id"]], deep) for v in variants if v["source_id"] in refs]))
        hashes = dict(ex.map(_hash, list(refs.values())))
    for v in variants:
        if v["source_id"] not in refs:
            results.append({"item": v["input_id"], "kind": "variant", "status": "fail", "errors": ["reference metadata missing"], "warnings": []})
    # split isolation: groups and exact / near duplicates across splits
    leak = []
    group_split = collections.defaultdict(set)
    for r in refs.values():
        group_split[r["group_id"]].add(r.get("split"))
    for g, ss in group_split.items():
        if len(ss) > 1:
            leak.append({"type": "group_in_multiple_splits", "group": g, "splits": sorted(map(str, ss))})
    by_sha = collections.defaultdict(list)
    for r in refs.values():
        by_sha[r["planes_sha256"]].append(r["source_id"])
    for sha, ids in by_sha.items():
        if len(ids) > 1:
            leak.append({"type": "exact_duplicate_reference", "ids": ids})
    ids = sorted(refs)
    near = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if not hashes[a] or not hashes[b]:
                continue
            d = min(checks.hamming(x, y) for x in hashes[a] for y in hashes[b])
            if d <= args.near_dup_bits:
                same_group = refs[a]["group_id"] == refs[b]["group_id"]
                cross = refs[a].get("split") != refs[b].get("split")
                near.append({"a": a, "b": b, "min_dhash_bits": d, "same_group": same_group, "cross_split": cross})
                if cross:
                    leak.append({"type": "near_duplicate_across_splits", "a": a, "b": b, "min_dhash_bits": d})
    status = collections.Counter((r["kind"], r["status"]) for r in results)
    quarantine = [r for r in results if r["status"] == "fail"]
    write_jsonl(METADATA / "quarantine.jsonl", quarantine)
    write_json(REPORTS / "validation.json", {"generated_at": utc_now(), "deep": deep,
                                              "summary": {f"{k}/{s}": n for (k, s), n in sorted(status.items())},
                                              "split_leaks": leak, "near_duplicates": near, "results": results})
    for (k, s), n in sorted(status.items()):
        print(f"{k:10s} {s:5s} {n}")
    print("split leaks:", len(leak), "| near-duplicate pairs:", len(near), "| quarantined:", len(quarantine))
    for q in quarantine:
        print("  FAIL", q["item"], q["errors"])
    return 1 if quarantine or leak else 0


if __name__ == "__main__":
    sys.exit(main())
