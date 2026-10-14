import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import { ColdWarmCard } from "./ColdWarmCard";
import { RecallTable, RunbooksCard } from "./MemoryView";

describe("Memory tab", () => {
  it("recall shows similarity, recency and salience as separate columns", () => {
    render(
      <RecallTable
        rows={[
          { id: "inc-h1", title: "checkout 5xx", distance: 0.1, similarity: 0.9, salience: 1.5, recency: 0.25, opened_at: 0, shared: ["sym-a"], fixes: ["flip_flag"], cause_targets: [], postmortem: [] },
        ]}
      />,
    );
    const head = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(head).toEqual(["Incident", "Similarity", "Recency", "Salience", "Shared symptom", "Fixed by"]);
    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell").map((c) => c.textContent);
    expect(cells.slice(1, 6)).toEqual(["0.9", "0.25", "1.5", "sym-a", "feature flag"]);
  });

  it("derived runbooks come with their support count and DERIVED_FROM postmortems", () => {
    render(
      <CypherPanelProvider>
        <RunbooksCard
          graph="tenant_acme"
          tenant="acme"
          incident={null}
          r={{
            template: "Q-MEM-RB",
            params: {},
            ms: 1,
            truncated: false,
            rows: [
              { id: "rb-d", title: "Derived: flip flag x (worked 4×)", source: "derived", support: 4, salience: 1, reviewed_at: null, for_ids: ["sym-a"], derived_from: ["pm-1", "pm-2", "pm-3", "pm-4"] },
              { id: "rb-h", title: "Payment runbook", source: "human", support: 0, salience: 1, reviewed_at: null, for_ids: ["payment"], derived_from: [] },
            ],
          }}
        />
      </CypherPanelProvider>,
    );
    expect(screen.getByRole("heading", { name: /Runbooks in effect \(1 derived\)/ })).toBeTruthy();
    expect(screen.getByText("support 4")).toBeTruthy();
    expect(screen.getByText(/DERIVED_FROM 4 postmortems/)).toBeTruthy();
    expect(screen.getByText("derived")).toBeTruthy();
    expect(screen.getByText("human")).toBeTruthy();
  });

  it("cold vs warm copies the eval's numbers verbatim (value in text next to each bar)", async () => {
    stubFetch({
      "/evals/summary.json": {
        body: {
          source: "evals/results/latest.json",
          run: "run_0010.json",
          generated_from_mtime: null,
          values: { "memory.cold_prior": 0.7681, "memory.warm_prior": 0.8423, "memory.trials": 3, "memory.gate_verdicts_identical": true },
        },
      },
    });
    render(<ColdWarmCard />);
    expect(await screen.findByText("0.7681")).toBeTruthy();
    expect(screen.getByText("0.8423")).toBeTruthy();
    expect(screen.getAllByText(/gate verdicts identical cold vs warm/)[0]).toBeTruthy();
    expect(screen.getByText(/run_0010\.json/)).toBeTruthy();
    // a key the eval did not produce is said to be missing, never filled in
    expect(screen.getAllByText(/not in this eval/).length).toBeGreaterThan(0);
  });

  it("says when the eval results cannot be read", async () => {
    stubFetch({ "/evals/summary.json": { status: 404, body: {} } });
    render(<ColdWarmCard />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Eval results unavailable/);
  });
});
