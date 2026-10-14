import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { IncidentView, Obligations } from "@/lib/types";
import { fmtBreach, ObligationsCard } from "./ObligationsCard";

const o: Obligations = {
  urgent: true,
  reason: "slo-checkout (checkout) runs out of error budget in ~42 min at 12.0x burn (40% of budget left); under the 60-min paging line",
  page_within_min: 60,
  breach: { slo: "slo-checkout", service: "checkout", breach_in_min: 42, burn: 12, budget_remaining: 0.4 },
  revenue_at_risk: 120000,
  customers_reached: 3,
  slos: [{ slo: "slo-checkout", service: "checkout", objective: 0.999, window_days: 30, error_rate: 0.012, burn: 12, budget_remaining: 0.4, breach_in_min: 42, status: "burning" }],
  customers: [{ customer: "cus-1", name: "Big Co", mrr: 100000, through: ["checkout"], via: ["api"], path: ["payment", "checkout"] }],
  evidence_id: "ev_obl",
};

const view = (obligations: unknown, outcome = "CONFIRMED") =>
  ({ run: { outcome }, report: { obligations } }) as unknown as IncidentView;

describe("ObligationsCard", () => {
  it("shows time to breach, customers reached and an urgent badge with text", () => {
    render(<ObligationsCard view={view(o)} mode="live" onOpenEvidence={() => {}} />);
    expect(screen.getByText("URGENT: page now")).toBeTruthy();
    expect(screen.getAllByText("~42 min").length).toBe(2); // the soonest breach, and its SLO row
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText(/120,000 MRR at risk/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Evidence ev_obl/ })).toBeTruthy();
  });

  it("an unknown urgency (clock failed) is neutral, never 'not urgent'", () => {
    render(<ObligationsCard view={view({ ...o, urgent: null })} mode="live" onOpenEvidence={() => {}} />);
    expect(screen.getByText("urgency unknown")).toBeTruthy();
    expect(screen.queryByText("not urgent")).toBeNull();
  });

  it("says when a recording predates the clock instead of showing numbers", () => {
    render(<ObligationsCard view={view({})} mode="replay" onOpenEvidence={() => {}} />);
    expect(screen.getByText(/before the obligation clock existed/)).toBeTruthy();
  });

  it("formats breach times", () => {
    expect(fmtBreach(null)).toBe("no breach projected");
    expect(fmtBreach(150)).toBe("~2.5 h");
    expect(fmtBreach(4320)).toBe("~3.0 days");
  });
});
