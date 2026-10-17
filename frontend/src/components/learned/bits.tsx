"use client";

import { useId, useState } from "react";
import { LoaderCircle, OctagonAlert, type LucideIcon } from "lucide-react";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { StatusChip } from "@/components/StatusChip";
import { ApiError, errorText } from "@/lib/api";
import type { Envelope } from "@/lib/learned";
import { cn } from "@/lib/utils";

/**
 * Opens the Cypher panel for one section of GET /api/learned: the template, the params the server ran it with, its
 * engine time and row count. The origin names the graph the server read (the on-call home, or audit_<t> for receipts).
 */
export function useOpenLearned(tenant: string) {
  const panel = useCypherPanel();
  return (env: Pick<Envelope<unknown>, "template" | "params" | "ms" | "digest"> & { rows?: unknown[] }, title: string, graph: string | null, origin = "GET /api/learned") => {
    if (!env.template) return;
    panel.open({
      template: env.template,
      title,
      origin: `${origin}${graph ? ` (${graph})` : ""}`,
      recordedParams: env.params,
      recorded: env.ms !== null ? { ms: env.ms, rows: env.rows ? env.rows.length : null, digest: env.digest } : null,
      ctx: {},
      tenant,
    });
  };
}

/** The section hit the template's LIMIT: say so (the list is not everything). */
export function Truncated({ env }: { env: Pick<Envelope<unknown>, "truncated"> }) {
  return env.truncated ? (
    <StatusChip tone="warn" className="mb-2">
      truncated at the template LIMIT
    </StatusChip>
  ) : null;
}

/** An honest empty state: what would fill this section, never a sample. */
export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">{children}</p>;
}

/** One sentence for a failed learned-state write; the next step when there is one. */
export function writeErrorText(e: unknown): { head: string; text: string } {
  if (!(e instanceof ApiError)) return { head: "Failed:", text: errorText(e) };
  const d = e.detail.replace(/\.$/, "");
  switch (e.status) {
    case null:
      return { head: "Unavailable:", text: `${d}.` };
    case 401:
    case 403:
      return { head: "Approver key required:", text: `${d} (HTTP ${e.status}). Enter the approver key.` };
    case 404:
      return { head: "Not found:", text: `${d} (HTTP 404).` };
    case 409:
      return { head: "Refused:", text: `${d} (HTTP 409).` };
    case 422:
      return { head: "Refused:", text: `${d} (HTTP 422).` };
    case 429:
      return { head: "Rate limited:", text: `${d} (HTTP 429). Try again in a minute.` };
    default:
      return { head: "Failed:", text: `${d} (HTTP ${e.status}).` };
  }
}

const FIELD =
  "h-8 rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400";

/** The person-id field every learned-state change needs (`by` / `approver`: an active person of the tenant). */
export function PersonField({
  label,
  value,
  onChange,
  listId,
  id: idProp,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  listId?: string;
  id?: string;
}) {
  const own = useId();
  const id = idProp ?? own;
  return (
    <label htmlFor={id} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
      {label}
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        list={listId}
        required
        maxLength={60}
        autoComplete="off"
        spellCheck={false}
        placeholder="e.g. p-017"
        className={cn(FIELD, "w-44 max-w-full")}
      />
    </label>
  );
}

/** The approver key, typed per change: sent with that request only, never stored. */
export function KeyField({ value, onChange, publicDemo }: { value: string; onChange: (v: string) => void; publicDemo: boolean | null }) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
      {publicDemo ? "Approver key (required on the public demo; sent with this change only, never stored)" : "Approver key (when the server asks for one; sent with this change only, never stored)"}
      <input id={id} type="password" value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" className={cn(FIELD, "w-56 max-w-full text-xs")} />
    </label>
  );
}

/**
 * A learned-state change in two clicks: the trigger, then a confirm that names the consequence and asks who acts
 * (an active person id) and, when the server needs it, the approver key. The result is reported by the caller
 * (`onDone`), since the item it changed usually moves to another list.
 */
export function ActorConfirm({
  label,
  ariaLabel,
  icon: Icon,
  question,
  confirmLabel,
  tone = "neutral",
  actor,
  onActor,
  listId,
  publicDemo,
  run,
  onDone,
}: {
  label: string;
  ariaLabel: string;
  icon: LucideIcon;
  question: React.ReactNode;
  confirmLabel: string;
  tone?: "neutral" | "primary" | "danger";
  actor: string;
  onActor: (v: string) => void;
  listId?: string;
  publicDemo: boolean | null;
  run: (by: string, key: string | undefined) => Promise<unknown>;
  onDone: (res: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ head: string; text: string } | null>(null);
  const go = async () => {
    if (!actor.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await run(actor.trim(), key.trim() || undefined);
      setOpen(false);
      setKey("");
      onDone(res);
    } catch (e) {
      setErr(writeErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  const trigger = cn(
    "inline-flex h-7 items-center gap-1 rounded-full px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
    tone === "danger"
      ? "text-red-200 ring-1 ring-red-400/40 hover:bg-red-500/10"
      : tone === "primary"
        ? "text-sky-100 ring-1 ring-sky-400/50 hover:bg-sky-500/10"
        : "text-zinc-200 ring-1 ring-white/15 hover:bg-white/[0.05]",
  );
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} aria-label={ariaLabel} className={trigger}>
        <Icon aria-hidden className="size-3.5" /> {label}
      </button>
    );
  }
  return (
    <div role="group" aria-label={`Confirm: ${ariaLabel}`} className="mt-1 w-full space-y-2 rounded-lg bg-white/[0.03] p-2.5 ring-1 ring-white/10">
      <p className="text-xs text-zinc-100">{question}</p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void go();
        }}
      >
        <PersonField label="Who decides (an active person id)" value={actor} onChange={onActor} listId={listId} />
        <KeyField value={key} onChange={setKey} publicDemo={publicDemo} />
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={busy || !actor.trim()}
            className={cn(
              "inline-flex h-8 items-center gap-1 rounded-full px-3.5 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60",
              tone === "danger" ? "bg-red-300 text-zinc-950 hover:bg-red-200" : "bg-zinc-50 text-zinc-950 hover:bg-white",
            )}
          >
            {busy ? <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" /> : <Icon aria-hidden className="size-3.5" />}
            {confirmLabel}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setOpen(false);
              setErr(null);
            }}
            className="inline-flex h-8 items-center rounded-full px-3 text-xs text-zinc-200 outline-none hover:bg-white/[0.06] focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            Cancel
          </button>
        </div>
      </form>
      {err ? (
        <p role="alert" className="flex items-start gap-1.5 text-[11px] text-red-200">
          <OctagonAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
          <span>
            <strong className="font-semibold">{err.head}</strong> {err.text}
          </span>
        </p>
      ) : null}
    </div>
  );
}
