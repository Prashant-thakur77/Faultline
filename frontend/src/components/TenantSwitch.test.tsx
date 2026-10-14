import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tenantStore } from "@/lib/tenant";
import type { StatusResponse } from "@/lib/types";
import { stubFetch } from "@/test/fixtures";
import { IsolationBadge, TenantSwitch } from "./TenantSwitch";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), pathname: "/brain" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  usePathname: () => nav.pathname,
}));

const status = (graph: string, acl: StatusResponse["acl"] = "ro_user") =>
  ({ status: "ok", graph, tenant: graph.replace("tenant_", ""), acl }) as unknown as StatusResponse;

const SUMMARY = { source: "evals/results/latest.json", run: "run_0010.json", generated_from_mtime: null, values: { "s7.passed": 34, "s7.failed": 0 } };

beforeEach(() => {
  nav.push.mockReset();
  nav.replace.mockReset();
  nav.pathname = "/brain";
});

describe("TenantSwitch", () => {
  it("lists the tenant graphs the API reports and switches the whole UI", async () => {
    stubFetch({
      "/api/tenants": { body: [{ tenant: "acme", graph: "tenant_acme", ready: true }, { tenant: "globex", graph: "tenant_globex", ready: true }] },
    });
    render(<TenantSwitch />);
    const select = screen.getByLabelText(/tenant/) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect([...select.options].map((o) => o.value)).toEqual(["acme", "globex"]);
    fireEvent.change(select, { target: { value: "globex" } });
    expect(tenantStore.get()).toBe("globex");
    expect(window.localStorage.getItem("faultline.tenant")).toBe("globex");
    expect(nav.replace).toHaveBeenCalledWith("/brain?tenant=globex");
  });

  it("leaves an incident page (the incident lives in one tenant's graph only)", async () => {
    nav.pathname = "/incidents/inc-1";
    stubFetch({ "/api/tenants": { body: [{ tenant: "acme", graph: "tenant_acme", ready: true }, { tenant: "globex", graph: "tenant_globex", ready: true }] } });
    render(<TenantSwitch />);
    const select = screen.getByLabelText(/tenant/) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    fireEvent.change(select, { target: { value: "globex" } });
    expect(nav.push).toHaveBeenCalledWith("/?tenant=globex");
  });

  it("stays on the current tenant and says so when the tenant list fails", async () => {
    stubFetch({ "/api/tenants": { status: 503, body: { detail: "FalkorDB unavailable" } } });
    render(<TenantSwitch />);
    await waitFor(() => expect(screen.getByText(/Tenant list unavailable: 503/)).toBeTruthy());
    expect((screen.getByLabelText(/tenant/) as HTMLSelectElement).value).toBe("acme");
  });
});

describe("IsolationBadge", () => {
  it("says isolated (icon + text) only when the status reports the selected tenant's graph", async () => {
    stubFetch({ "/evals/summary.json": { body: SUMMARY } });
    tenantStore.set("globex");
    render(<IsolationBadge status={status("tenant_globex")} />);
    const badge = screen.getByText(/graph: tenant_globex/).parentElement!;
    expect(badge.textContent).toMatch(/isolated/);
    await waitFor(() => expect(badge.textContent).toMatch(/34 passed, 0 failed/));
    expect(badge.getAttribute("title")).toMatch(/every read in this UI is bound to tenant_globex; read-only ACL user/);
  });

  it("shows a switching state, not isolated, while status still reports the other graph", () => {
    stubFetch({ "/evals/summary.json": { body: SUMMARY } });
    tenantStore.set("globex");
    render(<IsolationBadge status={status("tenant_acme")} />);
    expect(screen.getByText(/switching to tenant_globex/)).toBeTruthy();
    expect(screen.queryByText(/isolated/)).toBeNull();
  });

  it("turns into a failure when the last eval's isolation tests failed", async () => {
    stubFetch({ "/evals/summary.json": { body: { ...SUMMARY, values: { "s7.passed": 30, "s7.failed": 2 } } } });
    render(<IsolationBadge status={status("tenant_acme", "default_user")} />);
    await waitFor(() => expect(screen.getByText(/isolation test failing/)).toBeTruthy());
  });
});

describe("tenantStore", () => {
  it("prefers ?tenant= over the stored choice and rejects invalid ids", () => {
    window.localStorage.setItem("faultline.tenant", "globex");
    window.history.replaceState(null, "", "/memory?tenant=acme");
    tenantStore.reset();
    expect(tenantStore.get()).toBe("acme");
    window.history.replaceState(null, "", "/memory?tenant=Bad%20Id");
    tenantStore.reset();
    expect(tenantStore.get()).toBe("globex");
    expect(() => tenantStore.set("../acme")).toThrow(/invalid tenant/);
  });
});
