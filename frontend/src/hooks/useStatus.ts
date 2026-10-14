"use client";

import { useCallback, useEffect, useState } from "react";
import { api, DEFAULT_TENANT, errorText, failureStore } from "@/lib/api";
import type { StatusResponse } from "@/lib/types";

const POLL_MS = 15_000;

export interface StatusState {
  status: StatusResponse | null;
  /** Transport or HTTP error from the last poll (the backend itself is down). */
  error: string | null;
  loading: boolean;
  /** Re-poll now (e.g. after a re-arm). */
  refresh?: () => void;
}

/**
 * Polls GET /api/status. When the backend reports `status: "unavailable"` the reason is
 * pushed to the failure banner, so the whole app says so (fail loudly).
 *
 * `enabled: false` (the static replay site, which has no API) never polls and reports
 * "not loading, no status"; the top bar then says the site is a recording instead.
 */
export function useStatus(tenant = DEFAULT_TENANT, enabled = true): StatusState {
  const [state, setState] = useState<StatusState>({ status: null, error: null, loading: enabled });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let ctrl: AbortController | null = null;
    const tick = async () => {
      ctrl?.abort();
      ctrl = new AbortController();
      try {
        const s = await api.status(tenant, ctrl.signal);
        if (disposed) return;
        if (s.status === "unavailable") {
          failureStore.report({
            key: "status-unavailable",
            reason: s.reason ?? "FalkorDB unavailable",
            status: null,
          });
        } else {
          failureStore.clear("status-unavailable");
        }
        const missing = Object.entries(s.udf ?? {}).filter(([, v]) => v !== "loaded").map(([k]) => k);
        if (missing.length) {
          failureStore.report({
            key: "udf-missing",
            reason: `FalkorDB UDF library ${missing.join(", ")} is not loaded at its pinned version (GRAPH.UDF LIST): fuzzy entity resolution and hidden-coupling queries will fail. Restart the API or run make up.`,
            status: null,
          });
        } else {
          failureStore.clear("udf-missing");
        }
        setState({ status: s, error: null, loading: false });
      } catch (e) {
        if (disposed || (e instanceof DOMException && e.name === "AbortError")) return;
        setState((prev) => ({ status: prev.status, error: errorText(e), loading: false }));
      }
    };
    void tick();
    const t = setInterval(tick, POLL_MS);
    return () => {
      disposed = true;
      ctrl?.abort();
      clearInterval(t);
    };
  }, [tenant, nonce, enabled]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, refresh };
}
