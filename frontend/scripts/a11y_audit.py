"""
Accessibility audit of the Faultline UI: axe-core on every page plus keyboard checks.

What it does
  1. Live UI (production `next start`, default http://localhost:3100, backend on :8400):
       home/launcher (and its reset confirm step, cancelled); an S1 incident room at AWAITING_APPROVAL; the same room in the
       naive-vs-Faultline lens, with the Reject form open and after a rejection (M13); /memory for that incident;
       /brain widgets on globex; the same room in the
       plan/approval state (an option chosen, the exact action shown; nothing is approved, so no
       PR is opened); /brain after one question (and a forget dry run, never executed); /preflight after the S6 example; /explore;
       /replay/ and /replay/s1-hero (played to the end at 8x).
  2. Static GitHub Pages export (out-pages/, served here under /Faultline): landing, /replay/,
       /replay/s1-hero/ and /replay/s2-data-incident/ (played to the end), with no backend.
  3. Keyboard: Tab from the top of the incident room in the plan state reaches
       "Approve this exact action"; a gate check's Cypher button opens the Cypher dialog with
       Enter, focus moves into it, Escape closes it and focus returns to the trigger; every
       focused control shows a visible focus indicator (outline or ring).
  axe-core is injected from node_modules/axe-core (pinned devDependency). Rules: WCAG 2.0/2.1/2.2
  A and AA plus best-practice. The UI is dark-only, so contrast is checked in dark mode only.

Fail loudly: if the API or the UI is unreachable the script exits non-zero; nothing is skipped
silently. Exit status 1 when any serious or critical violation remains or a keyboard check fails.

Usage (from the repo root):
  .venv/bin/python frontend/scripts/a11y_audit.py [--ui http://localhost:3100] [--api http://localhost:8400]
      [--static-only | --live-only] [--out frontend/test-results/a11y] [--chromium PATH]
Writes <out>/a11y.json (every violation with its nodes) and prints a summary table.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

FRONTEND = Path(__file__).resolve().parents[1]
AXE = FRONTEND / "node_modules" / "axe-core" / "axe.min.js"
IMPACTS = ("critical", "serious", "moderate", "minor")
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
VIEW = {"width": 1440, "height": 900}


def die(msg: str) -> None:
    print(f"a11y_audit FAILED: {msg}", file=sys.stderr)
    sys.exit(2)


def http_json(url: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (localhost only)
        return json.loads(r.read())


# ---------------------------------------------------------------- axe


def run_axe(page: Page, name: str) -> dict:
    page.wait_for_timeout(600)  # let entry transitions settle (axe flags mid-fade contrast otherwise)
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        page.add_script_tag(content=AXE.read_text())
    res = page.evaluate(
        """async (tags) => {
            const r = await window.axe.run(document, { runOnly: { type: 'tag', values: tags }, resultTypes: ['violations'] });
            return { url: location.href, version: window.axe.version, violations: r.violations.map(v => ({
                id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl, tags: v.tags,
                nodes: v.nodes.map(n => ({ target: n.target, html: n.html.slice(0, 300), summary: n.failureSummary })) })) };
        }""",
        AXE_TAGS,
    )
    res["page"] = name
    return res


def summarise(results: list[dict]) -> tuple[Counter, Counter]:
    rules: Counter = Counter()
    nodes: Counter = Counter()
    for r in results:
        for v in r["violations"]:
            rules[v["impact"]] += 1
            nodes[v["impact"]] += len(v["nodes"])
    return rules, nodes


# ---------------------------------------------------------------- keyboard


FOCUS_JS = r"""() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const cs = getComputedStyle(el);
  const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 && !/^rgba\([^)]*,\s*0\)$/.test(cs.outlineColor) && cs.outlineColor !== 'transparent';
  // A ring counts only if some box-shadow layer has a non-transparent colour and a non-zero
  // length (Tailwind keeps transparent 0px placeholder layers on every element).
  const COLOR = /(rgba?|oklch|oklab|lab|lch|hsla?|color)\([^)]*\)/;
  const ring = (cs.boxShadow || 'none') !== 'none' && cs.boxShadow.split(/,(?![^(]*\))/).some((layer) => {
    const c = (layer.match(COLOR) || [''])[0];
    const transparent = /^rgba\([^)]*,\s*0\)$/.test(c) || /\/\s*0\)$/.test(c) || c === '';
    const lengths = layer.replace(COLOR, '').trim().split(/\s+/).map(parseFloat).filter((n) => !Number.isNaN(n));
    return !transparent && lengths.some((n) => n > 0);
  });
  const name = (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || '').trim().slice(0, 120);
  return { tag: el.tagName.toLowerCase(), name, visible: outline || ring, inDialog: !!el.closest('[role=dialog]') };
}"""


def keyboard_checks(page: Page) -> list[dict]:
    checks: list[dict] = []
    page.evaluate("() => { window.scrollTo(0, 0); document.activeElement && document.activeElement.blur && document.activeElement.blur(); }")
    page.locator("body").click(position={"x": 2, "y": 2})
    seen_invisible: list[str] = []
    reached = None
    for i in range(600):
        page.keyboard.press("Tab")
        page.wait_for_timeout(260)  # buttons fade their focus ring in (transition-all, 150 ms)
        f = page.evaluate(FOCUS_JS)
        if not f:
            continue
        if not f["visible"]:
            seen_invisible.append(f"{f['tag']}:{f['name'][:50]}")
        if re.search(r"Approve this exact action", f["name"]):
            reached = i + 1
            break
    checks.append({"check": "Tab reaches 'Approve this exact action'", "ok": reached is not None,
                   "detail": f"after {reached} Tab presses" if reached else "not reached in 600 presses"})
    checks.append({"check": "Every Tab stop shows a visible focus indicator", "ok": not seen_invisible,
                   "detail": "; ".join(sorted(set(seen_invisible))[:15]) or "all visible"})

    # Cypher panel by keyboard: focus a gate check's Cypher button, Enter, Escape.
    gate = page.locator("section[aria-labelledby='gate-h']")
    trigger = gate.get_by_role("button", name=re.compile(r"^G2 path: pass")).first
    trigger.focus()
    page.keyboard.press("Enter")
    dlg = page.get_by_role("dialog")
    opened = True
    try:
        expect(dlg).to_be_visible(timeout=10_000)
    except AssertionError:
        opened = False
    page.wait_for_timeout(300)
    f = page.evaluate(FOCUS_JS) or {}
    checks.append({"check": "Enter on a gate check opens the Cypher panel with focus inside", "ok": opened and bool(f.get("inDialog")),
                   "detail": f"focused {f.get('tag')}:{f.get('name', '')[:60]}"})
    # Tab inside the dialog stays inside (focus trap) and is visible.
    trapped, vis = True, True
    for _ in range(12):
        page.keyboard.press("Tab")
        page.wait_for_timeout(150)  # Base UI's focus guards hand focus back to the start asynchronously
        g = page.evaluate(FOCUS_JS) or {}
        trapped &= bool(g.get("inDialog"))
        vis &= bool(g.get("visible"))
    checks.append({"check": "Tab cycles inside the Cypher panel with visible focus", "ok": trapped and vis,
                   "detail": f"trapped={trapped} visible={vis}"})
    page.keyboard.press("Escape")
    closed = True
    try:
        expect(dlg).to_be_hidden(timeout=5_000)
    except AssertionError:
        closed = False
    page.wait_for_timeout(200)
    back = page.evaluate("(el) => document.activeElement === el", trigger.element_handle())
    checks.append({"check": "Escape closes the Cypher panel and returns focus to the trigger", "ok": closed and back,
                   "detail": f"closed={closed} focus_returned={back}"})
    return checks


# ---------------------------------------------------------------- static server


def serve_static(root: Path, base: str) -> tuple[http.server.ThreadingHTTPServer, str]:
    class H(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path: str) -> str:
            p = path.split("?", 1)[0]
            if p.startswith(base):
                p = p[len(base):] or "/"
            return super().translate_path(p)

        def log_message(self, *a) -> None:  # quiet
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}{base}"


def play_replay_to_end(page: Page) -> None:
    expect(page.get_by_text("Recorded run · static files")).to_be_visible(timeout=20_000)
    page.get_by_role("radio", name="8×").click()
    expect(page.get_by_text(re.compile(r"Event (\d+) / \1\b"))).to_be_visible(timeout=90_000)


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui", default="http://localhost:3100")
    ap.add_argument("--api", default="http://localhost:8400")
    ap.add_argument("--out", default=str(FRONTEND / "test-results" / "a11y"))
    ap.add_argument("--chromium", default=None, help="Chromium/headless-shell binary (default: Playwright's)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--static-only", action="store_true")
    g.add_argument("--live-only", action="store_true")
    a = ap.parse_args()

    if not AXE.exists():
        die(f"{AXE} missing: run npm install in frontend/")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    keyboard: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=a.chromium) if a.chromium else pw.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, reduced_motion="no-preference")
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        expect.set_options(timeout=20_000)

        if not a.static_only:
            try:
                st = http_json(f"{a.api}/api/status", timeout=10)
            except (urllib.error.URLError, OSError) as e:
                die(f"API {a.api} unreachable ({e}); the live audit needs it (or pass --static-only)")
            if st.get("status") != "ok":
                die(f"API status is {st.get('status')!r}, not ok")
            try:
                urllib.request.urlopen(a.ui, timeout=10)  # noqa: S310
            except (urllib.error.URLError, OSError) as e:
                die(f"UI {a.ui} unreachable ({e})")

            page.goto(f"{a.ui}/")
            expect(page.get_by_role("button", name=re.compile(r"Run scenario S1 with"))).to_be_visible(timeout=30_000)
            page.wait_for_load_state("networkidle")
            results.append(run_axe(page, "live: home / launcher"))
            # the reset confirm step (cancelled with Escape: nothing is reset)
            page.get_by_role("button", name="Reset demo data (all visitors)").click()
            expect(page.get_by_role("button", name="Reset now")).to_be_focused()
            results.append(run_axe(page, "live: home (reset confirm step)"))
            page.keyboard.press("Escape")
            expect(page.get_by_role("button", name="Reset demo data (all visitors)")).to_be_focused()

            run = http_json(f"{a.api}/api/scenarios/S1/run", {"llm": "baseline"}, timeout=60)
            inc = run.get("incident")
            if not inc:
                die(f"S1 run returned no incident: {run}")
            page.goto(f"{a.ui}/incidents/{inc}")
            expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=120_000)
            page.wait_for_timeout(1500)
            results.append(run_axe(page, "live: incident room (S1, AWAITING_APPROVAL)"))

            plan = page.locator("section[aria-labelledby='plan-h']")
            # the first offered option (which one is offered depends on the demo repos' live state);
            # choosing renders the exact action only, nothing is approved or applied
            plan.get_by_role("button", name=re.compile(r"^(Choose|Re-choose)$")).first.click()
            expect(plan.get_by_text("Exact action the server will take")).to_be_visible(timeout=30_000)
            page.wait_for_timeout(800)
            results.append(run_axe(page, "live: incident room (plan / approval)"))

            page.get_by_role("button", name=re.compile(r"^G2 path: pass")).first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.wait_for_timeout(1500)
            results.append(run_axe(page, "live: Cypher panel (incident room)"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)

            keyboard = keyboard_checks(page)

            # M13: the naive-vs-Faultline lens, the reject form and the room after a rejection (this S1 run's own
            # graph copy only; nothing is approved, so no PR is opened)
            sus = page.locator("section[aria-labelledby='suspects-h']")
            sus.get_by_role("button", name=re.compile(r"Naive recency")).click()
            expect(sus.get_by_text("Naive recency would blame")).to_be_visible()
            results.append(run_axe(page, "live: incident room (naive vs Faultline)"))
            plan = page.locator("section[aria-labelledby='plan-h']")
            plan.get_by_role("button", name=re.compile(r"Reject")).click()
            plan.get_by_label(re.compile(r"^Reason")).fill("audit: prefer another option")
            results.append(run_axe(page, "live: incident room (reject form)"))
            plan.get_by_role("button", name="Confirm reject").click()
            expect(plan.get_by_text("Rejected:")).to_be_visible()
            results.append(run_axe(page, "live: incident room (after reject)"))

            page.goto(f"{a.ui}/memory?incident={inc}&tenant=acme")
            expect(page.get_by_role("heading", name=re.compile(r"Recall for"))).to_be_visible()
            expect(page.get_by_text("support", exact=False).first).to_be_visible()
            results.append(run_axe(page, "live: /memory (recall for the S1 incident)"))

            page.goto(f"{a.ui}/brain?tenant=globex")
            expect(page.get_by_text("current head")).to_be_visible()
            expect(page.get_by_text(re.compile(r"Knowledge health \("))).to_be_visible()
            results.append(run_axe(page, "live: /brain widgets (tenant globex)"))

            page.goto(f"{a.ui}/brain?tenant=acme")
            expect(page.get_by_text("current head")).to_be_visible()
            page.get_by_role("button", name="What breaks if productcatalog goes down?").click()
            expect(page.get_by_text("citation guard ✓")).to_be_visible(timeout=30_000)
            results.append(run_axe(page, "live: /brain (after one question)"))
            # forget: dry run only (read-only); the execute step is never pressed here
            page.get_by_label("document id").fill("doc-adr-021")
            page.get_by_role("button", name="Dry run").click()
            expect(page.get_by_text("receipt token")).to_be_visible()
            results.append(run_axe(page, "live: /brain (forget dry run)"))

            page.goto(f"{a.ui}/preflight?tenant=acme")
            page.get_by_role("button", name=re.compile(r"S6: payment timeout 5000 ms")).click()
            expect(page.locator("[data-verdict]").first).to_be_visible(timeout=30_000)
            page.wait_for_timeout(1500)
            results.append(run_axe(page, "live: /preflight (S6 example)"))

            page.goto(f"{a.ui}/explore")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            results.append(run_axe(page, "live: /explore"))

            page.goto(f"{a.ui}/replay")
            page.wait_for_load_state("networkidle")
            results.append(run_axe(page, "live: /replay (index)"))

            page.goto(f"{a.ui}/replay/s1-hero")
            play_replay_to_end(page)
            results.append(run_axe(page, "live: /replay/s1-hero (end)"))

            page.goto(f"{a.ui}/does-not-exist")
            results.append(run_axe(page, "live: 404"))

        if not a.live_only:
            root = FRONTEND / "out-pages"
            if not (root / "index.html").exists():
                die("out-pages/index.html missing: run npm run build:pages first")
            srv, base = serve_static(root, "/Faultline")
            try:
                page.goto(f"{base}/")
                page.wait_for_load_state("networkidle")
                results.append(run_axe(page, "pages: landing"))
                page.goto(f"{base}/replay/")
                page.wait_for_load_state("networkidle")
                results.append(run_axe(page, "pages: /replay/"))
                page.goto(f"{base}/memory/")
                expect(page.get_by_text(re.compile(r"Cold vs warm"))).to_be_visible()
                page.wait_for_load_state("networkidle")
                results.append(run_axe(page, "pages: /memory/ (cold vs warm only)"))
                for run_id in ("s1-hero", "s2-data-incident"):
                    page.goto(f"{base}/replay/{run_id}/")
                    play_replay_to_end(page)
                    results.append(run_axe(page, f"pages: /replay/{run_id}/ (end)"))
            finally:
                srv.shutdown()

        browser.close()

    rules, nodes = summarise(results)
    version = next((r["version"] for r in results), "?")
    (out / "a11y.json").write_text(json.dumps({"axe": version, "tags": AXE_TAGS, "pages": results, "keyboard": keyboard}, indent=2))

    print(f"axe-core {version}; tags {', '.join(AXE_TAGS)}")
    print(f"{'page':58} " + " ".join(f"{i:>9}" for i in IMPACTS))
    for r in results:
        c = Counter()
        for v in r["violations"]:
            c[v["impact"]] += len(v["nodes"])
        print(f"{r['page'][:58]:58} " + " ".join(f"{c[i]:>9}" for i in IMPACTS))
        for v in r["violations"]:
            print(f"    - [{v['impact']}] {v['id']} x{len(v['nodes'])}: {v['help']}")
    print("totals (rules / nodes): " + ", ".join(f"{i} {rules[i]}/{nodes[i]}" for i in IMPACTS))
    for k in keyboard:
        print(f"keyboard: {'PASS' if k['ok'] else 'FAIL'}  {k['check']}  ({k['detail']})")
    print(f"wrote {out / 'a11y.json'}")
    bad = rules["critical"] + rules["serious"]
    kb_fail = sum(1 for k in keyboard if not k["ok"])
    return 1 if bad or kb_fail else 0


if __name__ == "__main__":
    sys.exit(main())
