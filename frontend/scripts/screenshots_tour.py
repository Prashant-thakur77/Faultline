"""
The home page's product-tour images (frontend/public/shots/*.webp) and their docs copies, from a fresh S1 run against
the real backend. Run with the API on --api and the production UI on --ui:
  incident-room-full.webp  the incident room at AWAITING_APPROVAL, verdict first
  crew.webp                the same room with its crew lanes in view (17-crew-board.png: the lanes alone)
  provenance.webp          "Why do you believe this?" open on the confirmed cause (18-provenance.png)
  22-product-tour.png      the home page's product tour section, showing them
(brain-graph.webp and preflight-reversal.webp show no incident and are kept.)
Usage (repo root): .venv/bin/python frontend/scripts/screenshots_tour.py [--ui URL] [--api URL] [--chromium PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "frontend" / "public" / "shots"
DOCS = ROOT / "docs" / "screenshots"
VIEW = {"width": 1440, "height": 900}


def webp(png: Path, out: Path) -> None:
    from PIL import Image   # installed with fastembed (a runtime dependency)

    Image.open(png).convert("RGB").save(out, "WEBP", quality=84, method=6)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui", default="http://localhost:3000")
    ap.add_argument("--api", default="http://localhost:8400")
    ap.add_argument("--chromium", default=None)
    a = ap.parse_args()
    req = urllib.request.Request(f"{a.api}/api/scenarios/S1/run", data=json.dumps({"llm": "baseline"}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - our own API
            inc = json.loads(r.read()).get("incident")
    except OSError as e:
        print(f"tour shots FAILED: API unreachable: {e}", file=sys.stderr)
        return 2
    if not inc:
        print("tour shots FAILED: the S1 run opened no incident", file=sys.stderr)
        return 2
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chromium) if a.chromium else p.chromium.launch()
        page = b.new_context(viewport=VIEW, color_scheme="dark", reduced_motion="reduce").new_page()
        page.set_default_timeout(30_000)
        page.goto(f"{a.ui}/incidents/{inc}?tenant=acme")
        expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=120_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(DOCS / "_room.png"))
        webp(DOCS / "_room.png", SHOTS / "incident-room-full.webp")

        crew = page.locator("section[aria-labelledby='crew-h']")
        expect(crew).to_be_visible()
        # bring the crew lanes into the middle pane's view without scrolling the page header away
        crew.evaluate("""e => { let p = e.parentElement;
            while (p && !(p.scrollHeight > p.clientHeight && getComputedStyle(p).overflowY !== 'visible')) p = p.parentElement;
            if (p && p !== document.scrollingElement) p.scrollTop += e.getBoundingClientRect().top - p.getBoundingClientRect().top - 8;
            else e.scrollIntoView({block: 'start'}); }""")
        page.wait_for_timeout(800)
        page.screenshot(path=str(DOCS / "_crew.png"))
        webp(DOCS / "_crew.png", SHOTS / "crew.webp")
        crew.screenshot(path=str(DOCS / "17-crew-board.png"))

        page.get_by_role("button", name="Why do you believe this?").first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(DOCS / "18-provenance.png"))
        webp(DOCS / "18-provenance.png", SHOTS / "provenance.webp")

        page.goto(f"{a.ui}/?tenant=acme")   # the home page's product tour, now showing the images above
        tour = page.get_by_role("heading", name="See it work.", exact=False).first
        expect(tour).to_be_visible(timeout=30_000)
        tour.evaluate("e => e.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(DOCS / "22-product-tour.png"))
        b.close()
    for tmp in ("_room.png", "_crew.png"):
        (DOCS / tmp).unlink(missing_ok=True)
    print(f"tour shots: {inc} → incident-room-full.webp, crew.webp, provenance.webp; 17-crew-board.png, 18-provenance.png, "
          "22-product-tour.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
