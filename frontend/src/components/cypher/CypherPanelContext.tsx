"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ParamContext } from "@/lib/params";
import type { Evidence, TemplateInfo } from "@/lib/types";
import { CypherPanel } from "./CypherPanel";

/** What a gate check, evidence row, tool call or graph node asks the panel to show. */
export interface CypherRequest {
  /** Template id (Q-…); null for evidence produced by a non-graph tool. */
  template: string | null;
  /** Heading, e.g. "G5 sufficiency · D-fx-pause-7". */
  title: string;
  /** Where it was opened from, e.g. "gate run gr-… (competitor sweep)". */
  origin: string;
  /** The gate check detail / evidence summary, shown verbatim. */
  detail?: string | null;
  /** Params exactly as recorded on the check (null when the gate did not record them). */
  recordedParams?: Record<string, unknown> | null;
  /** Incident context used to pre-fill unrecorded params (labelled "derived"). */
  ctx: ParamContext;
  /** Incident whose graph the re-run targets. */
  incident?: string;
  tenant: string;
  /** Evidence item, when opened from one (digest comparison, non-graph sources). */
  evidence?: Evidence | null;
  /** What the recorded tool call reported (engine ms, rows), shown next to the query. */
  recorded?: { ms: number | null; rows: number | null; digest?: string | null } | null;
  /**
   * Replay mode: no live API. The panel shows the Cypher exported with the recording
   * and disables PROFILE / Re-run with this reason instead of calling the backend.
   */
  offline?: { reason: string; templates: Record<string, TemplateInfo> } | null;
}

interface PanelApi {
  open: (req: CypherRequest) => void;
}

const Ctx = createContext<PanelApi | null>(null);

export function CypherPanelProvider({ children }: { children: React.ReactNode }) {
  const [req, setReq] = useState<CypherRequest | null>(null);
  const [nonce, setNonce] = useState(0);
  const returnFocus = useRef<HTMLElement | null>(null);

  const open = useCallback((r: CypherRequest) => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setReq(r);
    setNonce((n) => n + 1);
  }, []);

  const value = useMemo(() => ({ open }), [open]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <CypherPanel
        key={nonce}
        request={req}
        onClose={() => setReq(null)}
        returnFocus={returnFocus}
      />
    </Ctx.Provider>
  );
}

export function useCypherPanel(): PanelApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCypherPanel must be used inside <CypherPanelProvider>");
  return v;
}
