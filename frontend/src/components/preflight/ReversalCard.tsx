"use client";

import { useId } from "react";
import { ExternalLink, FileText, History, Info, Scale } from "lucide-react";
import { fmtDate, fmtValue } from "@/lib/format";
import type { PreflightReversal } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

const isWeb = (url: string | null): url is string => !!url && /^https?:\/\//.test(url);

/** A decision id chip; a link only when the decision's url is a web URL (a repository path is shown as a title). */
export function DecisionChip({ id, url }: { id: string; url: string | null }) {
  const inner = (
    <>
      <Scale aria-hidden className="size-3" />
      {id}
    </>
  );
  const cls =
    "inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-400 px-1.5 font-mono text-[11px] font-bold text-zinc-950";
  if (isWeb(url)) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className={cn(cls, "underline outline-none focus-visible:ring-2 focus-visible:ring-amber-200")}
      >
        {inner}
        <ExternalLink aria-hidden className="size-3" />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    );
  }
  return (
    <span className={cls} title={url ? `document: ${url} (repository path, not a web link)` : undefined}>
      {inner}
    </span>
  );
}

/**
 * Reversal guard (advisory): the PR puts back a value the organisation decided once and later reversed. One card
 * per reversal, above the risk terms: what was reversed, the decision in force (`head`), when, and the evidence for
 * the reversal. It never changes the verdict or the risk, and says so.
 */
export function ReversalCards({ reversals }: { reversals: PreflightReversal[] }) {
  if (!reversals.length) return null;
  return (
    <ul aria-label="Reversed decisions this PR reinstates" className="mt-3 space-y-2">
      {reversals.map((r) => (
        <li key={`${r.reversed}:${r.head}:${r.rule_key ?? ""}`}>
          <ReversalCard r={r} />
        </li>
      ))}
    </ul>
  );
}

function ReversalCard({ r }: { r: PreflightReversal }) {
  const hid = useId();
  return (
    <article aria-labelledby={hid} className="rounded-xl border border-amber-400/50 bg-amber-500/[0.06] p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <History aria-hidden className="size-4 shrink-0 text-amber-300" />
        <h3 id={hid} className="text-sm font-semibold text-amber-50">
          Reinstates a reversed decision
        </h3>
        <StatusChip tone="info" icon={Info} className="sm:ml-auto">
          advisory: does not change the verdict
        </StatusChip>
      </div>

      <p className="mt-2 text-sm leading-relaxed break-words text-zinc-100">
        <span className="font-mono font-semibold text-zinc-50 line-through decoration-amber-300/70">{r.reversed}</span>
        {r.reversed_title ? <> ({r.reversed_title})</> : null} was replaced by{" "}
        <span className="font-mono font-semibold text-amber-100">{r.head}</span>
        {r.head_title ? <> ({r.head_title})</> : null}
        {r.head_decided_at !== null && Number.isFinite(r.head_decided_at) ? (
          <>
            {" "}
            on <time dateTime={new Date(r.head_decided_at).toISOString()}>{fmtDate(r.head_decided_at)}</time>
          </>
        ) : null}
        .
      </p>

      {r.rule_key ? (
        <p className="mt-1 text-xs text-zinc-300">
          This PR sets <span className="font-mono text-zinc-100 [overflow-wrap:anywhere]">{r.rule_key}</span> back to{" "}
          <span className="font-mono font-semibold text-amber-100">{fmtValue(r.actual)}</span>
          {r.about ? (
            <>
              {" "}
              on <span className="font-mono text-zinc-100">{r.about}</span>
            </>
          ) : null}
          .
        </p>
      ) : null}

      <div className="mt-2">
        <h4 className="text-[11px] font-semibold tracking-wide text-zinc-300 uppercase">Because</h4>
        {r.because.length ? (
          <ul aria-label={`Evidence for reversing ${r.reversed}`} className="mt-1 space-y-1 text-xs">
            {r.because.map((b) => (
              <li key={b.id} className="flex flex-wrap items-start gap-1.5">
                <FileText aria-hidden className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
                <span className="min-w-0 flex-1 break-words text-zinc-200">{b.title ?? b.id}</span>
                <span className="rounded border border-white/[0.1] px-1 font-mono text-[10px] text-zinc-300 [overflow-wrap:anywhere]">
                  {b.id}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-zinc-300">No evidence for the reversal is recorded.</p>
        )}
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-zinc-300">
        <span>Decision in force</span>
        <DecisionChip id={r.head} url={r.head_url} />
        {r.head_url && !isWeb(r.head_url) ? (
          <span className="font-mono text-[11px] break-all text-zinc-400">{r.head_url}</span>
        ) : null}
      </p>
      <p className="mt-1.5 text-[11px] text-zinc-400">
        Advisory only: the verdict and the risk score are unchanged by it.
      </p>
    </article>
  );
}
