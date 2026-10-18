import { describe, expect, it } from "vitest";
import { buildGraphModel } from "./graphModel";
import {
  DETAIL_ZOOM,
  LABEL_PX,
  boundsOf,
  boundsWithCaptions,
  chipSide,
  chooseFit,
  cutLabels,
  fitCandidates,
  keyNodeIds,
  labelLod,
  placeCaptions,
  preflightEmphasis,
  type FitRect,
} from "./graphLabels";
import { COL_W } from "./layout";
import type { GraphResponse } from "./types";

// A small failure-flow graph: change D1 → a → b (proof, b is the symptom), a rejected change D2 → c → d → e.
const graph: GraphResponse = {
  graph: "tenant_t",
  nodes: ["a", "b", "c", "d", "e", "x"].map((id) => ({ id, label: id === "e" ? "KPI" : "Service", tier: 1, betweenness: 0 })),
  edges: [
    { source: "a", target: "b", cap: 1, domain: "service" },
    { source: "c", target: "d", cap: 0.02, domain: "service" },
    { source: "d", target: "e", cap: 1, domain: "service" },
    { source: "x", target: "a", cap: 1, domain: "service" },
  ],
};
const model = buildGraphModel(
  graph,
  {
    proof: { cause: "D1", chain: ["D1", "a", "b"], source: "report" },
    rejected: [{ cause: "D2", origin: "confirm", gateRunId: "g2", failed: [], chain: ["D2", "c", "d", "e"] }],
  },
  ["b"],
  new Map(),
);

describe("labelLod", () => {
  it("keeps the full node text at or above the detail zoom", () => {
    expect(labelLod(DETAIL_ZOOM, { w: 156, h: 40 })).toEqual({ mode: "detail" });
    expect(labelLod(1.6, { w: 156, h: 40 })).toEqual({ mode: "detail" });
    expect(labelLod(Number.NaN, { w: 156, h: 40 })).toEqual({ mode: "detail" });
  });

  it("counter-scales below it so a name prints at LABEL_PX on screen, inside the box only when it fits", () => {
    const mid = labelLod(0.5, { w: 156, h: 40 });
    expect(mid).toEqual({ mode: "compact", inv: 2, nameInBox: true });
    if (mid.mode === "compact") expect(LABEL_PX * mid.inv * 0.5).toBe(LABEL_PX);
    // a phone fit (~0.2): a 156 px box is 31 px on screen, too small for a readable name
    expect(labelLod(0.2, { w: 156, h: 40 })).toMatchObject({ mode: "compact", nameInBox: false });
  });
});

describe("chipSide", () => {
  it("alternates by layout column so neighbours' captions sit on opposite sides", () => {
    expect(chipSide(0)).toBe("below");
    expect(chipSide(COL_W)).toBe("above");
    expect(chipSide(2 * COL_W)).toBe("below");
    expect(chipSide(COL_W + 20)).toBe("above");
  });
});

describe("keyNodeIds", () => {
  it("path mode: proof path, cause, symptom, rejected suspect and its target, cut ends; not the rejected tail", () => {
    const keys = keyNodeIds(model, null, [{ u: "x", v: "a" }]);
    expect([...keys].sort()).toEqual(["D1", "D2", "a", "b", "c", "x"]);
    expect(keys.has("d")).toBe(false);
    expect(keys.has("e")).toBe(false);
  });

  it("ripple mode: cause, symptoms (hop 0) and the emphasised nodes only", () => {
    const ripple = { cause: new Set(["a"]), blast: new Map<string, number | null>([["b", 0], ["c", 1], ["d", 2], ["e", null]]), emphasis: new Set(["e"]) };
    expect([...keyNodeIds(model, ripple, [])].sort()).toEqual(["a", "b", "e"]);
  });
});

describe("fitCandidates / chooseFit", () => {
  it("frames every highlight first, then without the rejected tail", () => {
    const [full, core] = fitCandidates(model, null, []);
    expect(full).toEqual(["D1", "D2", "a", "b", "c", "d", "e"]);
    expect(core).toEqual(["D1", "D2", "a", "b", "c"]);
  });

  it("ripple mode frames the cause and the whole blast radius", () => {
    const ripple = { cause: new Set(["a"]), blast: new Map<string, number | null>([["b", 0], ["c", 1]]) };
    expect(fitCandidates(model, ripple, [{ u: "x", v: "a" }])).toEqual([["a", "b", "c", "x"]]);
  });

  it("takes the widest set that is still readable, else the widest within the slack of the best", () => {
    const zoom = { wide: 0.7, mid: 0.5, tight: 0.52 } as const;
    expect(chooseFit(["wide", "mid", "tight"] as const, (c) => zoom[c])).toBe("wide");
    expect(chooseFit(["mid", "tight"] as const, (c) => zoom[c])).toBe("mid"); // 0.5 ≥ 0.95 × 0.52
    expect(chooseFit(["a", "b"] as const, (c) => (c === "a" ? 0.3 : 0.5))).toBe("b");
    expect(chooseFit([], () => 1)).toBeNull();
  });
});

describe("placeCaptions", () => {
  const cap = (side: "above" | "below") => ({ w: 100, h: 46, side });
  // two captioned nodes side by side on one row, one column apart, seen at 0.25× (columns 54 px apart)
  const row: FitRect[] = [
    { id: "p", x: 0, y: 0, w: 156, h: 40, caption: cap("below"), priority: 0 },
    { id: "q", x: COL_W, y: 0, w: 156, h: 40, caption: cap("below"), priority: 1 },
  ];

  it("keeps the higher-priority caption on its side and moves the other off it", () => {
    const spots = placeCaptions(row, 0.25);
    expect(spots.get("p")).toEqual({ side: "below", dx: 0 });
    expect(spots.get("q")?.side).toBe("above");
  });

  it("drops an optional caption (rejected suspect, cut end) that has no free spot", () => {
    const crowded: FitRect[] = [
      ...row.map((r) => ({ ...r, caption: { ...r.caption!, w: 300 } })),
      { id: "r", x: COL_W / 2, y: 0, w: 156, h: 40, caption: { w: 300, h: 46, side: "below" as const }, priority: 3 },
    ];
    expect(placeCaptions(crowded, 0.25).get("r")).toBeNull();
  });

  it("treats a min-cut label as taken space", () => {
    const rects = new Map(row.map((r) => [r.id, r]));
    const labels = cutLabels(rects, [{ u: "p", v: "q", cost: 0.04 }]);
    expect(labels).toHaveLength(1);
    // the label sits between the two boxes, at their mid-height
    expect(labels[0].x).toBeCloseTo((156 + COL_W) / 2);
    expect(labels[0].y).toBeCloseTo(20);
  });
});

describe("boundsWithCaptions", () => {
  it("grows the node bounds by the standing captions (constant on-screen size, so larger when zoomed out)", () => {
    const list: FitRect[] = [{ id: "p", x: 0, y: 0, w: 156, h: 40, caption: { w: 120, h: 46, side: "below" }, priority: 0 }];
    const plain = boundsOf(list);
    const b = boundsWithCaptions(list, () => 0.5);
    expect(b.height).toBeCloseTo(40 + 46 / 0.5);
    expect(b.width).toBeCloseTo(240); // a 120 px caption at 0.5× is 240 flow px, wider than the box
    expect(b.width).toBeGreaterThan(plain.width);
  });
});

describe("preflightEmphasis", () => {
  it("is the revenue tier-1 nodes and the KPIs the change reaches, without the changed component", () => {
    const labels = new Map([["k", "KPI"], ["s", "Service"], ["t", "Service"]]);
    expect(
      preflightEmphasis({ changed: ["s"], impacted: ["t", "k", "u"], revenue_tier1: ["s", "t"] }, (id) => labels.get(id)),
    ).toEqual(["t", "k"]);
  });
});
