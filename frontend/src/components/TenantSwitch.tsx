"use client";

import { useEffect, useId, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Building2, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { tenantGraph, tenantStore, useTenant } from "@/lib/tenant";
import type { StatusResponse } from "@/lib/types";
import { evalValue, useEvalSummary } from "@/hooks/useEvalSummary";
import { StatusChip } from "./StatusChip";

type TenantList = { state: "loading" } | { state: "ok"; tenants: { tenant: string; ready: boolean }[] } | { state: "error"; error: string };

/**
 * Top-bar tenant switch. The list comes from GET /api/tenants (the tenant_*
 * graphs FalkorDB actually holds), never a fixed list. Switching re-reads every view from the
 * other tenant's graph; pages that show one tenant's object (an incident, a PR) go back to their
 * list, because that object does not exist in the other graph.
 */
export function TenantSwitch() {
  const tenant = useTenant();
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const id = useId();
  const [list, setList] = useState<TenantList>({ state: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .tenants(ctrl.signal)
      .then((tenants) => setList({ state: "ok", tenants }))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setList({ state: "error", error: errorText(e) });
      });
    return () => ctrl.abort();
  }, []);

  const options = list.state === "ok" ? list.tenants : [];
  const known = options.some((t) => t.tenant === tenant);

  const pick = (t: string) => {
    tenantStore.set(t);
    const qs = `?tenant=${encodeURIComponent(t)}`;
    if (pathname.startsWith("/incidents/")) router.push(`/${qs}`);
    else if (pathname.startsWith("/preflight/")) router.push(`/preflight${qs}`);
    else router.replace(`${pathname}${qs}`); // keeps a shared URL honest about which tenant it shows
  };

  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor={id} className="flex items-center gap-1 text-zinc-400">
        <Building2 aria-hidden className="size-3.5" /> tenant
      </label>
      <select
        id={id}
        value={tenant}
        onChange={(e) => pick(e.target.value)}
        disabled={list.state !== "ok"}
        aria-describedby={list.state === "error" ? `${id}-err` : undefined}
        className="h-7 rounded-md border border-zinc-700 bg-zinc-900 px-1.5 font-mono text-xs text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-80"
      >
        {!known ? <option value={tenant}>{tenant}</option> : null}
        {options.map((t) => (
          <option key={t.tenant} value={t.tenant}>
            {t.tenant}
            {t.ready ? "" : " (not ready)"}
          </option>
        ))}
      </select>
      {list.state === "error" ? (
        <span id={`${id}-err`} className="sr-only">
          Tenant list unavailable: {list.error}
        </span>
      ) : null}
    </div>
  );
}

/**
 * "graph: tenant_globex · isolated". Isolation is structural: one graph per tenant, every API read
 * is bound to the selected tenant's graph (the RO wrapper refuses another tenant's graph), plus the
 * read-only ACL user when configured. The badge only says "isolated" when /api/status reports the
 * graph of the selected tenant; the last eval's S7 cross-tenant test counts are in its tooltip.
 */
export function IsolationBadge({ status }: { status: StatusResponse | null }) {
  const tenant = useTenant();
  const evals = useEvalSummary();
  const want = tenantGraph(tenant);
  const passed = evalValue(evals, "s7.passed");
  const failed = evalValue(evals, "s7.failed");
  const run = evals.state === "ok" ? evals.summary.run : null;
  const s7 =
    passed !== null && failed !== null
      ? `S7 cross-tenant isolation tests in the last eval (${run ?? "run unknown"}): ${passed} passed, ${failed} failed.`
      : evals.state === "error"
        ? `S7 eval results unavailable (${evals.error}).`
        : "";
  if (!status) return <span className="font-mono text-zinc-100">graph: {want}</span>;
  if (status.graph !== want) {
    return (
      <StatusChip tone="running" title={`status still reports ${status.graph}`}>
        graph: switching to {want}…
      </StatusChip>
    );
  }
  const acl = status.acl === "ro_user" ? "read-only ACL user per tenant" : "RO_QUERY only (no ACL user configured)";
  const s7Failed = typeof failed === "number" && failed > 0;
  return (
    <StatusChip
      tone={s7Failed ? "fail" : "pass"}
      icon={s7Failed ? ShieldAlert : ShieldCheck}
      title={`One FalkorDB graph per tenant: every read in this UI is bound to ${want}; ${acl}. ${s7}`.trim()}
    >
      <span className="font-mono">graph: {want}</span> · {s7Failed ? "isolation test failing" : "isolated"}
      <span className="sr-only">. {s7}</span>
    </StatusChip>
  );
}
