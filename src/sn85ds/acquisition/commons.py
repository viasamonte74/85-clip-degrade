"""Wikimedia Commons: per-file licence metadata, search, frame sampling and window download.

Every file is reviewed individually: the licence comes from the file page's own metadata
(extmetadata LicenseShortName / LicenseUrl / Artist / Restrictions), never from a category or
a collection. The Commons API is used sequentially with a generic User-Agent and back-off on
'maxlag' / 'cirrussearch-too-busy'. Media come from upload.wikimedia.org; the API's SHA-1 is
checked after download.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "sn85ds-dataset-builder/0.2 (licensed video dataset research; generic client)"

# Commons LicenseShortName -> normalised id; anything not listed is rejected
_LIC = [
    (r"^cc0( 1\.0)?$|^cc-zero$", "CC0-1.0"),
    (r"^public domain$|^pd$|^pdm$|^public domain mark", "PD"),
    (r"^cc by (2\.0|2\.5|3\.0|4\.0)$", "CC-BY-{v}"),
    (r"^cc by-sa (2\.0|2\.5|3\.0|4\.0)$", "CC-BY-SA-{v}"),
]
PORTED = r"^cc by(-sa)? (2\.0|2\.5|3\.0) [a-z]{2,3}(-[a-z]{2})?$"   # national ports: accepted, flagged


def normalise_licence(short: str) -> tuple[str | None, str | None]:
    s = re.sub(r"\s+", " ", (short or "").strip().lower())
    for pat, out in _LIC:
        m = re.match(pat, s)
        if m:
            return out.format(v=m.group(1)) if "{v}" in out else out, None
    m = re.match(PORTED, s)
    if m:
        return f"CC-BY{'-SA' if m.group(1) else ''}-{m.group(2)}", f"ported licence variant '{short}'"
    return None, None


def api(params: dict, retries: int = 8) -> dict:
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    body = urllib.parse.urlencode(params).encode()  # POST: long title lists overflow a GET URL (HTTP 414)
    for attempt in range(retries):
        req = urllib.request.Request(API, data=body, headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            data = json.loads(resp.read())
        except Exception as e:
            wait = min(120, 5 * 2 ** attempt)
            ra = getattr(e, "headers", None) and e.headers.get("Retry-After")
            if ra and str(ra).isdigit():
                wait = max(wait, int(ra))
            print(f"commons api retry in {wait}s: {str(e)[:120]}", flush=True)
            time.sleep(wait)
            continue
        err = (data.get("error") or {}).get("code")
        if err in ("maxlag", "cirrussearch-too-busy", "ratelimited"):
            print(f"commons api {err}; retry", flush=True)
            time.sleep(min(120, 5 * 2 ** attempt))
            continue
        time.sleep(2.0)  # be gentle: at most one request every ~2 s
        if err:
            raise RuntimeError(f"Commons API error {err}: {data['error'].get('info')}")
        return data
    raise RuntimeError("Commons API unavailable")


def search(query: str, limit: int = 200) -> list[str]:
    titles, off = [], 0
    while off < limit:
        d = api({"action": "query", "list": "search", "srsearch": query, "srnamespace": "6", "srlimit": "50", "sroffset": str(off)})
        hits = d.get("query", {}).get("search", [])
        titles += [h["title"] for h in hits]
        if "continue" not in d or not hits:
            break
        off = d["continue"]["sroffset"]
        time.sleep(1.0)
    return titles


def _strip(v: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", v or "")).strip()


def file_info(titles: list[str]) -> dict[str, dict]:
    """Licence, author, size, duration and checksum per file (batches of 40)."""
    out: dict[str, dict] = {}
    for i in range(0, len(titles), 40):
        batch = titles[i:i + 40]
        d = api({"action": "query", "prop": "imageinfo|categories", "titles": "|".join(batch), "cllimit": "max",
                 "iiprop": "url|size|mime|sha1|extmetadata|user|timestamp|metadata", "iiextmetadatalanguage": "en"})
        for p in d.get("query", {}).get("pages", []):
            if not p.get("imageinfo"):
                continue
            ii = p["imageinfo"][0]
            em = ii.get("extmetadata", {})
            g = lambda k: _strip((em.get(k) or {}).get("value"))  # noqa: E731
            meta = {m["name"]: m["value"] for m in (ii.get("metadata") or []) if isinstance(m, dict) and "name" in m}
            dur = ii.get("duration") or meta.get("playtime_seconds") or meta.get("length")
            lic, lic_note = normalise_licence(g("LicenseShortName"))
            out[p["title"]] = {
                "title": p["title"], "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_")),
                "url": ii["url"], "mime": ii.get("mime"), "width": ii.get("width"), "height": ii.get("height"), "bytes": ii.get("size"),
                "duration": float(dur) if dur else None, "sha1": ii.get("sha1"), "uploader": ii.get("user"), "uploaded": ii.get("timestamp"),
                "licence_short": g("LicenseShortName"), "licence": lic, "licence_note": lic_note, "licence_url": g("LicenseUrl"),
                "usage_terms": g("UsageTerms"), "artist": g("Artist"), "credit": g("Credit"), "attribution_required": g("AttributionRequired"),
                "restrictions": g("Restrictions"), "copyrighted": g("Copyrighted"), "description": g("ImageDescription")[:500],
                "date": g("DateTimeOriginal") or g("DateTime"), "categories": [c["title"].split(":", 1)[1] for c in p.get("categories", [])],
            }
        time.sleep(1.0)
    return out


BAD_CATEGORY = re.compile(r"(computer[- ]generated|animation|animated|screenshot|screencast|video game|ai[- ]generated|"
                          r"generated by|slideshow|time[- ]?lapse|hyperlapse|stop[- ]motion|televis|film trailer|"
                          r"music video|concert|logo|title card|archival|newsreel|propaganda|rendered|3d render|simulation|"
                          r"visualization|visualisation|nasa svs|scientific visualization|infographic)", re.I)


def probe_remote(url: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-user_agent", UA, "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,field_order,color_space,color_transfer,color_primaries,color_range,bit_rate,nb_frames:format=duration,bit_rate",
                          "-of", "json", url], capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-500:])
    d = json.loads(out.stdout)
    s = d["streams"][0]
    s["format_duration"] = float(d["format"].get("duration") or 0)
    s["format_bit_rate"] = int(d["format"].get("bit_rate") or 0)
    return s


def grab_frames(url: str, times: list[float], dest_prefix: Path, width: int = 480) -> list[Path]:
    """One small JPEG per timestamp (input seeking over HTTP ranges)."""
    paths = []
    for t in times:
        p = dest_prefix.with_name(f"{dest_prefix.name}_{int(t * 10):05d}.jpg")
        if not p.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-user_agent", UA, "-ss", f"{t:.3f}", "-i", url, "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "4", "-y", str(p)], capture_output=True, timeout=300)
        if p.exists():
            paths.append(p)
    return paths


def download_file(url: str, dest: Path, sha1: str | None) -> dict:
    """Whole original file (resumable ranged download), verified against the API's SHA-1."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest.exists() and sha1 and _sha1(dest) == sha1):
        tmp = dest.with_suffix(dest.suffix + ".part")
        _stream(url.split("?")[0], tmp)  # one sequential stream: Wikimedia rate-limits parallel ranges
        tmp.replace(dest)
    got = _sha1(dest)
    if sha1 and got != sha1:
        dest.unlink()
        raise IOError(f"SHA-1 mismatch for {url}: {got} != {sha1}")
    return {"sha1": got, "sha1_verified": bool(sha1), "bytes": dest.stat().st_size}


def _stream(url: str, dest: Path) -> None:
    """Single GET with at most one retry: on HTTP 429 the caller defers the file to a later pass."""
    from sn85ds.acquisition.http import UA as HTTP_UA, _open
    part = dest.with_name(dest.name + ".streaming")
    with _open(urllib.request.Request(url, headers=HTTP_UA), retries=2) as r, part.open("wb") as out:
        while True:
            b = r.read(1 << 22)
            if not b:
                break
            out.write(b)
    part.replace(dest)


def _sha1(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def fetch_window(clip: dict, base: Path) -> dict:
    """download_sources hook: fetch the reviewed Commons file whole (SHA-1 checked); the reference
    step selects the frame window (clip['first'], clip['frames']) by decoded frame index."""
    ext = Path(urllib.parse.urlparse(clip["file_url"]).path).suffix.lower()
    dest = base / f"source{ext}"
    cached = Path(__file__).resolve().parents[3] / "data" / "work" / "commons" / "files" / f"{clip['id'].split('_')[2].rstrip('p')}{ext}"
    if not dest.exists() and cached.exists():
        import os
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(cached, dest)  # reuse the copy downloaded during selection (SHA-1 re-checked below)
    info = download_file(clip["file_url"], dest, clip.get("sha1"))
    return {"urls": [clip["file_url"]], "files": [dest], "publisher_checksums": "Commons API SHA-1 verified" if info["sha1_verified"] else "none",
            "commons": {"page": clip["commons_page"], "sha1": info["sha1"], "licence_short": clip.get("licence_short"),
                        "artist": clip.get("artist"), "window_frames": [clip["first"], clip["first"] + clip["frames"]]}}
