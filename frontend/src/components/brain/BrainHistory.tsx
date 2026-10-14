"use client";

import { useEffect, useState } from "react";
import { History, LoaderCircle, RefreshCcw } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { fmtTime } from "@/lib/format";
import type { BrainHistoryTurn } from "@/lib/types";
import { Button } from "@/components/ui/button";

/**
 * "History": this visitor's past brain turns, read back from the graph (GET /api/brain/history,
 * template Q-SESS-1: (:Session {user})-[:HAS_TURN]->(:Turn)). The user id is an anonymous
 * per-tab id kept in sessionStorage; nothing here is stored in the browser beyond that id.
 * Re-read whenever `refreshKey` changes (a new answer was recorded).
 */
export function BrainHistory({
  user,
  refreshKey,
  onAsk,
  busy,
}: {
  user: string | null;
  refreshKey: string;
  onAsk: (q: string) => void;
  busy: boolean;
}) {
  const tenant = useTenant();
  const [turns, setTurns] = useState<BrainHistoryTurn[] | null>(null);
  const [err, setErr] = useState<{ status: number | null; text: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!user) return;
    const ctrl = new AbortController();
    // Loading flag flips inside the async chain (not synchronously in the effect body).
    Promise.resolve()
      .then(() => setLoading(true))
      .then(() => api.brainHistory(user, tenant, ctrl.signal))
      .then((h) => {
        setTurns(h.turns);
        setErr(null);
      })
      .catch((e) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setErr({ status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e) });
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [user, refreshKey, nonce, tenant]);

  // Oldest first within the newest sessions (the template returns newest first).
  const shown = (turns ?? []).slice(0, 12).reverse();

  return (
    <section aria-labelledby="brain-history-h" className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="flex items-center gap-2">
        <h2 id="brain-history-h" className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
          <History aria-hidden className="size-4 text-sky-300" /> History
        </h2>
        <Button
          size="xs"
          variant="outline"
          className="ml-auto"
          onClick={() => setNonce((n) => n + 1)}
          disabled={!user || loading}
          aria-label="Refresh history"
        >
          {loading ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <RefreshCcw aria-hidden />}
          Refresh
        </Button>
      </div>
      <p className="text-xs text-zinc-400">
        Your past questions in this tab, read back from the graph (Q-SESS-1). Anonymous id{" "}
        <span className="font-mono text-zinc-300">{user ?? "unavailable (browser storage blocked)"}</span>.
      </p>
      <div aria-live="polite">
        {err ? (
          <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100">
            History unavailable: {err.text}
            {err.status ? ` (HTTP ${err.status})` : ""}
          </p>
        ) : turns === null ? (
          <p className="text-xs text-zinc-300">{user ? "Loading history…" : "No history without a session id."}</p>
        ) : shown.length === 0 ? (
          <p className="text-xs text-zinc-300">No questions recorded for this tab yet.</p>
        ) : (
          <ol className="space-y-1.5" aria-label="Recorded turns, oldest first">
            {shown.map((t) => {
              const isUser = /^(user|human|question)$/i.test(t.role);
              return (
                <li key={`${t.session}:${t.seq}:${t.role}`} className="text-xs">
                  <span className="mr-1 font-semibold text-zinc-400">{isUser ? "You" : "Brain"}</span>{" "}
                  {t.at ? <span className="mr-1 text-[11px] text-zinc-400">{fmtTime(t.at)}</span> : null}{" "}
                  {isUser ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onAsk(t.text)}
                      className="inline-flex min-h-6 items-center rounded text-left text-sky-200 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
                    >
                      {t.text}
                      <span className="sr-only"> (ask again)</span>
                    </button>
                  ) : (
                    <span className="line-clamp-2 text-zinc-300">{t.text}</span>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
