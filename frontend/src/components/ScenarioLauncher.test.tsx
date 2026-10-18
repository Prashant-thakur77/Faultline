import { act, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestHeroRun } from "@/lib/heroRun";
import { stubFetch } from "@/test/fixtures";
import { ScenarioLauncher } from "./ScenarioLauncher";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: vi.fn() }),
  usePathname: () => "/",
}));

// the API's order: the hero is third
const SCENARIOS = [
  { id: "S2", name: "data_incident_cross_domain", tenant: "globex", report: "revenue dashboard looks wrong" },
  { id: "S4D", name: "data_control_no_incident", tenant: "globex", report: "is the revenue table late?" },
  { id: "S1", name: "hero_bad_payment_deploy_with_same_minute_distractor", tenant: "acme", report: "checkout is failing" },
];

const RUN = { job: "job-1", state: "done", scenario: "S1", tenant: "acme", incident: "inc-s1-1" };

beforeEach(() => {
  nav.push.mockReset();
});

describe("ScenarioLauncher", () => {
  it("lists the hero scenario first, marked as the hero, with its name in words and in full", async () => {
    stubFetch({ "/api/scenarios": { body: SCENARIOS } });
    render(<ScenarioLauncher />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-scenario"))).toEqual(["S1", "S2", "S4D"]);
    expect(within(rows[0]).getByText("hero")).toBeTruthy();
    expect(within(rows[1]).queryByText("hero")).toBeNull();
    const name = within(rows[0]).getByText("hero bad payment deploy with same minute distractor");
    expect(name.className).not.toContain("truncate");
    expect(name.getAttribute("title")).toBe("hero_bad_payment_deploy_with_same_minute_distractor");
    expect(within(rows[0]).getByRole("button", { name: /Run scenario S1 \(the hero incident\)/ })).toBeTruthy();
  });

  it("starts the hero scenario when the home call to action asks, and opens its incident room", async () => {
    const { calls } = stubFetch({ "/api/scenarios/S1/run": { body: RUN }, "/api/scenarios": { body: SCENARIOS } });
    render(<ScenarioLauncher />);
    await screen.findAllByRole("listitem");
    act(() => requestHeroRun());
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/incidents/inc-s1-1?tenant=acme"));
    const run = calls.filter((c) => c.url.includes("/run"));
    expect(run).toHaveLength(1);
    expect(run[0].url).toContain("/api/scenarios/S1/run");
    expect(JSON.parse(String(run[0].init?.body))).toEqual({ llm: "baseline" });
  });

  it("remembers a hero request made before the list arrives and runs it on the hero's tenant", async () => {
    const { calls } = stubFetch({ "/api/scenarios/S1/run": { body: RUN }, "/api/scenarios": { body: SCENARIOS } });
    render(<ScenarioLauncher />);
    act(() => requestHeroRun()); // the list is still loading
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/incidents/inc-s1-1?tenant=acme"));
    expect(calls.filter((c) => c.url.includes("/run"))).toHaveLength(1);
  });

  it("says why when the hero run cannot start (fails loudly, no fake incident)", async () => {
    stubFetch({
      "/api/scenarios/S1/run": { status: 503, body: { detail: "FalkorDB unreachable" } },
      "/api/scenarios": { body: SCENARIOS },
    });
    render(<ScenarioLauncher />);
    await screen.findAllByRole("listitem");
    act(() => requestHeroRun());
    expect((await screen.findByRole("alert")).textContent).toMatch(/Run not started: .*FalkorDB unreachable/);
    expect(nav.push).not.toHaveBeenCalled();
  });
});
