"use client";

import { useId, useState } from "react";
import { CircleCheck, Hand, KeyRound, LoaderCircle } from "lucide-react";
import { ApiError, errorText } from "@/lib/api";
import { oncallApi } from "@/lib/oncall";
import { cn } from "@/lib/utils";

/**
 * Ack one page: POST /api/pages/{id}/ack with the page's signed link token when there is one (the phone link's
 * `?t=`). Without a token, or when the server refuses it (401/403), the approver key field opens; the key is sent
 * with this ack only and never stored. 409 (already acked, escalated or resolved) is said as such and the caller
 * re-reads the page. The server records (:Person)-[:ACKED {at, via}]->(:Page) and stops the escalation.
 */
export function AckControl({
  pageId,
  tenant,
  token = null,
  big = false,
  who,
  incident = null,
  onAcked,
}: {
  pageId: string;
  tenant: string;
  token?: string | null;
  big?: boolean;
  /** Who was paged, for the button's accessible name ("Ack the page to Asha Rao"). */
  who?: string;
  /** The page's incident: this tab's run token for it is sent when there is no page token. */
  incident?: string | null;
  onAcked: () => void;
}) {
  const keyId = useId();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<{ status: number | null; text: string } | null>(null);
  const [needKey, setNeedKey] = useState(false);
  const [key, setKey] = useState("");

  const ack = async (withKey: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      await oncallApi.ack(pageId, tenant, withKey ? null : token, withKey ? key.trim() || undefined : undefined, incident);
      setDone(true);
      onAcked();
    } catch (e) {
      const status = e instanceof ApiError ? e.status : null;
      if (status === 401 || status === 403) setNeedKey(true);
      if (status === 409) onAcked();
      setErr({ status, text: e instanceof ApiError ? e.detail : errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <p role="status" className={cn("flex items-center gap-1.5 font-medium text-emerald-200", big ? "text-base" : "text-xs")}>
        <CircleCheck aria-hidden className={big ? "size-5" : "size-3.5"} />
        Acked: the escalation stops here.
      </p>
    );
  }

  return (
    <div className={cn("min-w-0", big ? "space-y-3" : "space-y-1.5")}>
      {!needKey ? (
        <button
          type="button"
          onClick={() => void ack(false)}
          disabled={busy}
          aria-label={who ? `Ack the page to ${who}` : "Acknowledge this page"}
          className={cn(
            "fl-press inline-flex items-center justify-center gap-2 rounded-full font-medium outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:cursor-not-allowed disabled:opacity-60",
            big ? "h-14 w-full bg-zinc-50 text-lg text-zinc-950 hover:bg-white" : "h-8 bg-zinc-50 px-3.5 text-[13px] text-zinc-950 hover:bg-white",
          )}
        >
          {busy ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : <Hand aria-hidden className={big ? "size-5" : "size-4"} />}
          {big ? "Acknowledge" : "Ack"}
        </button>
      ) : (
        <form
          className={cn("flex flex-wrap items-end gap-2", big && "flex-col items-stretch")}
          onSubmit={(e) => {
            e.preventDefault();
            if (key.trim() && !busy) void ack(true);
          }}
        >
          <label htmlFor={keyId} className="flex min-w-0 flex-col gap-0.5 text-[11px] text-zinc-300">
            Approver key (sent with this ack only, never stored)
            <input
              id={keyId}
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              autoComplete="off"
              required
              className={cn(
                "rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
                big ? "h-11 text-base" : "h-8 w-56 max-w-full text-xs",
              )}
            />
          </label>
          <button
            type="submit"
            disabled={busy || !key.trim()}
            className={cn(
              "fl-press inline-flex items-center justify-center gap-2 rounded-full bg-zinc-50 font-medium text-zinc-950 outline-none hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60",
              big ? "h-12 text-base" : "h-8 px-3.5 text-[13px]",
            )}
          >
            {busy ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : <KeyRound aria-hidden className="size-4" />}
            Ack with the key
          </button>
        </form>
      )}
      {err ? (
        <p role="alert" className={cn("text-red-200", big ? "text-sm" : "text-[11px]")}>
          {err.status === 409 ? (
            <>
              <strong className="font-semibold">Not open any more:</strong> {err.text} (HTTP 409). Re-reading the page.
            </>
          ) : err.status === 401 || err.status === 403 ? (
            <>
              <strong className="font-semibold">Ack refused:</strong> {err.text} (HTTP {err.status}).{" "}
              {token ? "The link token was not accepted; " : "This view has no link token; "}enter the approver key.
            </>
          ) : err.status === 404 ? (
            <>
              <strong className="font-semibold">Ack failed:</strong> {err.text} (HTTP 404).
            </>
          ) : (
            <>
              <strong className="font-semibold">Ack failed:</strong> {err.text}
              {err.status ? ` (HTTP ${err.status})` : ""}
            </>
          )}
        </p>
      ) : null}
    </div>
  );
}
