"use client";

import { useCallback, useEffect, useState } from "react";
import { GitMerge } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type { EdgeProposal, IncidentView } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/StatusChip";
import { Section } from "./Section";

/**
 * M15 #4, the graph learns from a verified fix. When the gate did not confirm a cause, a human can name the change they
 * suspect: it becomes an ordinary rollback option (two-step approval, three-valued verification). After a VERIFIED
 * fix, the links the graph was missing are listed here as proposals; a learned edge exists only once a human approves
 * the exact proposal (plan hash).
 */
export function LearnedEdgesCard({
  view,
  stage,
  onChanged,
}: {
  view: IncidentView;
  stage: string;
  onChanged: () => void;
}) {
  const tenant = useTenant();
  const inc = view.incident.id;
  const [props, setProps] = useState<EdgeProposal[] | null>(null);
  const [change, setChange] = useState("");
  const [by, setBy] = useState("");
  const [why, setWhy] = useState("");
  const [approver, setApprover] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api.edgeProposals(inc, tenant).then(
      (r) => setProps(r.proposals),
      (e) => setErr(errorText(e)),
    );
  }, [inc, tenant]);
  useEffect(load, [load]);

  const notConfirmed =
    !view.report?.cause_id || view.report?.outcome !== "CONFIRMED";
  const canName =
    notConfirmed &&
    ["UNKNOWN_ESCALATED", "GATE", "AWAITING_APPROVAL"].includes(stage);
  if (!canName && !props?.length) return null;

  async function name() {
    setErr(null);
    try {
      const r = await api.humanFix(inc, { change, by, why }, tenant);
      setMsg(
        `Added ${r.id}: choose and approve it in the plan; verification decides whether it fixed the incident.`,
      );
      onChanged();
    } catch (e) {
      setErr(errorText(e));
    }
  }

  async function approve(p: EdgeProposal) {
    setErr(null);
    try {
      await api.approveEdge(
        inc,
        p.id,
        { plan_hash: p.plan_hash, approver },
        tenant,
      );
      load();
    } catch (e) {
      setErr(errorText(e));
    }
  }

  return (
    <Section
      id="learned"
      title="The graph learns"
      aside={
        <StatusChip tone="info" icon={GitMerge}>
          {props?.length ?? 0} proposed links
        </StatusChip>
      }
    >
      {canName ? (
        <details className="mb-2 text-xs">
          <summary className="cursor-pointer text-zinc-300">
            Name the change you suspect (the gate did not confirm one)
          </summary>
          <div className="mt-2 grid gap-1">
            <label className="text-zinc-400">
              Change id
              <input
                value={change}
                onChange={(e) => setChange(e.target.value)}
                className="mt-1 block w-60 rounded border border-zinc-700 bg-zinc-900 p-1 font-mono text-zinc-100"
              />
            </label>
            <label className="text-zinc-400">
              You (person id)
              <input
                value={by}
                onChange={(e) => setBy(e.target.value)}
                className="mt-1 block w-40 rounded border border-zinc-700 bg-zinc-900 p-1 font-mono text-zinc-100"
              />
            </label>
            <label className="text-zinc-400">
              Why
              <input
                value={why}
                onChange={(e) => setWhy(e.target.value)}
                className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-900 p-1 text-zinc-100"
              />
            </label>
            <Button
              size="sm"
              variant="outline"
              disabled={!change.trim() || !by.trim() || why.trim().length < 3}
              onClick={name}
              className="w-fit"
            >
              Add as a rollback option
            </Button>
          </div>
        </details>
      ) : null}
      {msg ? (
        <p role="status" className="mb-2 text-xs text-emerald-200">
          {msg}
        </p>
      ) : null}
      {props?.length ? (
        <ul className="space-y-2" aria-label="Proposed failure links">
          {props.map((p) => (
            <li
              key={p.id}
              className="rounded-md border border-zinc-700 p-2 text-xs"
            >
              <span className="font-mono text-zinc-100">
                {p.src} → {p.dst}
              </span>{" "}
              <span className="text-zinc-400">capacity {p.cap.toFixed(3)}</span>{" "}
              <StatusChip tone={p.status === "approved" ? "pass" : "warn"}>
                {p.status === "approved"
                  ? `learned (approved by ${p.approved_by})`
                  : "proposed: not an edge yet"}
              </StatusChip>
              <span className="mt-1 block text-zinc-300">{p.why}</span>
              {p.status === "proposed" ? (
                <span className="mt-1 flex items-end gap-2">
                  <label className="text-zinc-400">
                    Approver
                    <input
                      value={approver}
                      onChange={(e) => setApprover(e.target.value)}
                      className="mt-1 block w-36 rounded border border-zinc-700 bg-zinc-900 p-1 font-mono text-zinc-100"
                    />
                  </label>
                  <Button
                    size="sm"
                    disabled={!approver.trim()}
                    onClick={() => approve(p)}
                  >
                    Approve this exact link
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {err ? (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {err}
        </p>
      ) : null}
    </Section>
  );
}
