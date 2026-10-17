import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import type { PlanResponse } from "@/lib/types";
import { plan, stubFetch } from "@/test/fixtures";
import { NotifyCard } from "./NotifyCard";

const NOW = Date.now();

function withNotify(): PlanResponse {
  return {
    ...plan([]),
    notify_set: {
      id: "tc-n",
      evidence_id: "ev-n",
      summary: "",
      template: "Q-NOTIFY-1",
      params: { target_id: "payment" },
      at: 0,
      payload: { rows: [{ team: "t-pay", name: "Payments", owns_impacted: ["payment"], oncall: ["p-030"], impact: 3, nearest_hops: 0 }] },
    },
  } as PlanResponse;
}

const PAGES = {
  rows: [
    { id: "pg-2", incident: "inc-1", channel: "in_app", kind: "escalation", status: "sent", attempt: 2, sent_at: NOW - 30_000, ack_due_at: NOW + 270_000, person: { id: "p-031", name: "Ravi Iyer" } },
    { id: "pg-1", incident: "inc-1", channel: "slack", kind: "page", status: "escalated", attempt: 1, sent_at: NOW - 400_000, person: { id: "p-030", name: "Asha Rao" } },
  ],
  channels: [{ channel: "in_app", configured: true }, { channel: "slack", configured: true }],
};

describe("NotifyCard: real pages for the incident", () => {
  it("lists who was actually paged for this incident, with the ack state (GET /api/pages?incident=)", async () => {
    const { calls } = stubFetch({ "/api/pages?": { body: PAGES } });
    render(
      <CypherPanelProvider>
        <NotifyCard plan={withNotify()} error={null} stage="AWAITING_APPROVAL" mode="live" onOpenPlanItem={vi.fn()} incidentId="inc-1" />
      </CypherPanelProvider>,
    );
    const list = await screen.findByRole("list", { name: "Pages sent for this incident" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("awaiting ack")).toBeTruthy();
    expect(within(items[1]).getByText("escalated")).toBeTruthy();
    expect(within(items[1]).getByText(/Slack/)).toBeTruthy();
    expect(screen.getByText("2 pages · 0 acked · 1 waiting")).toBeTruthy();
    expect(screen.getByText("Delivered in-app and by Slack.")).toBeTruthy();
    expect(calls.some((c) => c.url.includes("/api/pages?tenant=acme&incident=inc-1"))).toBe(true);
  });

  it("replay never calls the pager", () => {
    const { calls } = stubFetch({});
    render(
      <CypherPanelProvider>
        <NotifyCard plan={withNotify()} error={null} stage="RESOLVED" mode="replay" onOpenPlanItem={vi.fn()} incidentId="inc-1" />
      </CypherPanelProvider>,
    );
    expect(screen.queryByText("Pages sent")).toBeNull();
    expect(calls.filter((c) => c.url.includes("/api/pages"))).toHaveLength(0);
  });

  it("an empty answer is said plainly", async () => {
    stubFetch({ "/api/pages?": { body: { rows: [], channels: [] } } });
    render(
      <CypherPanelProvider>
        <NotifyCard plan={withNotify()} error={null} stage="AWAITING_APPROVAL" mode="live" onOpenPlanItem={vi.fn()} incidentId="inc-1" />
      </CypherPanelProvider>,
    );
    expect(await screen.findByText("No page sent for this incident yet.")).toBeTruthy();
    expect(screen.getByText("No external channel configured: pages are in-app only.")).toBeTruthy();
  });
});
