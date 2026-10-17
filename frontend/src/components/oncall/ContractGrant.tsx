"use client";

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Copy, FileSignature, LoaderCircle, Moon, OctagonAlert, RotateCcw } from "lucide-react";
import { ApiError, errorText, FOREIGN_RUN_TEXT, isForeignRun } from "@/lib/api";
import { fmtWhen, oncallApi, type Contract, type ContractQuote } from "@/lib/oncall";
import { useTenant } from "@/lib/tenant";
import type { OptionContractSuggestion, WhoFixesRow } from "@/lib/types";
import { SuggestionChip } from "@/components/incident/LearnedBits";
import { cn } from "@/lib/utils";
import { UsesMeter } from "./ContractsCard";

const KIND_TEXT: Record<string, string> = {
  flip_flag: "feature flag",
  rollback_deploy: "rollback",
  open_issue: "issue",
  data_repair: "data repair",
};

const MAX_USES = { min: 1, max: 10, start: 3 };
const DAYS = { min: 1, max: 30, start: 7 };

function clampInt(v: string, lo: number, hi: number): number | null {
  if (!/^\d{1,3}$/.test(v.trim())) return null;
  const n = Number(v);
  return n >= lo && n <= hi ? n : null;
}

function StepHeading({ n, title, done }: { n: number; title: string; done: boolean }) {
  return (
    <h4 className="flex items-center gap-2 text-[13px] font-medium text-zinc-100">
      <span
        className={cn(
          "inline-flex size-5 items-center justify-center rounded-full border text-[11px]",
          done ? "border-emerald-400 bg-emerald-500/20 text-emerald-200" : "border-sky-400 text-sky-200",
        )}
      >
        {done ? <Check aria-hidden className="size-3" /> : n}
      </span>
      Step {n} of 2: {title}
      {done ? <span className="font-normal text-emerald-300">(done)</span> : null}
    </h4>
  );
}

/**
 * "Grant a contract for repeats", offered once the action is verified APPLIED. Two steps like the action itself:
 * choosing a scope (max uses, days) is not approving it. Step 1 POSTs {step: "choose", scope} and shows the exact
 * contract the server will record and its hash; step 2 POSTs {step: "approve", hash, approver} with the approver key.
 * The server checks the approver is on call for, or owns, an impacted component; a stale hash is refused (409).
 */
export function ContractGrant({
  incidentId,
  actionId = null,
  actionKind,
  candidates,
  suggestion = null,
  family = null,
}: {
  incidentId: string;
  /** The verified APPLIED action the contract repeats (sent with the choose step so the offer binds to it). */
  actionId?: string | null;
  actionKind: string;
  /** Who-fixes ranking: the top person pre-fills the approver. */
  candidates: WhoFixesRow[];
  /**
   * M21: Faultline suggests a standing approval because the same exact fix (family, action, parameters) was approved
   * and verified APPLIED on enough incidents (learn.contract_suggest_k). It only opens this form: still two steps.
   */
  suggestion?: OptionContractSuggestion | null;
  family?: string | null;
}) {
  const tenant = useTenant();
  const usesId = useId();
  const daysId = useId();
  const approverId = useId();
  const keyId = useId();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [uses, setUses] = useState(String(MAX_USES.start));
  const [days, setDays] = useState(String(DAYS.start));
  const [quote, setQuote] = useState<ContractQuote | null>(null);
  const [approver, setApprover] = useState(candidates[0]?.person ?? "");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"choose" | "approve" | null>(null);
  const [granted, setGranted] = useState<Contract | null>(null);
  const [err, setErr] = useState<{ op: "choose" | "approve"; status: number | null; text: string; foreign: boolean } | null>(null);
  const [copied, setCopied] = useState(false);
  const usesRef = useRef<HTMLInputElement>(null);

  const maxUses = clampInt(uses, MAX_USES.min, MAX_USES.max);
  const nDays = clampInt(days, DAYS.min, DAYS.max);

  const fail = (op: "choose" | "approve", e: unknown) =>
    setErr({ op, status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e), foreign: isForeignRun(e) });

  const choose = async () => {
    if (maxUses === null || nDays === null) return;
    setBusy("choose");
    setErr(null);
    setQuote(null);
    try {
      setQuote(await oncallApi.contractChoose(incidentId, { max_uses: maxUses, days: nDays }, tenant, actionId));
    } catch (e) {
      fail("choose", e);
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (!quote || !approver.trim()) return;
    setBusy("approve");
    setErr(null);
    try {
      const c = await oncallApi.contractApprove(incidentId, { hash: quote.hash, approver: approver.trim() }, key.trim() || undefined, tenant);
      if (!c) throw new ApiError("the server answered without a contract id: nothing is shown as granted", 200, "contract");
      setGranted(c);
    } catch (e) {
      fail("approve", e);
    } finally {
      setBusy(null);
    }
  };

  if (granted) {
    return (
      <div role="status" className="space-y-1.5 rounded-xl bg-[color-mix(in_oklch,var(--fl-iris)_8%,transparent)] p-3 ring-1 ring-[color-mix(in_oklch,var(--fl-iris)_40%,transparent)]">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
          <Moon aria-hidden className="size-4 text-[var(--fl-iris)]" /> Contract <span className="font-mono">{granted.id}</span> granted
        </p>
        <p className="text-xs leading-relaxed text-zinc-300">
          The next repeat{granted.family ? (
            <>
              {" "}of family <span className="font-mono text-zinc-100">{granted.family}</span>
            </>
          ) : null}
          , fixed by the same {KIND_TEXT[granted.actionKind ?? actionKind] ?? granted.actionKind ?? actionKind} with the same parameters, runs
          without paging anyone{granted.expiresAt !== null ? `, until ${fmtWhen(granted.expiresAt)}` : ""}. The gate still has to
          confirm the cause and the fix still has to verify; anything else pages a human at once.
        </p>
        <p className="flex flex-wrap items-center gap-3">
          <UsesMeter uses={granted.uses ?? 0} max={granted.maxUses} />
          <Link
            href={`/oncall?tenant=${encodeURIComponent(tenant)}`}
            className="inline-flex items-center gap-1 rounded text-xs text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            See it under Contracts <ArrowUpRight aria-hidden className="size-3.5" />
          </Link>
        </p>
      </div>
    );
  }

  const openForm = () => {
    setOpen(true);
    requestAnimationFrame(() => usesRef.current?.focus());
  };

  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-white/[0.02] px-3 py-2.5 ring-1 ring-white/[0.06]">
        <Moon aria-hidden className="size-4 shrink-0 text-[var(--fl-iris)]" />
        {suggestion ? (
          <div className="min-w-0 flex-1 space-y-1">
            <SuggestionChip s={suggestion} tenant={tenant} onGrant={openForm} />
            <p className="text-xs text-zinc-300">
              The same exact fix was approved and verified <span className="font-mono">APPLIED</span> on {suggestion.n} incident
              {suggestion.n === 1 ? "" : "s"}
              {family ? (
                <>
                  {" "}of <span className="font-mono text-zinc-100">{family}</span>
                </>
              ) : null}
              {suggestion.incidents.length ? ` (${suggestion.incidents.slice(0, 3).join(", ")}${suggestion.incidents.length > 3 ? ", …" : ""})` : ""}.
              Let the next repeat be fixed the same way without waking anyone, under limits you set.
            </p>
          </div>
        ) : (
          <p className="min-w-0 flex-1 text-xs text-zinc-300">
            <span className="font-medium text-zinc-100">Same fault again?</span> Let the next repeat be fixed the same way without
            waking anyone, under limits you set.
          </p>
        )}
        <button
          type="button"
          onClick={openForm}
          className="inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13px] text-zinc-100 ring-1 ring-white/15 outline-none hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          <FileSignature aria-hidden className="size-4" /> Grant a contract for repeats…
        </button>
      </div>
    );
  }

  const field = "h-8 rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400";
  return (
    <section aria-labelledby={`${usesId}-h`} className="space-y-3 rounded-xl bg-white/[0.02] p-3 ring-1 ring-white/[0.08]">
      <h3 id={`${usesId}-h`} className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
        <FileSignature aria-hidden className="size-4 text-[var(--fl-iris)]" /> Grant a contract for repeats
      </h3>
      <p className="text-xs leading-relaxed text-zinc-400">
        A standing approval for this incident family and this exact action ({KIND_TEXT[actionKind] ?? actionKind}, same
        parameters). It never skips the gate; verification still runs, and a fix that does not verify pages a human at once.
      </p>

      <StepHeading n={1} title="Choose the scope" done={!!quote} />
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy) void choose();
        }}
      >
        <label htmlFor={usesId} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
          Max uses ({MAX_USES.min} to {MAX_USES.max})
          <input
            id={usesId}
            ref={usesRef}
            type="number"
            inputMode="numeric"
            min={MAX_USES.min}
            max={MAX_USES.max}
            value={uses}
            onChange={(e) => {
              setUses(e.target.value);
              setQuote(null);
            }}
            aria-invalid={maxUses === null ? true : undefined}
            className={cn(field, "w-24")}
          />
        </label>
        <label htmlFor={daysId} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
          For how many days ({DAYS.min} to {DAYS.max})
          <input
            id={daysId}
            type="number"
            inputMode="numeric"
            min={DAYS.min}
            max={DAYS.max}
            value={days}
            onChange={(e) => {
              setDays(e.target.value);
              setQuote(null);
            }}
            aria-invalid={nDays === null ? true : undefined}
            className={cn(field, "w-24")}
          />
        </label>
        <button
          type="submit"
          disabled={!!busy || maxUses === null || nDays === null}
          className="inline-flex h-8 items-center gap-1.5 rounded-full bg-zinc-50 px-3.5 text-[13px] font-medium text-zinc-950 outline-none hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy === "choose" ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : null}
          {quote ? "Choose this scope again" : "Choose this scope"}
        </button>
      </form>

      {quote ? (
        <>
          <section aria-label="Exact contract" className="space-y-1.5 rounded-lg border border-sky-500/40 bg-zinc-950/60 p-2.5">
            <h4 className="text-xs font-semibold text-sky-200">Exact contract the server will record</h4>
            {quote.quote ? <p className="text-xs leading-relaxed text-zinc-200">{quote.quote}</p> : null}
            <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-zinc-400">family</dt>
              <dd className="font-mono break-all text-zinc-100">{quote.family ?? "–"}</dd>
              <dt className="text-zinc-400">action</dt>
              <dd className="font-mono text-zinc-100">{quote.actionKind ?? "–"}</dd>
              <dt className="text-zinc-400">params hash</dt>
              <dd className="font-mono break-all text-zinc-100" title={quote.paramsHash ?? undefined}>
                {quote.paramsHash ? quote.paramsHash.slice(0, 12) : "–"}
              </dd>
              <dt className="text-zinc-400">max uses</dt>
              <dd className="font-mono text-zinc-100">{quote.maxUses ?? "–"}</dd>
              <dt className="text-zinc-400">expires</dt>
              <dd className="text-zinc-100">
                {quote.expiresAt !== null ? fmtWhen(quote.expiresAt) : quote.days !== null ? `${quote.days} days after approval` : "–"}
              </dd>
              {quote.offerExpiresAt !== null ? (
                <>
                  <dt className="text-zinc-400">approve before</dt>
                  <dd className="text-zinc-100">{fmtWhen(quote.offerExpiresAt)} (the offer lapses after that)</dd>
                </>
              ) : null}
              <dt className="text-zinc-400">contract hash</dt>
              <dd className="flex flex-wrap items-center gap-2">
                <code className="rounded bg-zinc-800 px-1 font-mono text-[12px] font-semibold text-zinc-50" title={quote.hash}>
                  {quote.hash.slice(0, 12)}
                </code>
                <button
                  type="button"
                  onClick={() => {
                    void navigator.clipboard?.writeText(quote.hash).then(
                      () => setCopied(true),
                      () => setCopied(false),
                    );
                  }}
                  aria-label="Copy contract hash"
                  className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-zinc-300 ring-1 ring-white/10 outline-none hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </dd>
            </dl>
          </section>

          <StepHeading n={2} title="Approve this exact contract" done={false} />
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!busy && approver.trim()) void approve();
            }}
          >
            <div className="flex flex-wrap items-end gap-3">
              <label htmlFor={approverId} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
                Approver (on call for, or owning, an impacted component)
                <input
                  id={approverId}
                  value={approver}
                  onChange={(e) => setApprover(e.target.value)}
                  list={candidates.length ? listId : undefined}
                  required
                  maxLength={60}
                  autoComplete="off"
                  spellCheck={false}
                  className={cn(field, "w-44")}
                />
              </label>
              {candidates.length ? (
                <datalist id={listId}>
                  {candidates.map((c) => (
                    <option key={c.person} value={c.person}>
                      {c.name ? `${c.name} (${c.person})` : c.person}
                    </option>
                  ))}
                </datalist>
              ) : null}
              <label htmlFor={keyId} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
                Approver key (sent with this grant only, never stored)
                <input id={keyId} type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" className={cn(field, "w-56 max-w-full text-xs")} />
              </label>
              <button
                type="submit"
                disabled={!!busy || !approver.trim()}
                className="inline-flex h-9 items-center gap-1.5 rounded-full bg-violet-700 px-4 text-sm font-medium text-white outline-none hover:bg-violet-800 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy === "approve" ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : <FileSignature aria-hidden className="size-4" />}
                Grant this exact contract
              </button>
            </div>
            <p className="text-[11px] text-zinc-400">
              Bound to contract hash <span className="font-mono text-zinc-300">{quote.hash.slice(0, 12)}</span>: if the scope or the
              incident changes, the server refuses it (409).
            </p>
          </form>
        </>
      ) : null}

      {err ? (
        <div role="alert" className="flex flex-wrap items-start gap-2 rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100">
          <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
          <p className="min-w-0 flex-1">
            {err.foreign ? (
              <>
                <strong className="font-semibold">Not your run.</strong> {FOREIGN_RUN_TEXT}
              </>
            ) : err.status === 409 && err.op === "choose" ? (
              <>
                <strong className="font-semibold">Refused:</strong> {err.text} (HTTP 409).
              </>
            ) : err.status === 409 ? (
              <>
                <strong className="font-semibold">Changed since you chose:</strong> {err.text} (HTTP 409). Choose the scope again.
              </>
            ) : err.status === 422 ? (
              <>
                <strong className="font-semibold">{err.op === "approve" ? "Approver not eligible:" : "Scope refused:"}</strong> {err.text} (HTTP 422).
              </>
            ) : err.status === 401 || err.status === 403 ? (
              <>
                <strong className="font-semibold">Approver key required:</strong> {err.text} (HTTP {err.status}). Enter the approver key.
              </>
            ) : (
              <>
                <strong className="font-semibold">{err.op === "approve" ? "Grant failed:" : "Choose failed:"}</strong> {err.text}
                {err.status ? ` (HTTP ${err.status})` : ""}
              </>
            )}
          </p>
          {err.status === 409 && err.op === "approve" ? (
            <button
              type="button"
              onClick={() => void choose()}
              className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-red-50 ring-1 ring-red-300/40 outline-none hover:bg-red-500/15 focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <RotateCcw aria-hidden className="size-3" /> Choose the scope again
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
