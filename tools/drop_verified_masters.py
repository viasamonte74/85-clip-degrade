#!/usr/bin/env python3
"""Disk-saving pass over already-prepared clips: re-checksum each reference's decoded planes against
references.jsonl and only then delete its master files (manifest.json is kept, so downloaded masters
can be re-fetched and rebuilt bit-exactly; rendered masters can be re-rendered from the recorded
scene, seed and script hash). Updates provenance in sources.jsonl."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import yaml  # noqa: E402

from prepare_references import drop_master  # noqa: E402
from sn85ds.media import decoded_checksum  # noqa: E402
from sn85ds.util import DATA, METADATA, read_jsonl, upsert_jsonl, utc_now  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", nargs="*", default=["config/pilot_clips.yaml", "config/phase_b_clips.yaml"])
    ap.add_argument("--kinds", nargs="*", default=["frames_http", "zip_j2k", "y4m_range", "ftp_mov_j2k", "commons_window"])
    args = ap.parse_args()
    plan = {}
    for p in args.plans:
        plan.update({c["id"]: c for c in yaml.safe_load((ROOT / p).read_text())["clips"]})
    refs = {r["source_id"]: r for r in read_jsonl(METADATA / "references.jsonl")}
    srcs = {r["source_id"]: r for r in read_jsonl(METADATA / "sources.jsonl")}
    total = 0
    for cid, c in plan.items():
        base = DATA / "downloads" / cid
        if c["kind"] not in args.kinds or cid not in refs or not base.exists():
            continue
        if not any(p.is_file() and p.name != "manifest.json" for p in base.rglob("*")):
            continue
        ref = refs[cid]
        dec, n = decoded_checksum(ROOT / ref["reference_path"])
        if dec != ref["planes_sha256"] or n != ref["frames"]:
            print(cid, "reference re-verification FAILED; master kept", flush=True)
            continue
        freed = drop_master(base)
        total += freed
        s = srcs.get(cid)
        if s:
            s["provenance"]["master_on_disk"] = False
            s["provenance"]["master_dropped"] = {"at": utc_now(), "bytes_freed": freed, "reverified_planes_sha256": True}
            upsert_jsonl(METADATA / "sources.jsonl", s, "source_id")
        print(cid, f"{freed / 1e9:.2f} GB freed", flush=True)
    print(f"total {total / 1e9:.1f} GB freed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
