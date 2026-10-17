import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EXACT, HASH, option, plan, stubFetch } from "@/test/fixtures";
import type { ActionOption, OptionLearned, PlanLearned } from "@/lib/types";
import { PlanApprovalCard } from "./PlanApprovalCard";

const PREF_LINE = "learned: your team approved the flag flip 5 of the last 5 time(s) for payment; last 2 h ago";
const GUIDE_LINE = 'against your guideline gl-abc123: "flag off hides the revenue KPI" (Asha Rao, promoted by p-017); approving it needs an explicit override';
const SUGG_LINE =
  "this exact fix was approved and verified APPLIED on 2 incidents of payment: once it is verified here, grant a standing approval for repeats? (still two steps)";

const ACTIVE_GUIDE: OptionLearned["guideline"] = {
  id: "gl-abc123",
  text: "flag off hides the revenue KPI",
  status: "active",
  by: "p-030",
  by_name: "Asha Rao",
  at: Date.now() - 3 * 3_600_000,
  incident: "inc-s1-1",
  event: "le-r1",
  needs_override: true,
  decided_by: "p-017",
  line: GUIDE_LINE,
};

function render2(options: ActionOption[], extra: { learned?: PlanLearned; stage?: string; readOnly?: boolean } = {}) {
  const onRefresh = vi.fn();
  const onApproved = vi.fn();
  const p = { ...plan(options), learned: extra.learned ?? null };
  const { unmount } = render(
    <PlanApprovalCard
      incidentId="inc-1"
      stage={extra.stage ?? "AWAITING_APPROVAL"}
      stages={[]}
      plan={p}
      error={null}
      onRefresh={onRefresh}
      onApproved={onApproved}
      readOnly={extra.readOnly}
    />,
  );
  return { onRefresh, onApproved, unmount };
}

const items = () => within(screen.getByRole("list", { name: "Action options" })).getAllByRole("listitem");

describe("PlanApprovalCard: what the team taught Faultline (M21)", () => {
  it("an option learning moved says so, with an arrow and its rank without learning; the why line is not repeated in the reason", () => {
    stubFetch({});
    render2(
      [
        option({
          id: "act-inc-1-1",
          reason: `cuts the failure edge; ${PREF_LINE}`,
          learned: { family: "payment", rank_without_learning: 2, score: 0.79, preference: { pref: 0.857, n_approve: 5, n_reject: 0, n_family_approve: 5, last_at: null, events: ["le-a1"], line: PREF_LINE } },
        }),
        option({ id: "act-inc-1-2", kind: "rollback_deploy", option: "roll back payment", learned: { family: "payment", rank_without_learning: 1 } }),
      ],
      { learned: { consulted: true, family: "payment", n_family: 5, applies: true, pref_min_n: 3, moved: ["act-inc-1-1", "act-inc-1-2"] } },
    );
    const [first, second] = items();
    expect(within(first).getByText("moved up from #2")).toBeTruthy();
    expect(within(first).getAllByText(PREF_LINE)).toHaveLength(1); // shown once, not again inside the reason
    expect(within(first).getByText("cuts the failure edge")).toBeTruthy();
    expect(within(second).getByText("moved down from #1")).toBeTruthy();
    expect(screen.getByText(/5 recorded choices by your team for payment are blended into the order; 2 options moved/)).toBeTruthy();
  });

  it("an option learning did not move shows no arrow; its preference stays in Why and details", () => {
    stubFetch({});
    render2([option({ learned: { family: "payment", rank_without_learning: 1, preference: { pref: 0.857, n_approve: 5, n_reject: 0, n_family_approve: 5, last_at: null, events: [], line: PREF_LINE } } })]);
    expect(screen.queryByText(/moved (up|down) from/)).toBeNull();
    expect(screen.getByText(PREF_LINE)).toBeTruthy();
  });

  it("a run that never consulted learning shows nothing learned", () => {
    stubFetch({});
    render2([option({})], { learned: { consulted: false, note: "learning not consulted for this run (no on-call home)" } });
    expect(screen.queryByText(/^Learned:/)).toBeNull();
    expect(screen.queryByText(/moved (up|down)/)).toBeNull();
  });

  it("an active guideline flags the option, and approving needs the named override and a reason (sent with the plan hash)", async () => {
    const { calls } = stubFetch({ "/approve": { body: { approved: true, state: "EXECUTE", mine: true, idem: "x", approval_id: "ap-1", override: { id: "gl-abc123", reason: "KPI already down", text: "flag off hides the revenue KPI" }, learned: { learned: true, family: "payment", event: "le-ap1" } } } });
    const { onApproved } = render2([
      option({ status: "chosen", spec: EXACT, plan_hash: HASH, reason: `cuts the failure edge; ${GUIDE_LINE}`, learned: { family: "payment", rank_without_learning: 1, guideline: ACTIVE_GUIDE } }),
    ]);
    const banner = screen.getByRole("note", { name: "Against your guideline gl-abc123" });
    expect(banner.textContent).toMatch(/Against your guideline gl-abc123: “flag off hides the revenue KPI”/);
    expect(banner.textContent).toMatch(/Asha Rao \(p-030\)'s rejection on inc-s1-1/);
    expect(banner.textContent).toMatch(/promoted by p-017/);

    const approve = screen.getByRole("button", { name: /Approve this exact action/ }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    const group = screen.getByRole("group", { name: "Override guideline gl-abc123" });
    fireEvent.click(within(group).getByLabelText("I am overriding guideline gl-abc123 for this incident"));
    expect(approve.disabled).toBe(true); // a reason is still needed
    fireEvent.change(within(group).getByLabelText(/^Override reason/), { target: { value: "no" } });
    expect(approve.disabled).toBe(true);
    fireEvent.change(within(group).getByLabelText(/^Override reason/), { target: { value: "KPI already down" } });
    expect(approve.disabled).toBe(false);
    fireEvent.click(approve);
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
    const call = calls.find((c) => c.url.includes("/approve"))!;
    expect(JSON.parse(String(call.init?.body))).toEqual({
      action_id: "act-flag",
      plan_hash: HASH,
      approver: "p-030",
      override_guideline: "gl-abc123",
      override_reason: "KPI already down",
    });
    // the reject path is unchanged: still one Reject button and its own Reason field
    expect(screen.getAllByRole("button", { name: /Reject/ })).toHaveLength(1);
  });

  it("a guideline promoted after the plan was made: the server's 409 names it and the override appears (never retried for you)", async () => {
    const detail =
      'flag paymentGate → off is against active guideline gl-abc123 ("flag off hides the revenue KPI", promoted by Mei Chen): send override_guideline=gl-abc123 and an override_reason';
    stubFetch({ "/approve": { status: 409, body: { detail } } });
    const { onApproved, onRefresh } = render2([option({ status: "chosen", spec: EXACT, plan_hash: HASH })]);
    expect(screen.queryByRole("group", { name: /Override guideline/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Approve this exact action/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Needs a guideline override: .*\(HTTP 409\)/);
    expect(within(alert).queryByRole("button", { name: /Re-choose/ })).toBeNull();
    const group = screen.getByRole("group", { name: "Override guideline gl-abc123" });
    expect(group.textContent).toMatch(/The server refused the approval/);
    expect(group.textContent).toMatch(/promoted by Mei Chen/);
    expect(onApproved).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();

    const { calls } = stubFetch({ "/approve": { body: { approved: true, state: "EXECUTE", mine: true, idem: "x", approval_id: "ap-1" } } });
    fireEvent.click(within(group).getByLabelText(/I am overriding guideline gl-abc123/));
    fireEvent.change(within(group).getByLabelText(/^Override reason/), { target: { value: "checkout matters more" } });
    fireEvent.click(screen.getByRole("button", { name: /Approve this exact action/ }));
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
    expect(JSON.parse(String(calls[0].init?.body))).toMatchObject({ override_guideline: "gl-abc123", override_reason: "checkout matters more", plan_hash: HASH });
  });

  it("a proposed guideline is a quiet note pointing at where it is decided; it asks for no override", () => {
    stubFetch({});
    render2([
      option({
        status: "chosen",
        spec: EXACT,
        plan_hash: HASH,
        learned: { family: "payment", guideline: { ...ACTIVE_GUIDE, status: "proposed", needs_override: false, decided_by: null, line: "proposed guideline gl-abc123 …" } },
      }),
    ]);
    expect(screen.getByText(/Not active: promote or dismiss it in/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "What Faultline has learned" }).getAttribute("href")).toBe("/memory?tenant=acme#learned");
    expect(screen.queryByRole("group", { name: /Override guideline/ })).toBeNull();
    expect((screen.getByRole("button", { name: /Approve this exact action/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("a contract suggestion is a chip that explains itself before the fix is verified, and opens the grant form after", () => {
    stubFetch({});
    const s = { n: 2, params_hash: "9d71aa", incidents: ["inc-s1-1", "inc-s1-2"], events: ["le-v1"], people: ["p-030"], line: SUGG_LINE };
    const { unmount } = render2([option({ learned: { family: "payment", contract_suggestion: s } })]);
    const chip = screen.getByRole("button", { name: /Faultline suggests a standing approval/ });
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(SUGG_LINE)).toBeTruthy();
    expect(screen.getByText(/Nothing is granted by this suggestion/)).toBeTruthy();
    unmount();
    render2([option({ status: "executed", verdict: "APPLIED", plan_hash: HASH, learned: { family: "payment", contract_suggestion: s } })], { stage: "RESOLVED" });
    const open = screen.getByRole("button", { name: "Faultline suggests a standing approval" });
    expect(screen.getByRole("region", { name: "Plan & approval" }).textContent).toMatch(/verified APPLIED on 2 incidents of payment \(inc-s1-1, inc-s1-2\)/);
    fireEvent.click(open);
    expect(screen.getByRole("button", { name: "Choose this scope" })).toBeTruthy(); // the M19 grant form, still two steps
  });

  it("a rejection with a reason says which guideline it proposed and where to decide it", async () => {
    stubFetch({
      "/reject": {
        body: {
          rejected: true,
          action_id: "act-flag",
          status: "rejected",
          rejected_at: 1,
          stage: "AWAITING_APPROVAL",
          reason: "flag off hides the revenue KPI",
          approver: { id: "p-030" },
          learned: { learned: true, family: "payment", event: "le-r9", kind: "reject", guideline: { id: "gl-99aa00", status: "proposed" } },
        },
      },
    });
    render2([option({ status: "chosen", spec: EXACT, plan_hash: HASH })]);
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    fireEvent.change(screen.getByLabelText(/^Reason/), { target: { value: "flag off hides the revenue KPI" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm reject" }));
    const st = (await screen.findByText("Rejected:")).closest("[role=status]")!;
    expect(st.textContent).toMatch(/Rejected:.*p-030.*choose another option/);
    expect(st.textContent).toMatch(/Faultline proposed guideline gl-99aa00 from your reason/);
  });
});
