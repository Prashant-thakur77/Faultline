import { describe, expect, it } from "vitest";
import { DRY_RUN, LEARNED, NOW, RECEIPT, TOKEN } from "@/test/learnedFixture";
import { ApiError } from "./api";
import { guidelineFrom409, knownPeople, parseForgetPlan, parseForgetReceipt, parseLearned } from "./learned";

describe("learned state parser (GET /api/learned)", () => {
  it("reads every documented section with its query, and never invents a value", () => {
    const s = parseLearned(LEARNED);
    expect(s.home).toBe("oncall_acme");
    expect(s.now).toBe(NOW);
    expect(s.halfLifeDays).toBe(14);
    expect(s.preferences.template).toBe("Q-LEARN-PREFS");
    expect(s.preferences.params).toEqual({ now: NOW, half_life_ms: 14 * 24 * 3_600_000 });
    const p = s.preferences.rows[0];
    expect(p).toMatchObject({ family: "payment", actionKind: "flip_flag", pref: 0.857, nApprove: 5, events: ["le-a1", "le-a2"] });
    expect(p.line).toMatch(/^learned: your team approved/);
    const g = s.guidelines.rows[0];
    expect(g.by).toEqual({ id: "p-030", name: "Asha Rao" });
    expect(g.decidedBy).toBeNull();
    expect(s.guidelines.rows[1].decidedBy).toEqual({ id: "p-017", name: "Mei Chen" });
    expect(s.responders.rows[0]).toMatchObject({ person: { id: "p-017", name: "Mei Chen" }, mttaMs: 60000, acks: 5 });
    expect(s.gaps.rows[0]).toMatchObject({ owners: ["team-payments"], about: ["payment"], status: "open" });
    expect(s.suggestions.rows[0]).toMatchObject({ n: 2, coveredBy: null, incidents: ["inc-s1-1", "inc-s1-2"] });
    expect(s.events.rows[0].person).toEqual({ id: "p-030", name: "Asha Rao" });
    expect(s.events.counts).toEqual([
      { kind: "approve", n: 5, people: 1, lastAt: NOW - 2 * 3_600_000 },
      { kind: "reject", n: 1, people: 1, lastAt: NOW - 3 * 3_600_000 },
    ]);
    expect(s.receipts.rows).toEqual([]);
  });

  it("a receipt's recomputed lists are JSON text in the graph: they come back as lists", () => {
    const s = parseLearned({
      ...LEARNED,
      receipts: { ...LEARNED.receipts, rows: [{ person: "p-030", families: '["payment"]', responders: '["payment"]', gaps: "[]", events_left: 0 }] },
    });
    expect(s.receipts.rows[0]).toMatchObject({ families: ["payment"], responders: ["payment"], gaps: [], eventsLeft: 0, approver: null });
  });

  it("a section that is not an envelope is an error, not an empty list", () => {
    expect(() => parseLearned({ ...LEARNED, gaps: [] })).toThrow(ApiError);
    expect(() => parseLearned([])).toThrow(/expected an object/);
  });

  it("collects the people it mentions for the person-id suggestions", () => {
    const ids = knownPeople(parseLearned(LEARNED)).map((p) => p.id);
    expect(ids).toEqual(expect.arrayContaining(["p-030", "p-017", "p-031"]));
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("forget responses", () => {
  it("the dry run lists what goes and the token that binds it", () => {
    const p = parseForgetPlan(DRY_RUN);
    expect(p).toMatchObject({ person: "p-030", nEvents: 6, guidelines: ["gl-abc123"], families: ["payment"], token: TOKEN });
    expect(p.byKind).toEqual([
      { kind: "approve", n: 5 },
      { kind: "reject", n: 1 },
    ]);
    expect(p.events[1].guidelines).toEqual(["gl-abc123"]);
  });

  it("a dry run without a token cannot be confirmed", () => {
    expect(() => parseForgetPlan({ ...DRY_RUN, token: null })).toThrow(/no receipt token/);
    expect(() => parseForgetPlan(RECEIPT)).toThrow(ApiError);
  });

  it("the receipt is 'forgotten' only when the server's proof says so and nothing is left", () => {
    expect(parseForgetReceipt(RECEIPT)).toMatchObject({ forgotten: true, events: 6, familiesRecomputed: ["payment"], eventsLeft: 0 });
    const bad = parseForgetReceipt({ ...RECEIPT, proof: { events_left: 1, preferences_still_citing: 0, verdict: "INCOMPLETE (events or citations remain)" } });
    expect(bad.forgotten).toBe(false);
    expect(bad.verdict).toMatch(/^INCOMPLETE/);
  });
});

describe("guideline named in an approve 409", () => {
  it("reads the id, the text and who promoted it from the server's sentence", () => {
    const d =
      'flag paymentGate → off is against active guideline gl-abc123 ("flag off hides the revenue KPI", promoted by Mei Chen): send override_guideline=gl-abc123 and an override_reason';
    expect(guidelineFrom409(d)).toEqual({ id: "gl-abc123", text: "flag off hides the revenue KPI", promotedBy: "Mei Chen" });
    expect(guidelineFrom409("plan hash does not match the current chosen action")).toBeNull();
  });
});
