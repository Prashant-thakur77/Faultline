import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SystemMap } from "./SystemMap";

// reduced motion and a desktop viewport: no packets, the map's own parts are the controls
beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => vi.unstubAllGlobals());

const PARTS = ["Alerts", "Deploys", "Warehouse", "Docs & decisions", "FalkorDB context graph", "Faultline crew",
  "One approved action", "Who fixes it", "Preflight on PRs"];

describe("SystemMap", () => {
  it("makes every part a focusable, labelled control described by the caption", () => {
    const { container } = render(<SystemMap />);
    expect(screen.getByRole("heading", { name: /Where it sits/ })).toBeTruthy();
    for (const name of PARTS) {
      const part = screen.getByRole("button", { name: new RegExp(`^${name.replace(/[&]/g, "\\$&")}:`) });
      expect(part.getAttribute("tabindex")).toBe("0");
      const caption = container.querySelector(`#${CSS.escape(part.getAttribute("aria-describedby")!)}`);
      expect(caption).toBeTruthy();
    }
    expect(screen.getByText("Hover a part")).toBeTruthy();
    expect(screen.getByText("illustrative")).toBeTruthy();
    // no packets under reduced motion
    expect(container.querySelector("animateMotion")).toBeNull();
  });

  it("changes the caption when a part takes focus and restores it on blur", () => {
    render(<SystemMap />);
    const graph = screen.getByRole("button", { name: /^FalkorDB context graph:/ });
    const caption = () => document.getElementById(graph.getAttribute("aria-describedby")!)!.textContent;
    expect(caption()).toMatch(/^The loop\./);

    fireEvent.focus(graph);
    expect(caption()).toMatch(/^FalkorDB context graph\..*one FalkorDB graph per tenant/i);

    const alerts = screen.getByRole("button", { name: /^Alerts:/ });
    fireEvent.blur(graph);
    fireEvent.focus(alerts);
    expect(caption()).toMatch(/^Alerts\..*algo\.WCC/);

    fireEvent.blur(alerts);
    expect(caption()).toMatch(/^The loop\./);
  });

  it("pins a part with Enter so the caption stays after focus leaves", () => {
    render(<SystemMap />);
    const crew = screen.getByRole("button", { name: /^Faultline crew:/ });
    fireEvent.focus(crew);
    fireEvent.keyDown(crew, { key: "Enter" });
    expect(crew.getAttribute("aria-pressed")).toBe("true");
    fireEvent.blur(crew);
    expect(document.getElementById(crew.getAttribute("aria-describedby")!)!.textContent).toMatch(/^Faultline crew\./);
  });
});
