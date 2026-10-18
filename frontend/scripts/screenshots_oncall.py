"""
Screenshots of the pages added after the first set (on call, learning, FalkorDB observing itself, the explainer,
Break it), against the real backend, into docs/screenshots/. Run after frontend/scripts/screenshots.py, which leaves
an S1 run whose pages are still open:
  23-oncall          /oncall: pager inbox, who is on call now, contracts, the last 7 days
  24-phone-page      one open page as the person paged sees it, at a phone's size (390x844, 2x)
  25-learned         /memory#learned: preferences, guidelines, who responds, recent learning events
  26-engine          /engine: memory per graph (GRAPH.MEMORY USAGE), query templates timed by the engine's telemetry
  27-explainer       /explainer at scene 5 (algo.maxFlow: can the look-alike carry the impact?)
  28-break-it        /playground: change one edge or call and watch the decision flip
Fails loudly (exit 2) if the API or UI is unreachable or a page has nothing to show.
Usage (repo root): .venv/bin/python frontend/scripts/screenshots_oncall.py [--ui URL] [--api URL] [--chromium PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEW = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def get(api: str, path: str) -> dict:
    with urllib.request.urlopen(f"{api.rstrip('/')}{path}", timeout=20) as r:  # noqa: S310 - our own API
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui", default="http://localhost:3000")
    ap.add_argument("--api", default="http://localhost:8400")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--chromium", default=None)
    ap.add_argument("--tenant", default="acme")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    q = f"tenant={urllib.parse.quote(a.tenant)}"
    try:
        pages = get(a.api, f"/api/pages?{q}&status=open").get("rows") or []
    except OSError as e:
        print(f"screenshots FAILED: API unreachable: {e}", file=sys.stderr)
        return 2
    if not pages:
        print("screenshots FAILED: no open page (run frontend/scripts/screenshots.py first: its S1 run pages the on-call)",
              file=sys.stderr)
        return 2
    pid = pages[0]["id"]
    done = []
    with sync_playwright() as p:
        args = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]   # WebGL for the 3D explainer
        b = p.chromium.launch(executable_path=a.chromium, args=args) if a.chromium else p.chromium.launch(args=args)
        ctx = b.new_context(viewport=VIEW, color_scheme="dark", reduced_motion="reduce")
        page = ctx.new_page()

        page.goto(f"{a.ui}/oncall?{q}")
        expect(page.locator("#oncall-verdict")).to_have_count(1, timeout=30_000)   # it renders twice on first load
        expect(page.locator("#oncall-verdict")).not_to_have_text(re.compile(r"^Reading"), timeout=30_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=out / "23-oncall.png")
        done.append("23-oncall.png")

        phone = b.new_context(viewport=PHONE, device_scale_factor=2, color_scheme="dark", reduced_motion="reduce")
        pp = phone.new_page()
        pp.goto(f"{a.ui}/oncall/page/{urllib.parse.quote(pid)}?{q}")
        expect(pp.get_by_text("Why: the proof path")).to_be_visible(timeout=30_000)
        pp.wait_for_timeout(1000)
        pp.screenshot(path=out / "24-phone-page.png")
        done.append("24-phone-page.png")
        phone.close()

        page.goto(f"{a.ui}/memory?{q}#learned")
        section = page.locator("section#learned")
        expect(section).to_be_visible(timeout=30_000)
        expect(section.get_by_role("heading", name="Preferences")).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1500)
        page.evaluate("() => document.querySelector('section#learned').scrollIntoView({block: 'start'})")
        page.wait_for_timeout(800)
        page.screenshot(path=out / "25-learned.png")
        done.append("25-learned.png")

        page.goto(f"{a.ui}/engine?{q}")
        expect(page.get_by_text("Memory per graph")).to_be_visible(timeout=30_000)
        page.wait_for_timeout(2500)
        page.screenshot(path=out / "26-engine.png")
        done.append("26-engine.png")

        anim = b.new_context(viewport=VIEW, color_scheme="dark")   # the 3D explainer animates only without reduced motion
        ap_ = anim.new_page()
        ap_.goto(f"{a.ui}/explainer?view=stage&autoplay=0&captions=chips")
        ap_.wait_for_function("() => !!window.__explainer && window.__explainer.state().mode === 'animated'",
                              timeout=60_000)
        ap_.evaluate("() => window.__explainer.playScene(5, 1.5)")
        ap_.wait_for_timeout(3500)
        ap_.screenshot(path=out / "27-explainer.png")
        done.append("27-explainer.png")
        anim.close()

        page.goto(f"{a.ui}/playground?{q}")
        expect(page.get_by_role("heading").first).to_be_visible(timeout=30_000)
        page.wait_for_timeout(2500)
        page.screenshot(path=out / "28-break-it.png")
        done.append("28-break-it.png")
        b.close()
    print(f"screenshots: {len(done)} files in {out}")
    for f in done:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
