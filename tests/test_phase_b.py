"""Phase B additions: Commons licence normalisation, QuickTime sample tables (SVT FTP path),
disk-saving master removal, screen builders."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))


def test_commons_licence_normalisation():
    from sn85ds.acquisition.commons import normalise_licence
    assert normalise_licence("CC BY-SA 4.0") == ("CC-BY-SA-4.0", None)
    assert normalise_licence("CC BY 3.0") == ("CC-BY-3.0", None)
    assert normalise_licence("CC0") == ("CC0-1.0", None)
    assert normalise_licence("Public domain") == ("PD", None)
    lic, note = normalise_licence("CC BY-SA 3.0 de")
    assert lic == "CC-BY-SA-3.0" and "ported" in note
    for bad in ("CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-SA 3.0", "FAL", "GFDL", "", "Copyrighted"):
        assert normalise_licence(bad)[0] is None, bad


class LocalRange:
    """Same interface as FtpRange, on a local file."""
    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size

    def read(self, offset: int, length: int) -> bytes:
        with self.path.open("rb") as f:
            f.seek(offset)
            return f.read(length)


@pytest.mark.parametrize("faststart", [False, True])
def test_mov_sample_table_matches_ffprobe(tmp_path, faststart):
    from sn85ds.acquisition.ftp import find_top_level, parse_video_track
    mov = tmp_path / "t.mov"
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=50", "-frames:v", "12", "-c:v", "mjpeg", "-q:v", "3"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    subprocess.run(cmd + [str(mov)], check=True)
    r = LocalRange(mov)
    off, size = find_top_level(r, b"moov")
    tr = parse_video_track(r.read(off, size))
    pk = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pos,size", "-of", "json", str(mov)],
                                   capture_output=True, text=True, check=True).stdout)["packets"]
    assert tr.frames == 12 == len(pk)
    assert tr.sample_offsets == [int(p["pos"]) for p in pk]
    assert tr.sample_sizes == [int(p["size"]) for p in pk]
    assert tr.timescale / tr.sample_durations[0] == 50


def test_drop_master_keeps_manifest(tmp_path):
    from prepare_references import drop_master
    base = tmp_path / "clip"
    (base / "frames").mkdir(parents=True)
    (base / "frames" / "0001.png").write_bytes(b"x" * 100)
    (base / "clip.y4m").write_bytes(b"y" * 50)
    (base / "manifest.json").write_text("{}")
    assert drop_master(base) == 150
    assert sorted(p.name for p in base.rglob("*")) == ["manifest.json"]


def test_screen_builders_deterministic():
    from sn85ds.screen.scenes import BUILDERS
    for name, b in BUILDERS.items():
        for w, h in ((1920, 1080), (1080, 1920)):
            a, c = b(123, w, h), b(123, w, h)
            assert a.html == c.html and "renderFrame" in a.html, name
            assert a.viewport[0] * a.device_scale == pytest.approx(w, abs=1)
        assert b(1, 1920, 1080).html != b(2, 1920, 1080).html, name


def test_screen_page_data_cannot_close_the_script_tag():
    """Code shown on screen may contain '</script>' (this project's own sources); the embedded JSON must escape it."""
    from sn85ds.screen.scenes import BUILDERS
    for seed in range(5000, 5030):
        for name in ("code", "notebook"):
            html = BUILDERS[name](seed, 1920, 1080).html
            assert html.count("</script") == 1, (name, seed)
