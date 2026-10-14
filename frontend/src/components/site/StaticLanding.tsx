import { Hero } from "@/components/home/Hero";
import { ApiTabs } from "@/components/home/ApiTabs";
import { Features } from "@/components/home/Features";
import { Marquee } from "@/components/home/Marquee";
import { ProofStory } from "@/components/home/ProofStory";
import { SiteFooter } from "@/components/home/SiteFooter";
import { SystemMap } from "@/components/home/SystemMap";
import { ProductTour } from "@/components/home/ProductTour";
import { Faq } from "@/components/home/Faq";
import { SectionRule } from "@/components/home/SectionRule";
import { readFile } from "node:fs/promises";
import path from "node:path";
import Link from "next/link";
import { Film, Info, Play } from "lucide-react";
import { StatusChip } from "@/components/StatusChip";
import { outcomeMeta } from "@/lib/gate";
import { REPLAY_RUNS, type ReplayManifest } from "@/lib/replay";
import { REPO_URL } from "@/lib/site";
import type { Outcome } from "@/lib/types";

/**
 * Landing page of the static replay site (GitHub Pages). Server component: the run list is read
 * from public/replay/index.json at build time, so it is in the HTML and needs no request. A
 * missing or inconsistent index fails the build (fail loudly) rather than shipping an empty site.
 */
async function loadIndex(): Promise<ReplayManifest[]> {
  const file = path.join(process.cwd(), "public", "replay", "index.json");
  const runs = JSON.parse(await readFile(file, "utf8")) as ReplayManifest[];
  const names = new Set(runs.map((r) => r.name));
  const missing = REPLAY_RUNS.filter((r) => !names.has(r));
  if (missing.length) {
    throw new Error(`public/replay/index.json lacks ${missing.join(", ")}: run npm run replay:export first`);
  }
  return runs.filter((r) => (REPLAY_RUNS as readonly string[]).includes(r.name));
}

export async function StaticLanding() {
  const runs = await loadIndex();
  return (
    // one block child of the scrolling <main>: as separate flex items, the overflow-hidden hero would shrink to 0
    <div className="w-full">
      <Hero />
      <Marquee />
      <Features />
      <SectionRule />
      <SystemMap />
      <SectionRule />
      <ProofStory />
      <SectionRule />
      <ProductTour />
      <SectionRule />
      <ApiTabs />
    <div className="mx-auto w-full max-w-3xl space-y-4 p-4 pb-16">
      <section
        aria-labelledby="about-replay"
        className="space-y-2 rounded-xl border border-sky-500/40 bg-sky-950/30 p-5"
      >
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip tone="info" icon={Film}>
            Recorded replay · no backend
          </StatusChip>
        </div>
        <h2 id="about-replay" className="text-base font-semibold text-zinc-50">
          This is a recorded, backend-free replay
        </h2>
        <p className="text-sm text-zinc-300">
          Each run below was recorded from a real Faultline run and exported from its graph (stage events, tool calls,
          gate runs, hypotheses, the plan and the report). This site is static files only: it calls no API and no
          database, needs no API key, and computes nothing. The player steps through the recorded events in their
          recorded order.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-300">
          <li>
            Every gate check and evidence item opens its Cypher panel with the exact recorded query and params. PROFILE
            and Re-run need a live FalkorDB, so they are switched off here and say so.
          </li>
          <li>
            Incidents, Preflight, Brain and Explore query the live graph; on this site they explain that instead of
            showing anything.
          </li>
        </ul>
      </section>

      <section aria-labelledby="runs-title" className="space-y-2">
        <h2 id="runs-title" className="flex items-center gap-2 text-base font-semibold text-zinc-50">
          <Play aria-hidden className="size-4 text-sky-300" /> Recorded runs
        </h2>
        <ul className="space-y-2">
          {runs.map((r) => {
            const m = outcomeMeta(r.outcome as Outcome);
            const rec = r.recorded;
            return (
              <li key={r.name} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/replay/${encodeURIComponent(r.name)}`}
                    className="rounded font-mono text-sm font-semibold text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                  >
                    replay/{r.name}
                  </Link>
                  <StatusChip tone={m.tone}>{m.text}</StatusChip>
                </div>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                  {rec ? (
                    <>
                      <dt className="text-zinc-400">scenario</dt>
                      <dd className="font-mono text-zinc-200">
                        {rec.scenario}, run to {rec.final_stage}
                      </dd>
                    </>
                  ) : null}
                  <dt className="text-zinc-400">incident</dt>
                  <dd className="font-mono text-zinc-200">{r.incident}</dd>
                  <dt className="text-zinc-400">cause</dt>
                  <dd className="font-mono text-zinc-200">{r.cause ?? "–"}</dd>
                  <dt className="text-zinc-400">events</dt>
                  <dd className="font-mono text-zinc-200">{r.events}</dd>
                  {rec ? (
                    <>
                      <dt className="text-zinc-400">recorded with</dt>
                      <dd className="text-zinc-200">
                        {rec.investigator}; {rec.github} GitHub
                      </dd>
                    </>
                  ) : null}
                </dl>
              </li>
            );
          })}
        </ul>
        <p>
          <Link
            href="/replay"
            className="rounded text-sm text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            All recorded runs
          </Link>
        </p>
      </section>

      <section aria-labelledby="live-title" className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5">
        <h2 id="live-title" className="flex items-center gap-2 text-base font-semibold text-zinc-50">
          <Info aria-hidden className="size-4 text-zinc-300" /> Run it live
        </h2>
        <p className="mt-1 text-sm text-zinc-300">
          The live demo runs the agent against FalkorDB:{" "}
          <code className="font-mono text-zinc-200">make up &amp;&amp; make seed &amp;&amp; make demo</code>
          {REPO_URL ? (
            <>
              {" "}(source:{" "}
              <a href={REPO_URL} className="text-sky-300 underline" rel="noreferrer">
                {REPO_URL.replace(/^https?:\/\//, "")}
              </a>
              )
            </>
          ) : null}
          .
        </p>
      </section>
    </div>
      <SectionRule />
      <Faq />
      <SiteFooter />
    </div>
  );
}
