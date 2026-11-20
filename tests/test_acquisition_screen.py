"""Acquisition fallbacks (servers without byte ranges, remote zip members) and screen scenes."""

from __future__ import annotations

import functools
import http.server
import threading
import zipfile
from pathlib import Path

import pytest

from sn85ds.acquisition import http as H
from sn85ds.screen.scenes import BUILDERS
from sn85ds.util import sha256_file


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Minimal Range support (206) so RemoteZip can be tested; '/norange/' paths ignore Range."""

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng and not self.path.startswith("/norange/"):
            path = Path(self.translate_path(self.path))
            data = path.read_bytes()
            a, b = rng.split("=")[1].split("-")
            a, b = int(a), min(int(b), len(data) - 1)
            self.send_response(206)
            self.send_header("Content-Length", str(b - a + 1))
            self.end_headers()
            self.wfile.write(data[a:b + 1])
            return
        if self.path.startswith("/norange/"):
            self.path = self.path[len("/norange"):]
        return super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/norange/"):
            self.path = self.path[len("/norange"):]
        return super().do_HEAD()


@pytest.fixture()
def server(tmp_path):
    handler = functools.partial(_RangeHandler, directory=str(tmp_path))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()


def test_download_falls_back_to_streaming_when_ranges_are_ignored(server):
    base, root = server
    (root / "big.bin").write_bytes(bytes(range(256)) * 5000)
    res = H.download(f"{base}/norange/big.bin", root / "out" / "big.bin", chunk=100_000, connections=2)
    assert res.get("mode") == "stream"
    assert sha256_file(root / "out" / "big.bin") == sha256_file(root / "big.bin")


def test_ranged_download_and_remote_zip(server):
    base, root = server
    (root / "big.bin").write_bytes(bytes(range(256)) * 5000)
    res = H.download(f"{base}/big.bin", root / "out2" / "big.bin", chunk=100_000, connections=3)
    assert res["sha256"] == sha256_file(root / "big.bin")
    with zipfile.ZipFile(root / "a.zip", "w") as z:
        z.writestr("SDR/x/frame00000001.j2k", b"A" * 1000)
        z.writestr("SDR/x/frame00000002.j2k", b"B" * 2000, compress_type=zipfile.ZIP_DEFLATED)
    rz = H.RemoteZip(f"{base}/a.zip")
    m = rz.members(r"\.j2k$")
    assert [i.filename for i in m] == ["SDR/x/frame00000001.j2k", "SDR/x/frame00000002.j2k"]
    out = rz.fetch(m[1], root / "f2.j2k")
    assert (root / "f2.j2k").read_bytes() == b"B" * 2000 and out["crc32"]


def test_screen_scenes_are_deterministic_and_offline():
    for name, build in BUILDERS.items():
        w, h = (1080, 1920) if name == "document" else (1920, 1080)
        a, b = build(7, w, h), build(7, w, h)
        assert a.html == b.html and a.params == b.params
        assert "window.renderFrame=renderFrame" in a.html
        assert "http://" not in a.html and "https://" not in a.html  # nothing fetched
        assert build(8, w, h).html != a.html


def test_screen_render_smoke(tmp_path):
    pytest.importorskip("playwright")
    from sn85ds.media import probe
    from sn85ds.screen.render import render_scene
    sc = BUILDERS["terminal"](3, 1920, 1080)
    try:
        res = render_scene(sc, "30", 3, tmp_path / "t.mkv")
    except Exception as exc:  # browser not installed in this environment
        pytest.skip(f"chromium unavailable: {exc}")
    p = probe(tmp_path / "t.mkv")
    assert (p.width, p.height, p.frames, p.codec) == (1920, 1080, 3, "ffv1") and res["frames"] == 3
