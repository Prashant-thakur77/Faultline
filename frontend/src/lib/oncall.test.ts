import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  endpointMissing,
  externalChannels,
  fmtCountdown,
  fmtDuration,
  needsAck,
  oncallErrorText,
  parseContractQuote,
  parseContracts,
  parseOnCallNow,
  parsePageDetail,
  parsePages,
  parseReport,
  parseStats,
  toMs,
} from "./oncall";

describe("on-call parsers", () => {
  it("read the plan's bare array and the view envelope alike, keeping the server's template and params", () => {
    const bare = parseOnCallNow([{ team: "t-pay", person: { id: "p-1", name: "Asha" }, from: 1, to: 2 }]);
    expect(bare.rows[0]).toEqual({ team: "t-pay", teamName: null, person: { id: "p-1", name: "Asha" }, from: 1000, to: 2000 });
    expect(bare.template).toBe("Q-ONCALL-NOW"); // the plan names the template; params are not invented
    expect(bare.params).toBeNull();
    const env = parseOnCallNow({ rows: [{ team: "t-pay", person: "p-1" }], template: "Q-ONCALL-NOW", params: { now: 5 }, ms: 1.2 });
    expect(env.rows[0].person).toEqual({ id: "p-1", name: null });
    expect(env.params).toEqual({ now: 5 });
    expect(env.ms).toBe(1.2);
  });

  it("throw on a response that is neither shape (never an empty list in its place)", () => {
    expect(() => parsePages({ detail: "oops" })).toThrow(ApiError);
    expect(() => parseContracts("nope")).toThrow(/expected a list/);
  });

  it("parse a page with its person, ack and channels, and never fill in a missing field", () => {
    const list = parsePages({
      pages: [
        { id: "pg-1", incident: "inc-1", channel: "in_app", kind: "page", urgency: "urgent", sent_at: 1_700_000_000_000, ack_due_at: 1_700_000_300_000, status: "sent", attempt: 1, person: { id: "p-1", name: "Asha" } },
        { id: "pg-2", status: "acked", acked_by: "p-2", acked_at: 1_700_000_100_000, ack_via: "telegram" },
        { status: "sent" },
      ],
      channels: [{ channel: "in_app", configured: true }, { channel: "slack", configured: false }],
      template: "Q-PAGE-LIST",
    });
    expect(list.rows).toHaveLength(2); // a row without an id is dropped, not shown with a made-up one
    expect(list.rows[0].person).toEqual({ id: "p-1", name: "Asha" });
    expect(list.rows[1].ack).toEqual({ by: { id: "p-2", name: null }, at: 1_700_000_100_000, via: "telegram" });
    expect(list.rows[1].channel).toBeNull();
    expect(externalChannels(list.channels)).toEqual([]); // slack not configured, in-app does not count
    expect(externalChannels(parsePages([]).channels)).toBeNull(); // not reported ≠ none configured
    expect(externalChannels(parsePages({ rows: [], channels: { slack: true, in_app: true } }).channels)?.map((c) => c.channel)).toEqual(["slack"]);
  });

  it("needsAck counts only open pages a human must answer", () => {
    expect(needsAck({ status: "sent", kind: "page" })).toBe(true);
    expect(needsAck({ status: "delivery_failed", kind: "escalation" })).toBe(true);
    expect(needsAck({ status: "sent", kind: "contract_notice" })).toBe(false);
    expect(needsAck({ status: "acked", kind: "page" })).toBe(false);
    expect(needsAck({ status: "escalated", kind: "page" })).toBe(false);
  });

  it("page detail: incident one-liner, proof chain with relationships, who fixes and the chain", () => {
    const d = parsePageDetail({
      page: { id: "pg-1", incident: "inc-1", status: "sent" },
      incident: { id: "inc-1", title: "checkout 5xx", line: "deploy d-9 flipped paymentGate" },
      proof: { nodes: ["d-9", "payment", "checkout"], rels: ["CHANGED", "CALLS"], template: "Q-PATH-1", params: { a: 1 } },
      who_fixes: { rows: [{ person: "p-1", name: "Asha", score: 0.9, reasons: ["owns payment"] }], template: "Q-WHO-1", params: {} },
      chain: [{ id: "pg-0", person: "p-0", status: "escalated", attempt: 1 }, { id: "pg-1", person: "p-1", status: "sent", attempt: 2 }],
      obligations: { breach: { breach_in_min: 42, slo: "slo-checkout" } },
    });
    expect(d.incident?.line).toBe("deploy d-9 flipped paymentGate");
    expect(d.proof).toEqual({ nodes: ["d-9", "payment", "checkout"], rels: ["CHANGED", "CALLS"], query: { template: "Q-PATH-1", params: { a: 1 }, ms: null } });
    expect(d.whoFixes[0]).toEqual({ person: { id: "p-1", name: "Asha" }, score: 0.9, reasons: ["owns payment"] });
    expect(d.whoFixesQuery?.template).toBe("Q-WHO-1");
    expect(d.chain.map((s) => s.attempt)).toEqual([1, 2]);
    expect(d.chainQuery).toEqual({ template: "Q-PAGE-CHAIN", params: null, ms: null });
    expect(d.breachInMin).toBe(42);
    expect(d.breachSlo).toBe("slo-checkout");
  });

  it("contract quote needs a hash: without one there is nothing to approve", () => {
    expect(() => parseContractQuote({ scope: { max_uses: 3, days: 7 } })).toThrow(/no hash/);
    const qt = parseContractQuote({ hash: "h".repeat(64), scope: { max_uses: 3, days: 7, family: "fam-1", action_kind: "flip_flag", params_hash: "abc", expires_at: "2026-10-24T00:00:00Z" } });
    expect(qt.maxUses).toBe(3);
    expect(qt.family).toBe("fam-1");
    expect(qt.expiresAt).toBe(Date.parse("2026-10-24T00:00:00Z"));
  });

  it("stats durations from _ms, _s or _min; people paged under any of its names; null when absent", () => {
    expect(parseStats({ mtta_ms: 240_000, mttr_s: 600, people_paged: 3, handled_under_contract: 2 })).toMatchObject({
      mttaMs: 240_000,
      mttrMs: 600_000,
      peoplePaged: 3,
      handledUnderContract: 2,
      template: "Q-ONCALL-STATS",
    });
    expect(parseStats({ mtta_min: 2, people_woken: 0 })).toMatchObject({ mttaMs: 120_000, peoplePaged: 0, mttrMs: null, handledUnderContract: null });
  });

  it("report: counts from the server, else the rows it sent, else null (not zero)", () => {
    const r = parseReport({ from: 1, to: 2, counts: { pages: 5 }, incidents: [{ id: "inc-1", title: "checkout 5xx", status: "RESOLVED" }], acks: [] });
    expect(r.counts.pages).toBe(5);
    expect(r.counts.incidents).toBe(1);
    expect(r.counts.acks).toBe(0);
    expect(r.counts.actions).toBeNull();
    expect(r.sections.incidents?.[0]).toMatchObject({ id: "inc-1", title: "checkout 5xx", status: "RESOLVED" });
    expect(r.template).toBe("Q-SHIFT-REPORT");
  });

  it("toMs takes ms, seconds and ISO; rejects junk", () => {
    expect(toMs(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(toMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(toMs("2026-10-17T00:00:00Z")).toBe(Date.parse("2026-10-17T00:00:00Z"));
    expect(toMs("soon")).toBeNull();
    expect(toMs(null)).toBeNull();
  });

  it("formats durations and countdowns", () => {
    expect(fmtDuration(null)).toBe("–");
    expect(fmtDuration(42_000)).toBe("42 s");
    expect(fmtDuration(4 * 60_000 + 5_000)).toBe("4 min 5 s");
    expect(fmtDuration(90 * 60_000)).toBe("1 h 30 min");
    expect(fmtDuration(50 * 3_600_000)).toBe("2 d 2 h");
    expect(fmtCountdown(192_000)).toBe("3:12");
  });

  it("names a missing endpoint apart from an unknown id", () => {
    const missing = new ApiError("Not Found", 404, "u");
    const unknown = new ApiError("unknown page pg-9", 404, "u");
    expect(endpointMissing(missing)).toBe(true);
    expect(endpointMissing(unknown)).toBe(false);
    expect(oncallErrorText(missing, "the pager")).toBe(
      "The pager: this API has no such endpoint (HTTP 404), so the on-call backend is not deployed on this server.",
    );
    expect(oncallErrorText(unknown, "the page")).toBe("The page failed: unknown page pg-9 (HTTP 404).");
    expect(oncallErrorText(new ApiError("Faultline API unreachable at x", null, "u"), "the pager")).toBe("The pager unavailable: Faultline API unreachable at x.");
  });

  it("reads the backend templates' own row shapes (Q-PAGES, Q-CONTRACTS, Q-SHIFT-REPORT and Q-ONCALL-STATS as single rows)", () => {
    const pages = parsePages({
      rows: [
        {
          id: "pg-1", incident: "inc-1", incident_title: "checkout 5xx", incident_stage: "AWAITING_APPROVAL", kind: "page",
          channel: "in_app,telegram", channels: ["in_app", "telegram"], urgency: "urgent", sent_at: 1, ack_due_at: 2,
          status: "delivery_failed", attempt: 1, detail: "", reason: "on call for t-pay", team: "t-pay",
          delivery: '{"in_app": {"ok": true}, "telegram": {"ok": false, "status": 401}}', deep_link: "/oncall/page/pg-1?t=x",
          person: "p-030", person_name: "Asha", acked_by: null, acked_by_name: null, acked_at: null, ack_via: null,
          escalated_to: null, overdue: true,
        },
      ],
      template: "Q-PAGES",
      params: { incident: "", statuses: [], now: 3 },
      channels: [{ channel: "in_app", configured: true, detail: "always on" }, { channel: "telegram", configured: true, detail: "one chat" }],
    });
    const p = pages.rows[0];
    expect(p.person).toEqual({ id: "p-030", name: "Asha" });
    expect(p.ack).toBeNull();
    expect(p.channels).toEqual(["in_app", "telegram"]);
    expect(p.delivery).toEqual([
      { channel: "in_app", ok: true, detail: null },
      { channel: "telegram", ok: false, detail: "HTTP 401" },
    ]);
    expect(p.overdue).toBe(true);
    expect(p.reason).toBe("on call for t-pay");
    expect(p.incidentStage).toBe("AWAITING_APPROVAL");
    expect(externalChannels(pages.channels)?.map((c) => c.channel)).toEqual(["telegram"]);

    const contracts = parseContracts({
      rows: [{ id: "ct-1", family: "payment", action_kind: "flip_flag", params_hash: "ph", max_uses: 3, uses: 1, days: 7, expires_at: 9, granted_at: 1, status: "active", quote: "", granted_by: "p-030", granted_by_name: "Asha", covers: "payment", source_incident: "inc-1", revoked_at: null, revoked_by: null, used_in: [{ id: "cu-1", incident: "inc-2", at: 5, verdict: "APPLIED" }] }],
      template: "Q-CONTRACTS",
    });
    expect(contracts.rows[0]).toMatchObject({ grantedBy: { id: "p-030", name: "Asha" }, sourceIncident: "inc-1", quote: null, usedIn: [{ incident: "inc-2", at: 5000, verdict: "APPLIED" }] });

    const report = parseReport({
      rows: [{ incidents: [{ id: "inc-1", title: "checkout 5xx", stage: "RESOLVED", opened_at: 10 }], pages: [], acks: [{ id: "pg-1", page: "pg-1", by: "p-030", name: "Asha", at: 11 }], actions: [], contract_uses: [], handoffs: [{ id: "ho-1", at: 12, note: "watch payment", to: "p-031", to_name: "Ravi" }] }],
      template: "Q-SHIFT-REPORT",
      params: { from: 0, to: 20 },
    });
    expect(report.counts).toEqual({ incidents: 1, pages: 0, acks: 1, actions: 0, contract_uses: 0, handoffs: 1 });
    expect(report.sections.acks?.[0].who).toBe("Asha");
    expect(report.sections.handoffs?.[0]).toMatchObject({ title: "watch payment", who: "Ravi" });
    expect(report.params).toEqual({ from: 0, to: 20 });

    const stats = parseStats({
      rows: [{ pages: 4, people: ["p-030", "p-031"], incidents_paged: 2, acked_incidents: 2, ack_ms_sum: 240_000, resolved_incidents: 1, resolve_ms_sum: 900_000, under_contract: 1 }],
      template: "Q-ONCALL-STATS",
      params: { since: 0 },
    });
    expect(stats).toMatchObject({ mttaMs: 120_000, mttrMs: 900_000, peoplePaged: 2, handledUnderContract: 1, pages: 4, incidents: 2 });
    // the server's own mean wins over the template's sums
    expect(parseStats({ mtta_ms: 1000, ack_ms_sum: 9, acked_incidents: 1 }).mttaMs).toBe(1000);
    expect(parseStats({ acked_incidents: 0, ack_ms_sum: 0 }).mttaMs).toBeNull();
  });

  it("reads GET /api/pages/{id} and the contract choose step exactly as the API sends them", () => {
    const d = parsePageDetail({
      page: {
        id: "pg-1", incident: "inc-1", kind: "page", status: "sent", channels: ["in_app"], delivery: { in_app: { ok: true } },
        person: { id: "p-030", name: "Asha" }, ack: null, overdue: false, graph: "run_acme_1", ack_token: "tok.abc",
      },
      ack_token: "tok.abc",
      chain: { rows: [{ id: "pg-1", person: { id: "p-030", name: "Asha" }, person_name: "Asha", status: "sent", attempt: 1, acked_by: null }], template: "Q-PAGE-CHAIN", params: { page: "pg-1" }, ms: 0.4 },
      incident: { id: "inc-1", title: "checkout 5xx", line: "checkout 5xx: the gate confirmed d-9 as the cause", stage: "AWAITING_APPROVAL", cause: "d-9" },
      proof: { nodes: ["d-9", "payment", "checkout"], rels: [], template: "Q-GATE-1", params: { a: "d-9" }, gate_run: "gr-1" },
      who_fixes: { rows: [{ person: "p-030", name: "Asha", score: 2, teams: ["t"], reasons: ["owns payment"] }], template: "Q-ORG-HARM", evidence_id: "ev-1" },
      obligations: { breach: { slo: "slo-1", service: "checkout", breach_in_min: 12, burn: 3, budget_remaining: 0.4 }, urgent: true, reason: "r", template: "Q-OBL-1" },
    });
    expect(d.page.ackToken).toBe("tok.abc");
    expect(d.page.graph).toBe("run_acme_1");
    expect(d.chain[0].person).toEqual({ id: "p-030", name: "Asha" });
    expect(d.chainQuery).toEqual({ template: "Q-PAGE-CHAIN", params: { page: "pg-1" }, ms: 0.4 });
    expect(d.proof?.query?.template).toBe("Q-GATE-1");
    expect(d.whoFixes[0].person).toEqual({ id: "p-030", name: "Asha" });
    expect(d.breachInMin).toBe(12);

    const qt = parseContractQuote({
      hash: "a".repeat(64), contract_id: "ct-aaaaaaaaaaaaaaaa",
      scope: { family: "payment", action_kind: "flip_flag", params_hash: "ph", params: {}, max_uses: 3, days: 7, expires_at: 1_800_000_000_000 },
      quote: "Standing approval: flag off without paging …", action: "act-2", option: "flag paymentGate → off", offer_expires_at: 1_799_000_000_000,
    });
    expect(qt).toMatchObject({ id: "ct-aaaaaaaaaaaaaaaa", family: "payment", maxUses: 3, days: 7, offerExpiresAt: 1_799_000_000_000, quote: "Standing approval: flag off without paging …", option: "flag paymentGate → off" });
  });
});
