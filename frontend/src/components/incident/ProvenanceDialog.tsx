"use client";

import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { CircleAlert, GitFork, LoaderCircle, RotateCw, X } from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { api, ApiError, errorText } from "@/lib/api";
import { STATIC_SITE } from "@/lib/site";
import { useTenant } from "@/lib/tenant";
import type { IncidentView, ProvenanceNode, ProvenanceResponse } from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { cn } from "@/lib/utils";
import { ProvenanceGraph, ProvenanceHeader } from "./ProvenanceGraph";
import type { IncidentActions } from "./useIncidentActions";

/** The template behind the view; the payload names it too (and wins once loaded). */
const PROV_TEMPLATE = "Q-PROV-1";
const EASE = [0.22, 1, 0.36, 1] as const;

/** True when the incident has a confirmed cause: only then is there a verdict to explain. */
export function hasConfirmedCause(view: IncidentView): boolean {
  return !!view.report?.cause_id && view.hypotheses.some((h) => h.status === "confirmed");
}

/**
 * Entry point in the verdict area: "Why do you believe this?" opens the provenance graph in a sheet. Rendered only
 * for a confirmed cause. The static replay build has no API, and a replay is a recording rather than the live graph,
 * so there it is shown disabled ("live only") instead of querying anything.
 */
export function WhyBelieveButton({
  view,
  mode,
  actions,
}: {
  view: IncidentView;
  mode: "live" | "replay";
  actions: IncidentActions;
}) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => {
    setOpen(false);
    btn.current?.focus();
  }, []);
  if (!hasConfirmedCause(view)) return null;
  const liveOnly = STATIC_SITE || mode !== "live";
  const cls =
    "inline-flex min-h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400";
  if (liveOnly) {
    return (
      <button
        type="button"
        disabled
        title="The provenance graph is a live FalkorDB query (Q-PROV-1); a recording has no API to ask."
        className={cn(cls, "cursor-not-allowed border-white/[0.08] text-zinc-400")}
      >
        <GitFork aria-hidden className="size-3.5" />
        Why do you believe this?
        <span className="rounded border border-white/[0.12] px-1 font-mono text-[10px] text-zinc-300">live only</span>
      </button>
    );
  }
  return (
    <>
      <button
        ref={btn}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className={cn(cls, "border-white/[0.12] bg-white/[0.03] text-zinc-100 hover:border-white/[0.22] hover:bg-white/[0.06]")}
      >
        <GitFork aria-hidden className="size-3.5 text-zinc-400" />
        Why do you believe this?
      </button>
      <ProvenanceSheet open={open} onClose={close} view={view} actions={actions} />
    </>
  );
}

const subscribeNothing = () => () => {};

type Loaded =
  | { key: string; data: ProvenanceResponse; error?: undefined }
  | { key: string; data?: undefined; error: { text: string; status: number | null } };

/**
 * Full-screen sheet on phones, a centred panel on wider screens. A modal dialog of its own (not Base UI): the Cypher
 * panel (a Base UI dialog) opens on top of it from a card and returns focus to that card, so this one only traps Tab
 * inside itself, closes on Esc from within, and hands focus back to its opener.
 */
export function ProvenanceSheet({
  open,
  onClose,
  view,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  view: IncidentView;
  actions: IncidentActions;
}) {
  const mounted = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const reduced = useReducedMotion();
  if (!mounted) return null;
  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          key="provenance"
          className="fixed inset-0 z-40"
          initial={reduced ? { opacity: 1 } : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduced ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0 }}
          transition={reduced ? { duration: 0 } : { duration: 0.18, ease: EASE }}
        >
          <SheetBody onClose={onClose} view={view} actions={actions} reduced={reduced} />
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function SheetBody({
  onClose,
  view,
  actions,
  reduced,
}: {
  onClose: () => void;
  view: IncidentView;
  actions: IncidentActions;
  reduced: boolean;
}) {
  const tenant = useTenant();
  const panel = useCypherPanel();
  const titleId = useId();
  const descId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const incident = view.incident.id;
  const [nonce, setNonce] = useState(0);
  const reqKey = `${tenant}:${incident}:${nonce}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .provenance(incident, tenant, ctrl.signal)
      .then((data) => setLoaded({ key: reqKey, data }))
      .catch((e) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setLoaded({
          key: reqKey,
          error: { text: e instanceof ApiError ? e.detail : errorText(e), status: e instanceof ApiError ? e.status : null },
        });
      });
    return () => ctrl.abort();
  }, [incident, tenant, reqKey]);
  const cur = loaded?.key === reqKey ? loaded : null;
  const data = cur?.data ?? null;

  // focus the dialog on open; lock the page behind it (phones scroll the document, desktop scrolls <main>)
  useEffect(() => {
    ref.current?.focus();
    const root = document.documentElement;
    const prev = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = prev;
    };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
      (el) => !el.closest("[hidden], [inert]") && !(el.closest("details:not([open])") && el.tagName !== "SUMMARY"),
    );
    if (!items.length) {
      e.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const at = document.activeElement;
    if (e.shiftKey && (at === first || at === ref.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && at === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const openQuery = () =>
    panel.open({
      template: data?.template ?? PROV_TEMPLATE,
      title: `why ${incident} is believed`,
      origin: "the provenance graph (Why do you believe this?)",
      detail: data
        ? "The query GET /api/incidents/{inc}/provenance ran; its params are the ones the API used."
        : null,
      recordedParams: data?.params ?? null,
      ctx: { incident, run: view.run.run },
      incident,
      tenant,
    });

  const producedBy = (callId: string): string | null =>
    data?.edges.find((e) => e.rel === "PRODUCED_EVIDENCE" && e.source === callId)?.target ?? null;

  // A call is a ToolCall node: open the recorded row (with its params) when the view has it, else the call as
  // Q-PROV-1 returned it (the panel then derives params and labels them so).
  const openCall = (n: ProvenanceNode) =>
    actions.openToolCall(
      view.tool_calls.find((t) => t.id === n.id) ?? {
        id: n.id,
        tool: n.label,
        template: n.template ?? null,
        ms: n.ms ?? Number.NaN,
        rows: Number.NaN,
        at: Number.NaN,
        evidence_id: producedBy(n.id),
        kind: null,
        summary: null,
      },
    );

  const openEvidence = (n: ProvenanceNode) => {
    if (actions.evidenceById.has(n.id) || view.tool_calls.some((t) => t.evidence_id === n.id)) {
      actions.openEvidence(n.id);
      return;
    }
    panel.open({
      template: n.template ?? null,
      title: `${n.id} · ${n.label}`,
      origin: `evidence ${n.id} (supports the verdict, read with ${data?.template ?? PROV_TEMPLATE})`,
      detail: n.summary ?? null,
      ctx: { incident, run: view.run.run, onset: view.incident.onset_at, targets: view.incident.targets },
      incident,
      tenant,
    });
  };

  const counts = data
    ? (() => {
        const n = (k: string) => data.nodes.filter((x) => x.kind === k).length;
        return `${n("evidence")} evidence · ${n("call")} calls · ${n("agent")} agents`;
      })()
    : null;

  return (
    <>
      <div aria-hidden className="absolute inset-0 bg-black/70" onClick={onClose} />
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        initial={reduced ? { opacity: 1, y: 0 } : { opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={reduced ? { duration: 0 } : { duration: 0.28, ease: EASE }}
        className="absolute inset-0 flex flex-col overflow-hidden bg-[var(--fl-surface)] text-zinc-100 shadow-2xl outline-none sm:inset-6 sm:mx-auto sm:max-w-6xl sm:rounded-2xl sm:border sm:border-[var(--fl-line)]"
      >
        <div className="flex items-start gap-3 border-b border-[var(--fl-line)] px-4 py-3 sm:px-5">
          <div className="min-w-0 flex-1">
            <p className="mb-0.5 font-mono text-[11px] text-zinc-400">{incident}</p>
            <ProvenanceHeader
              titleId={titleId}
              descId={descId}
              template={data?.template ?? PROV_TEMPLATE}
              onOpenQuery={openQuery}
            />
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close: why do you believe this"
            className="rounded-md p-1.5 text-zinc-300 outline-none transition-colors hover:bg-white/[0.06] hover:text-zinc-50 focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            <X aria-hidden className="size-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
          <p role="status" aria-live="polite" className="sr-only">
            {cur === null ? "Loading the provenance graph" : data ? `Provenance graph loaded: ${counts}` : "Provenance graph unavailable"}
          </p>
          {cur === null ? (
            <p className="flex items-center gap-2 text-sm text-zinc-300">
              <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" />
              Reading the verdict&apos;s provenance from FalkorDB…
            </p>
          ) : cur.error ? (
            <ErrorBox error={cur.error} onRetry={() => setNonce((n) => n + 1)} />
          ) : (
            <>
              {counts ? <p className="mb-3 font-mono text-[11px] text-zinc-400">{counts}</p> : null}
              <ProvenanceGraph
                data={cur.data}
                roster={view.crew?.roster ?? []}
                onOpenCall={openCall}
                onOpenEvidence={openEvidence}
              />
            </>
          )}
        </div>
      </motion.div>
    </>
  );
}

function ErrorBox({ error, onRetry }: { error: { text: string; status: number | null }; onRetry: () => void }) {
  const down = error.status === null || error.status === 503;
  return (
    <div role="alert" className="flex flex-wrap items-start gap-2 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
      <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
      <p className="min-w-0 flex-1">
        <strong className="font-semibold">{down ? "Graph unavailable:" : "Provenance query failed:"}</strong>{" "}
        {error.text}
        {error.status ? ` (HTTP ${error.status})` : ""}. Nothing is shown in its place.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1 rounded-md border border-red-300/40 px-2 py-0.5 text-xs text-red-50 outline-none hover:bg-red-500/15 focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        <RotateCw aria-hidden className="size-3.5" />
        Retry
      </button>
    </div>
  );
}
