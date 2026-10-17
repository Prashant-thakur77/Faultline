"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { Ban, CalendarClock, CircleCheck, CircleMinus, FileSignature, Hourglass, LoaderCircle, Moon } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { useNow, type Polled } from "@/hooks/usePolled";
import { ApiError, errorText } from "@/lib/api";
import type { Tone } from "@/lib/gate";
import { fmtDuration, fmtWhen, oncallApi, personText, type Contract, type ContractsList, type ContractStatus } from "@/lib/oncall";
import { cn } from "@/lib/utils";
import { PanelError, useOpenQuery } from "./bits";

const STATUS: Record<ContractStatus, { tone: Tone; icon: typeof Ban; text: string }> = {
  active: { tone: "pass", icon: CircleCheck, text: "active" },
  exhausted: { tone: "na", icon: CircleMinus, text: "used up" },
  expired: { tone: "na", icon: Hourglass, text: "expired" },
  revoked: { tone: "warn", icon: Ban, text: "revoked" },
};

const KIND_TEXT: Record<string, string> = {
  flip_flag: "feature flag",
  rollback_deploy: "rollback",
  open_issue: "issue",
  data_repair: "data repair",
};

export function ContractStatusChip({ status }: { status: string | null }) {
  const s = status && status in STATUS ? STATUS[status as ContractStatus] : null;
  return s ? (
    <StatusChip tone={s.tone} icon={s.icon}>
      {s.text}
    </StatusChip>
  ) : (
    <StatusChip tone="na">{status ?? "status not recorded"}</StatusChip>
  );
}

/** Used / left as dots plus words ("1 of 3 used · 2 left"); dots are decorative, the words carry it. */
export function UsesMeter({ uses, max }: { uses: number | null; max: number | null }) {
  if (uses === null || max === null) return <span className="text-[11px] text-zinc-400">uses not recorded</span>;
  const dots = Math.max(1, Math.min(12, max));
  return (
    <span className="inline-flex items-center gap-2 text-[11px] text-zinc-300">
      <span aria-hidden className="inline-flex gap-1">
        {Array.from({ length: dots }, (_, i) => (
          <span key={i} className={cn("size-2 rounded-full", i < uses ? "bg-[var(--fl-iris)]" : "bg-white/[0.12]")} />
        ))}
      </span>
      {uses} of {max} used · {Math.max(0, max - uses)} left
    </span>
  );
}

/**
 * Contracts ("handle it next time"): standing approvals for one repeat (same incident family, same action, same
 * parameters), from GET /api/contracts. Active first, with uses, expiry and Revoke; past ones folded.
 */
export function ContractsCard({ polled, tenant }: { polled: Polled<ContractsList>; tenant: string }) {
  const open = useOpenQuery(tenant);
  const data = polled.data;
  const rows = data?.rows ?? [];
  const active = rows.filter((c) => c.status === "active");
  const past = rows.filter((c) => c.status !== "active");
  return (
    <Section
      id="contracts"
      title="Contracts"
      via={
        data?.template ? (
          <ViaFalkor template={data.template} label="the contracts" onOpen={() => open(data, "contracts", "GET /api/contracts")} />
        ) : null
      }
      aside={
        data ? (
          <StatusChip tone={active.length ? "info" : "na"} icon={FileSignature}>
            {active.length} active
          </StatusChip>
        ) : null
      }
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        A standing approval for repeats of one fault: same incident family, same action, same parameters, a use count and
        an expiry. It never skips the gate, verification still runs, and a fix that does not verify pages a human at once.
      </p>
      {polled.error ? <PanelError error={polled.error} what="contracts (GET /api/contracts)" stale={!!data} /> : null}
      {polled.loading && !data && !polled.error ? (
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> Reading contracts from FalkorDB…
        </p>
      ) : null}
      {data && rows.length === 0 ? (
        <p className="rounded-xl bg-white/[0.02] px-4 py-4 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
          No contract yet. After a fix is verified <span className="font-mono text-zinc-100">APPLIED</span>, the incident
          room offers &ldquo;Grant a contract for repeats&rdquo;.
        </p>
      ) : null}
      {active.length ? (
        <ul aria-label="Active contracts" className="space-y-2">
          {active.map((c) => (
            <ContractItem key={c.id} c={c} tenant={tenant} onChanged={polled.refresh} />
          ))}
        </ul>
      ) : data && rows.length ? (
        <p className="text-sm text-zinc-300">No active contract: every repeat pages a human.</p>
      ) : null}
      {past.length ? (
        <Disclosure className="mt-3" size="xs" defaultOpen={false} summary={<>Past contracts<span className="text-[var(--fl-subtle)]"> · {past.length}</span></>}>
          <ul aria-label="Past contracts" className="space-y-2">
            {past.map((c) => (
              <ContractItem key={c.id} c={c} tenant={tenant} onChanged={polled.refresh} />
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </Section>
  );
}

function Expiry({ at }: { at: number | null }) {
  const now = useNow(30_000);
  if (at === null) return <span>expiry not recorded</span>;
  const left = at - now;
  return (
    <span className="inline-flex items-center gap-1" title={fmtWhen(at)}>
      <CalendarClock aria-hidden className="size-3.5" />
      {left > 0 ? `expires in ${fmtDuration(left)}` : `expired ${fmtWhen(at)}`}
    </span>
  );
}

function ContractItem({ c, tenant, onChanged }: { c: Contract; tenant: string; onChanged: () => void }) {
  const live = c.status === "active";
  return (
    <li className={cn("rounded-xl px-3.5 py-3 ring-1", live ? "bg-[color-mix(in_oklch,var(--fl-iris)_6%,transparent)] ring-[color-mix(in_oklch,var(--fl-iris)_30%,transparent)]" : "bg-white/[0.02] ring-white/[0.06]")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <ContractStatusChip status={c.status} />
        <span className="text-sm font-medium text-zinc-50">{c.actionKind ? KIND_TEXT[c.actionKind] ?? c.actionKind : "action not recorded"}</span>
        <span className="text-xs text-zinc-400">for family</span>
        <span className="font-mono text-xs break-all text-zinc-200">{c.family ?? "–"}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-400">
        <UsesMeter uses={c.uses} max={c.maxUses} />
        <Expiry at={c.expiresAt} />
      </div>
      <p className="mt-1.5 text-[11px] break-words text-zinc-400">
        granted by <span className="text-zinc-200">{personText(c.grantedBy)}</span>
        {c.grantedAt !== null ? ` · ${fmtWhen(c.grantedAt)}` : ""}
        {c.paramsHash ? (
          <>
            {" · params "}
            <span className="font-mono text-zinc-300" title={c.paramsHash}>
              {c.paramsHash.slice(0, 12)}
            </span>
          </>
        ) : null}
        <span className="font-mono text-[var(--fl-subtle)]"> · {c.id}</span>
      </p>
      {c.quote ? <p className="mt-1.5 border-l-2 border-white/10 pl-2 text-xs text-zinc-300 italic">&ldquo;{c.quote}&rdquo;</p> : null}
      {c.usedIn.length ? (
        <p className="mt-1.5 flex flex-wrap items-center gap-1 text-[11px] text-zinc-400">
          <Moon aria-hidden className="size-3.5 text-[var(--fl-iris)]" />
          used on
          {c.usedIn.map((u, i) => (
            <span key={`${u.incident}:${i}`}>
              <Link
                href={`/incidents/${encodeURIComponent(u.incident)}?tenant=${encodeURIComponent(tenant)}`}
                className="rounded font-mono text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                {u.incident}
              </Link>
              {u.verdict ? ` (${u.verdict})` : ""}
              {i < c.usedIn.length - 1 ? "," : ""}
            </span>
          ))}
        </p>
      ) : null}
      {live ? <RevokeControl contract={c} tenant={tenant} onRevoked={onChanged} /> : null}
    </li>
  );
}

/** Revoke in two clicks (confirm names the consequence); the approver key is optional and sent only when typed. */
function RevokeControl({ contract, tenant, onRevoked }: { contract: Contract; tenant: string; onRevoked: () => void }) {
  const keyId = useId();
  const [confirm, setConfirm] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ status: number | null; text: string } | null>(null);
  const revoke = async () => {
    setBusy(true);
    setErr(null);
    try {
      await oncallApi.revokeContract(contract.id, tenant, key.trim() || undefined);
      setConfirm(false);
      onRevoked();
    } catch (e) {
      setErr({ status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e) });
    } finally {
      setBusy(false);
    }
  };
  if (!confirm) {
    return (
      <div className="mt-2.5">
        <button
          type="button"
          onClick={() => setConfirm(true)}
          className="inline-flex h-7 items-center gap-1 rounded-full px-3 text-xs text-red-200 ring-1 ring-red-400/40 outline-none hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-sky-400"
          aria-label={`Revoke contract ${contract.id}`}
        >
          <Ban aria-hidden className="size-3.5" /> Revoke
        </button>
      </div>
    );
  }
  return (
    <div role="group" aria-label={`Confirm revoking ${contract.id}`} className="mt-2.5 space-y-2 rounded-lg bg-red-500/[0.06] p-2.5 ring-1 ring-red-400/30">
      <p className="text-xs text-red-100">Revoke this contract? The next repeat pages a human again.</p>
      <label htmlFor={keyId} className="flex flex-col gap-0.5 text-[11px] text-zinc-300">
        Approver key (when the server asks for one; sent with this revoke only, never stored)
        <input
          id={keyId}
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          autoComplete="off"
          className="h-7 w-56 max-w-full rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-xs text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void revoke()}
          disabled={busy}
          className="inline-flex h-7 items-center gap-1 rounded-full bg-red-300 px-3 text-xs font-medium text-zinc-950 outline-none hover:bg-red-200 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
        >
          {busy ? <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" /> : <Ban aria-hidden className="size-3.5" />}
          Yes, revoke
        </button>
        <button
          type="button"
          onClick={() => {
            setConfirm(false);
            setErr(null);
          }}
          disabled={busy}
          className="inline-flex h-7 items-center rounded-full px-3 text-xs text-zinc-200 outline-none hover:bg-white/[0.06] focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          Keep it
        </button>
      </div>
      {err ? (
        <p role="alert" className="text-[11px] text-red-200">
          <strong className="font-semibold">Revoke failed:</strong> {err.text}
          {err.status ? ` (HTTP ${err.status})` : ""}
          {err.status === 401 || err.status === 403 ? ". Enter the approver key above." : ""}
        </p>
      ) : null}
    </div>
  );
}
