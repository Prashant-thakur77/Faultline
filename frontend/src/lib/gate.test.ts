import { describe, expect, it } from "vitest";
import { CHECK_STATE_TEXT, checkState, sortChecks } from "./gate";
import type { GateCheck } from "./types";

const c = (name: string, passed: boolean | null, downgrade_only = false): GateCheck => ({
  name,
  passed,
  detail: "",
  template: null,
  params: null,
  evidence_ids: [],
  downgrade_only,
});

describe("gate checks", () => {
  it("orders G7 correlation right after G7 agreement", () => {
    const names = sortChecks([c("G8 contradiction", true), c("G7 correlation", null, true), c("G1 grounded", true), c("G7 agreement", true)]).map((x) => x.name);
    expect(names).toEqual(["G1 grounded", "G7 agreement", "G7 correlation", "G8 contradiction"]);
  });

  it("orders G4 origin right after G4 quantitative", () => {
    const names = sortChecks([c("G5 sufficiency", true), c("G4 origin", false, true), c("G4 quantitative", true)]).map((x) => x.name);
    expect(names).toEqual(["G4 quantitative", "G4 origin", "G5 sufficiency"]);
  });

  it("renders passed=None as a neutral 'not evaluable', a failed downgrade-only check as a downgrade", () => {
    expect(checkState(c("G7 correlation", null, true))).toBe("na");
    expect(CHECK_STATE_TEXT.na).toBe("not evaluable");
    expect(checkState(c("G7 correlation", false, true))).toBe("downgrade");
    expect(checkState(c("G2 path", false))).toBe("fail");
    expect(checkState({ ...c("G8 contradiction", false, true), attach_only: true })).toBe("noted");
  });
});
