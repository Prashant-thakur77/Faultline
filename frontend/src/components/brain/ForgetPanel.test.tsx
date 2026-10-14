import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ForgetFlip } from "@/lib/types";
import { FlipView } from "./ForgetPanel";

const FLIP: ForgetFlip = {
  question: "What did we decide about the cache TTL?",
  before: {
    answer: "Decided in [ADR-7], citing [doc-a] and [doc-b].",
    citations: ["ADR-7", "doc-a", "doc-b"],
    intent: "decision",
  },
  after: { answer: "Decided in [ADR-7], citing [doc-b].", citations: ["ADR-7", "doc-b"], intent: "decision" },
  no_longer_cited: ["doc-a"],
  answer_changed: true,
};

describe("FlipView (forget: the same question before and after)", () => {
  it("shows both answers side by side and strikes the ids the answer no longer cites", () => {
    render(<FlipView flip={FLIP} />);
    const section = screen.getByRole("region", { name: "The same question, before and after" });
    expect(section.textContent).toContain("“What did we decide about the cache TTL?”");
    expect(within(section).queryByText(/the answer did not change/)).toBeNull();
    expect(within(section).getByText("Decided in [ADR-7], citing [doc-a] and [doc-b].")).toBeTruthy();
    expect(within(section).getByText("Decided in [ADR-7], citing [doc-b].")).toBeTruthy();

    // "before" lists doc-a struck through (not colour only: line-through), "after" no longer lists it
    const column = (k: string) => within(section).getByText(k).parentElement!;
    const before = within(column("before")).getByText("doc-a");
    expect(before.className).toContain("line-through");
    expect(within(column("before")).getByText("ADR-7").className).not.toContain("line-through");
    expect(within(column("after")).queryByText("doc-a")).toBeNull();
    expect(within(column("after")).getByText("doc-b").className).not.toContain("line-through");
    expect(within(section).getByText(/No longer cited:/).textContent).toBe("No longer cited: doc-a");
  });

  it("says so when the answer did not change", () => {
    render(<FlipView flip={{ ...FLIP, after: FLIP.before, no_longer_cited: [], answer_changed: false }} />);
    expect(screen.getByText("(the answer did not change)")).toBeTruthy();
    expect(screen.queryByText(/No longer cited:/)).toBeNull();
  });

  it("fails loudly when the before/after question could not be asked", () => {
    render(<FlipView flip={{ question: "q", error: "brain unavailable" }} />);
    expect(screen.getByRole("alert").textContent).toBe("Before/after question unavailable: brain unavailable");
    expect(screen.queryByRole("region")).toBeNull();
  });
});
