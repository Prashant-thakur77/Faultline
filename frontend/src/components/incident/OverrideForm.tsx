"use client";

import { useId, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { OverrideResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";

const VERDICTS = [
  {
    v: "intentional",
    text: "Intentional: the change departs from it on purpose",
  },
  { v: "accidental", text: "Accidental: the violation stands" },
  { v: "discuss", text: "Discuss: needs a decision" },
] as const;

/**
 * Answer a contradiction for this change (M15 #3), two steps like an action: review returns the exact override and
 * its plan hash; approving sends that hash back with an approver. An intentional answer takes the decision out of G8
 * and preflight for this change from the next gate run on; accidental and discuss keep the violation.
 */
export function OverrideForm({
  decision,
  change,
  incident,
  tenant,
}: {
  decision: string;
  change: string;
  incident: string;
  tenant: string;
}) {
  const [verdict, setVerdict] = useState<string>("accidental");
  const [why, setWhy] = useState("");
  const [approver, setApprover] = useState("");
  const [review, setReview] = useState<OverrideResponse | null>(null);
  const [done, setDone] = useState<OverrideResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const id = useId();

  async function step(final: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const base = { change, verdict, why, incident };
      if (!final) setReview(await api.decisionOverride(decision, base, tenant));
      else if (review)
        setDone(
          await api.decisionOverride(
            decision,
            { ...base, plan_hash: review.plan_hash, approver },
            tenant,
          ),
        );
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <p role="status" className="mt-2 text-xs text-emerald-200">
        Recorded ({done.override}): {done.verdict} by {approver}. It applies to
        the next gate run or preflight of {change}.
      </p>
    );
  }
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-zinc-300 outline-none focus-visible:ring-2 focus-visible:ring-amber-300">
        Answer this contradiction
      </summary>
      <div className="mt-2 space-y-2">
        <fieldset className="space-y-1">
          <legend className="text-zinc-400">Was it intended?</legend>
          {VERDICTS.map((x) => (
            <label key={x.v} className="flex items-center gap-2 text-zinc-200">
              <input
                type="radio"
                name={`${id}-verdict`}
                value={x.v}
                checked={verdict === x.v}
                onChange={() => {
                  setVerdict(x.v);
                  setReview(null);
                }}
              />
              {x.text}
            </label>
          ))}
        </fieldset>
        <label className="block text-zinc-400">
          Why (recorded with the override)
          <textarea
            value={why}
            onChange={(e) => {
              setWhy(e.target.value);
              setReview(null);
            }}
            rows={2}
            maxLength={500}
            className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-900 p-1 text-zinc-100"
          />
        </label>
        {!review ? (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || why.trim().length < 3}
            onClick={() => step(false)}
          >
            {busy ? (
              <LoaderCircle aria-hidden className="motion-safe:animate-spin" />
            ) : null}
            Review
          </Button>
        ) : (
          <div className="space-y-1 rounded border border-zinc-700 p-2">
            <p className="text-zinc-300">
              Record{" "}
              <span className="font-semibold text-zinc-100">
                {review.verdict}
              </span>{" "}
              for {review.change} against {review.decision} (
              {review.contradiction.rule_key} ={" "}
              {String(review.contradiction.actual)}).
              <span className="block font-mono text-[10px] text-zinc-400">
                plan hash {review.plan_hash.slice(0, 16)}…
              </span>
            </p>
            <label className="block text-zinc-400">
              Approver (person id)
              <input
                value={approver}
                onChange={(e) => setApprover(e.target.value)}
                className="mt-1 block w-48 rounded border border-zinc-700 bg-zinc-900 p-1 font-mono text-zinc-100"
              />
            </label>
            <Button
              size="sm"
              disabled={busy || !approver.trim()}
              onClick={() => step(true)}
            >
              Approve this exact override
            </Button>
          </div>
        )}
        {err ? (
          <p role="alert" className="text-red-300">
            {err}
          </p>
        ) : null}
      </div>
    </details>
  );
}
