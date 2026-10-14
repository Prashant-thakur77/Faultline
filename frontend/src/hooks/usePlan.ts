"use client";

import { useCallback, useEffect, useState } from "react";
import { api, DEFAULT_TENANT, errorText } from "@/lib/api";
import type { BlastResponse, PlanResponse } from "@/lib/types";

/**
 * GET /api/incidents/{id}/plan: containment, routing and the action options the agent
 * recorded. Re-read whenever `refreshKey` changes (a new stage was recorded), so option
 * status, verdict and verification channels follow the action path. `enabled` is false
 * until the gate has run (before that the plan has nothing to show).
 */
export function usePlan(incidentId: string, refreshKey: string, enabled: boolean, tenant = DEFAULT_TENANT) {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    api
      .plan(incidentId, tenant, ctrl.signal)
      .then((p) => {
        setPlan(p);
        setError(null);
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setError(errorText(e));
      });
    return () => ctrl.abort();
  }, [incidentId, tenant, refreshKey, enabled, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { plan, error, refresh };
}

/** GET /api/incidents/{id}/blast: algo.BFS blast radius per symptom (ripple mode). Loaded once. */
export function useBlast(incidentId: string, enabled: boolean, tenant = DEFAULT_TENANT) {
  const [blast, setBlast] = useState<BlastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    api
      .blast(incidentId, tenant, ctrl.signal)
      .then((b) => {
        setBlast(b);
        setError(null);
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setError(errorText(e));
      });
    return () => ctrl.abort();
  }, [incidentId, tenant, enabled]);

  return { blast, error };
}
