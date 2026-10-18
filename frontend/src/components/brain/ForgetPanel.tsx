"use client";

import { useId, useState } from "react";
import { plural } from "@/lib/format";
import { Eraser, LoaderCircle, ReceiptText, SearchCheck, ShieldCheck, TriangleAlert } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type { ForgetDryRun, ForgetFlip, ForgetReceipt } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/StatusChip";

type Err = { status: number | null; text: string };

/**
 * "Forget a document" (S10): dry run → the exact set and its receipt token →
 * a human approves that token → receipt (W-MEM-3 deletes, the receipt goes to audit_<tenant>,
 * vectors are re-queried to prove they are gone). On the public demo the server runs the
 * delete on a clean-room copy and says so (`clean_room: true`); the UI repeats it verbatim.
 */
export function ForgetPanel() {
  const tenant = useTenant();
  const docId = useId();
  const approverId = useId();
  const [doc, setDoc] = useState("");
  const [approver, setApprover] = useState("");
  const [plan, setPlan] = useState<ForgetDryRun | null>(null);
  const [receipt, setReceipt] = useState<ForgetReceipt | null>(null);
  const [busy, setBusy] = useState<"dry" | "exec" | null>(null);
  const [err, setErr] = useState<Err | null>(null);

  const fail = (e: unknown): Err => ({ status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e) });

  const dryRun = async () => {
    const id = doc.trim();
    if (!id || busy) return;
    setBusy("dry");
    setErr(null);
    setPlan(null);
    setReceipt(null);
    try {
      setPlan(await api.forgetDryRun(id, tenant));
    } catch (e) {
      setErr(fail(e));
    } finally {
      setBusy(null);
    }
  };

  const execute = async () => {
    if (!plan || !approver.trim() || busy) return;
    setBusy("exec");
    setErr(null);
    try {
      setReceipt(await api.forgetExecute(plan.doc.id, plan.token, approver.trim(), tenant));
    } catch (e) {
      setErr(fail(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="forget-h" className="space-y-2 fl-card rounded-2xl px-5 py-4">
      <h2 id="forget-h" className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
        <Eraser aria-hidden className="size-4 text-amber-300" /> Forget a document
      </h2>
      <p className="text-xs text-zinc-400">
        Dry run first: the graph lists exactly what the document alone produced. Approving binds to that receipt token; if the
        graph changed in between, the server refuses (409). On the public demo the delete runs on a clean-room copy; on a local
        server it deletes from the tenant graph (Reset demo data restores it).
      </p>

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void dryRun();
        }}
      >
        <div className="flex flex-col gap-0.5">
          <label htmlFor={docId} className="text-[11px] text-zinc-400">
            document id
          </label>
          <input
            id={docId}
            value={doc}
            onChange={(e) => setDoc(e.target.value)}
            maxLength={160}
            placeholder="e.g. doc-adr-021"
            autoComplete="off"
            spellCheck={false}
            className="h-8 w-48 rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          />
        </div>
        <Button type="submit" size="sm" variant="outline" disabled={!doc.trim() || busy !== null}>
          {busy === "dry" ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <SearchCheck aria-hidden />}
          Dry run
        </Button>
      </form>

      <div aria-live="polite" className="space-y-2">
        {err ? (
          <p role="alert" className="flex items-start gap-1.5 rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100">
            <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
            <span>
              <strong className="font-semibold">
                {err.status === 404
                  ? "Unknown document:"
                  : err.status === 409
                    ? "Receipt no longer matches the graph: run the dry run again."
                    : err.status === 429
                      ? "Rate limited:"
                      : "Forget failed:"}
              </strong>{" "}
              {err.text}
              {err.status ? ` (HTTP ${err.status})` : ""}
            </span>
          </p>
        ) : null}

        {plan && !receipt ? (
          <div className="space-y-2 rounded-md border border-amber-400/50 bg-amber-500/5 p-2 text-xs">
            <p className="font-semibold text-amber-100">
              Dry run: <span className="font-mono">{plan.doc.id}</span>
              {plan.doc.title ? <span className="font-normal text-zinc-200"> · {plan.doc.title}</span> : null}
            </p>
            <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5">
              <dt className="text-zinc-400">would delete</dt>
              <dd className="text-zinc-100">
                {plural(plan.nodes, "node")} (the document + {plan.owned.length} it alone produced) ·{" "}
                {plural(plan.relationships, "relationship")} · {plural(plan.vectors, "vector")}
              </dd>
              <dt className="text-zinc-400">ids</dt>
              <dd className="font-mono break-all text-zinc-100">{plan.owned.map((o) => `${o.id} (${o.label})`).join(", ") || "–"}</dd>
              <dt className="text-zinc-400">kept</dt>
              <dd className="font-mono break-all text-zinc-200">
                {plan.kept.length ? `${plan.kept.join(", ")} (also produced by another document)` : "none"}
              </dd>
              <dt className="text-zinc-400">receipt token</dt>
              <dd className="font-mono text-zinc-100" title={plan.token}>
                {plan.token.slice(0, 16)}… <span className="text-zinc-400">({plan.token.length} hex)</span>
              </dd>
            </dl>
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void execute();
              }}
            >
              <div className="flex flex-col gap-0.5">
                <label htmlFor={approverId} className="text-[11px] text-zinc-400">
                  approver (unverified identity in demo mode)
                </label>
                <input
                  id={approverId}
                  value={approver}
                  onChange={(e) => setApprover(e.target.value)}
                  maxLength={60}
                  required
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="person id"
                  className="h-8 w-40 rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                />
              </div>
              <Button type="submit" size="sm" className="bg-red-700 text-white hover:bg-red-800" disabled={!approver.trim() || busy !== null}>
                {busy === "exec" ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <Eraser aria-hidden />}
                Approve and forget
              </Button>
            </form>
          </div>
        ) : null}

        {receipt ? (
          <div role="status" className="space-y-1.5 rounded-md border border-emerald-400/60 bg-emerald-500/10 p-2 text-xs">
            <p className="flex flex-wrap items-center gap-1.5 font-semibold text-emerald-100">
              <ReceiptText aria-hidden className="size-4 text-emerald-300" /> Receipt for <span className="font-mono">{receipt.doc}</span>
              {receipt.vectors === 0 ? (
                <StatusChip tone="info" icon={ShieldCheck}>
                  no vectors owned
                </StatusChip>
              ) : receipt.vectors_still_found === 0 ? (
                <StatusChip tone="pass" icon={ShieldCheck}>
                  vectors gone (re-queried)
                </StatusChip>
              ) : (
                <StatusChip tone="fail" icon={TriangleAlert}>
                  {receipt.vectors_still_found} vectors still found
                </StatusChip>
              )}
            </p>
            {receipt.clean_room ? (
              <p className="text-amber-100">
                Ran on a clean-room copy (<span className="font-mono">{receipt.graph}</span>); the live graph is unchanged.
              </p>
            ) : null}
            <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5">
              <dt className="text-zinc-400">deleted</dt>
              <dd className="text-zinc-100">
                {plural(receipt.nodes, "node")} · {plural(receipt.relationships, "relationship")} · {plural(receipt.vectors, "vector")}
              </dd>
              <dt className="text-zinc-400">forgotten</dt>
              <dd className="font-mono break-all text-zinc-100">{receipt.forgotten_ids.join(", ") || "–"}</dd>
              <dt className="text-zinc-400">kept</dt>
              <dd className="font-mono break-all text-zinc-200">{receipt.kept_ids.join(", ") || "none"}</dd>
              <dt className="text-zinc-400">vector re-query</dt>
              <dd className="text-zinc-100">{receipt.proof.vector_requery}</dd>
              <dt className="text-zinc-400">approver</dt>
              <dd className="font-mono text-zinc-100">{receipt.approver}</dd>
              <dt className="text-zinc-400">graph</dt>
              <dd className="font-mono break-all text-zinc-200">{receipt.graph ?? `tenant_${receipt.tenant}`}</dd>
            </dl>
            <p className="text-zinc-400">The receipt is written to the audit graph (audit_{receipt.tenant}).</p>
            {receipt.flip ? <FlipView flip={receipt.flip} /> : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}


/** The same question, before and after the forget: the behavioural proof, next to the vector proof. */
export function FlipView({ flip }: { flip: ForgetFlip }) {
  if (flip.error || !flip.before || !flip.after) {
    return <p role="alert" className="text-amber-300">Before/after question unavailable: {flip.error ?? "no answer"}</p>;
  }
  const gone = new Set(flip.no_longer_cited ?? []);
  return (
    <section aria-label="The same question, before and after" className="mt-2 space-y-2 border-t border-white/[0.06] pt-3">
      <p className="text-zinc-300">
        Same question, before and after: <span className="text-zinc-100">&ldquo;{flip.question}&rdquo;</span>
        {flip.answer_changed ? null : <span className="ml-2 text-amber-300">(the answer did not change)</span>}
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {([["before", flip.before], ["after", flip.after]] as const).map(([k, a]) => (
          <div key={k} className="min-w-0 rounded-lg border border-white/[0.08] bg-black/20 p-3">
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-zinc-400">{k}</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-zinc-200">{a.answer}</p>
            <p className="mt-2 flex flex-wrap gap-1 font-mono text-[11px]">
              {a.citations.map((c) => (
                <span key={c} className={"rounded border px-1.5 py-0.5 " + (k === "before" && gone.has(c)
                  ? "border-red-400/40 text-red-200 line-through" : "border-white/10 text-zinc-300")}>{c}</span>
              ))}
            </p>
          </div>
        ))}
      </div>
      {gone.size ? <p className="text-zinc-300">No longer cited: <span className="font-mono text-zinc-100">{[...gone].join(", ")}</span></p> : null}
    </section>
  );
}
