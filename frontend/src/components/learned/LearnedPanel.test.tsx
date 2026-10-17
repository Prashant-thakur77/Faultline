import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import { DRY_RUN, EMPTY_LEARNED, LEARNED, RECEIPT, TOKEN } from "@/test/learnedFixture";
import { LearnedPanel } from "./LearnedPanel";

function show() {
  return render(
    <CypherPanelProvider>
      <LearnedPanel />
    </CypherPanelProvider>,
  );
}

const section = (name: RegExp | string) => screen.getByRole("heading", { name }).closest("section") as HTMLElement;

describe("What Faultline has learned", () => {
  it("leads with the verdict, then every section with its FalkorDB query chip", async () => {
    const { calls } = stubFetch({ "/api/learned?": { body: LEARNED } });
    show();
    expect(await screen.findByText("Learned from 6 events, newest 2 h ago")).toBeTruthy();
    expect(screen.getByText(/1 guideline waits for a decision · 1 standing approval suggested · 1 open knowledge gap/)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "What Faultline has learned" })).toBeTruthy();
    expect(screen.getByText("oncall_acme")).toBeTruthy();
    expect(calls[0].url).toContain("/api/learned?tenant=acme");
    for (const [title, q] of [
      ["Preferences", "Q-LEARN-PREFS"],
      ["Guidelines", "Q-LEARN-GUIDES"],
      ["Who actually responds", "Q-LEARN-RESPS"],
      ["Knowledge gaps", "Q-KGAP-1"],
      ["Standing approvals to consider", "Q-LEARN-SUGGESTS"],
      ["Recent learning events", "Q-LEARN-EVENTS"],
      ["Forget a person's influence", "Q-LEARN-RECEIPTS"],
    ] as const) {
      const s = section(title);
      expect(within(s).getByRole("button", { name: new RegExp(`${q}: open the Cypher panel`) })).toBeTruthy();
    }
  });

  it("each item carries its why: the preference line, decayed counts, last seen; provenance on guidelines; owners on gaps", async () => {
    stubFetch({ "/api/learned?": { body: LEARNED } });
    show();
    await screen.findByText(/Learned from 6 events/);
    const prefs = section("Preferences");
    expect(within(prefs).getByText(/your team approved the flag flip 5 of the last 5 time\(s\) for payment/)).toBeTruthy();
    expect(within(prefs).getByText("preference 0.86")).toBeTruthy();
    expect(within(prefs).getByText(/decayed: 5 approvals · 0 rejections · 0 other/)).toBeTruthy();
    expect(within(prefs).getByText("last seen 2 h ago")).toBeTruthy();
    const guides = section("Guidelines");
    expect(within(guides).getByText("proposed: waits for a decision")).toBeTruthy(); // status in words, not colour alone
    expect(within(guides).getByText(/Asha Rao \(p-030\)/)).toBeTruthy();
    expect(within(guides).getByRole("link", { name: "inc-s1-1" })).toBeTruthy();
    const resp = section("Who actually responds");
    expect(within(resp).getByText(/mean time to ack 1 min/)).toBeTruthy();
    const gaps = section("Knowledge gaps");
    expect(within(gaps).getByText("team-payments")).toBeTruthy();
    const sugg = section("Standing approvals to consider");
    expect(within(sugg).getByRole("link", { name: "Grant a contract from incident inc-s1-1" }).getAttribute("href")).toBe(
      "/incidents/inc-s1-1?tenant=acme#plan-h",
    );
  });

  it("promotes a guideline only after a confirm that asks who decides, with the approver key as a header", async () => {
    const { calls } = stubFetch({
      "/api/learned/guidelines/gl-abc123": { body: { guideline: { id: "gl-abc123", status: "active" }, action: "promote", before: "proposed", by: "p-017" } },
      "/api/learned?": { body: LEARNED },
    });
    show();
    await screen.findByText(/Learned from 6 events/);
    fireEvent.click(screen.getByRole("button", { name: "Promote guideline gl-abc123" }));
    const confirm = screen.getByRole("group", { name: "Confirm: Promote guideline gl-abc123" });
    expect(confirm.textContent).toMatch(/needs an explicit override/);
    const yes = within(confirm).getByRole("button", { name: "Yes, promote" }) as HTMLButtonElement;
    expect(yes.disabled).toBe(true); // nobody named yet
    fireEvent.change(within(confirm).getByLabelText(/^Who decides/), { target: { value: "p-017" } });
    fireEvent.change(within(confirm).getByLabelText(/^Approver key/), { target: { value: "k3y" } });
    fireEvent.click(yes);
    await waitFor(() => expect(screen.getByText("Guideline gl-abc123 promoted to active.")).toBeTruthy());
    const post = calls.find((c) => c.url.includes("/api/learned/guidelines/gl-abc123"))!;
    expect(post.url).toContain("?tenant=acme");
    expect(JSON.parse(String(post.init?.body))).toEqual({ action: "promote", by: "p-017" });
    expect((post.init?.headers as Record<string, string>)["X-Faultline-Approver-Key"]).toBe("k3y");
    // the panel re-reads the graph after the change
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/api/learned?")).length).toBeGreaterThan(1));
  });

  it("a refused change (403 on the public demo) says so inside the confirm", async () => {
    stubFetch({
      "/api/learned/gaps/kg-0a1b2c/dismiss": { status: 403, body: { detail: "on the public demo dismissing a knowledge gap needs the approver key" } },
      "/api/learned?": { body: { ...LEARNED, trust: { ...LEARNED.trust, public: true } } },
    });
    show();
    await screen.findByText(/Learned from 6 events/);
    expect(screen.getByText("public demo: changes need the approver key")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss knowledge gap kg-0a1b2c" }));
    const confirm = screen.getByRole("group", { name: "Confirm: Dismiss knowledge gap kg-0a1b2c" });
    expect(within(confirm).getByLabelText(/^Approver key \(required on the public demo/)).toBeTruthy();
    fireEvent.change(within(confirm).getByLabelText(/^Who decides/), { target: { value: "p-017" } });
    fireEvent.click(within(confirm).getByRole("button", { name: "Yes, dismiss" }));
    const alert = await within(confirm).findByRole("alert");
    expect(alert.textContent).toMatch(/Approver key required: on the public demo .* \(HTTP 403\)\. Enter the approver key\./);
  });

  it("forget: dry run first, then an explicit, irreversible confirm bound to the receipt token, then the receipt", async () => {
    const { calls } = stubFetch({ "/api/learned/forget": { body: DRY_RUN }, "/api/learned?": { body: LEARNED } });
    show();
    await screen.findByText(/Learned from 6 events/);
    const card = section("Forget a person's influence");
    fireEvent.change(within(card).getByLabelText(/^Person whose influence to forget/), { target: { value: "p-030" } });
    fireEvent.click(within(card).getByRole("button", { name: "Dry run: show what would be forgotten" }));
    const what = await within(card).findByRole("region", { name: "What will be forgotten" });
    expect(what.textContent).toMatch(/Dry run: 6 learning events from p-030/);
    expect(what.textContent).toMatch(/gl-abc123/);
    expect(within(what).getByText(TOKEN.slice(0, 12))).toBeTruthy();
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/forget"))!.init?.body))).toEqual({ person: "p-030" });

    const confirm = within(card).getByRole("group", { name: "Forget p-030's influence for good" });
    expect(confirm.textContent).toMatch(/This cannot be undone/);
    const go = within(confirm).getByRole("button", { name: "Forget for good" }) as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(within(confirm).getByLabelText(/^Approver \(an active person id\)/), { target: { value: "p-017" } });
    expect(go.disabled).toBe(true); // not acknowledged yet
    fireEvent.click(within(confirm).getByLabelText(/I understand/));
    expect(go.disabled).toBe(false);

    stubFetch({ "/api/learned/forget": { body: RECEIPT }, "/api/learned?": { body: LEARNED } });
    fireEvent.click(go);
    const receipt = await within(card).findByRole("status");
    expect(receipt.textContent).toMatch(/forgotten/);
    expect(receipt.textContent).toMatch(/6 events, 1 guideline, 14 relationships/);
    expect(receipt.textContent).toMatch(/0 events left · 0 preferences still citing one/);
    expect(receipt.textContent).toMatch(/audit_acme/);
    const fetchMock = globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } };
    const post = fetchMock.mock.calls.find(([u]) => String(u).includes("/forget"))!;
    expect(JSON.parse(String(post[1].body))).toEqual({ person: "p-030", token: TOKEN, approver: "p-017" });
  });

  it("forget: a stale token (409) deletes nothing and offers the dry run again", async () => {
    stubFetch({ "/api/learned/forget": { body: DRY_RUN }, "/api/learned?": { body: LEARNED } });
    show();
    await screen.findByText(/Learned from 6 events/);
    const card = section("Forget a person's influence");
    fireEvent.change(within(card).getByLabelText(/^Person whose influence to forget/), { target: { value: "p-030" } });
    fireEvent.click(within(card).getByRole("button", { name: "Dry run: show what would be forgotten" }));
    const confirm = await within(card).findByRole("group", { name: "Forget p-030's influence for good" });
    fireEvent.change(within(confirm).getByLabelText(/^Approver \(an active/), { target: { value: "p-017" } });
    fireEvent.click(within(confirm).getByLabelText(/I understand/));
    stubFetch({
      "/api/learned/forget": { status: 409, body: { detail: "the dry-run receipt no longer matches the learned state; run the dry run again" } },
      "/api/learned?": { body: LEARNED },
    });
    fireEvent.click(within(confirm).getByRole("button", { name: "Forget for good" }));
    const alert = await within(card).findByRole("alert");
    expect(alert.textContent).toMatch(/Changed since the dry run: .*\(HTTP 409\)\. Nothing was deleted/);
    expect(within(alert).getByRole("button", { name: "Run the dry run again" })).toBeTruthy();
  });

  it("a person with nothing learned: the dry run says so and offers no confirm", async () => {
    stubFetch({
      "/api/learned/forget": { body: { ...DRY_RUN, person: "p-099", n_events: 0, by_kind: {}, events: [], guidelines: [], families: [], responded: [] } },
      "/api/learned?": { body: LEARNED },
    });
    show();
    await screen.findByText(/Learned from 6 events/);
    const card = section("Forget a person's influence");
    fireEvent.change(within(card).getByLabelText(/^Person whose influence to forget/), { target: { value: "p-099" } });
    fireEvent.click(within(card).getByRole("button", { name: "Dry run: show what would be forgotten" }));
    expect((await within(card).findByRole("status")).textContent).toMatch(/Nothing to forget: p-099 has no learning event in oncall_acme/);
    expect(within(card).queryByRole("button", { name: "Forget for good" })).toBeNull();
  });

  it("nothing learned: says so plainly, every section shows what would fill it", async () => {
    stubFetch({ "/api/learned?": { body: EMPTY_LEARNED } });
    show();
    expect(await screen.findByText("Nothing learned yet")).toBeTruthy();
    expect(screen.getByText(/No preference yet/)).toBeTruthy();
    expect(screen.getByText(/No guideline yet/)).toBeTruthy();
    expect(screen.getByText(/No responder learned yet/)).toBeTruthy();
    expect(screen.getByText(/No knowledge gap/)).toBeTruthy();
  });

  it("fails loudly: an API without the endpoint, and an API that is down, each say so and show no data", async () => {
    stubFetch({ "/api/learned?": { status: 404, body: { detail: "Not Found" } } });
    const { unmount } = show();
    expect(await screen.findByText("Learning is not on this server: its API has no /api/learned endpoint")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/learning backend is not deployed on this server/);
    expect(screen.queryByRole("heading", { name: "Preferences" })).toBeNull();
    unmount();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    show();
    expect((await screen.findByRole("alert")).textContent).toMatch(/What Faultline learned \(GET \/api\/learned\) is unavailable: Faultline API unreachable/);
    expect(screen.queryByRole("heading", { name: "Preferences" })).toBeNull();
  });
});
