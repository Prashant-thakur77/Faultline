import type { Metadata } from "next";
import { FalkorExplainer } from "@/components/explainer/FalkorExplainer";

export const metadata: Metadata = {
  title: "How FalkorDB decides · Faultline",
  description: "A 3D explainer: one FalkorDB graph per tenant, sparse matrices, algo.BFS, algo.SPpaths, algo.maxFlow, the min-cut on a GRAPH.COPY branch, who fixes it, and read-only by design.",
};

/** /explainer: how FalkorDB works inside Faultline, in nine scenes (static: works on the replay site too). */
export default function ExplainerPage() {
  return <FalkorExplainer />;
}
