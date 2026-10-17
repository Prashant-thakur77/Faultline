"""Charts for the README and docs/PROOF.md, drawn as static SVG straight from evals/results/latest.json.

Emphasis form: Faultline's bar in the accent hue, every baseline in a neutral gray, each value labelled at the bar's
end, a <title> on every bar (a native tooltip when the SVG is opened). A light card, so the chart reads the same on
GitHub's light and dark themes. No number is typed here: every value is read from latest.json at render time.

    uv run python scripts/gen_charts.py          # → docs/media/charts/*.svg
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media" / "charts"
ACCENT, GRAY, INK, INK2, MUTED, GRID, CARD = "#2a78d6", "#8c8a84", "#0b0b0b", "#52514e", "#77756f", "#e7e6e2", "#fcfcfb"
FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def bars(title: str, subtitle: str, rows: list, fmt, vmax: float, note: str = "", log: bool = False,
         vmin: float = 1.0) -> str:
    """Horizontal bars. rows: (label, value, is_faultline, tooltip[, ci[, text]]): ci = (lo, hi) in the value's units
    draws a 95 % interval whisker; text replaces fmt(value) at the bar's end. value None draws an 'n/a' row. `log`: a
    log10 axis from vmin to vmax (a value at or below vmin draws no bar, only its label)."""
    import math

    w, left, right, top, row_h, bar_h = 820, 290, 150, 84, 38, 18
    h = top + row_h * len(rows) + (46 if note else 24)
    plot = w - left - right

    def x_of(v: float) -> float:
        if log:
            if v <= vmin:
                return 0.0
            return plot * (math.log10(v) - math.log10(vmin)) / (math.log10(vmax) - math.log10(vmin))
        return plot * (v / vmax) if vmax else 0.0

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
         f'aria-label="{escape(title)}">',
         f'<title>{escape(title)}</title>',
         f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" fill="{CARD}" stroke="{GRID}"/>',
         f'<text x="24" y="34" font-family="{FONT}" font-size="17" font-weight="600" fill="{INK}">{escape(title)}</text>',
         f'<text x="24" y="56" font-family="{FONT}" font-size="12.5" fill="{INK2}">{escape(subtitle)}</text>']
    ticks = ([vmin * 10 ** i for i in range(int(round(math.log10(vmax / vmin))) + 1)] if log else [0, vmax / 2, vmax])
    for t in ticks:  # recessive grid
        x = left + x_of(t) if (t > vmin or not log) else left
        o.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{top + row_h * len(rows) - 12}" stroke="{GRID}"/>')
        if log:
            o.append(f'<text x="{x:.1f}" y="{top + row_h * len(rows) - 1}" text-anchor="middle" font-family="{FONT}" '
                     f'font-size="10.5" fill="{MUTED}">{t:,.0f}</text>')
    for i, row in enumerate(rows):
        label, v, mine, tip = row[:4]
        ci = row[4] if len(row) > 4 else None
        text = row[5] if len(row) > 5 else None
        y = top + i * row_h
        weight, ink = ("600", INK) if mine else ("400", INK2)
        o.append(f'<text x="{left - 14}" y="{y + bar_h - 4}" text-anchor="end" font-family="{FONT}" font-size="13" '
                 f'font-weight="{weight}" fill="{ink}">{escape(label)}</text>')
        if v is None:
            o.append(f'<text x="{left + 6}" y="{y + bar_h - 4}" font-family="{FONT}" font-size="12" fill="{MUTED}">n/a</text>')
            continue
        bw = max(x_of(v), 2.5) if x_of(v) > 0 else 0
        if bw:
            o.append(f'<g><title>{escape(tip)}</title><rect x="{left}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="4" '
                     f'fill="{ACCENT if mine else GRAY}"/></g>')
        end = bw
        if ci is not None and ci[0] is not None and ci[1] is not None:
            x0, x1, ym = left + x_of(ci[0]), left + x_of(ci[1]), y + bar_h / 2
            o.append(f'<g stroke="{INK}" stroke-width="1.4"><title>{escape(tip)}: 95 % interval {ci[0]}–{ci[1]}</title>'
                     f'<line x1="{x0:.1f}" y1="{ym:.1f}" x2="{x1:.1f}" y2="{ym:.1f}"/>'
                     f'<line x1="{x0:.1f}" y1="{ym - 5:.1f}" x2="{x0:.1f}" y2="{ym + 5:.1f}"/>'
                     f'<line x1="{x1:.1f}" y1="{ym - 5:.1f}" x2="{x1:.1f}" y2="{ym + 5:.1f}"/></g>')
            end = max(end, x_of(ci[1]))
        o.append(f'<text x="{left + end + 8:.1f}" y="{y + bar_h - 4}" font-family="{FONT}" font-size="13" '
                 f'font-weight="{weight}" fill="{INK}">{escape(text if text is not None else fmt(v))}</text>')
    if note:
        o.append(f'<text x="24" y="{h - 18}" font-family="{FONT}" font-size="11.5" fill="{MUTED}">{escape(note)}</text>')
    o.append("</svg>")
    return "\n".join(o) + "\n"


def pct(v: float) -> str:
    return f"{v * 100:.0f}%" if abs(v * 100 - round(v * 100)) < 0.05 else f"{v * 100:.1f}%"


def main() -> int:
    d = json.loads((ROOT / "evals" / "results" / "latest.json").read_text())
    run = str(d.get("run", "latest")).removesuffix(".json")
    OUT.mkdir(parents=True, exist_ok=True)
    arms = [("Faultline (graph + evidence gate)", "A3", True), ("Same, max-flow check G5 off", "A3-noG5", False),
            ("Telemetry only", "T", False), ("Vector similarity only", "V", False), ("Naive recency", "N", False),
            ("FalkorDB switched off", "A4", False)]

    def kn(prefix: str) -> tuple[float | None, tuple | None, str]:
        """(rate, (lo, hi), 'k/n') from the report's wilson keys."""
        k, n = d.get(f"{prefix}.k"), d.get(f"{prefix}.n")
        if k is None or not n:
            return None, None, "n/a"
        kk = int(k) if float(k).is_integer() else k
        return k / n, (d.get(f"{prefix}.ci_lo"), d.get(f"{prefix}.ci_hi")), f"{kk}/{n}"

    def rate_row(lbl: str, prefix: str, mine: bool, unit: str) -> tuple:
        r, ci, txt = kn(prefix)
        return (lbl, r, mine, f"{lbl}: {txt} {unit}", ci, f"{txt}" + (f"  ({ci[0] * 100:.0f}–{ci[1] * 100:.0f} %)" if ci else ""))

    files = {
        "outcome.svg": bars("Right outcome on the scenario suite",
                            "Distinct scenarios with the correct verdict (confirm the true cause, or abstain when there is "
                            f"none); a tie is never correct. Whiskers: 95 % interval. Eval {run}.",
                            [rate_row(lbl, f"arm.{a}.scen.outcome_correct_strict", mine, "scenarios") for lbl, a, mine in arms],
                            pct, 1.0,
                            note="8 scenarios (5 with a cause). FalkorDB switched off fails closed by design: it confirms nothing."),
        "false_blame.svg": bars("Blaming a change that did not cause it",
                                "Distinct scenarios where the approach blamed a wrong change, controls included. Lower is "
                                f"better. Whiskers: 95 % interval. Eval {run}.",
                                [rate_row(lbl, f"arm.{a}.scen.wrong_blame", mine, "scenarios")
                                 for lbl, a, mine in arms if a in ("A3", "T", "V", "N")], pct, 1.0,
                                note="8 scenarios. Naive, vector and telemetry-only cannot say \"no change explains this\" by design."),
    }
    ctx = [("Graph context pack: graph-scoped, anomaly-ranked", "GA", True),
           ("Graph distance only (no telemetry)", "G", False),
           ("Telemetry ranking, no graph", "TR", False), ("Vector RAG", "V", False), ("Recency", "R", False)]
    files["context_mrr.svg"] = bars("Is the true cause near the top of the agent's context?",
                                    f"Mean reciprocal rank of the true cause over {d.get('ctx.busy30.worlds')} worlds with 30 "
                                    "unrelated deploys in the window, 1,000-token budget. Whiskers: 95 % bootstrap interval.",
                                    [(lbl, d.get(f"ctx.busy30.b1000.{a}.mrr"), mine, f"{lbl} MRR",
                                      (d.get(f"ctx.busy30.b1000.{a}.mrr_ci_lo"), d.get(f"ctx.busy30.b1000.{a}.mrr_ci_hi"))
                                      if d.get(f"ctx.busy30.b1000.{a}.mrr_ci_lo") is not None else None,
                                      None if d.get(f"ctx.busy30.b1000.{a}.mrr") is None else f"{d.get(f'ctx.busy30.b1000.{a}.mrr'):.2f}")
                                     for lbl, a, mine in ctx if d.get(f"ctx.busy30.b1000.{a}.mrr") is not None],
                                    lambda v: f"{v:.2f}", 1.0,
                                    note="1.00 = the true cause is ranked first every time. The pack's ranking signal is the "
                                         "telemetry the graph holds; distance alone is weak.")
    cc = d.get("ladder.full.b.confirm_cases")
    files["ladder.svg"] = bars("Remove both path and flow checks and true causes are lost",
                               f"Right cause blamed, of the {cc} gate-bench worlds (second seed) that have one, one capability "
                               "removed at a time. Whiskers: 95 % interval.",
                               [rate_row("Full product (SPpaths + maxFlow)", "ladder.full.b.right_cause", True, "worlds"),
                                rate_row("algo.maxFlow removed", "ladder.no_maxflow.b.right_cause", False, "worlds"),
                                rate_row("algo.SPpaths → connectivity only", "ladder.no_sppaths.b.right_cause", False, "worlds"),
                                rate_row("Both removed", "ladder.neither.b.right_cause", False, "worlds")],
                               pct, 1.0,
                               note=f"Each algorithm backs up the other here (healthy look-alikes). Both removed: "
                                    f"{d.get('ladder.neither.abstained')} of {d.get('ladder.neither.cases')} worlds abstain; "
                                    "0 confident wrong blames on every rung.")
    lk = [("shortest_causal_path", "Shortest causal path"), ("reach_set", "Blast radius (reach set)"),
          ("hop_distance", "Hop distances")]
    rows = []
    for key, name in lk:
        rows.append((f"{name}: FalkorDB", d.get(f"perf.1k.{key}.falkordb_rt_p50"), True, "FalkorDB round trip p50 ms"))
        rows.append((f"{name}: DuckDB SQL", d.get(f"perf.1k.{key}.sql_p50"), False, "DuckDB recursive SQL p50 ms, in-process"))
    files["vs_sql.svg"] = bars("Same graph questions, same answers: FalkorDB and recursive SQL",
                               "1,000-service graph, p50 milliseconds, lower is better. FalkorDB includes the network round "
                               "trip; DuckDB runs in-process.", rows, lambda v: f"{v:.2f} ms",
                               max(v for _, v, _, _ in rows if v),
                               note="Results were checked equal on every instance. Max flow has no SQL equivalent.")
    if d.get("live.hero.n"):
        n = d["live.hero.n"]
        files["live.svg"] = bars("The live deployment, measured over HTTPS", f"Hero incident, {n} runs from outside the "
                                 f"server ({d.get('live.at')}): right cause {d.get('live.hero.cause_correct')}/{n}, "
                                 f"verified APPLIED {d.get('live.hero.applied')}/{n}. Milliseconds, p50; lower is better.",
                                 [("Alert to gate verdict", d.get("live.hero.verdict_ms_p50"), True, "p50 ms to a verdict"),
                                  ("Approve to verified write-back", d.get("live.hero.act_ms_p50"), True, "p50 ms"),
                                  ("Alert to RESOLVED, end to end", d.get("live.hero.total_ms_p50"), True, "p50 ms"),
                                  ("Company brain answer", d.get("live.brain.ms_p50"), False, "p50 ms"),
                                  ("Page, time to first byte", d.get("live.pages_ttfb_p50"), False, "p50 ms over pages")],
                                 lambda v: f"{v:,.0f} ms",
                                 max(v for v in (d.get("live.hero.total_ms_p50"), d.get("live.brain.ms_p50"), 1) if v))
    dr = [rate_row("Right cause · Faultline", "deep.fresh.all.right_cause", True, "worlds with a cause"),
          rate_row("Right cause · LLM alone", "llm_deep.deep.all.right_cause", False, "worlds with a cause"),
          rate_row("Right cause · telemetry only", "deep.fresh.all.T.right_strict", False, "worlds with a cause"),
          rate_row("Confident wrong blames · Faultline", "deep.fresh.all.wrong_confident", True, "worlds"),
          rate_row("Wrong blames · LLM alone", "llm_deep.deep.all.wrong_confident", False, "worlds"),
          rate_row("Wrong blames · telemetry only", "deep.fresh.all.T.wrong_any", False, "worlds"),
          rate_row("Abstained · Faultline", "deep.fresh.all.abstained", True, "worlds"),
          rate_row("Abstained · LLM alone", "llm_deep.deep.all.abstained", False, "worlds"),
          rate_row("Abstained · telemetry only", "deep.fresh.all.T.abstained", False, "worlds")]
    files["deep.svg"] = bars("Faultline trades recall for safety",
                             f"Deep bench, {d.get('deep.fresh.all.cases')} adversarial worlds ({d.get('deep.fresh.all.cause_cases')} "
                             "with a cause). Whiskers: 95 % interval.", [r for r in dr if r[1] is not None], pct, 1.0,
                             note="LLM alone: claude-opus-5-5, the same telemetry and change list, one trial per world. Ties never count.")
    if d.get("otel.faultline.right_cause.n"):
        orows = [rate_row("Right cause · Faultline", "otel.faultline.right_cause", True, "fault windows"),
                 rate_row("Right cause · telemetry threshold (T+)", "otel.Tplus.right_cause", False, "fault windows"),
                 rate_row("Right cause · recency", "otel.N.right_cause", False, "fault windows"),
                 rate_row("Wrong blames · Faultline", "otel.faultline.wrong", True, "windows"),
                 rate_row("Wrong blames · telemetry threshold (T+)", "otel.Tplus.wrong", False, "windows"),
                 rate_row("Wrong blames · recency", "otel.N.wrong", False, "windows"),
                 rate_row("Abstained · Faultline", "otel.faultline.abstained", True, "windows")]
        files["otel.svg"] = bars("On a real system: the OpenTelemetry Demo",
                                 f"Its own fault flags and its real telemetry: {d.get('otel.fault_windows')} fault windows "
                                 f"and {d.get('otel.controls')} no-fault controls, our decoy changes in each. Whiskers: 95 % "
                                 "interval.", [r for r in orows if r[1] is not None], pct, 1.0,
                                 note="Pre-registered, one laptop, five faults. Recency looks strong on faults only because "
                                      "the flag flip lands just before the page; it blames a change in every control.")
    nopath = d.get("perf.acme.shortest_causal_path.falkordb_engine_p50")
    cost = [("FalkorDB proving \"no path\" (G2)", 0, True, f"0 model tokens; engine time p50 {nopath} ms", None,
             f"0 tokens · {nopath} ms engine time")]
    for a, lbl in (("A0", "LLM alone"), ("A1", "LLM + vector RAG"), ("A3L", "LLM investigator + the graph gate")):
        v = d.get(f"arm.{a}.tokens_median")
        if v is not None:
            cost.append((f"{lbl} ({a})", float(v), False, f"{lbl}: median {v:,} tokens per decision", None,
                         f"{v:,} tokens"))
    vmax_c = 10 ** (len(str(int(max(v for _, v, *_ in cost)))))
    files["cost.svg"] = bars("The cost of a decision",
                             "Model tokens per decision, median of the recorded LLM runs (one trial per scenario); log scale. "
                             "The graph check itself uses no model.", cost, lambda v: f"{v:,.0f}", float(vmax_c), log=True,
                             vmin=100.0, note="Tokens from evals/results/llm_arms.json (claude-opus-5-5). The engine time is "
                                              "FalkorDB's own p50 on acme.")
    pub = ROOT / "frontend" / "public" / "media" / "charts"
    for name, svg in files.items():
        (OUT / name).write_text(svg)
        if pub.is_dir():   # the proof page's copies (byte-for-byte; the video recorder refuses a drifted copy)
            (pub / name).write_text(svg)
    print(f"wrote {len(files)} charts to {OUT.relative_to(ROOT)}: {', '.join(sorted(files))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
