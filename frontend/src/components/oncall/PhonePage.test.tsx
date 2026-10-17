import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import { PhonePage } from "./PhonePage";

const NOW = Date.now();

const DETAIL = {
  page: {
    id: "pg-1",
    incident: "inc-1",
    channel: "telegram",
    kind: "page",
    urgency: "urgent",
    sent_at: NOW - 60_000,
    ack_due_at: NOW + 240_000,
    status: "sent",
    attempt: 2,
    person: { id: "p-030", name: "Asha Rao" },
  },
  incident: { id: "inc-1", title: "Checkout is failing", line: "Deploy d-9 turned paymentGate on; payments time out.", cause: "d-9" },
  proof: { nodes: ["d-9", "payment-api", "checkout"], rels: ["CHANGED", "CALLS"], template: "Q-PATH-1", params: { src: "d-9" } },
  who_fixes: [{ person: "p-030", name: "Asha Rao", score: 0.92, reasons: ["owns payment-api", "on call"] }, { person: "p-031", name: "Ravi Iyer", score: 0.4, reasons: [] }],
  chain: [
    { id: "pg-0", person: { id: "p-029", name: "Lee" }, status: "escalated", attempt: 1, channel: "in_app" },
    { id: "pg-1", person: { id: "p-030", name: "Asha Rao" }, status: "sent", attempt: 2, channel: "telegram" },
  ],
  obligations: { breach: { breach_in_min: 42, slo: "slo-checkout-99" } },
};

function renderPage(token: string | null, routes: Record<string, { status?: number; body: unknown }>) {
  const stub = stubFetch(routes);
  render(
    <CypherPanelProvider>
      <PhonePage pageId="pg-1" token={token} />
    </CypherPanelProvider>,
  );
  return stub;
}

describe("/oncall/page/[id] (phone first)", () => {
  it("shows the verdict line, time to breach, ack window, proof path, who fixes and the escalation", async () => {
    renderPage("tok-abcdefgh", { "/api/pages/pg-1": { body: DETAIL } });
    expect(await screen.findByRole("heading", { level: 1, name: "Checkout is failing" })).toBeTruthy();
    expect(screen.getByText("Deploy d-9 turned paymentGate on; payments time out.")).toBeTruthy();
    expect(screen.getByText("~42 min")).toBeTruthy();
    expect(screen.getByText(/ack due in [34]:\d\d/)).toBeTruthy();
    const head = screen.getByRole("banner");
    expect(within(head).getByText("urgent")).toBeTruthy();
    expect(within(head).getByText("awaiting ack")).toBeTruthy();
    const proof = screen.getByRole("list", { name: "Proof path, cause first" });
    expect(within(proof).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringMatching(/^d-9 \(cause\)CHANGED$/),
      expect.stringMatching(/^payment-apiCALLS$/),
      "checkout",
    ]);
    expect(screen.getByRole("button", { name: /Q-PATH-1: open the Cypher panel for the proof path/ })).toBeTruthy();
    const who = screen.getByRole("list", { name: "People ranked by the graph" });
    expect(within(who).getAllByRole("listitem")).toHaveLength(2);
    expect(within(who).getByText("owns payment-api · on call")).toBeTruthy();
    const chain = screen.getByRole("list", { name: "Escalation chain of pg-1" });
    expect(within(chain).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Open the incident/ }).getAttribute("href")).toBe("/incidents/inc-1?tenant=acme");
  });

  it("acks with the link's signed token", async () => {
    const { calls } = renderPage("tok-abcdefgh", { "/api/pages/pg-1/ack": { body: { status: "acked" } }, "/api/pages/pg-1": { body: DETAIL } });
    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge this page" }));
    expect(await screen.findByText("Acked: the escalation stops here.")).toBeTruthy();
    const post = calls.find((c) => c.url.includes("/ack"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ token: "tok-abcdefgh" });
  });

  it("without a token it says the key will be asked for, and a refused ack opens the key field", async () => {
    renderPage(null, { "/api/pages/pg-1/ack": { status: 401, body: { detail: "token or approver key required" } }, "/api/pages/pg-1": { body: DETAIL } });
    expect(await screen.findByText(/This link carries no ack token/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge this page" }));
    expect(await screen.findByLabelText(/Approver key/)).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/This view has no link token; enter the approver key/);
  });

  it("an acked page shows who acked and no Ack button", async () => {
    renderPage("tok-abcdefgh", {
      "/api/pages/pg-1": { body: { ...DETAIL, page: { ...DETAIL.page, status: "acked", acked_by: { id: "p-030", name: "Asha Rao" }, acked_at: NOW - 1000 } } },
    });
    expect(await screen.findByText("Acked: the escalation stopped.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Acknowledge this page" })).toBeNull();
    expect(screen.getByText("by Asha Rao")).toBeTruthy();
  });

  it("an unknown page and a missing endpoint are said differently", async () => {
    renderPage(null, { "/api/pages/pg-1": { status: 404, body: { detail: "unknown page pg-1" } } });
    expect((await screen.findByRole("alert")).textContent).toBe("No page pg-1 in tenant_acme: unknown page pg-1");
  });

  it("a missing endpoint says the on-call backend is not deployed", async () => {
    renderPage(null, { "/api/pages/pg-1": { status: 404, body: { detail: "Not Found" } } });
    expect((await screen.findByRole("alert")).textContent).toMatch(/this API has no such endpoint \(HTTP 404\)/);
  });
});
