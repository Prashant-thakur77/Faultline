import type { Metadata } from "next";
import { PreflightView } from "@/components/preflight/PreflightView";
import { LiveOnly, PREFLIGHT_WHAT } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

export const metadata: Metadata = { title: "Preflight · Faultline" };

/**
 * Static replay site: one placeholder path so the export has something to render (a dynamic
 * route needs at least one param under output: "export"); every other PR id gets the site's
 * 404 page, which says the same thing. The live build exports no generateStaticParams
 * (undefined), so the route stays dynamic exactly as before.
 */
export const generateStaticParams = STATIC_SITE ? () => [{ pr: ["live-only"] }] : undefined;

/**
 * Target of the PR comment's "Open in Faultline" link (/preflight/<pr id>?focus=<node>). The API
 * older links; the page loads the latest recorded preflight for that PR (GET /api/preflight?pr=).
 */
export default async function PreflightPrPage({
  params,
  searchParams,
}: {
  params: Promise<{ pr: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (STATIC_SITE) return <LiveOnly feature="Preflight" what={PREFLIGHT_WHAT} />;
  const { pr } = await params;
  const sp = await searchParams;
  const focus = typeof sp.focus === "string" && sp.focus ? sp.focus : null;
  return <PreflightView prRef={pr.map(decodeURIComponent).join("/")} focus={focus} />;
}
