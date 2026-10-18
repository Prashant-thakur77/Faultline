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
