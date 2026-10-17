"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// One request per template id per page load (GET /api/templates/{id}), shared by every row that names it.
const cache = new Map<string, Promise<string | null>>();

function purposeOf(id: string): Promise<string | null> {
  let p = cache.get(id);
  if (!p) {
    p = api
      .template(id)
      .then((t) => (typeof t.purpose === "string" && t.purpose.trim() ? t.purpose.trim() : null))
      .catch(() => {
        cache.delete(id); // retried on a later render; nothing is invented meanwhile
        return null;
      });
    cache.set(id, p);
  }
  return p;
}

/** Test hook: forget the cached purposes. */
export function resetTemplatePurposes() {
  cache.clear();
}

/**
 * The catalogue's own purpose line for each template id (the row's title), read lazily for the ids on screen. Writer
 * ids (W-…) are not catalogue templates and get none. A failed read leaves the row without a title, never a guess.
 */
export function useTemplatePurposes(ids: string[]): Record<string, string | null> {
  const key = [...new Set(ids.filter((id) => id.startsWith("Q-")))].sort().join("|");
  const [got, setGot] = useState<Record<string, string | null>>({});
  useEffect(() => {
    if (!key) return;
    let alive = true;
    const want = key.split("|");
    Promise.all(want.map(async (id) => [id, await purposeOf(id)] as const)).then((pairs) => {
      if (!alive) return;
      setGot((prev) => {
        const next = { ...prev };
        for (const [id, p] of pairs) next[id] = p;
        return next;
      });
    });
    return () => {
      alive = false;
    };
  }, [key]);
  return got;
}
