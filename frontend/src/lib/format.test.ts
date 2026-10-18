import { describe, expect, it } from "vitest";
import { midTruncate, plural, sentence, slugWords } from "./format";

describe("plural", () => {
  it("says one and many in plain words", () => {
    expect(plural(1, "check")).toBe("1 check");
    expect(plural(0, "check")).toBe("0 checks");
    expect(plural(3, "query", "queries")).toBe("3 queries");
  });
  it("never invents an unknown count", () => {
    expect(plural(null, "event")).toBe("– events");
    expect(plural(undefined, "event")).toBe("– events");
  });
});

describe("sentence", () => {
  it("adds a full stop only when the text has none", () => {
    expect(sentence("12,000 MRR at risk")).toBe("12,000 MRR at risk.");
    expect(sentence("already done.")).toBe("already done.");
    expect(sentence("  ")).toBe("");
  });
});

describe("midTruncate", () => {
  it("keeps short ids whole and cuts long ones in the middle", () => {
    expect(midTruncate("ADR-012")).toBe("ADR-012");
    expect(midTruncate("ADR-013")).not.toBe(midTruncate("ADR-012"));
    expect(midTruncate("rb-derived-0b6bb0db12")).toBe("rb-der…0db12");
    expect(midTruncate("rb-derived-0b6bb0db12")).toHaveLength(12);
  });
});

describe("slugWords", () => {
  it("turns a snake_case name into words", () => {
    expect(slugWords("hero_bad_payment_deploy_with_same_minute_distractor")).toBe("hero bad payment deploy with same minute distractor");
  });
});
