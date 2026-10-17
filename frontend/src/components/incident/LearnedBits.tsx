"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ChevronDown, GraduationCap, Lightbulb, Moon, ShieldAlert } from "lucide-react";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { StatusChip } from "@/components/StatusChip";
import { fmtAgo } from "@/lib/format";
import { templateIds } from "@/lib/templateAlgo";
import type { ActionOption, OptionContractSuggestion, OptionGuideline, OptionLearned, PlanLearned } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * M21 on the plan card: what the team taught Faultline about each option, in the server's own words. Learning only
 * reorders, annotates and suggests: nothing here enables, disables, adds or removes an option, and the approval stays
 * two steps bound by the plan hash (an option against an ACTIVE guideline additionally needs an explicit override).
 */

/** The option's learned annotations: the object /plan sends, or the JSON text a recording kept. */
export function optionLearned(o: Pick<ActionOption, "learned">): OptionLearned | null {
  const l = o.learned;
  if (!l) return null;
  if (typeof l !== "string") return l;
  try {
    const v = JSON.parse(l) as OptionLearned;
    return v && typeof v === "object" ? v : null;
  } catch {
    return null;
  }
}

/** The why lines the server appended to `reason` ("; learned: …", "; against your guideline …"), which the card shows on their own. */
export function stripLearnedLines(reason: string, l: OptionLearned | null): string {
  if (!l) return reason;
  let r = reason;
  for (const line of [l.preference?.line, l.guideline?.line, l.contract_suggestion?.line]) {
    if (line) r = r.split(`; ${line}`).join("");
  }
  return r;
}

/** Learning moved this option: its place differs from its rank without learning (both 1-based). */
export function movedFrom(l: OptionLearned | null, place: number): number | null {
  const r = l?.rank_without_learning;
  return typeof r === "number" && Number.isFinite(r) && r !== place ? r : null;
}

/** "learned … moved up from #2": shown, unfolded, under each option learning moved. */
export function MovedLine({ learned, place }: { learned: OptionLearned; place: number }) {
  const from = movedFrom(learned, place);
  if (from === null) return null;
  const up = place < from;
  const why =
    learned.preference?.line ??
    (learned.guideline?.needs_override
      ? "moved after the other options: it is against an active guideline (below)"
      : "moved by what your team chose recently");
  return (
    <p className="mt-1.5 flex flex-wrap items-start gap-1.5 text-xs text-zinc-300">
      <StatusChip tone="info" icon={up ? ArrowUp : ArrowDown} title={`#${place} now; #${from} without learning`}>
        moved {up ? "up" : "down"} from #{from}
      </StatusChip>
      <span className="min-w-0 flex-1 break-words">{why}</span>
    </p>
  );
}

/** The preference line of an option learning did not move (kept in the option's "Why and details"). */
export function PreferenceLine({ learned }: { learned: OptionLearned }) {
  if (!learned.preference?.line) return null;
  return (
    <p className="flex flex-wrap items-start gap-1.5 text-xs break-words text-zinc-300">
      <StatusChip tone="na" icon={GraduationCap}>
        learned
      </StatusChip>
      <span className="min-w-0 flex-1">{learned.preference.line}</span>
    </p>
  );
}

function who(g: Pick<OptionGuideline, "by" | "by_name">): string {
  return g.by_name ? `${g.by_name} (${g.by})` : (g.by ?? "someone");
}

/**
 * A guideline on this option's family and kind. ACTIVE: a banner (icon + words, not colour alone) saying approving it
 * needs an explicit override. PROPOSED: a quiet note pointing at where a human promotes or dismisses it.
 */
export function GuidelineBanner({ g, tenant, now }: { g: OptionGuideline; tenant: string; now: number }) {
  const where = (
    <Link
      href={`/memory?tenant=${encodeURIComponent(tenant)}#learned`}
      className="rounded text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
    >
      What Faultline has learned
    </Link>
  );
  const from = (
    <>
      from {who(g)}&apos;s rejection
      {g.incident ? (
        <>
          {" "}on <span className="font-mono">{g.incident}</span>
        </>
      ) : null}
      {g.at !== null ? ` · ${fmtAgo(g.at, now)}` : ""}
    </>
  );
  const others = g.others?.length ? ` · ${g.others.length} more guideline${g.others.length === 1 ? "" : "s"} on this fix kind` : "";
  if (g.needs_override) {
    return (
      <div role="note" aria-label={`Against your guideline ${g.id}`} className="mt-1.5 rounded-lg bg-amber-500/[0.08] px-3 py-2 ring-1 ring-amber-400/45">
        <p className="flex items-start gap-1.5 text-xs text-amber-50">
          <ShieldAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-amber-300" />
          <span className="min-w-0 break-words">
            <strong className="font-semibold">Against your guideline</strong> <span className="font-mono">{g.id}</span>: &ldquo;{g.text}&rdquo;
          </span>
        </p>
        <p className="mt-0.5 pl-5 text-[11px] break-words text-amber-100/85">
          {from}
          {g.decided_by ? ` · promoted by ${g.decided_by}` : ""}
          {others}. Approving it needs an explicit override with a reason; it is never blocked silently.
        </p>
      </div>
    );
  }
  return (
    <p className="mt-1.5 flex items-start gap-1.5 text-[11px] break-words text-zinc-400">
      <Lightbulb aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--fl-subtle)]" />
      <span className="min-w-0">
        <span className="text-zinc-200">Proposed guideline</span> <span className="font-mono">{g.id}</span>: &ldquo;{g.text}&rdquo; ({from}
        {others}). Not active: promote or dismiss it in {where}.
      </span>
    </p>
  );
}

/**
 * "Faultline suggests a standing approval": the same exact fix was approved and verified APPLIED on K incidents of
 * this family. Before this incident's fix is verified it explains (the M19 grant needs a verified fix here, still two
 * steps); `onGrant` (set once it is verified) opens the grant form instead.
 */
export function SuggestionChip({
  s,
  tenant,
  onGrant,
  className,
}: {
  s: OptionContractSuggestion;
  tenant: string;
  onGrant?: (() => void) | null;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const chip =
    "inline-flex min-h-6 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400 " +
    "border-[color-mix(in_oklch,var(--fl-iris)_45%,transparent)] bg-[color-mix(in_oklch,var(--fl-iris)_10%,transparent)] text-violet-200 hover:bg-[color-mix(in_oklch,var(--fl-iris)_18%,transparent)]";
  if (onGrant) {
    return (
      <button type="button" onClick={onGrant} className={cn(chip, className)}>
        <Moon aria-hidden className="size-3.5" /> Faultline suggests a standing approval
      </button>
    );
  }
  return (
    <div className={className}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)} className={chip}>
        <Moon aria-hidden className="size-3.5" /> Faultline suggests a standing approval
        <ChevronDown aria-hidden className={cn("size-3 transition-transform motion-reduce:transition-none", open && "rotate-180")} />
      </button>
      <div id={id} hidden={!open} className="mt-1.5 space-y-1 rounded-lg bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-zinc-300 ring-1 ring-white/[0.06]">
        <p className="break-words">{s.line}</p>
        {s.incidents.length ? (
          <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
            <span className="text-zinc-400">verified on</span>
            {s.incidents.slice(0, 6).map((inc, i) => (
              <span key={inc}>
                <Link
                  href={`/incidents/${encodeURIComponent(inc)}?tenant=${encodeURIComponent(tenant)}`}
                  className="rounded font-mono text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  {inc}
                </Link>
                {i < Math.min(s.incidents.length, 6) - 1 ? "," : ""}
              </span>
            ))}
            {s.incidents.length > 6 ? <span className="text-zinc-400">+{s.incidents.length - 6} more</span> : null}
          </p>
        ) : null}
        <p className="text-zinc-400">
          The grant form (two steps, bound to a contract hash) opens on this card once this fix is approved and verified{" "}
          <span className="font-mono text-zinc-300">APPLIED</span> here. Nothing is granted by this suggestion.
        </p>
      </div>
    </div>
  );
}

/** One line on what learning did to this plan (the plan's `learned` summary), with the recorded learned_preferences read. */
export function LearnedPlanNote({
  learned,
  query,
}: {
  learned: PlanLearned | null | undefined;
  query: { template: string | null; onOpen: () => void } | null;
}) {
  if (!learned?.consulted) return null;
  const n = learned.n_family ?? 0;
  const fam = learned.family;
  const min = learned.pref_min_n;
  const moved = learned.moved?.length ?? 0;
  const flagged = learned.flagged?.length ?? 0;
  const suggested = learned.suggested?.length ?? 0;
  const head = !fam
    ? "nothing learned for this incident's family yet"
    : learned.applies
      ? `${n} recorded choice${n === 1 ? "" : "s"} by your team for ${fam} are blended into the order`
      : `${n} recorded choice${n === 1 ? "" : "s"} for ${fam}${min ? `, fewer than ${min}` : ""}: the order is unchanged`;
  const tail = [
    moved ? `${moved} option${moved === 1 ? "" : "s"} moved` : null,
    flagged ? `${flagged} against an active guideline` : null,
    suggested ? "a standing approval is suggested" : null,
  ].filter(Boolean);
  const ids = templateIds(query?.template);
  return (
    <p className="mb-3 flex flex-wrap items-start gap-1.5 text-xs text-zinc-400">
      <GraduationCap aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--fl-subtle)]" />
      <span className="min-w-0 flex-1">
        <span className="font-semibold text-zinc-100">Learned:</span> {head}
        {tail.length ? `; ${tail.join(", ")}` : ""}. It only reorders and annotates; the gate and the two-step approval are unchanged.
      </span>
      {query && ids.length ? (
        <button
          type="button"
          onClick={query.onOpen}
          className={QUERY_ID_CLS}
          aria-label={`${ids[0]}: open the Cypher panel for what the team taught Faultline about this family`}
        >
          {ids.length > 1 ? `${ids[0]} +${ids.length - 1}` : ids[0]}
        </button>
      ) : null}
    </p>
  );
}

/**
 * The explicit override an ACTIVE guideline asks for before approving (step 2 still binds the plan hash): it names
 * the guideline, needs a deliberate tick and a reason, and both are sent with the approval and recorded in the graph.
 */
export function OverrideFields({
  guideline,
  refusedByServer,
  checked,
  reason,
  onChecked,
  onReason,
  disabled,
  hintId: hintIdProp,
}: {
  guideline: { id: string; text: string | null; promotedBy: string | null };
  /** The server refused the approval for this guideline (it became active after the plan was made). */
  refusedByServer: boolean;
  checked: boolean;
  reason: string;
  onChecked: (v: boolean) => void;
  onReason: (v: string) => void;
  disabled?: boolean;
  /** Id for the status line (the Approve button points its aria-describedby at it). */
  hintId?: string;
}) {
  const titleId = useId();
  const boxId = useId();
  const reasonId = useId();
  const ownHintId = useId();
  const hintId = hintIdProp ?? ownHintId;
  const short = reason.length > 0 && reason.trim().length < 3;
  return (
    <div role="group" aria-labelledby={titleId} className="space-y-1.5 rounded-md border border-amber-400/60 bg-amber-500/[0.07] p-2">
      <p id={titleId} className="flex items-center gap-1.5 text-[12px] font-semibold text-amber-100">
        <ShieldAlert aria-hidden className="size-3.5 text-amber-300" /> Override guideline <span className="font-mono">{guideline.id}</span>
      </p>
      <p className="text-[11px] leading-relaxed break-words text-amber-50/90">
        {refusedByServer ? "The server refused the approval: this option is against an active guideline. " : "This option is against an active guideline. "}
        {guideline.text ? <>&ldquo;{guideline.text}&rdquo;</> : null}
        {guideline.promotedBy ? ` (promoted by ${guideline.promotedBy})` : ""}. Approving it anyway needs an explicit override: the
        guideline and your reason are sent with the approval, and recorded as an override learning event when the approval is
        learned.
      </p>
      <label htmlFor={boxId} className="flex items-start gap-2 text-xs text-zinc-100">
        <input
          id={boxId}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChecked(e.target.checked)}
          className="mt-0.5 size-4 shrink-0 accent-amber-400 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        />
        <span>
          I am overriding guideline <span className="font-mono">{guideline.id}</span> for this incident
        </span>
      </label>
      <label htmlFor={reasonId} className="block text-[11px] text-zinc-300">
        Override reason (required, 3 to 300 characters)
      </label>
      <textarea
        id={reasonId}
        value={reason}
        onChange={(e) => onReason(e.target.value)}
        rows={2}
        maxLength={300}
        disabled={disabled}
        aria-describedby={hintId}
        aria-invalid={short ? true : undefined}
        placeholder="e.g. the KPI is already down; restoring checkout matters more"
        className="w-full rounded-md border border-zinc-600 bg-zinc-950 p-2 text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      />
      <p id={hintId} className="text-[11px] text-zinc-300">
        {checked && reason.trim().length >= 3
          ? "Override ready: it is sent with this approval only."
          : "Approve stays disabled until you tick the override and give a reason."}
      </p>
    </div>
  );
}
