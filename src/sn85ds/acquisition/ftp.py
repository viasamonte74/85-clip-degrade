"""Ranged reads over anonymous FTP and QuickTime/MP4 sample tables.

Used for the SVT Open Content suite (ftp://svtopencontent.svt.se), whose masters are single
25-66 GB QuickTime files of lossless JPEG 2000 frames. Instead of downloading a whole file,
the sample table (moov/stbl) is parsed from ranged reads and only the frames a clip needs
are fetched, each as one ranged read (FTP REST + RETR, aborted after the wanted bytes).
"""

from __future__ import annotations

import ftplib
import random
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path


class FtpRange:
    """Read byte ranges of one file on an anonymous FTP server (one connection per call)."""

    def __init__(self, host: str, path: str, timeout: float = 60.0):
        self.host, self.path, self.timeout = host, path, timeout
        self._size: int | None = None

    def _connect(self) -> ftplib.FTP:
        f = ftplib.FTP(self.host, timeout=self.timeout)
        f.login()
        f.voidcmd("TYPE I")
        return f

    @property
    def size(self) -> int:
        if self._size is None:
            f = self._connect()
            try:
                self._size = int(f.size(self.path))
            finally:
                f.close()
        return self._size

    def read(self, offset: int, length: int, retries: int = 14) -> bytes:
        last: Exception | None = None
        for attempt in range(retries):
            f = None
            try:
                f = self._connect()
                conn = f.transfercmd(f"RETR {self.path}", rest=offset)
                conn.settimeout(self.timeout)
                buf = bytearray()
                while len(buf) < length:
                    chunk = conn.recv(min(1 << 20, length - len(buf)))
                    if not chunk:
                        break
                    buf += chunk
                conn.close()
                if len(buf) != length:
                    raise IOError(f"short read {len(buf)}/{length} at {offset}")
                return bytes(buf)
            except (OSError, EOFError, ftplib.Error, socket.timeout) as e:
                last = e
                # '421 too many connections': the server caps connections per address; back off longer
                time.sleep(min(90, 2 ** attempt) + (15 if "421" in str(e) else 0) + random.uniform(0, 3))
            finally:
                if f is not None:
                    try:
                        f.close()  # closing the control connection aborts the transfer server-side
                    except Exception:
                        pass
        raise IOError(f"ftp read failed after {retries} attempts: {last}")


# ---------------------------------------------------------------- QuickTime / ISO-BMFF tables

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"}


def _atoms(buf: bytes, start: int = 0, end: int | None = None):
    end = len(buf) if end is None else end
    p = start
    while p + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[p:p + 8])
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", buf[p + 8:p + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - p
        yield typ, p, hdr, size
        p += size


def find_top_level(reader: FtpRange, want: bytes = b"moov") -> tuple[int, int]:
    """Walk top-level atoms with 16-byte header reads; return (offset, size) of ``want``."""
    off, total = 0, reader.size
    while off < total:
        h = reader.read(off, 16)
        size, typ = struct.unpack(">I4s", h[:8])
        if size == 1:
            size = struct.unpack(">Q", h[8:16])[0]
        elif size == 0:
            size = total - off
        if typ == want:
            return off, size
        off += size
    raise IOError(f"no {want!r} atom")


@dataclass
class VideoTrack:
    timescale: int
    sample_offsets: list[int]
    sample_sizes: list[int]
    sample_durations: list[int]
    codec: str

    @property
    def frames(self) -> int:
        return len(self.sample_sizes)


def parse_video_track(moov: bytes) -> VideoTrack:
    """Sample offsets/sizes of the first video track of a moov atom."""
    for typ, p, hdr, size in _atoms(moov):
        if typ != b"moov":
            continue
        for ttyp, tp, thdr, tsize in _atoms(moov, p + hdr, p + size):
            if ttyp != b"trak":
                continue
            tab = _collect(moov, tp + thdr, tp + tsize)
            if tab.get(b"hdlr") is None or tab[b"hdlr"][8:12] != b"vide":
                continue
            mdhd = tab[b"mdhd"]
            ver = mdhd[0]
            timescale = struct.unpack(">I", mdhd[12:16] if ver == 0 else mdhd[20:24])[0]
            stsd = tab[b"stsd"]
            codec = stsd[12:16].decode("latin-1")
            stsz = tab[b"stsz"]
            fixed, count = struct.unpack(">II", stsz[4:12])
            sizes = [fixed] * count if fixed else list(struct.unpack(f">{count}I", stsz[12:12 + 4 * count]))
            if b"co64" in tab:
                n = struct.unpack(">I", tab[b"co64"][4:8])[0]
                chunks = list(struct.unpack(f">{n}Q", tab[b"co64"][8:8 + 8 * n]))
            else:
                n = struct.unpack(">I", tab[b"stco"][4:8])[0]
                chunks = list(struct.unpack(f">{n}I", tab[b"stco"][8:8 + 4 * n]))
            stsc = tab[b"stsc"]
            n = struct.unpack(">I", stsc[4:8])[0]
            runs = [struct.unpack(">III", stsc[8 + 12 * i:20 + 12 * i]) for i in range(n)]
            offsets: list[int] = []
            s = 0
            for ci, chunk_off in enumerate(chunks, start=1):
                per = next(r[1] for r in reversed(runs) if r[0] <= ci)
                o = chunk_off
                for _ in range(per):
                    if s >= count:
                        break
                    offsets.append(o)
                    o += sizes[s]
                    s += 1
            stts = tab[b"stts"]
            n = struct.unpack(">I", stts[4:8])[0]
            durs: list[int] = []
            for i in range(n):
                c, d = struct.unpack(">II", stts[8 + 8 * i:16 + 8 * i])
                durs += [d] * c
            if len(offsets) != count:
                raise IOError(f"sample table mismatch: {len(offsets)} offsets for {count} samples")
            return VideoTrack(timescale, offsets, sizes, durs[:count], codec)
    raise IOError("no video track")


def _collect(buf: bytes, start: int, end: int) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    for typ, p, hdr, size in _atoms(buf, start, end):
        if typ in CONTAINERS:
            for k, v in _collect(buf, p + hdr, p + size).items():
                out.setdefault(k, v)  # first occurrence wins (mdia/hdlr before minf/hdlr)
        elif typ not in out:
            out[typ] = buf[p + hdr:p + size]
    return out


def j2k_codestream(sample: bytes) -> bytes:
    """Return the raw JPEG 2000 codestream of a QuickTime 'mjp2' sample (strip a jp2c box)."""
    if sample[:2] == b"\xff\x4f":
        return sample
    for typ, p, hdr, size in _atoms(sample):
        if typ == b"jp2c":
            return sample[p + hdr:p + size]
    i = sample.find(b"\xff\x4f\xff\x51")
    if i < 0:
        raise IOError("no JPEG 2000 codestream in sample")
    return sample[i:]


def fetch_mov_frames(reader: FtpRange, track: VideoTrack, indices: list[int], dest: Path, workers: int = 4) -> list[Path]:
    """Fetch the given samples byte for byte, named by sample index (resumable).

    SVT's 'mjp2' samples are complete JP2 files (signature, ftyp, jp2h with ihdr/colr, jp2c);
    they are stored unchanged as .jp2 so that decoding matches the publisher's QuickTime file
    exactly (stripping the boxes changes how decoders interpret the components)."""
    from concurrent.futures import ThreadPoolExecutor

    dest.mkdir(parents=True, exist_ok=True)

    def one(k: int) -> Path:
        p = dest / f"{k:06d}.jp2"
        if p.exists() and p.stat().st_size == track.sample_sizes[k]:
            return p
        blob = reader.read(track.sample_offsets[k], track.sample_sizes[k])
        if blob[4:8] != b"jP  " and blob[:2] != b"\xff\x4f":
            raise IOError(f"sample {k}: not a JPEG 2000 file")
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(p)
        return p

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, indices))
