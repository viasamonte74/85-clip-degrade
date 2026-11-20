"""Render a screen Scene frame by frame in headless Chromium into a lossless FFV1 reference.

Frame k is rendered at t = k / fps exactly (no wall-clock animation), captured as a PNG
screenshot at the native output size (viewport x device scale), and converted to 8-bit
4:2:0 BT.709 limited range with the project's explicit conversion (browser pixels are
sRGB-encoded; they are taken as BT.709 R'G'B' without a transfer conversion, the usual
convention for screen capture).
"""

from __future__ import annotations

import hashlib
import time
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from sn85ds.colour import rgb_to_yuv420
from sn85ds.media import RawYuv420Writer, ffv1_args
from sn85ds.screen.scenes import Scene

CHROMIUM_ARGS = ["--disable-gpu", "--disable-lcd-text", "--force-color-profile=srgb", "--font-render-hinting=none",
                 "--disable-font-subpixel-positioning", "--hide-scrollbars"]


def render_scene(scene: Scene, fps: str, frames: int, out_path: str | Path, *, sample_png_dir: str | Path | None = None,
                 sample_frames: tuple[int, ...] = ()) -> dict:
    from playwright.sync_api import sync_playwright

    fr = Fraction(fps)
    t0 = time.time()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".partial.mkv")
    vw, vh = scene.viewport
    png_hash = hashlib.sha256()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=CHROMIUM_ARGS)
        version = browser.version
        page = browser.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=scene.device_scale)
        page.route("**/*", lambda route: route.abort() if not route.request.url.startswith("data:") and not route.request.url.startswith("about:") else route.continue_())
        page.set_content(scene.html, wait_until="load")
        writer = RawYuv420Writer(tmp, scene.width, scene.height, fps, ffv1_args())
        with writer:
            for k in range(frames):
                t = float(Fraction(k) / fr)
                page.evaluate("t => window.renderFrame(t)", t)
                png = page.screenshot(type="png", animations="disabled", caret="hide")
                png_hash.update(png)
                img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
                if img is None or img.shape[:2] != (scene.height, scene.width):
                    raise RuntimeError(f"screenshot {None if img is None else img.shape} != {scene.width}x{scene.height}")
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                writer.write(*rgb_to_yuv420(rgb))
                if sample_png_dir and k in sample_frames:
                    Path(sample_png_dir).mkdir(parents=True, exist_ok=True)
                    (Path(sample_png_dir) / f"{out.stem}_f{k:05d}.png").write_bytes(png)
        browser.close()
    tmp.replace(out)
    return {"frames": writer.frames, "chromium": version, "viewport": [vw, vh], "device_scale": scene.device_scale,
            "screenshots_sha256": png_hash.hexdigest(), "planes_sha256": writer.hash.hexdigest(),
            "seconds": round(time.time() - t0, 1), "chromium_args": CHROMIUM_ARGS}
