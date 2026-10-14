import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FAQ_ITEMS, Faq } from "./Faq";

describe("Faq", () => {
  it("toggles each answer independently with aria-expanded, and labels each region by its question", () => {
    render(<Faq />);
    expect(screen.getByRole("heading", { name: "Before you run it." })).toBeTruthy();
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(FAQ_ITEMS.map((x) => x.q));
    for (const b of buttons) expect(b.getAttribute("aria-expanded")).toBe("false");

    const q = screen.getByRole("button", { name: "What does it need to run?" });
    const panel = document.getElementById(q.getAttribute("aria-controls")!)!;
    expect(panel.getAttribute("role")).toBe("region");
    expect(panel.getAttribute("aria-labelledby")).toBe(q.id);
    expect(panel.className).toContain("invisible");
    expect(panel.textContent).toContain("make setup && make judge-check");

    fireEvent.click(q);
    expect(q.getAttribute("aria-expanded")).toBe("true");
    expect(panel.className).toContain("visible grid-rows-[1fr]");
    expect(screen.getByRole("region", { name: "What does it need to run?" })).toBeTruthy();

    const other = screen.getByRole("button", { name: "Is the data real?" });
    fireEvent.click(other);
    expect(other.getAttribute("aria-expanded")).toBe("true");
    expect(q.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(q);
    expect(q.getAttribute("aria-expanded")).toBe("false");
    expect(panel.className).toContain("invisible");
  });

  it("keeps the page free of numbers in its copy", () => {
    render(<Faq />);
    const text = screen.getByRole("heading", { name: "Before you run it." }).closest("section")!.textContent!;
    // `latest.json` is a file name; everything else must be digit-free
    expect(text.replace("latest.json", "")).not.toMatch(/\d/);
  });
});
