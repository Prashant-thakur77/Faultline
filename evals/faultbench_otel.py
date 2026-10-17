"""FaultBench-OTel: fault injection into the real OpenTelemetry Demo, with real telemetry (PREREGISTRATION addendum
2026-10-16 23:00 IST).

Three steps, each resumable and each writing raw JSON:
  record       drive the running demo through the pre-registered schedule (seed 20261171): 20 slots, each a no-fault
               control window then a fault window; flip the demo's own flagd flags (verified through OFREP), keep the
               raw span-metrics counter samples of every window (evals/results/faultbench_otel_raw/<window>.json) and
               the injection log (data/scenarios/faultbench_otel.truth.json, read only by the grader below). ~15 h.
  run          for every recorded window: per-minute server error rates from the raw samples, the pre-registered page
               rule (the monitoring), then the PRODUCT path on a fresh GRAPH.COPY of golden_acme (changes, alerts, the
               measured windows ingested by faultline.ingest.observed with an Evidence node; INTAKE; run_incident with
               the deterministic investigator for every incident opened), plus T, T+ and naive recency on the same
               windows; graded against the truth file → evals/results/faultbench_otel.json.
  llm-dry-run  render the A0 v2 evidence (llm_arms.evidence_text) of every scored window and estimate the cost; no
               API call (a paid run needs the owner's approval).

    scripts/otel_demo.sh up
    PYTHONPATH=backend scripts/memguard.sh 600 uv run python evals/faultbench_otel.py record --reason "…"
    PYTHONPATH=backend scripts/memguard.sh 3000 uv run python evals/faultbench_otel.py run --reason "…"
    PYTHONPATH=backend uv run python evals/faultbench_otel.py llm-dry-run
    scripts/otel_demo.sh down
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if str(ROOT / "evals") not in sys.path:
    sys.path.insert(0, str(ROOT / "evals"))

import gate_bench  # noqa: E402

DEMO_TAG = "3.1.0"
DEMO = ROOT / "tmp" / "otel-demo" / "src"
FLAG_FILE = DEMO / "src" / "flagd" / "demo.flagd.json"
PROM = os.environ.get("FAULTBENCH_PROM", "http://127.0.0.1:19090")
RAW = ROOT / "evals" / "results" / "faultbench_otel_raw"
TRUTH = ROOT / "data" / "scenarios" / "faultbench_otel.truth.json"
OUT = ROOT / "evals" / "results" / "faultbench_otel.json"
DRY = ROOT / "evals" / "results" / "faultbench_otel_llm_dryrun.json"

SEED = 20261171
REPS = 4
FAULTS = {   # flag → (the service it gates in data/topology/otel-demo.yaml, the variant switched on)
    "paymentFailure": ("payment", "50%"),
    "paymentUnreachable": ("checkout", "on"),
    "cartFailure": ("cart", "100%"),
    "productCatalogFailure": ("product-catalog", "on"),
    "adFailure": ("ad", "on"),
}
HARMLESS = "emitRawPii"
TARGET_PRODUCT = "OLJCESPC7Z"   # productCatalogFailure's built-in targeting rule matches this product id
TELEMETRY_SERVICES = ["ad", "cart", "checkout", "currency", "email", "flagd", "frontend", "frontend-proxy",
                      "image-provider", "payment", "product-catalog", "quote", "recommendation", "shipping"]
CONTAINERS = TELEMETRY_SERVICES + ["load-generator", "otel-collector", "prometheus", "valkey-cart", "astronomy-db"]
QUIET_S = 30 * 60
FAULT_ON_S = 8 * 60
RECOVERY_S = 60
FETCH_LAG_S = 5 * 60
METRIC = "traces_span_metrics_calls_total"
SERIES = f'{METRIC}{{span_kind="SPAN_KIND_SERVER"}}'
# the page rule (pre-registered): rate ≥ PAGE_RATE with ≥ PAGE_CALLS calls, rise over its own baseline ≥ PAGE_RISE
PAGE_RATE, PAGE_CALLS, PAGE_RISE = 0.05, 5, 0.01
BASE_FROM_MIN, BASE_TO_MIN = 30, 5
DETECT_MIN, LAG_MIN, CTRL_LEAD_MIN = 6, 1, 5
WINDOW_BEFORE_MIN, WINDOW_AFTER_MIN = 30, 5
MIN = 60_000
INFRA_EVENTS = [   # logged as they happened (pre-registered stopping rule); nothing was re-recorded because of a result
    {"at": "2026-10-17T09:16+05:30", "event": "the recorder process was killed by a session restart after slot 14 was "
     "recorded, before any slot-15 injection; no window was lost or re-recorded"},
    {"at": "2026-10-17T17:07:33+05:30", "event": "every demo container was started anew (outside the bench, during the "
     "same restart; RestartCount 0, new StartedAt); the recorder resumed at 17:08 with slot 15, so slots 15-20 ran on the "
     "restarted stack, each still after a fault-free 30-minute stretch"},
]
ARMS = ("faultline", "faultline_prefix", "t", "tplus", "n")   # faultline_prefix: as registered (PREREGISTRATION amendment)


def log(msg: str) -> None:
    print(f"[faultbench {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ the pre-registered plan (seeded, no I/O)
def plan(seed: int = SEED) -> list[dict]:
    topo = gate_bench.Topo()      # data/topology/otel-demo.yaml: any failure edge (cap > 0), followed server → client
    rnd, ids_rnd = random.Random(seed), random.Random(seed ^ 0x0BAD1D5)

    def opaque(n: int = 8) -> str:
        return "".join(ids_rnd.choice("0123456789abcdef") for _ in range(n))

    order = [f for f in FAULTS for _ in range(REPS)]
    rnd.shuffle(order)
    slots = []
    for k, flag in enumerate(order, 1):
        svc = FAULTS[flag][0]
        d1 = "checkout" if svc != "checkout" else "payment"
        on = sorted(x for x in topo.any[svc] if x in TELEMETRY_SERVICES and x not in (svc, d1))
        off = sorted(x for x in TELEMETRY_SERVICES if x not in topo.any[svc] and x not in (svc, d1))
        c23 = rnd.sample(sorted(x for x in TELEMETRY_SERVICES if x != "checkout"), 2)
        ctl = {"wid": f"otel-c{k:02d}", "kind": "control", "quiet_jitter_s": round(rnd.uniform(0, 60), 1),
               "d1_before_s": round(rnd.uniform(10, 840), 1), "d1": "checkout", "d2": c23[0], "d3": c23[1],
               "u2": rnd.random(), "u3": rnd.random(), "page_on": rnd.randrange(3),
               "ids": {"d1": f"D-{opaque()}", "d2": f"D-{opaque()}", "d3": f"D-{opaque()}"}, "sid": f"C{opaque(6)}",
               "alert": f"al-{opaque()}"}
        flt = {"wid": f"otel-f{k:02d}", "kind": "fault", "flag": flag, "variant": FAULTS[flag][1], "service": svc,
               "flip_after_s": round(330 + rnd.uniform(0, 90), 1), "d1_before_s": round(rnd.uniform(10, 840), 1),
               "d1": d1, "d2": rnd.choice(on), "d3": rnd.choice(off), "u2": rnd.random(), "u3": rnd.random(),
               "ids": {"cause": f"D-{opaque()}", "d1": f"D-{opaque()}", "d2": f"D-{opaque()}", "d3": f"D-{opaque()}"},
               "sid": f"C{opaque(6)}", "on_path": on, "off_path": off}
        slots.append({"slot": k, "control": ctl, "fault": flt, "shuffle": rnd.random()})
    return slots


# ------------------------------------------------------------------ the system under observation (demo, flagd, Prometheus)
def pristine_flags() -> dict:
    out = subprocess.run(["git", "-C", str(DEMO), "show", "HEAD:src/flagd/demo.flagd.json"], check=True,
                         capture_output=True, text=True).stdout
    return json.loads(out)


def render_flags(state: dict) -> dict:
    """The demo's flag file with our flags set: {flag: variant} (productCatalogFailure: 'on'/'off' via its targeting)."""
    d = pristine_flags()
    for flag, variant in state.items():
        f = d["flags"][flag]
        if variant not in f["variants"]:
            raise ValueError(f"{flag}: no variant {variant!r}")
        if flag == "productCatalogFailure":
            f["targeting"]["if"][1] = variant
        else:
            f["defaultVariant"] = variant
    return d


def write_flags(state: dict) -> int:
    body = json.dumps(render_flags(state), indent=2) + "\n"
    with open(FLAG_FILE, "w") as fh:   # in place, one write: flagd watches this path (as flagd-ui writes it)
        fh.write(body)
    return int(time.time() * 1000)


def ofrep(flag: str) -> str:
    ctx = {"product_id": TARGET_PRODUCT} if flag == "productCatalogFailure" else {}
    code = ("import json,urllib.request;r=urllib.request.Request('http://flagd:8016/ofrep/v1/evaluate/flags/" + flag
            + "',data=json.dumps({'context':" + json.dumps(ctx) + "}).encode(),headers={'Content-Type':'application/json'});"
            "print(json.loads(urllib.request.urlopen(r,timeout=5).read())['variant'])")
    r = subprocess.run(["docker", "exec", "load-generator", "python3", "-c", code], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError(f"OFREP {flag}: {r.stderr.strip()[-300:]}")
    return r.stdout.strip()


def set_flag(state: dict, flag: str, variant: str, timeout_s: float = 30.0) -> dict:
    """Flip one flag (the others keep `state`), verify through flagd's OFREP endpoint; returns the flip record."""
    state[flag] = variant
    written = write_flags(state)
    deadline = time.monotonic() + timeout_s
    while True:
        got = ofrep(flag)
        if got == variant:
            return {"flag": flag, "variant": variant, "written_at": written, "verified_at": int(time.time() * 1000)}
        if time.monotonic() > deadline:
            raise RuntimeError(f"{flag}: flagd still serves {got!r} {timeout_s:.0f} s after writing {variant!r}")
        time.sleep(0.5)


def defaults() -> dict:
    d = pristine_flags()["flags"]
    return {f: (d[f]["targeting"]["if"][1] if f == "productCatalogFailure" else d[f]["defaultVariant"])
            for f in [*FAULTS, HARMLESS]}


def prom_raw(start_ms: int, end_ms: int) -> list[dict]:
    """Raw counter samples of every server-span series in (start, end]: one RO read of Prometheus (a range selector)."""
    span_min = math.ceil((end_ms - start_ms) / MIN)
    q = urllib.parse.urlencode({"query": f"{SERIES}[{span_min}m]", "time": f"{end_ms / 1000:.3f}"})
    with urllib.request.urlopen(f"{PROM}/api/v1/query?{q}", timeout=60) as r:
        body = json.loads(r.read())
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus: {body}")
    keep = ("service_name", "span_name", "status_code", "collector_instance_id")
    return [{"labels": {k: s["metric"].get(k) for k in keep},
             "values": [[int(float(t) * 1000), float(v)] for t, v in s["values"]]} for s in body["data"]["result"]]


def health() -> dict:
    r = subprocess.run(["docker", "inspect", "--format", "{{.Name}} {{.RestartCount}} {{.State.OOMKilled}} "
                        "{{.State.Status}} {{.State.StartedAt}}", *CONTAINERS], capture_output=True, text=True)
    out = {}
    for line in r.stdout.splitlines():
        name, restarts, oom, status, started = line.split()
        out[name.lstrip("/")] = {"restarts": int(restarts), "oom": oom == "true", "status": status, "started": started}
    return out


# ------------------------------------------------------------------ record (live, ~15 h)
def _load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def _save(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n")
    os.replace(tmp, p)


def _sleep_until(t_ms: int) -> None:
    while True:
        left = t_ms / 1000 - time.time()
        if left <= 0:
            return
        time.sleep(min(left, 20.0))


def record(reason: str, only: int | None = None) -> None:
    got = subprocess.run(["git", "-C", str(DEMO), "describe", "--tags", "--exact-match"], capture_output=True, text=True)
    if got.stdout.strip() != DEMO_TAG:
        raise SystemExit(f"demo checkout is not at tag {DEMO_TAG}")
    truth = _load(TRUTH, {"bench": "FaultBench-OTel", "seed": SEED, "demo": DEMO_TAG, "windows": {}, "log": []})
    truth["log"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "record start", "reason": reason})
    state = defaults()
    for f in state:   # every fault off, verified, before anything else (a crashed run may have left one on)
        set_flag(state, f, state[f])
    _save(TRUTH, truth)
    t0 = int(time.time() * 1000) + RECOVERY_S * 1000   # anything left on by a crash is off from now: one minute of recovery
    try:
        for s in plan():
            if only is not None and s["slot"] != only:
                continue
            c, f = s["control"], s["fault"]
            if (RAW / f"{c['wid']}.json").exists() and (RAW / f"{f['wid']}.json").exists():
                continue
            ctl_onset = t0 + int((QUIET_S + c["quiet_jitter_s"]) * 1000)
            flip_at = ctl_onset + int(f["flip_after_s"] * 1000)
            events = sorted([(ctl_onset - int(c["d1_before_s"] * 1000), "control_d1"),
                             (flip_at - int(f["d1_before_s"] * 1000), "fault_d1"), (flip_at, "flip"),
                             (flip_at + FAULT_ON_S * 1000, "off")])
            log(f"slot {s['slot']}: control onset {time.strftime('%H:%M:%S', time.localtime(ctl_onset / 1000))}, "
                f"{f['flag']} at {time.strftime('%H:%M:%S', time.localtime(flip_at / 1000))}")
            rec: dict = {"slot": s["slot"], "control_onset": ctl_onset}
            for at, what in events:
                _sleep_until(at)
                if what in ("control_d1", "fault_d1"):
                    rec[what] = set_flag(state, HARMLESS, "off" if state[HARMLESS] == "on" else "on")
                elif what == "flip":
                    rec["flip"] = set_flag(state, f["flag"], f["variant"])
                    truth["windows"][f["wid"]] = {"kind": "fault", "slot": s["slot"], "flag": f["flag"],
                                                  "variant": f["variant"], "service": f["service"],
                                                  "cause": f["ids"]["cause"], "flip": rec["flip"], "complete": False}
                    _save(TRUTH, truth)
                else:
                    rec["off"] = set_flag(state, f["flag"], defaults()[f["flag"]])
                log(f"slot {s['slot']}: {what} done")
            t0 = rec["off"]["verified_at"] + RECOVERY_S * 1000
            _sleep_until(rec["off"]["verified_at"] + FETCH_LAG_S * 1000)
            hl = health()
            cw = {"wid": c["wid"], "kind": "control", "slot": s["slot"], "sid": c["sid"], "onset": ctl_onset,
                  "changes": [{"change": c["ids"]["d1"], "target": c["d1"], "kind": "flag",
                               "at": rec["control_d1"]["verified_at"]},
                              {"change": c["ids"]["d2"], "target": c["d2"], "kind": "deploy", "u": c["u2"]},
                              {"change": c["ids"]["d3"], "target": c["d3"], "kind": "deploy", "u": c["u3"]}],
                  "false_page": {"id": c["alert"], "target": [c["d1"], c["d2"], c["d3"]][c["page_on"]], "at": ctl_onset},
                  "range": [ctl_onset - 40 * MIN, ctl_onset + 10 * MIN], "health": hl}
            cw["samples"] = prom_raw(*cw["range"])
            fw = {"wid": f["wid"], "kind": "fault", "slot": s["slot"], "sid": f["sid"], "flip_window": [flip_at, None],
                  "changes": [{"change": f["ids"]["cause"], "target": f["service"], "kind": "flag",
                               "at": rec["flip"]["verified_at"]},
                              {"change": f["ids"]["d1"], "target": f["d1"], "kind": "flag",
                               "at": rec["fault_d1"]["verified_at"]},
                              {"change": f["ids"]["d2"], "target": f["d2"], "kind": "deploy", "u": f["u2"]},
                              {"change": f["ids"]["d3"], "target": f["d3"], "kind": "deploy", "u": f["u3"]}],
                  "range": [flip_at - 40 * MIN, rec["off"]["verified_at"] + FETCH_LAG_S * 1000 - 30_000], "health": hl}
            fw["flip_window"] = [rec["flip"]["verified_at"], rec["off"]["verified_at"]]
            fw["samples"] = prom_raw(*fw["range"])
            _save(RAW / f"{c['wid']}.json", cw)
            _save(RAW / f"{f['wid']}.json", fw)
            truth["windows"][c["wid"]] = {"kind": "control", "slot": s["slot"], "cause": None,
                                          "d1": rec["control_d1"], "complete": True,
                                          "decoys": {c["ids"]["d1"]: c["d1"], c["ids"]["d2"]: c["d2"], c["ids"]["d3"]: c["d3"]}}
            truth["windows"][f["wid"]].update({"off": rec["off"], "d1": rec["fault_d1"], "complete": True,
                                               "decoys": {f["ids"]["d1"]: f["d1"], f["ids"]["d2"]: f["d2"],
                                                          f["ids"]["d3"]: f["d3"]},
                                               "on_path": {f["ids"]["d1"]: f["d1"] in f["on_path"],
                                                           f["ids"]["d2"]: True, f["ids"]["d3"]: False}})
            _save(TRUTH, truth)
            log(f"slot {s['slot']}: recorded {c['wid']} and {f['wid']} ({len(fw['samples'])} series)")
    finally:
        try:
            for fl, v in defaults().items():
                if state.get(fl) != v:
                    set_flag(state, fl, v)
        finally:
            truth["log"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "record stop"})
            _save(TRUTH, truth)


# ------------------------------------------------------------------ telemetry → per-minute rates, the page rule
def minute_rates(samples: list[dict], range_start: int) -> dict[str, dict[int, list[float]]]:
    """{service: {minute stamp (ms): [calls, errors]}} from raw cumulative counters: consecutive differences (a decrease
    = a counter reset), each stamped with its sample time rounded UP to the minute (when the data became available). A
    series first seen more than 2 minutes after the range start was born inside it (a new status-code series, or a
    collector restart): its first sample counts from zero."""
    out: dict[str, dict[int, list[float]]] = {}
    for s in samples:
        svc, err = s["labels"]["service_name"], s["labels"]["status_code"] == "STATUS_CODE_ERROR"
        vals = sorted(s["values"])
        steps = [(t1, (v1 - v0) if v1 >= v0 else v1) for (_, v0), (t1, v1) in zip(vals, vals[1:])]
        if vals and vals[0][0] > range_start + 2 * MIN:
            steps.insert(0, (vals[0][0], vals[0][1]))
        for t, d in steps:
            m = -(-t // MIN) * MIN
            cell = out.setdefault(svc, {}).setdefault(m, [0.0, 0.0])
            cell[0] += d
            if err:
                cell[1] += d
    return out


def rate(cell: list[float]) -> float | None:
    return cell[1] / cell[0] if cell and cell[0] > 0 else None


def page_minutes(rates: dict, since: int, until: int) -> dict[str, int]:
    """{service: first minute in [since, until] where the pre-registered page rule fires}."""
    out = {}
    for svc, by in rates.items():
        for m in sorted(x for x in by if since <= x <= until):
            r = rate(by[m])
            base = [rate(by[b]) for b in by if m - BASE_FROM_MIN * MIN <= b <= m - BASE_TO_MIN * MIN and rate(by[b]) is not None]
            if r is None or by[m][0] < PAGE_CALLS or not base:
                continue
            if r >= PAGE_RATE and r - statistics.fmean(base) >= PAGE_RISE:
                out[svc] = m
                break
    return out


BROKEN_BASELINE = 0.5   # PREREGISTRATION amendment 2026-10-17 21:00 IST: a window whose baseline shows a broken system


def baseline_broken(w: dict) -> dict[str, float]:
    """{service: mean baseline error rate} for services at or above BROKEN_BASELINE over [ref − 30, ref − 5] min, where
    ref is the control onset or the fault flip: the system under test was already broken before the window began."""
    rates = minute_rates(w["samples"], w["range"][0])
    ref = w["onset"] if w["kind"] == "control" else w["flip_window"][0]
    out = {}
    for svc, by in rates.items():
        v = [rate(c) for m, c in by.items() if ref - BASE_FROM_MIN * MIN <= m <= ref - BASE_TO_MIN * MIN and rate(c) is not None]
        if v and statistics.fmean(v) >= BROKEN_BASELINE:
            out[svc] = round(statistics.fmean(v), 3)
    return out


def build(w: dict, slot_shuffle: float) -> dict:
    """The window as a scenario spec (the scenarios.yaml shape; no truth): onset, changes, alerts, observed windows.
    Returns {"detected": False, ...} for a fault window the page rule never fired in."""
    rates = minute_rates(w["samples"], w["range"][0])
    if w["kind"] == "fault":
        flip = w["flip_window"][0]
        pages = page_minutes(rates, flip, flip + DETECT_MIN * MIN)
        if not pages:
            return {"detected": False, "pages": {}}
        onset = min(pages.values())
        alerts = sorted((m, s) for s, m in pages.items() if m <= onset + LAG_MIN * MIN)
    else:
        onset = w["onset"]
        pages = page_minutes(rates, onset - CTRL_LEAD_MIN * MIN, onset + LAG_MIN * MIN)
        alerts = sorted({(onset, w["false_page"]["target"]), *((m, s) for s, m in pages.items())})
        onset = min(m for m, _ in alerts)
    rnd = random.Random(f"{w['wid']}:{slot_shuffle}")
    inject = []
    for c in w["changes"]:
        at = c["at"] if "at" in c else onset - 30_000 - int(c["u"] * 14.5 * MIN)
        inject.append({"change": c["change"], "target": c["target"], "kind": c["kind"],
                       "at": f"-{max(0, round((onset - at) / 1000))}s", "title": f"{c['target']}: change", "_at": at})
    rnd.shuffle(inject)   # the cause's position carries no signal
    for c in inject:
        if c["_at"] > onset:
            raise RuntimeError(f"{w['wid']}: change {c['change']} after onset")
        c.pop("_at")
    rows = [{"target": svc, "at": m, "value": round(rate(cell), 5), "calls": int(cell[0])}
            for svc, by in sorted(rates.items()) for m, cell in sorted(by.items())
            if svc in TELEMETRY_SERVICES and onset - WINDOW_BEFORE_MIN * MIN <= m <= onset + WINDOW_AFTER_MIN * MIN
            and rate(cell) is not None]
    first = alerts[0][1]
    ids = random.Random(f"{w['wid']}:alerts")
    spec = {"id": w["sid"], "name": f"generated incident {w['sid'].lower()}", "tenant": "acme", "onset": onset,
            "inject": inject,
            "alerts": [{"id": (w["false_page"]["id"] if w["kind"] == "control" and s == w["false_page"]["target"]
                               and m == w["onset"] else f"al-{ids.getrandbits(32):08x}"),
                        "target": s, "metric": "error_rate", "at": f"{round((m - onset) / 1000)}s"} for m, s in alerts],
            "report": gate_bench.BENCH_REPORT.format(target=first), "window_min": 30,
            "observed": {"source": "prometheus span metrics (OpenTelemetry Demo " + DEMO_TAG + ")", "query": SERIES,
                         "rows": rows}}
    return {"detected": True, "spec": spec, "pages": pages, "onset": onset}


# ------------------------------------------------------------------ run + grade
def _prefix_rule(v: float, b: float, band: float) -> bool:
    """metric_window's anomaly rule AS REGISTERED (before the zero-baseline fix of 2026-10-16 23:45 IST, PREREGISTRATION
    amendment): a ratio is required, so a rise from an exactly-zero baseline is never anomalous. Eval process only."""
    from faultline.agent import datatools
    from faultline.agent.weights import weights

    ratio = v / b if b else None
    return bool(ratio) and datatools._outside(ratio, band) and (v - b) >= float(weights()["gate"]["err_abs_min"])


def run_product(spec: dict, prefix: bool = False) -> dict:
    """The product on a fresh clean room; `prefix`: with metric_window's pre-fix anomaly rule (as registered)."""
    import anyio

    from faultline.agent import datatools

    from faultline import scenario
    from faultline.agent.loop import BaselineInvestigator
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy

    t0 = time.perf_counter()
    fixed = datatools.error_rate_anomalous
    p = scenario.prepare(spec["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=spec)
    try:
        if prefix:
            datatools.error_rate_anomalous = _prefix_rule
        results = anyio.run(lambda: scenario.investigate_all(p, BaselineInvestigator()))
    finally:
        datatools.error_rate_anomalous = fixed
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    incs = [{"incident": r.incident_id, "outcome": r.outcome, "cause": r.cause_id if r.outcome == "CONFIRMED" else None,
             # a change the gate accepted WITHOUT confidence (an abstention by outcome, reported apart, as on every bench)
             "accepted_not_confident": r.cause_id if r.outcome == "NOT_CONFIDENT" else None,
             "confident": r.confident, "error": r.error,
             "sweep": {v["change"]: f"{v['status']}: {v['reason']}"[:300] for v in r.sweep}} for r in results]
    return {"incidents": incs, "symptoms": p.symptoms, "groups": len(p.groups), "seconds": round(time.perf_counter() - t0, 2)}


def grade_blames(blamed: list[str], outcomes: list[str], cause: str | None) -> dict:
    blamed = sorted(set(blamed))
    return {"right_cause": cause is not None and blamed == [cause],
            "wrong": any(b != cause for b in blamed),
            "abstained": not blamed and bool(outcomes) and all(o in gate_bench.ABSTAIN_OK for o in outcomes),
            "no_incident": not blamed and bool(outcomes) and all(o == "NO_INCIDENT" for o in outcomes),
            "blame_free": not blamed}


def naive_recency(spec: dict) -> list[str]:
    from faultline.scenario import rel_ms

    ats = {c["change"]: rel_ms(c["at"], spec["onset"]) for c in spec["inject"]}
    best = max(ats.values())
    return sorted(c for c, a in ats.items() if a == best)


def run(reason: str, only: list[str] | None = None) -> dict:
    import baselines
    import harness

    truth = _load(TRUTH, None)
    if truth is None:
        raise SystemExit("no truth file: record first")
    shuffles = {s["fault"]["wid"]: s["shuffle"] for s in plan()} | {s["control"]["wid"]: s["shuffle"] for s in plan()}
    prior = _load(OUT, {})
    rows = {r["wid"]: r for r in prior.get("rows", [])}
    pressure: list[dict] = []
    t0 = time.perf_counter()
    for i, raw in enumerate(sorted(RAW.glob("otel-*.json"))):
        w = json.loads(raw.read_text())
        if only and w["wid"] not in only:
            continue
        tw = truth["windows"].get(w["wid"]) or {}
        if not tw.get("complete"):
            log(f"{w['wid']}: not complete in the injection log; skipped")
            continue
        broken = baseline_broken(w)
        if broken:   # excluded, never scored (the amendment's criterion), and said so in the results file
            rows[w["wid"]] = {"wid": w["wid"], "kind": w["kind"], "slot": w["slot"], "fault": tw.get("flag"),
                              "detected": False, "excluded": f"infrastructure: baseline error rate >= {BROKEN_BASELINE} "
                                                              f"on {broken}", "health": w.get("health")}
            log(f"{w['wid']}: excluded, broken baseline {broken}")
            continue
        b = build(w, shuffles[w["wid"]])
        row = {"wid": w["wid"], "kind": w["kind"], "slot": w["slot"], "fault": tw.get("flag"), "service": tw.get("service"),
               "detected": b["detected"], "pages": {k: v for k, v in b["pages"].items()}, "health": w.get("health")}
        if not b["detected"]:
            rows[w["wid"]] = row
            log(f"{w['wid']} {tw.get('flag')}: not detected by the page rule")
            continue
        spec, cause = b["spec"], tw.get("cause")
        prod = run_product(spec)
        blamed = [x["cause"] for x in prod["incidents"] if x["cause"]]
        pre = run_product(copy.deepcopy(spec), prefix=True)
        pre_blamed = [x["cause"] for x in pre["incidents"] if x["cause"]]
        tt = baselines.both({"spec": copy.deepcopy(spec)})
        nn = naive_recency(spec)
        row.update({"onset": b["onset"], "alerts": [a["target"] for a in spec["alerts"]],
                    "changes": [{k: c[k] for k in ("change", "target", "kind", "at")} for c in spec["inject"]],
                    "windows": len(spec["observed"]["rows"]), "product": prod,
                    "faultline": grade_blames(blamed, [x["outcome"] for x in prod["incidents"]], cause),
                    "blamed": blamed, "cause": cause, "product_prefix": pre, "blamed_prefix": pre_blamed,
                    "faultline_prefix": grade_blames(pre_blamed, [x["outcome"] for x in pre["incidents"]], cause),
                    "accepted_nc": sorted({x["accepted_not_confident"] for x in prod["incidents"]
                                           if x["accepted_not_confident"]}),
                    "t": {**grade_blames(tt["t"]["tied"], [tt["t"]["outcome"]], cause), "tied": tt["t"]["tied"]},
                    "tplus": {**grade_blames(tt["tplus"]["tied"], [tt["tplus"]["outcome"]], cause), "tied": tt["tplus"]["tied"],
                              "outcome": tt["tplus"]["outcome"]},
                    "n": {**grade_blames(nn, ["CONFIRMED"], cause), "tied": nn}})
        for arm in ("t", "tplus", "n"):   # a tie at the top is a blame of each tied change (strict: not right)
            x = row[arm]
            x["right_frac"] = round(1.0 / len(x["tied"]), 4) if cause in x["tied"] else 0.0
        rows[w["wid"]] = row
        log(f"{w['wid']} {tw.get('flag') or 'control'}: {[x['outcome'] for x in prod['incidents']]} "
            f"right={row['faultline']['right_cause']} wrong={row['faultline']['wrong']} (as registered: "
            f"{[x['outcome'] for x in pre['incidents']]}) T+={row['tplus']['tied']}")
        if (i + 1) % 10 == 0:
            harness._relieve_engine(f"faultbench-otel-{i + 1}", pressure)
    rows = {wid: r for wid, r in rows.items() if (RAW / f"{wid}.json").exists()}   # recordings set aside are listed below
    out = {"bench": "FaultBench-OTel", "seed": SEED, "demo": DEMO_TAG, "reason": reason,
           "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": sorted(rows.values(), key=lambda r: r["wid"]),
           "engine_pressure": pressure, "seconds": round(time.perf_counter() - t0, 1),
           "ingestion_fixes": prior.get("ingestion_fixes", []),
           "record_log": truth.get("log", []),
           "infrastructure_events": INFRA_EVENTS,
           "product_fixes": [{"at": "2026-10-16T23:45+05:30", "found_on": "otel-f01 (adFailure), as a pipeline check",
                              "what": "metric_window called a rise from an exactly-zero baseline normal (ratio None), so the "
                                      "negative proof accepted NO_INCIDENT; fixed in datatools.error_rate_anomalous. Both "
                                      "versions are run on every window: faultline (current) and faultline_prefix (as "
                                      "registered)."}]}   # every recorder start/stop, with its reason (interruptions included)
    out["excluded_windows"] = [   # earlier recordings set aside for an infrastructure failure (raw files kept)
        {"file": str(x.relative_to(ROOT)), "wid": (xw := json.loads(x.read_text()))["wid"], "kind": xw["kind"],
         "broken_baseline": baseline_broken(xw)} for x in sorted((RAW / "excluded").glob("otel-*.json"))]
    out["summary"] = summarize(out["rows"])
    _save(OUT, out)
    return out


def summarize(rows: list[dict]) -> dict:
    rows = [r for r in rows if not r.get("excluded")]
    scored = [r for r in rows if r.get("detected")]
    faults = [r for r in scored if r["kind"] == "fault"]
    ctl = [r for r in scored if r["kind"] == "control"]
    out = {"windows": len(rows), "fault_windows": sum(r["kind"] == "fault" for r in rows), "control_windows": len(ctl),
           "detected": len(faults), "scored": len(scored)}
    for arm in ARMS:
        out[arm] = {"right_cause": sum(r[arm]["right_cause"] for r in faults),
                    "wrong": sum(r[arm]["wrong"] for r in scored),
                    "wrong_fault": sum(r[arm]["wrong"] for r in faults),
                    "wrong_control": sum(r[arm]["wrong"] for r in ctl),
                    "abstained": sum(r[arm]["abstained"] for r in scored),
                    "control_blame_free": sum(r[arm]["blame_free"] for r in ctl)}
        if not arm.startswith("faultline"):
            out[arm]["right_frac"] = round(sum(r[arm]["right_frac"] for r in faults), 2)
    out["by_fault"] = {}
    for flag in FAULTS:
        rs = [r for r in rows if r.get("fault") == flag and r["kind"] == "fault"]
        d = [r for r in rs if r.get("detected")]
        out["by_fault"][flag] = {"windows": len(rs), "detected": len(d),
                                 **{f"{arm}.{m}": sum(r[arm][m] for r in d) for arm in ARMS
                                    for m in ("right_cause", "wrong", "abstained")}}
    return out


# ------------------------------------------------------------------ LLM alone: dry run only (no API call)
def llm_dry_run() -> dict:
    import llm_deep

    truth = _load(TRUTH, {"windows": {}})
    shuffles = {s["fault"]["wid"]: s["shuffle"] for s in plan()} | {s["control"]["wid"]: s["shuffle"] for s in plan()}
    worlds = {}
    for raw in sorted(RAW.glob("otel-*.json")):
        w = json.loads(raw.read_text())
        if not (truth["windows"].get(w["wid"]) or {}).get("complete"):
            continue
        b = build(w, shuffles[w["wid"]])
        if not b["detected"]:
            continue
        prompt = llm_deep.prompt_of(llm_deep.render({"spec": b["spec"]}))
        tin, tout = llm_deep.est_tokens(prompt)
        worlds[w["wid"]] = {"chars": len(prompt), "est_in": tin, "est_out": tout}
    tin, tout = sum(x["est_in"] for x in worlds.values()), sum(x["est_out"] for x in worlds.values())
    out = {"n": len(worlds), "est_input_tokens": tin, "est_output_tokens": tout, "est_usd": round(llm_deep.usd(tin, tout), 2),
           "model": llm_deep.MODEL, "price_per_mtok": llm_deep.llm_arms.PRICE_PER_MTOK,
           "chars_per_token": llm_deep.CHARS_PER_TOKEN, "worlds": worlds, "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "note": "estimate only; no API call was made"}
    _save(DRY, out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--reason", required=True)
    r.add_argument("--slot", type=int, help="record one slot only (re-record after an infrastructure failure)")
    u = sub.add_parser("run")
    u.add_argument("--reason", required=True)
    u.add_argument("--only", nargs="*")
    sub.add_parser("llm-dry-run")
    sub.add_parser("plan")
    a = ap.parse_args()
    if a.cmd == "record":
        record(a.reason, a.slot)
    elif a.cmd == "run":
        print(json.dumps(run(a.reason, a.only)["summary"], indent=1))
    elif a.cmd == "llm-dry-run":
        x = llm_dry_run()
        print(json.dumps({k: x[k] for k in ("n", "est_input_tokens", "est_output_tokens", "est_usd", "model")}, indent=1))
    else:
        for s in plan():
            print(s["slot"], s["fault"]["flag"], "D1", s["fault"]["d1"], "on", s["fault"]["d2"], "off", s["fault"]["d3"],
                  "| control", s["control"]["d2"], s["control"]["d3"], "page", s["control"]["page_on"])


if __name__ == "__main__":
    main()
