import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CREW, GATE_RUNS } from "@/test/crewFixture";
import type { GateRun } from "@/lib/types";
import { CrewBoard } from "./CrewBoard";

function renderBoard(over: Partial<Parameters<typeof CrewBoard>[0]> = {}) {
  const onOpenCall = vi.fn();
  const onOpenCheck = vi.fn();
  const onOpenQuery = vi.fn();
  render(
    <CrewBoard
      crew={CREW}
      gateRuns={GATE_RUNS}
      onOpenCall={onOpenCall}
      onOpenCheck={onOpenCheck}
      onOpenQuery={onOpenQuery}
      {...over}
    />,
  );
  return { onOpenCall, onOpenCheck, onOpenQuery };
}

function lanes(): HTMLElement[] {
  const ol = screen.getByRole("list", { name: "Crew steps in hand-off order" });
  return [...ol.querySelectorAll<HTMLElement>(":scope > li")];
}

function lane(name: string): HTMLElement {
  const hit = lanes().find((li) => within(li).getAllByRole("heading", { level: 3 })[0].textContent === name);
  if (!hit) throw new Error(`no lane ${name}`);
  return hit;
}

describe("CrewBoard", () => {
  it("lays the crew steps out in hand-off order (NEXT edges), not payload order", () => {
    renderBoard();
    const names = lanes().map((li) => within(li).getAllByRole("heading", { level: 3 })[0].textContent);
    // the fixture stores the steps reversed: this order can only come from `after`
    expect(names).toEqual([
      "Triage",
      "Historian",
      "Cartographer",
      "Profiler",
      "Lead investigator",
      "Gatekeeper",
      "Containment",
      "Dispatcher",
      "Planner",
    ]);
    expect(within(lane("Historian")).getByText(/hands to/).textContent).toContain("Cartographer");
    expect(screen.getByText(/Every step below is a record in FalkorDB/)).toBeTruthy();
  });

  it("marks roles honestly: deterministic, model optional, and the gate decides in code", () => {
    renderBoard();
    expect(within(lane("Triage")).getByText("deterministic")).toBeTruthy();
    expect(within(lane("Lead investigator")).getByText("model optional")).toBeTruthy();
    expect(within(lane("Gatekeeper")).getByText("code: decides")).toBeTruthy();
    expect(within(lane("Historian")).getByText("RECALL")).toBeTruthy();
    expect(within(lane("Historian")).getByText("62 ms")).toBeTruthy();
  });

  it("groups the five specialists inside the lead's lane with status, suspects and unknowns", () => {
    renderBoard();
    const lead = lane("Lead investigator");
    const grid = within(lead).getByRole("list", { name: "Specialists dispatched in parallel" });
    const specs = [...grid.querySelectorAll<HTMLElement>(":scope > li")];
    expect(specs.map((li) => within(li).getByRole("heading", { level: 4 }).textContent)).toEqual([
      "Topology specialist",
      "Telemetry specialist",
      "Data specialist",
      "Change specialist",
      "Code specialist",
    ]);
    const data = specs[2];
    expect(within(data).getByText("insufficient")).toBeTruthy();
    expect(within(data).getByText(/no KPI symptom/)).toBeTruthy();
    expect(within(data).getByText("names no suspect")).toBeTruthy();
    const code = specs[4];
    expect(within(code).getByText("complete")).toBeTruthy();
    expect(within(within(code).getByRole("list", { name: /Suspects/ })).getByText("D-pay-417")).toBeTruthy();
    // specialists are never lanes of their own
    expect(lanes().some((li) => /specialist$/.test(within(li).getAllByRole("heading", { level: 3 })[0].textContent ?? ""))).toBe(false);
    expect(within(lead).getByText(/their reports converge/).textContent).toContain("Gatekeeper");
  });

  it("shows the gate runs in the Gatekeeper's lane with each rejected candidate's first failing check", () => {
    const { onOpenCheck } = renderBoard();
    const gate = lane("Gatekeeper");
    const runs = within(gate).getByRole("list", { name: "Gate runs, candidate by candidate" });
    const rec = [...runs.querySelectorAll<HTMLElement>(":scope > li")].find((li) => li.textContent?.includes("D-rec-12"))!;
    expect(within(rec).getByText("rejected")).toBeTruthy();
    const fail = within(rec).getByRole("button", { name: /G2 path failed: G2: no path to any primary symptom/ });
    fireEvent.click(fail);
    const run = GATE_RUNS.find((g) => g.cause === "D-rec-12")!;
    expect(onOpenCheck).toHaveBeenCalledWith(run, run.checks[0]);
    const email = [...runs.querySelectorAll<HTMLElement>(":scope > li")].find((li) => li.textContent?.includes("D-email-88"))!;
    expect(within(email).getByRole("button", { name: /G5 sufficiency failed: G5: max flow/ })).toBeTruthy();
  });

  it("says 'not evaluable' for a G7 check the gate could not evaluate", () => {
    const runs: GateRun[] = GATE_RUNS.map((g) =>
      g.origin === "confirm"
        ? { ...g, checks: g.checks.map((c) => (c.name === "G7 agreement" ? { ...c, passed: null, detail: "one channel only" } : c)) }
        : g,
    );
    renderBoard({ gateRuns: runs });
    expect(within(lane("Gatekeeper")).getByRole("button", { name: /G7 agreement not evaluable: one channel only/ })).toBeTruthy();
  });

  it("opens a call's Cypher panel from its chip, and the crew query from the header", () => {
    const { onOpenCall, onOpenQuery } = renderBoard();
    const hist = lane("Historian");
    const calls = within(hist).getByRole("list", { name: /Graph calls by Historian/ });
    fireEvent.click(within(calls).getAllByRole("button")[0]);
    const step = CREW.steps.find((s) => s.role === "historian")!;
    expect(onOpenCall).toHaveBeenCalledWith(step.calls[0], step);
    fireEvent.click(screen.getByRole("button", { name: /Q-CREW-1/ }));
    expect(onOpenQuery).toHaveBeenCalledWith("Q-CREW-1");
  });

  it("shows a quiet note when the run did not record a crew", () => {
    renderBoard({ crew: undefined });
    expect(screen.getByText("crew not recorded in this run")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Crew steps in hand-off order" })).toBeNull();
  });
});
