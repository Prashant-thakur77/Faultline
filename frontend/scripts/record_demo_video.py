"""
Records the demo video (docs/DEMO_SCRIPT.md) from the live UI with Playwright.

Real UI from real runs only: it presses Re-arm, runs S1 from the launcher, shows the gate,
runs the S6 preflight (before 1:50, rubric C2), approves the flag through the two-step approval
and asks the brain. S2 uses its labelled recorded replay. The UNKNOWN-verification beat (S9) is
shown from the rendered evals/RESULTS.md (the UI has no switch to break GitHub reads, and none is
faked). Caption numbers (G5 flow, preflight verdict, write-back n/m, S9, arms) are read from the
page, never hard-coded. Beat start times are written to <work>/meta.json.

Outputs:
  docs/media/demo.mp4        H.264 / yuv420p, 1920x1080
  docs/video_captions.srt    the captions shown, with their times
  docs/media/hero.gif        18 s: G2 rejection -> G5 rejection -> payment path (README top);
                             only with --gif (when the gate beats changed)

Usage (backend on :8400, production UI on --ui):
  .venv/bin/python frontend/scripts/record_demo_video.py --ui http://localhost:3100 \
      --chromium ~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEW = {"width": 1536, "height": 864}  # the script's 125 % zoom: recorded at 1536x864, upscaled to 1920x1080 by ffmpeg
VIDEO = {"width": 1920, "height": 1080}

CAPTION_JS = """
(text) => {
  let el = document.getElementById('__demo_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption';
    el.setAttribute('aria-hidden', 'true');
    Object.assign(el.style, {
      position: 'fixed', left: '50%', bottom: '18px', transform: 'translateX(-50%)', zIndex: 2147483647,
      width: 'max-content', maxWidth: 'min(1380px, 90vw)', padding: '10px 18px', borderRadius: '10px', pointerEvents: 'none',
      background: 'rgba(0,0,0,0.86)', color: '#fafafa', font: '600 21px/1.35 ui-sans-serif, system-ui, sans-serif',
      textAlign: 'center', boxShadow: '0 6px 24px rgba(0,0,0,.5)', border: '1px solid rgba(255,255,255,.18)',
    });
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.display = text ? 'block' : 'none';
}
"""

FLASH_JS = """
(el) => {
  const o = el.style.outline, f = el.style.outlineOffset;
  el.style.outline = '3px solid #38bdf8'; el.style.outlineOffset = '2px';
  setTimeout(() => { el.style.outline = o; el.style.outlineOffset = f; }, 1100);
}
"""


class Director:
    def __init__(self, page: Page, t_video: float):
        self.page = page
        self.t_video = t_video  # monotonic time the video started (page created)
        self.t0: float | None = None  # first frame we keep
        self.caps: list[tuple[float, float, str]] = []
        self.cur: tuple[float, str] | None = None
        self.marks: dict[str, float] = {}

    def now(self) -> float:
        return time.monotonic() - (self.t0 or time.monotonic())

    def start(self) -> None:
        self.t0 = time.monotonic()

    def caption(self, text: str) -> None:
        if self.cur:
            self.caps.append((self.cur[0], self.now(), self.cur[1]))
        self.cur = (self.now(), text) if text else None
        self.page.evaluate(CAPTION_JS, text)

    def reapply(self) -> None:
        self.page.evaluate(CAPTION_JS, self.cur[1] if self.cur else "")

    def go(self, url: str) -> None:
        self.page.goto(url)
        self.reapply()

    def until(self, t: float) -> None:
        """Hold the shot until t seconds into the kept video (no-op if already past)."""
        d = t - self.now()
        if d > 0:
            self.page.wait_for_timeout(int(d * 1000))

    def mark(self, k: str) -> None:
        self.marks[k] = self.now()

    def show(self, loc: Locator, block: str = "start") -> None:
        loc.evaluate(f"e => e.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
        self.page.wait_for_timeout(700)

    def click(self, loc: Locator) -> None:
        loc.scroll_into_view_if_needed()
        loc.evaluate(FLASH_JS)
        self.page.wait_for_timeout(450)
        loc.click()

    def finish(self) -> None:
        self.caption("")


def srt_time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def record(ui: str, chromium: str | None, work: Path) -> tuple[Path, Director]:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium) if chromium else p.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, record_video_dir=str(work), record_video_size=VIEW, device_scale_factor=1)
        page = ctx.new_page()
        d = Director(page, time.monotonic())
        page.set_default_timeout(30_000)

        # 0:00 title
        page.goto(f"{ui}/media/title.html")
        page.wait_for_timeout(300)
        d.start()
        d.caption("Faultline: an on-call agent whose brain is a FalkorDB graph. The model suggests; a read-only query decides.")
        d.until(6)

        # Re-arm
        d.go(f"{ui}/")
        d.mark("rearm")
        d.caption("Re-arm: restore the tenant graph from its golden copy and reset the simulated GitHub world.")
        d.click(page.get_by_role("button", name="Reset demo data (all visitors)"))
        d.click(page.get_by_role("button", name="Reset now"))
        expect(page.get_by_text(re.compile(r"Reset tenant_\w+ from golden_"))).to_be_visible(timeout=20_000)
        d.until(11)

        # Run S1
        d.mark("s1")
        d.caption("Run S1, “Checkout errors are spiking”, with the keyless baseline investigator: the stage rail moves INTAKE → RECALL → …")
        d.click(page.get_by_role("button", name=re.compile(r"Run scenario S1 with the baseline")))
        page.wait_for_url(re.compile(r"/incidents/inc-s1-"), timeout=30_000)
        d.reapply()
        incident_url = page.url
        expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=60_000)
        d.until(20)

        # Memory
        d.mark("memory")
        d.caption("First it remembers: past payment incidents found in FalkorDB's vector index and confirmed through a shared symptom node, never similarity alone.")
        d.show(page.locator("section[aria-labelledby='memory-h']"))
        d.until(28)

        # Ripple
        d.mark("ripple")
        d.caption("algo.BFS shows what breaks: payment red, the blast radius yellow, hop by hop.")
        d.show(page.locator("section[aria-labelledby='graph-h']"))
        d.click(page.get_by_role("button", name=re.compile(r"^Ripple")))
        d.until(36)

        # G2 rejection
        d.caption("Three changes in the window. The recommendation deploy has no causal path to checkout: Q-GATE-1 returns 0 rows. No path, no claim.")
        gate = page.locator("section[aria-labelledby='gate-h']")
        d.show(gate)
        d.mark("g2")
        d.click(gate.get_by_role("button", name=re.compile(r"Rejected by competitor sweep: G2")).first)
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Cypher", exact=True)).to_be_visible()
        d.reapply()
        page.wait_for_timeout(1000)
        d.click(dlg.get_by_role("button", name="Re-run (read-only)"))
        expect(dlg.get_by_text(re.compile(r"^0 rows\b")).first).to_be_visible(timeout=15_000)
        d.show(dlg.get_by_text(re.compile(r"^0 rows\b")).first, "center")
        d.until(48)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # G5 rejection (numbers read from the page)
        g5 = gate.get_by_role("button", name=re.compile(r"^G5 sufficiency: fail")).first
        detail = g5.text_content() or ""  # accessible name comes from the button content
        m = re.search(r"max flow ([\d.]+) < needed ([\d.]+)", detail)
        if not m:  # fail loudly: never record a caption with a number the page did not show
            raise SystemExit(f"G5 detail not found on the page: {detail!r}")
        flow, needed = m.group(1), m.group(2)
        d.caption(f"The email deploy shipped in the same minute and has a path. But algo.maxFlow says it carries at most {flow}; {needed} is needed. Rejected, with proof.")
        d.show(g5, "center")
        d.mark("g5")
        g5.evaluate(FLASH_JS)
        d.until(58)

        # Proof path + PROFILE
        d.caption("algo.SPpaths: D-pay-417 → payment → checkout, lit edge by edge. Every claim carries its Cypher, with PROFILE engine time.")
        d.show(page.locator("section[aria-labelledby='graph-h']"))
        d.click(page.get_by_role("button", name=re.compile(r"^Path")))
        page.wait_for_timeout(300)
        d.mark("path")
        replay = page.get_by_role("button", name="Replay path")
        if replay.count():
            d.click(replay)
        page.wait_for_timeout(4200)  # the path lights hop by hop
        d.click(gate.get_by_role("button", name=re.compile(r"^G2 path: pass")).last)
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Cypher", exact=True)).to_be_visible()
        d.reapply()
        d.click(dlg.get_by_role("button", name="PROFILE"))
        expect(dlg.get_by_text(re.compile(r"engine [\d.]+ ms")).first).to_be_visible(timeout=15_000)
        d.show(dlg.get_by_text("GRAPH.PROFILE").first, "start")
        d.until(71)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # S2 recorded replay (short)
        d.mark("s2")
        d.caption("Same graph, data incident (recorded replay): a payment provider cutover, traced into the revenue lineage.")
        d.go(f"{ui}/replay/s2-data-incident")
        expect(page.get_by_text("Recorded run · static files")).to_be_visible(timeout=15_000)
        d.click(page.get_by_role("radio", name="8×"))
        expect(page.get_by_text(re.compile(r"Event (\d+) / \1\b"))).to_be_visible(timeout=30_000)
        page.wait_for_timeout(300)
        fx = page.locator("section[aria-labelledby='gate-h']").get_by_role("button", name=re.compile(r"Rejected by competitor sweep: G5")).first
        d.show(fx, "center")
        fx_text = fx.text_content() or ""
        m = re.search(r"max flow ([\d.]+) < needed ([\d.]+)", fx_text)
        if not m:
            raise SystemExit(f"S2 FX G5 detail not found on the page: {fx_text!r}")
        else:
            d.caption(f"Same graph, data incident (recorded replay): the path crosses into the revenue lineage; the stale FX feed is ruled out by flow ({m.group(1)} < {m.group(2)}).")
        d.until(82)

        # Preflight (rubric C2: before 1:50)
        d.go(f"{ui}/preflight")
        d.mark("preflight")
        d.caption("Better still: the same graph scores the risky pull request before it ships: verdict, the ADRs it contradicts, the path to checkout, reviewers.")
        d.click(page.get_by_role("button", name=re.compile(r"S6: payment timeout 5000 ms")))
        expect(page.locator("[data-verdict]")).to_be_visible(timeout=20_000)
        pf_verdict = page.locator("[data-verdict]").first.get_attribute("data-verdict") or "?"
        page.wait_for_timeout(2500)
        d.show(page.locator("section[aria-labelledby='pf-assess-h']"))
        d.caption(f"Preflight verdict: {pf_verdict}. The same graph that explained the outage gates the next change before it merges.")
        d.until(96)

        # Containment
        d.go(incident_url)
        d.mark("containment")
        d.caption("Back to the incident. algo.maxFlow finds the smallest cut; a what-if on a GRAPH.COPY branch checks that it contains the failure first.")
        expect(page.locator("section[aria-labelledby='containment-h']").get_by_text("Min-cut", exact=False).first).to_be_visible(timeout=20_000)
        d.show(page.locator("section[aria-labelledby='containment-h']"))
        d.until(105)

        # Who fixes it
        d.mark("whofixes")
        d.caption("Who fixes it: the people who wrote this code and fixed the last outages here, ranked by harmonic centrality; bus factor and escalation tree.")
        d.show(page.locator("section[aria-labelledby='whofixes-h']"))
        d.until(113)

        # Choose
        d.mark("choose")
        plan = page.locator("section[aria-labelledby='plan-h']")
        d.caption("Choosing isn't approving: the server renders the exact diff, the PR body with reviewers, and the plan hash first.")
        d.show(plan)
        d.click(plan.locator("li", has_text="flag paymentGate").get_by_role("button", name=re.compile(r"^(Choose|Re-choose)$")))
        expect(plan.get_by_text("Exact action the server will take")).to_be_visible(timeout=20_000)
        d.show(page.locator("section[aria-label='Exact action']"))
        d.until(123)

        # Approve -> RESOLVED
        d.mark("approve")
        d.caption("Approve this exact change: one PR (simulated GitHub, labelled), verified through a second channel, then written back.")
        d.click(plan.get_by_role("button", name="Approve this exact action"))
        t_click = d.now()
        expect(plan.locator("[data-verdict]").first).to_be_visible(timeout=60_000)
        status = plan.get_by_role("status").filter(has_text=re.compile(r"write-back verified \d+/\d+"))
        expect(status).to_be_visible(timeout=60_000)
        verdict = plan.locator("[data-verdict]").first.get_attribute("data-verdict")
        d.show(plan.get_by_role("list", name="Action path after approval"), "center")
        d.until(t_click + 3.5)
        wb = re.search(r"verified (\d+/\d+)", status.inner_text())
        d.caption(f"{verdict}: GitHub main re-read and telemetry back in band, no collateral. Write-back verified {wb.group(1) if wb else '?'}; the incident becomes memory.")
        d.show(plan.locator("[data-verdict]").first, "start")
        page.wait_for_timeout(2500)
        d.show(status, "center")
        d.until(137)

        # UNKNOWN escalation (S9): shown from evals/RESULTS.md, verbatim; the UI has no switch to break GitHub reads.
        d.go(f"{ui}/media/results.html")
        d.mark("unknown")
        s9 = page.locator("li", has_text="S9 unknown verification").first
        s9_text = s9.inner_text()
        m9 = re.search(r"verdict (\w+), success written = (\w+)", s9_text)
        m9r = re.search(r"'(\w+)', '(APPLIED|NOT_APPLIED|UNKNOWN)', '(\d+/\d+)'", s9_text)
        if not (m9 and m9r):
            raise SystemExit(f"S9 line not parsed from RESULTS.md: {s9_text!r}")
        s9.evaluate("e => { e.style.background = 'rgba(56,189,248,.16)'; e.style.outline = '2px solid #38bdf8'; e.style.outlineOffset = '3px'; e.style.borderRadius = '4px'; }")
        d.show(s9, "center")
        # Only what the highlighted RESULTS.md line shows: verdict, success written, reconciler result.
        d.caption(
            f"And when verification can't confirm the change (S9, an eval run): verdict {m9.group(1) if m9 else '?'}, "
            f"success written = {m9.group(2) if m9 else '?'}. Never a silent success: a later reconciler pass → "
            f"{m9r.group(1) if m9r else '?'}, {m9r.group(2) if m9r else '?'} {m9r.group(3) if m9r else '?'}. (evals/RESULTS.md)"
        )
        d.until(147)

        # Brain
        d.go(f"{ui}/brain")
        d.mark("brain")
        d.caption("And it's the team's memory: every node an answer cites was read by that question's own queries, or the answer is withheld.")
        d.click(page.get_by_role("button", name="What breaks if productcatalog goes down?"))
        expect(page.get_by_text("citation guard ✓")).to_be_visible(timeout=20_000)
        d.until(158)

        # Results: arms table + per-scenario table; A3-noG5, A4 then V outlined (numbers read from the rendered RESULTS.md)
        d.go(f"{ui}/media/results.html")
        d.mark("results")

        def cell(row: str, col: int) -> str:
            return page.locator(f"tr[data-row='{row}'] td").nth(col).inner_text().strip()

        def outline(row: str, colour: str) -> None:
            page.locator(f"tr[data-row='{row}']").evaluate(f"e => {{ e.style.outline = '2px solid {colour}'; e.style.outlineOffset = '-2px'; }}")

        def clear(row: str) -> None:
            page.locator(f"tr[data-row='{row}']").evaluate("e => { e.style.outline = ''; }")

        # Per-scenario table columns: scenario | N | V | A2 | A3 | A3-noG5 | A4
        sc = {s: {"V": cell(s, 2), "A3": cell(s, 4), "noG5": cell(s, 5)} for s in ("S1", "S2", "S3", "S3b")}
        # The captions below describe these cells; refuse to record a caption the page contradicts.
        assert sc["S2"]["noG5"] == "0.0" and sc["S1"]["noG5"] == "1.0", sc
        assert all(sc[s]["V"] == "0.0" for s in ("S2", "S3", "S3b")) and sc["S1"]["V"] == "1.0", sc
        d.show(page.locator("h2", has_text="Arms"), "start")
        outline("A4", "#f87171")
        outline("A3-noG5", "#fbbf24")
        outline("S1", "#fbbf24")
        outline("S2", "#fbbf24")
        d.caption(
            f"FalkorDB off (A4): {cell('A4', 7)} confirmed causes. Max-flow check off (A3-noG5): top-1 {cell('A3-noG5', 2)}. "
            f"S2 can no longer be decided ({sc['S2']['noG5']}); S1 still is ({sc['S1']['noG5']}): the sweep's origin test rejects the healthy email service."
        )
        d.until(167)
        for r in ("A4", "A3-noG5", "S1", "S2"):
            clear(r)
        outline("V", "#a78bfa")
        for r in ("S2", "S3", "S3b"):
            outline(r, "#a78bfa")
        d.caption(
            f"Vector similarity only (V): top-1 {cell('V', 2)}; it picks the wrong change on S2, S3 and S3b. "
            f"Naive recency: {cell('N', 2)}. The graph (A3): {cell('A3', 2)}. (evals/RESULTS.md)"
        )
        d.until(175)
        d.go(f"{ui}/media/title.html")
        d.mark("end")
        d.caption("Faultline: no path, no claim. Verify it yourself: make judge-check.")
        d.until(179.0)
        d.finish()

        video = page.video.path() if page.video else None
        ctx.close()
        browser.close()
    if not video:
        raise SystemExit("no video recorded")
    d.offset = d.t0 - d.t_video  # seconds of pre-roll to trim
    return Path(video), d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui", default="http://localhost:3100")
    ap.add_argument("--chromium", default=None)
    ap.add_argument("--work", default=str(ROOT / "tmp" / "demo-video"))
    ap.add_argument("--gif", action="store_true", help="also regenerate docs/media/hero.gif (only when the gate beats changed)")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    webm, d = record(a.ui, a.chromium, work)
    media = ROOT / "docs" / "media"
    media.mkdir(parents=True, exist_ok=True)
    mp4 = media / "demo.mp4"
    ff = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{d.offset:.3f}", "-i", str(webm), "-t", "180",
                    "-vf", f"scale={VIDEO['width']}:{VIDEO['height']}:flags=lanczos",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-r", "30",
                    "-movflags", "+faststart", "-an", str(mp4)], check=True)
    srt = ROOT / "docs" / "video_captions.srt"
    srt.write_text("".join(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n\n" for i, (s, e, t) in enumerate(d.caps, 1)))
    # Hero GIF: 6 s each of G2 rejection, G5 rejection, payment path (cut from the same recording).
    segs = [(d.marks["g2"], 6.0), (d.marks["g5"] - 0.5, 6.0), (d.marks["path"], 6.0)]
    gif = media / "hero.gif"
    if not a.gif:
        segs = []
    parts = "".join(f"[0:v]trim=start={s:.2f}:duration={n},setpts=PTS-STARTPTS[v{i}];" for i, (s, n) in enumerate(segs))
    concat = "".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps=8,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    if segs:
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(mp4), "-filter_complex", parts + concat, str(gif)], check=True)
    meta = {"webm": str(webm), "offset_s": round(d.offset, 3), "captions": len(d.caps), "marks": {k: round(v, 2) for k, v in d.marks.items()}}
    (work / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    sys.exit(main())
