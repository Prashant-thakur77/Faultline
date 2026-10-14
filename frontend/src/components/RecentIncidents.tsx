"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { fmtAgo } from "@/lib/format";
import { outcomeMeta } from "@/lib/gate";
import type { IncidentListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusChip } from "./StatusChip";

const POLL_MS = 10_000;

/** GET /api/incidents (newest first), read from the tenant's audit graph. */
const SCROLL = "rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-sky-400 [mask-image:linear-gradient(to_bottom,#000_calc(100%-2.5rem),transparent)]";

export function RecentIncidents() {
  const tenant = useTenant();
  const [items, setItems] = useState<IncidentListItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    const load = () =>
      api
        .incidents(tenant, ctrl.signal)
        .then((x) => {
          setItems(x);
          setErr(null);
          setNow(Date.now());
        })
        .catch((e) => {
          if (!(e instanceof DOMException && e.name === "AbortError")) setErr(errorText(e));
        });
    void load();
    const t = setInterval(load, POLL_MS);
    return () => {
      ctrl.abort();
      clearInterval(t);
    };
  }, [tick, tenant]);

  return (
    <Card className="fl-glass rounded-3xl bg-transparent lg:h-full lg:min-h-0">
      {/* the panel's scroll areas fade out at the bottom (scroll padding keeps the last row clear of the fade) */}
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Recent incidents
          <Button
            size="icon-sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => setTick((t) => t + 1)}
            aria-label="Refresh recent incidents"
          >
            <RefreshCw aria-hidden />
          </Button>
        </CardTitle>
        <CardDescription className="text-zinc-400">
          From audit_{tenant} (the tenant&apos;s audit graph), newest first{items && items.length ? ` · ${items.length} runs` : ""}.
        </CardDescription>
      </CardHeader>
      <CardContent className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col">
        {err ? (
          <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-2 text-sm text-red-200">
            Could not load incidents: {err}
          </p>
        ) : items === null ? (
          <p className="text-sm text-zinc-400">Loading incidents…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-zinc-300">
            No incidents recorded for tenant {tenant} yet. Run a scenario to create one.
          </p>
        ) : (
          <>
          {/* the list scrolls inside the card (it grows with every run), never stretching the page */}
          <ul className={"grid max-h-[60vh] gap-2 overflow-y-auto overscroll-contain pb-8 md:hidden " + SCROLL}
              aria-label="Recent incidents" tabIndex={0} data-lenis-prevent>
            {items.map((i) => {
              const m = outcomeMeta(i.outcome);
              return (
                <li key={i.run}>
                  <Link
                    href={`/incidents/${encodeURIComponent(i.incident)}?tenant=${encodeURIComponent(tenant)}`}
                    className="block rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 outline-none transition-colors hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-sm text-sky-300">{i.incident}</span>
                      <span className="shrink-0 text-xs text-zinc-400">{fmtAgo(i.started_at, now)}</span>
                    </span>
                    <span className="mt-2 flex flex-wrap items-center gap-2">
                      <StatusChip tone={m.tone} title={m.meaning}>{m.text}</StatusChip>
                      <span className="font-mono text-xs text-zinc-300">{i.scenario}</span>
                      {i.cause ? <span className="font-mono text-xs whitespace-nowrap text-zinc-200">cause {i.cause}</span> : null}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className={"hidden max-h-[min(70vh,640px)] overflow-auto overscroll-contain pb-8 md:block lg:max-h-none lg:min-h-0 lg:flex-1 " + SCROLL}
               role="region" aria-label="Recent incidents (scrolls)" tabIndex={0} data-lenis-prevent>
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Recent incidents</caption>
              <thead className="sticky top-0 z-10 bg-[#141516] text-xs text-zinc-400 shadow-[0_1px_0_rgb(255_255_255/0.06)]">
                <tr>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Incident</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Outcome</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Cause</th>
                  <th scope="col" className="hidden py-1.5 pr-3 font-medium xl:table-cell">Investigator</th>
                  <th scope="col" className="py-1.5 font-medium">Started</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => {
                  const m = outcomeMeta(i.outcome);
                  return (
                    <tr key={i.run} className="border-t border-zinc-800">
                      <td className="py-2 pr-3 whitespace-nowrap">
                        <Link
                          href={`/incidents/${encodeURIComponent(i.incident)}?tenant=${encodeURIComponent(tenant)}`}
                          className="rounded font-mono text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
                        >
                          {i.incident}
                        </Link>
                        <span className="ml-2 font-mono text-xs text-zinc-400">{i.scenario}</span>
                      </td>
                      <td className="py-2 pr-3">
                        <StatusChip tone={m.tone} title={m.meaning}>
                          {m.text}
                        </StatusChip>
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap text-zinc-200">{i.cause ?? "–"}</td>
                      <td className="hidden max-w-40 truncate py-2 pr-3 text-xs text-zinc-300 xl:table-cell" title={i.investigator}>
                        {/* the short name; the full description stays in the tooltip */}
                        {i.investigator.split(" (")[0]}
                      </td>
                      <td className="py-2 text-xs whitespace-nowrap text-zinc-300" title={new Date(i.started_at).toISOString()}>
                        {fmtAgo(i.started_at, now)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
