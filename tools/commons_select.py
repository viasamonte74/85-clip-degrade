#!/usr/bin/env python3
"""Turn reviewed Wikimedia Commons files into planned clips.

Input: config/commons_review.yaml — one entry per reviewed file (review_id from the sheets):
  decision (accept / reject), reasons, subcategory, orientation, duration_s, optional group,
  optional start_s (preferred window start) and notes.
For every accepted file: download the original (SHA-1 from the API verified), probe it, detect
cuts on decoded thumbnails, and choose a window of the requested duration inside one shot
(away from fades/black, preferring start_s). Writes data/work/commons/windows/<id>.jpg (first /
middle / last frame of the window) for a final check, and appends kind=commons_window clips to
config/phase_b_clips.yaml. Rejections are recorded in metadata/commons_review.jsonl with reasons.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import yaml  # noqa: E402

from sn85ds.acquisition import commons as cm  # noqa: E402
from sn85ds.media import probe  # noqa: E402
from sn85ds.util import DATA, METADATA, upsert_jsonl, utc_now  # noqa: E402
from sn85ds.validation.shots import detect_cuts, shots, thumbnails  # noqa: E402

WORK = DATA / "work" / "commons"
PLAN = ROOT / "config" / "phase_b_clips.yaml"
OK_FPS = {"24": "24", "25": "25", "30": "30", "60": "60", "30000/1001": "30000/1001", "60000/1001": "60000/1001", "24000/1001": "24000/1001"}


def detail_psnr(src: Path, vi, orientation: str) -> list[float]:
    """Detail check on the 1080p-downscaled frame (20/50/80 % of the file): PSNR between the frame and
    its 2x area-down / bicubic-up copy, measured on the 95th-percentile 32x32 block (the sharpest
    regions, so shallow depth of field does not count against a file). Calibrated on the pilot
    references: genuine footage 27-44 dB, the same frames upscaled from 540p 37-56 dB; > 45 dB
    is rejected, 40-45 dB is flagged for a visual check."""
    import cv2
    from sn85ds.acquisition.references import aspect_crop, target_size
    tw, th_ = target_size(orientation)
    cw, ch, x, y = aspect_crop(vi.width, vi.height, orientation)
    out = []
    for f in (0.2, 0.5, 0.8):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{vi.duration_s * f:.2f}", "-i", str(src), "-frames:v", "1",
                              "-vf", f"crop={cw}:{ch}:{x}:{y},scale={tw}:{th_}:flags=spline,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        if len(raw) != tw * th_:
            continue
        a = np.frombuffer(raw, np.uint8).reshape(th_, tw).astype(np.float32)
        d = cv2.resize(a, (tw // 2, th_ // 2), interpolation=cv2.INTER_AREA)
        u = cv2.resize(d, (tw, th_), interpolation=cv2.INTER_CUBIC)
        e = ((a - u) ** 2)[: th_ // 32 * 32, : tw // 32 * 32].reshape(th_ // 32, 32, tw // 32, 32).mean(axis=(1, 3))
        out.append(round(float(10 * np.log10(255.0 ** 2 / max(float(np.percentile(e, 95)), 1e-6))), 2))  # sharpest 5 % of blocks
    return out or [99.0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default=str(ROOT / "config" / "commons_review.yaml"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    review = yaml.safe_load(Path(args.review).read_text())["files"]
    cands = {v["review_id"]: v for v in json.loads((WORK / "shortlist.json").read_text())}
    planned = {c["id"] for c in yaml.safe_load(PLAN.read_text())["clips"]}
    new_clips = []
    pending = [rid for rid, r in review.items() if r["decision"] == "accept"
               and not (WORK / "files" / f"{rid}{Path(cands[rid]['url'].split('?')[0]).suffix.lower()}").exists()
               and f"cam_wc_{rid}" not in "".join(planned)]
    if pending:  # one tiny probe request: if Wikimedia rate-limits this client, defer the whole pass
        import urllib.request
        from sn85ds.acquisition.http import UA as HTTP_UA
        try:
            req = urllib.request.Request(cands[pending[0]]["url"].split("?")[0], headers={**HTTP_UA, "Range": "bytes=0-0"})
            urllib.request.urlopen(req, timeout=30).read()
        except Exception as e:
            if getattr(e, "code", None) == 429:
                print(utc_now(), "rate-limited (HTTP 429) - pass deferred,", len(pending), "files pending", flush=True)
                return 0
    for rid, r in review.items():
        info = cands[rid]
        row = {"review_id": rid, "title": info["title"], "page": info["page"], "licence": info["licence"], "licence_short": info["licence_short"],
               "artist": info["artist"], "decision": r["decision"], "reasons": r.get("reasons"), "reviewed_at": utc_now(),
               "restrictions": info.get("restrictions"), "categories": info["categories"][:12]}
        if r["decision"] != "accept":
            upsert_jsonl(METADATA / "commons_review.jsonl", row, "review_id")
            continue
        cid = f"cam_wc_{rid}" + ("p" if r["orientation"] == "portrait" else "")
        if cid in planned:
            continue
        ext = Path(info["url"].split("?")[0]).suffix.lower()
        src = WORK / "files" / f"{rid}{ext}"
        try:
            dl = cm.download_file(info["url"], src, info["sha1"])
        except Exception as e:  # e.g. HTTP 429 from Wikimedia's edge: leave for a later pass, never hammer
            print(rid, "download deferred:", str(e)[:160], flush=True)
            continue
        vi = probe(src)
        fps = str(Fraction(vi.fps))
        if fps not in OK_FPS:
            row.update(decision="reject", reasons=f"frame rate {fps} after download")
            upsert_jsonl(METADATA / "commons_review.jsonl", row, "review_id")
            continue
        if vi.field_order not in ("progressive", "unknown", "", None) or vi.color_transfer in ("smpte2084", "arib-std-b67") or vi.color_primaries == "bt2020":
            row.update(decision="reject", reasons=f"scan/colour: field {vi.field_order}, trc {vi.color_transfer}, primaries {vi.color_primaries}")
            upsert_jsonl(METADATA / "commons_review.jsonl", row, "review_id")
            continue
        detail = detail_psnr(src, vi, r["orientation"])
        row["detail_psnr_db"] = detail
        row["soft_flag"] = min(detail) > 40.0
        if min(detail) > 45.0:
            row.update(decision="reject", reasons=f"no genuine 1080p detail (sharpest-block 2x down-up PSNR {detail} dB > 45): likely upscaled or very soft")
            upsert_jsonl(METADATA / "commons_review.jsonl", row, "review_id")
            print(rid, "rejected: soft/upscaled", detail)
            continue
        # only the first 60 s are analysed (and the window lies there): long 4K files would otherwise be
        # decoded in full for cut detection and again up to the window during reference preparation
        th = thumbnails(src, max_frames=int(60 * float(Fraction(fps))))
        cuts = detect_cuts(th)
        runs = shots(len(th), cuts)
        lum = th.reshape(len(th), -1).mean(axis=1)
        want = int(round(float(r["duration_s"]) * float(Fraction(fps))))
        margin = int(round(0.5 * float(Fraction(fps))))
        best = None
        for a, b in runs:
            a2, b2 = a + margin, b - margin
            if b2 - a2 < want:
                continue
            pref = int(round(float(r.get("start_s", 0)) * float(Fraction(fps))))
            s0 = min(max(a2, pref), b2 - want)
            # avoid near-black windows (fades): require the window's darkest frame > 6 % of the mean level
            seg = lum[s0:s0 + want]
            if seg.min() < 0.06 * max(1.0, lum.mean()) or seg.min() < 8:
                continue
            score = (abs(s0 - pref), -(b2 - a2))
            if best is None or score < best[0]:
                best = (score, s0)
        if best is None:
            row.update(decision="reject", reasons=f"no continuous shot of {want} frames (shots {[(a, b) for a, b in runs][:8]})")
            upsert_jsonl(METADATA / "commons_review.jsonl", row, "review_id")
            print(rid, "no window")
            continue
        first = best[1]
        sheet = WORK / "windows" / f"{cid}.jpg"
        sheet.parent.mkdir(exist_ok=True)
        idx = [first, first + want // 2, first + want - 1]
        sel = "+".join(f"eq(n\\,{k})" for k in idx)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"select='{sel}',scale=640:-2,tile=3x1", "-fps_mode", "passthrough",
                        "-frames:v", "1", str(sheet)], check=False)
        clip = {"id": cid, "category": "real_camera", "subcategory": r["subcategory"], "collection": "wikimedia_commons",
                "group": r.get("group") or f"wc_{rid}", "kind": "commons_window", "file_url": info["url"].split("?")[0], "sha1": info["sha1"],
                "commons_page": info["page"], "licence": info["licence"], "licence_short": info["licence_short"], "licence_url": info["licence_url"],
                "artist": info["artist"][:200], "title": info["title"], "first": int(first), "frames": int(want), "fps": OK_FPS[fps],
                "orientation": r["orientation"], "master_size": [vi.width, vi.height], "master_codec": vi.codec,
                "master_colour": [vi.color_space, vi.color_range, vi.color_primaries, vi.color_transfer]}
        if r.get("privacy_flag"):
            clip["privacy_flag"] = True
        if info.get("licence_note"):
            clip["licence_note"] = info["licence_note"]
        new_clips.append(clip)
        row.update(clip_id=cid, window=[first, first + want], fps=fps, master=[vi.width, vi.height, vi.codec, round(vi.bit_rate / 1e6, 1) if vi.bit_rate else None],
                   shots=[list(x) for x in runs][:20], sha1_verified=dl["sha1_verified"])
        upsert_jsonl(METADATA / "commons_review.jsonl", row, "review_id")
        print(rid, cid, "window", first, want, fps, f"{vi.width}x{vi.height}", flush=True)
    if new_clips and not args.dry_run:
        lines = []
        if "Wikimedia Commons (reviewed" not in PLAN.read_text():
            lines += ["", "  # ================================================================== real camera: Wikimedia Commons (reviewed file by file)",
                      "  # tools/commons_select.py from config/commons_review.yaml; window chosen inside one shot"]
        lines += ["  - " + yaml.safe_dump(c, default_flow_style=True, sort_keys=False, width=1000).strip() for c in new_clips]
        with PLAN.open("a") as f:
            f.write("\n".join(lines) + "\n")
    print(len(new_clips), "clips planned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
