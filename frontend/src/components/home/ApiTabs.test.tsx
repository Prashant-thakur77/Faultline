import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiTabs } from "./ApiTabs";

// reduced motion: the panel swaps without a framer animation that happy-dom would cancel at unmount
beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => vi.unstubAllGlobals());

describe("ApiTabs", () => {
  it("switches interface by click and by arrow keys, one tab selected at a time", async () => {
    render(<ApiTabs />);
    const mcp = screen.getByRole("tab", { name: "MCP" });
    expect(mcp.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").textContent).toContain("@prashantthakur77/faultline-mcp");

    fireEvent.click(screen.getByRole("tab", { name: "REST" }));
    expect(screen.getByRole("tab", { name: "REST" }).getAttribute("aria-selected")).toBe("true");
    // the panel swaps after the old content's exit animation
    await waitFor(() => expect(screen.getByRole("tabpanel").textContent).toContain("/api/context_pack?tenant=acme"));

    // each switch waits for its panel, so no exit animation is cancelled mid-flight (a stray rejection in happy-dom)
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Cypher" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByRole("tabpanel").textContent).toContain("algo.SPpaths"));
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "MCP" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByRole("tabpanel").textContent).toContain("mcpServers"));
    expect(screen.getAllByRole("tab").filter((t) => t.getAttribute("aria-selected") === "true").length).toBe(1);
  });
});
