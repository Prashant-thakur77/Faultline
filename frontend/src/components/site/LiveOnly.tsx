import Link from "next/link";
import { Film, Unplug } from "lucide-react";
import { StatusChip } from "@/components/StatusChip";
import { REPLAY_RUNS } from "@/lib/replay";
import { REPO_URL } from "@/lib/site";

export const PREFLIGHT_WHAT =
  "The pre-deploy gate scores a pull request against the live dependency graph and its recorded incidents.";

export const INCIDENT_WHAT =
  "The live incident room streams a run's stages from the API and reads its plan, graph and evidence from FalkorDB.";

/**
 * Shown on the static replay site (GitHub Pages) in place of a page that needs the live API and
 * FalkorDB. It says so plainly and points at the recorded runs; it never renders sample data.
 */
export function LiveOnly({
  feature,
  what,
  title,
  chip = "Needs the live backend",
}: {
  feature: string;
  what: string;
  /** Overrides the heading ("<feature> needs the live backend"). */
  title?: string;
  chip?: string;
}) {
  return (
    <div className="flex flex-1 items-start justify-center p-4 sm:p-8">
      <section
        aria-labelledby="live-only-title"
        className="w-full max-w-2xl space-y-3 rounded-xl border border-amber-500/40 bg-zinc-900/70 p-5"
      >
        <StatusChip tone="warn" icon={Unplug}>
          {chip}
        </StatusChip>
        <h1 id="live-only-title" className="text-lg font-semibold text-zinc-50">
          {title ?? `${feature} needs the live backend`}
        </h1>
        <p className="text-sm text-zinc-300">
          {what} This is the static replay site: it has no Faultline API and no FalkorDB behind it, so this page has
          nothing truthful to show here and shows nothing in its place.
        </p>
        <p className="text-sm text-zinc-300">
          The recorded runs below play the full incident (gate, proof path, containment, approval, verification and
          write-back) from files exported from the graph.
        </p>
        <ul className="flex flex-wrap gap-2 pt-1">
          {REPLAY_RUNS.map((r) => (
            <li key={r}>
              <Link
                href={`/replay/${r}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 font-mono text-sm text-sky-200 underline outline-none hover:bg-sky-500/20 focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                <Film aria-hidden className="size-4" /> replay/{r}
              </Link>
            </li>
          ))}
          <li>
            <Link
              href="/"
              className="inline-flex items-center rounded-md px-2.5 py-1 text-sm text-zinc-300 underline outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              About this site
            </Link>
          </li>
        </ul>
        <p className="text-xs text-zinc-400">
          To use it live, run the stack locally (<code className="font-mono text-zinc-200">make up &amp;&amp; make seed &amp;&amp; make demo</code>)
          {REPO_URL ? (
            <>
              {" "}from{" "}
              <a href={REPO_URL} className="text-sky-300 underline" rel="noreferrer">
                the repository
              </a>
            </>
          ) : null}
          .
        </p>
      </section>
    </div>
  );
}
