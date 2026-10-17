import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { option, plan, stubFetch } from "@/test/fixtures";
import { PlanApprovalCard } from "@/components/incident/PlanApprovalCard";
import { ContractGrant } from "./ContractGrant";

const HASH = "c".repeat(64);
const QUOTE = { hash: HASH, scope: { max_uses: 2, days: 5, family: "fam-7", action_kind: "flip_flag", params_hash: "abcdef0123456789", expires_at: 1_800_000_000_000 } };
const GRANTED = { id: "ct-9", family: "fam-7", action_kind: "flip_flag", max_uses: 2, uses: 0, expires_at: 1_800_000_000_000, status: "active" };
const WHO = [{ person: "p-030", name: "Asha Rao", score: 1, teams: [], reasons: [] }];

describe("Grant a contract for repeats", () => {
  it("is two steps: choose posts the scope and shows the exact contract; approve posts its hash", async () => {
    const { calls } = stubFetch({ "/api/incidents/inc-1/contract": { body: QUOTE } });
    render(<ContractGrant incidentId="inc-1" actionKind="flip_flag" candidates={WHO} />);
    fireEvent.click(screen.getByRole("button", { name: /Grant a contract for repeats/ }));
    fireEvent.change(screen.getByLabelText(/^Max uses/), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/^For how many days/), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Choose this scope" }));
    const exact = await screen.findByRole("region", { name: "Exact contract" });
    expect(within(exact).getByText("fam-7")).toBeTruthy();
    expect(within(exact).getByText(HASH.slice(0, 12))).toBeTruthy();
    const choose = calls.find((c) => c.url.includes("/contract"))!;
    expect(choose.url).toContain("/api/incidents/inc-1/contract?tenant=acme");
    expect(JSON.parse(String(choose.init?.body))).toEqual({ step: "choose", scope: { max_uses: 2, days: 5 } });

    stubFetch({ "/api/incidents/inc-1/contract": { body: { contract: GRANTED } } });
    const approver = screen.getByLabelText(/^Approver \(on call/) as HTMLInputElement;
    expect(approver.value).toBe("p-030"); // the top of Who fixes it
    fireEvent.change(screen.getByLabelText(/^Approver key/), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "Grant this exact contract" }));
    expect(await screen.findByText(/granted/)).toBeTruthy();
    const fetchMock = globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } };
    const [url, init] = fetchMock.mock.calls.at(-1)!;
    expect(url).toContain("/api/incidents/inc-1/contract?tenant=acme");
    expect(JSON.parse(String(init.body))).toEqual({ step: "approve", hash: HASH, approver: "p-030", approver_key: "s3cret" });
    expect((init.headers as Record<string, string>)["X-Faultline-Approver-Key"]).toBe("s3cret");
    expect(screen.getByRole("status").textContent).toMatch(/Contract ct-9 granted/);
    expect(screen.getByText("0 of 2 used · 2 left")).toBeTruthy();
  });

  it("changing the scope after choosing drops the quote (the hash binds the exact scope)", async () => {
    stubFetch({ "/api/incidents/inc-1/contract": { body: QUOTE } });
    render(<ContractGrant incidentId="inc-1" actionKind="flip_flag" candidates={WHO} />);
    fireEvent.click(screen.getByRole("button", { name: /Grant a contract for repeats/ }));
    fireEvent.click(screen.getByRole("button", { name: "Choose this scope" }));
    await screen.findByRole("region", { name: "Exact contract" });
    fireEvent.change(screen.getByLabelText(/^Max uses/), { target: { value: "4" } });
    expect(screen.queryByRole("region", { name: "Exact contract" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Grant this exact contract" })).toBeNull();
  });

  it("out-of-range scope cannot be chosen", () => {
    stubFetch({});
    render(<ContractGrant incidentId="inc-1" actionKind="flip_flag" candidates={WHO} />);
    fireEvent.click(screen.getByRole("button", { name: /Grant a contract for repeats/ }));
    fireEvent.change(screen.getByLabelText(/^Max uses/), { target: { value: "50" } });
    expect((screen.getByRole("button", { name: "Choose this scope" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByLabelText(/^Max uses/).getAttribute("aria-invalid")).toBe("true");
  });

  it("a stale hash (409) says so and offers to choose again; an ineligible approver (422) is named", async () => {
    stubFetch({ "/api/incidents/inc-1/contract": { body: QUOTE } });
    render(<ContractGrant incidentId="inc-1" actionKind="flip_flag" candidates={WHO} />);
    fireEvent.click(screen.getByRole("button", { name: /Grant a contract for repeats/ }));
    fireEvent.click(screen.getByRole("button", { name: "Choose this scope" }));
    await screen.findByRole("region", { name: "Exact contract" });
    stubFetch({ "/api/incidents/inc-1/contract": { status: 409, body: { detail: "contract hash is stale" } } });
    fireEvent.click(screen.getByRole("button", { name: "Grant this exact contract" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Changed since you chose: contract hash is stale \(HTTP 409\)/);
    expect(screen.getByRole("button", { name: "Choose the scope again" })).toBeTruthy();
    stubFetch({ "/api/incidents/inc-1/contract": { status: 422, body: { detail: "p-030 is not on call for an impacted component" } } });
    fireEvent.click(screen.getByRole("button", { name: "Grant this exact contract" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Approver not eligible: p-030 is not on call/));
  });

  it("the plan card offers it only after a verified APPLIED action, and never in replay", () => {
    stubFetch({});
    const applied = [option({ status: "executed", verdict: "APPLIED", plan_hash: "a".repeat(64) })];
    const { unmount } = render(
      <PlanApprovalCard incidentId="inc-1" stage="RESOLVED" stages={[]} plan={plan(applied)} error={null} onRefresh={() => {}} onApproved={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /Grant a contract for repeats/ })).toBeTruthy();
    // the recorder reads the plan card's first [data-verdict]: the grant adds none
    expect(document.querySelectorAll("[data-verdict]")[0].getAttribute("data-verdict")).toBe("APPLIED");
    unmount();
    render(
      <PlanApprovalCard incidentId="inc-1" stage="RESOLVED" stages={[]} plan={plan(applied)} error={null} onRefresh={() => {}} onApproved={() => {}} readOnly />,
    );
    expect(screen.queryByRole("button", { name: /Grant a contract for repeats/ })).toBeNull();
  });

  it("is not offered when the action did not verify", () => {
    stubFetch({});
    render(
      <PlanApprovalCard
        incidentId="inc-1"
        stage="UNKNOWN_ESCALATED"
        stages={[]}
        plan={plan([option({ status: "executed", verdict: "UNKNOWN", plan_hash: "a".repeat(64) })])}
        error={null}
        onRefresh={() => {}}
        onApproved={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /Grant a contract for repeats/ })).toBeNull();
  });
});
