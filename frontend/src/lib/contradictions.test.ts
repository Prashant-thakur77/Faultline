import { describe, expect, it } from "vitest";
import { parseContradictions } from "./contradictions";

describe("parseContradictions (G8 detail)", () => {
  it("parses plain violations, a recorded answer and an accepted deviation", () => {
    const parts = parseContradictions(
      "violates ADR-012: payment.client.timeout_ms <= 2000 (actual 5000) (accidental: nobody meant it); " +
        "violates ADR-013: payment.client.retries >= 2 (actual 0); " +
        "accepted deviation from ADR-014 (payment.client.pool 4): marked intentional by p-030: agreed in review",
    );
    expect(parts).toHaveLength(3);
    expect(parts[0].parsed).toEqual({
      decision: "ADR-012",
      key: "payment.client.timeout_ms",
      op: "<=",
      expected: "2000",
      actual: "5000",
    });
    expect(parts[0].answer).toEqual({
      verdict: "accidental",
      why: "nobody meant it",
    });
    expect(parts[1].parsed?.actual).toBe("0");
    expect(parts[1].answer).toBeNull();
    expect(parts[2].parsed).toBeNull();
    expect(parts[2].accepted).toEqual({
      decision: "ADR-014",
      fact: "payment.client.pool 4",
      by: "p-030",
      why: "agreed in review",
    });
  });

  it("keeps an unrecognised part verbatim", () => {
    const [p] = parseContradictions("something else entirely");
    expect(p.parsed).toBeNull();
    expect(p.accepted).toBeUndefined();
    expect(p.raw).toBe("something else entirely");
  });
});
