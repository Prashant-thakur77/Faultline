"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Polled<T> {
  /** The last successful answer for the current key (kept while a later poll fails, with `error` set). */
  data: T | null;
  /** The last failure for the current key; cleared by the next success. */
  error: unknown;
  /** When `data` was read (client clock), for "as of" labels. */
  at: number | null;
  /** True until the first answer (or failure) for the current key. */
  loading: boolean;
  refresh: () => void;
}

interface State<T> {
  key: string;
  data: T | null;
  error: unknown;
  at: number | null;
  done: boolean;
}

/**
 * Reads `load` now and then every `intervalMs` while the tab is visible (a hidden tab does not poll; it reads once
 * when it becomes visible again). `intervalMs: null` reads once. A change of `key` starts over: the previous key's
 * answer is never shown for the new one. In-flight reads are aborted on unmount and on key change.
 */
export function usePolled<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  { intervalMs, enabled = true }: { intervalMs: number | null; enabled?: boolean },
): Polled<T> {
  const [state, setState] = useState<State<T>>({ key: "", data: null, error: null, at: null, done: false });
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let ctrl: AbortController | null = null;
    const tick = () => {
      ctrl?.abort();
      const c = new AbortController();
      ctrl = c;
      loadRef.current(c.signal).then(
        (data) => {
          if (!disposed && !c.signal.aborted) setState({ key, data, error: null, at: Date.now(), done: true });
        },
        (error: unknown) => {
          if (disposed || c.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) return;
          setState((prev) => (prev.key === key ? { ...prev, error, done: true } : { key, data: null, error, at: null, done: true }));
        },
      );
    };
    const visible = () => typeof document === "undefined" || document.visibilityState !== "hidden";
    tick();
    const t = intervalMs ? setInterval(() => visible() && tick(), intervalMs) : null;
    const onVis = () => {
      if (visible() && intervalMs) tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      disposed = true;
      ctrl?.abort();
      if (t) clearInterval(t);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [key, nonce, enabled, intervalMs]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  const mine = state.key === key;
  return {
    data: mine ? state.data : null,
    error: mine ? state.error : null,
    at: mine ? state.at : null,
    loading: enabled && !(mine && state.done),
    refresh,
  };
}

/** A wall clock that ticks every `ms` (countdowns); the first value is read on mount. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
