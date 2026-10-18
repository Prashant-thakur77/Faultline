import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import type { AgentNotesResponse } from "@/lib/types";
import { stubFetch } from "@/test/fixtures";
import { AgentNotesCard } from "./AgentNotesCard";

const NOW = Date.now();

const NOTES: AgentNotesResponse = {
  rows: [
    {
      id: "note-1",
      agent: "faultline:run-7",
      name: "faultline",
      kind: "verdict",
      text: "D-pay-417 caused inc-1; fixed by flag paymentGate off, verified APPLIED on a second channel.",
      created_at: NOW - 5 * 60_000,
      expires_at: NOW + 86_400_000,
      about: ["payment", "checkout"],
      hops: 0,
      similarity: null,
      replies: [
        { id: "note-2", agent: "key-ab12cd34", stance: "confirms", text: "Saw the same after the flag flip." },
        { id: "note-3", agent: "local", stance: "refutes", text: "The retry storm started earlier." },
        { id: "note-4", agent: "key-ab12cd34", stance: "confirms", text: "Error rate back in band." },
      ],
      score: 0.91,
    },
    {
      id: "note-5",
      agent: "key-ab12cd34",
      name: "",
      kind: "lead",
      text: "Check the fx_rates refresh job first.",
      created_at: NOW - 3 * 3_600_000,
      expires_at: NOW + 86_400_000,
      about: ["fx_rates"],
      hops: 1,
      similarity: null,
      replies: [],
      score: 0.4,
    },
  ],
  via: "db.idx.vector.queryNodes(Note) ∪ (focus)-[:PROPAGATES_TO*0..2]-()<-[:ABOUT]-(:Note), ranked by faultline.noteScore",
  template: "Q-NOTE-RECALL",
  cypher: "CALL { … }\nRETURN n.id AS id\nLIMIT 20",
  params: { focus: "payment", q: null, hops: 2, floor: 0.6, w: [0.5, 0.3, 0.2, 1440] },
  ms: 1.42,
  served_by: "FalkorDB 4.x · agentmem_acme · GRAPH.RO_QUERY as ro_acme",
  note: "leads left by agents; never evidence",
};

function renderCard(focus: string | null = "payment") {
  return render(
    <CypherPanelProvider>
      <AgentNotesCard focus={focus} />
    </CypherPanelProvider>,
  );
}

describe("AgentNotesCard: notes other agents left (GET /api/notes)", () => {
  it("lists the notes with kind, who, nearness, about chips and the reply tally", async () => {
    const { calls } = stubFetch({ "/api/notes?": { body: NOTES } });
    renderCard();
    const list = await screen.findByRole("list", { name: "Notes about payment or near it, best first" });
    const items = within(list).getAllByRole("listitem").filter((li) => li.parentElement === list);
    expect(items).toHaveLength(2);

    const first = within(items[0]);
    expect(first.getByText("verdict")).toBeTruthy();
    expect(first.getByText("faultline")).toBeTruthy();
    expect(first.getByText("faultline:run-7")).toBeTruthy();
    expect(first.getByText("5 min ago")).toBeTruthy();
    expect(first.getByText(/^about$/)).toBeTruthy();
    const about = first.getByRole("list", { name: "Components this note is about" });
    expect(within(about).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["payment", "checkout"]);
    const tally = first.getByRole("button", { name: /3 replies/ });
    expect(tally.textContent).toContain("2 confirm");
    expect(tally.textContent).toContain("1 refute");
    expect(tally.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(tally);
    expect(tally.getAttribute("aria-expanded")).toBe("true");
    const replies = first.getByRole("list", { name: "Replies to note note-1" });
    expect(within(replies).getAllByRole("listitem")).toHaveLength(3);
    expect(within(replies).getByText("The retry storm started earlier.")).toBeTruthy();
    expect(within(replies).getByText("refutes")).toBeTruthy();

    const second = within(items[1]);
    expect(second.getByText("lead")).toBeTruthy();
    expect(second.getByText("key-ab12cd34")).toBeTruthy(); // no self-declared name: the signed-in caller
    expect(second.getByText(/1 hop away/)).toBeTruthy();
    expect(second.getByText("No replies yet.")).toBeTruthy();

    expect(screen.getByText("2 notes")).toBeTruthy();
    expect(
      screen.getByText(/Leads that agents left for each other: Faultline's own runs and any MCP client\. Never evidence/),
    ).toBeTruthy();
    expect(calls.some((c) => c.url.includes("/api/notes?tenant=acme&focus=payment"))).toBe(true);
  });

  it("opens the Cypher panel on the template (home: the notes graph) with the params the response carried", async () => {
    const { calls } = stubFetch({
      "/api/notes?": { body: NOTES },
      "/api/templates/Q-NOTE-RECALL": {
        body: { id: "Q-NOTE-RECALL", purpose: "shared agent notes", cypher: NOTES.cypher, file: "note_recall.cypher",
                limit: 20, internal: false, home: "agentmem" },
      },
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /Q-NOTE-RECALL: open the Cypher panel/ }));
    const dialog = await screen.findByRole("dialog");
    expect((await within(dialog).findByRole("region", { name: "Cypher of Q-NOTE-RECALL" })).textContent).toBe(NOTES.cypher);
    expect((within(dialog).getByLabelText("Params (JSON, editable)") as HTMLTextAreaElement).value).toContain('"focus": "payment"');
    expect(calls.some((c) => c.url.includes("/api/templates/Q-NOTE-RECALL"))).toBe(true);
  });

  it("an empty answer is said plainly", async () => {
    stubFetch({ "/api/notes?": { body: { ...NOTES, rows: [] } } });
    renderCard();
    expect(await screen.findByText("No agent has left a note about this component or its neighbours yet.")).toBeTruthy();
    expect(screen.getByText("0 notes")).toBeTruthy();
  });

  it("FalkorDB down (503) is said loudly, with no notes shown", async () => {
    stubFetch({ "/api/notes?": { status: 503, body: { detail: "recall_notes: FalkorDB unavailable" } } });
    renderCard();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Notes unavailable: FalkorDB is down or not ready");
    expect(alert.textContent).toContain("HTTP 503");
    expect(screen.getByText("unavailable")).toBeTruthy();
    expect(screen.queryByRole("list", { name: /Notes about/ })).toBeNull();
    expect(screen.queryByText(/No agent has left a note/)).toBeNull();
  });

  it("no component to look near: no read at all", () => {
    const { calls } = stubFetch({});
    renderCard(null);
    expect(screen.getByText(/names no component/)).toBeTruthy();
    expect(calls.filter((c) => c.url.includes("/api/notes"))).toHaveLength(0);
  });
});
