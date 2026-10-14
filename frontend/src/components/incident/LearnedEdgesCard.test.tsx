import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { stubFetch } from "@/test/fixtures";
import type { IncidentView } from "@/lib/types";
import { LearnedEdgesCard } from "./LearnedEdgesCard";

const VIEW = {
  incident: { id: "inc-1" },
  report: { cause_id: null, outcome: "UNKNOWN_ESCALATED" },
} as unknown as IncidentView;
const PROPOSAL = {
  id: "edge-1",
  src: "payment",
  dst: "checkout",
  cap: 0.82,
  why: "rolling back D-1 brought checkout back in band",
  status: "proposed",
  plan_hash: "a".repeat(64),
  action: "act-1-h1",
  change: "D-1",
  approved_by: null,
};

describe("LearnedEdgesCard", () => {
  it("offers to name a suspect when escalated, and approves a proposed link by its exact plan hash", async () => {
    const { calls } = stubFetch({
      "/edge-proposals/edge-1/approve": { body: { approved: "edge-1" } },
      "/edge-proposals": { body: { incident: "inc-1", proposals: [PROPOSAL] } },
    });
    render(
      <LearnedEdgesCard
        view={VIEW}
        stage="UNKNOWN_ESCALATED"
        onChanged={() => {}}
      />,
    );
    expect(await screen.findByText("payment → checkout")).toBeTruthy();
    expect(screen.getByText("proposed: not an edge yet")).toBeTruthy();
    expect(screen.getByText(/Name the change you suspect/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Approver"), {
      target: { value: "p-030" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Approve this exact link" }),
    );
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.includes("/edge-proposals/edge-1/approve")),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(calls.find((c) => c.url.includes("/approve"))!.init!.body),
    );
    expect(body).toEqual({ plan_hash: "a".repeat(64), approver: "p-030" });
  });

  it("renders nothing for a confirmed incident with no proposals", async () => {
    stubFetch({
      "/edge-proposals": { body: { incident: "inc-1", proposals: [] } },
    });
    const confirmed = {
      incident: { id: "inc-1" },
      report: { cause_id: "D-1", outcome: "CONFIRMED" },
    } as unknown as IncidentView;
    const { container } = render(
      <LearnedEdgesCard
        view={confirmed}
        stage="AWAITING_APPROVAL"
        onChanged={() => {}}
      />,
    );
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});
