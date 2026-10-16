import { readFileSync } from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import { parseExplainer } from "./data";
import { FalkorExplainer } from "./FalkorExplainer";
import { DURATIONS, SCENES, TOTAL, emptyShare, pct } from "./scenes";
import { POSE_KEYS, newPose, target } from "./timeline";

// the real static exports the page reads (no hand-made fixture: the explainer must draw what FalkorDB returned)
const pub = (f: string) => JSON.parse(readFileSync(path.resolve(__dirname, "../../../public", f), "utf8"));
const RAW = {
  graph: pub("replay/s1-hero/graph.json"),
  blast: pub("replay/s1-hero/blast.json"),
  plan: pub("replay/s1-hero/plan.json"),
  calls: pub("replay/s1-hero/tool_calls.json"),
  templates: pub("replay/s1-hero/templates.json"),
  summary: pub("evals/summary.json"),
  stats: pub("explainer/graph-stats.json"),
};
const ROUTES = {
  "/replay/s1-hero/graph.json": { body: RAW.graph },
  "/replay/s1-hero/blast.json": { body: RAW.blast },
  "/replay/s1-hero/plan.json": { body: RAW.plan },
  "/replay/s1-hero/tool_calls.json": { body: RAW.calls },
  "/replay/s1-hero/templates.json": { body: RAW.templates },
  "/evals/summary.json": { body: RAW.summary },
  "/explainer/graph-stats.json": { body: RAW.stats },
};

const reducedMotion = (on: boolean) =>
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: on && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));

const mount = () => render(<CypherPanelProvider><FalkorExplainer /></CypherPanelProvider>);
const stage = () => document.querySelector<HTMLElement>("[data-scene]")!;

beforeEach(() => {
  // happy-dom has no IntersectionObserver
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} });
});
afterEach(() => vi.unstubAllGlobals());

describe("FalkorExplainer", () => {
  it("reduced motion: a static, captioned step-through with every scene's caption, numbers from the eval export", async () => {
    reducedMotion(true);
    stubFetch(ROUTES);
    mount();
    await waitFor(() => expect(screen.getAllByTestId("scene-text")).toHaveLength(SCENES.length));
    await waitFor(() => expect(screen.getByText(/max flow is 0\.02, the outage needs 0\.2433/, { selector: "[data-testid=scene-text] p" })).toBeTruthy());
    const items = screen.getAllByTestId("scene-text");
    SCENES.forEach((s, i) => expect(within(items[i]).getByText(s.title)).toBeTruthy());
    expect(stage().dataset.mode).toBe("static");
    // no auto-play under reduced motion: no Play button, the stage stays on scene 1
    expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
    expect(stage().dataset.scene).toBe("1");
    // the fail-closed sentence, not a measured "0 causes" claim, and the right-cause ladder
    expect(screen.getAllByText(/refuses to confirm anything: no graph, no claim\. .*falls from 65 to 43 of 65 cases/).length).toBeGreaterThan(0);
  });

  it("navigates with next, previous, the scene dots and the keyboard; the caption is announced", async () => {
    reducedMotion(true);
    stubFetch(ROUTES);
    mount();
    await waitFor(() => expect(stage().dataset.mode).toBe("static"));
    const live = screen.getByTestId("caption");
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(within(live).getByText(SCENES[0].title)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous scene" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Next scene" }));
    await waitFor(() => expect(stage().dataset.scene).toBe("2"));
    expect(within(live).getByText(SCENES[1].title)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: `Scene 5: ${SCENES[4].title}` }));
    await waitFor(() => expect(stage().dataset.scene).toBe("5"));
    expect(screen.getByRole("button", { name: `Scene 5: ${SCENES[4].title}` }).getAttribute("aria-current")).toBe("step");

    fireEvent.click(screen.getByRole("button", { name: "Previous scene" }));
    await waitFor(() => expect(stage().dataset.scene).toBe("4"));

    fireEvent.keyDown(stage(), { key: "ArrowRight" });
    await waitFor(() => expect(stage().dataset.scene).toBe("5"));
    fireEvent.keyDown(stage(), { key: "End" });
    await waitFor(() => expect(stage().dataset.scene).toBe(String(SCENES.length)));
    expect((screen.getByRole("button", { name: "Next scene" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(stage(), { key: "Home" });
    await waitFor(() => expect(stage().dataset.scene).toBe("1"));
  });

  it("exposes the recorder hooks: go(n) is 1-based and moves the stage", async () => {
    reducedMotion(true);
    stubFetch(ROUTES);
    mount();
    await waitFor(() => expect(window.__explainer).toBeTruthy());
    const api = window.__explainer!;
    expect(api.sceneCount).toBe(SCENES.length);
    expect(api.durations).toEqual(DURATIONS);
    act(() => api.go(7));
    await waitFor(() => expect(stage().dataset.scene).toBe("7"));
    expect(api.state()).toMatchObject({ scene: 7, mode: "static" });
    expect(["playing", "paused", "done"]).toContain(stage().dataset.state);
  });

  it("fails loudly when an export is missing: an alert, and no numbers made up", async () => {
    reducedMotion(true);
    stubFetch({ ...ROUTES, "/evals/summary.json": { status: 404, body: {} } });
    mount();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Explainer data unavailable.*summary\.json: HTTP 404/));
    expect(screen.queryByText(/0\.2433/)).toBeNull();
    expect(screen.getAllByText(/max flow is –, the outage needs –/).length).toBeGreaterThan(0);
  });
});

describe("explainer data and timeline", () => {
  it("reads the hero recording: three suspects, D-rec-12 has no path to checkout, the cut and the ranking", () => {
    const d = parseExplainer(RAW);
    expect(d.changed.map((c) => `${c.deploy}>${c.target}`).sort()).toEqual(["D-email-88>email", "D-pay-417>payment", "D-rec-12>recommendation"]);
    expect(d.paths.find((p) => p.cause === "D-rec-12" && p.symptom === "checkout")?.chain).toEqual([]);
    expect(d.paths.find((p) => p.cause === "D-pay-417" && p.symptom === "checkout")?.chain).toEqual(["D-pay-417", "payment", "checkout"]);
    expect(d.cut.length).toBeGreaterThan(0);
    expect(d.people[0].id).toMatch(/^p-/);
    expect(d.templates["Q-GATE-1"].cypher).toMatch(/algo\.SPpaths/);
  });

  it("a scene of 55-70 s in total; the pose is a pure function of (scene, t)", () => {
    expect(TOTAL).toBeGreaterThanOrEqual(55);
    expect(TOTAL).toBeLessThanOrEqual(70);
    for (let s = 0; s < SCENES.length; s++) {
      const a = target(s, DURATIONS[s] * 0.6, false, newPose());
      const b = target(s, DURATIONS[s] * 0.6, false, newPose());
      for (const k of POSE_KEYS) expect(Number.isFinite(a[k])).toBe(true);
      expect(a).toEqual(b);
    }
  });

  it("matrix emptiness shows the first digit that is not a 9", () => {
    expect(pct(emptyShare(43, 1824))).toBe("99.9987%");
    expect(pct(emptyShare(undefined, 1824))).toBe("–");
  });
});
