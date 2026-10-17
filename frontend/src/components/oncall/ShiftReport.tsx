"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { LoaderCircle, NotebookPen, Send } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import type { Polled } from "@/hooks/usePolled";
import { ApiError, errorText } from "@/lib/api";
import { fmtWhen, oncallApi, REPORT_SECTIONS, type HandoffResult, type ReportItem, type ReportSection, type ShiftReport } from "@/lib/oncall";
import { cn } from "@/lib/utils";
import { PanelError, useOpenQuery } from "./bits";

export const REPORT_WINDOWS = [
  { hours: 12, label: "12 h" },
  { hours: 24, label: "24 h" },
  { hours: 168, label: "7 d" },
] as const;

/**
 * The shift report (Q-SHIFT-REPORT, GET /api/oncall/report): what happened in the window (incidents, pages, acks,
 * actions, uses under contract, hand-offs), then the hand-off note for whoever takes over (POST /api/handoffs).
 */
export function ShiftReportCard({
  polled,
  tenant,
  hours,
  onHours,
  people,
  incidents,
}: {
  polled: Polled<ShiftReport>;
  tenant: string;
  hours: number;
  onHours: (h: number) => void;
  /** Suggestions for "to" (who is on call now), from the graph. */
  people: { id: string; name: string | null }[];
  /** Suggestions for the incident field (pages and the report's incidents). */
  incidents: string[];
}) {
  const open = useOpenQuery(tenant);
  const r = polled.data;
  const total = r ? REPORT_SECTIONS.reduce((n, s) => n + (r.counts[s.key] ?? 0), 0) : 0;
  return (
    <Section
      id="shift"
      title="Shift report"
      via={r?.template ? <ViaFalkor template={r.template} label="the shift report" onOpen={() => open(r, "shift report", "GET /api/oncall/report")} /> : null}
      aside={
        <div role="group" aria-label="Report window" className="inline-flex rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]">
          {REPORT_WINDOWS.map((w) => (
            <button
              key={w.hours}
              type="button"
              aria-pressed={hours === w.hours}
              onClick={() => onHours(w.hours)}
              className={cn(
                "h-6 rounded-full px-2.5 text-[11px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
                hours === w.hours ? "bg-zinc-50 font-medium text-zinc-950" : "text-zinc-300 hover:text-zinc-50",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
      }
    >
      {polled.error ? <PanelError error={polled.error} what="the shift report (GET /api/oncall/report)" stale={!!r} /> : null}
      {polled.loading && !r && !polled.error ? (
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> Reading the shift from FalkorDB…
        </p>
      ) : null}
      {r ? (
        <div className="space-y-3">
          <p className="text-xs text-zinc-400">
            {r.from !== null && r.to !== null ? (
              <>
                {fmtWhen(r.from)} to {fmtWhen(r.to)}
              </>
            ) : (
              "Window not reported by the server."
            )}
          </p>
          {r.summary ? <p className="text-sm leading-relaxed text-zinc-200">{r.summary}</p> : null}
          <ReportCounts report={r} tenant={tenant} />
          {!r.summary && total === 0 && REPORT_SECTIONS.every((s) => r.counts[s.key] !== null) ? (
            <p className="text-sm text-zinc-300">A quiet shift: nothing was recorded in this window.</p>
          ) : null}
        </div>
      ) : null}
      <div className="mt-4 border-t border-white/[0.06] pt-4">
        <HandoffForm tenant={tenant} people={people} incidents={incidents} onRecorded={polled.refresh} />
      </div>
    </Section>
  );
}

/** One tile per section; a tile with rows opens its list below (one at a time), so the report stays one glance. */
function ReportCounts({ report: r, tenant }: { report: ShiftReport; tenant: string }) {
  const [open, setOpen] = useState<ReportSection | null>(null);
  const listId = useId();
  const shown = open && r.sections[open]?.length ? REPORT_SECTIONS.find((s) => s.key === open)! : null;
  return (
    <div className="space-y-2">
      <ul aria-label="What happened in the window" className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {REPORT_SECTIONS.map((s) => {
          const n = r.counts[s.key];
          const rows = r.sections[s.key]?.length ?? 0;
          const body = (
            <>
              <span className="block truncate text-[11px] text-zinc-400">{s.short}</span>
              <span className="mt-0.5 block font-mono text-lg leading-tight text-zinc-50">
                {n ?? "–"}
                {n === null ? <span className="sr-only"> (not reported)</span> : null}
              </span>
            </>
          );
          return (
            <li key={s.key} className="min-w-0">
              {rows ? (
                <button
                  type="button"
                  aria-expanded={open === s.key}
                  aria-controls={listId}
                  title={`${s.label}: show the ${rows} row${rows === 1 ? "" : "s"}`}
                  onClick={() => setOpen((o) => (o === s.key ? null : s.key))}
                  className={cn(
                    "w-full rounded-lg px-2.5 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
                    open === s.key ? "bg-white/[0.08] ring-1 ring-white/20" : "bg-white/[0.03] hover:bg-white/[0.06]",
                  )}
                >
                  {body}
                </button>
              ) : (
                <div className="rounded-lg bg-white/[0.02] px-2.5 py-2">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
      <div id={listId} hidden={!shown}>
        {shown ? <ReportList items={r.sections[shown.key]!} tenant={tenant} label={shown.label} /> : null}
      </div>
    </div>
  );
}

function ReportList({ items, tenant, label }: { items: ReportItem[]; tenant: string; label: string }) {
  return (
    <ul aria-label={label} className="space-y-1 pb-1">
      {items.slice(0, 50).map((it, i) => (
        <li key={`${it.id ?? "row"}:${i}`} className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md bg-white/[0.02] px-2.5 py-1.5 text-xs">
          {it.id ? <span className="font-mono text-zinc-200">{it.id}</span> : null}
          {it.title ? <span className="min-w-0 break-words text-zinc-300">{it.title}</span> : null}
          {it.status ? <StatusChip tone="na">{it.status}</StatusChip> : null}
          {it.who ? <span className="text-zinc-400">· {it.who}</span> : null}
          {it.incident && it.incident !== it.id ? (
            <Link
              href={`/incidents/${encodeURIComponent(it.incident)}?tenant=${encodeURIComponent(tenant)}`}
              className="rounded font-mono text-[11px] text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              {it.incident}
            </Link>
          ) : null}
          {it.at !== null ? <span className="ml-auto text-[11px] text-[var(--fl-subtle)]">{fmtWhen(it.at)}</span> : null}
        </li>
      ))}
      {items.length > 50 ? <li className="text-[11px] text-zinc-400">+{items.length - 50} more in the report</li> : null}
    </ul>
  );
}

/** The hand-off note: to whom (a person id the server checks in the graph), optionally which incident, and the note. */
export function HandoffForm({
  tenant,
  people,
  incidents,
  onRecorded,
}: {
  tenant: string;
  people: { id: string; name: string | null }[];
  incidents: string[];
  onRecorded: () => void;
}) {
  const toId = useId();
  const incId = useId();
  const noteId = useId();
  const peopleList = useId();
  const incList = useId();
  const hintId = useId();
  const [to, setTo] = useState("");
  const [from, setFrom] = useState("");
  const [key, setKey] = useState("");
  const fromId = useId();
  const keyId = useId();
  const [incident, setIncident] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<(HandoffResult & { to: string }) | null>(null);
  const [err, setErr] = useState<{ status: number | null; text: string } | null>(null);
  const noteOk = note.trim().length >= 3;

  const submit = async () => {
    setBusy(true);
    setErr(null);
    setDone(null);
    try {
      const body = {
        note: note.trim(),
        to: to.trim(),
        ...(incident.trim() ? { incident: incident.trim() } : {}),
        ...(from.trim() ? { from: from.trim() } : {}),
      };
      const res = await oncallApi.handoff(body, tenant, key.trim() || undefined);
      setDone({ ...res, to: body.to });
      setNote("");
      onRecorded();
    } catch (e) {
      setErr({ status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  const field =
    "rounded-md border border-zinc-700 bg-zinc-950 px-2 text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400";
  return (
    <form
      aria-labelledby={`${noteId}-h`}
      className="space-y-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy && to.trim() && noteOk) void submit();
      }}
    >
      <h3 id={`${noteId}-h`} className="flex items-center gap-1.5 text-[13px] font-medium text-zinc-100">
        <NotebookPen aria-hidden className="size-4 text-[var(--fl-subtle)]" /> Hand off the shift
      </h3>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <label htmlFor={toId} className="flex min-w-0 flex-col gap-0.5 text-[11px] text-zinc-400">
          To (person id)
          <input
            id={toId}
            value={to}
            onChange={(e) => setTo(e.target.value)}
            list={people.length ? peopleList : undefined}
            required
            maxLength={60}
            autoComplete="off"
            spellCheck={false}
            placeholder="e.g. who is on call next"
            className={cn(field, "h-8 font-mono")}
          />
        </label>
        {people.length ? (
          <datalist id={peopleList}>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name ? `${p.name} (${p.id})` : p.id}
              </option>
            ))}
          </datalist>
        ) : null}
        <label htmlFor={incId} className="flex min-w-0 flex-col gap-0.5 text-[11px] text-zinc-400">
          Incident (optional)
          <input
            id={incId}
            value={incident}
            onChange={(e) => setIncident(e.target.value)}
            list={incidents.length ? incList : undefined}
            maxLength={160}
            autoComplete="off"
            spellCheck={false}
            placeholder="the incident this note covers"
            className={cn(field, "h-8 font-mono")}
          />
        </label>
        {incidents.length ? (
          <datalist id={incList}>
            {incidents.map((i) => (
              <option key={i} value={i} />
            ))}
          </datalist>
        ) : null}
        <label htmlFor={fromId} className="flex min-w-0 flex-col gap-0.5 text-[11px] text-zinc-400 sm:col-span-2">
          From (optional: by default, whoever is on call now for their team)
          <input
            id={fromId}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            list={people.length ? peopleList : undefined}
            maxLength={60}
            autoComplete="off"
            spellCheck={false}
            placeholder="your person id"
            className={cn(field, "h-8 font-mono sm:w-1/2")}
          />
        </label>
      </div>
      <label htmlFor={noteId} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
        Note (at least 3 characters)
        <textarea
          id={noteId}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={2000}
          required
          aria-describedby={hintId}
          aria-invalid={note.length > 0 && !noteOk ? true : undefined}
          placeholder="What is still open, what to watch, what you already tried"
          className={cn(field, "py-1.5 leading-relaxed")}
        />
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={busy || !to.trim() || !noteOk}
          className="fl-press inline-flex h-8 items-center gap-1.5 rounded-full bg-zinc-50 px-4 text-[13px] font-medium text-zinc-950 outline-none hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : <Send aria-hidden className="size-4" />}
          Record hand-off
        </button>
        <p id={hintId} className="text-[11px] text-[var(--fl-subtle)]">
          Written to the graph as a (:Handoff) from this shift to that person; the next shift sees it here.
        </p>
      </div>
      <details open={err?.status === 403 || undefined} className="text-[11px] text-zinc-400">
        <summary className="cursor-pointer rounded outline-none focus-visible:ring-2 focus-visible:ring-sky-400">Approver key (only on the public demo)</summary>
        <label htmlFor={keyId} className="mt-1 flex flex-col gap-0.5">
          Sent with this hand-off only, never stored
          <input
            id={keyId}
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            className={cn(field, "h-7 w-56 max-w-full font-mono text-xs")}
          />
        </label>
      </details>
      {done ? (
        <p role="status" className="text-xs text-emerald-200">
          Hand-off <span className="font-mono">{done.id}</span> recorded{done.at !== null ? ` at ${fmtWhen(done.at)}` : ""} for{" "}
          <span className="font-mono">{done.to}</span>.
        </p>
      ) : null}
      {err ? (
        <p role="alert" className="text-xs text-red-200">
          <strong className="font-semibold">Not recorded:</strong> {err.text}
          {err.status ? ` (HTTP ${err.status})` : ""}
          {err.status === 422 ? ". The server accepts only active people in the graph; name who hands off when nobody else is on call for that team." : ""}
          {err.status === 403 ? ". Enter the approver key below." : ""}
        </p>
      ) : null}
    </form>
  );
}
