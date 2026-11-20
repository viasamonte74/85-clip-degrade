#!/usr/bin/env python3
"""Propagate plan-level labels (subcategory, privacy flag) from the clip plans into
metadata/references.jsonl, sources.jsonl and variants.jsonl after a label is corrected in a plan
(e.g. a shot window turned out to show different content than its preview suggested).
Media, checksums and splits are untouched; every change is printed."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import yaml  # noqa: E402

from sn85ds.util import METADATA, read_jsonl, write_jsonl  # noqa: E402


def main() -> int:
    plan = {}
    for f in ("pilot_clips.yaml", "phase_b_clips.yaml"):
        for c in yaml.safe_load((ROOT / "config" / f).read_text())["clips"]:
            plan[c["id"]] = c
    for name in ("references.jsonl", "sources.jsonl", "variants.jsonl"):
        rows = read_jsonl(METADATA / name)
        n = 0
        for r in rows:
            c = plan.get(r.get("source_id"))
            if not c:
                continue
            if r.get("subcategory") != c["subcategory"]:
                print(f"{name}: {r.get('input_id', r['source_id'])} subcategory {r.get('subcategory')} -> {c['subcategory']}")
                r["subcategory"] = c["subcategory"]
                n += 1
            if name == "sources.jsonl":
                pf = bool(c.get("privacy_flag", False))
                if r.get("privacy_flag") != pf:
                    r["privacy_flag"] = pf
                    n += 1
                if r.get("plan") != c:
                    r["plan"] = c
        if n:
            write_jsonl(METADATA / name, rows)
        print(name, n, "changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
