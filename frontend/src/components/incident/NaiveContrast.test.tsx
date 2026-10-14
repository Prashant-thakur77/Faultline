import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ContrastChange, ContrastResponse } from "@/lib/types";
import { ContrastView, fmtBeforeOnset } from "./NaiveContrast";

const ch = (over: Partial<ContrastChange>): ContrastChange => ({
  deploy: "D-a",
  kind: "deploy",
  target: "svc-a",
  at: 1000,
  before_onset_ms: 180_000,
  pagerank: 0.5,
  gate_status: null,
  gate_reason: null,
  confirmed: false,
  ...over,
});

const base: ContrastResponse = {
  graph: "eval_x",
  onset_at: 2000,
  confirmed: "D-b",
  outcome: "CONFIRMED",
  naive: ["D-a"],
  changes: [
    ch({ deploy: "D-a", gate_status: "eliminated", gate_reason: "G5: max flow 0.02 < needed 0.24" }),
    ch({ deploy: "D-b", target: "svc-b", gate_status: "confirmed", gate_reason: "gate passed", confirmed: true, at: 900, before_onset_ms: 240_000 }),
    ch({ deploy: "D-c", target: "svc-c", at: 800, before_onset_ms: 300_000 }),
  ],
  window_changes: { template: "Q-SUS-2", evidence_id: "ev_1", params: { onset: 2000, window_ms: 1 }, summary: "3 changes" },
  rank_causes: null,
  unavailable: null,
};

describe("ContrastView (naive recency vs the gate)", () => {
  it("shows the naive pick next to the gate's verdict and flags the disagreement", () => {
    render(<ContrastView data={base} />);
    expect(screen.getByText("Naive recency would blame").parentElement?.textContent).toContain("D-a");
    expect(screen.getByText(/Faultline.s gate decided/).parentElement?.textContent).toContain("D-b");
    expect(screen.getByRole("status").textContent).toMatch(/naive would have blamed the wrong change/);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.querySelector("td")?.textContent)).toEqual(["D-anaive pick", "D-b", "D-c"]);
    expect(rows[0].textContent).toMatch(/eliminated.*G5: max flow/);
    expect(rows[2].textContent).toMatch(/not hypothesised/);
  });

  it("says when they agree, and when a tie makes naive a guess", () => {
    const { rerender } = render(<ContrastView data={{ ...base, naive: ["D-b"] }} />);
    expect(screen.getByRole("status").textContent).toMatch(/they agree/);
    rerender(<ContrastView data={{ ...base, naive: ["D-a", "D-b"] }} />);
    expect(screen.getByRole("status").textContent).toMatch(/naive would have to guess: 2 tied changes/);
    expect(screen.getAllByText("naive pick")).toHaveLength(2);
  });

  it("states the reason when the run recorded nothing to contrast (no fake rows)", () => {
    render(<ContrastView data={{ ...base, changes: [], naive: [], unavailable: "this run recorded no window_changes result" }} />);
    expect(screen.getByText(/recorded no window_changes result/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("formats the time before onset", () => {
    expect(fmtBeforeOnset(45_000)).toBe("45 s");
    expect(fmtBeforeOnset(180_000)).toBe("3 min");
    expect(fmtBeforeOnset(252_000)).toBe("4 min 12 s");
    expect(fmtBeforeOnset(null)).toBe("–");
  });
});
