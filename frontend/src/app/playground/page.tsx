import { PlaygroundView } from "@/components/playground/PlaygroundView";
import { LiveOnly } from "@/components/site/LiveOnly";
import { PageIntro } from "@/components/site/PageIntro";
import { STATIC_SITE } from "@/lib/site";

const PLAYGROUND_WHAT =
  "Break the graph: change one edge, capacity or person on a GRAPH.COPY of the hero incident and see which decisions move.";

/** /playground: one change to a copy of the graph, the product run twice, every decision compared (M15 #2). */
export default function PlaygroundPage() {
  if (STATIC_SITE)
    return <LiveOnly feature="Break the graph" what={PLAYGROUND_WHAT} />;
  return (
    <>
      <PageIntro eyebrow="Break it" title="Break the graph," accent="watch the verdict move" after=".">
        Change one thing in a copy of the graph and see which decisions follow.
      </PageIntro>
      <PlaygroundView />
    </>
  );
}
