import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { layoutProvenance, lineage } from "@/lib/provenance";
import type { ProvenanceResponse } from "@/lib/types";
import { PROVENANCE } from "@/test/provenanceFixture";
import { ProvenanceGraph } from "./ProvenanceGraph";

// reduced motion: cards and lines appear without a framer animation that happy-dom would cancel at unmount
beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => vi.unstubAllGlobals());

function renderGraph(data: ProvenanceResponse = PROVENANCE) {
  const onOpenCall = vi.fn();
  const onOpenEvidence = vi.fn();
  render(<ProvenanceGraph data={data} onOpenCall={onOpenCall} onOpenEvidence={onOpenEvidence} />);
  return { onOpenCall, onOpenEvidence };
}

/** The `data-prov-id` of each card in a column, top to bottom. */
function column(name: RegExp): string[] {
  const list = screen.getByRole("list", { name });
  return [...list.querySelectorAll<HTMLElement>(":scope > li [data-prov-id]")].map((el) => el.dataset.provId!);
}

describe("ProvenanceGraph", () => {
  it("lays the payload out in four layers, Agent → Call → Evidence → Verdict, ordered so lines do not cross", () => {
    renderGraph();
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Agents 2", "Tool calls 5", "Evidence 4", "Verdict 1"]);
    expect(column(/^Agents/)).toEqual(["agent:telemetry-specialist-eb3eaec3", "agent:gate"]);
    // calls grouped under their agent; evidence follows the calls that produced it
    expect(column(/^Tool calls/)).toEqual([
      "run-s1-363667c4-tc0014",
      "run-s1-363667c4-tc0016",
      "run-s1-363667c4-tc0042",
      "run-s1-363667c4-tc0040",
      "run-s1-363667c4-tc0043",
    ]);
    expect(column(/^Evidence/)).toEqual(["ev_9dc2e8c800", "ev_d3ce0adb65", "ev_0d9b87053a", "ev_edbfd9c531"]);
    expect(column(/^Verdict/)).toEqual(["verdict:hyp-inc-s1-363667c4-D-pay-417"]);
    const verdict = screen.getByRole("list", { name: /^Verdict/ });
    expect(within(verdict).getByText("D-pay-417")).toBeTruthy();
    expect(within(verdict).getByText("confirmed")).toBeTruthy();
  });

  it("names the agents: a specialist by role, and the gate's own reads as the gate", () => {
    renderGraph();
    const agents = screen.getByRole("list", { name: /^Agents/ });
    expect(within(agents).getByText("Telemetry specialist")).toBeTruthy();
    expect(within(agents).getByText("gate (its own checks)")).toBeTruthy();
    expect(within(agents).getByText("gate: reads in code")).toBeTruthy();
  });

  it("hangs the graph nodes each call SAW under it as chips", () => {
    renderGraph();
    const saw = screen.getByRole("list", { name: /\(run-s1-363667c4-tc0040\) saw/ });
    expect(within(saw).getByText("payment")).toBeTruthy();
    expect(screen.queryByRole("list", { name: /\(run-s1-363667c4-tc0014\) saw/ })).toBeNull();
  });

  it("opens a call's and an evidence item's Cypher panel from their cards", () => {
    const { onOpenCall, onOpenEvidence } = renderGraph();
    const calls = screen.getByRole("list", { name: /^Tool calls/ });
    fireEvent.click(within(calls).getByRole("button", { name: /Tool call run-s1-363667c4-tc0042/ }));
    expect(onOpenCall).toHaveBeenCalledWith(PROVENANCE.nodes.find((n) => n.id === "run-s1-363667c4-tc0042"));
    const ev = screen.getByRole("list", { name: /^Evidence/ });
    fireEvent.click(within(ev).getByRole("button", { name: /ev_edbfd9c531/ }));
    expect(onOpenEvidence).toHaveBeenCalledWith(PROVENANCE.nodes.find((n) => n.id === "ev_edbfd9c531"));
  });

  it("repeats the graph as a text table: evidence, producing calls, agents, what they saw, the verdict", () => {
    renderGraph();
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      expect.stringContaining("ev_9dc2e8c800"),
      expect.stringContaining("ev_d3ce0adb65"),
      expect.stringContaining("ev_0d9b87053a"),
      expect.stringContaining("ev_edbfd9c531"),
    ]);
    const bound = within(rows[3]).getAllByRole("cell").map((c) => c.textContent);
    expect(bound[0]).toContain("run-s1-363667c4-tc0040");
    expect(bound[0]).toContain("run-s1-363667c4-tc0043");
    expect(bound[1]).toContain("gate (its own checks)");
    expect(bound[2]).toContain("payment");
    expect(bound[3]).toBe("D-pay-417");
  });

  it("says so when Q-PROV-1 returned nothing, and draws nothing", () => {
    renderGraph({ ...PROVENANCE, nodes: [], edges: [] });
    expect(screen.getByText(/returned no confirmed verdict/)).toBeTruthy();
    expect(screen.queryByRole("list", { name: /^Agents/ })).toBeNull();
  });
});

describe("layoutProvenance", () => {
  it("draws only MADE / PRODUCED_EVIDENCE / SUPPORTS lines and traces one lineage without its siblings", () => {
    const l = layoutProvenance(PROVENANCE);
    expect(new Set(l.edges.map((e) => e.rel))).toEqual(new Set(["MADE", "PRODUCED_EVIDENCE", "SUPPORTS"]));
    const lit = lineage("ev_9dc2e8c800", l.edges);
    expect([...lit.nodes].sort()).toEqual(
      [
        "agent:telemetry-specialist-eb3eaec3",
        "ev_9dc2e8c800",
        "run-s1-363667c4-tc0014",
        "verdict:hyp-inc-s1-363667c4-D-pay-417",
      ].sort(),
    );
  });

  it("is deterministic: the same payload always yields the same order", () => {
    const a = layoutProvenance(PROVENANCE);
    const b = layoutProvenance(structuredClone(PROVENANCE));
    expect(b.calls.map((n) => n.id)).toEqual(a.calls.map((n) => n.id));
    expect(b.evidence.map((n) => n.id)).toEqual(a.evidence.map((n) => n.id));
  });
});
