"use client";

import Link from "next/link";
import { MonitorPlay, Wallet } from "lucide-react";
import type { StatusResponse } from "@/lib/types";

/**
 * §9.1.9 / §11.3: when this hour's live-LLM budget is spent (/api/status llm_budget.replay_only), say
 * so plainly. Live LLM runs are refused by the server until the hour rolls over; baseline runs (no LLM)
 * and the recorded replays still work. Never shown when the backend does not report a budget.
 */
export function BudgetBanner({ status }: { status: StatusResponse | null }) {
  const b = status?.llm_budget;
  if (!b?.replay_only) return null;
  return (
    <div role="status" className="border-b border-amber-500/60 bg-amber-950/80">
      <p className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-2 px-4 py-2 text-sm text-amber-50">
        <Wallet aria-hidden className="size-4 shrink-0 text-amber-300" />
        <strong className="font-semibold">Live LLM runs unavailable: this hour&apos;s LLM budget is spent</strong>
        <span className="text-amber-100">
          (${b.usd_last_hour.toFixed(2)} of ${b.usd_per_hour_limit.toFixed(2)} per hour). The Baseline investigator needs no LLM;
          or watch the recorded run instead.
        </span>
        <Link
          href="/replay/s1-hero"
          className="inline-flex items-center gap-1 rounded font-semibold text-sky-200 underline outline-none hover:text-sky-100 focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          <MonitorPlay aria-hidden className="size-4" /> Watch the recorded run
        </Link>
      </p>
    </div>
  );
}
