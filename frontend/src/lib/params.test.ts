import { describe, expect, it } from "vitest";
import { splitTemplateId } from "./params";

describe("splitTemplateId", () => {
  it("keeps a plain id as one part with the whole record", () => {
    expect(splitTemplateId("Q-GATE-1", { cause: "c" })).toEqual([
      { key: "Q-GATE-1", template: "Q-GATE-1", recordedParams: { cause: "c" } },
    ]);
  });

  it("splits a combined id and gives each part its own recorded params", () => {
    const rec = { "Q-A": { x: 1 }, "Q-B": { y: 2 } };
    expect(splitTemplateId("Q-A+Q-B", rec)).toEqual([
      { key: "Q-A", template: "Q-A", recordedParams: { x: 1 } },
      { key: "Q-B", template: "Q-B", recordedParams: { y: 2 } },
    ]);
  });

  it("maps a repeated template's runs to their #n keys and the base template", () => {
    const rec = { "Q-GATE-3": { s: "a" }, "Q-GATE-3#2": { s: "b" }, "Q-GATE-MULT": { m: 1 } };
    const parts = splitTemplateId("Q-GATE-3+Q-GATE-3+Q-GATE-MULT", rec);
    expect(parts.map((p) => [p.key, p.template, p.recordedParams])).toEqual([
      ["Q-GATE-3", "Q-GATE-3", { s: "a" }],
      ["Q-GATE-3#2", "Q-GATE-3", { s: "b" }],
      ["Q-GATE-MULT", "Q-GATE-MULT", { m: 1 }],
    ]);
  });

  it("loads the base template for a single #n id instead of a 404", () => {
    expect(splitTemplateId("Q-GATE-3#2", null)).toEqual([{ key: "Q-GATE-3#2", template: "Q-GATE-3", recordedParams: null }]);
  });
});
