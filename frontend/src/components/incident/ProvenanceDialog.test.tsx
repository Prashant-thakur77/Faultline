import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import type { IncidentView } from "@/lib/types";
import { stubFetch } from "@/test/fixtures";
import { PROVENANCE } from "@/test/provenanceFixture";
import { WhyBelieveButton } from "./ProvenanceDialog";
import { useIncidentActions } from "./useIncidentActions";

beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => vi.unstubAllGlobals());

const VIEW: IncidentView = {
  incident: {
    id: PROVENANCE.incident,
    title: "checkout errors",
    stage: "RESOLVED",
    onset_at: 0,
    opened_at: 0,
    confident: true,
    targets: ["checkout"],
    kinds: [],
  },
  run: { run: "run-test", graph: "tenant_acme", scenario: "test", outcome: "CONFIRMED", cause: "D-pay-417", investigator: "code" },
  stages: [],
  tool_calls: [],
  hypotheses: [
    { id: "h1", cause: "D-pay-417", status: "confirmed", score: 1, reason: null, origin: "code", supports: [], refutes: [] },
  ],
  gate_runs: [],
  report: {
    incident_id: PROVENANCE.incident,
    outcome: "CONFIRMED",
    confident: true,
    cause_id: "D-pay-417",
    mechanism: [],
    proven: [],
    inferred: [],
    rejected: [],
    evidence: [],
  },
};

function Harness({ view, mode }: { view: IncidentView; mode: "live" | "replay" }) {
  const actions = useIncidentActions(view);
  return <WhyBelieveButton view={view} mode={mode} actions={actions} />;
}

function renderButton(view: IncidentView = VIEW, mode: "live" | "replay" = "live") {
  return render(
    <CypherPanelProvider>
      <Harness view={view} mode={mode} />
    </CypherPanelProvider>,
  );
}

const TEMPLATE = { id: "Q-GATE-UPSTREAM-UB", purpose: "test", cypher: "MATCH (n) RETURN n LIMIT 1", file: "t.cypher", limit: 1 };

describe("Why do you believe this?", () => {
  it("is absent when the incident has no confirmed cause", () => {
    renderButton({ ...VIEW, hypotheses: VIEW.hypotheses.map((h) => ({ ...h, status: "open" as const })) });
    expect(screen.queryByRole("button", { name: /Why do you believe this/ })).toBeNull();
  });

  it("is disabled and marked live only for a recording", () => {
    const { fn } = stubFetch({});
    renderButton(VIEW, "replay");
    const b = screen.getByRole("button", { name: /Why do you believe this/ }) as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    expect(b.textContent).toContain("live only");
    expect(fn).not.toHaveBeenCalled();
  });

  it("opens a labelled dialog with the graph, opens a call's Cypher panel, and Esc closes it back to the button", async () => {
    const { calls } = stubFetch({ "/provenance": { body: PROVENANCE }, "/api/templates/": { body: TEMPLATE } });
    renderButton();
    const open = screen.getByRole("button", { name: /Why do you believe this/ });
    fireEvent.click(open);
    const dialog = await screen.findByRole("dialog", { name: "Why do you believe this?" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(within(dialog).getByText(/Every arrow below is a stored edge in FalkorDB \(Q-PROV-1\)/)).toBeTruthy();
    await within(dialog).findByRole("list", { name: /^Agents/ });
    expect(calls.some((c) => c.url.includes(`/api/incidents/${PROVENANCE.incident}/provenance?tenant=`))).toBe(true);

    fireEvent.click(within(dialog).getByRole("button", { name: /Tool call run-s1-363667c4-tc0042/ }));
    const cypher = await screen.findByRole("dialog", { name: /upstream_explained/ });
    expect(cypher).toBeTruthy();
    fireEvent.click(within(cypher).getByRole("button", { name: "Close Cypher panel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /upstream_explained/ })).toBeNull());

    fireEvent.keyDown(screen.getByRole("dialog", { name: "Why do you believe this?" }), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Why do you believe this?" })).toBeNull());
    expect(document.activeElement).toBe(open);
  });

  it("fails loudly when the graph is unavailable, and never draws a graph", async () => {
    stubFetch({ "/provenance": { status: 503, body: { detail: "FalkorDB unreachable" } } });
    renderButton();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Why do you believe this/ }));
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Graph unavailable:");
    expect(alert.textContent).toContain("FalkorDB unreachable");
    expect(screen.queryByRole("list", { name: /^Agents/ })).toBeNull();
  });
});
