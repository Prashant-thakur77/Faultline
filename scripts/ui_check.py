"""Browser checks for the UI (optional; needs Playwright's Chromium and a running app: `make demo`, then `make ui-check`).

Every page at desktop (1440×900) and phone (390×844) size:
  * no element sticks out sideways unless a scroll container clips it, and the page is exactly the phone's width
    (a phone widens its layout viewport to fit wide content, so innerWidth alone would hide the overflow);
  * the home hero and every page intro have real height (a flex-collapse bug once rendered them at 0 px), and
    their headlines are visible (a motion bug once left the reduced-motion hero at opacity 0);
  * axe-core finds no serious or critical accessibility violation.
Exit 1 with the list when anything fails. Not part of `make judge-check` (that one needs no browser)."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("UI_BASE", "http://localhost:3000")
PAGES = ["/", "/preflight", "/memory", "/brain", "/explore", "/playground", "/replay"]
CHROME = os.environ.get("UI_CHROME") or str(Path.home() / ".cache/ms-playwright/chromium-1243/chrome-linux64/chrome")
OVERFLOW = """() => { const W = window.innerWidth; const bad = new Set();
  for (const e of document.querySelectorAll('main *')) { const r = e.getBoundingClientRect(); if (r.width === 0) continue;
    if (r.right > W + 1) { let p = e.parentElement, clipped = false;
      while (p) { if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(p).overflowX)) { clipped = true; break; } p = p.parentElement; }
      if (!clipped) bad.add(e.tagName.toLowerCase() + '.' + String(e.className).split(' ').slice(0, 3).join('.')); } }
  return [...bad].slice(0, 5); }"""
HEIGHTS = """() => [...document.querySelectorAll('section[aria-labelledby=hero-title], [data-fl-intro]')]
  .map(e => Math.round(e.getBoundingClientRect().height))"""
# every headline line must be visible: fully opaque along its ancestors and on top at its own centre (catches
# text left at opacity 0 or still translated out of its mask after the reveal; a 0 px box is HEIGHTS' job)
HEADLINE = """() => [...document.querySelectorAll('#hero-title > span > *, [data-fl-intro] h1')].filter(e => {
  const r = e.getBoundingClientRect(); if (!r.width || !r.height) return false;
  let o = 1; for (let p = e; p; p = p.parentElement) o *= parseFloat(getComputedStyle(p).opacity);
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return o < 0.9 || !(hit && (e === hit || e.contains(hit))); }).map(e => e.textContent.trim().slice(0, 30))"""
AXE = (ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js").read_text()


def main() -> int:
    problems: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME if Path(CHROME).exists() else None, args=["--no-sandbox"])
        for vp, size, mob in (("desktop", {"width": 1440, "height": 900}, False), ("phone", {"width": 390, "height": 844}, True)):
            for path in PAGES:
                ctx = b.new_context(viewport=size, is_mobile=mob, has_touch=mob, reduced_motion="reduce")
                pg = ctx.new_page()
                r = pg.goto(BASE + path, wait_until="networkidle", timeout=60_000)
                pg.wait_for_timeout(2500)
                where = f"{vp} {path}"
                if not r or r.status != 200:
                    problems.append(f"{where}: HTTP {r.status if r else 'no response'}")
                # a phone widens its layout viewport to fit wide content, and innerWidth follows: check that first
                if mob and (w := pg.evaluate("[window.innerWidth, document.documentElement.scrollWidth]")) != [size["width"]] * 2:
                    problems.append(f"{where}: page is wider than the phone (innerWidth, scrollWidth = {w})")
                if mob and (o := pg.evaluate(OVERFLOW)):
                    problems.append(f"{where}: overflow {o}")
                if any(h < 100 for h in pg.evaluate(HEIGHTS)):
                    problems.append(f"{where}: a hero or page intro collapsed ({pg.evaluate(HEIGHTS)} px)")
                if hidden := pg.evaluate(HEADLINE):
                    problems.append(f"{where}: headline not visible {hidden}")
                pg.add_script_tag(content=AXE)
                v = pg.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
                                ".filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ×' + v.nodes.length)")
                if v:
                    problems.append(f"{where}: axe {v}")
                ctx.close()
        b.close()
    for x in problems:
        print("FAIL", x)
    print(f"ui-check: {'PASS' if not problems else 'FAIL'} ({len(PAGES)} pages × 2 sizes)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
