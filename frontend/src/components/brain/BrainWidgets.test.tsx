import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import type { DecisionTrace, OwnerAtResult } from "@/lib/types";
import { Guardrails, OwnerHistory, TraceView } from "./BrainWidgets";

const env = { via: "", cypher: "", ms: 1, digest: "d", truncated: false, evidence_id: "ev" };

const trace: DecisionTrace = {
  trace: { ...env, template: "Q-DEC-2", params: { id: "ADR-1" }, rows: [{ id: "ADR-1", status: "superseded", head: "ADR-3", depth: 2, sources: ["docs/adr-3.md"], source_ids: ["doc-adr-3"] }] },
  chain: {
    template: "Q-DEC-CHAIN",
    params: { id: "ADR-1" },
    ms: 1,
    truncated: false,
    rows: [
      { id: "ADR-1", title: "first", status: "superseded", decided_at: 0, url: null, supersedes: [], superseded_by: ["ADR-2"] },
      { id: "ADR-2", title: "second", status: "superseded", decided_at: 1, url: null, supersedes: ["ADR-1"], superseded_by: ["ADR-3"] },
      { id: "ADR-3", title: "third", status: "active", decided_at: 2, url: null, supersedes: ["ADR-2"], superseded_by: [] },
    ],
  },
};

describe("Decision tracer", () => {
  it("lists the SUPERSEDES chain oldest first and marks the head in text, not colour only", () => {
    render(<TraceView t={trace} asked="ADR-1" />);
    const items = within(screen.getByRole("list", { name: /SUPERSEDES chain of ADR-1/ })).getAllByRole("listitem");
    expect(items.map((li) => li.textContent?.match(/ADR-\d/)?.[0])).toEqual(["ADR-1", "ADR-2", "ADR-3"]);
    expect(items[2].textContent).toMatch(/current head/);
    expect(items[1].textContent).toMatch(/supersedes ADR-1/);
    expect(screen.getByText(/the decision in force is/).textContent).toMatch(/ADR-3.*2 hops/);
    expect(screen.getByText(/docs\/adr-3\.md/)).toBeTruthy();
  });

  it("shows a tool error loudly instead of an empty chain", () => {
    render(<TraceView t={{ ...trace, trace: { error: "unavailable: FalkorDB down" } }} asked="ADR-1" />);
    expect(screen.getByRole("alert").textContent).toMatch(/trace_decision failed: unavailable/);
  });
});

describe("Ownership history", () => {
  it("shows periods, the current owner and a changed-hands badge with text", () => {
    const r: OwnerAtResult = {
      ...env,
      template: "Q-OWN-AT",
      params: {},
      rows: [
        { team: "team-a", name: "A", since: 0, until: 86_400_000, covers_at: false, current: false },
        { team: "team-b", name: "B", since: 86_400_000, until: null, covers_at: true, current: true },
      ],
      owner_then: "team-b",
      owner_now: "team-b",
      changed_hands: true,
      knew_it_then: [],
      at: 1,
    };
    render(<OwnerHistory r={r} comp="svc" />);
    expect(screen.getByText("changed hands")).toBeTruthy();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[1].textContent).toMatch(/team-b\(current\).*now/);
  });
});

describe("Guardrails", () => {
  it("reads missing guardrails and knowledge health for the tenant and groups findings by kind", async () => {
    const { calls } = stubFetch({
      "/api/brain/guardrails": {
        body: {
          missing_guardrails: { ...env, template: "Q-GAP-1", params: {}, rows: [{ id: "svc-x", name: "x", no_owner: true, no_runbook: false, tier: 1 }] },
          knowledge_health: {
            ...env,
            template: "Q-KH-1+Q-KH-2",
            params: { "Q-KH-1": { now: 1, stale_days: 90 }, "Q-KH-2": {} },
            templates: ["Q-KH-1", "Q-KH-2"],
            stale_days: 90,
            rows: [
              { kind: "stale_runbook", id: "svc-y", ref: "rb-1", tier: 1, why: "runbook rb-1 not reviewed for 120 days" },
              { kind: "stale_runbook", id: "svc-z", ref: "rb-2", tier: 2, why: "runbook rb-2 not reviewed for 99 days" },
              { kind: "missing_edge", id: "q", ref: "r", tier: null, why: "3 incidents caused at q also hit r" },
            ],
          },
        },
      },
    });
    render(
      <CypherPanelProvider>
        <Guardrails tenant="globex" />
      </CypherPanelProvider>,
    );
    await screen.findByText(/Missing guardrails \(1\)/);
    expect(calls[0].url).toContain("tenant=globex");
    expect(screen.getByText("no owner")).toBeTruthy();
    const stale = screen.getByRole("button", { name: /stale runbook/ });
    expect(stale.textContent).toMatch(/2$/);
    expect(stale.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(stale);
    await waitFor(() => expect(screen.getByText(/not reviewed for 120 days/)).toBeTruthy());
    // every query behind the card can be opened (template chips with their params)
    for (const t of ["Q-GAP-1", "Q-KH-1", "Q-KH-2"]) expect(screen.getByRole("button", { name: new RegExp(`^${t}: open the Cypher panel`) })).toBeTruthy();
  });

  it("fails loudly when the API is down", async () => {
    stubFetch({ "/api/brain/guardrails": { status: 503, body: { detail: "FalkorDB unavailable: connection refused" } } });
    render(
      <CypherPanelProvider>
        <Guardrails tenant="acme" />
      </CypherPanelProvider>,
    );
    expect((await screen.findByRole("alert")).textContent).toMatch(/guardrails unavailable: 503: FalkorDB unavailable/);
  });
});
