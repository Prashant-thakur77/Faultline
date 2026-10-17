import { EngineView } from "@/components/engine/EngineView";
import { LiveOnly } from "@/components/site/LiveOnly";
import { PageIntro } from "@/components/site/PageIntro";
import { STATIC_SITE } from "@/lib/site";

const ENGINE_WHAT =
  "It reads FalkorDB's own numbers for the tenant's graphs: memory per graph (GRAPH.MEMORY USAGE), every query's wait, execution and report time from the engine's telemetry stream, and the engine's limits. They change with every query, so a recording would only show stale numbers.";

/** /engine: inside FalkorDB right now (M20 #8): memory per graph, queries per template, the live tail, the guards. */
export default function EnginePage() {
  if (STATIC_SITE) {
    return <LiveOnly feature="Inside FalkorDB" title="Inside FalkorDB is live server only" chip="Live server only" what={ENGINE_WHAT} />;
  }
  return (
    <>
      <PageIntro eyebrow="Engine" title="Inside FalkorDB" accent="right now" after=".">
        FalkorDB watching itself: how much memory each of this tenant&apos;s graphs takes, and how long every query took,
        from the engine&apos;s own telemetry, mapped back to the query templates that ran it. Template ids and timings only;
        no query text and no parameters.
      </PageIntro>
      <EngineView />
    </>
  );
}
