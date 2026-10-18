import { describe, expect, it } from "vitest";
import type { GuidelineRow } from "@/lib/learned";
import { collapseProposed } from "./LearnedControls";

const row = (id: string, at: number, extra: Partial<GuidelineRow> = {}): GuidelineRow => ({
  id, text: "prefer a rollback during the freeze", family: "payment", actionKind: "flip_flag", status: "proposed",
  source: "rejection", by: null, at, incident: null, graph: null, option: null, event: null, decidedBy: null,
  decidedAt: null, ...extra,
});

describe("collapseProposed", () => {
  it("shows one proposal per reason, family and fix kind, newest first, counting the rest", () => {
    const out = collapseProposed([row("g1", 1), row("g2", 3), row("g3", 2), row("g4", 4, { actionKind: "rollback_deploy" })]);
    expect(out.map((x) => [x.g.id, x.more])).toEqual([["g4", 0], ["g2", 2]]);
  });

  it("never merges active guidelines", () => {
    const out = collapseProposed([row("a1", 1, { status: "active" }), row("a2", 2, { status: "active" })]);
    expect(out.map((x) => x.g.id)).toEqual(["a2", "a1"]);
  });
});
