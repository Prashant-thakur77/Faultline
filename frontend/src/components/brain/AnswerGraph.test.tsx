import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { layoutBrainGraph, subgraphIds, touching } from "@/lib/brainGraph";
import type { BrainAnswer, BrainSubgraph, TemplateInfo } from "@/lib/types";
import { BRAIN_ANSWER, BRAIN_SUBGRAPH } from "@/test/brainSubgraphFixture";
import { stubFetch } from "@/test/fixtures";
import { AnswerGraph } from "./AnswerGraph";

// reduced motion: nodes and lines appear without a framer animation that happy-dom would cancel at unmount
beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => vi.unstubAllGlobals());

const TEMPLATE: TemplateInfo = {
  id: "Q-BRAIN-SUB",
  purpose: "a brain answer drawn as a graph",
  cypher: BRAIN_SUBGRAPH.cypher,
  file: "brain_subgraph.cypher",
  limit: 60,
};

const REQUESTED = BRAIN_SUBGRAPH.params.ids as string[];

function renderGraph(answer: BrainAnswer = BRAIN_ANSWER, sub: { status?: number; body: unknown } = { body: BRAIN_SUBGRAPH }) {
  const stub = stubFetch({ "/api/brain/subgraph": sub, "/api/templates/": { body: TEMPLATE } });
  render(
    <CypherPanelProvider>
      <AnswerGraph answer={answer} />
    </CypherPanelProvider>,
  );
  return stub;
}

/** The node ids of each drawn column, top to bottom (cards are laid out column by column). */
function columns(): string[][] {
  const out: string[][] = [];
  let lastX = Number.NaN;
  for (const b of document.querySelectorAll<HTMLElement>("[data-node-id]")) {
    const x = Number.parseFloat((b.parentElement as HTMLElement).style.left);
    const cited = b.dataset.cited === "true";
    const colX = cited ? x : x - 6; // connecting cards are narrower and centred in their column
    if (colX !== lastX) out.push([]);
    lastX = colX;
    out.at(-1)!.push(b.dataset.nodeId!);
  }
  return out;
}

describe("layoutBrainGraph", () => {
  it("is deterministic: the same picture for the same payload, whatever order the rows came back in", () => {
    const a = layoutBrainGraph(BRAIN_SUBGRAPH, REQUESTED);
    const b = layoutBrainGraph(BRAIN_SUBGRAPH, REQUESTED);
    expect(b).toEqual(a);
    const shuffled: BrainSubgraph = { ...BRAIN_SUBGRAPH, nodes: [...BRAIN_SUBGRAPH.nodes].reverse(), edges: [...BRAIN_SUBGRAPH.edges].reverse() };
    const c = layoutBrainGraph(shuffled, REQUESTED);
    const pos = (l: typeof a) => Object.fromEntries(l.nodes.map((n) => [n.id, [n.x, n.y, n.w, n.h]]));
    expect(pos(c)).toEqual(pos(a));
    expect(c.pairs.map((p) => [p.key, p.d]).sort()).toEqual(a.pairs.map((p) => [p.key, p.d]).sort());
  });

  it("lays nodes out in columns by kind (who → decisions → context → systems) and keeps every edge once", () => {
    const l = layoutBrainGraph(BRAIN_SUBGRAPH, REQUESTED);
    expect(l.columns.map((c) => `${c.title} ${c.count}`)).toEqual(["Who 7", "Decisions 2", "Context 2", "Systems 2"]);
    const col = (i: number) => l.nodes.filter((n) => n.col === i).map((n) => n.id);
    expect(col(0)).toEqual(["p-004", "p-022", "p-017", "p-030", "p-034", "p-036", "team-payments"]);
    expect(col(1)).toEqual(["ADR-012", "ADR-013"]);
    expect(col(2)).toEqual(["doc-chat-payment-timeouts", "inc-h028"]);
    expect(col(3)).toEqual(["payment", "checkout"]);
    expect(l.edges).toHaveLength(BRAIN_SUBGRAPH.edges.length);
    // COLLABORATES both ways plus REPORTS_TO between the same two people share one line with arrows at both ends
    const pair = l.pairs.find((p) => p.key === "p-004|p-017")!;
    expect(pair.rels).toEqual(["COLLABORATES", "REPORTS_TO"]);
    expect(pair.forward && pair.backward).toBe(true);
    expect(l.unconnected).toEqual([]);
    expect(l.width).toBeLessThanOrEqual(760); // fits the answer column on a desktop; scrolls inside the card below that
  });

  it("splits cited from connecting nodes when every node is one kind; unknown labels fall back gracefully", () => {
    const l = layoutBrainGraph(
      {
        nodes: [
          { id: "svc-a", label: "Service", name: "a", cited: true },
          { id: "svc-b", label: "Service", name: "b", cited: true },
          { id: "svc-m", label: "Service", name: "m", cited: false },
        ],
        edges: [
          { rel: "CALLS", source: "svc-a", target: "svc-m" },
          { rel: "CALLS", source: "svc-m", target: "svc-b" },
          { rel: "CALLS", source: "svc-m", target: "ghost" },
        ],
      },
      ["svc-a", "svc-b", "svc-z"],
    );
    expect(l.columns.map((c) => c.title)).toEqual(["Cited", "Connecting"]);
    expect(l.edges).toHaveLength(2); // an edge to a node the payload does not hold is never drawn
    expect(l.unconnected).toEqual(["svc-z"]);
    const odd = layoutBrainGraph({ nodes: [{ id: "x", label: null, name: null, cited: true }], edges: [] });
    expect(odd.nodes[0]).toMatchObject({ label: "Node", name: "x" });
  });

  it("lights only the lines touching a node; caps and dedupes the ids it asks for", () => {
    const l = layoutBrainGraph(BRAIN_SUBGRAPH, REQUESTED);
    const lit = touching("ADR-012", l.pairs);
    expect([...lit.nodes].sort()).toEqual(["ADR-012", "doc-chat-payment-timeouts", "p-004", "p-022", "payment"]);
    expect(lit.pairs.size).toBe(4);
    const many = Array.from({ length: 15 }, (_, i) => `id-${i}`);
    expect(subgraphIds([...many, "id-0", " ", "a,b"])).toEqual({ ids: many.slice(0, 12), total: 15 });
  });
});

describe("AnswerGraph", () => {
  it("asks for the answer's citations and draws cited nodes filled, connecting nodes outlined and smaller", async () => {
    const { calls } = renderGraph();
    await screen.findByRole("group", { name: /^Answer graph: 13 nodes/ });
    const url = calls.find((c) => c.url.includes("/api/brain/subgraph"))!.url;
    expect(url).toContain("tenant=acme");
    expect(decodeURIComponent(url)).toContain("ids=ADR-012,ADR-013,p-004,p-022,payment");
    expect(columns()).toEqual([
      ["p-004", "p-022", "p-017", "p-030", "p-034", "p-036", "team-payments"],
      ["ADR-012", "ADR-013"],
      ["doc-chat-payment-timeouts", "inc-h028"],
      ["payment", "checkout"],
    ]);

    const cited = screen.getByRole("button", { name: /Dorian Marrowby.*Cited in the answer/ });
    expect(cited.querySelector("svg [fill]")!.getAttribute("fill")).not.toBe("none");
    expect(cited.querySelector("svg")!.getAttribute("width")).toBe("14");
    expect(cited.querySelector("svg")!.dataset.shape).toBe("circle");
    const via = screen.getByRole("button", { name: /^Payments.*Connects cited ids/ });
    expect(via.querySelector("svg [fill]")!.getAttribute("fill")).toBe("none");
    expect(via.querySelector("svg")!.getAttribute("width")).toBe("11");
    expect(via.querySelector("svg")!.dataset.shape).toBe("hexagon");
    expect(via.className).toContain("border-dashed");
    expect(document.querySelectorAll('[data-cited="true"]')).toHaveLength(5);

    const decision = screen.getByRole("button", { name: /Payment client keeps ≥ 2 retries/ });
    expect(decision.querySelector("svg")!.dataset.shape).toBe("diamond");

    // legend: kinds, filled vs outlined in words, and every relationship type with its ends
    const rels = screen.getByRole("list", { name: "Relationship types" });
    expect(within(rels).getByText("DECIDED").parentElement!.textContent).toContain("Person → Decision ×4");
    expect(within(rels).getByText("MEMBER_OF")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "Node kinds" })).getByText("filled: cited in the answer")).toBeTruthy();
  });

  it("lights a node's edges on hover and focus, and names them", async () => {
    renderGraph();
    const btn = await screen.findByRole("button", { name: /Payment client timeout must stay/ });
    expect(document.querySelectorAll("[data-lit]")).toHaveLength(0);
    fireEvent.focus(btn);
    const lit = [...document.querySelectorAll<SVGGElement>("[data-lit]")].map((g) => g.dataset.pair).sort();
    expect(lit).toEqual(["ADR-012|doc-chat-payment-timeouts", "ADR-012|payment", "p-004|ADR-012", "p-022|ADR-012"]);
    expect([...document.querySelectorAll("svg text")].map((t) => t.textContent).sort()).toEqual(["CITES", "CONSTRAINS", "DECIDED", "DECIDED"]);
    fireEvent.blur(btn);
    expect(document.querySelectorAll("[data-lit]")).toHaveLength(0);
    fireEvent.mouseEnter(btn);
    expect(document.querySelectorAll("[data-lit]")).toHaveLength(4);
  });

  it("repeats the graph as a text list of edges, A —REL→ B", async () => {
    renderGraph();
    await screen.findByRole("group", { name: /^Answer graph/ });
    expect(screen.getByText(/Text alternative: the 36 edges as a list/)).toBeTruthy();
    const items = within(screen.getByRole("list", { name: "Edges of the answer graph" })).getAllByRole("listitem");
    expect(items).toHaveLength(36);
    expect(items[0].textContent).toBe("Dorian Marrowby (p-004) —DECIDED→ Payment client timeout must stay ≤ 2000 ms (ADR-012)");
  });

  it("opens the Cypher panel for Q-BRAIN-SUB with the API's params, from a node and from the header", async () => {
    renderGraph();
    fireEvent.click(await screen.findByRole("button", { name: /Vesna Hollowell.*Open the Cypher panel/ }));
    const panel = await screen.findByRole("dialog", { name: /p-022 · answer as a graph/ });
    await waitFor(() => expect(within(panel).getAllByText(/brain_subgraph\.cypher|Q-BRAIN-SUB/).length).toBeGreaterThan(0));
    await waitFor(() => expect((within(panel).getByRole("textbox") as HTMLTextAreaElement).value).toContain('"ADR-012"'));
    expect(within(panel).getByText(/cited node p-022 \(Person\)/)).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "Close Cypher panel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: /Q-BRAIN-SUB.*open the query that draws this graph/ }));
    const whole = await screen.findByRole("dialog", { name: /answer brain-680304d11e as a graph/ });
    await waitFor(() => expect((within(whole).getByRole("textbox") as HTMLTextAreaElement).value).toContain('"p-004"'));
    fireEvent.click(within(whole).getByRole("button", { name: "Close Cypher panel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("says 'graph unavailable' on a 503 and draws nothing in its place", async () => {
    renderGraph(BRAIN_ANSWER, { status: 503, body: { detail: "FalkorDB unreachable" } });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Graph unavailable: FalkorDB unreachable \(HTTP 503\)/);
    expect(screen.queryByRole("group", { name: /^Answer graph/ })).toBeNull();
    expect(document.querySelectorAll("[data-node-id]")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toMatch(/Answer graph unavailable/);
  });

  it("shows any other error verbatim, and retries", async () => {
    const { fn } = renderGraph(BRAIN_ANSWER, { status: 422, body: { detail: "ids: 1-12 comma-separated node ids" } });
    expect((await screen.findByRole("alert")).textContent).toMatch(/Could not draw the answer graph: ids: 1-12 comma-separated node ids \(HTTP 422\)/);
    const before = fn.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(fn.mock.calls.length).toBe(before + 1));
    await screen.findByRole("alert");
  });

  it("says when the query was truncated and which cited ids connect to nothing", async () => {
    renderGraph({ ...BRAIN_ANSWER, citations: [...BRAIN_ANSWER.citations, "ADR-999"] }, { body: { ...BRAIN_SUBGRAPH, truncated: true } });
    expect(await screen.findByText(/Truncated: the query hit its row limit/)).toBeTruthy();
    expect(screen.getByText(/Not connected to another cited id within 2 hops/).textContent).toContain("ADR-999");
  });

  it("announces loading politely, then the counts", async () => {
    renderGraph();
    expect(screen.getByRole("status").textContent).toBe("Loading the answer graph");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Answer graph loaded: 13 nodes, 36 edges"));
  });

  it("hides and shows on the toggle", async () => {
    renderGraph();
    await screen.findByRole("group", { name: /^Answer graph/ });
    const toggle = screen.getByRole("button", { name: /Hide the answer as a graph/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(screen.queryByRole("group", { name: /^Answer graph/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Show the answer as a graph/ }).getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: /Show the answer as a graph/ }));
    await screen.findByRole("group", { name: /^Answer graph/ });
  });

  it("is not offered for an answer with fewer than two citations (and asks for nothing)", () => {
    const { fn } = renderGraph({ ...BRAIN_ANSWER, citations: ["payment"] });
    expect(screen.queryByText("Answer as a graph")).toBeNull();
    expect(fn).not.toHaveBeenCalled();
  });
});
