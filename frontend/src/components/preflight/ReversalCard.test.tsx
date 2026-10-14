import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { REVERSALS } from "@/test/provenanceFixture";
import { ReversalCards } from "./ReversalCard";

describe("ReversalCards (preflight reversal guard)", () => {
  it("states what was reversed, by which decision and when, the evidence for it, and that it is advisory", () => {
    render(<ReversalCards reversals={REVERSALS} />);
    const card = screen.getByRole("article", { name: "Reinstates a reversed decision" });
    const text = card.textContent?.replace(/\s+/g, " ") ?? "";
    expect(text).toContain(
      "ADR-009 (Catalog DB migrations run off-peak) was replaced by ADR-021 (Catalog DB schema changes use online migrations) on 03 Jun 2026.",
    );
    expect(text).toContain("This PR sets catalog.db.migration_window back to off_peak on product-catalog.");
    expect(within(card).getByText("advisory: does not change the verdict")).toBeTruthy();
    const because = within(card).getByRole("list", { name: "Evidence for reversing ADR-009" });
    expect(within(because).getByText("#catalog-db: off-peak migrations still lock the catalog")).toBeTruthy();
    expect(within(because).getByText("doc-chat-catalog-migrations")).toBeTruthy();
    // a repository path is shown, not linked as if it were a web page
    expect(within(card).getByText("data/gen/docs/adr-021.md")).toBeTruthy();
    expect(within(card).queryByRole("link")).toBeNull();
  });

  it("links the decision in force when its url is a web URL", () => {
    render(<ReversalCards reversals={[{ ...REVERSALS[0], head_url: "https://example.org/adr-021" }]} />);
    const link = screen.getByRole("link", { name: /ADR-021/ });
    expect(link.getAttribute("href")).toBe("https://example.org/adr-021");
  });

  it("renders nothing when the PR reinstates no reversed decision", () => {
    const { container } = render(<ReversalCards reversals={[]} />);
    expect(container.textContent).toBe("");
  });
});
