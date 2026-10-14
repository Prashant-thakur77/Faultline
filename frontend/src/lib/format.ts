/** Formatting helpers. Pure display: they never invent values. */

export function fmtTime(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  return new Date(ms).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function fmtClock(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  const d = new Date(ms);
  return `${d.toLocaleTimeString(undefined, { hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

/** Offset from the first event of a run, e.g. "+0.231 s". */
export function fmtOffset(ms: number, base: number): string {
  const s = (ms - base) / 1000;
  return `+${s.toFixed(3)} s`;
}

export function fmtAgo(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  return ms < 10 ? `${ms.toFixed(2)} ms` : `${ms.toFixed(1)} ms`;
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "–";
  return n.toLocaleString("en-US");
}

/** "sha256:107455e862a8…" style short digest (keeps the algorithm prefix when present). */
export function shortDigest(d: string | null | undefined, n = 12): string {
  if (!d) return "–";
  const [algo, hex] = d.includes(":") ? d.split(":", 2) : ["", d];
  return `${algo ? `${algo}:` : ""}${hex.slice(0, n)}`;
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(6)));
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** A stage id in words for prose and screen-reader announcements ("AWAITING_APPROVAL" → "awaiting approval"). */
export function stageWords(stage: string): string {
  return stage.toLowerCase().replace(/_/g, " ");
}

/** A calendar date ("03 Jun 2026") in UTC: decisions are dated by day, so the local zone must not shift the day. */
export function fmtDate(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  return new Date(ms).toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "2-digit", timeZone: "UTC" });
}
