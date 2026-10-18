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

/**
 * A count with its noun, pluralised: "1 check", "3 checks", "0 checks". Pass `many` when the plural is not the noun
 * plus "s" ("1 query", "2 queries"). An unknown count reads "– checks" (never a guessed number).
 */
export function plural(n: number | null | undefined, one: string, many = `${one}s`): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return `– ${many}`;
  return `${n} ${n === 1 ? one : many}`;
}

/** Ends a sentence that came from elsewhere (a server reason, a note) with a full stop unless it already has one. */
export function sentence(s: string): string {
  const t = s.trim();
  return t === "" || /[.!?…:;]$/.test(t) ? t : `${t}.`;
}

/**
 * A long id cut in the middle so both ends stay readable ("ADR-012" stays whole; "rb-derived-0b6bb0db12" becomes
 * "rb-der…0db12"). Ids of `max` characters or fewer are returned unchanged.
 */
export function midTruncate(id: string, max = 12): string {
  if (id.length <= max) return id;
  const tail = Math.floor((max - 1) / 2);
  const head = max - 1 - tail;
  return `${id.slice(0, head)}…${id.slice(id.length - tail)}`;
}

/** A snake_case scenario or flag name in words ("same_minute_distractor" → "same minute distractor"). */
export function slugWords(s: string): string {
  return s.replace(/[_]+/g, " ").replace(/\s+/g, " ").trim();
}
