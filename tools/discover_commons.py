#!/usr/bin/env python3
"""Search Wikimedia Commons for real-camera video candidates and build review sheets.

1. CirrusSearch queries per real-camera subcategory (filetype:video, >= 2560 px wide, plus
   portrait and high-bitrate 1080p queries).
2. Per-file metadata via the API (licence, author, restrictions, categories, SHA-1).
3. Automatic screening: licence on the allow-list, >= 1080 lines in the target orientation,
   >= 6 s, no excluded categories (animation, CGI, screenshots, time-lapse, archival...),
   bitrate high enough that the 1080p downscale hides the upload's compression, constant
   native frame rate in the allowed set (remote ffprobe).
4. Four sample frames per survivor -> data/work/commons/sheets/*.jpg for manual review.

Writes data/work/commons/candidates.json (all metadata + screening reasons).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from sn85ds.acquisition import commons as cm  # noqa: E402
from sn85ds.util import DATA  # noqa: E402

WORK = DATA / "work" / "commons"
TOPICS = {
    "people_hands_activity": ["cooking", "baking bread", "woodworking", "pottery wheel", "knitting", "craftsman hands", "blacksmith forge",
                              "street market", "folk dance", "juggling", "sewing machine", "carpentry", "playing chess", "making pasta"],
    "animals_foliage_nature": ["bird", "insect", "bee flower", "butterfly", "deer", "horse", "cat", "dog", "cow", "squirrel", "flowers wind",
                               "forest", "leaves wind", "grass meadow", "duck", "swan", "fish aquarium", "ants"],
    "water_rain_reflections": ["waterfall", "rain", "river", "waves beach", "sea", "lake", "fountain", "stream", "water drops", "puddle reflection",
                               "snowfall", "rapids"],
    "urban_vehicles": ["traffic", "train", "tram", "street", "city", "cars road", "bicycle", "airport aircraft", "harbour ship", "bus",
                       "railway station", "highway", "motorcycle", "crowd square"],
    "low_light_motion_blur": ["night", "fireworks", "candle", "campfire", "city at night", "neon", "aurora", "lightning", "fire flames",
                              "night traffic", "lantern", "sunset"],
}
ALLOWED_FPS = {Fraction(24), Fraction(25), Fraction(30), Fraction(60), Fraction(30000, 1001), Fraction(60000, 1001), Fraction(24000, 1001), Fraction(50)}


def screen(info: dict) -> list[str]:
    why = []
    if not info["licence"]:
        why.append(f"licence '{info['licence_short']}' not on the allow-list")
    w, h = info["width"] or 0, info["height"] or 0
    if min(w, h) < 1080 or max(w, h) < 1920:
        why.append(f"{w}x{h} below 1080p")
    if not info["duration"] or info["duration"] < 6:
        why.append(f"duration {info['duration']}")
    bad = [c for c in info["categories"] if cm.BAD_CATEGORY.search(c)]
    if bad:
        why.append("excluded category: " + "; ".join(bad[:3]))
    if info["duration"]:
        mbps = info["bytes"] * 8 / info["duration"] / 1e6
        info["mbps"] = round(mbps, 2)
        px = w * h
        bpp_req = 0.10 if max(w, h) >= 2560 else 0.25   # bits / pixel / second-ish proxy (at 30 fps): 4K >= ~25 Mbps, 1080p >= ~15 Mbps
        if mbps * 1e6 / (px * 30) < bpp_req * 1.0:
            why.append(f"bitrate {mbps:.1f} Mbps too low for {w}x{h}")
    if info["restrictions"]:
        info["restriction_flag"] = info["restrictions"]
    return why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=100)
    ap.add_argument("--sheets-only", action="store_true")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    cand_path = WORK / "candidates.json"
    cands = json.loads(cand_path.read_text()) if cand_path.exists() else {}
    if not args.sheets_only:
        for sub, topics in TOPICS.items():
            for t in topics:
                for q in (f"filetype:video filew:>2559 {t}",):
                    key = f"q::{q}"
                    if key in cands:
                        continue
                    titles = cm.search(q, args.per_query)
                    new = [x for x in titles if x not in cands]
                    for title, info in cm.file_info(new).items():
                        info["queries"] = [q]
                        info["topic_subcategory"] = sub
                        info["screen_reasons"] = screen(info)
                        cands[title] = info
                    for x in titles:
                        if x in cands and q not in cands[x].get("queries", []):
                            cands[x].setdefault("queries", []).append(q)
                    cands[key] = {"done": True, "hits": len(titles)}
                    cand_path.write_text(json.dumps(cands, indent=1))
                    print(sub, q, len(titles), "hits", len(new), "new", flush=True)
        files = {k: v for k, v in cands.items() if not k.startswith("q::")}
        print(len(files), "files;", sum(1 for v in files.values() if not v["screen_reasons"]), "pass the metadata screen;",
              "next: tools/commons_sheets.py (shortlist, frame-rate probe, thumbnails)")
        return 0
        todo = [v for v in files.values() if not v["screen_reasons"] and "probe" not in v]

        def pr(v):
            try:
                v["probe"] = cm.probe_remote(v["url"])
                fr = Fraction(v["probe"]["r_frame_rate"])
                av = Fraction(v["probe"]["avg_frame_rate"]) if v["probe"].get("avg_frame_rate") not in (None, "0/0") else fr
                if fr not in ALLOWED_FPS:
                    v["screen_reasons"].append(f"frame rate {fr}")
                elif abs(float(av) / float(fr) - 1) > 0.002:
                    v["screen_reasons"].append(f"variable frame rate (avg {float(av):.3f} vs {float(fr):.3f})")
                if v["probe"].get("field_order") not in (None, "progressive", "unknown"):
                    v["screen_reasons"].append(f"interlaced ({v['probe']['field_order']})")
                if v["probe"].get("color_transfer") in ("smpte2084", "arib-std-b67") or v["probe"].get("color_primaries") == "bt2020":
                    v["screen_reasons"].append("HDR / BT.2020")
            except Exception as e:
                v["screen_reasons"].append(f"probe failed: {str(e)[:120]}")
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(pr, todo))
        cand_path.write_text(json.dumps(cands, indent=1))
    files = {k: v for k, v in cands.items() if not k.startswith("q::")}
    ok = sorted((v for v in files.values() if not v["screen_reasons"]), key=lambda v: (v["topic_subcategory"], -(v.get("mbps") or 0)))
    print(len(files), "files,", len(ok), "pass automatic screening")
    sheets = WORK / "sheets"
    sheets.mkdir(exist_ok=True)
    frames_dir = WORK / "frames"
    frames_dir.mkdir(exist_ok=True)

    def grab(i_v):
        i, v = i_v
        d = v["duration"]
        v["review_id"] = f"c{i:03d}"
        v["sample_frames"] = [str(p) for p in cm.grab_frames(v["url"], [d * f for f in (0.1, 0.35, 0.6, 0.85)], frames_dir / v["review_id"], 320)]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(grab, list(enumerate(ok))))
    cand_path.write_text(json.dumps(cands, indent=1))
    per = 8
    for s in range(0, len(ok), per):
        chunk = ok[s:s + per]
        W, H = 320, 180
        im = Image.new("RGB", (4 * W, len(chunk) * (H + 26)), "black")
        dr = ImageDraw.Draw(im)
        for r, v in enumerate(chunk):
            y = r * (H + 26)
            pr = v.get("probe", {})
            dr.text((2, y + 1), f"{v['review_id']} {v['topic_subcategory'][:12]} {v['width']}x{v['height']} {pr.get('r_frame_rate')} "
                    f"{v.get('mbps')}Mbps {v['duration']:.0f}s {v['licence']} | {v['title'][5:70]}", fill="yellow")
            dr.text((2, y + 12), f"by {v['artist'][:60]} | {', '.join(v['categories'][:4])[:110]}", fill="cyan")
            for c, p in enumerate(v.get("sample_frames", [])):
                t = Image.open(p).convert("RGB")
                t.thumbnail((W, H))
                im.paste(t, (c * W, y + 26))
        im.save(sheets / f"sheet_{s // per:03d}.jpg", quality=80)
    print("sheets", (len(ok) + per - 1) // per)
    return 0


if __name__ == "__main__":
    sys.exit(main())
