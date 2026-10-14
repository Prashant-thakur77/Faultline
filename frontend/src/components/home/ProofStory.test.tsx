import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SNIPPETS } from "@/lib/proofSnippets";
import { CodeCard } from "./CodeCard";
import { ProofStory } from "./ProofStory";

const { scrollToElement } = vi.hoisted(() => ({ scrollToElement: vi.fn() }));
vi.mock("@/lib/smooth", () => ({ scrollToElement }));

describe("CodeCard", () => {
  it("copies exactly the code it shows", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<CodeCard title="Q-GATE-1" code={SNIPPETS.path.code} />);
    expect(screen.getByText(/algo\.SPpaths/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy Q-GATE-1" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy());
    expect(writeText).toHaveBeenCalledWith(SNIPPETS.path.code);
  });
});

describe("ProofStory", () => {
  // reduced motion: the bar and figure swap instantly, with no framer animation that happy-dom would cancel at unmount
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders the six steps, each with its template's Cypher, and a bar segment per step", () => {
    render(<ProofStory />);
    const steps = screen.getByRole("heading", { name: /How it decides/ }).closest("section")!.querySelectorAll("ol > li[data-step]");
    expect(steps.length).toBe(6);
    for (const id of ["Q-STORM-WCC", "Q-GATE-1", "Q-GATE-3", "Q-CUT-1", "Q-WB-1"]) expect(screen.getAllByText(id).length).toBeGreaterThan(0);
    const bar = screen.getByRole("navigation", { name: "Proof steps" });
    expect(within(bar).getByText("One incident")).toBeTruthy();
    expect(within(bar).getAllByRole("button").length).toBe(6);
    expect(within(bar).getByRole("button", { name: "Step 01: Alert" }).getAttribute("aria-current")).toBe("step");
    expect(within(bar).getAllByRole("button").filter((b) => b.getAttribute("aria-current") === "step").length).toBe(1);
    expect(screen.getByText("Fig 2.1")).toBeTruthy();
  });

  it("jumps to a step from its bar segment and marks it active", () => {
    scrollToElement.mockClear();
    render(<ProofStory />);
    const bar = screen.getByRole("navigation", { name: "Proof steps" });
    fireEvent.click(within(bar).getByRole("button", { name: "Step 04: Proof" }));
    expect(scrollToElement).toHaveBeenCalledTimes(1);
    const [el, opts] = scrollToElement.mock.calls[0];
    expect((el as HTMLElement).dataset.step).toBe("3");
    expect(opts).toEqual({ block: "center", smooth: false });
    expect(within(bar).getByRole("button", { name: "Step 04: Proof" }).getAttribute("aria-current")).toBe("step");
    expect(within(bar).getByRole("button", { name: "Step 01: Alert" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByText("Fig 2.4")).toBeTruthy();
    expect(screen.getByText("the path is the proof", { selector: "figcaption span" })).toBeTruthy();
  });
});
