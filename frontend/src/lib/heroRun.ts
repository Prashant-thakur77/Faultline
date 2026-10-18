/**
 * The home page's "Run the hero incident" call to action and the scenario launcher live in different components:
 * the button asks with a window event, the launcher (which owns the run state, the errors and the redirect) answers
 * by starting the hero scenario. No launcher on the page: nothing happens beyond the button's own scroll to #run.
 */

/** The hero scenario: a bad payment deploy with a same-minute distractor (data/scenarios/scenarios.yaml). */
export const HERO_SCENARIO = "S1";

export const RUN_HERO_EVENT = "faultline:run-hero";

export function requestHeroRun(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(RUN_HERO_EVENT));
}

/** The data incident (S2): the executive revenue KPI jumps after a payment-provider cutover; the agent proposes the
 *  transform repair from its own measurements and the lineage graph, and the warehouse rebuild verifies it. */
export const DATA_SCENARIO = "S2";

export const RUN_SCENARIO_EVENT = "faultline:run-scenario";

/** Ask the launcher on the page to start `id` (the hero button's mechanism, for any seeded scenario). */
export function requestScenarioRun(id: string): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(RUN_SCENARIO_EVENT, { detail: { id } }));
}
