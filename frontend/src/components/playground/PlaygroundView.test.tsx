import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { stubFetch } from "@/test/fixtures";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { PlaygroundView } from "./PlaygroundView";

const MENU = {
  scenario: "S1",
  perturbations: [
    { id: "cut", label: "Remove the call a → b", what: "deletes the edge", expect: "G2 withdraws the claim", algorithm: "algo.SPpaths" },
    { id: "cap", label: "Raise a cap", what: "sets cap", expect: "G4 still holds", algorithm: "algo.maxFlow" },
  ],
};
const RESULT = {
  scenario: "S1",
  perturbation: MENU.perturbations[0],
  applied: { deleted: 1 },
  seconds: 1.2,
  changed: ["outcome", "suspect D-1"],
  diff: [
    { decision: "outcome", before: "CONFIRMED", after: "UNKNOWN_ESCALATED", changed: true, templates: ["Q-GATE-1"] },
    { decision: "who_fixes", before: ["p-1"], after: ["p-1"], changed: false, templates: ["Q-ORG-HARM"] },
    { decision: "suspect D-1", before: { status: "candidate", reason: "G5 ok" }, after: { status: "eliminated", reason: "G2: no path" }, changed: true, templates: ["Q-GATE-1"] },
  ],
};

describe("PlaygroundView: break the graph", () => {
  it("lists the menu, runs the picked change and marks what moved in text, with the deciding templates", async () => {
    const { calls } = stubFetch({ "/api/playground/cut": { body: RESULT }, "/api/playground": { body: MENU } });
    render(
      <CypherPanelProvider>
        <PlaygroundView />
      </CypherPanelProvider>,
    );
    // the radio's name starts with the option title (the recorder picks options this way)
    expect(await screen.findByRole("radio", { name: /^Remove the call a → b/ })).toBeTruthy();
    expect(screen.getByText(/G4 still holds/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Break it" }));
    await waitFor(() => expect(screen.getByText("2 decisions changed")).toBeTruthy());
    expect(calls.some((c) => c.url.includes("/api/playground/cut") && c.init?.method === "POST")).toBe(true);
    const row = screen.getByRole("rowheader", { name: /^outcome/ }).closest("tr")!;
    expect(within(row).getByText("(changed)")).toBeTruthy();                    // text, not colour alone
    expect(within(row).getByText("UNKNOWN_ESCALATED")).toBeTruthy();
    expect(within(row).getByRole("button", { name: /Q-GATE-1: open the Cypher/ })).toBeTruthy();
    expect(screen.getByText("eliminated: G2: no path")).toBeTruthy();
    const same = screen.getByRole("rowheader", { name: /^who_fixes/ }).closest("tr")!;
    expect(within(same).queryByText("(changed)")).toBeNull();
  });
});
