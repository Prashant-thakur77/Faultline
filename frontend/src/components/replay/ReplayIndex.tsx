"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Film } from "lucide-react";
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
    <div className="mx-auto w-full max-w-[1000px] space-y-4 px-5 py-8 sm:px-8">
      <p className="flex items-center gap-2 text-sm text-zinc-400">
        <Film aria-hidden className="size-4 text-[var(--fl-subtle)]" />
        Exported from FalkorDB (examples/&lt;run&gt;/) as static files: no API key, no backend.
      </p>
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
        <ul className="grid gap-4 sm:grid-cols-2">
          {runs.map((r) => {
            const m = outcomeMeta(r.outcome as Outcome);
            return (
              <li key={r.name}>
                <Link
                  href={`/replay/${encodeURIComponent(r.name)}`}
                  className="fl-card fl-press group flex h-full flex-col gap-3 rounded-2xl px-5 py-5 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-[var(--fl-subtle)]">{r.recorded?.scenario ?? r.name}</span>
                    <StatusChip tone={m.tone}>{m.text}</StatusChip>
                  </span>
                  <span className="text-lg font-[560] tracking-[-0.01em] text-zinc-50">
                    {r.cause ? (
                      <>
                        Cause <span className="font-mono text-[var(--fl-ember)]">{r.cause}</span>
                      </>
                    ) : (
                      r.name
                    )}
                  </span>
                  <span className="text-xs text-[var(--fl-subtle)]">
                    <span className="font-mono">{r.name}</span> · {r.incident} · {r.events} events
                    {r.recorded ? ` · ended ${r.recorded.final_stage.toLowerCase()}` : ""}
                  </span>
                  <span className="mt-auto inline-flex items-center gap-1 text-sm text-zinc-200 group-hover:text-white">
                    Watch the run <ArrowRight aria-hidden className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
