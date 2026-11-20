#!/usr/bin/env python3
"""Fetch one representative frame per candidate segment (middle frame) and save a small JPEG
preview under data/work/previews/, so windows can be chosen by eye before full downloads.
Collections: BBB 3D scene folders, Elephants Dream (every N frames), Netflix SDR zips, Netflix y4m."""
from __future__ import annotations
import argparse, io, json, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from PIL import Image
from sn85ds.acquisition.http import RemoteZip, get_bytes, get_range, head, s3_list
from sn85ds.util import DATA, METADATA, read_jsonl

OUT = DATA / "work" / "previews"
XM = "https://s3.amazonaws.com/xiph-media/"


def save_img_bytes(blob: bytes, name: str, ext: str) -> None:
    dst = OUT / f"{name}.jpg"
    if dst.exists():
        return
    with tempfile.NamedTemporaryFile(suffix=ext) as f:
        f.write(blob); f.flush()
        png = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", f.name, "-frames:v", "1", "-vf", "scale=480:-2",
                              "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    Image.open(io.BytesIO(png)).convert("RGB").save(dst, quality=85)


def y4m_frame(url: str, k: int, name: str) -> None:
    if (OUT / f"{name}.jpg").exists():
        return
    hdr = get_range(url, 0, 255)
    line = hdr.split(b"\n", 1)[0]
    tok = dict((t[:1].decode(), t[1:].decode()) for t in line.split()[1:])
    w, h, c = int(tok["W"]), int(tok["H"]), tok.get("C", "420")
    depth = 2 if c.endswith(("p10", "p12")) else 1
    sub = 1.5 if c.startswith("420") else 2.0 if c.startswith("422") else 3.0
    fsize = int(w * h * sub) * depth
    off = len(line) + 1 + k * (6 + fsize)
    blob = get_range(url, off, off + 6 + fsize - 1)[6:]
    pix = {"420": "yuv420p", "422": "yuv422p", "444": "yuv444p"}[c[:3]] + ("10le" if depth == 2 else "")
    png = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{w}x{h}", "-i", "-", "-frames:v", "1",
                          "-vf", "scale=480:-2", "-f", "image2pipe", "-vcodec", "png", "-"], input=blob, capture_output=True, check=True).stdout
    Image.open(io.BytesIO(png)).convert("RGB").save(OUT / f"{name}.jpg", quality=85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", nargs="*", default=["bbb3d", "ed", "netflix", "y4m"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cands = read_jsonl(METADATA / "candidates.jsonl")
    jobs = []
    if "bbb3d" in args.what:
        for c in cands:
            if c["collection"] == "xiph_bbb3d":
                d = c["access"]; n = c["frames"]
                _, files = s3_list(XM, d[len(XM):])
                pngs = sorted(k for k, _ in files if k.endswith(".png"))
                k = pngs[len(pngs) // 2]
                jobs.append(lambda k=k, c=c: save_img_bytes(get_bytes(XM + k), c["candidate_id"], ".png"))
    if "ed" in args.what:
        for n in range(200, 15700, 240):
            jobs.append(lambda n=n: save_img_bytes(get_bytes(f"{XM}media.xiph.org/ED/ED-1080-png/{n:05d}.png"), f"ed_{n:05d}", ".png"))
    if "netflix" in args.what:
        for c in cands:
            if c["collection"] == "netflix_sdr_segments" and c["usable"]:
                def job(c=c):
                    if (OUT / f"{c['candidate_id']}.jpg").exists():
                        return
                    rz = RemoteZip(c["access"]); mem = sorted(rz.members(r"\.j2k$"), key=lambda i: int(re.findall(r"(\d+)\.j2k$", i.filename)[0]))
                    for frac, tag in ((0.5, ""),):
                        i = mem[int(len(mem) * frac)]
                        with tempfile.TemporaryDirectory() as td:
                            r = rz.fetch(i, Path(td) / "f.j2k"); save_img_bytes(Path(r["path"]).read_bytes(), c["candidate_id"] + tag, ".j2k")
                jobs.append(job)
    if "y4m" in args.what:
        for c in cands:
            if c["access"].endswith(".y4m"):
                jobs.append(lambda c=c: y4m_frame(c["access"], c["frames"] // 2, c["candidate_id"]))
    def run(j):
        try: j()
        except Exception as e: print("ERR", e, flush=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, jobs))
    print("previews", len(list(OUT.glob("*.jpg"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
