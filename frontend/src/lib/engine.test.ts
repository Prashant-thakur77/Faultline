import { describe, expect, it } from "vitest";
import { INSIGHT } from "@/test/engineFixture";
import { ApiError } from "./api";
import { constraintSummary, fmtBytes, fmtEngineMs, fmtWindow, insightSummary, mergeRecent, parseInsight, tailRows } from "./engine";
import { notItemised } from "@/components/engine/EngineMemory";

describe("engine insight parser (GET /api/engine/insight)", () => {
  it("reads config, load, graphs (tenant first, clean rooms last) and the combined table", () => {
    const d = parseInsight(INSIGHT);
    expect(d.config).toMatchObject({ queryMemCapacity: 268435456, timeoutMax: 10000, timeoutDefault: 2000, threadCount: 20, maxInfoQueries: 1000 });
    expect(d.load).toEqual({ running: 0, waiting: 0 });
    expect(d.graphs.map((g) => [g.name, g.role])).toEqual([
      ["tenant_acme", "tenant"],
      ["golden_acme", "golden"],
      ["eval_acme_api_v2_s1_1_abcd", "room"],
    ]);
    const t = d.graphs[0];
    expect(t.memory).toMatchObject({ totalMb: 2, labelMatricesMb: 0, nodeAttributesMb: 1, edgeAttributesMb: 0 });
    expect(t.memory.byLabel[0]).toEqual({ name: "Node", mb: 1 });
    expect(t.telemetry.from).toBe(1792245970 * 1000); // the stream's epoch seconds, as ms
    expect(t.telemetry.queries[0]).toMatchObject({ id: "Q-META-1", kind: "template", n: 58, totalP50: 0.15, totalP95: 0.38, cachePct: 15.5 });
    expect(t.telemetry.unmapped.n).toBe(225);
    expect(t.telemetry.recent[0]).toMatchObject({ id: "Q-ONCALL-NOW", graph: "tenant_acme", totalMs: 0.94, cache: false });
    expect(t.telemetry.recent[0].at).toBe(1792252980100); // the stream id's millisecond, not the whole second
    expect(t.telemetry).toMatchObject({ overallP50: 0.3, overallP95: 3.5 });
    expect(t.constraints).toEqual({ declared: 15, operational: 15, pending: 0, missing: 0, expected: true });
    expect(d.engine).toEqual({ version: "6.0.2", digest: expect.stringMatching(/^sha256:/) });
    expect(d.templates.queries.map((q) => q.id)).toEqual(["Q-META-1", "Q-INC-1", "W-STAGE"]);
    expect(d.templates).toMatchObject({ overallP50: 0.36, overallP95: 1.9 });
    expect(d.templates.recent?.map((r) => [r.id, r.graph])).toEqual([
      ["Q-INC-1", "eval_acme_api_v2_s1_1_abcd"],
      ["Q-ONCALL-NOW", "tenant_acme"],
      ["W-STAGE", "tenant_acme"],
    ]);
  });

  it("a graph without the per-label breakdown keeps those parts unknown, not 0", () => {
    const g = parseInsight(INSIGHT).graphs.find((x) => x.name === "golden_acme")!;
    expect(g.memory.nodeAttributesMb).toBeNull();
    expect(g.memory.edgeAttributesMb).toBeNull();
    expect(notItemised(g.memory)).toBe(2); // the whole total, since no part was itemised
  });

  it("a response without graphs or templates is an error, not an empty page", () => {
    expect(() => parseInsight({ tenant: "acme" })).toThrow(ApiError);
    expect(() => parseInsight([])).toThrow(/expected an object/);
  });
});

describe("derived numbers (arithmetic on the server's own)", () => {
  it("the verdict sums memory and timeouts, names the busiest template and never combines percentiles", () => {
    const s = insightSummary(parseInsight(INSIGHT));
    expect(s.graphs).toBe(3);
    expect(s.memoryMb).toBe(7);
    expect(s.entries).toBe(1400);
    expect(s.timeouts).toBe(0);
    expect(s.busiest?.id).toBe("Q-META-1");
    expect([s.overallP50, s.overallP95]).toEqual([0.36, 1.9]);
    expect(s.slowest?.id).toBe("Q-INC-1");
    // 58×15.5% + 40×50% + 12×80% + 225×40% hits over 1,400 entries
    expect(s.cachePct).toBeCloseTo((100 * (58 * 0.155 + 40 * 0.5 + 12 * 0.8 + 225 * 0.4)) / 1400, 5);
  });

  it("the tail merges each graph's recent queries, newest first", () => {
    const r = mergeRecent(parseInsight(INSIGHT).graphs, 20);
    expect(r.map((x) => [x.id, x.graph])).toEqual([
      ["Q-INC-1", "eval_acme_api_v2_s1_1_abcd"],
      ["Q-ONCALL-NOW", "tenant_acme"],
      ["W-STAGE", "tenant_acme"],
    ]);
    expect(mergeRecent(parseInsight(INSIGHT).graphs, 1)).toHaveLength(1);
  });

  it("the tail takes the server's merge when it sends one, else merges the graphs' own", () => {
    const d = parseInsight(INSIGHT);
    expect(tailRows(d, 2).map((r) => r.id)).toEqual(["Q-INC-1", "Q-ONCALL-NOW"]);
    const old = structuredClone(INSIGHT) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    delete old.templates.recent;
    const o = parseInsight(old);
    expect(o.templates.recent).toBeNull();
    expect(tailRows(o).map((r) => r.id)).toEqual(["Q-INC-1", "Q-ONCALL-NOW", "W-STAGE"]);
  });

  it("constraints: the fewest enforced on a graph that should carry them; the audit log is expected to carry none", () => {
    const raw = structuredClone(INSIGHT) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    raw.graphs.audit_acme = { ...raw.graphs.golden_acme, constraints: { declared: 15, operational: 0, pending: 0, missing: 15, expected: false } };
    const k = constraintSummary(parseInsight(raw).graphs)!;
    expect(k).toMatchObject({ declared: 15, enforced: 15, graphs: 3, short: [], notExpected: ["audit_acme"], unreported: [] });
    raw.graphs.golden_acme.constraints = { declared: 15, operational: 14, pending: 1, missing: 0, expected: true };
    expect(constraintSummary(parseInsight(raw).graphs)).toMatchObject({ enforced: 14, short: ["golden_acme"] });
    for (const v of Object.values(raw.graphs) as Record<string, unknown>[]) delete v.constraints;
    expect(constraintSummary(parseInsight(raw).graphs)).toBeNull();
  });

  it("formats bytes, engine milliseconds and windows", () => {
    expect(fmtBytes(268435456)).toBe("256 MB");
    expect(fmtBytes(null)).toBe("–");
    expect(fmtEngineMs(0.153)).toBe("0.15 ms");
    expect(fmtEngineMs(0.0042)).toBe("0.004 ms");
    expect(fmtEngineMs(46.93)).toBe("46.9 ms");
    expect(fmtEngineMs(null)).toBe("–");
    expect(fmtWindow(2 * 3_600_000 + 29 * 60_000)).toBe("2 h 29 min");
  });
});
