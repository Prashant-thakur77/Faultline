import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProductTour, TOUR_ADVANCE_MS, TOUR_SHOTS } from "./ProductTour";

/** The section is always "on screen": the observer reports it intersecting as soon as it observes. */
class SeenObserver {
  constructor(private cb: IntersectionObserverCallback) {}
  observe(el: Element) { this.cb([{ isIntersecting: true, target: el } as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}

const stubMotion = (reduce: boolean) =>
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: reduce && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));

const fetchStub = vi.fn(() => Promise.reject(new Error("no network in tests")));

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", SeenObserver);
  vi.stubGlobal("fetch", fetchStub);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const selected = () => screen.getAllByRole("tab").filter((t) => t.getAttribute("aria-selected") === "true");
/** The one screenshot not hidden from assistive tech (inactive layers are aria-hidden). */
const shownImage = () => screen.getByRole("tabpanel").querySelector('[aria-hidden="false"] img') as HTMLImageElement;

describe("ProductTour", () => {
  it("switches screens by arrow keys, Home and End, one tab selected at a time, with the right image per tab", () => {
    stubMotion(true);
    render(<ProductTour />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(TOUR_SHOTS.map((s) => s.tab));
    expect(selected().map((t) => t.textContent)).toEqual(["Incident room"]);
    expect(shownImage().getAttribute("src")).toBe("/shots/incident-room-full.webp");
    expect(shownImage().getAttribute("loading")).toBe("eager");

    const list = screen.getByRole("tablist");
    const expected = ["/shots/crew.webp", "/shots/provenance.webp", "/shots/preflight-reversal.webp", "/shots/brain-graph.webp", "/shots/incident-room-full.webp"];
    for (const src of expected) {
      fireEvent.keyDown(list, { key: "ArrowRight" });
      expect(selected().length).toBe(1);
      expect(document.activeElement).toBe(selected()[0]);
      expect(shownImage().getAttribute("src")).toBe(src);
    }
    fireEvent.keyDown(list, { key: "ArrowLeft" });
    expect(selected()[0].textContent).toBe("Brain");
    fireEvent.keyDown(list, { key: "Home" });
    expect(selected()[0].textContent).toBe("Incident room");
    fireEvent.keyDown(list, { key: "End" });
    expect(selected()[0].textContent).toBe("Brain");

    // the panel is labelled by the active tab and links to the live screen
    const panel = screen.getByRole("tabpanel");
    expect(panel.getAttribute("aria-labelledby")).toBe(selected()[0].id);
    expect(screen.getByRole("link", { name: /Open it live/ }).getAttribute("href")).toBe("/brain");
    // the callout is in the text too (the overlay bubble is decorative)
    expect(panel.querySelector("figcaption")?.textContent).toContain("who decided, and are they still here");
  });

  it("selects by click, and only the active tab is in the tab order", () => {
    stubMotion(true);
    render(<ProductTour />);
    fireEvent.click(screen.getByRole("tab", { name: "Preflight" }));
    expect(selected()[0].textContent).toBe("Preflight");
    expect(shownImage().getAttribute("src")).toBe("/shots/preflight-reversal.webp");
    expect(screen.getAllByRole("tab").filter((t) => t.tabIndex === 0).map((t) => t.textContent)).toEqual(["Preflight"]);
    // other shots load lazily
    const imgs = [...screen.getByRole("tabpanel").querySelectorAll("img")];
    expect(imgs.filter((i) => i.getAttribute("loading") === "lazy").length).toBe(TOUR_SHOTS.length - 1);
  });

  it("never auto-advances under reduced motion, and shows no pause control", () => {
    vi.useFakeTimers();
    stubMotion(true);
    render(<ProductTour />);
    act(() => { vi.advanceTimersByTime(TOUR_ADVANCE_MS * 3); });
    expect(selected()[0].textContent).toBe("Incident room");
    expect(screen.queryByRole("button", { name: /the tour/ })).toBeNull();
  });

  it("auto-advances while on screen, pauses on hover, and stops once a tab is chosen", () => {
    vi.useFakeTimers();
    stubMotion(false);
    render(<ProductTour />);
    act(() => { vi.advanceTimersByTime(TOUR_ADVANCE_MS + 10); });
    expect(selected()[0].textContent).toBe("Crew");

    const region = screen.getByRole("tablist").parentElement!.parentElement!;
    fireEvent.pointerEnter(region);
    act(() => { vi.advanceTimersByTime(TOUR_ADVANCE_MS * 2); });
    expect(selected()[0].textContent).toBe("Crew");
    fireEvent.pointerLeave(region);
    act(() => { vi.advanceTimersByTime(TOUR_ADVANCE_MS + 10); });
    expect(selected()[0].textContent).toBe("Why");

    fireEvent.click(screen.getByRole("button", { name: "Pause the tour" }));
    act(() => { vi.advanceTimersByTime(TOUR_ADVANCE_MS * 2); });
    expect(selected()[0].textContent).toBe("Why");
    expect(screen.getByRole("button", { name: "Play the tour" })).toBeTruthy();
  });
});
