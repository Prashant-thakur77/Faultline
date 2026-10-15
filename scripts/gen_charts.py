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


def bars(title: str, subtitle: str, rows: list[tuple[str, float | None, bool, str]], fmt, vmax: float,
         note: str = "") -> str:
    """Horizontal bars. rows: (label, value, is_faultline, tooltip). value None draws an em-less 'n/a' row."""
    w, left, right, top, row_h, bar_h = 760, 250, 70, 84, 38, 18
    h = top + row_h * len(rows) + (46 if note else 24)
    plot = w - left - right
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
         f'aria-label="{escape(title)}">',
         f'<title>{escape(title)}</title>',
         f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" fill="{CARD}" stroke="{GRID}"/>',
         f'<text x="24" y="34" font-family="{FONT}" font-size="17" font-weight="600" fill="{INK}">{escape(title)}</text>',
         f'<text x="24" y="56" font-family="{FONT}" font-size="12.5" fill="{INK2}">{escape(subtitle)}</text>']
    for t in (0, 0.5, 1.0):  # recessive grid at 0, half and full scale
        x = left + plot * t
        o.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{top + row_h * len(rows) - 12}" stroke="{GRID}"/>')
    for i, (label, v, mine, tip) in enumerate(rows):
        y = top + i * row_h
        weight, ink = ("600", INK) if mine else ("400", INK2)
        o.append(f'<text x="{left - 14}" y="{y + bar_h - 4}" text-anchor="end" font-family="{FONT}" font-size="13" '
                 f'font-weight="{weight}" fill="{ink}">{escape(label)}</text>')
        if v is None:
            o.append(f'<text x="{left + 6}" y="{y + bar_h - 4}" font-family="{FONT}" font-size="12" fill="{MUTED}">n/a</text>')
            continue
        bw = max(plot * (v / vmax), 2.5) if v > 0 else 0
        if bw:
            o.append(f'<g><title>{escape(tip)}</title><rect x="{left}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="4" '
                     f'fill="{ACCENT if mine else GRAY}"/></g>')
        o.append(f'<text x="{left + bw + 8:.1f}" y="{y + bar_h - 4}" font-family="{FONT}" font-size="13" '
                 f'font-weight="{weight}" fill="{INK}">{escape(fmt(v))}</text>')
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

    def arm_rows(metric: str, keys: list[tuple[str, str, bool]]) -> list:
        return [(lbl, d.get(f"arm.{a}.{metric}"), mine, f"{lbl}: {metric} = {d.get(f'arm.{a}.{metric}')} "
                 f"over {d.get(f'arm.{a}.trials')} trials") for lbl, a, mine in keys]

    files = {
        "outcome.svg": bars("Right outcome on the scenario suite", f"Share of trials with the correct verdict (confirm the "
                            f"true cause, or abstain when there is none). Higher is better. Eval {run}.",
                            arm_rows("outcome_correct_rate", arms), pct, 1.0,
                            note="FalkorDB switched off fails closed: it confirms nothing rather than guessing."),
        "false_blame.svg": bars("Confidently blaming the wrong change", "Share of scenarios with a true cause where the "
                                f"approach blamed a different change. Lower is better. Eval {run}.",
                                arm_rows("false_blame_rate", [a for a in arms if a[1] in ("A3", "T", "V", "N")]), pct, 1.0),
        "context_mrr.svg": bars("Is the true cause near the top of the agent's context?", "Mean reciprocal rank of the "
                                "true cause with 30 unrelated deploys in the window, 1,000-token budget. Higher is better.",
                                [("Graph context pack (FalkorDB)", d.get("ctx.busy30.b1000.GA.mrr"), True, "graph context_pack MRR"),
                                 ("Vector RAG", d.get("ctx.busy30.b1000.V.mrr"), False, "vector RAG MRR"),
                                 ("Recency", d.get("ctx.busy30.b1000.R.mrr"), False, "recency MRR")],
                                lambda v: f"{v:.2f}", 1.0, note="1.00 means the true cause is ranked first every time."),
    }
    files["ladder.svg"] = bars("Take FalkorDB's algorithms away and the answers get worse",
                               f"Correct verdicts on the {d.get('ladder.full.cases')} held-out gate-bench worlds, one capability "
                               "removed at a time. Higher is better.",
                               [("Full product (SPpaths + maxFlow)", d.get("ladder.full.correct"), True, "correct of 100"),
                                ("algo.maxFlow removed", d.get("ladder.no_maxflow.correct"), False, "correct of 100"),
                                ("algo.SPpaths removed (connectivity only)", d.get("ladder.no_sppaths.correct"), False, "correct of 100"),
                                ("Both removed", d.get("ladder.neither.correct"), False, "correct of 100")],
                               lambda v: f"{v:.0f}", float(d.get("ladder.full.cases") or 100),
                               note="Every rung stays at zero confident wrong blames; what is lost is the ability to decide.")
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
    for name, svg in files.items():
        (OUT / name).write_text(svg)
    print(f"wrote {len(files)} charts to {OUT.relative_to(ROOT)}: {', '.join(sorted(files))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
