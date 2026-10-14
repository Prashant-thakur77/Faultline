"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Film } from "lucide-react";
import { BASE_PATH, type ReplayManifest } from "@/lib/replay";
import { outcomeMeta } from "@/lib/gate";
import type { Outcome } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";

/** Lists the recorded runs shipped as static files (public/replay/index.json). */
export function ReplayIndex() {
  const [runs, setRuns] = useState<ReplayManifest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${BASE_PATH}/replay/index.json`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`replay/index.json: HTTP ${r.status}`);
        setRuns((await r.json()) as ReplayManifest[]);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 p-4">
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
        <h1 className="flex items-center gap-2 text-lg font-semibold text-zinc-50">
          <Film aria-hidden className="size-5 text-sky-300" /> Recorded runs
        </h1>
        <p className="mt-1 text-sm text-zinc-300">
          These replays play runs exported from the graph (examples/&lt;run&gt;/) as static files. They need no API key and
          no backend.
        </p>
      </section>
      {error ? (
        <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
          Could not list the recorded runs: {error}
        </p>
      ) : !runs ? (
        <p className="text-sm text-zinc-300" aria-live="polite">
          Loading…
        </p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-zinc-300">No recorded runs are bundled with this build.</p>
      ) : (
        <ul className="space-y-2">
          {runs.map((r) => {
            const m = outcomeMeta(r.outcome as Outcome);
            return (
              <li key={r.name} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/replay/${encodeURIComponent(r.name)}`}
                    className="rounded font-mono text-sm font-semibold text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                  >
                    {r.name}
                  </Link>
                  <StatusChip tone={m.tone}>{m.text}</StatusChip>
                  <span className="text-xs text-zinc-400">
                    {r.incident} · cause <span className="font-mono text-zinc-200">{r.cause ?? "–"}</span> · {r.events} events
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
