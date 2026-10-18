import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import type { StatusState } from "@/hooks/useStatus";
import type { StatusResponse, UdfDetail, UdfLibrary } from "@/lib/types";
import { stubFetch } from "@/test/fixtures";
import { UdfCard } from "./EngineUdf";

const FLEX: UdfLibrary = {
  state: "loaded",
  pinned_sha: "e7e833ba87f8",
  loaded_sha: "e7e833ba87f8",
  functions: Array.from({ length: 41 }, (_, i) => `fn.f${i}`),
  used: ["sim.jaccard", "text.jaroWinkler"],
  templates: ["Q-COUPLE-2", "Q-RESOLVE-1"],
};

const OURS: UdfLibrary = {
  state: "loaded",
  pinned_sha: "55cd126a097d",
  loaded_sha: "55cd126a097d",
  functions: ["capImpact", "impact", "noteScore", "round4", "tierWeight"],
  used: ["capImpact", "impact", "noteScore"],
  templates: ["Q-BLAST-1", "Q-NOTE-2"],
};

const BASE: StatusResponse = {
  status: "ok",
  engine: { engine: "FalkorDB 6.0.2", digest: "sha256:x" },
  tenant: "acme",
  graph: "tenant_acme",
  acl: "ro_user",
  graph_disabled: false,
  models: { orchestrator: "x", specialists: "y" },
  llm_configured: false,
  templates: 90,
};

const TEMPLATE = { id: "Q-COUPLE-2", purpose: "hidden coupling", cypher: "RETURN flex.sim.jaccard([1], [1]) AS j", file: "x.cypher", limit: 1 };

function show(state: StatusState) {
  return render(
    <CypherPanelProvider>
      <UdfCard tenant="acme" state={state} />
    </CypherPanelProvider>,
  );
}

const ok = (udf_detail?: UdfDetail): StatusState => ({ status: { ...BASE, udf_detail }, error: null, loading: false });
const card = () => screen.getByRole("heading", { name: "UDF libraries in the engine" }).closest("section") as HTMLElement;

describe("UDF libraries in the engine", () => {
  it("both loaded: state, pinned sha, the functions our queries call, and templates that open their Cypher", async () => {
    stubFetch({ "/api/templates/": { body: TEMPLATE } });
    show(ok({ flex: FLEX, faultline: OURS }));
    const c = card();
    expect(c.textContent).toMatch(/Functions loaded into FalkorDB with GRAPH\.UDF LOAD, pinned by sha256, called inside read-only queries\./);
    expect(within(c).getByText("GRAPH.UDF LIST")).toBeTruthy();
    expect(within(c).getByText("2 of 2 loaded")).toBeTruthy();
    const [flex, ours] = Array.from(within(c).getByRole("list", { name: "UDF libraries" }).children) as HTMLElement[];
    expect(flex.textContent).toMatch(/flexFalkorDB's FLEX, vendored unmodified/);
    expect(within(flex).getByText("loaded")).toBeTruthy();
    expect(within(flex).getByText("e7e833ba87f8")).toBeTruthy();
    // flex: only the 2 of 41 the queries call, with their prefix
    const called = within(within(flex).getByRole("list", { name: "flex: functions our queries call" })).getAllByRole("listitem");
    expect(called.map((li) => li.textContent)).toEqual(["flex.sim.jaccard", "flex.text.jaroWinkler"]);
    // ours: every function
    expect(ours.textContent).toMatch(/ours: scoring that runs inside the engine/);
    const fns = within(within(ours).getByRole("list", { name: "faultline: functions" })).getAllByRole("listitem");
    expect(fns.map((li) => li.textContent)).toEqual(["faultline.capImpact", "faultline.impact", "faultline.noteScore", "faultline.round4", "faultline.tierWeight"]);
    expect(within(ours).getByText("Functions (5)")).toBeTruthy();
    expect(within(ours).getByRole("button", { name: "Q-BLAST-1: open the Cypher panel for this template" })).toBeTruthy();
    expect(within(c).queryByRole("alert")).toBeNull();
    fireEvent.click(within(flex).getByRole("button", { name: "Q-COUPLE-2: open the Cypher panel for this template" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/Q-COUPLE-2 · calls flex/);
  });

  it("one missing: a fail chip with the plain reason, the card's summary says so, and a different sha is named", () => {
    stubFetch({});
    const { unmount } = show(ok({ flex: FLEX, faultline: { ...OURS, state: "missing", loaded_sha: null, functions: [] } }));
    const c = card();
    expect(within(c).getByText("1 of 2 not loaded as pinned")).toBeTruthy();
    expect(within(c).getByText("not loaded")).toBeTruthy();
    expect(c.textContent).toMatch(/Not loaded in FalkorDB, so the queries below fail\. Restart the API or run make up\./);
    // not loaded: the engine reports no functions, so the card lists the ones the queries call
    expect(within(within(c).getByRole("list", { name: "faultline: functions our queries call" })).getAllByRole("listitem")).toHaveLength(3);
    unmount();
    show(ok({ flex: { ...FLEX, state: "mismatch", loaded_sha: "0123456789ab" }, faultline: OURS }));
    const m = card();
    expect(within(m).getByText("different code loaded")).toBeTruthy();
    expect(m.textContent).toMatch(/sha256 0123456789ab, pinned e7e833ba87f8/);
  });

  it("fails loudly: GRAPH.UDF LIST refused, FalkorDB down, an API that does not answer; and says so when the status has no detail", () => {
    stubFetch({});
    const a = show(ok({ error: "GRAPH.UDF LIST failed: unknown command" }));
    expect(within(card()).getByRole("alert").textContent).toMatch(/FalkorDB did not list its libraries \(GRAPH\.UDF LIST\): GRAPH\.UDF LIST failed: unknown command\. No library is shown as loaded\./);
    expect(within(card()).getByText("unreadable")).toBeTruthy();
    expect(within(card()).queryByText("loaded")).toBeNull();
    a.unmount();
    const b = show({ status: { ...BASE, status: "unavailable", reason: "FalkorDB unreachable (ConnectionError)" }, error: null, loading: false });
    expect(within(card()).getByRole("alert").textContent).toMatch(/FalkorDB is unavailable: FalkorDB unreachable \(ConnectionError\)\. The libraries cannot be read/);
    b.unmount();
    const d = show({ status: null, error: "Faultline API unreachable", loading: false });
    expect(within(card()).getByRole("alert").textContent).toMatch(/did not answer \(GET \/api\/status\): Faultline API unreachable/);
    d.unmount();
    show(ok(undefined));
    expect(card().textContent).toMatch(/This server's status has no library detail, so nothing is shown here\./);
    expect(within(card()).queryByRole("list", { name: "UDF libraries" })).toBeNull();
  });
});
