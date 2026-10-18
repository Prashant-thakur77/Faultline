"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { DATA_SCENARIO, requestHeroRun, requestScenarioRun } from "@/lib/heroRun";

type Step = {
  bullet: string;
  what: string;
  cta: string;
  /** "#run" steps start a run in the launcher below; the others are plain links. */
  href: string;
  run?: () => void;
};

const STEPS: Step[] = [
  {
    bullet: "Multi-hop reasoning",
    what: "A six-hop proof path from a payment cutover, through the data lineage, to the revenue KPI (algo.SPpaths).",
    cta: "Run the data incident",
    href: "#run",
    run: () => requestScenarioRun(DATA_SCENARIO),
  },
  {
    bullet: "Graph queries and algorithms as agent tools",
    what: "Shortest paths, max flow, the min-cut, BFS, centrality: one scene per FalkorDB call, from the hero incident.",
    cta: "See how FalkorDB decides",
    href: "/explainer",
  },
  {
    bullet: "Tool selection through MCP",
    what: "The agent calls its graph tools over MCP, stage by stage; your own client can call the same read-only tools.",
    cta: "Connect an MCP client",
    href: "#api",
  },
  {
    bullet: "Actions based on what the graph shows",
    what: "The min-cut picks the containment, a pull request applies it, and a second channel verifies it APPLIED.",
    cta: "Run the hero incident",
    href: "#run",
    run: requestHeroRun,
  },
  {
    bullet: "Explainable results",
    what: "Every claim opens its Cypher; “Why do you believe this?” draws the verdict back to each tool call.",
    cta: "Open a recorded run",
    href: "/replay/s1-hero",
  },
];

/**
 * A compact guide for a Track 1 judge (Agents That Act on Connected Data): each scored bullet, what it looks like
 * here, and one click to see it. Runs start in the launcher below (#run), exactly as the hero buttons do.
 */
export function JudgePath() {
  return (
    <section aria-labelledby="judge-title" className="mx-auto max-w-[1200px] px-5 pb-14 sm:px-8">
      <h2 id="judge-title" className="text-xs font-medium tracking-[0.2em] text-[var(--fl-subtle)] uppercase">
        Agents that act on connected data, in five clicks
      </h2>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map((s, i) => {
          const cls =
            "group mt-auto inline-flex items-center gap-1.5 pt-3 text-[13px] font-medium text-sky-300 outline-none focus-visible:ring-2 focus-visible:ring-sky-400";
          return (
            <li key={s.bullet} className="fl-card flex flex-col rounded-2xl px-4 py-4">
              <span className="font-mono text-[11px] text-[var(--fl-subtle)]">{String(i + 1).padStart(2, "0")}</span>
              <span className="mt-1 text-[14px] font-[560] leading-snug text-zinc-50">{s.bullet}</span>
              <span className="mt-1.5 text-[12.5px] leading-relaxed text-zinc-400">{s.what}</span>
              {s.href.startsWith("/") ? (
                <Link href={s.href} className={cls}>
                  {s.cta} <ArrowRight aria-hidden className="size-3.5 transition-transform group-hover:translate-x-0.5" />
                </Link>
              ) : (
                <a href={s.href} onClick={s.run} className={cls}>
                  {s.cta} <ArrowRight aria-hidden className="size-3.5 transition-transform group-hover:translate-x-0.5" />
                </a>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
