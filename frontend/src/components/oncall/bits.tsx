"use client";

import {
  BellRing,
  ChevronsUp,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  Clock,
  MailX,
  Moon,
  OctagonAlert,
  Siren,
  type LucideIcon,
} from "lucide-react";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { StatusChip } from "@/components/StatusChip";
import type { Tone } from "@/lib/gate";
import { CHANNEL_TEXT, oncallErrorText, PAGE_STATUS_TEXT, type PageStatus, type QueryRef } from "@/lib/oncall";
import { tenantGraph } from "@/lib/tenant";

const PAGE_STATUS: Record<PageStatus, { tone: Tone; icon: LucideIcon }> = {
  sent: { tone: "warn", icon: BellRing },
  delivery_failed: { tone: "fail", icon: MailX },
  acked: { tone: "pass", icon: CircleCheck },
  escalated: { tone: "warn", icon: ChevronsUp },
  resolved: { tone: "pass", icon: CircleCheck },
  superseded: { tone: "na", icon: CircleMinus },
};

/** A page's status: colour, icon and words (never colour alone). Unknown statuses are shown as sent by the server. */
export function PageStatusChip({ status, kind, className }: { status: string | null; kind?: string | null; className?: string }) {
  if (kind === "contract_notice" && status !== "delivery_failed") {
    return (
      <StatusChip tone="info" icon={Moon} className={className} title="Informational: a contract handled it; nobody was woken">
        FYI · no wake
      </StatusChip>
    );
  }
  const s = status && status in PAGE_STATUS ? PAGE_STATUS[status as PageStatus] : null;
  if (!s) {
    return (
      <StatusChip tone="na" icon={CircleDashed} className={className}>
        {status ?? "status not recorded"}
      </StatusChip>
    );
  }
  return (
    <StatusChip tone={s.tone} icon={s.icon} className={className}>
      {PAGE_STATUS_TEXT[status as PageStatus]}
    </StatusChip>
  );
}

export function UrgencyChip({ urgency }: { urgency: string | null }) {
  if (!urgency) return null;
  return urgency === "urgent" ? (
    <StatusChip tone="fail" icon={Siren}>
      urgent
    </StatusChip>
  ) : (
    <StatusChip tone="info" icon={Clock}>
      {urgency}
    </StatusChip>
  );
}

/** "in-app + Telegram" from a channel or the server's comma-joined list ("in_app,telegram"). */
export function channelText(c: string | null | string[]): string {
  const parts = (Array.isArray(c) ? c : (c ?? "").split(",")).map((x) => x.trim()).filter(Boolean);
  if (!parts.length) return "channel not recorded";
  return parts.map((x) => CHANNEL_TEXT[x.toLowerCase()] ?? x).join(" + ");
}

/** A failed read, said plainly (role=alert). Endpoint missing, API down and HTTP errors each get their own words. */
export function PanelError({ error, what, stale }: { error: unknown; what: string; stale?: boolean }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-100 ring-1 ring-red-500/40">
      <OctagonAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
      <span>
        {oncallErrorText(error, what)}
        {stale ? " Showing the last answer the server gave; it may be out of date." : ""}
      </span>
    </p>
  );
}

/** Opens the Cypher panel for an on-call read (template + the params the server reported, re-runnable read-only). */
export function useOpenQuery(tenant: string) {
  const panel = useCypherPanel();
  return (ref: QueryRef | null, title: string, origin: string) => {
    if (!ref?.template) return;
    panel.open({
      template: ref.template,
      title,
      origin: `${origin} (${tenantGraph(tenant)})`,
      recordedParams: ref.params,
      recorded: ref.ms !== null ? { ms: ref.ms, rows: null } : null,
      ctx: {},
      tenant,
    });
  };
}

/** Initials for a person's avatar dot (decorative; the name is always written next to it). */
export function initials(name: string | null | undefined, id: string): string {
  const src = (name ?? id).replace(/[^A-Za-z\s-]/g, " ").trim();
  const parts = src.split(/[\s-]+/).filter(Boolean);
  const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? id).slice(0, 2);
  return s.toUpperCase();
}

export function Avatar({ name, id, className }: { name: string | null | undefined; id: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-[linear-gradient(135deg,color-mix(in_oklch,var(--fl-iris)_45%,transparent),color-mix(in_oklch,var(--fl-ember)_30%,transparent))] text-[11px] font-semibold text-zinc-50 ring-1 ring-white/10 " +
        (className ?? "")
      }
    >
      {initials(name, id)}
    </span>
  );
}
