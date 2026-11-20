"""Procedural, licence-clean content for screen scenes (all generated here: CC0).

Numbers, dates, names, log lines and prose come from a seeded generator; the only
'real' text used is this project's own source code (MIT, authored for this project),
shown in the code-editor scenes.
"""

from __future__ import annotations

import html
import keyword
import re
from pathlib import Path

import numpy as np

WORDS = ("data frame signal model input output vector buffer stream packet sample index range value matrix "
         "kernel filter channel volume region cluster queue thread process window record table column report "
         "metric budget forecast revenue margin quarter region north south east west target actual delta "
         "growth review status pending approved shipped invoice ledger account balance transfer schedule "
         "station platform route segment harbor bridge garden river valley summit forest meadow lantern "
         "copper silver amber violet cobalt crimson indigo saffron granite marble cedar maple willow").split()
FIRST = "Ada Bram Cleo Dara Eli Faye Gus Hana Ivo Juno Kai Lena Milo Nia Omar Pia Quin Rhea Sami Tova Uri Vera Wren Yara Zane".split()
LAST = "Aalto Berg Costa Dahl Eklund Ferro Garcia Holm Ito Janssen Kowal Lind Moreau Nakamura Okafor Petrov Quist Rossi Silva Tanaka".split()
LEVELS = [("INFO", 0.62), ("DEBUG", 0.2), ("WARN", 0.12), ("ERROR", 0.06)]


def sentence(rng: np.random.Generator, lo: int = 6, hi: int = 18) -> str:
    n = int(rng.integers(lo, hi))
    w = [WORDS[int(i)] for i in rng.integers(0, len(WORDS), n)]
    w[0] = w[0].capitalize()
    return " ".join(w) + rng.choice([".", ".", ".", ";", ":"])


def paragraph(rng: np.random.Generator) -> str:
    return " ".join(sentence(rng) for _ in range(int(rng.integers(3, 7))))


def name(rng: np.random.Generator) -> str:
    return f"{FIRST[int(rng.integers(len(FIRST)))]} {LAST[int(rng.integers(len(LAST)))]}"


def log_line(rng: np.random.Generator, t0: float, i: int) -> dict:
    lv = rng.choice([l for l, _ in LEVELS], p=[p for _, p in LEVELS])
    ts = t0 + i * float(rng.uniform(0.002, 0.4))
    hh, mm, ss = int(ts // 3600) % 24, int(ts // 60) % 60, ts % 60
    comp = rng.choice(["scheduler", "ingest", "encoder", "auth", "cache", "worker", "router", "storage"])
    kind = rng.random()
    if kind < 0.25:
        msg = f"processed {int(rng.integers(1, 99999))} records in {rng.uniform(0.1, 999):.1f} ms (batch {int(rng.integers(1, 9999))})"
    elif kind < 0.45:
        msg = f"GET /api/v{int(rng.integers(1, 4))}/{rng.choice(WORDS)}/{int(rng.integers(1, 99999))} -> {rng.choice([200, 200, 200, 201, 204, 304, 404, 500])} {rng.uniform(0.2, 950):.1f}ms"
    elif kind < 0.6:
        msg = f"checksum {rng.bytes(16).hex()} ok; size={int(rng.integers(1, 2**31))}"
    else:
        msg = sentence(rng, 4, 11).lower()
    return {"ts": f"2026-11-{int(rng.integers(1, 28)):02d} {hh:02d}:{mm:02d}:{ss:06.3f}", "level": str(lv), "comp": str(comp), "msg": msg}


# --- code: this project's own sources, tokenised for highlighting -----------------------

_PY_TOKEN = re.compile(
    r"(?P<comment>#[^\n]*)|(?P<string>\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*')"
    r"|(?P<number>\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|(?P<name>[A-Za-z_][A-Za-z_0-9]*)|(?P<op>[^\sA-Za-z_0-9])"
)
_BUILTINS = {"print", "len", "range", "int", "float", "str", "dict", "list", "tuple", "set", "min", "max", "sum", "open",
             "isinstance", "enumerate", "zip", "sorted", "round", "abs", "super", "type", "bool", "any", "all"}


def own_source_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted(p for p in root.rglob("*.py") if p.stat().st_size > 1500)


def highlight_python(src: str) -> list[str]:
    """Return one HTML string per source line with <span class=...> tokens."""
    out_lines: list[str] = [""]
    pos = 0
    for m in _PY_TOKEN.finditer(src):
        if m.start() > pos:
            gap = src[pos:m.start()]
            for k, part in enumerate(gap.split("\n")):
                if k:
                    out_lines.append("")
                out_lines[-1] += html.escape(part)
        kind = m.lastgroup
        text = m.group(0)
        cls = kind
        if kind == "name":
            cls = "kw" if keyword.iskeyword(text) else ("bi" if text in _BUILTINS else ("fn" if src[m.end():m.end() + 1] == "(" else "id"))
        for k, part in enumerate(text.split("\n")):
            if k:
                out_lines.append("")
            if part:
                out_lines[-1] += f'<span class="{cls}">{html.escape(part)}</span>'
        pos = m.end()
    if pos < len(src):
        for k, part in enumerate(src[pos:].split("\n")):
            if k:
                out_lines.append("")
            out_lines[-1] += html.escape(part)
    return out_lines
