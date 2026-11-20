#!/usr/bin/env python3
"""Download the master frames of every clip in a plan (kinds: frames_http, zip_j2k, y4m_range,
ftp_mov_j2k, commons_window).

Files go to data/downloads/<clip_id>/frames/ (y4m ranges to data/downloads/<clip_id>/clip.y4m);
data/downloads/<clip_id>/manifest.json records every URL, byte size and sha256, and whether a
publisher checksum was available and matched. Resumable; --dry-run lists what would be fetched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from sn85ds.acquisition.http import RemoteZip, download_many, get_bytes, get_range, head  # noqa: E402
from sn85ds.util import DATA, sha256_file, utc_now  # noqa: E402

PUBLISHER_SUMS = {
    # collection -> (url of a sha256 list, path prefix inside it)
    "xiph_sintel4k": ("https://s3.amazonaws.com/xiph-media/media.xiph.org/sintel/SHA256SUMS.txt", "sintel-4k-png/"),
}


def publisher_sums(collection: str) -> dict[str, str]:
    if collection not in PUBLISHER_SUMS:
        return {}
    url, prefix = PUBLISHER_SUMS[collection]
    try:
        text = get_bytes(url).decode("utf-8", "replace")
    except Exception:
        return {}
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*").startswith(prefix):
            out[Path(parts[1]).name] = parts[0]
    return out


def fetch_frames_http(clip: dict, dest: Path, workers: int) -> dict:
    sums = publisher_sums(clip["collection"])
    items = []
    for n in range(clip["first"], clip["first"] + clip["frames"]):
        url = clip["url_pattern"].format(n=n)
        items.append((url, dest / Path(url).name))
    download_many(items, workers=workers, expected=sums)
    files = [p for _, p in items]
    return {"urls": [u for u, _ in items], "files": files,
            "publisher_checksums": "verified" if sums and all(p.name in sums for p in files) else "not published for these files"}


def fetch_zip(clip: dict, dest: Path, workers: int) -> dict:
    rz = RemoteZip(clip["zip_url"])
    members = rz.members(r"\.j2k$")
    members.sort(key=lambda i: int(re.findall(r"(\d+)\.j2k$", i.filename)[0]))
    sel = members[clip.get("skip", 0): clip.get("skip", 0) + clip["frames"]]
    if len(sel) < clip["frames"]:
        raise SystemExit(f"{clip['id']}: zip has only {len(members)} frames")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda i: rz.fetch(i, dest / Path(i.filename).name), sel))
    return {"urls": [clip["zip_url"] + "#" + i.filename for i in sel], "files": [Path(r["path"]) for r in res],
            "publisher_checksums": "zip CRC-32 verified per member", "zip_members_total": len(members)}


def fetch_y4m(clip: dict, dest_file: Path, workers: int) -> dict:
    url = clip["y4m_url"]
    hdr = get_range(url, 0, 255)
    line = hdr.split(b"\n", 1)[0]
    header_len = len(line) + 1
    tok = dict((t[:1].decode(), t[1:].decode()) for t in line.split()[1:])
    w, h = int(tok["W"]), int(tok["H"])
    chroma = tok.get("C", "420")
    depth = 2 if chroma.endswith(("p10", "p12", "p16")) else 1
    fsize = int(w * h * {"420": 1.5, "422": 2.0, "444": 3.0}[chroma[:3]]) * depth
    step = 6 + fsize
    size = int(head(url)["content-length"])
    total = (size - header_len) // step
    first, n = clip["first"], clip["frames"]
    if first + n > total:
        raise SystemExit(f"{clip['id']}: y4m has {total} frames")
    parts = dest_file.with_name("y4m_parts")
    parts.mkdir(parents=True, exist_ok=True)

    def one(k: int) -> None:
        p = parts / f"{k:06d}.raw"
        if p.exists() and p.stat().st_size == fsize:
            return
        off = header_len + k * step
        blob = get_range(url, off, off + step - 1)
        if blob[:6] != b"FRAME\n":
            raise IOError(f"frame {k}: missing FRAME marker")
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(blob[6:])
        tmp.replace(p)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, range(first, first + n)))
    with dest_file.open("wb") as out:
        out.write(line + b"\n")
        for k in range(first, first + n):
            out.write(b"FRAME\n")
            out.write((parts / f"{k:06d}.raw").read_bytes())
    for p in parts.iterdir():
        p.unlink()
    parts.rmdir()
    return {"urls": [f"{url}#frames={first}-{first + n - 1}"], "files": [dest_file], "y4m_header": line.decode(),
            "source_frames_total": total, "publisher_checksums": "none published; FRAME markers checked"}


def fetch_ftp_mov(clip: dict, dest: Path, workers: int) -> dict:
    """SVT Open Content: ranged FTP reads of single JPEG 2000 samples from the publisher's
    QuickTime master. ``step`` > 1 keeps every step-th source frame (50p -> 25p by taking
    source frames first, first+2, ...; no interpolation). Output frames are numbered 0..n-1."""
    from sn85ds.acquisition.ftp import FtpRange, find_top_level, parse_video_track

    r = FtpRange(clip["ftp_host"], clip["ftp_path"])
    cache = DATA / "work" / "moov_cache" / (Path(clip["ftp_path"]).name + ".moov")
    if cache.exists():
        moov = cache.read_bytes()
    else:
        off, size = find_top_level(r, b"moov")
        moov = r.read(off, size)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(moov)
    tr = parse_video_track(moov)
    step, first, n = int(clip.get("step", 1)), int(clip["first"]), int(clip["frames"])
    src = [first + step * k for k in range(n)]
    if src[-1] >= tr.frames:
        raise SystemExit(f"{clip['id']}: master has {tr.frames} samples")
    if len(set(tr.sample_durations)) != 1:
        raise SystemExit(f"{clip['id']}: variable sample durations in master")
    dest.mkdir(parents=True, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor

    def one(kv: tuple[int, int]) -> Path:
        k, s = kv
        p = dest / f"{k:06d}.jp2"
        if p.exists() and p.stat().st_size == tr.sample_sizes[s]:
            return p
        blob = r.read(tr.sample_offsets[s], tr.sample_sizes[s])
        if blob[4:8] != b"jP  ":
            raise IOError(f"sample {s}: not a JP2 file")
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(p)
        return p

    with ThreadPoolExecutor(max_workers=workers) as ex:
        files = list(ex.map(one, enumerate(src)))
    from fractions import Fraction
    master_fps = str(Fraction(tr.timescale, tr.sample_durations[0]))
    return {"urls": [f"ftp://{clip['ftp_host']}{clip['ftp_path']}#samples={src[0]}-{src[-1]}:step{step}"], "files": files,
            "source_samples": src, "master_samples_total": tr.frames, "master_rate": master_fps, "temporal_step": step,
            "publisher_checksums": "whole-file sums only (sha256Sum.sha256); each sample stored byte-exact with its sha256 and JP2 signature checked"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(ROOT / "config" / "pilot_clips.yaml"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    plan = yaml.safe_load(Path(args.plan).read_text())
    for clip in plan["clips"]:
        if clip["kind"] not in ("frames_http", "zip_j2k", "y4m_range", "ftp_mov_j2k", "commons_window") or (args.only and clip["id"] not in args.only):
            continue
        base = DATA / "downloads" / clip["id"]
        man = base / "manifest.json"
        if man.exists() and json.loads(man.read_text()).get("complete"):
            print("skip", clip["id"])
            continue
        if args.dry_run:
            print("would fetch", clip["id"], clip["kind"], clip["frames"], "frames")
            continue
        t0 = time.time()
        if clip["kind"] == "frames_http":
            info = fetch_frames_http(clip, base / "frames", args.workers)
        elif clip["kind"] == "zip_j2k":
            info = fetch_zip(clip, base / "frames", args.workers)
        elif clip["kind"] == "ftp_mov_j2k":
            info = fetch_ftp_mov(clip, base / "frames", min(args.workers, 3))  # server caps connections per address
        elif clip["kind"] == "commons_window":
            from sn85ds.acquisition.commons import fetch_window
            info = fetch_window(clip, base)
        else:
            info = fetch_y4m(clip, base / "clip.y4m", args.workers)
        files = info.pop("files")
        sizes = sum(f.stat().st_size for f in files)
        manifest = {"clip_id": clip["id"], "collection": clip["collection"], "kind": clip["kind"], "complete": True,
                    "downloaded_at": utc_now(), "seconds": round(time.time() - t0, 1), "bytes": sizes,
                    "files": [{"name": f.name, "bytes": f.stat().st_size, "sha256": sha256_file(f)} for f in files], **info}
        man.write_text(json.dumps(manifest, indent=1))
        print(clip["id"], len(files), "files", round(sizes / 1e9, 2), "GB", manifest["seconds"], "s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
