"""Small shared helpers: paths, hashing, deterministic seeds, subprocess, JSONL."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA = PROJECT_ROOT / "data"
METADATA = PROJECT_ROOT / "metadata"
REPORTS = PROJECT_ROOT / "reports"
CONFIG = PROJECT_ROOT / "config"

FFMPEG = os.environ.get("SN85DS_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("SN85DS_FFPROBE", "ffprobe")


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_seed(*parts: Any) -> int:
    """A 63-bit seed derived from the given parts (stable across runs and machines)."""
    text = "\x1f".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big") >> 1


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run(cmd: list[str], *, timeout: float | None = None, check: bool = True,
        capture: bool = True, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    """Run a command (list form, never through a shell)."""
    return subprocess.run(cmd, input=input_bytes, capture_output=capture, timeout=timeout, check=check)


def cmd_str(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def nice_prefix() -> list[str]:
    """Run heavy media work at the lowest CPU priority: this machine shares its CPU quota."""
    return ["nice", "-n", os.environ.get("SN85DS_NICE", "19")]


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    """Atomically rewrite a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def upsert_jsonl(path: str | Path, row: dict, key: str) -> None:
    """Insert or replace the row whose ``key`` matches (read-modify-write under an exclusive
    file lock, so concurrent tools never lose each other's rows)."""
    import fcntl

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(p.suffix + ".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rows = [r for r in read_jsonl(p) if r.get(key) != row.get(key)]
        rows.append(row)
        rows.sort(key=lambda r: str(r.get(key)))
        write_jsonl(p, rows)


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def chunked(seq: list, n: int) -> Iterator[list]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def even(x: float) -> int:
    """Nearest even integer >= 2."""
    return max(2, int(round(x / 2.0)) * 2)
