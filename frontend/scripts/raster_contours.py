"""Rasterise public/brand/contours.svg once into public/brand/contours.webp.

The SVG is a single path of thousands of short segments. Drawn live as a large, slowly zooming CSS background, the
browser re-rasterised it at each new scale: 100-300 ms stalls while scrolling on an integrated GPU. A bitmap is
decoded once and only moved. White lines on a transparent background; the page sets its opacity.

    .venv/bin/python frontend/scripts/raster_contours.py [--chromium PATH]
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from playwright.sync_api import sync_playwright

PUB = Path(__file__).resolve().parents[1] / "public" / "brand"
W, H = 2400, 1500   # the SVG's 16:10 viewBox, sized for the largest layer it covers (about 1.6k px CSS wide)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", default=None)
    a = ap.parse_args()
    svg = (PUB / "contours.svg").read_text()
    sized = svg.replace("<svg ", f'<svg width="{W}" height="{H}" ', 1)
    html = f"<html><body style='margin:0;background:transparent'><div style='width:{W}px;height:{H}px'>{sized}</div></body></html>"
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chromium) if a.chromium else p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.set_content(html)
        png = pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": W, "height": H})
        b.close()
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGBA")
    out = PUB / "contours.webp"
    im.save(out, "WEBP", quality=80, method=6)
    print(f"wrote {out} ({W}x{H}, {out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
