"""
Records the narrated demo video (docs/DEMO_SCRIPT.md) from the real UI with Playwright, timed to the voice.

Story first (cut v4): the problem (a card), the website's hero and its 3D cube, the FalkorDB explainer, then a live run
of the hero incident in the incident room through to a real pull request, then on call (the page, at a phone's size;
the ack; the Telegram still; a standing approval and the same fault fixed while nobody is woken), what Faultline
learned, FalkorDB observing itself (/engine), the proof charts, the live deployment and the end card. Every beat keys
to a narration segment (tmp/narration/timing.json, written by frontend/scripts/narrate.py) and starts at that
segment's start; actions inside a beat are timed to the words they show (the share of the segment's text before the
word). The on-call, learn and engine beats use cue words with a fallback share of the segment (their narration is
still being worded), so rewording never stops a take; what the voice claims is still checked against the page.
The preflight and brain beats of earlier cuts are kept and run only when the narration has those segments.

On call (v4): by the time the oc_* beats air, the take's own incident is RESOLVED and its pages are settled, so right
after its fix is APPLIED the recorder opens incident B (a second run of the hero scenario, through the API, off
screen) whose page still waits for an ack; oc_page shows it in /oncall and, at a phone's size, in media/phone.html
(the live page view in a 390x844 frame); oc_ack taps Acknowledge there. oc_contract grants a standing approval on the
take's incident (two steps, in the incident room), then runs the same fault again as incident C (through the API, as
evals/oncall_night.py does) and shows it handled under the contract with nobody woken (/oncall's contracts panel, the
stat tile, the contract-notice page). A real take needs --real-repeat for that: after the take's fix the flag is off
at GitHub main, so the recorder turns it back on (one commit to flags.json on main of the demo infra repo: the fault
comes back) before B and C open; C's contract then merges a second real pull request. The recorder refuses to start
with an active contract (it would fix the take's own incident without a human) and when the ack window is shorter than
the beats need.

Pre-roll (trimmed): it checks the API, re-arms the tenant (with its confirm step), runs the hero scenario once to read
and check every value the take depends on, and confirms WebGL works for the cube. Only then does the kept footage
start; the take runs the scenario again, live, from the launcher.

Numbers: the spoken numbers are filled from evals/results/latest.json by narrate.py; the recorder re-fills the
narration text from the current latest.json and refuses a stale narration. Numbers the voice states about the page
(suspects, rows, flow, decisions contradicted) are checked against the page before recording. The LLM card shows only
values read from latest.json. Captions are the narration's own words, 2-3 chunks per segment, burned in at encode
time from the .srt (so they are timed to the voice, not to page loads).

Sync: a beat that overruns pushes the next segment later; the encoder places each segment's audio at the moment its
beat actually started (adelay per segment), so the voice never drifts from the picture. The video is the narration
plus any such pushes plus a 2 s tail.

Real GitHub (--real-github): the API must run with FAULTLINE_GITHUB=real and FAULTLINE_APPROVER_KEY. The recorder reads
the approver key from the file in $FAULTLINE_APPROVER_KEY_FILE, types it into the password-type approver key fields
(the approval and the contract grant; masked with CSS if one were ever plain text) and never prints it. It refuses to
start unless the flag is "on" at main of the demo infra repo (gh api). Without --real-github the take uses the
simulated GitHub: a "dry run" badge is shown from the approval on, and the github.com shot shows the real PR an
earlier real take merged (checked with gh). On a public API (FAULTLINE_PUBLIC) the scripted runs B and C are trusted
runs only with the approver key: a dry run then reads it from the same file and sends it as a header, never printed.

Outputs:
  --out (real: docs/media/demo.mp4; simulated: tmp/demo-video/narrated_sim.mp4)
                             H.264 1080p + AAC 192k narration (loudnorm I=-16), captions burned in
  docs/video_captions.srt    the captions with their times (real take only; always <work>/captions.srt)
  docs/media/hero.gif        G2 rejection -> G5 rejection -> proof path; only with --gif
  <work>/meta.json           segment starts, pushes, the facts read from the page
With --no-encode (dry run) only <work>/ is written: the raw .webm, captions.srt and meta.json.
--from-segment SID [--to-segment SID] (simulated takes only; implies --no-encode) records part of the take: the beats
before SID still run, fast and untimed, so the state the later beats need is real (the run, the approval, B, ...);
the kept footage starts at SID. For trying beats without a whole take.

Usage (API on --api, production UI on --ui):
  .venv/bin/python frontend/scripts/record_demo_video.py --ui http://localhost:3000 --api http://localhost:8400 \
      --narration tmp/narration --chromium ~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome \
      [--real-github --real-repeat] [--gif] [--no-encode] [--from-segment oc_page --to-segment engine] [--out PATH]
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from playwright.sync_api import Frame, FrameLocator, Locator, Page, expect, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_MEDIA = ROOT / "frontend" / "public" / "media"
DOCS_CHARTS = ROOT / "docs" / "media" / "charts"
LATEST = ROOT / "evals" / "results" / "latest.json"
LLM_ARMS = ROOT / "evals" / "results" / "llm_arms.json"
VIEW = {"width": 1536, "height": 864}  # the 125 % zoom of a 1920x1080 screen; upscaled to 1080p by ffmpeg
VIDEO = {"width": 1920, "height": 1080}
TAIL = 2.0  # seconds of the end card after the last word
MUSIC_GAIN = 0.30  # the music bed under the voice, before ducking
GITHUB_SHOT = 4.0  # silent seconds on the merged PR at github.com after the approval beat
MIN_GAP = 0.25  # the shortest pause between two segments when a beat ran long

EXPLAINER = ["x_tenant", "x_matrices", "x_blast", "x_path", "x_flow", "x_cut", "x_who", "x_readonly", "x_unplug"]  # /explainer scenes, in order
ONCALL = ["oc_page", "oc_ack", "oc_contract"]  # the page, the ack, a standing approval
# The beats, in narration order (cut v4). The recorder refuses a narration whose segments differ.
SEGMENT_IDS = ["problem", "whyhard", "idea", "cube", *EXPLAINER, "run", "g2", "g5", "proof", "contain", "act", *ONCALL,
               "brain", "learn", "engine", "numbers", "cost", "close"]   # "preflight" has a beat; out of the short cut
# The proof beats' charts (media/proof.html#<name>), per segment, in the order shown; several in one segment share it
# evenly, or "name@word" shows it when the voice reaches that word. "close" shows its charts before "Any agent".
# Every name listed must be drawn into docs/media/charts/<name>.svg (scripts/gen_charts.py), copied byte for byte to
# frontend/public/media/charts/ and known to proof.html's CHARTS; the recorder refuses to start otherwise.
PROOF_CHARTS: dict[str, list[str]] = {"numbers": ["deep", "otel@real system"], "cost": ["cost", "tenants@it scales"],
                                     "close": ["live"]}
# Hooks for the newer benches' charts: proof.html knows these names; list one above (e.g. "numbers": ["deep", "otel"])
# once scripts/gen_charts.py draws it, and the check above applies to it.
CHART_HOOKS = ["otel", "tenants", "algo"]
CHARTS = [c.split("@")[0] for cs in PROOF_CHARTS.values() for c in cs]
NUM_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
MIN_ACK_WINDOW_S = 150  # a page must wait at least this long for its ack, or B escalates before the oc_ack beat taps it
PAGE_POLL_S = 2.5  # GET /api/pages is limited to 60 a minute per address, and the UI polls it too

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
    "contract_uses": "1",   # the standing approval granted in oc_contract: one repeat (used up by incident C) ...
    "contract_days": "7",   # ... for a week; the narration's "one use, seven days" is checked against these
}

# Before any page script: skip the home intro (odometer) except when a beat asks for it, and draw a visible pointer
# (headless video has none) that follows the real mouse events the recorder sends.
INIT_JS = r"""
(() => {
  try {
    if (sessionStorage.getItem('__demo_intro') === 'play') { sessionStorage.removeItem('__demo_intro'); sessionStorage.removeItem('fl-intro'); }
    else sessionStorage.setItem('fl-intro', '1');
  } catch (e) {}
  const install = () => {
    if (location.pathname.includes('/media/')) return;  // the cards and charts are not interacted with
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor'; c.setAttribute('aria-hidden', 'true');
    Object.assign(c.style, { position: 'fixed', left: '0', top: '0', width: '22px', height: '22px', margin: '-11px 0 0 -11px',
      borderRadius: '50%', border: '2px solid rgba(255,255,255,.92)', background: 'rgba(255,255,255,.16)',
      boxShadow: '0 0 0 1px rgba(0,0,0,.55), 0 4px 14px rgba(0,0,0,.5)', zIndex: 2147483647, pointerEvents: 'none',
      transform: 'translate(-200px,-200px)', transition: 'width .12s, height .12s, margin .12s' });
    document.documentElement.appendChild(c);
    let p = null;
    try { p = JSON.parse(sessionStorage.getItem('__demo_xy') || 'null'); } catch (e) {}
    if (p) c.style.transform = `translate(${p[0]}px, ${p[1]}px)`;
    addEventListener('mousemove', (e) => {
      c.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
      try { sessionStorage.setItem('__demo_xy', JSON.stringify([e.clientX, e.clientY])); } catch (err) {}
    }, true);
    addEventListener('mousedown', () => { c.style.width = c.style.height = '16px'; c.style.margin = '-8px 0 0 -8px'; }, true);
    addEventListener('mouseup', () => { c.style.width = c.style.height = '22px'; c.style.margin = '-11px 0 0 -11px'; }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', install); else install();
})();
"""

FLASH_JS = """
(el) => {
  const o = el.style.outline, f = el.style.outlineOffset;
  el.style.outline = '3px solid #38bdf8'; el.style.outlineOffset = '2px';
  setTimeout(() => { el.style.outline = o; el.style.outlineOffset = f; }, 1400);
}
"""

# Eased scroll of the page's scroller (<main> on desktop, which Lenis drives on the home page) to an element.
GLIDE_JS = """
async ([el, block, ms]) => {
  const main = document.getElementById('main');
  const own = main && /(auto|scroll)/.test(getComputedStyle(main).overflowY);
  const sc = own ? main : document.scrollingElement;
  const top = own ? main.getBoundingClientRect().top : 0;
  const r = el.getBoundingClientRect();
  const from = sc.scrollTop;
  let to = from + (r.top - top) - (block === 'center' ? (sc.clientHeight - r.height) / 2 : 24);
  to = Math.max(0, Math.min(to, sc.scrollHeight - sc.clientHeight));
  const t0 = performance.now();
  await new Promise((done) => {
    const step = (t) => {
      const k = Math.min(1, (t - t0) / ms);
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      sc.scrollTop = from + (to - from) * e;
      if (k < 1) requestAnimationFrame(step); else done();
    };
    requestAnimationFrame(step);
  });
}
"""

CHIP_JS = """
([id, text, where]) => {
  let el = document.getElementById(id);
  if (!text) { if (el) el.remove(); return; }
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    el.setAttribute('aria-hidden', 'true');
    document.documentElement.appendChild(el);
  }
  Object.assign(el.style, {
    position: 'fixed', zIndex: 2147483646, pointerEvents: 'none', padding: '8px 16px', borderRadius: '999px',
    font: '600 18px/1.2 ui-monospace, monospace', boxShadow: '0 10px 30px rgba(0,0,0,.5)',
    ...(where === 'url'
      ? { left: '50%', top: '66px', transform: 'translateX(-50%)', background: 'rgba(0,0,0,0.88)', color: '#fafafa',
          border: '1px solid rgba(255,255,255,.22)' }
      : { right: '18px', top: '66px', background: 'rgba(120,53,15,0.92)', color: '#fde68a',
          border: '1px solid rgba(251,191,36,.6)' }),
  });
  el.textContent = text;
}
"""

SYNC_ON_JS = """
() => new Promise((done) => {
  const m = document.createElement('div');
  m.id = '__demo_sync';
  Object.assign(m.style, { position: 'fixed', left: '0', top: '0', width: '40px', height: '40px', background: '#fff',
                           zIndex: 2147483647 });
  document.documentElement.appendChild(m);
  requestAnimationFrame(() => requestAnimationFrame(() => done(true)));
})
"""

# Only if the approver key field were ever plain text: hide what is typed (the field is type=password today).
MASK_JS = "e => { e.style.webkitTextSecurity = 'disc'; e.style.filter = 'blur(6px)'; }"


def fail(msg: str) -> SystemExit:
    return SystemExit(f"record_demo_video: {msg}")


@dataclass
class Seg:
    id: str
    start: float
    length: float
    text: str


class Director:
    """Holds the take to the narration: begin(id) waits for a segment's start, at_word() for a word inside it."""

    def __init__(self, page: Page, segs: dict[str, Seg], t_video: float):
        self.page = page
        self.segs = segs
        self.t_video = t_video  # monotonic time the video started (page created)
        self.t0: float | None = None  # first frame we keep (the problem beat)
        self.actual: dict[str, float] = {}  # segment id -> when its beat really started (video seconds)
        self.shift = 0.0  # how much later than planned the narration now runs (beats that overran push it)
        self.cur: Seg | None = None
        self.marks: dict[str, float] = {}
        self.chips: dict[str, tuple[str, str]] = {}
        self.mouse = (VIEW["width"] / 2, VIEW["height"] / 2)
        self.offset = 0.0
        # partial takes (--from-segment): until `live_from` begins, beats run fast and untimed (nothing is kept)
        self.fast = False
        self.live_from: str | None = None

    def now(self) -> float:
        return time.monotonic() - (self.t0 or time.monotonic())

    def start(self) -> None:
        self.t0 = time.monotonic()

    def until(self, t: float) -> None:
        if self.fast:
            return
        d = t - self.now()
        if d > 0:
            self.page.wait_for_timeout(int(d * 1000))

    def begin(self, sid: str) -> None:
        """Start a beat at its segment's start, or right after the previous segment's audio if that ran late
        (a push is won back inside the narration's gaps; two segments never overlap)."""
        seg = self.segs[sid]
        if self.fast and sid == self.live_from:   # a partial take: the kept footage starts here, on its cue
            self.fast = False
            self.t0 = time.monotonic() - seg.start
            self.actual.clear()
            self.cur = None
            self.marks = {"sync": 0.0}
        prev = self.cur
        target = seg.start if prev is None else max(seg.start, self.actual[prev.id] + prev.length + MIN_GAP)
        self.until(target)
        a = self.now()
        if a - target > 0.3 and not self.fast:
            print(f"  segment {sid} starts {a - target:.1f} s after its cue (the previous beat ran long)", file=sys.stderr)
        self.shift = a - seg.start
        self.actual[sid] = a
        self.marks[sid] = a
        self.cur = seg

    def left(self) -> float:
        """Seconds left in the current segment."""
        assert self.cur
        return self.actual[self.cur.id] + self.cur.length - self.now()

    def mark(self, k: str) -> None:
        self.marks[k] = self.now()

    def word(self, w: str, nth: int = 1) -> float:
        """Seconds into the current segment at which the voice reaches `w` (share of the text before it)."""
        assert self.cur
        hits = [m.start() for m in re.finditer(rf"(?<!\w){re.escape(w)}(?!\w)", self.cur.text, re.I)]
        if len(hits) < nth:
            raise fail(f"segment {self.cur.id}: the narration no longer says {w!r}; re-time this beat")
        return self.cur.length * hits[nth - 1] / len(self.cur.text)

    def at(self, sec: float) -> None:
        assert self.cur
        self.until(self.actual[self.cur.id] + sec)

    def at_word(self, w: str, lead: float = 0.0, nth: int = 1) -> None:
        self.at(max(0.0, self.word(w, nth) - lead))

    def says(self, w: str) -> bool:
        assert self.cur
        return re.search(rf"(?<!\w){re.escape(w)}(?!\w)", self.cur.text, re.I) is not None

    def at_cue(self, words: tuple[str, ...], frac: float, lead: float = 0.0) -> None:
        """at_word for beats whose narration is still being worded: the first of `words` the segment says, else
        `frac` of the segment (said once on stderr, so the beat can be re-timed). Claims are checked elsewhere."""
        assert self.cur
        for w in words:
            if self.says(w):
                self.at_word(w, lead)
                return
        if not self.fast:
            print(f"  note: segment {self.cur.id} says none of {list(words)}; cued at {frac:.0%} of it", file=sys.stderr)
        self.at(max(0.0, self.cur.length * frac - lead))

    def end(self, slack: float = 0.0) -> None:
        assert self.cur
        self.at(self.cur.length - slack)

    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(min(ms, 120) if self.fast else ms)

    def chip(self, key: str, text: str | None, where: str = "badge") -> None:
        if text:
            self.chips[key] = (text, where)
        else:
            self.chips.pop(key, None)
        self.page.evaluate(CHIP_JS, [f"__demo_{key}", text or "", where])

    def reapply(self) -> None:
        for k, (text, where) in self.chips.items():
            self.page.evaluate(CHIP_JS, [f"__demo_{k}", text, where])

    def go(self, url: str) -> None:
        self.page.goto(url)
        self.reapply()

    def show(self, loc: Locator, block: str = "start") -> None:
        loc.evaluate(f"e => e.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
        self.wait(700)

    def glide(self, loc: Locator, block: str = "start", ms: int = 1200) -> None:
        self.page.evaluate(GLIDE_JS, [loc.element_handle(), block, ms])
        self.wait(150)

    def flash(self, loc: Locator) -> None:
        loc.evaluate(FLASH_JS)

    def move_to(self, loc: Locator, ms: int = 420) -> None:
        box = loc.bounding_box()
        if box is None or box["y"] < 0 or box["y"] + box["height"] > VIEW["height"]:
            loc.scroll_into_view_if_needed()
            box = loc.bounding_box()
        if box is None:
            raise fail(f"cannot point at {loc}")
        self.move_xy(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, ms)

    def move_xy(self, x: float, y: float, ms: int = 420) -> None:
        if self.fast:
            ms = min(ms, 60)
        x0, y0 = self.mouse
        n = max(4, ms // 30)
        for i in range(1, n + 1):
            k = i / n
            e = 1 - (1 - k) ** 3
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(ms // n)
        self.mouse = (x, y)

    def hover(self, loc: Locator) -> None:
        self.move_to(loc)

    def click(self, loc: Locator, flash: bool = True) -> None:
        self.move_to(loc)
        if flash:
            loc.evaluate(FLASH_JS)
        self.wait(250)
        loc.click()


# ------------------------------------------------------------------ narration, captions and checks

def load_narration(dirp: Path) -> tuple[list[Seg], float, Path]:
    tj, wav = dirp / "timing.json", dirp / "narration.wav"
    if not tj.exists() or not wav.exists():
        raise fail(f"{dirp} needs timing.json and narration.wav (frontend/scripts/narrate.py writes them)")
    t = json.loads(tj.read_text())
    segs = [Seg(s["id"], float(s["start"]), float(s["length"]), s["text"]) for s in t["segments"]]
    if [s.id for s in segs] != SEGMENT_IDS:
        raise fail(f"narration segments {[s.id for s in segs]} differ from the beats {SEGMENT_IDS}")
    for s in segs:
        if not (dirp / f"{s.id}.wav").exists():
            raise fail(f"{dirp}/{s.id}.wav is missing; the encoder places each segment's audio itself")
    # the spoken numbers must still be today's: re-fill the narration from the current latest.json
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import narrate  # noqa: E402 - frontend/scripts/narrate.py (imports nothing heavy at module level)

    latest = json.loads(LATEST.read_text())
    for (sid, _gap, raw), s in zip(narrate.SEGMENTS, segs):
        now = narrate.fill(raw, latest)
        if sid != s.id or now != s.text:
            raise fail(f"the narration is stale at {s.id!r} (latest.json changed since it was spoken): re-run narrate.py")
    return segs, float(t["total"]), dirp


def chunks(text: str) -> list[str]:
    """2-3 readable caption chunks per segment, split at sentence ends (commas only inside a long sentence)."""
    sents = [s for s in re.split(r"(?<=[.?!])\s+(?=[A-Z\"'])", text.strip()) if s]
    out: list[str] = []
    for s in sents:
        if len(s) > 125 and ", " in s:  # a long sentence: split at the comma nearest its middle
            cut = min((m.start() for m in re.finditer(", ", s)), key=lambda i: abs(i - len(s) / 2))
            out += [s[:cut + 1], s[cut + 2:]]
        else:
            out.append(s)
    n = max(1, min(3, math.ceil(len(text) / 105)))
    target = len(text) / n
    groups: list[str] = []
    for s in out:
        if groups and len(groups[-1]) + len(s) + 1 <= target * 1.25 and len(groups) >= n:
            groups[-1] += " " + s
        elif groups and len(groups[-1]) < target * 0.6:
            groups[-1] += " " + s
        else:
            groups.append(s)
    while len(groups) > 3:  # merge the two shortest neighbours
        i = min(range(len(groups) - 1), key=lambda k: len(groups[k]) + len(groups[k + 1]))
        groups[i:i + 2] = [groups[i] + " " + groups[i + 1]]
    return groups


def caption_track(segs: list[Seg], actual: dict[str, float]) -> list[tuple[float, float, str]]:
    caps = []
    for i, s in enumerate(segs):
        if s.id not in actual:
            continue
        t, end = actual[s.id], actual[s.id] + s.length
        nxt = actual.get(segs[i + 1].id) if i + 1 < len(segs) else None
        hold = min(end + 0.6, nxt) if nxt is not None else end + 0.6
        parts = chunks(s.text)
        total = sum(len(p) for p in parts)
        for j, p in enumerate(parts):
            d = s.length * len(p) / total
            caps.append((t, hold if j == len(parts) - 1 else t + d, p))
            t += d
    return caps


def srt_time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def number_said(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else NUM_WORDS.get(w)


# ------------------------------------------------------------------ checks before the browser starts (fail early)

def http_get(url: str, timeout: float = 15.0) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - our own servers / the live demo
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        raise fail(f"GET {url} failed: {e}") from None


def check_api(api: str, tenant: str, real: bool) -> dict:
    st = json.loads(http_get(f"{api.rstrip('/')}/api/status?tenant={tenant}"))
    if st.get("status") != "ok":
        raise fail(f"the API says FalkorDB is not ready for {tenant}: {st.get('reason') or st.get('status')}")
    if st.get("graph_disabled"):
        raise fail("the API runs with FAULTLINE_DISABLE_GRAPH=true (A4 ablation); the demo needs the graph")
    mode = st.get("github")
    if real and mode != "real":
        raise fail(f"--real-github, but the API acts on {mode or 'an unknown'} GitHub: start it with FAULTLINE_GITHUB=real")
    if not real and mode == "real":
        raise fail("the API acts on real GitHub; a dry run must not: restart it without FAULTLINE_GITHUB=real")
    return st


def check_media(ui: str) -> None:
    """The static pages must be served by the running UI (Next serves public/ files present at build time)."""
    for name in ["hook.html", "proof.html", "open.html", "end.html", "phone.html",
                 *[f"charts/{c}.svg" for c in CHARTS]]:
        http_get(f"{ui.rstrip('/')}/media/{name}")
    proof = http_get(f"{ui.rstrip('/')}/media/proof.html").decode("utf-8", "replace")
    if b"__step" not in http_get(f"{ui.rstrip('/')}/media/hook.html") or "__llm" not in proof or \
            b"__phone" not in http_get(f"{ui.rstrip('/')}/media/phone.html"):
        raise fail("the UI serves older media pages than frontend/public/media; rebuild and restart it")
    for c in CHARTS:
        if not re.search(rf"^\s*{re.escape(c)}\s*:\s*\"", proof, re.M):
            raise fail(f"media/proof.html does not know the chart {c!r}: add it to its CHARTS (title = the alt text)")
    # media/phone.html frames the live page view: a UI behind a proxy that forbids framing (the deployment's Caddy
    # sends X-Frame-Options DENY) would show an empty phone, so record on a UI without it (next start)
    try:
        with urllib.request.urlopen(f"{ui.rstrip('/')}/oncall", timeout=15) as r:  # noqa: S310 - our own UI
            xfo, csp = (r.headers.get("X-Frame-Options") or "").upper(), r.headers.get("Content-Security-Policy") or ""
    except (urllib.error.URLError, OSError) as e:
        raise fail(f"GET {ui}/oncall failed: {e}") from None
    if xfo == "DENY" or re.search(r"frame-ancestors\s+'none'", csp):
        raise fail(f"{ui} forbids framing its pages (X-Frame-Options/frame-ancestors), so media/phone.html cannot show "
                   "the page at a phone's size: record against the UI itself (next start), not the proxy")


def http_try(url: str, timeout: float = 15.0) -> tuple[int, bytes]:
    """GET that reports a 404 instead of raising (an unreachable server still fails loudly)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - our own servers
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError) as e:
        raise fail(f"GET {url} failed: {e}") from None


# ------------------------------------------------------------------ the API, for the scripted steps (B, C) and checks

def api_req(api: str, method: str, path: str, body: dict | None = None, headers: dict | None = None,
            timeout: float = 30.0) -> Any:
    """One JSON call to our API. Errors name the method, path, status and the server's detail, never a header (the
    approver key and run tokens only ever travel in headers)."""
    req = urllib.request.Request(f"{api.rstrip('/')}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - our own API
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}").get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise fail(f"{method} {path.split('?')[0]} answered HTTP {e.code}: {detail or e.reason}") from None
    except (urllib.error.URLError, OSError) as e:
        raise fail(f"{method} {path.split('?')[0]} failed: {e}") from None
    return json.loads(raw) if raw else None


def open_page(p: dict) -> bool:
    return p.get("kind") in ("page", "escalation") and p.get("status") in ("sent", "delivery_failed")


def check_oncall_api(api: str, tenant: str, S: dict[str, Seg]) -> dict:
    """Before the browser starts, for the v4 beats: no active contract (it would fix the take's own incident without a
    human), what the learn beat's voice names is in the graph, /engine answers, and the counters the take compares
    against later. Returns {"public", "handled_before", "channels"}."""
    q = f"tenant={urllib.parse.quote(tenant)}"
    out: dict[str, Any] = {"public": False, "handled_before": None, "channels": []}
    if any(s in S for s in ONCALL) or "learn" in S:
        active = [c for c in api_req(api, "GET", f"/api/contracts?{q}")["rows"] if c.get("status") == "active"]
        if active:
            raise fail(f"active contract(s) {', '.join(c['id'] for c in active)}: one would fix the take's own incident "
                       "without a human. Revoke them on /oncall (Contracts, Revoke) first")
        learned = api_req(api, "GET", f"/api/learned?{q}")
        out["public"] = bool((learned.get("trust") or {}).get("public"))
        out["handled_before"] = api_req(api, "GET", f"/api/oncall/stats?{q}&days=7").get("handled_under_contract")
        out["channels"] = [c.get("channel") for c in api_req(api, "GET", f"/api/pages?{q}&status=open").get("channels")
                           or [] if c.get("configured")]
        if "learn" in S:
            text = S["learn"].text.lower()
            need = [("preferences", "prefer", lambda r: r.get("line")),
                    ("guidelines", "guideline", lambda r: r.get("status") in ("proposed", "active")),
                    ("responders", "respond", lambda r: True)]
            for sec, word, ok in need:
                if word in text and not any(ok(r) for r in (learned.get(sec) or {}).get("rows") or []):
                    raise fail(f"the learn narration speaks of {sec}, and the tenant has learned none yet "
                               "(GET /api/learned): run incidents with trusted approvals, acks and rejections first")
    if "engine" in S:
        api_req(api, "GET", f"/api/engine/insight?{q}")
    return out


def numbers_said(text: str, pattern: str) -> list[int]:
    """Every number the text says where `pattern` (one group: the number, as digits or a word) matches."""
    out = []
    for m in re.finditer(pattern, text, re.I):
        w = m.group(1).lower()
        n = int(w) if w.isdigit() else NUM_WORDS.get(w)
        if n is not None:
            out.append(n)
    return out


def check_contract_scope(S: dict[str, Seg], uses: int, days: int) -> None:
    """The scope typed into the grant (--contract-uses/--contract-days) is the one the voice says."""
    if "oc_contract" not in S:
        return
    if not (1 <= uses <= 10 and 1 <= days <= 30):
        raise fail(f"contract scope {uses} uses / {days} days is outside the grant form's limits (1-10 uses, 1-30 days)")
    for pat, n, what in ((r"\b(\w+) uses?\b", uses, "--contract-uses"), (r"\b(\w+) days?\b", days, "--contract-days")):
        said = numbers_said(S["oc_contract"].text, pat)
        if said and any(x != n for x in said):
            raise fail(f"the oc_contract narration says {said}, the take grants {n} ({what})")


def check_charts() -> None:
    for c in CHARTS:
        src, dst = DOCS_CHARTS / f"{c}.svg", PUBLIC_MEDIA / "charts" / f"{c}.svg"
        if not src.exists():
            raise fail(f"docs/media/charts/{c}.svg is missing; run scripts/gen_charts.py")
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            raise fail(f"frontend/public/media/charts/{c}.svg differs from docs/media/charts/{c}.svg: "
                       "cp docs/media/charts/*.svg frontend/public/media/charts/ (and rebuild the UI if it is new)")


def pct(v: float) -> str:
    return f"{v * 100:.0f}%" if abs(v * 100 - round(v * 100)) < 0.05 else f"{v * 100:.1f}%"


def llm_card() -> dict:
    """The LLM comparison card's values, read from latest.json (and the model from llm_arms.json) now."""
    d = json.loads(LATEST.read_text())

    def g(k: str) -> Any:
        if d.get(k) is None:
            raise fail(f"{k} is not in evals/results/latest.json; the LLM card would have no source")
        return d[k]

    model = json.loads(LLM_ARMS.read_text()).get("model") if LLM_ARMS.exists() else None
    if not model:
        raise fail("evals/results/llm_arms.json names no model; the LLM card would not say which model it was")
    rows = [("The model alone", "reads the alert, raw telemetry and the change list (A0)", "A0", False),
            ("The model + vector RAG", "runbooks, postmortems and ADRs retrieved by similarity (A1)", "A1", False),
            ("Faultline, same model", "the model proposes; the graph gate decides (A3L)", "A3L", True)]
    scen = sorted(k.split(".")[2] for k in d if re.fullmatch(r"arm\.A3L\.S\w+\.outcome_correct_rate", k))
    return {"model": model,
            "rows": [{"label": lbl, "detail": det, "mine": mine, "outcome": g(f"arm.{a}.outcome_correct_rate"),
                      "abstain": g(f"arm.{a}.abstention_correct_rate"), "trials": g(f"arm.{a}.trials")}
                     for lbl, det, a, mine in rows],
            "note": (f"One trial per scenario; A3L ran on {len(scen)} scenarios ({', '.join(scen)}): a direction, not a "
                     "benchmark. evals/llm_arms.py · docs/PROOF.md")}


def check_open_card(live_url: str) -> None:
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


def flag_back_on(repo: str, flag: str) -> str | None:
    """--real-repeat (real take): the fault comes back. One commit to flags.json on main of the demo infra repo that
    sets `flag` back to "on" (only that value changes), so incidents B and C find on at main what the take's fix turned
    off, and C's contract merges a real pull request again. Returns the commit's URL (None: it was on already)."""
    d = gh("api", f"repos/{repo}/contents/flags.json?ref=main")
    raw = base64.b64decode(d["content"]).decode()
    doc = json.loads(raw)
    state = ((doc.get("flags") or {}).get(flag) or {}).get("state")
    if state == "on":
        return None
    if state is None:
        raise fail(f"{flag} is not in flags.json at main of {repo}")
    new, n = re.subn(rf'("{re.escape(flag)}"\s*:\s*\{{[^{{}}]*?"state"\s*:\s*)"{re.escape(state)}"', r'\1"on"', raw,
                     count=1)
    want = json.loads(raw)
    want["flags"][flag]["state"] = "on"
    if n != 1 or json.loads(new) != want:
        raise fail(f"could not change only {flag}'s state in flags.json at main of {repo}; turn it on by hand")
    res = gh("api", "-X", "PUT", f"repos/{repo}/contents/flags.json",
             "-f", f"message=demo take: {flag} back on (the same fault again, for the standing-approval beat)",
             "-f", f"content={base64.b64encode(new.encode()).decode()}", "-f", f"sha={d['sha']}", "-f", "branch=main")
    return ((res or {}).get("commit") or {}).get("html_url") or "committed"


def pr_merged(url: str, wait_s: float = 0.0) -> dict:
    t_end = time.monotonic() + wait_s
    while True:
        pr = gh("pr", "view", url, "--json", "state,mergedAt,url,title,number")
        if pr.get("state") == "MERGED" or time.monotonic() >= t_end:
            break
        time.sleep(2)
    if pr.get("state") != "MERGED":
        raise fail(f"{url} is in state {pr.get('state')}, not merged; the shot would be false")
    return pr


def issue_info(ref: str) -> dict:
    repo, num = ref.split("#")
    return gh("issue", "view", num, "-R", repo, "--json", "title,state,url,number")


def read_key(why: str = "--real-github") -> str:
    path = os.environ.get("FAULTLINE_APPROVER_KEY_FILE")
    if not path:
        raise fail(f"{why} needs FAULTLINE_APPROVER_KEY_FILE (a file holding the approver key)")
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

def read_room(page: Page, a: argparse.Namespace) -> tuple[SimpleNamespace, dict]:
    """Locators and values of a finished incident room (paused, awaiting approval)."""
    L = SimpleNamespace()
    L.timeline = page.locator("#pane-timeline")
    L.gate = page.locator("section[aria-labelledby='gate-h']")
    L.rej = (L.gate.get_by_role("listitem").filter(has_text=a.distractor_path)
             .get_by_role("button", name=re.compile(r"^Rejected by .*\bG2\b")).first)
    expect(L.rej).to_be_visible()
    L.g5 = (L.gate.get_by_role("list", name=re.compile(rf"^Checks for {re.escape(a.distractor_flow)}\b"))
            .get_by_role("button", name=re.compile(r"^G5 sufficiency: fail")).first)
    expect(L.g5).to_be_visible()
    m = re.search(r"max flow ([\d.]+) < needed ([\d.]+)", L.g5.text_content() or "")
    if not m:
        raise fail(f"G5 detail for {a.distractor_flow} not found on the page")
    labels = L.gate.get_by_role("list", name=re.compile(r"^Checks for ")).evaluate_all(
        "els => els.map(e => e.getAttribute('aria-label'))")
    suspects = sorted({re.match(r"Checks for (\S+)", x).group(1) for x in labels if x} - {"NO_INCIDENT"})
    L.root = page.locator("section[aria-labelledby='root-h']")
    links = L.root.get_by_role("list", name="Mechanism chain").get_by_role("button")
    try:   # the root-cause card can render a moment after the pause line (the check below says what is missing)
        expect(links.nth(1)).to_be_visible(timeout=20_000)
    except AssertionError:
        pass
    chain = links.all_inner_texts()
    if len(chain) < 2:
        raise fail(f"no mechanism chain on the page: {chain}")
    L.cause = L.gate.get_by_role("list", name=re.compile(rf"^Checks for {re.escape(chain[0])}\b")).first
    L.why = L.root.get_by_role("button", name="Why do you believe this?")
    expect(L.why).to_be_enabled()
    L.graph = page.locator("section[aria-labelledby='graph-h']")
    L.crew = page.locator("section[aria-labelledby='crew-h']")
    if not L.crew.get_by_text(re.compile(r"^\d+ steps · \d+ specialists$")).count():
        raise fail("crew board not recorded for this run")
    L.contain = page.locator("section[aria-labelledby='containment-h']")
    L.cut = L.contain.get_by_role("table", name=re.compile(r"^Edges in the minimum cut"))
    expect(L.cut).to_be_visible(timeout=30_000)
    L.who = page.locator("section[aria-labelledby='whofixes-h']")
    L.top = L.who.get_by_role("list", name="People ranked by the graph").get_by_role("listitem").first
    expect(L.top).to_be_visible()
    L.plan = page.locator("section[aria-labelledby='plan-h']")
    opt = (L.plan.get_by_role("list", name="Action options").get_by_role("listitem")
           .filter(has_text=f"flag {a.flag}").first)
    L.choose = opt.get_by_role("button", name=re.compile(r"^(Choose|Re-choose)$"))
    if not L.choose.count():
        raise fail(f"the option 'flag {a.flag}' is not offered (is the flag already off at GitHub main?)")
    return L, {"flow": m.group(1), "needed": m.group(2), "suspects": suspects, "chain": chain}


def first_changed(page: Page) -> tuple[str, str, str]:
    rows = page.locator("section[aria-labelledby='pg-diff'] tbody tr").filter(has_text="(changed)")
    if not rows.count():
        raise fail("Break it: the page shows no changed decision")
    r = rows.first
    name = (r.locator("th").inner_text() or "").replace("(changed)", "").strip()
    before, after = (r.locator("td").nth(i).inner_text().strip() for i in (0, 1))
    return name, before[:80], after[:80]


# ------------------------------------------------------------------ v4 beats: on call, what it learned, the engine

@dataclass
class Take:
    """What the v4 beats share. `key`: the real-GitHub approver key (typed into password fields only). `api_key`: sent
    as a header on the scripted calls of a public API only (trusted runs B and C). Run tokens stay in `tokens`. None of
    them is printed or kept in facts."""
    a: argparse.Namespace
    page: Page
    d: Director
    S: dict[str, Seg]
    facts: dict
    ui: str
    key: str | None
    api_key: str | None
    public: bool
    handled_before: int | None
    inc_a: str | None = None          # the take's incident, fixed and APPLIED: the contract is granted on it
    b: dict | None = None             # incident B (a page that still waits for an ack): {"incident", "job", "graph"}
    c: dict | None = None             # incident C: the same fault again, handled under the contract
    pg: dict | None = None            # B's page: shown in oc_page, acked in oc_ack
    phone: FrameLocator | None = None
    tokens: dict[str, str] = field(default_factory=dict)

    @property
    def q(self) -> str:
        return f"tenant={urllib.parse.quote(self.a.tenant)}"

    def api(self, method: str, path: str, body: dict | None = None, run_token: str | None = None,
            keyed: bool = False, timeout: float = 30.0) -> Any:
        h = {"X-Faultline-Run-Token": run_token} if run_token else {}
        if keyed and self.public and self.api_key:
            h["X-Faultline-Approver-Key"] = self.api_key
        return api_req(self.a.api, method, path, body, h, timeout)


def incident_of(url: str) -> str:
    m = re.search(r"/incidents/([^/?#]+)", url)
    if not m:
        raise fail(f"not an incident room: {url}")
    return urllib.parse.unquote(m.group(1))


def start_run(t: Take, why: str) -> dict:
    """The hero scenario once more, through the API exactly as evals/oncall_night.py drives it (the deterministic
    investigator). Off the public demo a run is trusted; on it, the approver key header makes it so. The run token is
    kept for this incident only, never shown."""
    r = t.api("POST", f"/api/scenarios/{urllib.parse.quote(t.a.scenario)}/run", {"llm": "baseline"}, keyed=True)
    inc = r.get("incident")
    if not inc:
        raise fail(f"{why}: the run opened no incident (job state {r.get('state')!r})")
    if r.get("run_token"):
        t.tokens[inc] = r["run_token"]
    return {"incident": inc, "job": r.get("job"), "graph": r.get("graph")}


def stage_of(t: Take, inc: str) -> str:
    return t.api("GET", f"/api/incidents/{urllib.parse.quote(inc)}?{t.q}")["incident"]["stage"]


def wait_stage(t: Take, inc: str, stages: tuple[str, ...], timeout: float, why: str) -> str:
    end = time.monotonic() + timeout
    while True:
        st = stage_of(t, inc)
        if st in stages:
            return st
        if time.monotonic() > end:
            raise fail(f"{why}: {inc} is still {st} after {timeout:.0f} s")
        t.page.wait_for_timeout(500)


def wait_job(t: Take, job: str, timeout: float, why: str) -> dict:
    """Until the run job is done: a standing contract acts BEFORE the job reads done (api._run_job)."""
    end = time.monotonic() + timeout
    while True:
        j = t.api("GET", f"/api/jobs/{job}?{t.q}")
        if j.get("state") != "running":
            return j
        if time.monotonic() > end:
            raise fail(f"{why}: job {job} still running after {timeout:.0f} s")
        t.page.wait_for_timeout(700)


def pages_of(t: Take, inc: str) -> list[dict]:
    return t.api("GET", f"/api/pages?{t.q}&incident={urllib.parse.quote(inc)}")["rows"]


def page_row(t: Take, pid: str, inc: str | None = None) -> dict:
    d = t.api("GET", f"/api/pages/{urllib.parse.quote(pid)}?{t.q}", run_token=t.tokens.get(inc or ""))
    return d.get("page") or {}


def woken(rows: list[dict]) -> list[str]:
    """People woken for an incident: paged or escalated to (a contract notice informs, it never wakes)."""
    return sorted({(p.get("person") or {}).get("id") or "?" for p in rows if p.get("kind") in ("page", "escalation")})


def expect_text(loc: Locator, pattern: str, what: str, timeout: float = 20.0) -> str:
    """Wait for an element of `loc` whose text matches `pattern` (re.search) to be visible; its text, or fail."""
    hit = loc.filter(has_text=re.compile(pattern)).first
    try:
        expect(hit).to_be_visible(timeout=timeout * 1000)
    except AssertionError:
        got = " | ".join(x.strip() for x in loc.all_inner_texts()) or "(not on the page)"
        raise fail(f"{what}: the page shows {got!r}, expected /{pattern}/") from None
    return hit.inner_text().strip()


SETTLE_JS = """(s) => {
  const n = document.querySelectorAll(s).length, now = performance.now();
  if (n !== 1) { window.__settle = null; return false; }
  if (!window.__settle || window.__settle.s !== s) { window.__settle = {s, t: now}; return false; }
  return now - window.__settle.t > 600;
}"""


def settle(where: Page | Frame, sel: str, what: str, timeout: float = 25.0) -> None:
    """Until exactly one `sel` has been on the page for 0.6 s. A route's first mount can briefly hold two copies of its
    tree (the second still reading), and strict locators, flashes and clicks must act on the one that stays."""
    try:
        where.wait_for_function(SETTLE_JS, arg=sel, polling=100, timeout=timeout * 1000)
    except PlaywrightTimeout:
        n = where.locator(sel).count()
        raise fail(f"{what}: {n} copies of {sel} after {timeout:.0f} s (the page never settled)") from None


def said_alert(scope: Page | FrameLocator | Locator) -> Locator:
    """Alerts that say something (Next's route announcer is an always-present, empty role=alert)."""
    return scope.get_by_role("alert").filter(has_text=re.compile(r"\S"))


def show_phone(t: Take, src: str, title: str, note: str, kicker: str) -> FrameLocator:
    """media/phone.html: the live page view at a phone's size (390x844), framed inside the video."""
    t.d.go(f"{t.ui}/media/phone.html")
    if not t.page.evaluate("(o) => window.__phone(o)", {"src": src, "title": title, "note": note, "kicker": kicker}):
        raise fail("media/phone.html refused the page path")
    expect(t.page.locator("body[data-state='ready']")).to_be_attached(timeout=20_000)
    inner = next((f for f in t.page.frames if f.parent_frame is not None and "/oncall/page/" in f.url), None)
    if inner is None:
        raise fail("media/phone.html shows no page view in its frame")
    fr = t.page.frame_locator("#phone")
    try:
        settle(inner, "article[aria-labelledby='page-title']", "the page view at a phone's size", 30)
    except SystemExit:
        said = " | ".join(x.strip() for x in said_alert(fr).all_inner_texts())
        raise fail(f"the page view at a phone's size did not load{': ' + said if said else ''}") from None
    return fr


def after_act(t: Take) -> None:
    """Off screen, right after the take's fix is APPLIED (the take's own incident is RESOLVED, its pages settled): a
    real take with --real-repeat turns the flag back on at main (the fault comes back), then incident B opens, so the
    on-call beats have a page that still waits for an ack."""
    if not any(s in t.S for s in (*ONCALL, "learn")):
        return
    if t.key is not None and t.a.real_repeat and "oc_contract" in t.S:
        t.facts["repeat_commit"] = flag_back_on(t.a.infra_repo, t.a.flag)
    t.b = start_run(t, "incident B")
    t.facts["incident_b"] = t.b["incident"]


def owner_oncall(t: Take, inc: str) -> tuple[str | None, str | None, list[str]]:
    """The failing component's owner team, its name and who is on call for it, as the incident's ROUTE recorded them
    (who_fixes evidence, GET .../plan; team names from GET /api/oncall/now)."""
    w = (t.api("GET", f"/api/incidents/{urllib.parse.quote(inc)}/plan?{t.q}").get("who_fixes") or {}).get("payload") or {}
    team = w.get("owner_team")
    names = {r.get("team"): r.get("team_name") for r in t.api("GET", f"/api/oncall/now?{t.q}").get("rows") or []}
    return team, names.get(team) or team, [str(x) for x in w.get("oncall_now") or []]


def b_page(t: Take) -> dict:
    """B's page for the beats: the open page to the owning team's on-call (one person is paged once, so it may carry
    the learned-responder reason instead), else the newest open page."""
    inc = t.b["incident"]
    st = wait_stage(t, inc, ("AWAITING_APPROVAL", "RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "NO_INCIDENT"), 90,
                    "incident B")
    if st != "AWAITING_APPROVAL":
        raise fail(f"incident B ({inc}) ended {st}, not awaiting approval: no page of it waits for an ack")
    team, team_name, oncall = owner_oncall(t, inc)
    for _ in range(10):
        rows = [p for p in pages_of(t, inc) if open_page(p)]
        if rows:
            rows.sort(key=lambda p: ((p.get("person") or {}).get("id") not in oncall,
                                     "(the failing component)" not in (p.get("reason") or ""), -(p.get("sent_at") or 0)))
            pg = dict(rows[0])
            pg["_owner"] = {"team": team, "team_name": team_name, "oncall": oncall,
                            "is_owner_oncall": (pg.get("person") or {}).get("id") in oncall}
            return pg
        t.page.wait_for_timeout(int(PAGE_POLL_S * 1000))
    raise fail(f"incident B ({inc}) is awaiting approval but paged nobody (GET /api/pages?incident=)")


def beat_oc_page(t: Take) -> None:
    """The incident pages the on-call: /oncall (the verdict line, B's page in the pager inbox), then the page's own
    link at a phone's size. Checks: the page waits for an ack; it went to the owning team's on-call when the voice says
    so; the page count when the voice says one; the proof path and who fixes it when the voice names them."""
    d, page, seg = t.d, t.page, t.S["oc_page"]
    inc = t.b["incident"]
    pg = t.pg = b_page(t)   # before the beat: any wait here is a pause, not narration
    pid, reason, owner = pg["id"], pg.get("reason") or "", pg["_owner"]
    name = (pg.get("person") or {}).get("name") or (pg.get("person") or {}).get("id") or "?"
    if re.search(r"\bon[ -]call\b|owning team|owner team|team that owns", seg.text, re.I) and not owner["is_owner_oncall"]:
        raise fail(f"the voice says the owning team's on-call is paged; B's open page went to {name} ({reason!r}), and "
                   f"{owner['team_name']}'s on-call is {owner['oncall'] or 'nobody'} (who_fixes evidence)")
    note = (f"To {name}, on call for {owner['team_name']}, which owns the failing component" if owner["is_owner_oncall"]
            else f"To {name}: {reason}") + (" (and the person who usually answers it)." if "learned responder" in reason
                                             else ".")
    d.begin("oc_page")
    d.go(f"{t.ui}/oncall?{t.q}")
    settle(page, "#oncall-verdict", "/oncall")
    head = expect_text(page.locator("#oncall-verdict"), r"^\d+ pages? waiting for an ack$", "the /oncall verdict line")
    said = numbers_said(seg.text, r"\b(\w+) pages? (?:is |are )?waiting")
    if said and said[0] != int(head.split()[0]):
        raise fail(f"the voice says {said[0]} page(s) waiting; /oncall says {head!r}")
    inbox = page.locator("section[aria-labelledby='pager-h']")
    item = inbox.get_by_role("listitem").filter(
        has=page.get_by_role("link", name=f"Open page {pid}, as the person paged sees it"))
    expect(item).to_be_visible(timeout=20_000)   # the inbox re-reads every 5 s
    d.show(item, "center")
    d.at_cue(("pages", "paged", "page"), 0.3, lead=0.2)
    d.flash(item)
    d.hover(item.get_by_role("link", name=inc, exact=True))
    token = page_row(t, pid, inc).get("ack_token")
    if not token:
        raise fail(f"the API gives no ack token for B's page {pid} (a public API gives it to the run's owner only)")
    src = f"/oncall/page/{urllib.parse.quote(pid)}?{t.q}&t={urllib.parse.quote(token, safe='')}"
    d.at_cue(("on a phone", "phone", "opens"), 0.55, lead=0.4)
    link = item.get_by_role("link", name=f"Open page {pid}, as the person paged sees it")
    d.hover(link)
    d.flash(link)
    d.wait(350)
    fr = t.phone = show_phone(t, src, "The page, on a phone", note, "On call · the page link")
    title, alert = fr.locator("#page-title"), said_alert(fr)
    expect(title.or_(alert).first).to_be_visible(timeout=30_000)
    if not title.is_visible():
        raise fail(f"the phone page view says {alert.first.inner_text()!r}")
    ack = fr.get_by_role("button", name="Acknowledge this page")
    if not ack.is_visible():
        raise fail(f"the phone page view of {pid} offers no Acknowledge: it no longer waits for an ack")
    facts: dict[str, Any] = {"incident": inc, "page": pid, "to": name, "reason": reason, "urgency": pg.get("urgency"),
                             "owner_team": owner["team"], "owner_oncall": owner["is_owner_oncall"], "verdict_line": head}
    if re.search(r"proof path", seg.text, re.I):
        proof = fr.get_by_role("list", name="Proof path, cause first")
        expect(proof).to_be_visible(timeout=20_000)
        hops = proof.get_by_role("listitem").all_inner_texts()
        if len(hops) < 2:
            raise fail(f"the voice names the proof path; the phone page shows {hops}")
        facts["proof"] = [h.split("\n")[0] for h in hops]
        d.at_cue(("proof path",), 0.7, lead=0.3)
        sec = fr.locator("section[aria-labelledby='proof-h']")
        d.show(sec, "center")
        d.flash(sec)
    if re.search(r"who fixes", seg.text, re.I):
        ranked = fr.get_by_role("list", name="People ranked by the graph")
        expect(ranked).to_be_visible(timeout=20_000)
        if not ranked.get_by_role("listitem").count():
            raise fail("the voice names who fixes it; the phone page ranks nobody")
        d.at_cue(("who fixes",), 0.85, lead=0.3)
        sec = fr.locator("section[aria-labelledby='pagewho-h']")
        d.show(sec, "center")
        d.flash(sec)
    d.end(0.5)
    d.show(ack, "center")   # back up to the Acknowledge button for the next beat
    t.facts["oc_page"] = facts


def beat_oc_ack(t: Take) -> None:
    """One tap on Acknowledge (the page link's signed token). Checks: the page says the escalation stopped; the graph
    says the page is acked by the person paged and no page of B waits; off the public demo, the engine's own escalation
    pass a day later (scripted clock, scoped to B) escalates nothing."""
    d, fr, pg, inc = t.d, t.phone, t.pg, t.b["incident"]
    if fr is None or pg is None:
        raise fail("oc_ack needs the oc_page beat before it (the page on the phone)")
    pid = pg["id"]
    before = page_row(t, pid, inc)
    if not open_page(before):
        raise fail(f"B's page {pid} is {before.get('status')} before the ack beat (did its ack window pass?)")
    d.begin("oc_ack")
    btn = fr.get_by_role("button", name="Acknowledge this page")
    d.show(btn, "center")
    d.at_cue(("tap", "acknowledges", "acknowledge"), 0.08, lead=0.25)
    d.click(btn)
    done = fr.get_by_role("status").filter(has_text=re.compile(r"Acked: the escalation (stops here|stopped)"))
    bad = said_alert(fr)
    expect(done.or_(bad).first).to_be_visible(timeout=20_000)
    if not done.count():
        raise fail(f"the ack failed on the phone page: {bad.first.inner_text()!r}")
    after = page_row(t, pid, inc)
    by = ((after.get("ack") or {}).get("by") or {})
    if after.get("status") != "acked" or not by.get("id"):
        raise fail(f"after the tap the graph says page {pid} is {after.get('status')} (ack {after.get('ack')})")
    left = [p["id"] for p in pages_of(t, inc) if open_page(p)]
    if left:
        raise fail(f"after the ack, B still has pages waiting: {left}")
    later = None
    if not t.public:
        later = t.api("POST", f"/api/oncall/tick?{t.q}", {"now": int(time.time() * 1000) + 86_400_000,
                                                            "incident": inc}).get("escalated")
        if later:
            raise fail(f"after the ack, an escalation pass a day later still escalates {later}")
    d.at_cue(("escalation stops", "escalation", "stops"), 0.45, lead=0.2)
    d.wait(300)
    d.show(done.first, "center")
    d.flash(done.first)
    t.facts["oc_ack"] = {"page": pid, "by": by.get("id"), "via": (after.get("ack") or {}).get("via"),
                         "escalated_a_day_later": None if later is None else len(later)}


def beat_oc_contract(t: Take) -> None:
    """A standing approval, then the same fault again with nobody woken. In the take's incident room: Grant a contract
    for repeats (step 1: the scope typed, the exact contract shown; step 2: granted). Off screen: incident C (the same
    scenario, through the API). On screen while it runs and after: /oncall's contracts panel, the 'Handled while you
    slept' tile, the pager's entries for C, and C's contract-notice page at a phone's size. Checks: the scope is the one
    the voice says; C is RESOLVED with its fix APPLIED under this contract; nobody was paged or escalated to for C (the
    graph and the page agree); the tile counts one more incident handled under a contract."""
    d, page, a, seg = t.d, t.page, t.a, t.S["oc_contract"]
    uses, days = int(a.contract_uses), int(a.contract_days)
    if not t.inc_a:
        raise fail("oc_contract needs the take's fixed incident")
    d.begin("oc_contract")
    d.go(f"{t.ui}/incidents/{urllib.parse.quote(t.inc_a)}?{t.q}")
    settle(page, "section[aria-labelledby='plan-h']", "the take's incident room")
    plan = page.locator("section[aria-labelledby='plan-h']")
    open_btn = plan.get_by_role("button", name=re.compile(r"^Grant a contract for repeats"))
    expect(open_btn).to_be_visible(timeout=30_000)
    d.show(open_btn, "center")
    d.at_cue(("standing approval", "grant"), 0.08, lead=0.3)
    d.click(open_btn)
    form = plan.get_by_role("region", name="Grant a contract for repeats")
    err = said_alert(form)
    for label, n in ((r"^Max uses", uses), (r"^For how many days", days)):
        box = form.get_by_label(re.compile(label))
        expect(box).to_be_visible()
        d.click(box, flash=False)
        box.press("Control+a")
        box.press_sequentially(str(n), delay=60)
    d.click(form.get_by_role("button", name=re.compile(r"^Choose this scope")))
    exact = form.get_by_role("region", name="Exact contract")
    expect(exact.or_(err).first).to_be_visible(timeout=20_000)
    if not exact.count():
        raise fail(f"choosing the contract scope failed: {err.first.inner_text()!r}")
    d.show(exact, "center")
    d.flash(exact)
    k = t.key if t.key is not None else (t.api_key if t.public else None)
    if k is not None:
        field_ = form.get_by_label(re.compile(r"^Approver key \(sent with this grant only"))
        try:
            expect(field_).to_be_visible()
            if field_.get_attribute("type") != "password":
                field_.evaluate(MASK_JS)
                t.facts["key_field_masked"] = True
            field_.press_sequentially(k, delay=20)
        except Exception as e:  # noqa: BLE001 - never let an error message carry the key
            raise fail(f"could not enter the approver key for the grant ({type(e).__name__}; value not shown)") from None
    d.click(form.get_by_role("button", name="Grant this exact contract"))
    granted = plan.get_by_role("status").filter(has_text=re.compile(r"Contract ct-[0-9a-f]{16} granted"))
    expect(granted.or_(err).first).to_be_visible(timeout=20_000)
    if not granted.count():
        raise fail(f"the grant failed: {err.first.inner_text()!r}")
    cid = re.search(r"ct-[0-9a-f]{16}", granted.first.inner_text()).group(0)
    d.show(granted.first, "center")
    d.flash(granted.first)
    ct = next((c for c in t.api("GET", f"/api/contracts?{t.q}")["rows"] if c["id"] == cid), None)
    if not ct or ct.get("status") != "active" or ct.get("max_uses") != uses or ct.get("uses") \
            or float(ct.get("days") or 0) != days:
        raise fail(f"the graph does not hold contract {cid} as granted (active, {uses} use(s) over {days} days, none "
                   f"used): {ct}")

    # ---- the same fault again: incident C, off screen, through the API
    d.at_cue(("same fault", "comes back", "again"), 0.42, lead=0.2)
    t.c = start_run(t, "incident C (the same fault again)")
    inc = t.c["incident"]
    d.chip("repeat", f"The same fault again: {inc}, started through the API", "url")
    d.go(f"{t.ui}/oncall?{t.q}")
    settle(page, "section[aria-labelledby='contracts-h']", "/oncall")
    cards = page.locator("section[aria-labelledby='contracts-h']")
    mine = cards.get_by_role("listitem").filter(has_text=cid)
    expect(mine.first).to_be_visible(timeout=20_000)
    d.show(mine.first, "center")
    d.flash(mine.first)
    j = wait_job(t, t.c["job"], 300 if t.key is not None else 150, "incident C")
    st = stage_of(t, inc)
    rows = pages_of(t, inc)
    ct = next((c for c in t.api("GET", f"/api/contracts?{t.q}")["rows"] if c["id"] == cid), {})
    used = (ct.get("used_in") or [{}])[0]
    awake = woken(rows)
    notices = [p for p in rows if p.get("kind") == "contract_notice"]
    if st != "RESOLVED" or used.get("incident") != inc or used.get("verdict") != "APPLIED":
        raise fail(f"the same fault again was not fixed under {cid}: {inc} is {st} (job {j.get('state')}), the "
                   f"contract's last use is {used or 'none'}; pages: {[(p.get('kind'), p.get('status')) for p in rows]}")
    if awake or not notices:
        raise fail(f"{inc} under contract {cid} woke {awake or 'nobody'} and sent {len(notices)} contract notice(s)")
    if uses == 1 and ct.get("status") != "exhausted":
        raise fail(f"contract {cid} had one use and reads {ct.get('status')} after it")
    handled = t.api("GET", f"/api/oncall/stats?{t.q}&days=7").get("handled_under_contract")
    if t.handled_before is not None and (handled is None or handled < t.handled_before + 1):
        raise fail(f"'handled under a contract' (7 days) went from {t.handled_before} to {handled}, not up by one")

    # ---- on screen: what the graph says now
    d.at_cue(("verifies", "verified", "runs"), 0.66, lead=0.2)
    d.go(f"{t.ui}/oncall?{t.q}")
    settle(page, "section[aria-labelledby='contracts-h']", "/oncall")
    cards = page.locator("section[aria-labelledby='contracts-h']")
    if ct.get("status") != "active":   # used up: listed under "Past contracts", folded
        past = cards.get_by_role("button", name=re.compile(r"^Past contracts"))
        expect(past).to_be_visible(timeout=20_000)
        if past.get_attribute("aria-expanded") != "true":
            d.click(past)
    mine = cards.get_by_role("listitem").filter(has_text=cid)
    expect(mine.first).to_be_visible(timeout=20_000)
    expect_text(mine.first, rf"used on\s*{re.escape(inc)}\s*\(APPLIED\)", f"contract {cid} on /oncall")
    d.show(mine.first, "center")
    d.flash(mine.first)
    tile = page.locator("section[aria-labelledby='oncall-stats-h'] dl > div").filter(has_text="Handled while you slept")
    value = expect_text(tile.locator("dd").first, r"^\d[\d,]*$", "the 'Handled while you slept' tile")
    if int(value.replace(",", "")) != handled:
        raise fail(f"the 'Handled while you slept' tile shows {value}; the API says {handled}")
    d.at_cue(("while you slept", "slept"), 0.8, lead=0.3)
    d.show(tile, "center")
    d.flash(tile)
    inbox = page.locator("section[aria-labelledby='pager-h']")
    d.click(inbox.get_by_role("button", name=re.compile(r"^All · \d+")))
    mine_pages = inbox.get_by_role("list", name="All pages").get_by_role("listitem").filter(
        has=page.get_by_role("link", name=inc, exact=True))
    expect(mine_pages.first).to_be_visible(timeout=20_000)
    on_page = mine_pages.all_inner_texts()
    awake_page = [x for x in on_page if "contract notice" not in x]
    if awake_page or len(on_page) != len(rows):
        raise fail(f"the pager lists {len(on_page)} page(s) for {inc}, {len(awake_page)} of them not a contract notice; "
                   f"the graph has {len(rows)}")
    said = numbers_said(seg.text, r"\b(\w+) (?:people|persons?|humans?) (?:were |was )?(?:woken|woke|paged)")
    if said and said[0] != len(awake):
        raise fail(f"the voice says {said[0]} people woken; the graph and the pager say {len(awake)}")
    d.at_cue(("woken", "nobody", "no one"), 0.9, lead=0.4)
    d.show(mine_pages.first, "center")
    d.flash(mine_pages.first)
    n = notices[0]
    nname = (n.get("person") or {}).get("name") or (n.get("person") or {}).get("id") or "the on-call"
    d.chip("repeat", None)   # the phone frame's top line sits where the chip is
    fr = show_phone(t, f"/oncall/page/{urllib.parse.quote(n['id'])}?{t.q}", "A note, not a wake-up",
                    f"To {nname}: {inc} was fixed under contract {cid}. Nobody was paged.", "On call · contract notice")
    try:
        expect(fr.get_by_text(re.compile(r"Faultline page · contract notice"))).to_be_visible(timeout=30_000)
        if n.get("status") != "delivery_failed":   # a notice an external channel did not take says that instead
            expect(fr.get_by_text("FYI · no wake").first).to_be_visible()
    except AssertionError:
        raise fail(f"the contract-notice page {n['id']} does not read as a notice ('FYI · no wake') at a phone's size") \
            from None
    d.end(0.2)
    t.facts["oc_contract"] = {"contract": cid, "uses": uses, "days": days, "incident_c": inc, "stage": st,
                              "verdict": used.get("verdict"), "woken": len(awake), "notices": len(notices),
                              "handled_7d": [t.handled_before, handled]}


def moved_up(options: list[dict]) -> list[tuple[str, int, int]]:
    """(option, place now, place without learning) for each option learning moved up, from GET .../plan."""
    out = []
    for i, o in enumerate(options, start=1):
        lr = o.get("learned")
        if isinstance(lr, str):
            try:
                lr = json.loads(lr)
            except ValueError:
                lr = None
        r = (lr or {}).get("rank_without_learning") if isinstance(lr, dict) else None
        if isinstance(r, int) and r > i:
            out.append((o.get("option") or o.get("id") or "?", i, r))
    return out


def beat_learn(t: Take) -> None:
    """What Faultline learned (/memory#learned): preferences with their why lines, guidelines, learned responders,
    each flashed as the voice names it; then incident B's plan, where an option learning moved shows "moved up from #N".
    Checks: every section the voice names has rows; the moved-up number is the one the voice says."""
    d, page, seg = t.d, t.page, t.S["learn"]
    text = seg.text
    want_n = numbers_said(text, r"moved up from (?:number |#)?(\w+)")
    d.begin("learn")
    d.go(f"{t.ui}/memory?{t.q}#learned")
    settle(page, "section#learned", "/memory#learned")
    panel = page.locator("section#learned")
    expect_text(panel.locator("p[aria-live='polite']").first, r"^Learned from \d+ events?", "What Faultline has learned")
    d.glide(panel, "start", 900)
    learned = t.api("GET", f"/api/learned?{t.q}")
    shown: dict[str, int] = {}
    for words, sec, list_name, frac in ((("prefers", "prefer", "preferences"), "preferences",
                                         "Learned preferences by family", 0.15),
                                        (("guidelines", "guideline"), "guidelines", "Proposed and active guidelines", 0.4),
                                        (("responds", "responders", "respond"), "responders", "Learned responders", 0.55)):
        if not any(re.search(rf"\b{w}\b", text, re.I) for w in words):
            continue
        lst = panel.get_by_role("list", name=list_name)
        try:
            expect(lst).to_be_visible(timeout=20_000)
        except AssertionError:
            raise fail(f"the voice names learned {sec}; /memory#learned has no list {list_name!r}") from None
        items = lst.get_by_role("listitem")
        if not items.count():
            raise fail(f"the voice names learned {sec}; /memory#learned lists none")
        shown[sec] = items.count()
        if sec == "preferences":   # "and why": the why line the server wrote is on the page
            lines = [r["line"] for r in (learned.get("preferences") or {}).get("rows") or [] if r.get("line")]
            if re.search(r"\bwhy\b", text, re.I) and not any(ln in lst.inner_text() for ln in lines):
                raise fail("the voice says why; no preference's why line is on /memory#learned")
        d.at_cue(words, frac, lead=0.3)
        d.show(items.first, "center")
        d.flash(items.first)
    t.facts["learn"] = {"shown": shown}
    if not want_n and not re.search(r"\bmoved up\b", text, re.I):
        d.end(0.2)
        return
    inc = t.b["incident"] if t.b else None
    if not inc:
        raise fail("the learn beat shows incident B's plan; B was not opened")
    wait_stage(t, inc, ("AWAITING_APPROVAL",), 90, "incident B (its plan is shown)")
    opts = t.api("GET", f"/api/incidents/{urllib.parse.quote(inc)}/plan?{t.q}").get("options") or []
    moved = moved_up(opts)
    hit = [m for m in moved if not want_n or m[2] == want_n[0]]
    if not hit:
        raise fail(f"the voice says an option moved up from #{want_n[0] if want_n else '?'}; B's plan moved {moved or 'none'}"
                   " (the family needs learn.pref_min_n trusted choices; see /memory#learned)")
    d.at_cue(("next plan", "plan", "moved up"), 0.7, lead=0.4)
    d.go(f"{t.ui}/incidents/{urllib.parse.quote(inc)}?{t.q}")
    settle(page, "section[aria-labelledby='plan-h']", "incident B's room")
    plan = page.locator("section[aria-labelledby='plan-h']")
    chip = plan.get_by_text(f"moved up from #{hit[0][2]}", exact=True)
    expect(chip.first).to_be_visible(timeout=30_000)
    opt = plan.get_by_role("list", name="Action options").get_by_role("listitem").filter(
        has=page.get_by_text(f"moved up from #{hit[0][2]}", exact=True))
    d.show(opt.first, "center")
    d.at_cue(("moved up",), 0.85, lead=0.4)
    d.flash(opt.first)
    t.facts["learn"]["moved"] = {"incident": inc, "option": hit[0][0], "now": hit[0][1], "without_learning": hit[0][2]}
    d.end(0.2)


def beat_engine(t: Take) -> None:
    """Inside FalkorDB, right now (/engine): the verdict line, the memory per graph, the queries per template from the
    engine's own telemetry, the live tail. Checks: each has rows; a graph count the voice says matches the page."""
    d, page, seg = t.d, t.page, t.S["engine"]
    d.begin("engine")
    d.go(f"{t.ui}/engine?{t.q}")
    settle(page, "#engine-verdict", "/engine")
    head = expect_text(page.locator("#engine-verdict"), r"^FalkorDB\b.*\b\d+ graphs? for ", "the /engine verdict line", 30)
    n_graphs = int(re.search(r"\b(\d+) graphs? for ", head).group(1))
    said = numbers_said(seg.text, r"\b(\w+) graphs\b")
    if said and said[0] != n_graphs:
        raise fail(f"the voice says {said[0]} graphs; /engine says {head!r}")
    mem = page.locator("section[aria-labelledby='engine-memory-h']")
    graphs = mem.get_by_role("list", name="Graphs of this tenant").get_by_role("listitem")
    queries = page.locator("section[aria-labelledby='engine-queries-h']")
    rows = queries.locator("table tbody tr")
    tail = page.locator("section[aria-labelledby='engine-tail-h']")
    recent = tail.get_by_role("list", name="Most recent queries, newest first").get_by_role("listitem")
    for loc, what in ((graphs, "memory per graph"), (rows, "queries by template"), (recent, "the live tail")):
        expect(loc.first).to_be_visible(timeout=20_000)
    d.at_cue(("memory",), 0.3, lead=0.3)
    d.show(mem, "start")
    d.flash(mem)
    d.at_cue(("template", "templates", "query"), 0.55, lead=0.3)
    d.show(queries, "start")
    d.flash(rows.first)
    d.at_cue(("live tail", "tail"), 0.8, lead=0.3)
    d.show(tail, "start")
    d.flash(recent.first)
    t.facts["engine"] = {"verdict": head, "graphs": graphs.count(), "templates": rows.count(), "tail": recent.count()}
    d.end(0.2)


def beat_preflight(d: Director, page: Page, ui: str) -> None:
    """(Earlier cuts; runs only when the narration has a "preflight" segment.) The same graph blocks the risky PR; its
    numbers were checked against the page in the pre-roll."""
    d.begin("preflight")
    d.go(f"{ui}/preflight")
    d.click(page.get_by_role("button", name=re.compile(r"^S6: payment timeout 5000 ms")))
    pv = page.locator("[data-verdict]").first
    expect(pv).to_be_visible(timeout=30_000)
    d.show(pv, "center")
    assess = page.locator("section[aria-labelledby='pf-assess-h']")
    d.at_word("contradicts", lead=0.3)
    d.show(assess)
    for li in assess.get_by_role("listitem").filter(has_text="contradicted").all()[:3]:
        d.flash(li)
    d.at_word("Blocked", lead=0.3)
    d.show(pv, "center")
    d.flash(pv)


def beat_brain(d: Director, page: Page, ui: str, question: str) -> str:
    """(Earlier cuts; runs only when the narration has a "brain" segment.) Who decided, and are they still here: the
    answer must pass its citation guard."""
    d.begin("brain")
    d.go(f"{ui}/brain")
    box = page.get_by_label("Question", exact=True)
    expect(box).to_be_visible(timeout=20_000)
    d.click(box)
    box.press_sequentially(question, delay=12)
    box.press("Enter")
    answer = page.locator("section[aria-labelledby='brain-answer-h']")
    guard = answer.get_by_text(re.compile(r"^citation guard [✓✗]$")).first
    berr = answer.get_by_role("alert")
    expect(guard.or_(berr).first).to_be_visible(timeout=30_000)
    if not guard.count() or "✓" not in guard.inner_text():
        raise fail(f"brain answer not cited cleanly: {(berr.first.inner_text() if berr.count() else guard.inner_text())!r}")
    ag = answer.get_by_role("group", name=re.compile(r"^Answer graph: \d+ nodes"))
    expect(ag).to_be_visible(timeout=20_000)
    d.at_word("comes from a query", lead=0.2)
    d.show(ag, "center")
    return question


# ------------------------------------------------------------------ the recording

def record(a: argparse.Namespace, work: Path, segs: list[Seg], llm: dict, issue: dict,
           key: str | None, oc: dict, api_key: str | None) -> tuple[Path, Director, dict]:
    ui = a.ui.rstrip("/")
    S = {s.id: s for s in segs}
    order = [s.id for s in segs]
    partial = a.from_segment is not None
    last = a.to_segment or order[-1]

    def want(sid: str) -> bool:
        """Does this beat run? (A partial take runs every beat up to --to-segment; those before --from-segment fast.)"""
        return sid in S and order.index(sid) <= order.index(last)

    facts: dict[str, Any] = {"real_github": a.real_github, "key_field_masked": False,
                             "oncall_api": {"public": oc.get("public"), "channels": oc.get("channels"),
                                            "handled_under_contract_7d": oc.get("handled_before")}}
    with sync_playwright() as p:
        if a.gpu:   # the NVIDIA GPU through ANGLE/EGL (PRIME offload): the 3D renders at full frame rate
            args = ["--use-gl=angle", "--use-angle=gl-egl", "--ignore-gpu-blocklist", "--enable-gpu"]
            env = {**os.environ, "__NV_PRIME_RENDER_OFFLOAD": "1", "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
                   "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/10_nvidia.json"}
        else:       # software WebGL: works anywhere, but the 3D stutters on video
            args, env = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"], None
        browser = p.chromium.launch(executable_path=a.chromium, args=args, env=env) if a.chromium \
            else p.chromium.launch(args=args, env=env)
        if a.gpu:
            page0 = browser.new_page()
            renderer = page0.evaluate("() => { const g = document.createElement('canvas').getContext('webgl2');"
                                      " const x = g && g.getExtension('WEBGL_debug_renderer_info');"
                                      " return x ? g.getParameter(x.UNMASKED_RENDERER_WEBGL) : ''; }")
            page0.close()
            if "SwiftShader" in renderer or not renderer:
                raise fail(f"--gpu, but WebGL renders on {renderer or 'nothing'!r}")
            facts["renderer"] = renderer
        ctx = browser.new_context(viewport=VIEW, record_video_dir=str(work), record_video_size=VIEW, device_scale_factor=1)
        ctx.add_init_script(INIT_JS)
        page = ctx.new_page()
        d = Director(page, S, time.monotonic())
        page.set_default_timeout(30_000)

        # ---------------- pre-roll (trimmed): status, WebGL, re-arm, one validation run, every value checked
        page.goto(f"{ui}/?tenant={a.tenant}")
        ready = page.get_by_text("FalkorDB ready").first
        down = page.get_by_text(re.compile(r"^(API unreachable|FalkorDB unavailable)$")).first
        expect(ready.or_(down).first).to_be_visible(timeout=30_000)
        if down.is_visible():
            raise fail(f"the UI says {down.inner_text()!r}; start FalkorDB and the API first")
        if not page.evaluate("() => { try { return !!document.createElement('canvas').getContext('webgl2'); }"
                             " catch (e) { return false; } }"):
            raise fail("no WebGL in this browser, so the hero cube cannot render: pass --chromium <full chrome>")
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
        run_btn = page.get_by_role("button", name=re.compile(rf"^Run scenario {a.scenario} with the baseline investigator$"))
        t_run = time.monotonic()
        run_btn.click()
        page.wait_for_url(re.compile(rf"/incidents/inc-{a.scenario.lower()}-"), timeout=90_000)
        expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=120_000)
        facts["validation_run_s"] = round(time.monotonic() - t_run, 1)
        _, v = read_room(page, a)
        n = len(v["suspects"])
        # the voice and the cards state these about the page: check them against the page now
        for sid, pat in (("problem", r"\b(\w+) changes went live"), ("x_path", r"\b(\w+) deploys landed")):
            said = number_said(S[sid].text, pat)
            if said is not None and said != n:
                raise fail(f"the narration ({sid}) says {said} suspects, the incident room shows {n}: {v['suspects']}")
        if n != 3:
            raise fail(f"hook.html says three changes went live; the incident room shows {n}: {v['suspects']}")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import narrate  # noqa: E402

        said_flow = narrate.spoken(float(v["flow"]), "pct")
        if said_flow not in S["x_flow"].text:
            raise fail(f"the page's max flow {v['flow']} is {said_flow}, which the x_flow narration does not say")
        facts.update(suspects=v["suspects"], g5={"flow": v["flow"], "needed": v["needed"]}, chain=v["chain"])
        t = Take(a, page, d, S, facts, ui, key, api_key, bool(oc.get("public")), oc.get("handled_before"))
        if any(s in S for s in ONCALL) or "learn" in S:
            # the validation incident paged the on-call: its ack window must outlast oc_page (B escalates otherwise)
            inc_v = incident_of(page.url)
            facts["validation_incident"] = inc_v
            open_v = [p for p in pages_of(t, inc_v) if open_page(p) and p.get("ack_due_at") and p.get("sent_at")]
            if not open_v:
                raise fail(f"the validation incident {inc_v} paged nobody (GET /api/pages): the on-call beats need a page")
            win = min((p["ack_due_at"] - p["sent_at"]) / 1000 for p in open_v)
            facts["ack_window_s"] = round(win)
            if win < MIN_ACK_WINDOW_S:
                raise fail(f"pages wait only {win:.0f} s for an ack (FAULTLINE_ONCALL_DEMO_WINDOWS?): B would escalate "
                           f"before oc_ack; restart the API without it (at least {MIN_ACK_WINDOW_S} s)")
            # the validation incident's pages are the pre-roll's, not the take's: settle them now, or the inbox the
            # on-call beats film shows them waiting (and escalating) while the voice says nobody was woken. One ack
            # with the approver key (anonymous: no person credited, nothing learned) supersedes the incident's others.
            if key or api_key:
                api_req(a.api, "POST", f"/api/pages/{urllib.parse.quote(open_v[0]['id'])}/ack?{t.q}", {},
                        {"X-Faultline-Approver-Key": key or api_key})
                left = [p for p in pages_of(t, inc_v) if open_page(p)]
                if left:
                    raise fail(f"the validation incident {inc_v} still has {len(left)} open page(s) after its ack")
                facts["validation_pages_settled"] = True
            if "learn" in S and numbers_said(S["learn"].text, r"moved up from (?:number |#)?(\w+)"):
                mv = moved_up(t.api("GET", f"/api/incidents/{urllib.parse.quote(inc_v)}/plan?{t.q}").get("options") or [])
                facts["moved_on_validation_plan"] = mv
                if not mv:   # B's plan (the one shown) also counts the take's approval, so this is only a warning
                    print("  warning: the validation incident's plan has no option moved up by learning; the learn beat "
                          "fails unless incident B's plan has one", file=sys.stderr)
        if "preflight" in S:
            page.goto(f"{ui}/preflight")
            page.get_by_role("button", name=re.compile(r"^S6: payment timeout 5000 ms")).click()
            expect(page.locator("[data-verdict]").first).to_be_visible(timeout=30_000)
            pf_verdict = page.locator("[data-verdict]").first.get_attribute("data-verdict")
            adrs = sorted({m.group(0) for t_ in page.locator("section[aria-labelledby='pf-assess-h']")
                           .get_by_role("listitem").filter(has_text="contradicted").all_inner_texts()
                           if (m := re.search(r"\b[A-Z]+-\d+\b", t_))})
            said = number_said(S["preflight"].text, r"contradicts (\w+) decisions")
            if said is not None and said != len(adrs):
                raise fail(f"the narration says the PR contradicts {said} decisions; the page shows {adrs}")
            if pf_verdict != "block" and re.search(r"\bBlocked\b", S["preflight"].text):
                raise fail(f"the narration says blocked; the preflight verdict is {pf_verdict}")
            facts["preflight"] = {"verdict": pf_verdict, "contradicted": adrs}
        # the v4 pages must be the live server's (a static replay build shows "live server only" cards instead)
        for sid, path, ready_sel in (("oc_page", "/oncall", "#oncall-verdict"), ("learn", "/memory", "#learned-h"),
                                     ("engine", "/engine", "#engine-verdict")):
            if sid in S:
                page.goto(f"{ui}{path}?tenant={a.tenant}")
                try:
                    expect(page.locator(ready_sel)).to_be_attached(timeout=30_000)
                except AssertionError:
                    raise fail(f"{ui}{path} shows no {ready_sel}: is the UI the live build, and as new as the API?") from None
                if page.get_by_text(re.compile(r"live server only", re.I)).count():
                    raise fail(f"{ui}{path} is the static replay build ('live server only'); record on the live UI")

        # ---------------- 0:00 problem, then use case: the hook card, line by line with the voice
        if partial:   # a partial take: no opening; the beats before --from-segment run fast and untimed
            d.fast, d.live_from = True, a.from_segment
            d.start()
        else:
            d.go(f"{ui}/media/hook.html")
            page.evaluate("() => document.fonts.ready")
            if not page.evaluate("() => [...document.fonts].some((x) => x.family.replace(/[\"']/g, '') === 'Mona Sans'"
                                 " && x.status === 'loaded')"):
                print("  warning: Mona Sans did not load on the hook card (offline?); a fallback face is shown",
                      file=sys.stderr)
            d.move_xy(VIEW["width"] + 40, VIEW["height"] / 2, 30)  # the pointer waits off screen
            step = lambda n: page.evaluate("(n) => window.__step(n)", n)  # noqa: E731
            # sync marker, still in the trimmed pre-roll: a white square, timed once it has painted; the encoder finds
            # it in the video to know exactly where the kept footage starts
            page.evaluate(SYNC_ON_JS)
            t_mark = time.monotonic()
            d.wait(400)
            page.evaluate("() => document.getElementById('__demo_sync')?.remove()")
            d.wait(600)
            d.start()
            d.marks["sync"] = t_mark - (d.t0 or t_mark)  # negative: seconds before the kept footage
            d.begin("problem")
            step(1)
            d.at_word("three changes", lead=0.2)
            step(2)
            d.at_word("Which one", lead=0.1)
            step(3)
            d.at_word("Roll back", lead=0.2)
            step(4)
            d.begin("whyhard")
            step(5)
            d.at_word("Dashboards", lead=0.2)
            step(6)
            d.at_word("today's", lead=0.2)
            step(7)
            d.begin("idea")
            step(8)
            d.at_word("That's Faultline", lead=0.2)
            step(9)
            d.at_word("the engine", lead=0.2)
            step(10)

            # ---------------- cube: the website's hero; the cube opens into the hero incident's graph
            d.begin("cube")
            d.go(f"{ui}/?tenant={a.tenant}")
            expect(page.get_by_role("heading", name=re.compile(r"No path,\s*no claim"))).to_be_visible(timeout=20_000)
            cube = page.get_by_role("button", name=re.compile(r"^Click the cube"))
            expect(cube).to_be_visible(timeout=20_000)
            d.move_xy(VIEW["width"] * 0.27, VIEW["height"] * 0.42, 700)
            d.hover(cube)  # the closed cube's seams widen under the pointer: it can open
            d.at_word("Open it", lead=0.2)
            d.click(cube, flash=False)  # an outline would box the 3D canvas
            expect(page.get_by_role("button", name=re.compile(r"^Click to close"))).to_be_visible(timeout=5_000)
            box = page.get_by_role("button", name=re.compile(r"^Click to close")).bounding_box()
            if box:  # sweep across the open graph: the block under the pointer names itself
                for fx, fy in ((0.3, 0.42), (0.5, 0.55), (0.66, 0.4)):
                    if d.left() < 1.2:
                        break
                    d.move_xy(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy, 800)
                    d.wait(250)

            # ---------------- x_*: how FalkorDB does it, one explainer scene per narration segment
            # the stage fills the frame; it shows each scene's FalkorDB calls, and the video's subtitles carry the words
            d.go(f"{ui}/explainer?view=stage&autoplay=0&captions=chips")
            expect(page.locator("[data-scene]").first).to_be_attached(timeout=20_000)
            page.wait_for_function("() => !!window.__explainer && window.__explainer.state().mode === 'animated'",
                                   timeout=20_000)
            if page.evaluate("() => window.__explainer.sceneCount") != len(EXPLAINER):
                raise fail("the explainer's scenes differ from the narration's x_* segments")
            d.move_xy(VIEW["width"] + 40, VIEW["height"] / 2, 30)
            for i, sid in enumerate(EXPLAINER, start=1):
                d.begin(sid)   # each scene plays across its whole narration line, then holds its last frame
                page.evaluate("([n, s]) => window.__explainer.playScene(n, s)", [i, max(1.0, S[sid].length - 0.4)])

        # ---------------- run: the hero incident, live from the launcher
        d.begin("run")
        d.go(f"{ui}/?tenant={a.tenant}#run")   # the launcher lives on the home page
        d.glide(page.locator("#run"), "start", 600)
        d.click(run_btn)
        page.wait_for_url(re.compile(rf"/incidents/inc-{a.scenario.lower()}-"), timeout=90_000)
        d.reapply()
        facts["incident_url"] = page.url
        d.at_word("recall", lead=0.3)
        d.flash(page.locator("#pane-timeline"))
        expect(page.get_by_text("paused: awaiting approval")).to_be_visible(timeout=120_000)
        L, v2 = read_room(page, a)
        if v2["suspects"] != v["suspects"] or v2["flow"] != v["flow"]:
            raise fail(f"the take's run differs from the validation run: {v2} vs {v}")

        # ---------------- g2: no path, no claim (re-run read-only, 0 rows)
        d.begin("g2")
        d.show(L.gate)
        d.flash(L.gate.get_by_role("heading", name="Rejected suspects"))
        d.at_word("recommendation deploy", lead=0.3)
        d.click(L.rej)
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Cypher", exact=True)).to_be_visible()
        d.at_word("zero rows", lead=1.3)
        d.click(dlg.get_by_role("button", name="Re-run (read-only)"))
        res = dlg.get_by_role("region", name="Re-run result")
        rows = res.get_by_text(re.compile(r"^\d+ rows?$")).first
        err = res.get_by_role("alert").first
        expect(rows.or_(err).first).to_be_visible(timeout=20_000)
        if err.count() and err.is_visible():
            raise fail(f"G2 re-run failed: {err.inner_text()}")
        n_rows = rows.inner_text().strip()
        if not n_rows.startswith("0 "):
            raise fail(f"G2 re-run for {a.distractor_path} returned {n_rows}; the voice says zero rows")
        zero = res.get_by_text(re.compile(r"^0 rows\. For a G2 path query"))
        d.show(zero, "center")
        d.flash(zero)
        d.end(0.9)
        d.flash(zero)
        d.end(0.3)
        page.keyboard.press("Escape")

        # ---------------- g5: a path, but not enough flow
        d.begin("g5")
        d.show(L.g5, "center")
        d.flash(L.g5)
        d.at_word("max flow", lead=0.2)
        d.hover(L.g5)
        d.flash(L.g5)
        d.at_word("rejects it", lead=0.4)
        d.click(L.g5)
        expect(page.get_by_role("dialog").get_by_text("Cypher", exact=True)).to_be_visible()
        d.end(0.3)
        page.keyboard.press("Escape")

        # ---------------- proof: the cause passes; the proof path; why we believe it
        d.begin("proof")
        d.show(L.cause, "center")
        d.flash(L.cause)
        d.at_word("proof path", lead=0.4)
        d.show(L.graph)
        mode = L.graph.get_by_role("group", name="Graph view mode").get_by_role("button", name=re.compile(r"^Path"))
        if mode.get_attribute("aria-pressed") != "true":
            d.click(mode)
        replay = L.graph.get_by_role("button", name="Replay path")
        if replay.count():
            d.click(replay)
        d.at_word("every piece of evidence", lead=0.5)
        d.show(L.root)
        d.click(L.why)
        prov = page.get_by_role("dialog", name="Why do you believe this?")
        counts = prov.get_by_text(re.compile(r"^\d+ evidence · \d+ calls · \d+ agents$"))
        perr = prov.get_by_role("alert")
        expect(counts.or_(perr).first).to_be_visible(timeout=20_000)
        if perr.count():
            raise fail(f"provenance unavailable: {perr.first.inner_text()}")
        facts["provenance"] = counts.inner_text().strip()
        d.end(0.3)
        prov.get_by_role("button", name="Close: why do you believe this").click()

        # ---------------- contain: the min-cut (what-if on a copy), then who fixes it
        d.begin("contain")
        d.show(L.contain)
        d.flash(L.cut)
        d.at_word("who should fix", lead=0.4)
        d.show(L.who)
        d.flash(L.top)

        # ---------------- act: choose -> exact action + plan hash -> approve -> APPLIED -> the PR on github.com
        d.begin("act")
        if key is None:
            d.chip("badge", "Dry run: simulated GitHub")
        d.show(L.plan)
        d.click(L.choose)
        exact = L.plan.get_by_role("region", name="Exact action")
        expect(exact).to_be_visible(timeout=20_000)
        d.show(exact)
        bound = L.plan.get_by_text(re.compile(r"Approval is bound to plan hash")).first
        mh = re.search(r"plan hash\s+([0-9a-f]{6,})", bound.inner_text())
        if not mh:
            raise fail(f"plan hash not shown: {bound.inner_text()!r}")
        facts["plan_hash"] = mh.group(1)
        d.at_word("plan hash", lead=0.4)
        d.show(bound, "center")
        d.flash(bound)
        if key is not None:
            L.plan.get_by_text("Approver key (only when the server acts on real GitHub)").click()
            field = L.plan.get_by_label(re.compile(r"^X-Faultline-Approver-Key"))
            try:
                expect(field).to_be_visible()
                if field.get_attribute("type") != "password":
                    field.evaluate(MASK_JS)
                    facts["key_field_masked"] = True
                    print("  note: the approver key field is not type=password; masked with CSS", file=sys.stderr)
                field.press_sequentially(key, delay=20)
            except Exception as e:  # noqa: BLE001 - never let an error message carry the key
                raise fail(f"could not enter the approver key ({type(e).__name__}; value not shown)") from None
        d.at_word("opens a real pull request", lead=0.8)
        d.click(L.plan.get_by_role("button", name="Approve this exact action"))
        d.show(L.plan, "start")   # keep the plan card in view while GitHub merges (the room re-flows around it)
        big = L.plan.locator("[data-verdict]").first
        expect(big).to_be_visible(timeout=240_000 if key else 60_000)
        d.show(big, "center")
        status = L.plan.get_by_role("status").filter(has_text=re.compile(r"write-back verified \d+\/\d+"))
        expect(status).to_be_visible(timeout=240_000 if key else 60_000)
        verdict = big.get_attribute("data-verdict")
        wb = re.search(r"verified (\d+/\d+)", status.inner_text())
        if verdict != "APPLIED" or not wb:
            raise fail(f"the action ended {verdict} ({status.inner_text()!r}); the voice says applied")
        if not re.search(r"^\s*resolved\b", status.inner_text(), re.I | re.M):
            raise fail(f"the incident did not end RESOLVED: {status.inner_text()!r}")
        chan = L.plan.get_by_role("list", name="Verification channels").inner_text()
        if not re.search(r"GitHub main HEAD\s+ok|Telemetry\s+ok", chan):
            raise fail(f"APPLIED without a second channel on the page: {chan!r}")
        facts.update(verdict=verdict, writeback=wb.group(1))
        d.at_word("Applied", lead=0.2)
        d.show(big, "center")
        d.flash(big)
        d.at_word("writes the decision back", lead=0.2)
        d.show(status, "center")
        d.flash(status)
        link = L.plan.get_by_role("link", name=re.compile(r"github\.com\/\S+\/pull\/\d+"))
        if key is not None and not link.count():
            raise fail("--real-github, but the UI shows a simulated PR")
        d.end(0.1)
        if link.count():
            pr = pr_merged((link.first.get_attribute("href") or "").strip(), wait_s=20)
        else:
            if not L.plan.get_by_text("(simulated)", exact=True).count():
                raise fail("no PR reference on the page after APPLIED")
            pr = a.real_pr_info
            d.chip("badge", f"Dry run: showing PR #{pr['number']}, merged by an earlier real take")
        facts["pr"] = pr["url"]
        # off screen, while the PR shows: (--real-repeat) the flag back on at main, then incident B opens (its page
        # waits for an ack in oc_page: this incident is RESOLVED and its pages are settled by then)
        t.inc_a = incident_of(facts["incident_url"])
        if any(want(s) for s in (*ONCALL, "learn")):
            after_act(t)
        if not d.fast:
            d.go(pr["url"])
            d.chip("url", page.url, "url")
            d.wait(int(GITHUB_SHOT * 1000))
        d.chip("url", None)
        d.chip("badge", None)

        # ---------------- oc_*: on call. The page, at a phone's size; the ack; a standing approval and the same fault
        # fixed with nobody woken (beat_* above: each checks what the voice claims)
        for sid, beat in (("oc_page", beat_oc_page), ("oc_ack", beat_oc_ack), ("oc_contract", beat_oc_contract)):
            if want(sid):
                beat(t)

        # ---------------- preflight: the same graph blocks the risky PR (earlier cuts; only with its segment)
        if want("preflight"):
            beat_preflight(d, page, ui)
        # ---------------- brain: who decided, and are they still here (earlier cuts; only with its segment)
        if want("brain"):
            facts["brain"] = beat_brain(d, page, ui, a.brain_question)

        # ---------------- learn: what Faultline learned from the people using it; engine: FalkorDB observing itself
        if want("learn"):
            beat_learn(t)
        if want("engine"):
            beat_engine(t)

        # ---------------- numbers, cost: the proof charts (PROOF_CHARTS), then close: live now, any agent over MCP
        def chart(name: str) -> None:
            if page.url.split("#")[0].endswith("/media/proof.html"):
                page.evaluate("(c) => { location.hash = c; }", name)
            else:
                d.go(f"{ui}/media/proof.html#{name}")
            expect(page.locator(f"body[data-state='ready'][data-chart='{name}']")).to_be_attached(timeout=10_000)

        def charts(sid: str, until: float | None = None) -> None:
            """The segment's charts in order: evenly over its first `until` seconds, or each at its "@word" cue."""
            names = PROOF_CHARTS.get(sid) or []
            span = S[sid].length if until is None else until
            for i, item in enumerate(names):
                name, _, cue = item.partition("@")
                if i:
                    d.at_word(cue, lead=0.3) if cue else d.at(span * i / len(names))
                chart(name)

        for sid in ("numbers", "cost"):
            if want(sid):
                d.begin(sid)
                charts(sid)

        if want("close"):
            d.begin("close")
            # the live site renders too slowly over the internet for a 4 s line (a fresh load shows a dark page); the
            # live benchmark chart is the stronger evidence for "5 out of 5 real runs, verified", with the URL it measured
            charts("close", until=d.word("Any agent"))
            d.chip("url", a.live_url, "url")
            facts["live"] = a.live_url
            d.at_word("Any agent", lead=0.3)
            d.chip("url", None)
            d.go(f"{ui}/media/open.html")
            page.evaluate("(t) => { document.getElementById('issue-meta').textContent = t; }",
                          f"{issue['title']} · {issue['state'].lower()} · {issue['url']}")
            facts["issue"] = {k: issue[k] for k in ("url", "state", "title")}
            d.at_word("built on FalkorDB", lead=0.3)
            d.go(f"{ui}/media/end.html")
        d.end()   # the last beat's line (a partial take ends with --to-segment's)
        d.wait(int(TAIL * 1000))
        d.mark("end")

        video = page.video.path() if page.video else None
        d.marks["closed"] = d.now()
        ctx.close()
        browser.close()
    if not video:
        raise fail("no video recorded")
    # Pre-roll to trim. Playwright's first frame arrives seconds after the page is created, so the start is not
    # page creation: find the sync marker in the video (fallback: the end, which lags the last frame a little).
    d.offset = 0.0 if partial else find_offset(Path(video), d.marks)
    return Path(video), d, facts


def find_offset(webm: Path, marks: dict[str, float]) -> float:
    est = webm_duration(webm) - marks["closed"]
    if est < 0:
        raise fail(f"the video is shorter than the take ({est:.2f} s); frames were lost")
    ff = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    # search from the start: the end estimate can be seconds off (frames flushed after close, GPU start-up)
    lo, span = 0.0, max(8.0, est + marks["sync"] + 6)
    r = subprocess.run([ff, "-v", "error", "-ss", f"{lo:.3f}", "-t", f"{span:.3f}", "-i", str(webm), "-vf",
                        "crop=24:24:4:4,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
                       capture_output=True, text=True)
    t = None
    for blk in re.finditer(r"pts_time:([\d.]+)\s*\n\S*YAVG=([\d.]+)", r.stdout):
        if float(blk.group(2)) > 200:
            t = lo + float(blk.group(1))
            break
    if t is None:
        print(f"  warning: sync marker not found; trimming on the video's end ({est:.3f} s)", file=sys.stderr)
        return est
    off = t - marks["sync"]
    print(f"  sync marker at {t:.3f} s in the raw video: trim {off:.3f} s (end alignment said {est:.3f})", file=sys.stderr)
    return off


def webm_duration(path: Path) -> float:
    fp = shutil.which("ffprobe") or "/usr/bin/ffprobe"
    r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ------------------------------------------------------------------ encode

def encode(webm: Path, d: Director, segs: list[Seg], ndir: Path, srt: Path, out: Path, total: float) -> None:
    """Video (trimmed, 1080p, captions burned from the .srt) + each segment's audio at its beat's real start."""
    ff = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    style = ("FontName=DejaVu Sans,FontSize=10,PrimaryColour=&H00FAFAFA,OutlineColour=&H66000000,BackColour=&H66000000,"
             "BorderStyle=3,Outline=1.4,Shadow=0,MarginV=14,MarginL=60,MarginR=60,Alignment=2,WrapStyle=0")
    sub = str(srt).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    inputs = ["-ss", f"{d.offset:.3f}", "-i", str(webm)]
    fc = [f"[0:v]scale={VIDEO['width']}:{VIDEO['height']}:flags=lanczos,subtitles=filename='{sub}':force_style='{style}'[v]"]
    mix, ains, afc = [], [], []
    for i, s in enumerate(segs, start=1):
        ains += ["-i", str(ndir / f"{s.id}.wav")]
        ms = int(round(d.actual[s.id] * 1000))
        afc.append(f"[{i}:a]aresample=48000,adelay=delays={ms}:all=1[a{i}]")
        mix.append(f"[a{i}]")
    track = (f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:dropout_transition=0,apad=whole_dur={total:.3f}")
    # two-pass loudnorm: measure the placed narration, then a linear correction to I=-16 LUFS
    shift = [re.sub(r"^\[(\d+):a\]", lambda m: f"[{int(m.group(1)) - 1}:a]", x) for x in afc]
    r = subprocess.run([ff, "-hide_banner", "-nostats", *ains, "-filter_complex",
                        ";".join(shift) + f";{track},loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json[a]",
                        "-map", "[a]", "-f", "null", "-"], capture_output=True, text=True, check=True)
    ln = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    norm = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={ln['input_i']}:measured_TP={ln['input_tp']}:"
            f"measured_LRA={ln['input_lra']}:measured_thresh={ln['input_thresh']}:offset={ln['target_offset']}:linear=true")
    inputs += ains
    fc += afc
    # the music bed: composed here to the take's exact length (compose_music.py, ours, no licence), ducked under the voice
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import compose_music  # noqa: E402

    music = out.with_suffix(".music.wav")
    compose_music.write_wav(str(music), compose_music.compose(total))
    m = len(segs) + 1
    inputs += ["-i", str(music)]
    fc.append(f"{track},{norm},aresample=48000,asplit=2[nar][sc]")
    fc.append(f"[{m}:a]aresample=48000,volume={MUSIC_GAIN}[mus]")
    fc.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=8:attack=40:release=450[md]")
    fc.append("[nar][md]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89[a]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
                    "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)],
                   check=True)
    music.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ui", default="http://localhost:3000", help="production UI")
    ap.add_argument("--api", default="http://localhost:8400", help="the API the UI talks to (checked before recording)")
    ap.add_argument("--narration", default=str(ROOT / "tmp" / "narration"), help="timing.json + narration.wav + <id>.wav")
    ap.add_argument("--real-github", action="store_true",
                    help="act on real GitHub (API started with FAULTLINE_GITHUB=real; key file in "
                         "$FAULTLINE_APPROVER_KEY_FILE; the flag must be on at main)")
    ap.add_argument("--chromium", default=None, help="a full Chrome/Chromium (WebGL via SwiftShader for the cube)")
    ap.add_argument("--gpu", action="store_true", help="render WebGL on the NVIDIA GPU (smooth 3D); fails if it cannot")
    ap.add_argument("--work", default=str(ROOT / "tmp" / "demo-video"))
    ap.add_argument("--out", default=None, help="the mp4 (default: docs/media/demo.mp4 for a real take, "
                                                "tmp/demo-video/narrated_sim.mp4 for a simulated one)")
    ap.add_argument("--gif", action="store_true", help="also regenerate docs/media/hero.gif (real take only)")
    ap.add_argument("--no-encode", action="store_true", help="dry run: keep the raw video and captions in --work only")
    ap.add_argument("--reencode", default=None, metavar="META",
                    help="encode an earlier take again from its meta.json (no browser, no checks of the live system)")
    ap.add_argument("--real-repeat", action="store_true",
                    help="real take: after the take's fix, turn the flag back on at main of the demo infra repo (one "
                         "commit to flags.json: the same fault again) so incident C's contract merges a real PR too")
    ap.add_argument("--from-segment", default=None, metavar="SID",
                    help="simulated take only: keep the footage from this segment on (the beats before it run fast, "
                         "untimed, so the state is real); implies --no-encode")
    ap.add_argument("--to-segment", default=None, metavar="SID", help="with --from-segment: stop after this segment")
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k.replace('_', '-')}", default=v)
    a = ap.parse_args()
    for k in ("contract_uses", "contract_days"):
        if not str(getattr(a, k)).isdigit():
            raise fail(f"--{k.replace('_', '-')} must be a whole number")
    if a.to_segment and not a.from_segment:
        raise fail("--to-segment needs --from-segment")
    if a.from_segment:
        if a.real_github:
            raise fail("a partial take (--from-segment) is for trying beats: simulated GitHub only")
        for sid in filter(None, (a.from_segment, a.to_segment)):
            if sid not in SEGMENT_IDS:
                raise fail(f"unknown segment {sid!r}; the segments are {SEGMENT_IDS}")
        if SEGMENT_IDS.index(a.from_segment) < SEGMENT_IDS.index("run"):
            raise fail("--from-segment must be 'run' or later (the opening has no state to fast-forward)")
        if a.to_segment and SEGMENT_IDS.index(a.to_segment) < SEGMENT_IDS.index(a.from_segment):
            raise fail("--to-segment comes before --from-segment")
        if a.to_segment and SEGMENT_IDS.index(a.to_segment) < SEGMENT_IDS.index("act"):
            raise fail("--to-segment must be 'act' or later (run, g2, g5, proof, contain and act share one incident)")
        a.no_encode = True
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    docs_out = ROOT / "docs" / "media" / "demo.mp4"
    out = Path(a.out) if a.out else docs_out if a.real_github else work / "narrated_sim.mp4"
    if not a.real_github and out.resolve() == docs_out.resolve():
        raise fail("a simulated take never replaces docs/media/demo.mp4; pass another --out")

    if a.reencode:
        return reencode(Path(a.reencode), out, a.gif and a.real_github)

    # everything the take depends on is checked before the browser starts
    segs, _, ndir = load_narration(Path(a.narration))
    S = {s.id: s for s in segs}
    check_contract_scope(S, int(a.contract_uses), int(a.contract_days))
    if a.real_github and "oc_contract" in S and not a.real_repeat:
        raise fail("a real take's oc_contract beat runs the same fault again, but the take's fix leaves the flag off at "
                   f"GitHub main, so nothing could be fixed under the contract: pass --real-repeat (the recorder then "
                   f"turns {a.flag} back on at main of {a.infra_repo} with one commit, right after the fix)")
    check_charts()
    llm = llm_card()
    check_open_card(a.live_url)
    check_api(a.api, a.tenant, a.real_github)
    oc = check_oncall_api(a.api, a.tenant, S)
    check_media(a.ui)
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
        a.real_pr_info = pr_merged(a.real_pr)
    # scripted runs on a public API are trusted only with the approver key (read from the same file, never printed)
    api_key = key if key is not None else (
        read_key("a public API (the trusted runs B and C)") if oc["public"] and (any(s in S for s in ONCALL) or "learn" in S)
        else None)

    webm, d, facts = record(a, work, segs, llm, issue, key, oc, api_key)
    key = api_key = None
    kept = [s for s in segs if s.id in d.actual]   # every segment, or a partial take's
    last = kept[-1]
    total = d.actual[last.id] + last.length + TAIL
    caps = caption_track(segs, d.actual)
    srt_text = "".join(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n\n" for i, (s, e, t) in enumerate(caps, 1))
    srt = work / "captions.srt"
    srt.write_text(srt_text)
    pushes = {s.id: round(d.actual[s.id] - s.start, 2) for s in kept if d.actual[s.id] - s.start > 0.3}
    meta = {"webm": str(webm), "offset_s": round(d.offset, 3), "length_s": round(total, 3), "captions": len(caps),
            "segments": {s.id: round(d.actual[s.id], 3) for s in kept}, "marks": {k: round(v, 3) for k, v in d.marks.items()},
            "narration": str(ndir), "pushed_s": pushes, "facts": facts}
    if a.from_segment:
        meta["partial"] = [a.from_segment, last.id]
    (work / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps({k: meta[k] for k in ("webm", "offset_s", "length_s", "captions", "pushed_s")}, indent=2))
    if a.no_encode:
        return 0

    encode(webm, d, segs, ndir, srt, out, total)
    print(f"wrote {out} ({total:.1f} s)")
    if out.resolve() == docs_out.resolve():
        (ROOT / "docs" / "video_captions.srt").write_text(srt_text)
    if a.gif and a.real_github:
        hero_gif(out, d.marks)
    return 0


def hero_gif(mp4: Path, marks: dict[str, float]) -> None:
    """6 s each of the G2 rejection, the G5 rejection and the proof path, cut from the encoded take."""
    ff = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    segs_g = [(marks["g2"] + 1.0, 6.0), (marks["g5"], 6.0), (marks["proof"] + 1.5, 6.0)]
    parts = "".join(f"[0:v]trim=start={s:.2f}:duration={n},setpts=PTS-STARTPTS[v{i}];" for i, (s, n) in enumerate(segs_g))
    concat = ("".join(f"[v{i}]" for i in range(len(segs_g))) + f"concat=n={len(segs_g)}:v=1:a=0,fps=8,scale=960:-1:"
              "flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(mp4), "-filter_complex", parts + concat,
                    str(ROOT / "docs" / "media" / "hero.gif")], check=True)


def reencode(meta_path: Path, out: Path, gif: bool) -> int:
    """Encode an earlier take again (captions, audio placement and trim from its meta.json)."""
    m = json.loads(meta_path.read_text())
    if m.get("partial"):
        raise fail(f"{meta_path} is a partial take ({m['partial'][0]}..{m['partial'][1]}): it is never encoded")
    webm, ndir = Path(m["webm"]), Path(m.get("narration") or ROOT / "tmp" / "narration")
    segs, _, _ = load_narration(ndir)
    d = SimpleNamespace(actual={k: float(v) for k, v in m["segments"].items()}, offset=float(m["offset_s"]))
    if "sync" in m.get("marks", {}) and "closed" in m["marks"]:   # find the sync marker again (the search improves)
        d.offset = find_offset(webm, m["marks"])
    elif "closed" not in m.get("marks", {}):  # takes recorded before end alignment: align on the end now
        d.offset = webm_duration(webm) - float(m["length_s"])
        print(f"re-aligned the trim on the video's end: offset {d.offset:.3f} s (was {m['offset_s']})")
    last = segs[-1]
    total = d.actual[last.id] + last.length + TAIL
    caps = caption_track(segs, d.actual)
    srt = meta_path.parent / "captions.srt"
    srt.write_text("".join(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n\n" for i, (s, e, t) in enumerate(caps, 1)))
    encode(webm, d, segs, ndir, srt, out, total)  # type: ignore[arg-type]
    print(f"wrote {out} ({total:.1f} s)")
    if gif and "marks" in m:
        hero_gif(out, m["marks"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
