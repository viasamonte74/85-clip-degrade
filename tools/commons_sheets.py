#!/usr/bin/env python3
"""Shortlist Wikimedia Commons candidates and build review sheets cheaply.

From data/work/commons/candidates.json (tools/discover_commons.py): drop files whose title or
categories show they are not suitable camera footage (animation/CGI, screencasts, 360-degree
video, interviews/speeches/lectures, news, trailers, slideshows, time-lapses), rank the rest by
resolution and bits per pixel, cap uploads per uploader (diversity), keep the best N per
subcategory, check the frame rate with a header-only remote ffprobe, and fetch three still
thumbnails per file from Commons' own thumbnail service (no video download).
Writes data/work/commons/shortlist.json and data/work/commons/sheets/sl_*.jpg.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PIL import Image, ImageDraw  # noqa: E402

from sn85ds.acquisition import commons as cm  # noqa: E402
from sn85ds.util import DATA  # noqa: E402

WORK = DATA / "work" / "commons"
BAD_TITLE = re.compile(r"(animat|render|cgi|\bcg\b|simulat|game|screen|slideshow|time[- ]?lapse|hyperlapse|trailer|teaser|music video|lyric|"
                       r"interview|speech|conference|lecture|press|webinar|tutorial|presentation|news|documentary|\b360\b|360°|vr180|equirect|"
                       r"spherical|fpv|stereo|3d\b|ai[- ]gen|generated|montage|compilation|intro|outro|logo|countdown|subtit|sermon|debate|"
                       r"parliament|senate|council|hearing|briefing|campaign|advert|commercial|promo|wikipedia|wikimania|edit-a-thon|kurzgesagt)", re.I)
ALLOWED_FPS = {Fraction(24), Fraction(25), Fraction(30), Fraction(60), Fraction(30000, 1001), Fraction(60000, 1001), Fraction(24000, 1001)}


def thumb_urls(url: str, dur: float, width: int = 330) -> list[str]:
    """Commons video stills from the thumbnail service (thumb.wikimedia.org, standard width 330)."""
    path = urllib.parse.urlparse(url).path            # /wikipedia/commons/a/ab/Name.webm
    parts = path.split("/")
    name = parts[-1]
    base = "https://thumb.wikimedia.org" + "/".join(parts[:3]) + "/thumb/" + "/".join(parts[3:]) + "/"
    secs = [max(1.0, dur * f) for f in (0.2, 0.7)]
    return [base + f"{width}px-seek%3D{s:.0f}-{name}.jpg" for s in secs]


def get(url: str, tries: int = 6) -> bytes | None:
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": cm.UA})
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (404, 400):
                return None
            ra = getattr(e, "headers", None) and e.headers.get("Retry-After")
            wait = int(ra) if ra and str(ra).isdigit() else 10 * 2 ** k
            print(f"thumb retry in {wait}s ({code})", flush=True)
            time.sleep(min(wait, 900))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-sub", type=int, default=30)
    ap.add_argument("--per-uploader", type=int, default=2)
    args = ap.parse_args()
    cands = {k: v for k, v in json.loads((WORK / "candidates.json").read_text()).items() if not k.startswith("q::")}
    pool = []
    for t, v in cands.items():
        reasons = [r for r in v["screen_reasons"] if not r.startswith("probe") and not r.startswith("frame rate") and not r.startswith("variable")]
        if reasons:
            continue
        text = t + " " + " ".join(v["categories"])
        if BAD_TITLE.search(text) or not v["duration"] or v["duration"] > 1800:
            continue
        w, h = v["width"], v["height"]
        bpp = v["bytes"] * 8 / v["duration"] / (w * h * 30)
        v["score"] = round(min(min(w, h) / 1080, 2.0) + min(bpp / 0.04, 3.0), 3)
        pool.append(v)
    out, per_up = [], {}
    for sub in sorted({v["topic_subcategory"] for v in pool}):
        sel = [v for v in sorted(pool, key=lambda v: -v["score"]) if v["topic_subcategory"] == sub]
        k = 0
        for v in sel:
            up = (v.get("uploader") or "?", sub)
            if per_up.get(up, 0) >= args.per_uploader or v in out:
                continue
            per_up[up] = per_up.get(up, 0) + 1
            out.append(v)
            k += 1
            if k >= args.per_sub:
                break
    print(len(pool), "after title/category filter;", len(out), "shortlisted")

    # no remote probing here (Wikimedia rate limits media requests); the frame rate, scan type and colour
    # tags are checked on the downloaded file by tools/commons_select.py
    keep = out
    tdir = WORK / "thumbs"
    tdir.mkdir(exist_ok=True)
    for i, v in enumerate(keep):
        v["review_id"] = v.get("review_id") or "c" + hashlib.sha1(v["title"].encode()).hexdigest()[:6]
        v["thumbs"] = []
        for j, u in enumerate(thumb_urls(v["url"], v["duration"])):
            p = tdir / f"{v['review_id']}_{j}.jpg"
            if not p.exists():
                b = get(u)
                time.sleep(3.0)
                if b:
                    p.write_bytes(b)
            if p.exists():
                v["thumbs"].append(str(p))
    (WORK / "shortlist.json").write_text(json.dumps(keep, indent=1))
    per = 8
    W, H = 330, 186
    for s in range(0, len(keep), per):
        chunk = keep[s:s + per]
        im = Image.new("RGB", (2 * W, len(chunk) * (H + 26)), "black")
        dr = ImageDraw.Draw(im)
        for r, v in enumerate(chunk):
            y = r * (H + 26)
            dr.text((2, y + 1), f"{v['review_id']} {v['topic_subcategory'][:14]} {v['width']}x{v['height']} "
                    f"{v.get('mbps')}Mbps {v['duration']:.0f}s {v['licence']} | {v['title'][5:72]}", fill="yellow")
            dr.text((2, y + 12), f"up:{(v.get('uploader') or '')[:20]} by:{v['artist'][:40]} | {', '.join(v['categories'][:3])[:90]}", fill="cyan")
            for c, p in enumerate(v["thumbs"]):
                t = Image.open(p).convert("RGB")
                t.thumbnail((W, H))
                im.paste(t, (c * W, y + 26))
        im.save(WORK / "sheets" / f"sl_{s // per:03d}.jpg", quality=80)
    print("sheets", math.ceil(len(keep) / per))
    return 0


if __name__ == "__main__":
    sys.exit(main())
