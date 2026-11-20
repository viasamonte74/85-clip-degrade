"""HTTP acquisition: resumable parallel ranged downloads, remote zip members, S3 listings.

Only plain HTTPS with certificate verification; a generic User-Agent; no credentials.
Every completed file is checksummed; when the publisher ships checksums they are compared.
"""

from __future__ import annotations

import io
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sn85ds.util import sha256_file

UA = {"User-Agent": "sn85ds-dataset/0.1 (licensed open-media collection)"}
TIMEOUT = 120


def _open(req: urllib.request.Request, retries: int = 8):
    """urlopen with retries; 429/503 are honoured (Retry-After, else exponential back-off)."""
    delay = 2.0
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(req, timeout=TIMEOUT)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404, 410, 416):
                raise
            if attempt == retries - 1:
                raise
            wait = delay
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (429, 503):
                ra = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = max(wait, float(ra)) if ra else max(wait, 15.0)
                except ValueError:
                    wait = max(wait, 15.0)
            time.sleep(min(wait, 300.0))
            delay = min(120.0, delay * 2)
    raise RuntimeError("unreachable")


def head(url: str) -> dict:
    with _open(urllib.request.Request(url, method="HEAD", headers=UA)) as r:
        return {k.lower(): v for k, v in r.headers.items()}


class RangeNotSupported(IOError):
    """The server answered a ranged request with the whole resource (HTTP 200)."""


def get_range(url: str, start: int, end: int) -> bytes:
    """Bytes [start, end] inclusive; requires a 206 Partial Content reply."""
    req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={start}-{end}"})
    with _open(req) as r:
        if r.status != 206:
            raise RangeNotSupported(f"{url}: HTTP {r.status} to a range request")
        data = r.read()
    if len(data) != end - start + 1:
        raise IOError(f"{url}: short range read {len(data)} != {end - start + 1}")
    return data


def download_stream(url: str, dest: str | Path, *, expected_sha256: str | None = None) -> dict:
    """One sequential GET (for servers that do not serve byte ranges reliably)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".streaming")
    t0 = time.time()
    n = 0
    with _open(urllib.request.Request(url, headers=UA)) as r, tmp.open("wb") as out:
        while True:
            b = r.read(1 << 22)
            if not b:
                break
            out.write(b)
            n += len(b)
    os.replace(tmp, dest)
    digest = sha256_file(dest)
    if expected_sha256 and digest != expected_sha256:
        raise IOError(f"{dest}: sha256 {digest} != expected {expected_sha256}")
    return {"path": str(dest), "bytes": n, "sha256": digest, "seconds": round(time.time() - t0, 1), "mode": "stream"}


def get_bytes(url: str) -> bytes:
    with _open(urllib.request.Request(url, headers=UA)) as r:
        return r.read()


def download(url: str, dest: str | Path, *, size: int | None = None, connections: int = 4,
             chunk: int = 16 << 20, expected_sha256: str | None = None) -> dict:
    """Download ``url`` to ``dest`` with parallel ranges; resumable at chunk granularity.

    A sidecar ``.parts`` directory holds finished chunks until the file is assembled."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (size is None or dest.stat().st_size == size):
        digest = sha256_file(dest)
        if expected_sha256 and digest != expected_sha256:
            dest.unlink()
        else:
            return {"path": str(dest), "bytes": dest.stat().st_size, "sha256": digest, "resumed": True}
    if size is None:
        size = int(head(url)["content-length"])
    parts = dest.with_name(dest.name + ".parts")
    parts.mkdir(exist_ok=True)
    ranges = [(i, min(size, i + chunk) - 1) for i in range(0, size, chunk)]
    lock = threading.Lock()
    done = {"n": 0}

    def fetch(r: tuple[int, int]) -> None:
        p = parts / f"{r[0]:016d}"
        if p.exists() and p.stat().st_size == r[1] - r[0] + 1:
            return
        data = get_range(url, r[0], r[1])
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        with lock:
            done["n"] += 1

    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=connections) as ex:
            list(ex.map(fetch, ranges))
    except RangeNotSupported:
        for p in parts.iterdir():
            p.unlink()
        parts.rmdir()
        return download_stream(url, dest, expected_sha256=expected_sha256)
    tmp = dest.with_name(dest.name + ".assembling")
    with tmp.open("wb") as out:
        for r in ranges:
            out.write((parts / f"{r[0]:016d}").read_bytes())
    os.replace(tmp, dest)
    for p in parts.iterdir():
        p.unlink()
    parts.rmdir()
    digest = sha256_file(dest)
    if expected_sha256 and digest != expected_sha256:
        raise IOError(f"{dest}: sha256 {digest} != expected {expected_sha256}")
    return {"path": str(dest), "bytes": size, "sha256": digest, "seconds": round(time.time() - t0, 1)}


def download_many(items: list[tuple[str, Path]], *, workers: int = 6, expected: dict[str, str] | None = None) -> list[dict]:
    """Small files (frames) in parallel; skip files already present (and verified when a
    publisher checksum is known)."""
    expected = expected or {}

    def one(item: tuple[str, Path]) -> dict:
        url, dest = item
        dest.parent.mkdir(parents=True, exist_ok=True)
        exp = expected.get(dest.name)
        if dest.exists():
            if exp is None or sha256_file(dest) == exp:
                return {"path": str(dest), "skipped": True}
        data = get_bytes(url)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        if exp is not None:
            got = sha256_file(dest)
            if got != exp:
                dest.unlink()
                raise IOError(f"{dest.name}: sha256 mismatch (publisher {exp}, got {got})")
        return {"path": str(dest), "bytes": len(data)}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, items))


class _RangeFile(io.RawIOBase):
    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, off: int, whence: int = 0) -> int:
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + len(b)) - 1
        data = get_range(self.url, self.pos, end)
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


class RemoteZip:
    """Read a remote zip's directory with range requests and fetch single members."""

    def __init__(self, url: str):
        self.url = url
        self.size = int(head(url)["content-length"])
        self.zf = zipfile.ZipFile(io.BufferedReader(_RangeFile(url, self.size), buffer_size=1 << 20))
        self.infos = {i.filename: i for i in self.zf.infolist()}

    def members(self, pattern: str = r".*") -> list[zipfile.ZipInfo]:
        rx = re.compile(pattern)
        return [i for n, i in sorted(self.infos.items()) if rx.search(n) and not n.endswith("/")]

    def fetch(self, info: zipfile.ZipInfo, dest: Path) -> dict:
        """One member: local header + data in a single range read, CRC-checked."""
        if dest.exists() and dest.stat().st_size == info.file_size:
            return {"path": str(dest), "skipped": True}
        hdr = get_range(self.url, info.header_offset, info.header_offset + 29)
        name_len = int.from_bytes(hdr[26:28], "little")
        extra_len = int.from_bytes(hdr[28:30], "little")
        start = info.header_offset + 30 + name_len + extra_len
        blob = get_range(self.url, start, start + info.compress_size - 1)
        if info.compress_type == zipfile.ZIP_STORED:
            data = blob
        elif info.compress_type == zipfile.ZIP_DEFLATED:
            import zlib
            data = zlib.decompress(blob, -15)
        else:
            raise ValueError(f"unsupported zip compression {info.compress_type}")
        import zlib as _z
        if (_z.crc32(data) & 0xFFFFFFFF) != info.CRC:
            raise IOError(f"{info.filename}: CRC mismatch")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return {"path": str(dest), "bytes": len(data), "crc32": f"{info.CRC:08x}"}


def s3_list(bucket_url: str, prefix: str, *, delimiter: str | None = None, max_pages: int = 50) -> tuple[list[str], list[tuple[str, int]]]:
    """Anonymous ListObjectsV2 on a path-style bucket URL (https://s3.amazonaws.com/<bucket>/)."""
    dirs: list[str] = []
    files: list[tuple[str, int]] = []
    token = None
    for _ in range(max_pages):
        q = {"list-type": "2", "max-keys": "1000", "prefix": prefix}
        if delimiter:
            q["delimiter"] = delimiter
        if token:
            q["continuation-token"] = token
        x = get_bytes(bucket_url + "?" + urllib.parse.urlencode(q)).decode("utf-8")
        dirs += re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", x)
        files += [(k, int(s)) for k, s in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", x, re.S)]
        m = re.search(r"<NextContinuationToken>([^<]+)<", x)
        if not m:
            break
        token = m.group(1)
    return dirs, files
