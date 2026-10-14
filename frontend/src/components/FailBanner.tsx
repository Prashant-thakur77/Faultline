"use client";

import { useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MonitorPlay, OctagonAlert, X } from "lucide-react";
import { failureStore } from "@/lib/api";

/**
 * Red, assertive banner shown whenever the live system is unavailable: /api/status says
 * "unavailable", the API cannot be reached, or any call returned 503. It names the reason
 * verbatim from the backend. It never offers sample data in place of the live run.
 */
export function FailBanner() {
  const failures = useSyncExternalStore(
    failureStore.subscribe,
    failureStore.snapshot,
    failureStore.serverSnapshot,
  );
  const pathname = usePathname();
  if (!failures.length) return null;
  const onReplay = pathname?.startsWith("/replay");
  return (
    <div role="alert" aria-live="assertive" className="border-b border-red-500/60 bg-red-950/90">
      <ul className="mx-auto flex max-w-[1920px] flex-col gap-1 px-4 py-2">
        {failures.map((f) => (
          <li key={f.key} className="flex items-start gap-2 text-sm text-red-100">
            <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
            <p className="min-w-0 flex-1">
              <strong className="font-semibold">Live run unavailable:</strong>{" "}
              <span className="break-words">{f.reason}</span>
              {f.status ? <span className="text-red-300"> (HTTP {f.status})</span> : null}
              <span className="text-red-200/90"> · No substitute data is shown.</span>
            </p>
            <button
              type="button"
              onClick={() => failureStore.clear(f.key)}
              className="rounded p-0.5 text-red-200 outline-none hover:bg-red-500/20 focus-visible:ring-2 focus-visible:ring-red-300"
              aria-label={`Dismiss: ${f.reason}`}
            >
              <X aria-hidden className="size-4" />
            </button>
          </li>
        ))}
        <li className="flex items-center gap-2 pl-6 text-sm">
          {onReplay ? (
            <span className="text-red-100/90">
              This page plays a recorded run from static files; it does not need the live API.
            </span>
          ) : (
            <Link
              href="/replay/s1-hero"
              className="inline-flex items-center gap-1 rounded font-semibold text-sky-200 underline outline-none hover:text-sky-100 focus-visible:ring-2 focus-visible:ring-sky-300"
            >
              <MonitorPlay aria-hidden className="size-4" /> Watch the recorded run
            </Link>
          )}
        </li>
      </ul>
    </div>
  );
}
