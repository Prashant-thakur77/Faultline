"""
Screenshots of each main page of the Faultline UI, against the real backend (no mocks), into docs/screenshots/.

What it captures (1440x900, dark UI, reduced motion so the path animation is at rest):
  01-home                 / (hero, proof story; the isolation badge is asserted in the top bar's status panel)
  02-incident-room        an S1 run (POST /api/scenarios/S1/run, baseline) at AWAITING_APPROVAL
  03-naive-vs-faultline   its suspects card with the "Naive recency" lens on
  04-reject-form          its plan card: an option chosen, exact action rendered, the Reject form open with a reason
  05-rejected             the same card after the rejection (option disabled, who/why recorded); nothing is approved
  06-memory               /memory?incident=<that incident> (recall, families, derived runbooks, cold vs warm)
  07-brain                /brain with the decision tracer, ownership map and guardrails widgets
  08-brain-widgets        the widgets alone, with a component's ownership history open
  09-tenant-globex        /brain?tenant=globex (the same page on the other tenant's graph)
  10-preflight            /preflight after the S6 example
  11-explore              /explore (FalkorDB canvas)
  12-replay               /replay/s1-hero played to the end at 8x
  13-cypher-panel         the Cypher panel opened from a gate check
  14-obligations          the incident room's "Obligations at risk" card (obligation clock: time to breach, customers)
  (also frontend/public/shots/incident-room.webp, the home hero's product frame, from 02-incident-room)
  16-proof-story          / scrolled to step 05 of "How it decides" (pinned proof graph at the min-cut, Q-CUT-1 card)
The S1 run happens in its own GRAPH.COPY clean room; the rejection only touches that copy and nothing is approved,
so no PR is opened. Fails loudly (exit 2) if the API or UI is unreachable.

Usage (repo root): .venv/bin/python frontend/scripts/screenshots.py [--ui URL] [--api URL] [--out docs/screenshots] [--chromium PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEW = {"width": 1440, "height": 900}


def die(msg: str) -> None:
    print(f"screenshots FAILED: {msg}", file=sys.stderr)
    sys.exit(2)


def http_json(url: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (localhost only)
        return json.loads(r.read())


def settle(page: Page, ms: int = 900) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


HERO_SHOT = Path(__file__).resolve().parents[1] / "public" / "shots" / "incident-room.webp"


def hero_shot(png: Path) -> None:
    """The home hero's product frame shows this same incident-room shot: refresh its WebP so the two never drift."""
    from PIL import Image   # installed with fastembed (a runtime dependency); imported here only

    HERO_SHOT.parent.mkdir(parents=True, exist_ok=True)
    Image.open(png).convert("RGB").save(HERO_SHOT, "WEBP", quality=84, method=6)


def isolation(page, graph: str) -> None:
    """Open the top bar's status panel and wait for the isolation badge of `graph`."""
    page.get_by_role("button", name=re.compile(r"system details")).click()
    expect(page.get_by_text(re.compile(rf"graph: {graph}"))).to_be_visible()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui", default="http://localhost:3100")
    ap.add_argument("--api", default="http://localhost:8400")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--chromium", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        if http_json(f"{a.api}/api/status", timeout=10).get("status") != "ok":
            die("API status is not ok")
        urllib.request.urlopen(a.ui, timeout=10)  # noqa: S310
    except (urllib.error.URLError, OSError) as e:
        die(f"API or UI unreachable: {e}")
    shots: list[str] = []

    def snap_at(target, name: str) -> None:
        """Viewport shot with `target` scrolled to the middle (element shots of a tall card in a scroll pane tear)."""
        target.evaluate("e => e.scrollIntoView({block: 'center'})")
        page.wait_for_timeout(300)
        snap(page, name)

    def snap(target, name: str) -> None:
        path = out / f"{name}.png"
        target.screenshot(path=str(path))
        shots.append(path.name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=a.chromium) if a.chromium else pw.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, reduced_motion="reduce", device_scale_factor=1)
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        expect.set_options(timeout=30_000)
        # every page starts on acme (the tenant choice persists in localStorage)
        page.goto(f"{a.ui}/?tenant=acme")
        expect(page.get_by_role("button", name=re.compile(r"Run scenario S1 with"))).to_be_visible()
        isolation(page, "tenant_acme")
        page.get_by_role("button", name=re.compile(r"system details")).click()   # close the panel again for the shot
        settle(page)
        snap(page, "01-home")
        page.locator("li[data-step='4']").evaluate("e => e.scrollIntoView({block: 'center'})")
        expect(page.get_by_role("button", name="Step 05: Cut")).to_have_attribute("aria-current", "step")
        settle(page, 600)
        snap(page, "16-proof-story")

        run = http_json(f"{a.api}/api/scenarios/S1/run", {"llm": "baseline"})
        inc = run.get("incident") or die(f"S1 run returned no incident: {run}")
        page.goto(f"{a.ui}/incidents/{inc}?tenant=acme")
        expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=120_000)
        settle(page, 1500)
        snap(page, "02-incident-room")
        hero_shot(out / "02-incident-room.png")

        obl = page.locator("section[aria-labelledby='obligations-h']")
        expect(obl.get_by_text("time to SLO breach")).to_be_visible()
        snap_at(obl, "14-obligations")

        sus = page.locator("section[aria-labelledby='suspects-h']")
        sus.get_by_role("button", name=re.compile(r"Naive recency")).click()
        expect(sus.get_by_text("Naive recency would blame")).to_be_visible()
        settle(page, 400)
        snap(sus, "03-naive-vs-faultline")

        page.get_by_role("button", name=re.compile(r"^G2 path: pass")).first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        settle(page, 1500)
        snap(page, "13-cypher-panel")
        page.keyboard.press("Escape")

        plan = page.locator("section[aria-labelledby='plan-h']")
        plan.get_by_role("button", name=re.compile(r"^(Choose|Re-choose)$")).first.click()
        expect(plan.get_by_text("Exact action the server will take")).to_be_visible()
        plan.get_by_role("button", name=re.compile(r"Reject")).click()
        plan.get_by_label(re.compile(r"^Reason")).fill("prefer a rollback during the release freeze")
        settle(page, 300)
        snap_at(plan.locator("fieldset").first, "04-reject-form")
        plan.get_by_role("button", name="Confirm reject").click()
        expect(plan.get_by_text(re.compile(r"Rejected:"))).to_be_visible()
        expect(plan.get_by_text(re.compile(r"rejected by p-")).first).to_be_visible()
        settle(page, 600)
        snap_at(plan.get_by_text(re.compile(r"Rejected:")).first, "05-rejected")

        page.goto(f"{a.ui}/memory?incident={inc}&tenant=acme")
        expect(page.get_by_role("heading", name=re.compile(r"Recall for"))).to_be_visible()
        expect(page.get_by_text(re.compile(r"Cold vs warm"))).to_be_visible()
        settle(page)
        snap(page, "06-memory")

        page.goto(f"{a.ui}/brain?tenant=acme")
        expect(page.get_by_text("current head")).to_be_visible()
        expect(page.get_by_role("heading", name=re.compile(r"Ownership map"))).to_be_visible()
        expect(page.get_by_text(re.compile(r"Knowledge health \("))).to_be_visible()
        settle(page)
        snap(page, "07-brain")
        own = page.locator("section[aria-labelledby='ownmap-h']")
        own.locator("ul[aria-label^='Components owned by'] button").first.click()
        expect(own.get_by_text("owned now by")).to_be_visible()
        widgets = page.locator("section[aria-labelledby='dectrace-h']").locator("xpath=..")
        settle(page, 400)
        snap(widgets, "08-brain-widgets")

        page.goto(f"{a.ui}/brain?tenant=globex")
        expect(page.get_by_text("current head")).to_be_visible()
        isolation(page, "tenant_globex")   # left open: this shot shows the per-tenant isolation badge
        settle(page)
        page.locator("section[aria-labelledby='dectrace-h']").evaluate("e => e.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(300)
        snap(page, "09-tenant-globex")

        page.goto(f"{a.ui}/preflight?tenant=acme")
        page.get_by_role("button", name=re.compile(r"S6: payment timeout 5000 ms")).click()
        expect(page.locator("[data-verdict]").first).to_be_visible()
        settle(page, 1500)
        snap(page, "10-preflight")

        page.goto(f"{a.ui}/explore?tenant=acme")
        settle(page, 3000)
        snap(page, "11-explore")

        page.goto(f"{a.ui}/replay/s1-hero")
        expect(page.get_by_text("Recorded run · static files")).to_be_visible()
        # reduced motion makes playback manual: jump to the end (every recorded event applied)
        page.get_by_role("button", name="Jump to the end").click()
        expect(page.get_by_text(re.compile(r"Event (\d+) / \1\b")).first).to_be_visible(timeout=30_000)
        settle(page)
        snap(page, "12-replay")
        browser.close()

    print(f"screenshots: {len(shots)} files in {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    for s in shots:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
