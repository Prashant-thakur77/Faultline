import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import { OnCallView } from "./OnCallView";

const NOW = Date.now();

const PAGES = {
  rows: [
    {
      id: "pg-1",
      incident: "inc-1",
      incident_title: "checkout 5xx",
      channel: "in_app",
      kind: "page",
      urgency: "urgent",
      sent_at: NOW - 120_000,
      ack_due_at: NOW + 180_000,
      status: "sent",
      attempt: 1,
      person: { id: "p-030", name: "Asha Rao" },
    },
    {
      id: "pg-0",
      incident: "inc-0",
      channel: "in_app",
      kind: "page",
      urgency: "normal",
      sent_at: NOW - 3_600_000,
      status: "acked",
      attempt: 1,
      person: { id: "p-031", name: "Ravi Iyer" },
      acked_by: { id: "p-031", name: "Ravi Iyer" },
      acked_at: NOW - 3_500_000,
      ack_via: "in_app",
    },
  ],
  template: "Q-PAGE-LIST",
  params: { tenant: "acme" },
  channels: [{ channel: "in_app", configured: true }],
};

const ROUTES = {
  "/api/pages/pg-1/ack": { body: { id: "pg-1", status: "acked" } },
  "/api/pages/pg-1?": {
    body: {
      page: PAGES.rows[0],
      chain: [{ id: "pg-1", person: { id: "p-030", name: "Asha Rao" }, status: "sent", attempt: 1, channel: "in_app" }],
    },
  },
  "/api/pages?": { body: PAGES },
  "/api/oncall/now": {
    body: { rows: [{ team: "t-payments", team_name: "Payments", person: { id: "p-030", name: "Asha Rao" }, from: NOW - 1e6, to: NOW + 1e6 }], template: "Q-ONCALL-NOW", params: { now: NOW } },
  },
  "/api/contracts": {
    body: {
      rows: [
        {
          id: "ct-1",
          family: "fam-7",
          action_kind: "flip_flag",
          params_hash: "abcdef0123456789",
          max_uses: 3,
          uses: 1,
          expires_at: NOW + 6 * 86_400_000,
          granted_at: NOW - 86_400_000,
          status: "active",
          granted_by: { id: "p-030", name: "Asha Rao" },
          used_in: [{ incident: "inc-0", at: NOW - 3_600_000, verdict: "APPLIED" }],
        },
        { id: "ct-0", family: "fam-2", action_kind: "rollback_deploy", max_uses: 1, uses: 1, status: "exhausted" },
      ],
      template: "Q-CONTRACT-LIST",
      params: {},
    },
  },
  "/api/oncall/stats": { body: { mtta_s: 240, mttr_s: 1500, people_paged: 2, handled_under_contract: 1, pages: 3, template: "Q-ONCALL-STATS", params: { days: 7 } } },
  "/api/oncall/report": {
    body: {
      from: NOW - 12 * 3_600_000,
      to: NOW,
      incidents: [{ id: "inc-1", title: "checkout 5xx", status: "RUNNING" }],
      pages: PAGES.rows,
      acks: [{ page: "pg-0", by: "p-031", at: NOW - 3_500_000 }],
      actions: [],
      contract_uses: [{ contract: "ct-1", incident: "inc-0", verdict: "APPLIED" }],
      handoffs: [],
      template: "Q-SHIFT-REPORT",
      params: {},
    },
  },
  "/api/templates/": { body: { id: "Q", cypher: "MATCH (n) RETURN n" } },
};

function renderView() {
  return render(
    <CypherPanelProvider>
      <OnCallView />
    </CypherPanelProvider>,
  );
}

describe("/oncall", () => {
  it("leads with the verdict, then stats, the pager, who is on call and the contracts, each from its own endpoint", async () => {
    const { calls } = stubFetch(ROUTES);
    renderView();
    expect(await screen.findByRole("heading", { name: "1 page waiting for an ack" })).toBeTruthy();
    expect(screen.getByText(/1 urgent · oldest sent 2 min ago/)).toBeTruthy();

    // stats: the server's numbers, formatted only
    const stats = screen.getByRole("region", { name: /The last 7 days/ });
    await within(stats).findByText("4 min");
    expect(within(stats).getByText("25 min")).toBeTruthy();
    expect(within(stats).getByText("Handled while you slept")).toBeTruthy();

    // pager: status is chip + icon + words, the channel note is the API's own
    const pager = screen.getByRole("region", { name: "Pager inbox" });
    const waiting = within(pager).getByRole("list", { name: "Pages waiting for an ack" });
    expect(within(waiting).getAllByRole("listitem")).toHaveLength(1);
    expect(within(waiting).getByText("awaiting ack")).toBeTruthy();
    expect(within(waiting).getByText("urgent")).toBeTruthy();
    expect(within(pager).getByText("No external channel configured: pages are in-app only.")).toBeTruthy();
    fireEvent.click(within(pager).getByRole("button", { name: /^All · 2/ }));
    expect(within(pager).getByText(/acked by Ravi Iyer/)).toBeTruthy();
    expect(within(pager).getByRole("button", { name: /Q-PAGE-LIST: open the Cypher panel for the pager inbox/ })).toBeTruthy();

    // on call now
    const now = screen.getByRole("region", { name: "On call now" });
    expect(within(now).getByText("1 of 1 team covered")).toBeTruthy();
    expect(within(now).getByText("Asha Rao")).toBeTruthy();

    // contracts: active with uses and expiry; past ones folded
    const contracts = screen.getByRole("region", { name: "Contracts" });
    const active = within(contracts).getByRole("list", { name: "Active contracts" });
    expect(within(active).getByText("1 of 3 used · 2 left")).toBeTruthy();
    expect(within(active).getByText(/expires in (5|6) d/)).toBeTruthy();
    expect(within(contracts).getByRole("button", { name: /Past contracts/ }).getAttribute("aria-expanded")).toBe("false");

    // shift report counts
    const shift = screen.getByRole("region", { name: "Shift report" });
    const tiles = within(await within(shift).findByRole("list", { name: "What happened in the window" })).getAllByRole("listitem");
    expect(tiles.map((t) => t.textContent)).toEqual(["Incidents1", "Pages2", "Acks1", "Actions0", "Under contract1", "Hand-offs0"]);
    const incTile = within(tiles[0]).getByRole("button");
    expect(incTile.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(incTile);
    expect(within(within(shift).getByRole("list", { name: "Incidents" })).getByText("checkout 5xx")).toBeTruthy();
    expect(within(tiles[3]).queryByRole("button")).toBeNull(); // nothing to open: a tile, not a button
    expect(calls.some((c) => /\/api\/oncall\/report\?tenant=acme&from=\d+&to=\d+/.test(c.url))).toBe(true);
    expect(calls.some((c) => c.url.includes("/api/oncall/stats?tenant=acme&days=7"))).toBe(true);
  });

  it("acks a page from the inbox (POST /api/pages/{id}/ack) and re-reads the pager", async () => {
    const { calls } = stubFetch(ROUTES);
    renderView();
    const ack = await screen.findByRole("button", { name: "Ack the page to Asha Rao (p-030)" });
    const before = calls.filter((c) => c.url.includes("/api/pages?")).length;
    fireEvent.click(ack);
    expect(await screen.findByText("Acked: the escalation stops here.")).toBeTruthy();
    const post = calls.find((c) => c.url.includes("/api/pages/pg-1/ack"))!;
    expect(post.url).toContain("?tenant=acme");
    expect(post.init?.method).toBe("POST");
    expect(JSON.parse(String(post.init?.body))).toEqual({});
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/api/pages?")).length).toBeGreaterThan(before));
  });

  it("uses the ack token the server handed this console, never showing it", async () => {
    const withToken = { ...PAGES, rows: [{ ...PAGES.rows[0], ack_token: "tok.signed.123" }, PAGES.rows[1]] };
    const { calls } = stubFetch({ ...ROUTES, "/api/pages?": { body: withToken } });
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Ack the page to Asha Rao/ }));
    await screen.findByText("Acked: the escalation stops here.");
    const post = calls.find((c) => c.url.includes("/api/pages/pg-1/ack"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ token: "tok.signed.123" });
    expect(document.body.textContent).not.toContain("tok.signed.123");
  });

  it("a refused ack opens the approver key field and says why", async () => {
    stubFetch({ ...ROUTES, "/api/pages/pg-1/ack": { status: 403, body: { detail: "approver key required" } } });
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Ack the page to Asha Rao/ }));
    expect(await screen.findByLabelText(/Approver key \(sent with this ack only/)).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/Ack refused: approver key required \(HTTP 403\)/);
  });

  it("reads the escalation chain on first open", async () => {
    const { calls } = stubFetch(ROUTES);
    renderView();
    const toggle = await screen.findByRole("button", { name: /Escalation chain/ });
    expect(calls.some((c) => c.url.includes("/api/pages/pg-1?"))).toBe(false);
    fireEvent.click(toggle);
    const chain = await screen.findByRole("list", { name: "Escalation chain of pg-1" });
    expect(within(chain).getByText(/Attempt 1/)).toBeTruthy();
  });

  it("fails loudly per panel when the on-call API is not deployed (FastAPI's bare 404)", async () => {
    stubFetch({
      "/api/pages": { status: 404, body: { detail: "Not Found" } },
      "/api/oncall/now": { status: 404, body: { detail: "Not Found" } },
      "/api/contracts": { status: 404, body: { detail: "Not Found" } },
      "/api/oncall/stats": { status: 404, body: { detail: "Not Found" } },
      "/api/oncall/report": { status: 404, body: { detail: "Not Found" } },
    });
    renderView();
    expect(await screen.findByRole("heading", { name: "On-call is not on this server: its API has no pager endpoint" })).toBeTruthy();
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBe(5));
    const texts = screen.getAllByRole("alert").map((a) => a.textContent);
    expect(texts.every((t) => /this API has no such endpoint \(HTTP 404\)/.test(t ?? ""))).toBe(true);
    // nothing is filled in: no tiles with numbers, no people, no pages
    expect(screen.queryByText("Asha Rao")).toBeNull();
    expect(screen.queryByText("awaiting ack")).toBeNull();
  });

  it("says when the API does not report its channels, and when nothing waits", async () => {
    stubFetch({ ...ROUTES, "/api/pages?": { body: [PAGES.rows[1]] } });
    renderView();
    expect(await screen.findByRole("heading", { name: "All quiet: no page waits for an ack" })).toBeTruthy();
    expect(screen.getByText("This API does not report its delivery channels.")).toBeTruthy();
    expect(screen.getByText(/Nothing waits for an ack/)).toBeTruthy();
  });

  it("revokes a contract in two clicks", async () => {
    const { calls } = stubFetch({ "/api/contracts/ct-1/revoke": { body: { id: "ct-1", status: "revoked" } }, ...ROUTES });
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Revoke contract ct-1" }));
    const group = screen.getByRole("group", { name: "Confirm revoking ct-1" });
    expect(within(group).getByText(/The next repeat pages a human again/)).toBeTruthy();
    fireEvent.click(within(group).getByRole("button", { name: /Yes, revoke/ }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/api/contracts/ct-1/revoke?tenant=acme") && c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.url.includes("/revoke"))!;
    expect((post.init?.headers as Record<string, string>)["X-Faultline-Approver-Key"]).toBeUndefined();
  });

  it("records a hand-off note (POST /api/handoffs) with the person and the optional incident", async () => {
    const { calls } = stubFetch({ "/api/handoffs": { body: { id: "ho-1", at: NOW } }, ...ROUTES });
    renderView();
    const shift = await screen.findByRole("region", { name: "Shift report" });
    const submit = within(shift).getByRole("button", { name: /Record hand-off/ }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(shift).getByLabelText("To (person id)"), { target: { value: "p-031" } });
    fireEvent.change(within(shift).getByLabelText("Incident (optional)"), { target: { value: "inc-1" } });
    fireEvent.change(within(shift).getByLabelText(/^Note/), { target: { value: "inc-1 still open; flag off holds" } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    expect(await within(shift).findByText(/recorded/)).toBeTruthy();
    const post = calls.find((c) => c.url.includes("/api/handoffs"))!;
    expect(post.url).toContain("?tenant=acme");
    expect(JSON.parse(String(post.init?.body))).toEqual({ note: "inc-1 still open; flag off holds", to: "p-031", incident: "inc-1" });
  });
});
