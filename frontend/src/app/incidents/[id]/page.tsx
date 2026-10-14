import { IncidentRoom } from "@/components/incident/IncidentRoom";
import { INCIDENT_WHAT, LiveOnly } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

/**
 * Static replay site: one placeholder path so the export has something to render (a dynamic
 * route needs at least one param under output: "export"); every other incident id gets the
 * site's 404 page, which points at the replays. The live build exports no generateStaticParams
 * (undefined), so the route stays dynamic exactly as before.
 */
export const generateStaticParams = STATIC_SITE ? () => [{ id: "live-only" }] : undefined;

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  if (STATIC_SITE) return <LiveOnly feature="The live incident room" what={INCIDENT_WHAT} />;
  const { id } = await params;
  return <IncidentRoom incidentId={decodeURIComponent(id)} />;
}
