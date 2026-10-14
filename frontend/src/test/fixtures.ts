import { vi } from "vitest";
import type { ActionOption, ExactAction, PlanResponse } from "@/lib/types";

/** A fetch stub answering by URL substring; every call is recorded. Unmatched URLs fail loudly (500). */
export function stubFetch(routes: Record<string, { status?: number; body: unknown }>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = String(url);
    calls.push({ url: u, init });
    const hit = Object.entries(routes).find(([k]) => u.includes(k));
    const status = hit ? (hit[1].status ?? 200) : 500;
    const body = hit ? hit[1].body : { detail: `unstubbed ${u}` };
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export const HASH = "a".repeat(64);

export const EXACT: ExactAction = {
  kind: "flip_flag",
  incident: "inc-1",
  args: { repo: "org/infra" },
  branch: "faultline/fix-12345678",
  idem: "12345678",
  file: "flags.json",
  before: '{"on": true}\n',
  after: '{"on": false}\n',
  commit: "fix: flag off\n\nFaultline-Idem: 12345678",
  rollback: "flip it back",
  plan_hash: HASH,
};

export function option(over: Partial<ActionOption>): ActionOption {
  return {
    id: "act-flag",
    kind: "flip_flag",
    option: "flag paymentGate → off",
    enabled: true,
    reason: "cuts the failure edge",
    target: "payment",
    status: "option",
    preview: null,
    spec: null,
    plan_hash: null,
    idem: null,
    external_ref: null,
    verdict: null,
    explanation: null,
    channels: null,
    approval_id: null,
    ...over,
  };
}

export function plan(options: ActionOption[]): PlanResponse {
  return {
    stage: "AWAITING_APPROVAL",
    memory: { recalled: [], fix_history: [] },
    containment_cut: null,
    whatif: null,
    who_fixes: {
      id: "tc",
      evidence_id: "ev",
      summary: "",
      template: "Q-ORG-HARM",
      params: {},
      at: 0,
      payload: { rows: [{ person: "p-030", name: "Pat", score: 1, teams: ["t"], reasons: [] }] },
    },
    bus_factor: null,
    escalation_tree: null,
    options,
  } as unknown as PlanResponse;
}
