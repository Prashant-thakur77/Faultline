import type { Metadata } from "next";
import { ExploreView } from "@/components/explore/ExploreView";
import { LiveOnly } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

export const metadata: Metadata = { title: "Explore · Faultline" };

/** /explore[?tenant=<id>&focus=<node>]: the tenant's failure-flow graph in FalkorDB's @falkordb/canvas. */
export default async function ExplorePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  // Static replay site: searchParams are request-time data, and the canvas reads the live graph.
  if (STATIC_SITE) {
    return <LiveOnly feature="Explore" what="It draws the tenant's live failure-flow graph straight from FalkorDB." />;
  }
  const sp = await searchParams;
  // null: no tenant in the URL, so the view follows the tenant chosen in the top bar
  const tenant = typeof sp.tenant === "string" && /^[a-z0-9_]{1,32}$/.test(sp.tenant) ? sp.tenant : null;
  const focus = typeof sp.focus === "string" && sp.focus ? sp.focus : null;
  return <ExploreView key={`${tenant ?? ""}|${focus ?? ""}`} tenant={tenant} focus={focus} />;
}
