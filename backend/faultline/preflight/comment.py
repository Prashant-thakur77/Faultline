"""The PR comment (quiet on `allow`: silence as a feature) and the status-check outcome."""

from __future__ import annotations

ICON = {"block": "⛔ block", "require_review": "⚠️ require review", "allow": "✅ allow"}


def render(result: dict, ui_base: str = "") -> str | None:
    """Markdown for the PR, or None when the verdict is allow (no comment; the status check still reports)."""
    v = result["verdict"]
    rev = result.get("reversals") or []
    if v == "allow" and not rev:   # quiet on allow, except to say the org already tried this and reversed it
        return None
    a = result.get("assessment") or {}
    lines = [f"### Faultline preflight: {ICON[v]} (risk {result['risk']})", ""]
    for f in (result.get("freeze") or {}).get("rows") or []:   # M20 #6: decided in FalkorDB from the wall clock
        days = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
        lines.append(f"- **Change freeze {f['policy']}** ({f['effect']}): {f['title']} on {f['component']}. FalkorDB "
                     f"evaluated the merge time as {days.get(f['day'], f['day'])} {f['hour']:02d}:{f['minute']:02d} local "
                     f"(UTC{'+' if f['utc_offset_min'] >= 0 else '-'}{abs(f['utc_offset_min']) // 60:02d}:"
                     f"{abs(f['utc_offset_min']) % 60:02d}); decided by {f.get('decided_by') or '?'} ({f['url']})")
    for d in result.get("decision_links") or []:
        lines.append(f"- **Contradicts {d['id']}**: {d['title']} ([decision]({d['url']}))")
    for r in rev:
        why = "; ".join(c.get("title") or c.get("id") for c in r.get("because") or [] if c)
        lines.append(f"- **Reinstates a reversed decision**: {r['reversed']} ({r.get('reversed_title') or r['rule_key']}) was "
                     f"replaced by {r['head']} ({r.get('head_title') or ''})" + (f", because: {why}" if why else "")
                     + (f" ([decision]({r['head_url']}))" if r.get("head_url") else ""))
    for k, t in (result.get("terms") or {}).items():
        if t["weighted"] > 0 and k != "decision":
            lines.append(f"- {k.replace('_', ' ')} (+{t['weighted']}): {t['why']}")
    if a.get("revenue_tier1"):
        lines.append(f"- Path: {' → '.join(a['changed'])} → {', '.join(a['revenue_tier1'])} (revenue path)")
    if result.get("reviewers"):
        lines.append(f"- Required reviewers (owner team, active, not the author): {', '.join(result['reviewers'])}")
    for w in result.get("would_change_if") or []:
        lines.append(f"- Would be **{w['verdict']}** if {w['if']}")
    if result.get("unknown_files"):
        lines.append(f"- Not in the graph (uncertainty): {', '.join(result['unknown_files'][:10])}")
    focus = (a.get("changed") or [""])[0]
    if ui_base:
        from urllib.parse import quote

        lines += ["", f"[Open in Faultline]({ui_base.rstrip('/')}/preflight?pr={quote(result['pr'], safe='')}&focus={quote(focus, safe='')})"]
    lines += ["", f"<sub>Every term above comes from a FalkorDB query (evidence {result['evidence']['evidence_id']}, "
                  f"template {result['evidence']['template']}). Weights: weights.yaml.</sub>"]
    return "\n".join(lines)


def exit_code(result: dict) -> int:
    """Status check: block fails the check; require_review and allow pass (the comment asks for reviewers)."""
    return 1 if result["verdict"] == "block" else 0
