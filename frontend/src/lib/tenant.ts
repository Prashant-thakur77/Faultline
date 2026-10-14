"use client";

import { useSyncExternalStore } from "react";
import { DEFAULT_TENANT } from "./api";

/**
 * The tenant the whole UI reads (one FalkorDB graph per tenant: tenant_<id>). Chosen in the top
 * bar; every page and API call uses it, so a switch re-reads everything from the other graph.
 *
 * Source of truth on the client, in order: a `?tenant=` in the URL (deep links), then the last
 * choice in this browser (localStorage), then NEXT_PUBLIC_FAULTLINE_TENANT / "acme". The server
 * render always uses the default, and React re-renders with the client value after hydration
 * (useSyncExternalStore's server snapshot), so there is no hydration mismatch.
 *
 * The value is only a selector: the API validates it (422 for an unknown tenant) and binds
 * every read to that tenant's graph; nothing here grants access to anything.
 */

export const TENANT_RE = /^[a-z0-9_]{1,32}$/;
const STORAGE_KEY = "faultline.tenant";

let current: string | null = null;
const listeners = new Set<() => void>();

function initial(): string {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("tenant");
    if (fromUrl && TENANT_RE.test(fromUrl)) return fromUrl;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && TENANT_RE.test(stored)) return stored;
  } catch {
    /* storage blocked: fall back to the default */
  }
  return DEFAULT_TENANT;
}

export const tenantStore = {
  get(): string {
    if (typeof window === "undefined") return DEFAULT_TENANT;
    if (current === null) current = initial();
    return current;
  },
  set(t: string): void {
    if (!TENANT_RE.test(t)) throw new Error(`invalid tenant id ${JSON.stringify(t)}`);
    if (t === tenantStore.get()) return;
    current = t;
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* storage blocked: the choice lasts for this page only */
    }
    for (const l of listeners) l();
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  /** Test hook: forget the cached value (re-read URL / storage on next get). */
  reset(): void {
    current = null;
  },
};

const serverSnapshot = () => DEFAULT_TENANT;

/** The selected tenant (re-renders on switch). */
export function useTenant(): string {
  return useSyncExternalStore(tenantStore.subscribe, tenantStore.get, serverSnapshot);
}

export function tenantGraph(t: string): string {
  return `tenant_${t}`;
}
