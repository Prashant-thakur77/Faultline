import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { stubFetch } from "@/test/fixtures";
import { INSIGHT } from "@/test/engineFixture";
import { EngineView } from "./EngineView";
import { resetTemplatePurposes } from "./useTemplatePurposes";

const TEMPLATE = { id: "Q-META-1", purpose: "parking pattern: is this graph fully seeded? (Meta.ready)", cypher: "MATCH (m:Meta) RETURN m LIMIT 1", file: "meta.cypher", limit: 1 };

function show() {
  return render(
    <CypherPanelProvider>
      <EngineView />
    </CypherPanelProvider>,
  );
}

const section = (name: string) => screen.getByRole("heading", { name }).closest("section") as HTMLElement;

beforeEach(() => resetTemplatePurposes());

describe("Inside FalkorDB right now", () => {
  it("leads with the verdict: graphs, memory, query count, the busiest template's p50/p95, timeouts", async () => {
    const { calls } = stubFetch({ "/api/engine/insight": { body: INSIGHT }, "/api/templates/": { body: TEMPLATE } });
    show();
    expect(await screen.findByRole("heading", { level: 2, name: "FalkorDB · 3 graphs for acme · 7 MB" })).toBeTruthy();
    const verdict = screen.getByRole("heading", { name: /^FalkorDB/ }).closest("section")!;
    expect(verdict.textContent).toMatch(/1,400 queries in the last 1 h 57 min · busiest Q-META-1 p50 0\.15 ms, p95 0\.38 ms · 0 timeouts/);
    expect(verdict.textContent).toMatch(/0 running, 0 waiting now/);
    expect(verdict.textContent).toMatch(/no query text, no parameters/);
    expect(calls[0].url).toContain("/api/engine/insight?tenant=acme");
  });

  it("memory per graph: the sparse-matrix line, every part in words, the engine's whole-MB rounding said", async () => {
    stubFetch({ "/api/engine/insight": { body: INSIGHT }, "/api/templates/": { body: TEMPLATE } });
    show();
    const mem = await waitFor(() => section("Memory per graph"));
    expect(mem.textContent).toMatch(/sparse adjacency matrices \(GraphBLAS\)/);
    expect(within(mem).getByText("via FalkorDB")).toBeTruthy();
    expect(within(mem).getByText("GRAPH.MEMORY USAGE")).toBeTruthy();
    const tiles = within(mem).getByRole("list", { name: "Graphs of this tenant" });
    const tenant = within(tiles).getAllByRole("listitem")[0];
    expect(tenant.textContent).toMatch(/tenant_acme/);
    expect(tenant.textContent).toMatch(/live tenant graph/);
    expect(tenant.textContent).toMatch(/Node attributes1 MB/);
    expect(tenant.textContent).toMatch(/Not itemised1 MB/);
  });

  it("queries by template: runs, p50/p95, plan-cache bar, timeouts; a template opens its Cypher, a writer does not", async () => {
    stubFetch({ "/api/engine/insight": { body: INSIGHT }, "/api/templates/": { body: TEMPLATE } });
    show();
    const card = await waitFor(() => section("Queries by template"));
    const table = within(card).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    const idOf = (r: HTMLElement) => (within(r).queryByRole("button")?.textContent ?? within(r).getAllByRole("cell")[0].querySelector("span")?.textContent ?? "").trim();
    expect(rows.map(idOf)).toEqual(["Q-META-1", "Q-INC-1", "W-STAGE"]);
    expect(within(rows[0]).getByText("58")).toBeTruthy();
    expect(within(rows[0]).getByText("15.5%")).toBeTruthy();
    // the catalogue's purpose is the row's title (read from GET /api/templates/{id})
    expect(await within(rows[0]).findByText(/parking pattern: is this graph fully seeded/)).toBeTruthy();
    expect(within(rows[2]).getByText("one atomic write (graph/writes.py)")).toBeTruthy();
    expect(within(rows[2]).queryByRole("button")).toBeNull();
    expect(card.textContent).toMatch(/\+225 ad-hoc queries .* counted only, never shown/);
    // phones get the same rows as a list (CSS picks one), with every number written out
    const items = within(within(card).getByRole("list", { name: /^Queries by template or writer id/ })).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toMatch(/58 runs.*p50 0\.15 ms.*p95 0\.38 ms.*cache.*15\.5%.*0 timeouts/);
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Q-META-1: open the Cypher panel for this template" }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("filters to one graph and to writes", async () => {
    stubFetch({ "/api/engine/insight": { body: INSIGHT }, "/api/templates/": { body: TEMPLATE } });
    show();
    const card = await waitFor(() => section("Queries by template"));
    fireEvent.change(within(card).getByLabelText("Graph"), { target: { value: "eval_acme_api_v2_s1_1_abcd" } });
    expect(within(within(card).getByRole("table")).getAllByRole("row")).toHaveLength(2);
    fireEvent.change(within(card).getByLabelText("Graph"), { target: { value: "" } });
    fireEvent.click(within(card).getByRole("button", { name: "Writes" }));
    expect(within(card).getByRole("button", { name: "Writes" }).getAttribute("aria-pressed")).toBe("true");
    const rows = within(within(card).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toMatch(/W-STAGE/);
  });

  it("the live tail lists the newest queries across graphs with their split, and pause stops the reads", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { calls } = stubFetch({ "/api/engine/insight": { body: INSIGHT }, "/api/templates/": { body: TEMPLATE } });
      show();
      const tail = await waitFor(() => section("Live tail"));
      const items = within(within(tail).getByRole("list", { name: "Most recent queries, newest first" })).getAllByRole("listitem");
      const idOf = (i: HTMLElement) => (within(i).queryByRole("button")?.textContent ?? i.querySelector("span.inline-flex")?.textContent ?? "").trim();
      expect(items.map(idOf)).toEqual(["Q-INC-1", "Q-ONCALL-NOW", "W-STAGE"]);
      expect(items[1].textContent).toMatch(/wait 0\.07.*execution 0\.30.*report 0\.57/);
      expect(within(items[2]).getByText("cached plan")).toBeTruthy();
      const reads = () => calls.filter((c) => c.url.includes("/api/engine/insight")).length;
      const before = reads();
      await vi.advanceTimersByTimeAsync(5_100);
      await waitFor(() => expect(reads()).toBeGreaterThan(before));
      fireEvent.click(within(tail).getByRole("button", { name: "Pause updates" }));
      expect(within(tail).getByRole("button", { name: "Resume updates" })).toBeTruthy();
      expect(tail.textContent).toMatch(/Paused: these are the numbers as last read/);
      const paused = reads();
      await vi.advanceTimersByTimeAsync(15_000);
      expect(reads()).toBe(paused);
      expect(screen.getByText("FalkorDB · 3 graphs for acme · 7 MB")).toBeTruthy(); // the last numbers stay
    } finally {
      vi.useRealTimers();
    }
  });

  it("the guards: memory cap, timeouts, queue, cache, telemetry window, load, and egress said with its limit", async () => {
    stubFetch({ "/api/engine/insight": { body: INSIGHT }, "/api/templates/": { body: TEMPLATE } });
    show();
    const g = await waitFor(() => section("Engine guards"));
    expect(g.textContent).toMatch(/Memory per query256 MB/);
    expect(g.textContent).toMatch(/Query timeout2 s default · 10 s max/);
    expect(g.textContent).toMatch(/50 queued · 20 threads/);
    expect(g.textContent).toMatch(/last 1,000 per graph/);
    expect(g.textContent).toMatch(/none in production/);
    expect(g.textContent).toMatch(/The development compose does not isolate it/);
  });

  it("fails loudly: FalkorDB down (503), an API without the endpoint, and an unreachable API each say so and show no numbers", async () => {
    stubFetch({ "/api/engine/insight": { status: 503, body: { detail: "FalkorDB unreachable (ConnectionError)" } } });
    const { unmount } = show();
    expect((await screen.findByRole("alert")).textContent).toMatch(/FalkorDB is unavailable: FalkorDB unreachable \(ConnectionError\) \(HTTP 503\)/);
    expect(screen.queryByRole("heading", { name: "Memory per graph" })).toBeNull();
    unmount();
    stubFetch({ "/api/engine/insight": { status: 404, body: { detail: "Not Found" } } });
    const second = show();
    expect(await screen.findByRole("heading", { name: "The engine panel is not on this server" })).toBeTruthy();
    second.unmount();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    show();
    expect((await screen.findByRole("alert")).textContent).toMatch(/Inside FalkorDB \(GET \/api\/engine\/insight\) is unavailable: Faultline API unreachable/);
  });

  it("an engine with no recorded query yet says so instead of an empty table", async () => {
    const empty = {
      ...INSIGHT,
      graphs: { golden_acme: INSIGHT.graphs.golden_acme },
      templates: { entries: 0, from: null, to: null, queries: [], unmapped: { n: 0 } },
    };
    stubFetch({ "/api/engine/insight": { body: empty } });
    show();
    expect(await screen.findByText(/No query recorded in the telemetry streams yet/)).toBeTruthy();
    expect(screen.getByText(/No query recorded yet in these graphs' telemetry streams/)).toBeTruthy();
    expect(screen.getByText("No mapped query in the streams yet.")).toBeTruthy();
  });
});
