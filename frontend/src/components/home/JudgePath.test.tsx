import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JudgePath } from "./JudgePath";

describe("JudgePath", () => {
  it("names the five Track 1 bullets, each with one way to see it", () => {
    render(<JudgePath />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(5);
    for (const b of ["Multi-hop reasoning", "Graph queries and algorithms as agent tools", "Tool selection through MCP",
                     "Actions based on what the graph shows", "Explainable results"]) {
      expect(screen.getByText(b)).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: /Run the data incident/ }).getAttribute("href")).toBe("#run");
    expect(screen.getByRole("link", { name: /See how FalkorDB decides/ }).getAttribute("href")).toBe("/explainer");
    expect(screen.getByRole("link", { name: /Open a recorded run/ }).getAttribute("href")).toBe("/replay/s1-hero");
  });
});
