import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StatusResponse } from "@/lib/types";
import { stubFetch } from "@/test/fixtures";
import { TopBar } from "./TopBar";

const nav = vi.hoisted(() => ({ pathname: "/brain" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => nav.pathname,
}));

const status = {
  status: "ok", graph: "tenant_acme", tenant: "acme", acl: "ro_user", graph_disabled: false,
  engine: { engine: "6.0.2", digest: "sha256:107455e862a8" }, counts: { nodes: 1838, edges: 6021 },
  models: { orchestrator: "baseline", specialists: "baseline" }, llm_configured: false, templates: 170,
} as unknown as StatusResponse;

beforeEach(() => {
  nav.pathname = "/brain";
  stubFetch({ "/api/tenants": { body: [{ tenant: "acme", graph: "tenant_acme", ready: true }] } });
});

describe("TopBar", () => {
  it("lists every section and marks the current page", () => {
    render(<TopBar state={{ status, error: null, loading: false }} />);
    const sections = screen.getByRole("navigation", { name: "Sections" });
    const links = within(sections).getAllByRole("link").map((a) => a.textContent);
    expect(links).toEqual(["Incidents", "On-call", "Preflight", "Memory", "Brain", "Explore", "Break it", "Replay"]);
    expect(within(sections).getByRole("link", { name: "Brain" }).getAttribute("aria-current")).toBe("page");
  });

  it("opens the phone menu with the same sections and the live system facts", () => {
    render(<TopBar state={{ status, error: null, loading: false }} />);
    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" }).getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("navigation", { name: "Sections (menu)" });
    const menuLinks = within(menu).getAllByRole("link").map((a) => a.textContent);
    expect(menuLinks).toHaveLength(10);
    expect(menuLinks).toEqual(expect.arrayContaining(["Inside FalkorDB", "How it decides", "Explore", "Break it"]));
    expect(screen.getAllByText("FalkorDB 6.0.2 · sha256:107455e862a8").length).toBeGreaterThan(0);
  });

  it("puts Inside FalkorDB and the explainer behind More on desktop; Escape closes it and returns focus", () => {
    nav.pathname = "/engine";
    render(<TopBar state={{ status, error: null, loading: false }} />);
    const sections = screen.getByRole("navigation", { name: "Sections" });
    const more = within(sections).getByRole("button", { name: "More sections" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    const panel = document.getElementById(more.getAttribute("aria-controls")!)!;
    const links = within(panel).getAllByRole("link");
    // below xl the bar's Explore, Break it and Replay also sit here (CSS hides these copies from xl up)
    expect(links.map((a) => a.textContent)).toEqual(["Explore", "Break it", "Replay", "Inside FalkorDB", "How it decides"]);
    expect(within(panel).getByRole("link", { name: "Inside FalkorDB" }).getAttribute("href")).toBe("/engine");
    expect(within(panel).getByRole("link", { name: "Inside FalkorDB" }).getAttribute("aria-current")).toBe("page");
    expect(within(panel).getByRole("link", { name: "How it decides" }).getAttribute("href")).toBe("/explainer");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(more);
  });

  it("never fills in a status it does not have", () => {
    render(<TopBar state={{ status: null, error: "API unreachable", loading: false }} />);
    expect(screen.getAllByText("API unreachable").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getAllByText("–").length).toBeGreaterThan(0);
  });
});
