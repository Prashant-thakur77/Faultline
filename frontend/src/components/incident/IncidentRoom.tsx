"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { phaseOf, useIncident } from "@/hooks/useIncident";
import { useBlast, usePlan } from "@/hooks/usePlan";
import { useTenant } from "@/lib/tenant";
import { IncidentRoomLayout } from "./IncidentRoomLayout";

/**
 * Live incident room: the API is the data source (GET /api/incidents/{id} + SSE, /plan,
 * /blast, /graph). Rendering is shared with the replay page through IncidentRoomLayout.
 */
export function IncidentRoom({ incidentId }: { incidentId: string }) {
  const tenant = useTenant();
  const { view, viewError, graph, graphError, timeline, stream, announcement, follow } = useIncident(incidentId, tenant);
  const phase = phaseOf(view);
  const planKey = view ? `${view.incident.stage}:${view.stages.length}` : "";
  const { plan, error: planError, refresh } = usePlan(incidentId, planKey, !!view && (phase !== "investigating" || !!view.report), tenant);
  const { blast, error: blastError } = useBlast(incidentId, !!view, tenant);

  if (!view) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        {viewError ? (
          <div role="alert" className="max-w-xl rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-sm text-red-100">
            <p className="font-semibold">
              {viewError.status === 404
                ? "Unknown incident"
                : viewError.status === 410
                  ? "This run was collected"
                  : "Incident could not be loaded"}
            </p>
            <p className="mt-1 break-words">{viewError.text}</p>
            {viewError.status === 404 ? (
              <p className="mt-1 text-red-200">
                Looked in tenant <span className="font-mono">{tenant}</span>: an incident lives in one tenant&apos;s graph only.
                Switch the tenant in the top bar if it belongs to another one.
              </p>
            ) : null}
            <Link href="/" className="mt-3 inline-flex items-center gap-1 text-sky-300 underline">
              <ArrowLeft aria-hidden className="size-4" /> Back to the scenario launcher
            </Link>
          </div>
        ) : (
          <p className="text-sm text-zinc-300" aria-live="polite">
            Loading incident {incidentId} from FalkorDB…
          </p>
        )}
      </div>
    );
  }

  return (
    <IncidentRoomLayout
      source={{
        mode: "live",
        view,
        viewError,
        graph,
        graphError,
        timeline,
        stream,
        announcement,
        plan,
        planError,
        blast,
        blastError,
        onRefreshPlan: refresh,
        onApproved: follow,
      }}
    />
  );
}
