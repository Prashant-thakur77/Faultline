import { PageIntro } from "@/components/site/PageIntro";
import { ColdWarmCard } from "@/components/memory/ColdWarmCard";
import { MemoryView } from "@/components/memory/MemoryView";
import { LiveOnly } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

/** /memory[?incident=<id>]: the Memory tab for the tenant chosen in the top bar. */
export default async function MemoryPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (STATIC_SITE) {
    // The eval numbers are static files, so the cold/warm comparison still shows on the replay site.
    return (
      <div className="flex flex-1 flex-col">
        <LiveOnly
          feature="The Memory tab"
          what="It reads incident families (algo.labelPropagation), derived runbooks and recall (vector index + shared symptoms) from FalkorDB."
        />
        <div className="mx-auto w-full max-w-2xl px-4 pb-8">
          <ColdWarmCard />
        </div>
      </div>
    );
  }
  const sp = await searchParams;
  const incident = typeof sp.incident === "string" && /^[A-Za-z0-9_.:-]{1,160}$/.test(sp.incident) ? sp.incident : null;
  return (
    <>
      <PageIntro eyebrow="Memory" title="The next incident starts" accent="warm" after=".">
        Past incidents are grouped into families by the graph (algo.labelPropagation), fixes that worked become runbooks,
        and recall finds similar incidents by meaning. Memory can raise a prior or order the fixes; only a graph path
        proves a cause.
      </PageIntro>
      <MemoryView key={incident ?? ""} initialIncident={incident} />
    </>
  );
}
