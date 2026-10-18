import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EXACT, HASH, option, plan, stubFetch } from "@/test/fixtures";
import { PlanApprovalCard } from "./PlanApprovalCard";

// GET /api/status as the app shell shares it: only `github` matters to this card
const app = vi.hoisted(() => ({ github: undefined as "real" | "simulated" | undefined }));
vi.mock("@/components/AppShell", () => ({
  useAppStatus: () => ({ status: app.github ? { github: app.github } : null, error: null, loading: false }),
}));

function setup(
  options = [option({ status: "chosen", spec: EXACT, plan_hash: HASH })],
) {
  const onRefresh = vi.fn();
  const onApproved = vi.fn();
  render(
    <PlanApprovalCard
      incidentId="inc-1"
      stage="AWAITING_APPROVAL"
      stages={[]}
      plan={plan(options)}
      error={null}
      onRefresh={onRefresh}
      onApproved={onApproved}
    />,
  );
  return { onRefresh, onApproved };
}

describe("PlanApprovalCard: reject the exact action", () => {
  it("offers Reject next to Approve, needs a reason, and posts the exact action's plan hash", async () => {
    const { calls } = stubFetch({
      "/reject": {
        body: {
          rejected: true,
          action_id: "act-flag",
          status: "rejected",
          rejected_at: 1,
          stage: "AWAITING_APPROVAL",
          reason: "prefer a rollback",
          approver: { id: "p-030" },
        },
      },
    });
    const { onRefresh, onApproved } = setup();
    const approve = screen.getByRole("button", {
      name: /Approve this exact action/,
    });
    const reject = screen.getByRole("button", { name: /Reject/ });
    expect(approve).toBeTruthy();
    expect(reject.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(reject);
    expect(reject.getAttribute("aria-expanded")).toBe("true");
    const reason = screen.getByLabelText(/^Reason/);
    const confirm = screen.getByRole("button", {
      name: "Confirm reject",
    }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true); // no reason yet
    fireEvent.change(reason, { target: { value: "no" } });
    expect(confirm.disabled).toBe(true); // under 3 characters
    expect(reason.getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(reason, { target: { value: "prefer a rollback" } });
    expect(confirm.disabled).toBe(false);
    // while rejecting, Approve is disabled: one decision at a time
    expect((approve as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(confirm);
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    const call = calls.find((c) => c.url.includes("/reject"))!;
    expect(call.url).toContain("/api/incidents/inc-1/reject?tenant=acme");
    expect(JSON.parse(String(call.init?.body))).toEqual({
      action_id: "act-flag",
      plan_hash: HASH,
      approver: "p-030",
      reason: "prefer a rollback",
    });
    expect(onApproved).not.toHaveBeenCalled();
    const st = (await screen.findByText("Rejected:")).closest("[role=status]");
    expect(st?.textContent).toMatch(/Rejected:.*p-030.*choose another option/);
  });

  it("shows a stale plan hash (409) as an alert and does not refresh", async () => {
    stubFetch({
      "/reject": {
        status: 409,
        body: { detail: "plan hash does not match the current chosen action" },
      },
    });
    const { onRefresh } = setup();
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    fireEvent.change(screen.getByLabelText(/^Reason/), {
      target: { value: "not this one" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm reject" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Plan changed: re-choose\..*409/);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("Escape closes the reject form and returns focus to the Reject button", async () => {
    setup();
    const reject = screen.getByRole("button", { name: /Reject/ });
    fireEvent.click(reject);
    fireEvent.keyDown(screen.getByLabelText(/^Reason/), { key: "Escape" });
    expect(screen.queryByLabelText(/^Reason/)).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(reject));
  });

  it("lists a rejected option as disabled with who rejected it and why (icon + text, not colour alone)", () => {
    setup([
      option({
        status: "rejected",
        enabled: false,
        rejected_by: "p-030",
        reject_reason: "freeze",
        reason: "flag is on at GitHub main",
      }),
      option({ id: "act-issue", kind: "open_issue", option: "open an issue" }),
    ]);
    const list = screen.getByRole("list", { name: "Action options" });
    const items = within(list).getAllByRole("listitem");
    expect(items[0].textContent).toMatch(/rejected by p-030/);
    expect(items[0].textContent).toMatch(/rejected by p-030: freeze/); // reject_reason, not the option's reason
    expect(items[0].textContent).toMatch(/flag is on at GitHub main/); // the original reason is kept
    expect(
      within(items[0]).queryByRole("button", { name: /Choose/ }),
    ).toBeNull();
    expect(
      within(items[1]).getByRole("button", { name: /Choose/ }),
    ).toBeTruthy();
  });

  it("shows each option's predicted future as its own line, from the object or the graph's JSON text", () => {
    const fut = {
      key: "payment|checkout",
      predicted: "contains",
      line: "contains: every symptom predicted back in band",
      exposed: ["kpi.exec_revenue"],
    };
    setup([
      option({
        id: "act-roll",
        kind: "rollback_deploy",
        option: "roll back D-pay-417",
        reason:
          "revert it; future: contains: every symptom predicted back in band; history: rollback worked 6/6 times",
        future: JSON.stringify({ ...fut, key: "remove_origin", exposed: [] }),
      }),
      option({
        id: "act-flag",
        option: "flag paymentGate → off",
        future: fut as never,
        reason:
          "cuts payment → checkout; future: contains: every symptom predicted back in band; leaves kpi.exec_revenue exposed",
      }),
      option({
        id: "act-issue",
        kind: "open_issue",
        option: "open an issue",
        reason: "track",
        future: {
          key: "no_change",
          predicted: "does_not_contain",
          line: "does not contain: checkout residual 0.4029 over its band",
          exposed: [],
        },
      }),
    ]);
    const items = within(
      screen.getByRole("list", { name: "Action options" }),
    ).getAllByRole("listitem");
    expect(items[0].textContent).toMatch(/predicted: contains/);
    expect(items[0].textContent).toMatch(/revert it/);
    expect(items[0].textContent).toMatch(/learned order 6\/6/); // history still split out
    expect(
      items[0].textContent?.match(/every symptom predicted back in band/g)
        ?.length,
    ).toBe(1); // not twice
    expect(items[1].textContent).toMatch(/leaves kpi\.exec_revenue exposed/);
    expect(items[2].textContent).toMatch(/predicted: does not contain/); // text, not colour alone
  });
});

describe("PlanApprovalCard: simulated GitHub", () => {
  it("says in one calm line that GitHub is simulated, with a link to the real pull requests", () => {
    app.github = "simulated";
    try {
      setup();
      const line = screen.getByText(/GitHub here is simulated/);
      expect(line.closest("[role=alert]")).toBeNull(); // a note, not a warning
      const link = within(line).getByRole("link", { name: /faultline-demo-infra repo/ });
      expect(link.getAttribute("href")).toBe("https://github.com/Prashant-thakur77/faultline-demo-infra/pulls?q=is%3Apr");
    } finally {
      app.github = undefined;
    }
  });

  it("says nothing about it on a server that acts on real GitHub", () => {
    app.github = "real";
    try {
      setup();
      expect(screen.queryByText(/GitHub here is simulated/)).toBeNull();
    } finally {
      app.github = undefined;
    }
  });
});
