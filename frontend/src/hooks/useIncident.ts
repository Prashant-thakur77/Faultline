"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, DEFAULT_TENANT, errorText, incidentEventsUrl } from "@/lib/api";
import { stageWords } from "@/lib/format";
import type { GateRun, GraphResponse, IncidentView, StageRow, ToolCallRow } from "@/lib/types";

export type TimelineItem =
  | { key: string; at: number; kind: "stage"; row: StageRow }
  | { key: string; at: number; kind: "tool_call"; row: ToolCallRow }
  | { key: string; at: number; kind: "gate_run"; row: GateRun }
  | { key: string; at: number; kind: "done"; stage: string };

export type StreamState =
  | "connecting"
  | "live"
  | "following"
  | "awaiting"
  | "done"
  | "recorded"
  | "replay"
  | "idle"
  | "lost"
  | "collected";

const KIND_RANK = { stage: 0, tool_call: 1, gate_run: 2, done: 3 } as const;

export function itemKey(kind: TimelineItem["kind"], id: string, extra = "", at: number | string = ""): string {
  // Tool-call ids can repeat across gate phases, so the key also carries evidence id and time.
  return `${kind}:${id}:${extra}:${at}`;
}

export function timelineFromView(v: Pick<IncidentView, "stages" | "tool_calls" | "gate_runs">): TimelineItem[] {
  return [
    ...v.stages.map((row) => ({ key: itemKey("stage", row.id, "", row.at), at: row.at, kind: "stage" as const, row })),
    ...v.tool_calls.map((row) => ({
      key: itemKey("tool_call", row.id, row.evidence_id ?? "", row.at),
      at: row.at,
      kind: "tool_call" as const,
      row,
    })),
    ...v.gate_runs.map((row) => ({ key: itemKey("gate_run", row.id, "", row.at), at: row.at, kind: "gate_run" as const, row })),
  ];
}

export function sortTimeline(items: TimelineItem[]): TimelineItem[] {
  return [...items].sort(
    (a, b) => a.at - b.at || KIND_RANK[a.kind] - KIND_RANK[b.kind] || a.key.localeCompare(b.key),
  );
}

/** Stages after which nothing else happens on the incident. */
export const FINAL_STAGES = new Set(["RESOLVED", "UNKNOWN_ESCALATED", "FAILED", "NO_INCIDENT"]);
/** Stages of the action path that run in the background after approval. */
export const ACTION_STAGES = new Set(["EXECUTE", "VERIFY", "WRITEBACK"]);
/** Post-gate planning stages (transient: the run moves on to AWAITING_APPROVAL within ms). */
const PLANNING_STAGES = new Set(["CONTAIN", "ROUTE", "PLAN"]);

export type Phase = "investigating" | "planning" | "awaiting" | "acting" | "final";

/**
 * Where the incident is in its lifecycle. The run's outcome is written at the gate, so
 * "outcome set" alone does not mean "nothing more will happen": the action path
 * (AWAITING_APPROVAL → EXECUTE → VERIFY → WRITEBACK → RESOLVED) comes after it.
 */
export function phaseOf(v: IncidentView | null): Phase {
  if (!v) return "investigating";
  const stage = v.incident.stage;
  if (FINAL_STAGES.has(stage)) return "final";
  if (stage === "AWAITING_APPROVAL") return "awaiting";
  if (ACTION_STAGES.has(stage)) return "acting";
  const o = v.run.outcome;
  if (!o || o === "RUNNING") return "investigating";
  if (PLANNING_STAGES.has(stage)) return "planning";
  // Outcome recorded and the run stopped at GATE/CONTRADICTION: a run from before the action path,
  // or the instant between the gate and CONTAIN. Followed briefly (see MAX_IDLE_POLLS), then shown as recorded.
  return "planning";
}

const FOLLOW_MS = 1000;
const MAX_IDLE_POLLS = 8;

/**
 * Loads GET /api/incidents/{id} and, while the run is in flight, follows the SSE stream:
 * `hello` (first event; carries `retry: 5000`), stage, tool_call, gate_run, `paused` (the run
 * waits for a human at AWAITING_APPROVAL), `done` (only on a real terminal: NO_INCIDENT,
 * UNKNOWN_ESCALATED, FAILED, RESOLVED) and `idle` (the server closes a quiet stream; the hook
 * closes its EventSource so it does not reconnect in a loop, and polls the view instead). A
 * refused stream (e.g. 429: more than 3 per visitor) closes the EventSource; the hook polls. `collected` (the run's
 * graph was garbage-collected; the API answers 410 from then on) closes the stream and stops polling for good, so the
 * page says so instead of reconnecting forever. Each event also triggers a throttled re-read of the
 * full view, so hypotheses and the report appear as soon as the graph has them.
 *
 * After approval (`follow()`), the view is re-read every second and the stream re-opened,
 * so EXECUTE → VERIFY → WRITEBACK → RESOLVED show up as the backend records them.
 */
export function useIncident(incidentId: string, tenant = DEFAULT_TENANT) {
  const [view, setView] = useState<IncidentView | null>(null);
  const [viewError, setViewError] = useState<{ text: string; status: number | null } | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [streamed, setStreamed] = useState<TimelineItem[]>([]);
  const [stream, setStream] = useState<StreamState>("connecting");
  const [announcement, setAnnouncement] = useState("");
  const [followNonce, setFollowNonce] = useState(0);
  const lastStageId = useRef<string | null>(null);

  const announceNewStage = useCallback((v: IncidentView) => {
    const last = [...v.stages].sort((a, b) => a.at - b.at || a.ord - b.ord).at(-1);
    if (!last) return;
    if (lastStageId.current !== null && lastStageId.current !== last.id) {
      setAnnouncement(`Stage ${stageWords(last.stage)}${last.note ? `: ${last.note}` : ""}`);
    }
    lastStageId.current = last.id;
  }, []);

  // Initial load + SSE subscription; re-runs (with polling) when follow() is called after approval.
  useEffect(() => {
    let disposed = false;
    let es: EventSource | null = null;
    let refetchTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    const ctrl = new AbortController();
    const following = followNonce > 0;
    let gone = false;

    const load = async (): Promise<IncidentView | null> => {
      try {
        const v = await api.incident(incidentId, tenant, ctrl.signal);
        if (disposed) return null;
        setView(v);
        setViewError(null);
        announceNewStage(v);
        return v;
      } catch (e) {
        if (disposed || (e instanceof DOMException && e.name === "AbortError")) return null;
        const status = e && typeof e === "object" && "status" in e ? (e.status as number | null) : null;
        setViewError({ text: errorText(e), status });
        if (status === 410) {
          // the run's graph was collected: nothing will ever load again, so stop streaming and polling
          gone = true;
          es?.close();
          stopPolling();
          setStream("collected");
        }
        return null;
      }
    };

    const settle = (v: IncidentView | null, fallback: StreamState) => {
      const p = phaseOf(v);
      if (p === "awaiting") setStream("awaiting");
      else if (p === "final") setStream(following || fallback === "done" ? "done" : "recorded");
      else setStream(fallback);
    };

    const scheduleRefetch = () => {
      if (refetchTimer) return;
      refetchTimer = setTimeout(() => {
        refetchTimer = null;
        void load();
      }, 400);
    };

    const push = (item: TimelineItem, say?: string) => {
      setStreamed((prev) => (prev.some((p) => p.key === item.key) ? prev : [...prev, item]));
      if (say) setAnnouncement(say);
    };

    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    };

    /** Polls the view until the incident pauses for approval or finishes (or stops changing). */
    const startPolling = (every: number, failedStream: boolean) => {
      if (pollTimer) return;
      let idle = 0;
      let seen = -1;
      pollTimer = setInterval(async () => {
        const v = await load();
        if (gone) {
          stopPolling();
          return;
        }
        if (!v) return;
        const n = v.stages.length + v.tool_calls.length + v.gate_runs.length;
        idle = n === seen ? idle + 1 : 0;
        seen = n;
        const p = phaseOf(v);
        if (p === "final" || p === "awaiting") {
          stopPolling();
          es?.close();
          settle(v, "done");
        } else if (p === "planning" && idle >= MAX_IDLE_POLLS) {
          // Outcome recorded, no action path is running: show it as a recorded run.
          stopPolling();
          es?.close();
          setStream(failedStream ? "lost" : "recorded");
        }
      }, every);
    };

    const subscribe = () => {
      es = new EventSource(incidentEventsUrl(incidentId, tenant));
      es.onopen = () => !disposed && setStream(following ? "following" : "live");
      es.addEventListener("hello", () => {
        if (!disposed) setStream(following ? "following" : "live");
      });
      es.addEventListener("paused", () => {
        // The run waits for a human (e.g. back to approval after a NOT_APPLIED fix): stop streaming.
        es?.close();
        stopPolling();
        void load().then((v) => {
          if (disposed) return;
          settle(v, "done");
          setAnnouncement("Paused: waiting for a human to approve an action");
        });
      });
      es.addEventListener("idle", () => {
        es?.close();
        void load().then((v) => {
          if (disposed) return;
          const p = phaseOf(v);
          if (p === "awaiting" || p === "final") settle(v, "done");
          else {
            setStream("idle");
            startPolling(following ? FOLLOW_MS : 3000, false);
          }
        });
      });
      es.addEventListener("stage", (ev) => {
        const row = JSON.parse((ev as MessageEvent).data) as StageRow;
        push(
          { key: itemKey("stage", row.id, "", row.at), at: row.at, kind: "stage", row },
          `Stage ${stageWords(row.stage)}${row.note ? `: ${row.note}` : ""}`,
        );
        if (row.stage === "AWAITING_APPROVAL" && !following) {
          // The run pauses here until a human approves; nothing else will stream until then.
          es?.close();
          setStream("awaiting");
          void load();
          return;
        }
        scheduleRefetch();
      });
      es.addEventListener("tool_call", (ev) => {
        const row = JSON.parse((ev as MessageEvent).data) as ToolCallRow;
        push({ key: itemKey("tool_call", row.id, row.evidence_id ?? "", row.at), at: row.at, kind: "tool_call", row });
      });
      es.addEventListener("gate_run", (ev) => {
        const row = JSON.parse((ev as MessageEvent).data) as GateRun;
        push(
          { key: itemKey("gate_run", row.id, "", row.at), at: row.at, kind: "gate_run", row },
          `Gate run for ${row.cause}: ${row.passed ? "passed" : "rejected"} (${row.origin})`,
        );
        scheduleRefetch();
      });
      es.addEventListener("collected", (ev) => {
        // the run's graph was garbage-collected: say so once, never reconnect or poll again
        let reason = "this run's graph was collected; start a new run";
        try {
          reason = (JSON.parse((ev as MessageEvent).data) as { reason?: string }).reason ?? reason;
        } catch {
          /* keep the default text */
        }
        gone = true;
        es?.close();
        stopPolling();
        if (disposed) return;
        setStream("collected");
        setViewError({ text: reason, status: 410 });
        setAnnouncement(reason);
      });
      es.addEventListener("done", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data) as { stage: string };
        push({ key: itemKey("done", d.stage), at: Number.MAX_SAFE_INTEGER, kind: "done", stage: d.stage }, `Run finished at stage ${stageWords(d.stage)}`);
        es?.close();
        void load().then((v) => settle(v, "done"));
      });
      es.onerror = () => {
        if (disposed || gone) return;
        if (es?.readyState === EventSource.CLOSED) {
          // The server refused the stream (404/503) or it ended: fall back to polling the view.
          void load().then((v) => {
            if (disposed) return;
            const p = phaseOf(v);
            if (p === "awaiting" || p === "final") settle(v, "done");
            else {
              setStream("lost");
              startPolling(following ? FOLLOW_MS : 3000, true);
            }
          });
        }
      };
    };

    void (async () => {
      const v = await load();
      if (disposed || gone) return;
      if (!v) {
        setStream("lost");
        startPolling(3000, true);
        return;
      }
      const p = phaseOf(v);
      if (!following && p === "final") {
        setStream("recorded");
        return;
      }
      if (!following && p === "awaiting") {
        setStream("awaiting");
        return;
      }
      subscribe();
      // Belt and braces while the action path runs: the view is re-read every second.
      if (following || p === "acting" || p === "planning") startPolling(FOLLOW_MS, false);
    })();

    return () => {
      disposed = true;
      ctrl.abort();
      es?.close();
      if (refetchTimer) clearTimeout(refetchTimer);
      stopPolling();
    };
  }, [incidentId, tenant, followNonce, announceNewStage]);

  // Failure-flow graph of the incident's clean-room copy.
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .graph({ tenant, incident: incidentId }, ctrl.signal)
      .then((g) => {
        setGraph(g);
        setGraphError(null);
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setGraphError(errorText(e));
      });
    return () => ctrl.abort();
  }, [incidentId, tenant]);

  const timeline = useMemo(() => {
    const all = new Map<string, TimelineItem>();
    for (const it of view ? timelineFromView(view) : []) all.set(it.key, it);
    for (const it of streamed) if (!all.has(it.key)) all.set(it.key, it);
    return sortTimeline([...all.values()]);
  }, [view, streamed]);

  /** Call after a successful approval: follow the action path until it finishes. */
  const follow = useCallback(() => {
    setStream("following");
    setFollowNonce((n) => n + 1);
  }, []);

  return { view, viewError, graph, graphError, timeline, stream, announcement, follow };
}
