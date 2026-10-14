"use client";

import { useMemo } from "react";
import { useTenant } from "@/lib/tenant";
import { originText, parseChain } from "@/lib/gate";
import type { ParamContext } from "@/lib/params";
import type { Evidence, GateCheck, GateRun, IncidentView, PlanItem, ToolCallRow } from "@/lib/types";
import { useCypherPanel, type CypherRequest } from "@/components/cypher/CypherPanelContext";

export interface IncidentActions {
  openCheck: (run: GateRun, check: GateCheck) => void;
  openEvidence: (id: string) => void;
  openToolCall: (tc: ToolCallRow) => void;
  openNode: (id: string) => void;
  /** A recorded plan-stage tool result (containment cut, what-if, who fixes, …). */
  openPlanItem: (item: PlanItem<unknown>, title: string) => void;
  /**
   * A template the API ran to assemble a view (e.g. /plan memory, the report's M12 sections); params
   * derived from the incident, plus `ctx` overrides (still labelled "derived" in the panel).
   */
  openTemplate: (template: string, title: string, origin: string, detail?: string, ctx?: Partial<ParamContext>) => void;
  /** The latest recorded call of `tool` in this run (Cypher panel with its recorded params), if any. */
  toolCallOf: (tool: string) => ToolCallRow | null;
  evidenceById: Map<string, Evidence>;
}

/**
 * Wires gate checks, evidence, tool calls, plan items and graph nodes to the Cypher panel.
 * `offline` (replay mode) makes every panel show the exported Cypher without calling the API.
 */
export function useIncidentActions(
  view: IncidentView | null,
  offline: CypherRequest["offline"] = null,
): IncidentActions {
  const panel = useCypherPanel();
  const tenant = useTenant();

  return useMemo(() => {
    const open = (req: CypherRequest) => panel.open({ ...req, offline });
    const evidenceById = new Map<string, Evidence>((view?.report?.evidence ?? []).map((e) => [e.id, e]));
    const toolByEvidence = new Map<string, ToolCallRow>();
    for (const tc of view?.tool_calls ?? []) if (tc.evidence_id && !toolByEvidence.has(tc.evidence_id)) toolByEvidence.set(tc.evidence_id, tc);

    const base = (): ParamContext => ({
      incident: view?.incident.id,
      run: view?.run.run,
      onset: view?.incident.onset_at,
      targets: view?.incident.targets,
    });

    const chainOfRun = (run: GateRun): string[] | undefined => {
      const g2 = run.checks.find((c) => c.name === "G2 path" && c.passed === true);
      return parseChain(g2?.detail) ?? undefined;
    };

    const openCheck = (run: GateRun, check: GateCheck) => {
      const isNeg = run.cause === "NO_INCIDENT";
      open({
        template: check.template,
        title: `${check.name} · ${run.cause}`,
        origin: `gate run ${run.id} (${originText(run.origin)}, attempt ${run.attempt})`,
        detail: check.detail,
        recordedParams: check.params,
        ctx: {
          ...base(),
          cause: isNeg ? undefined : run.cause,
          chain: chainOfRun(run) ?? (view?.report?.cause_id === run.cause ? view?.report?.mechanism : undefined),
          evidenceIds: check.evidence_ids,
        },
        incident: view?.incident.id,
        tenant,
      });
    };

    /** Context of the gate check that cites this evidence (same template preferred). */
    const citingCtx = (id: string, template: string | null): ParamContext => {
      const citing = (view?.gate_runs ?? []).flatMap((g) =>
        g.checks.filter((c) => c.evidence_ids.includes(id)).map((c) => ({ g, c })),
      );
      const pick = citing.find((x) => template && x.c.template === template) ?? citing[0];
      if (!pick || pick.g.cause === "NO_INCIDENT") return {};
      return {
        cause: pick.g.cause,
        chain: chainOfRun(pick.g) ?? (view?.report?.cause_id === pick.g.cause ? view?.report?.mechanism : undefined),
      };
    };

    const openEvidence = (id: string) => {
      const ev = evidenceById.get(id);
      const tc = toolByEvidence.get(id);
      if (ev) {
        open({
          template: ev.template,
          title: `${ev.id} · ${ev.kind}`,
          origin: `evidence ${ev.id} (tool ${ev.tool}, source ${ev.source})`,
          detail: ev.summary,
          ctx: { ...base(), ...citingCtx(ev.id, ev.template), node: ev.about.length === 1 ? ev.about[0] : undefined },
          incident: view?.incident.id,
          tenant,
          evidence: ev,
        });
      } else if (tc) {
        open({
          template: tc.template,
          title: `${id} · ${tc.kind ?? tc.tool}`,
          origin: `tool call ${tc.tool} (${tc.id})`,
          detail: tc.summary ?? undefined,
          recordedParams: tc.params ?? null,
          recorded: { ms: tc.ms, rows: tc.rows, digest: tc.digest ?? null },
          ctx: { ...base(), ...citingCtx(id, tc.template) },
          incident: view?.incident.id,
          tenant,
        });
      } else {
        open({
          template: null,
          title: id,
          origin: "an evidence id cited by the gate",
          detail:
            "This evidence id is cited by a gate check but is neither in the report's evidence list nor attached to a tool call in this incident view.",
          ctx: base(),
          incident: view?.incident.id,
          tenant,
        });
      }
    };

    const openToolCall = (tc: ToolCallRow) => {
      const ev = tc.evidence_id ? evidenceById.get(tc.evidence_id) : undefined;
      open({
        template: tc.template,
        title: `${tc.tool}${tc.evidence_id ? ` → ${tc.evidence_id}` : ""}`,
        origin: `tool call ${tc.id} (${tc.rows} rows, ${tc.ms} ms)`,
        detail: tc.summary ?? undefined,
        recordedParams: tc.params ?? null,
        recorded: { ms: tc.ms, rows: tc.rows, digest: tc.digest ?? null },
        ctx: { ...base(), ...(tc.evidence_id ? citingCtx(tc.evidence_id, tc.template) : {}) },
        incident: view?.incident.id,
        tenant,
        evidence: ev ?? null,
      });
    };

    const openNode = (id: string) => {
      // A change node opens the G2 path query from it to the symptom; any other node opens its context.
      // Prefer the G2 check that recorded its params (the confirmation run), else the first one.
      const g2s = (view?.gate_runs ?? []).flatMap((g) =>
        g.cause === id ? g.checks.filter((c) => c.name === "G2 path").map((c) => ({ g, c })) : [],
      );
      const pick = g2s.find((x) => x.c.params) ?? g2s[0];
      if (pick) {
        openCheck(pick.g, pick.c);
        return;
      }
      open({
        template: "Q-CTX-1",
        title: `context of ${id}`,
        origin: `graph node ${id}`,
        ctx: { ...base(), node: id },
        incident: view?.incident.id,
        tenant,
      });
    };

    const openPlanItem = (item: PlanItem<unknown>, title: string) => {
      const tc = (view?.tool_calls ?? []).find((t) => t.id === item.id);
      open({
        template: item.template,
        title,
        origin: `tool call ${item.id}${item.evidence_id ? ` → evidence ${item.evidence_id}` : ""}`,
        detail: item.summary ?? undefined,
        recordedParams: item.params ?? null,
        recorded: tc ? { ms: tc.ms, rows: tc.rows, digest: tc.digest ?? null } : null,
        ctx: base(),
        incident: view?.incident.id,
        tenant,
        evidence: item.evidence_id ? (evidenceById.get(item.evidence_id) ?? null) : null,
      });
    };

    const openTemplate = (template: string, title: string, origin: string, detail?: string, ctx?: Partial<ParamContext>) => {
      open({ template, title, origin, detail, ctx: { ...base(), ...ctx }, incident: view?.incident.id, tenant });
    };

    const toolCallOf = (tool: string): ToolCallRow | null =>
      (view?.tool_calls ?? []).filter((t) => t.tool === tool).at(-1) ?? null;

    return { openCheck, openEvidence, openToolCall, openNode, openPlanItem, openTemplate, toolCallOf, evidenceById };
  }, [panel, view, offline, tenant]);
}
