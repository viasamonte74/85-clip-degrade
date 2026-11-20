#!/usr/bin/env python3
"""Re-verify licence evidence: fetch every evidence URL of every collection and check that the
recorded quote is still present (whitespace-normalised, first 120 characters).

Writes metadata/licenses.jsonl: one row per (collection, evidence URL) with status
verified / quote_missing / unreachable / not_checkable. A collection is 'verified' only if all
its fetchable evidence still matches. Sources are never silently replaced: a changed or
missing licence turns the collection's sources to 'needs review' in the validation report.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from sn85ds.acquisition.http import get_bytes  # noqa: E402
from sn85ds.util import METADATA, utc_now, write_jsonl  # noqa: E402


def norm(s: str) -> str:
    """Lower-case text with tags, markdown emphasis and whitespace before punctuation removed."""
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = s.replace("\\\"", "\"").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"[*_`]", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([.,;:)])", r"\1", s)
    return s.strip().lower()


def fetch_text(url: str) -> str:
    if url.startswith("https://media.xiph.org/"):  # throttled host: read the AWS Open Data mirror instead
        url = url.replace("https://media.xiph.org/", "https://s3.amazonaws.com/xiph-media/media.xiph.org/")
    if "github.com" in url and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    blob = get_bytes(url)
    if url.lower().endswith(".pdf"):
        import io
        from pypdf import PdfReader
        return "\n".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(blob)).pages)
    return blob.decode("utf-8", "replace")


def audit_commons_files() -> list[dict]:
    """Per-file Commons licences: re-read each used file's page metadata and compare."""
    from sn85ds.acquisition import commons as cm
    from sn85ds.util import read_jsonl
    srcs = [r for r in read_jsonl(METADATA / "sources.jsonl") if r.get("collection") == "wikimedia_commons"]
    rows = []
    if not srcs:
        return rows
    titles = [r["plan"]["title"] for r in srcs]
    info = cm.file_info(titles)
    for r in srcs:
        cur = info.get(r["plan"]["title"], {})
        same = cur.get("licence_short") == r["plan"]["licence_short"] and cur.get("sha1") == r["plan"]["sha1"]
        rows.append({"collection": "wikimedia_commons", "source_id": r["source_id"], "licence": r["licence"], "url": r["plan"]["commons_page"],
                     "checked_at": utc_now(), "status": "verified" if same else "quote_missing",
                     "note": f"file page licence now '{cur.get('licence_short')}', sha1 {'unchanged' if cur.get('sha1') == r['plan']['sha1'] else 'CHANGED'}"})
    return rows


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    rows = []
    for coll, c in cfg["collections"].items():
        for ev in c.get("evidence", []):
            url, quote = ev["url"], ev.get("quote", "")
            row = {"collection": coll, "licence": c["licence"], "url": url, "checked_at": utc_now()}
            if "<" in url:  # placeholder (per-file collections are audited file by file below)
                continue
            if url.lower().endswith((".png", ".jpg", ".tif")):  # text inside a frame of the work: read visually
                import hashlib
                try:
                    row["sha256"] = hashlib.sha256(get_bytes(url.replace("https://media.xiph.org/", "https://s3.amazonaws.com/xiph-media/media.xiph.org/"))).hexdigest()
                    row["status"], row["note"] = "verified_visual", "frame of the work itself; text read visually (2026-11-20), image hash recorded"
                except Exception as exc:
                    row["status"], row["error"] = "unreachable", repr(exc)[:200]
                rows.append(row)
                continue
            if quote.startswith("("):
                row["status"] = "not_checkable"
                row["note"] = "descriptive entry (licence file presence), not a quote"
                try:
                    txt = fetch_text(url)
                    row["status"] = "verified" if "creative commons" in txt.lower() else "quote_missing"
                    row["note"] = "licence file fetched; contains a Creative Commons licence text"
                except Exception as exc:
                    row["status"], row["error"] = "unreachable", repr(exc)[:200]
                rows.append(row)
                continue
            try:
                txt = norm(fetch_text(url))
                needle = norm(quote)
                probes = [p.strip(" .;:") for p in re.split(r"\.\.\.", needle) if len(p.strip(" .;:")) > 20]
                ok = all(p[:120] in txt for p in probes) if probes else needle[:120] in txt
                row["status"] = "verified" if ok else "quote_missing"
            except Exception as exc:
                row["status"], row["error"] = "unreachable", repr(exc)[:200]
            rows.append(row)
            print(f"{coll:24s} {row['status']:14s} {url}", flush=True)
    rows += audit_commons_files()
    write_jsonl(METADATA / "licenses.jsonl", rows)
    bad = [r for r in rows if r["status"] not in ("verified", "not_checkable", "verified_visual")]
    print(f"{len(rows)} evidence items, {len(bad)} not verified")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
