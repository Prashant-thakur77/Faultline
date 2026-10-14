import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HeroGraph3D from "./HeroGraph3D";

afterEach(() => vi.unstubAllGlobals());

describe("HeroGraph3D", () => {
  it("renders nothing without WebGL (the hero stands on its own, no crash)", () => {
    // happy-dom has no WebGL context; the recorded graph is not fetched in a unit test (no abort at teardown)
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    const { container } = render(<HeroGraph3D />);
    expect(container.innerHTML).toBe("");
  });
});
