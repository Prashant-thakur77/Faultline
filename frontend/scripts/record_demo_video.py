"""
Records the 3:00 demo video (docs/DEMO_SCRIPT.md) from the real UI with Playwright.

Real UI from real runs only. Before the kept footage starts (pre-roll, trimmed), it checks the API, re-arms the tenant
(with the confirm step), runs S1 from the launcher and reads every value the captions will state, so a missing
element fails the take before anything is recorded. The video then opens on a hook card laid over the finished
incident room and walks the beat sheet: the G2 rejection re-run read-only (0 rows), the crew, the G5 flow bound, the
proof path and its provenance, containment and who fixes it, the two-step approval to APPLIED and RESOLVED with the
pull request on github.com, "Break it", the preflight block and reversal guard, the company brain, the proof charts,
the live deployment and the end card.

Numbers: every number in a caption is read from the page at record time or from evals/results/latest.json; none is
typed here. A value that is missing or contradicts the caption stops the recording (fail loudly).

Real GitHub (--real-github): the API must run with FAULTLINE_GITHUB=real and FAULTLINE_APPROVER_KEY. The recorder
reads the approver key from the file named in $FAULTLINE_APPROVER_KEY_FILE, types it into the password-type approver
key field (masked with CSS if the field were ever plain text) and never prints it. It refuses to start unless the
flag is "on" at main of the demo infra repo (gh api), since otherwise the run would be a no-op; after a real take the
flag is off at main and must be turned back on in that repo before another real take. Without --real-github the run
uses the API's simulated GitHub (labelled "(simulated)" in the UI) and the caption says so; the github.com shot then
shows the real PR that the same path opened earlier (checked MERGED with gh first).

Outputs:
  docs/media/demo.mp4        H.264 / yuv420p, 1920x1080 (1536x864 viewport, upscaled)
  docs/video_captions.srt    every caption with its time (cards included, which are not burned in)
  docs/media/hero.gif        G2 rejection -> G5 rejection -> proof path; only with --gif
  <work>/meta.json           beat marks, lateness per beat, the facts read from the page
With --no-encode (dry run) only <work>/ is written: the raw .webm, captions.srt and meta.json.

Usage (API on --api, production UI on --ui, built after any change under frontend/public):
  .venv/bin/python frontend/scripts/record_demo_video.py --ui http://localhost:3100 --api http://localhost:8400 \
      [--real-github] [--gif] [--no-encode] [--chromium <path to chrome-headless-shell>]
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_MEDIA = ROOT / "frontend" / "public" / "media"
DOCS_CHARTS = ROOT / "docs" / "media" / "charts"
LATEST = ROOT / "evals" / "results" / "latest.json"
VIEW = {"width": 1536, "height": 864}  # the 125 % zoom of a 1920x1080 screen; upscaled to 1080p by ffmpeg
VIDEO = {"width": 1920, "height": 1080}
LENGTH = 180.0

# Beat starts in seconds of kept video (docs/DEMO_SCRIPT.md). Each shot is held until the next beat's start; a beat
# that starts late is logged in meta.json, and the chart beat absorbs the slack so the end card still lands on time.
BEATS = {"hook": 0, "g2": 8, "crew": 20, "g5": 32, "path": 44, "contain": 56, "act": 66, "breakit": 84,
         "preflight": 96, "brain": 108, "charts": 120, "live": 156, "end": 170}
CHARTS = ["outcome", "false_blame", "ladder", "context_mrr", "live"]  # shown in this order when present
MIN_CHART_S = 4.0

DEFAULTS = {
    "infra_repo": "Prashant-thakur77/faultline-demo-infra",
    "flag": "paymentGate",
    "real_pr": "https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1",
    "live_url": "https://13-203-185-119.sslip.io",
    "issue": "FalkorDB/FalkorDB#3349",
    "brain_question": "Who decided the payment timeout, and are they still here?",
    "tenant": "acme",
    "scenario": "S1",
    "distractor_path": "D-rec-12",    # rejected by G2 (no path)
    "distractor_flow": "D-email-88",  # rejected by G5 (not enough flow)
    "pg_choice": r"^Remove the call payment",
}

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
      background: 'rgba(0,0,0,0.86)', color: '#fafafa', font: '600 21px/1.35 Inter, ui-sans-serif, system-ui, sans-serif',
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
  setTimeout(() => { el.style.outline = o; el.style.outlineOffset = f; }, 1400);
}
"""

# The hook card is laid over the finished incident room (no reload when it lifts). Resolves to whether Mona Sans loaded.
CARD_JS = """
(src) => new Promise((resolve) => {
  const f = document.createElement('iframe');
  f.id = '__demo_card'; f.src = src; f.tabIndex = -1; f.setAttribute('aria-hidden', 'true');
  Object.assign(f.style, { position: 'fixed', inset: '0', width: '100vw', height: '100vh', border: '0',
                           zIndex: 2147483646, background: '#08090a', transition: 'opacity .45s ease' });
  f.onload = async () => {
    const doc = f.contentDocument;
    try { await doc.fonts.ready; } catch (e) {}
    resolve([...doc.fonts].some((x) => x.family.replace(/["']/g, '') === 'Mona Sans' && x.status === 'loaded'));
  };
  document.body.appendChild(f);
})
"""

ADDR_JS = """
(url) => {
  let el = document.getElementById('__demo_addr');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_addr';
    el.setAttribute('aria-hidden', 'true');
    Object.assign(el.style, {
      position: 'fixed', left: '50%', top: '66px', transform: 'translateX(-50%)', zIndex: 2147483647, pointerEvents: 'none',
      padding: '8px 16px', borderRadius: '999px', background: 'rgba(0,0,0,0.88)', border: '1px solid rgba(255,255,255,.22)',
      color: '#fafafa', font: '600 20px/1.2 ui-monospace, monospace', boxShadow: '0 10px 30px rgba(0,0,0,.5)',
    });
    document.body.appendChild(el);
  }
  el.textContent = 'URL  ' + url;
}
"""

# Only if the approver key field were ever plain text: hide what is typed (the field is type=password today).
MASK_JS = "e => { e.style.webkitTextSecurity = 'disc'; e.style.filter = 'blur(6px)'; }"


def fail(msg: str) -> SystemExit:
    return SystemExit(f"record_demo_video: {msg}")


class Director:
    def __init__(self, page: Page, t_video: float):
        self.page = page
        self.t_video = t_video  # monotonic time the video started (page created)
        self.t0: float | None = None  # first frame we keep
        self.caps: list[tuple[float, float, str]] = []
        self.cur: tuple[float, str] | None = None
        self.burned = ""
        self.marks: dict[str, float] = {}
        self.late: dict[str, float] = {}
        self.offset = 0.0

    def now(self) -> float:
        return time.monotonic() - (self.t0 or time.monotonic())

    def start(self) -> None:
        self.t0 = time.monotonic()

    def caption(self, text: str, burn: bool = True) -> None:
        """Show a caption (burned into the video) and log it for the .srt. burn=False: .srt only (the cards)."""
        if self.cur:
            self.caps.append((self.cur[0], self.now(), self.cur[1]))
        self.cur = (self.now(), text) if text else None
        self.burned = text if burn else ""
        self.page.evaluate(CAPTION_JS, self.burned)

    def reapply(self) -> None:
        self.page.evaluate(CAPTION_JS, self.burned)

    def go(self, url: str) -> None:
        self.page.goto(url)
        self.reapply()

    def until(self, t: float) -> None:
        """Hold the shot until t seconds into the kept video (no-op if already past)."""
        d = t - self.now()
        if d > 0:
            self.page.wait_for_timeout(int(d * 1000))

    def beat(self, key: str) -> None:
        """Start a beat: wait for its planned start, mark it, and log how late it began."""
        self.until(BEATS[key])
        self.marks[key] = self.now()
        late = self.now() - BEATS[key]
        if late > 0.75:
            self.late[key] = round(late, 2)
            print(f"  beat {key} started {late:.1f} s late", file=sys.stderr)

    def mark(self, k: str) -> None:
        self.marks[k] = self.now()

    def show(self, loc: Locator, block: str = "start") -> None:
        loc.evaluate(f"e => e.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
        self.page.wait_for_timeout(700)

    def flash(self, loc: Locator) -> None:
        loc.evaluate(FLASH_JS)

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


# ------------------------------------------------------------------ checks before the browser starts (fail early)

def http_get(url: str, timeout: float = 15.0) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - our own servers / the live demo
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        raise fail(f"GET {url} failed: {e}") from None


def check_api(api: str, tenant: str) -> dict:
    st = json.loads(http_get(f"{api.rstrip('/')}/api/status?tenant={tenant}"))
    if st.get("status") != "ok":
        raise fail(f"the API says FalkorDB is not ready for {tenant}: {st.get('reason') or st.get('status')}")
    if st.get("graph_disabled"):
        raise fail("the API runs with FAULTLINE_DISABLE_GRAPH=true (A4 ablation); the demo needs the graph")
    return st


def check_media(ui: str, charts: list[str]) -> None:
    """The static pages must be served by the running UI (Next serves public/ files present at build time)."""
    for name in ["hook.html", "proof.html", "open.html", "end.html", *[f"charts/{c}.svg" for c in charts]]:
        http_get(f"{ui.rstrip('/')}/media/{name}")


def chart_list() -> list[str]:
    """Charts in docs/media/charts (the source) whose public copy is byte-identical; a stale copy stops the take."""
    out = []
    for c in CHARTS:
        src, dst = DOCS_CHARTS / f"{c}.svg", PUBLIC_MEDIA / "charts" / f"{c}.svg"
        if not src.exists():
            continue
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            raise fail(f"frontend/public/media/charts/{c}.svg differs from docs/media/charts/{c}.svg: "
                       "cp docs/media/charts/*.svg frontend/public/media/charts/ and rebuild the UI")
        out.append(c)
    if not {"outcome", "false_blame", "ladder", "context_mrr"} <= set(out):
        raise fail(f"proof charts missing from docs/media/charts (have {out}); run scripts/gen_charts.py")
    return out


def pct(v: float) -> str:
    """As scripts/gen_charts.py labels its bars, so the caption reads the same as the chart."""
    return f"{v * 100:.0f}%" if abs(v * 100 - round(v * 100)) < 0.05 else f"{v * 100:.1f}%"


def chart_captions(charts: list[str]) -> dict[str, str]:
    """Each chart's headline with its numbers, read from evals/results/latest.json now (the charts' own source)."""
    d = json.loads(LATEST.read_text())

    def g(k: str) -> Any:
        if k not in d:
            raise fail(f"{k} is not in evals/results/latest.json; the chart caption would have no source")
        return d[k]

    caps = {
        "outcome": (f"Right verdict on the scenario suite ({g('arm.A3.trials')} trials): Faultline "
                    f"{pct(g('arm.A3.outcome_correct_rate'))}; telemetry only {pct(g('arm.T.outcome_correct_rate'))}, "
                    f"vector similarity {pct(g('arm.V.outcome_correct_rate'))}, naive recency "
                    f"{pct(g('arm.N.outcome_correct_rate'))}. FalkorDB switched off confirms "
                    f"{g('arm.A4.confirmed_causes')} causes."),
        "false_blame": (f"Confidently blaming the wrong change: Faultline {pct(g('arm.A3.false_blame_rate'))}; "
                        f"telemetry only {pct(g('arm.T.false_blame_rate'))}, vector similarity "
                        f"{pct(g('arm.V.false_blame_rate'))}, naive recency {pct(g('arm.N.false_blame_rate'))}."),
        "context_mrr": (f"Context for any agent, unrelated deploys crowding the window: the true cause ranks far higher "
                        f"in the graph's context pack (MRR {g('ctx.busy30.b1000.GA.mrr'):.2f}) than in vector RAG "
                        f"({g('ctx.busy30.b1000.V.mrr'):.2f}) or by recency ({g('ctx.busy30.b1000.R.mrr'):.2f})."),
    }
    rungs = ["full", "no_maxflow", "no_sppaths", "neither"]
    wrong = {g(f"ladder.{r}.wrong_confident") for r in rungs}
    caps["ladder"] = (f"Take FalkorDB's algorithms away: correct verdicts on {g('ladder.full.cases')} held-out worlds fall "
                      f"from {g('ladder.full.correct')} to {g('ladder.no_maxflow.correct')} without algo.maxFlow, "
                      f"{g('ladder.no_sppaths.correct')} without algo.SPpaths, {g('ladder.neither.correct')} without both"
                      + (f"; confident wrong blames stay at {wrong.pop()}." if len(wrong) == 1 else "."))
    if "live" in charts:
        n = g("live.hero.n")
        caps["live"] = (f"The live deployment, measured over HTTPS: right cause {g('live.hero.cause_correct')}/{n}, "
                        f"verified APPLIED {g('live.hero.applied')}/{n}; alert to RESOLVED p50 "
                        f"{g('live.hero.total_ms_p50'):,.0f} ms.")
    return {c: caps[c] for c in charts}


def check_open_card(live_url: str) -> None:
    """open.html must show the exact MCP one-liner of docs/MCP.md and the live URL being recorded."""
    page = (PUBLIC_MEDIA / "open.html").read_text()
    m = re.search(r'<pre id="mcp">(.*?)</pre>', page, re.S)
    doc = (ROOT / "docs" / "MCP.md").read_text()
    b = re.search(r"```bash\n(claude mcp add --transport http faultline-live .*?)\n```", doc, re.S)
    if not (m and b) or html.unescape(m.group(1)).split() != b.group(1).split():
        raise fail("the MCP one-liner in frontend/public/media/open.html differs from docs/MCP.md; copy it across")
    live = re.search(r'<span class="url" id="live">(.*?)</span>', page)
    if not live or live.group(1).rstrip("/") != live_url.rstrip("/"):
        raise fail(f"open.html shows {live.group(1) if live else 'no'} live URL, the recording uses {live_url}")


def gh(*args: str) -> Any:
    exe = shutil.which("gh")
    if not exe:
        raise fail("the GitHub CLI (gh) is needed to check the PR, the flag and the upstream issue")
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise fail(f"gh {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def flag_state(repo: str, flag: str) -> str | None:
    d = gh("api", f"repos/{repo}/contents/flags.json?ref=main")
    doc = json.loads(base64.b64decode(d["content"]))
    return ((doc.get("flags") or {}).get(flag) or {}).get("state")


def pr_merged(url: str, wait_s: float = 0.0) -> dict:
    t_end = time.monotonic() + wait_s
    while True:
        pr = gh("pr", "view", url, "--json", "state,mergedAt,url,title,number")
        if pr.get("state") == "MERGED" or time.monotonic() >= t_end:
            break
        time.sleep(2)
    if pr.get("state") != "MERGED":
        raise fail(f"{url} is in state {pr.get('state')}, not merged; the caption would be false")
    return pr


def issue_info(ref: str) -> dict:
    repo, num = ref.split("#")
    return gh("issue", "view", num, "-R", repo, "--json", "title,state,url,number")


def read_key() -> str:
    path = os.environ.get("FAULTLINE_APPROVER_KEY_FILE")
    if not path:
        raise fail("--real-github needs FAULTLINE_APPROVER_KEY_FILE (a file holding the approver key)")
    try:
        key = Path(path).expanduser().read_text().strip()
    except OSError as e:
        raise fail(f"cannot read the approver key file named in FAULTLINE_APPROVER_KEY_FILE: {e.strerror}") from None
    if not key:
        raise fail("the approver key file is empty")
    if re.search(r"pw:", os.environ.get("DEBUG", "")) or os.environ.get("PWDEBUG"):
        raise fail("unset DEBUG/PWDEBUG for a real-GitHub take: Playwright's API log could echo the typed key")
    return key


# ------------------------------------------------------------------ page readers (fail loudly when absent)

def flow_numbers(btn: Locator, what: str) -> tuple[str, str]:
    detail = btn.text_content() or ""
    m = re.search(r"max flow ([\d.]+) < needed ([\d.]+)", detail)
    if not m:
        raise fail(f"{what}: G5 detail not found on the page: {detail!r}")
    return m.group(1), m.group(2)


def first_changed(page: Page) -> tuple[str, str, str]:
    rows = page.locator("section[aria-labelledby='pg-diff'] tbody tr").filter(has_text="(changed)")
    if not rows.count():
        raise fail("Break it: the page shows no changed decision")
    r = rows.first
    name = (r.locator("th").inner_text() or "").replace("(changed)", "").strip()
    before, after = (r.locator("td").nth(i).inner_text().strip() for i in (0, 1))

    def cut(s: str) -> str:
        return s if len(s) <= 64 else s[:63].rstrip() + "…"

    return name, cut(before), cut(after)


def system_facts(page: Page) -> dict[str, str]:
    dl = page.locator("dl[aria-label='Live system status']").first
    dts, dds = dl.locator("dt").all_inner_texts(), dl.locator("dd").all_inner_texts()
    return {k.strip(): v.strip() for k, v in zip(dts, dds)}


# ------------------------------------------------------------------ the recording

def record(a: argparse.Namespace, work: Path, charts: list[str], chart_caps: dict[str, str], issue: dict,
           key: str | None) -> tuple[Path, Director, dict]:
    ui = a.ui.rstrip("/")
    facts: dict[str, Any] = {"real_github": a.real_github, "key_field_masked": False}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chromium) if a.chromium else p.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, record_video_dir=str(work), record_video_size=VIEW, device_scale_factor=1)
        # the home intro (odometer) plays once per tab; the video never needs it
        ctx.add_init_script("try { sessionStorage.setItem('fl-intro', '1'); } catch (e) {}")
        page = ctx.new_page()
        d = Director(page, time.monotonic())
        page.set_default_timeout(30_000)

        # ---------------- pre-roll (trimmed): status, re-arm with its confirm step, run S1, read every caption value
        page.goto(f"{ui}/?tenant={a.tenant}")
        ready = page.get_by_text("FalkorDB ready").first
        down = page.get_by_text(re.compile(r"^(API unreachable|FalkorDB unavailable)$")).first
        expect(ready.or_(down).first).to_be_visible(timeout=30_000)
        if down.is_visible():
            raise fail(f"the UI says {down.inner_text()!r}; start FalkorDB and the API first")
        page.get_by_role("button", name=re.compile(r"system details")).click()
        page.get_by_role("button", name="Reset demo data (all visitors)").click()
        page.get_by_role("group", name="Confirm reset").get_by_role("button", name="Reset now").click()
        ok = page.get_by_text(re.compile(r"^Reset tenant_\w+ from golden_\w+"))
        bad = page.get_by_role("alert").filter(has_text=re.compile(r"Reset (rate-limited|failed)"))
        expect(ok.or_(bad).first).to_be_visible(timeout=30_000)
        if bad.count():
            raise fail(f"re-arm did not happen: {bad.first.inner_text()}")
        facts["rearm"] = ok.first.inner_text()
        page.keyboard.press("Escape")

        page.get_by_role("button", name=re.compile(rf"^Run scenario {a.scenario} with the baseline investigator$")).click()
        page.wait_for_url(re.compile(rf"/incidents/inc-{a.scenario.lower()}-"), timeout=60_000)
        expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=120_000)
        facts["incident_url"] = page.url

        gate = page.locator("section[aria-labelledby='gate-h']")
        rej = (gate.get_by_role("listitem").filter(has_text=a.distractor_path)
               .get_by_role("button", name=re.compile(r"^Rejected by .*\bG2\b")).first)
        expect(rej).to_be_visible()
        tpl = re.search(r"\bQ-[A-Z0-9-]+\b", rej.inner_text())
        facts["g2_template"] = tpl.group(0) if tpl else None
        g5 = (gate.get_by_role("list", name=re.compile(rf"^Checks for {re.escape(a.distractor_flow)}\b"))
              .get_by_role("button", name=re.compile(r"^G5 sufficiency: fail")).first)
        expect(g5).to_be_visible()
        flow, needed = flow_numbers(g5, a.distractor_flow)
        root = page.locator("section[aria-labelledby='root-h']")
        chain = root.get_by_role("list", name="Mechanism chain").get_by_role("button").all_inner_texts()
        if len(chain) < 2:
            raise fail(f"no mechanism chain on the page: {chain}")
        why = root.get_by_role("button", name="Why do you believe this?")
        expect(why).to_be_enabled()
        crew = page.locator("section[aria-labelledby='crew-h']")
        crew_chip = crew.get_by_text(re.compile(r"^\d+ steps · \d+ specialists$")).first
        if not crew_chip.count():
            raise fail("crew board not recorded for this run (no 'N steps · M specialists' on the page)")
        crew_meta = crew_chip.inner_text().strip()
        contain = page.locator("section[aria-labelledby='containment-h']")
        cut_rows = contain.get_by_role("table", name=re.compile(r"^Edges in the minimum cut"))
        expect(cut_rows).to_be_visible(timeout=30_000)
        cut_edges = [t.split("\t")[0].strip() for t in cut_rows.locator("tbody tr").all_inner_texts()]
        verdict_chip = contain.get_by_text(re.compile(r"^(contains|does not contain)$")).first
        whatif = verdict_chip.inner_text().strip() if verdict_chip.count() else None
        if not cut_edges or not whatif:
            raise fail(f"containment incomplete on the page: cut {cut_edges}, what-if {whatif}")
        who = page.locator("section[aria-labelledby='whofixes-h']")
        top = who.get_by_role("list", name="People ranked by the graph").get_by_role("listitem").first
        expect(top).to_be_visible()
        top_name = top.locator("span.font-semibold").first.inner_text().strip()
        top_id = top.locator("span.font-mono").nth(1).inner_text().strip()
        plan = page.locator("section[aria-labelledby='plan-h']")
        opt = (plan.get_by_role("list", name="Action options").get_by_role("listitem")
               .filter(has_text=f"flag {a.flag}").first)
        choose = opt.get_by_role("button", name=re.compile(r"^(Choose|Re-choose)$"))
        if not choose.count():
            raise fail(f"the option 'flag {a.flag}' is not offered (is the flag already off at GitHub main?)")
        facts.update(g5={"flow": flow, "needed": needed}, chain=chain, crew=crew_meta, cut=cut_edges, whatif=whatif,
                     who=f"{top_name} ({top_id})")

        # ---------------- 0:00 hook card, laid over the finished incident room
        mona = page.evaluate(CARD_JS, f"{ui}/media/hook.html")
        if not mona:
            print("  warning: Mona Sans did not load on the hook card (offline?); a fallback face is shown",
                  file=sys.stderr)
        d.start()
        d.mark("hook")
        page.evaluate("() => document.getElementById('__demo_card').contentWindow.__go()")
        d.caption("Roughly 70% of outages come from changes (Site Reliability Engineering, Google). "
                  "Two deploys land in the same minute. Which one broke checkout?", burn=False)

        # ---------------- 0:08 G2: no path, no claim (re-run read-only, 0 rows)
        d.beat("g2")
        page.evaluate("() => { const f = document.getElementById('__demo_card'); f.style.opacity = '0';"
                      " setTimeout(() => f.remove(), 500); }")
        d.caption(f"Checkout is failing and several deploys are in the window. Could {a.distractor_path} be the cause? "
                  f"Ask FalkorDB for a causal path to checkout"
                  f"{' (' + facts['g2_template'] + ')' if facts['g2_template'] else ''}, read-only.")
        d.show(gate)
        d.click(rej)
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Cypher", exact=True)).to_be_visible()
        d.reapply()
        page.wait_for_timeout(900)
        d.click(dlg.get_by_role("button", name="Re-run (read-only)"))
        res = dlg.get_by_role("region", name="Re-run result")
        rows = res.get_by_text(re.compile(r"^\d+ rows?$")).first
        err = res.get_by_role("alert").first
        expect(rows.or_(err).first).to_be_visible(timeout=20_000)
        if err.count() and err.is_visible():
            raise fail(f"G2 re-run failed: {err.inner_text()}")
        n_rows = rows.inner_text().strip()
        if not n_rows.startswith("0 "):
            raise fail(f"G2 re-run for {a.distractor_path} returned {n_rows}; the caption says no path")
        zero = res.get_by_text(re.compile(r"^0 rows\. For a G2 path query"))
        d.show(zero, "center")
        d.flash(zero)
        d.caption(f"No path, no claim: FalkorDB returns no causal path from {a.distractor_path} to checkout "
                  f"({n_rows}), so it cannot be blamed.")
        d.until(19.3)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---------------- 0:20 how the run got here: stage rail + crew board
        d.beat("crew")
        d.caption(f"How it got here: a crew of least-privilege agents ({crew_meta}). "
                  "Every step is a record in the graph: who claimed it, what it ran, who it handed to.")
        d.flash(page.locator("#pane-timeline"))
        d.show(crew)
        lanes = crew.get_by_role("article")
        if lanes.count():
            d.flash(lanes.first)
        d.until(26)
        if lanes.count() > 2:
            d.show(lanes.nth(2), "center")
            d.flash(lanes.nth(2))

        # ---------------- 0:32 G5: a path, but not enough flow
        d.beat("g5")
        d.caption(f"{a.distractor_flow} shipped in the same minute and has a path. But algo.maxFlow says it can carry "
                  f"only {flow} of the {needed} needed. Rejected.")
        d.show(g5, "center")
        d.flash(g5)
        d.until(38)
        d.click(g5)
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Cypher", exact=True)).to_be_visible()
        d.reapply()
        d.until(43.5)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---------------- 0:44 the proof path, then provenance ("Why do you believe this?")
        d.beat("path")
        graph = page.locator("section[aria-labelledby='graph-h']")
        d.caption(f"The proof path, lit edge by edge: {' → '.join(chain)}.")
        d.show(graph)
        mode = graph.get_by_role("group", name="Graph view mode").get_by_role("button", name=re.compile(r"^Path"))
        if mode.get_attribute("aria-pressed") != "true":
            d.click(mode)
        replay = graph.get_by_role("button", name="Replay path")
        if replay.count():
            d.click(replay)
        page.wait_for_timeout(4200)  # the path lights hop by hop
        d.show(root)
        d.click(why)
        prov = page.get_by_role("dialog", name="Why do you believe this?")
        counts = prov.get_by_text(re.compile(r"^\d+ evidence · \d+ calls · \d+ agents$"))
        perr = prov.get_by_role("alert")
        expect(counts.or_(perr).first).to_be_visible(timeout=20_000)
        if perr.count():
            raise fail(f"provenance unavailable: {perr.first.inner_text()}")
        facts["provenance"] = counts.inner_text().strip()
        d.caption(f"Why do you believe this? Provenance from the verdict back to the tool calls and agents that "
                  f"produced each piece of evidence ({facts['provenance']}), every arrow a stored edge.")
        d.until(55.4)
        prov.get_by_role("button", name="Close: why do you believe this").click()
        page.wait_for_timeout(300)

        # ---------------- 0:56 containment (min-cut + what-if on GRAPH.COPY), then who fixes it
        d.beat("contain")
        d.caption(f"Smallest containment: cut {', '.join(cut_edges)} (algo.maxFlow min-cut). A what-if on a GRAPH.COPY "
                  f"branch checks it first: {whatif}.")
        d.show(contain)
        d.flash(cut_rows)
        d.until(61)
        d.caption(f"Who fixes it: {top_name} ({top_id}) first, ranked by algo.HarmonicCentrality over who wrote this "
                  "code and fixed past outages here.")
        d.show(who)
        d.flash(top)

        # ---------------- 1:06 two-step approval -> APPLIED -> write-back -> RESOLVED -> the PR on github.com
        d.beat("act")
        d.caption("Choosing isn't approving: the server first renders the exact diff, the PR body and the plan hash.")
        d.show(plan)
        d.click(choose)
        exact = plan.get_by_role("region", name="Exact action")
        expect(exact).to_be_visible(timeout=20_000)
        d.show(exact)
        bound = plan.get_by_text(re.compile(r"Approval is bound to plan hash")).first
        mh = re.search(r"plan hash\s+([0-9a-f]{6,})", bound.inner_text())
        if not mh:
            raise fail(f"plan hash not shown: {bound.inner_text()!r}")
        facts["plan_hash"] = mh.group(1)
        d.caption(f"Approve this exact action, bound to plan hash {mh.group(1)}: if the plan changes, the server refuses it.")
        d.show(bound, "center")
        d.until(BEATS["act"] + 5)
        if key is not None:
            plan.get_by_text("Approver key (only when the server acts on real GitHub)").click()
            field = plan.get_by_label(re.compile(r"^X-Faultline-Approver-Key"))
            try:
                expect(field).to_be_visible()
                if field.get_attribute("type") != "password":
                    field.evaluate(MASK_JS)
                    facts["key_field_masked"] = True
                    print("  note: the approver key field is not type=password; masked with CSS", file=sys.stderr)
                field.press_sequentially(key, delay=25)
            except Exception as e:  # noqa: BLE001 - never let an error message carry the key
                raise fail(f"could not enter the approver key ({type(e).__name__}; value not shown)") from None
            page.wait_for_timeout(500)
        approve = plan.get_by_role("button", name="Approve this exact action")
        d.click(approve)
        d.caption("Approved: the one write tool opens the pull request, then VERIFY checks it through a second channel.")
        big = plan.locator("[data-verdict]").first
        expect(big).to_be_visible(timeout=240_000 if key else 60_000)
        status = plan.get_by_role("status").filter(has_text=re.compile(r"write-back verified \d+\/\d+"))
        expect(status).to_be_visible(timeout=240_000 if key else 60_000)
        verdict = big.get_attribute("data-verdict")
        wb = re.search(r"verified (\d+/\d+)", status.inner_text())
        if verdict != "APPLIED" or not wb:
            raise fail(f"the action ended {verdict} ({status.inner_text()!r}); the take expects APPLIED")
        if not re.search(r"^\s*resolved\b", status.inner_text(), re.I | re.M):  # not "tracked in issue", not escalated
            raise fail(f"the incident did not end RESOLVED: {status.inner_text()!r}")
        chan = plan.get_by_role("list", name="Verification channels").inner_text()
        seen = [w for w, rx in (("GitHub main re-read", r"GitHub main HEAD\s+ok"), ("telemetry back in band", r"Telemetry\s+ok"))
                if re.search(rx, chan)]
        if not seen:
            raise fail(f"APPLIED without a second channel on the page: {chan!r}")
        link = plan.get_by_role("link", name=re.compile(r"github\.com\/\S+\/pull\/\d+"))
        simulated = plan.get_by_text("(simulated)", exact=True)
        if key is not None and not link.count():
            raise fail("--real-github, but the UI shows a simulated PR: start the API with FAULTLINE_GITHUB=real")
        facts.update(verdict=verdict, writeback=wb.group(1), channels=seen)
        d.show(plan.get_by_role("list", name="Action path after approval"), "center")
        d.caption(f"{verdict}: {' and '.join(seen)}. Write-back verified {wb.group(1)}: RESOLVED, "
                  "and the incident becomes memory.")
        d.show(status, "center")
        d.flash(status)
        page.wait_for_timeout(3000)
        if link.count():
            pr_url = (link.first.get_attribute("href") or "").strip()
            pr = pr_merged(pr_url, wait_s=20)
            d.flash(link.first)
            page.wait_for_timeout(1200)
            page.goto(pr_url, wait_until="domcontentloaded")
            page.evaluate(ADDR_JS, page.url)
            d.caption(f"A real pull request (#{pr['number']}), merged after two-step approval and verified through a "
                      f"second channel: {verdict}.")
        else:
            if not simulated.count():
                raise fail("no PR reference on the page after APPLIED")
            d.flash(simulated.first)
            page.wait_for_timeout(1200)
            pr = pr_merged(a.real_pr)
            page.goto(pr["url"], wait_until="domcontentloaded")
            page.evaluate(ADDR_JS, page.url)
            d.caption(f"This take used the simulated GitHub (labelled). The same path against real GitHub opened and "
                      f"merged this pull request (#{pr['number']}), verified APPLIED.")
        facts["pr"] = pr["url"]
        page.wait_for_timeout(3500)

        # ---------------- 1:24 Break it: take an edge away, the decision moves
        d.beat("breakit")
        d.go(f"{ui}/playground")
        d.caption("Break it: take one edge out of a GRAPH.COPY of the graph and run the product again.")
        radio = page.get_by_role("radio", name=re.compile(a.pg_choice))
        expect(radio).to_be_visible(timeout=20_000)
        d.click(radio)
        d.click(page.get_by_role("button", name="Break it", exact=True))
        moved = page.get_by_role("heading", name="What moved")
        pgerr = page.get_by_role("alert").filter(has_text=re.compile(r"^(Playground unavailable|Run failed):"))
        expect(moved.or_(pgerr).first).to_be_visible(timeout=90_000)
        if pgerr.count() and pgerr.first.is_visible():
            raise fail(f"playground: {pgerr.first.inner_text()}")
        dec, before, after = first_changed(page)
        facts["break_it"] = {"decision": dec, "before": before, "after": after}
        sect = page.locator("section[aria-labelledby='pg-diff']")
        d.show(sect)
        d.flash(sect.locator("tbody tr").filter(has_text="(changed)").first)
        d.caption(f"Take a graph edge away and the decision changes ({dec}: {before} → {after}). "
                  "The graph is load-bearing.")

        # ---------------- 1:36 preflight: the same graph blocks the risky PR; contradicted ADRs; reversal guard
        d.beat("preflight")
        d.go(f"{ui}/preflight")
        d.caption("Before the next deploy: the same graph scores the risky pull request.")
        d.click(page.get_by_role("button", name=re.compile(r"^S6: payment timeout 5000 ms")))
        pv = page.locator("[data-verdict]").first
        pferr = page.get_by_role("alert").filter(
            has_text=re.compile(r"^(Not found|PR body not accepted|Preflight key required|Rate limited|Preflight failed):"))
        expect(pv.or_(pferr).first).to_be_visible(timeout=30_000)
        if not pv.count():
            raise fail(f"preflight: {pferr.first.inner_text()}")
        pf_verdict = pv.get_attribute("data-verdict") or "?"
        assess = page.locator("section[aria-labelledby='pf-assess-h']")
        adrs: list[str] = []
        for t in assess.get_by_role("listitem").filter(has_text="contradicted").all_inner_texts():
            m = re.search(r"\b[A-Z]+-\d+\b", t)
            if m and m.group(0) not in adrs:
                adrs.append(m.group(0))
        facts["preflight"] = {"verdict": pf_verdict, "contradicted": adrs}
        d.show(pv, "center")
        d.caption(f"Preflight verdict: {pf_verdict}." + (f" It contradicts {', '.join(adrs)}." if adrs else "")
                  + " The same graph that explained the outage gates the next change.")
        page.wait_for_timeout(1500)
        if adrs:
            d.show(assess)
        d.until(BEATS["preflight"] + 6.5)
        rev = page.get_by_role("list", name="Reversed decisions this PR reinstates")
        if not rev.count():
            d.click(page.get_by_role("button", name=re.compile(r"^catalog: off-peak migrations again")))
            expect(rev.or_(pferr).first).to_be_visible(timeout=30_000)
            if not rev.count():
                raise fail(f"preflight (reversal example): {pferr.first.inner_text()}")
        card = rev.get_by_role("article").first
        names = card.locator("p", has_text="was replaced by").locator("span.font-mono").all_inner_texts()
        if len(names) < 2:
            raise fail(f"reversal card unreadable: {names}")
        facts["reversal"] = {"reversed": names[0], "head": names[1]}
        d.show(card, "center")
        d.flash(card)
        d.caption(f"Reversal guard: a PR that puts back what {names[0]} decided, which the team replaced with "
                  f"{names[1]}, is named with the evidence (advisory; the verdict is unchanged).")

        # ---------------- 1:48 company brain: cited answer + AnswerGraph
        d.beat("brain")
        d.go(f"{ui}/brain")
        d.caption("The company brain: who owns, knows and decided what.")
        box = page.get_by_label("Question", exact=True)
        expect(box).to_be_visible(timeout=20_000)
        box.click()
        box.press_sequentially(a.brain_question, delay=18)
        box.press("Enter")
        answer = page.locator("section[aria-labelledby='brain-answer-h']")
        guard = answer.get_by_text(re.compile(r"^citation guard [✓✗]$")).first
        berr = answer.get_by_role("alert")
        expect(guard.or_(berr).first).to_be_visible(timeout=30_000)
        if not guard.count() or "✓" not in guard.inner_text():
            raise fail(f"brain answer not cited cleanly: {(berr.first.inner_text() if berr.count() else guard.inner_text())!r}")
        facts["brain"] = a.brain_question
        d.caption("It answers citing only nodes its own queries returned (citation guard), and draws the answer as a graph.")
        ag = answer.get_by_role("group", name=re.compile(r"^Answer graph: \d+ nodes"))
        expect(ag).to_be_visible(timeout=20_000)
        page.wait_for_timeout(2500)
        d.show(ag, "center")

        # ---------------- 2:00 proof charts, one at a time (the slack-absorbing beat)
        d.beat("charts")
        per = (BEATS["live"] - d.now()) / len(charts)
        if per < MIN_CHART_S:
            print(f"  charts squeezed to {MIN_CHART_S} s each; the take will run "
                  f"{MIN_CHART_S * len(charts) - (BEATS['live'] - d.now()):.1f} s long", file=sys.stderr)
            per = MIN_CHART_S
        t = d.now()
        for i, c in enumerate(charts):
            if i == 0:
                d.go(f"{ui}/media/proof.html#{c}")
            else:
                page.evaluate("(c) => { location.hash = c; }", c)
            expect(page.locator(f"body[data-state='ready'][data-chart='{c}']")).to_be_attached(timeout=10_000)
            d.caption(chart_caps[c])
            t += per
            d.until(t)

        # ---------------- 2:36 live + open: the live URL, hosted MCP, the upstream issue
        d.beat("live")
        d.go(a.live_url)
        page.evaluate(ADDR_JS, page.url)
        expect(page.get_by_text("FalkorDB ready").first).to_be_visible(timeout=30_000)
        host = urlparse(page.url).netloc
        sf: dict[str, str] = {}
        try:  # the system facts panel (engine, size, ACL); if this deployment predates it, say only what was checked
            page.get_by_role("button", name=re.compile(r"system details")).click(timeout=5_000)
            expect(page.locator("dl[aria-label='Live system status']").first).to_be_visible(timeout=5_000)
            sf = system_facts(page)
        except AssertionError:
            print("  note: the live site shows no system facts panel; captioning only its FalkorDB ready pill",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - Playwright TimeoutError on the click: same fallback
            print(f"  note: live system facts unavailable ({type(e).__name__})", file=sys.stderr)
        engine = (sf.get("engine") or "").split(" · ")[0]
        if engine and engine != "–":
            d.caption(f"Live now at {host}: {engine}, {sf.get('size', '–')}"
                      + (", read through a read-only ACL user." if sf.get("ACL") == "read-only user" else "."))
        else:
            d.caption(f"Live now at {host}: FalkorDB ready.")
        facts["live"] = {"url": page.url, **sf}
        d.until(BEATS["live"] + 7)
        d.go(f"{ui}/media/open.html")
        page.evaluate("(t) => { document.getElementById('issue-meta').textContent = t; }",
                      f"{issue['title']} · {issue['state'].lower()} · {issue['url']}")
        d.caption("Any agent can query the same graph over hosted MCP (read-only, public demo key). "
                  f"Engine issues found along the way are filed upstream: {a.issue.split('/')[-1]}.")
        facts["issue"] = {k: issue[k] for k in ("url", "state", "title")}

        # ---------------- 2:50 end card
        d.beat("end")
        d.go(f"{ui}/media/end.html")
        d.caption("No path, no claim. github.com/Prashant-thakur77/Faultline · verify it yourself: make judge-check",
                  burn=False)
        d.until(LENGTH - 0.1)
        d.finish()

        video = page.video.path() if page.video else None
        ctx.close()
        browser.close()
    if not video:
        raise fail("no video recorded")
    d.offset = (d.t0 or d.t_video) - d.t_video  # seconds of pre-roll to trim
    return Path(video), d, facts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ui", default="http://localhost:3100", help="production UI (built after any public/ change)")
    ap.add_argument("--api", default="http://localhost:8400", help="the API the UI talks to (checked before recording)")
    ap.add_argument("--real-github", action="store_true",
                    help="act on real GitHub (API started with FAULTLINE_GITHUB=real; key file in "
                         "$FAULTLINE_APPROVER_KEY_FILE; the flag must be on at main)")
    ap.add_argument("--chromium", default=None)
    ap.add_argument("--work", default=str(ROOT / "tmp" / "demo-video"))
    ap.add_argument("--gif", action="store_true", help="also regenerate docs/media/hero.gif (only when the gate beats changed)")
    ap.add_argument("--no-encode", action="store_true", help="dry run: keep the raw video and captions in --work only")
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k.replace('_', '-')}", default=v)
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)

    # everything the captions depend on is checked before the browser starts
    charts = chart_list()
    chart_caps = chart_captions(charts)
    check_open_card(a.live_url)
    check_api(a.api, a.tenant)
    check_media(a.ui, charts)
    http_get(a.live_url, timeout=20)
    issue = issue_info(a.issue)
    key = None
    if a.real_github:
        key = read_key()
        state = flag_state(a.infra_repo, a.flag)
        if state != "on":
            raise fail(f"{a.flag} is {state or 'absent'} at main of {a.infra_repo}, so the action would be a no-op; "
                       "turn it back on in that repo (a commit to flags.json on main) before a real take")
    else:
        pr_merged(a.real_pr)

    webm, d, facts = record(a, work, charts, chart_caps, issue, key)
    key = None
    total = (d.caps[-1][1] if d.caps else 0.0)
    srt = "".join(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n\n" for i, (s, e, t) in enumerate(d.caps, 1))
    (work / "captions.srt").write_text(srt)
    meta = {"webm": str(webm), "offset_s": round(d.offset, 3), "length_s": round(total, 2), "captions": len(d.caps),
            "marks": {k: round(v, 2) for k, v in d.marks.items()}, "late_s": d.late, "facts": facts}
    (work / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps({k: meta[k] for k in ("webm", "offset_s", "length_s", "captions", "late_s")}, indent=2))
    long = total > LENGTH + 0.5
    if a.no_encode:
        return 2 if long else 0

    media = ROOT / "docs" / "media"
    media.mkdir(parents=True, exist_ok=True)
    mp4 = media / "demo.mp4"
    ff = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    # a take that ran long is encoded whole (nothing silently cut) and reported as a failure below
    dur = ["-t", f"{LENGTH:.0f}"] if not long else []
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{d.offset:.3f}", "-i", str(webm), *dur,
                    "-vf", f"scale={VIDEO['width']}:{VIDEO['height']}:flags=lanczos",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-r", "30",
                    "-movflags", "+faststart", "-an", str(mp4)], check=True)
    (ROOT / "docs" / "video_captions.srt").write_text(srt)
    if a.gif:  # hero GIF: 6 s each of the G2 rejection, the G5 rejection and the proof path, cut from the same take
        segs = [(d.marks["g2"] + 1.0, 6.0), (d.marks["g5"], 6.0), (d.marks["path"], 6.0)]
        parts = "".join(f"[0:v]trim=start={s:.2f}:duration={n},setpts=PTS-STARTPTS[v{i}];" for i, (s, n) in enumerate(segs))
        concat = ("".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps=8,scale=960:-1:"
                  "flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(mp4), "-filter_complex", parts + concat,
                        str(media / "hero.gif")], check=True)
    if long:
        print(f"record_demo_video: the take is {total:.1f} s, longer than 3:00; docs/media/demo.mp4 holds the whole "
              "take, uncut. Re-record (see late_s in meta.json).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
