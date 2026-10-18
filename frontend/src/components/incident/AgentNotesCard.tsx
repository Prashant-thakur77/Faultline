"use client";

import {
  ArrowRightLeft,
  CircleDashed,
  Compass,
  Eye,
  FlaskConical,
  Gavel,
  LoaderCircle,
  MapPin,
  MessageSquarePlus,
  MessagesSquare,
  OctagonAlert,
  Route,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { useNow, usePolled } from "@/hooks/usePolled";
import { api, ApiError } from "@/lib/api";
import { fmtAgo, fmtValue } from "@/lib/format";
import type { Tone } from "@/lib/gate";
import { useTenant } from "@/lib/tenant";
import type { AgentNote, AgentNoteReply, AgentNotesResponse } from "@/lib/types";
import { Section } from "./Section";

/** The card shows the best few; the query returns up to its LIMIT, ranked inside FalkorDB. */
const SHOW = 5;
/** Notes change rarely (a verified fix, an MCP client's `remember`): re-read every 30 s while the tab is visible. */
const NOTES_POLL_MS = 30_000;

const KIND: Record<string, { tone: Tone; icon: LucideIcon; text: string }> = {
  lead: { tone: "info", icon: Compass, text: "lead" },
  observation: { tone: "info", icon: Eye, text: "observation" },
  hypothesis: { tone: "na", icon: FlaskConical, text: "hypothesis" },
  handoff: { tone: "info", icon: ArrowRightLeft, text: "hand-off" },
  verdict: { tone: "info", icon: Gavel, text: "verdict" },
};

const STANCE: Record<string, { tone: Tone; icon: LucideIcon; text: string }> = {
  confirms: { tone: "pass", icon: ThumbsUp, text: "confirms" },
  refutes: { tone: "warn", icon: ThumbsDown, text: "refutes" },
  adds: { tone: "info", icon: MessageSquarePlus, text: "adds" },
};

/** GET /api/notes?focus=: re-read on an interval; a change of tenant or focus starts over (never the old answer). */
export function useAgentNotes(focus: string | null, tenant: string) {
  return usePolled<AgentNotesResponse>(
    `agent-notes|${tenant}|${focus ?? ""}`,
    (s) => api.notes({ tenant, focus: focus! }, s),
    { intervalMs: NOTES_POLL_MS, enabled: !!focus },
  );
}

/** One plain sentence for a failed read; a 503 says FalkorDB is down, never "no notes". */
export function notesErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail.replace(/\.$/, "");
    if (err.status === null) return `Notes unavailable: ${detail}.`;
    if (err.status === 503) return `Notes unavailable: FalkorDB is down or not ready (${detail}, HTTP 503).`;
    if (err.status === 404 && /^not found$/i.test(err.detail.trim()))
      return "Notes unavailable: this API has no notes endpoint (HTTP 404).";
    return `Notes could not be read: ${detail} (HTTP ${err.status}).`;
  }
  return `Notes could not be read: ${err instanceof Error ? err.message : String(err)}.`;
}

/**
 * Notes from other agents (track T2): short leads that agents left for each other about components (Faultline's own
 * runs after a verified fix, and any MCP client through `remember`), kept in their own graph agentmem_<tenant>. Read in
 * one read-only query (Q-NOTE-RECALL): the notes about `focus` or a component near it, ranked inside FalkorDB. Leads
 * only: the evidence gate never reads that graph. Live room only (a recording has no notes graph to read).
 */
export function AgentNotesCard({ focus }: { focus: string | null }) {
  const tenant = useTenant();
  const panel = useCypherPanel();
  const notes = useAgentNotes(focus, tenant);
  const d = notes.data;
  const rows = d?.rows ?? [];
  const shown = rows.slice(0, SHOW);
  const memGraph = `agentmem_${tenant}`;

  const openPanel = (r: AgentNotesResponse) =>
    panel.open({
      template: r.template,
      title: `notes from other agents${focus ? ` near ${focus}` : ""}`,
      origin: `the notes card (GET /api/notes, ${memGraph})`,
      detail:
        `${r.rows.length} note${r.rows.length === 1 ? "" : "s"} recalled by ${r.via}. Served by ${r.served_by}.` +
        (r.note ? ` ${r.note}.` : ""),
      recordedParams: r.params,
      recorded: { ms: r.ms, rows: r.rows.length },
      // no incident: Re-run and PROFILE read the template's home graph (`// home: agentmem` → agentmem_<tenant>)
      ctx: {},
      tenant,
    });

  return (
    <Section
      id="agentnotes"
      title="Notes from other agents"
      via={d ? <ViaFalkor template={d.template} label="the notes from other agents" onOpen={() => openPanel(d)} /> : null}
      aside={
        <>
          {d ? (
            <StatusChip tone={rows.length ? "info" : "na"} icon={MessagesSquare}>
              {rows.length} note{rows.length === 1 ? "" : "s"}
            </StatusChip>
          ) : notes.error ? (
            <StatusChip tone="fail" icon={OctagonAlert}>
              unavailable
            </StatusChip>
          ) : null}
          {focus ? (
            <span className="text-xs text-[var(--fl-subtle)]">
              near <span className="font-mono text-zinc-300">{focus}</span>
            </span>
          ) : null}
        </>
      }
    >
      <p className="mb-2 text-[11px] text-zinc-400">
        Leads that agents left for each other: Faultline&apos;s own runs and any MCP client. Never evidence: the gate does
        not read them.
      </p>
      {notes.error ? (
        <p
          role="alert"
          className="mb-2 flex items-start gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-100 ring-1 ring-red-500/40"
        >
          <OctagonAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
          <span>
            {notesErrorText(notes.error)}
            {d ? " Showing the last answer; it may be out of date." : ""}
          </span>
        </p>
      ) : null}
      {!focus ? (
        <p className="text-sm text-zinc-300">This incident names no component, so there is nothing to look up notes for.</p>
      ) : notes.loading && !d && !notes.error ? (
        <p role="status" className="flex items-center gap-2 text-xs text-zinc-300">
          <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" /> Reading notes from FalkorDB…
        </p>
      ) : d && rows.length === 0 ? (
        <p className="text-sm text-zinc-300">No agent has left a note about this component or its neighbours yet.</p>
      ) : shown.length ? (
        <>
          <ol className="space-y-1.5" aria-label={`Notes about ${focus} or near it, best first`}>
            {shown.map((n) => (
              <NoteItem key={n.id} note={n} focus={focus} />
            ))}
          </ol>
          {rows.length > SHOW ? (
            <p className="mt-1.5 text-[11px] text-zinc-400">
              Showing the top {SHOW} of {rows.length}.
            </p>
          ) : null}
        </>
      ) : null}
    </Section>
  );
}

function KindChip({ kind }: { kind: string }) {
  const k = KIND[kind];
  return k ? (
    <StatusChip tone={k.tone} icon={k.icon}>
      {k.text}
    </StatusChip>
  ) : (
    <StatusChip tone="na" icon={CircleDashed}>
      {kind || "no kind"}
    </StatusChip>
  );
}

function StanceChip({ stance }: { stance: string }) {
  const s = STANCE[stance];
  return s ? (
    <StatusChip tone={s.tone} icon={s.icon}>
      {s.text}
    </StatusChip>
  ) : (
    <StatusChip tone="na" icon={CircleDashed}>
      {stance || "no stance"}
    </StatusChip>
  );
}

function Nearness({ note, focus }: { note: AgentNote; focus: string }) {
  const cls = "inline-flex items-center gap-1 text-[11px] text-zinc-400";
  if (note.hops === null)
    return (
      <span className={cls} title={note.similarity !== null ? `meaning similarity ${fmtValue(note.similarity)}` : undefined}>
        <Sparkles aria-hidden className="size-3 shrink-0" /> by meaning
      </span>
    );
  if (note.hops === 0)
    return (
      <span className={cls}>
        <MapPin aria-hidden className="size-3 shrink-0" /> about <span className="font-mono text-zinc-300">{focus}</span>
      </span>
    );
  return (
    <span className={cls}>
      <Route aria-hidden className="size-3 shrink-0" /> {note.hops} hop{note.hops === 1 ? "" : "s"} away
    </span>
  );
}

function When({ at }: { at: number | null }) {
  const now = useNow(30_000);
  if (at === null || !Number.isFinite(at)) return <span>at an unrecorded time</span>;
  return (
    <time dateTime={new Date(at).toISOString()} title={new Date(at).toLocaleString()}>
      {fmtAgo(at, now)}
    </time>
  );
}

function NoteItem({ note, focus }: { note: AgentNote; focus: string }) {
  const who = note.name || note.agent;
  return (
    <li className="rounded-md border border-zinc-700 p-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <KindChip kind={note.kind} />
        <span className="text-sm font-semibold text-zinc-50">{who}</span>
        {note.name && note.name !== note.agent ? (
          <span className="font-mono text-[11px] text-zinc-400" title="the signed-in caller that wrote it">
            {note.agent}
          </span>
        ) : null}
        <span className="text-[11px] text-zinc-400">
          · <When at={note.created_at} />
        </span>
        <span
          className="ml-auto font-mono text-[11px] text-zinc-300"
          title="ranked inside FalkorDB by meaning, nearness and freshness"
        >
          score {fmtValue(note.score)}
        </span>
      </div>
      <p className="mt-1 text-sm break-words text-zinc-200 [overflow-wrap:anywhere]">{note.text}</p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <Nearness note={note} focus={focus} />
        {note.about.length ? (
          <ul className="flex flex-wrap gap-1" aria-label="Components this note is about">
            {note.about.map((id) => (
              <li
                key={id}
                className={
                  "rounded bg-white/[0.04] px-1 font-mono text-[11px] ring-1 ring-white/[0.08] " +
                  (id === focus ? "text-zinc-50" : "text-zinc-300")
                }
              >
                {id}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <Replies note={note} />
    </li>
  );
}

function Replies({ note }: { note: AgentNote }) {
  const replies = note.replies ?? [];
  if (!replies.length) return <p className="mt-1 text-[11px] text-zinc-400">No replies yet.</p>;
  const count = (s: string) => replies.filter((r) => r.stance === s).length;
  const confirm = count("confirms");
  const refute = count("refutes");
  const add = count("adds");
  return (
    <Disclosure
      size="xs"
      defaultOpen={false}
      className="mt-1"
      bodyClassName="mt-1"
      summary={
        <span className="inline-flex flex-wrap items-center gap-1">
          <span>
            {replies.length} repl{replies.length === 1 ? "y" : "ies"}
          </span>{" "}
          <StatusChip tone={confirm ? "pass" : "na"} icon={ThumbsUp}>
            {confirm} confirm
          </StatusChip>{" "}
          <StatusChip tone={refute ? "warn" : "na"} icon={ThumbsDown}>
            {refute} refute
          </StatusChip>
          {add ? (
            <>
              {" "}
              <StatusChip tone="info" icon={MessageSquarePlus}>
                {add} add
              </StatusChip>
            </>
          ) : null}
        </span>
      }
    >
      <ul className="space-y-1" aria-label={`Replies to note ${note.id}`}>
        {replies.map((r: AgentNoteReply) => (
          <li key={r.id} className="rounded bg-white/[0.02] px-2 py-1 text-xs ring-1 ring-white/[0.06]">
            <div className="flex flex-wrap items-center gap-1.5">
              <StanceChip stance={r.stance} />
              <span className="font-mono text-[11px] text-zinc-400">{r.agent}</span>
            </div>
            <p className="mt-0.5 break-words text-zinc-200 [overflow-wrap:anywhere]">{r.text}</p>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
