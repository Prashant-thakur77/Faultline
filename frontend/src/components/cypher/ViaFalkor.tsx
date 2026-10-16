"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { Database } from "lucide-react";
import { api } from "@/lib/api";
import { STATIC_SITE } from "@/lib/site";
import { algosOf, templateIds } from "@/lib/templateAlgo";
import type { TemplateInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Where template Cypher comes from when the live API is not there: the replay player provides the templates it
 * exported with the recording. Live pages leave it null and read GET /api/templates/{id}.
 */
const OfflineTemplates = createContext<Record<string, TemplateInfo> | null>(null);

export function OfflineTemplatesProvider({
  templates,
  children,
}: {
  templates: Record<string, TemplateInfo> | null;
  children: React.ReactNode;
}) {
  return <OfflineTemplates.Provider value={templates}>{children}</OfflineTemplates.Provider>;
}

/** Inside a folded summary row the affordance drops its "via FalkorDB" words (the icon and the algo stay). */
const ViaCompact = createContext(false);

export function ViaCompactProvider({ children }: { children: React.ReactNode }) {
  return <ViaCompact.Provider value={true}>{children}</ViaCompact.Provider>;
}

// One request per template id per page load, shared by every affordance that names it.
const cache = new Map<string, Promise<string[]>>();

function algosFor(id: string): Promise<string[]> {
  let p = cache.get(id);
  if (!p) {
    p = api
      .template(id)
      .then((t) => algosOf(t.cypher))
      .catch(() => {
        cache.delete(id); // a failed read is retried next time; nothing is invented meanwhile
        return [];
      });
    cache.set(id, p);
  }
  return p;
}

/**
 * The FalkorDB procedures behind a template (or a "+"-joined set), read from the template's own Cypher: the
 * recording's exported text in replay, the API's template text live. Empty while loading, on failure, or for a
 * template that calls no procedure (plain Cypher).
 */
export function useTemplateAlgos(template: string | null | undefined): string[] {
  const offline = useContext(OfflineTemplates);
  const ids = templateIds(template);
  const key = ids.join("+");
  const fromOffline = offline
    ? [...new Set(ids.flatMap((id) => algosOf(offline[id]?.cypher)))]
    : null;
  const [live, setLive] = useState<{ key: string; algos: string[] }>({ key: "", algos: [] });
  useEffect(() => {
    if (offline || STATIC_SITE || !key) return;
    let alive = true;
    Promise.all(key.split("+").map(algosFor)).then((lists) => {
      if (alive) setLive({ key, algos: [...new Set(lists.flat())] });
    });
    return () => {
      alive = false;
    };
  }, [key, offline]);
  return fromOffline ?? (live.key === key ? live.algos : []);
}

/**
 * The one provenance affordance: "via FalkorDB · algo.BFS · Q-BLAST-1". Quiet (muted 12 px, no fill); it opens
 * the Cypher panel for the query that produced what it sits next to. The accessible name keeps the template-first
 * form every script and test relies on ("Q-BLAST-1: open the Cypher panel for …").
 */
export function ViaFalkor({
  template,
  onOpen,
  label,
  className,
  compact: compactProp = false,
}: {
  template: string | null | undefined;
  onOpen: () => void;
  /** What the query produced, for the accessible name ("the blast radius"). */
  label: string;
  className?: string;
  /** Drop the "via FalkorDB" words (rows that already sit under a labelled header). */
  compact?: boolean;
}) {
  const compact = useContext(ViaCompact) || compactProp;
  const algos = useTemplateAlgos(template);
  const ids = templateIds(template);
  const idText = ids.length > 1 ? `${ids[0]} +${ids.length - 1}` : ids[0] ?? "no template";
  const algoText = algos.length ? algos.join(" + ") : null;
  // The accessible name starts with exactly the visible text (WCAG 2.5.3, label in name), then says what it does:
  // "via FalkorDB · algo.BFS · Q-BLAST-1: open the Cypher panel for the blast radius".
  const visible = [compact ? null : "via FalkorDB", algoText, idText].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${visible}: open the Cypher panel for ${label}`}
      title={ids.length > 1 ? ids.join(" + ") : undefined}
      className={cn(
        "group inline-flex min-h-6 max-w-full shrink-0 items-center gap-1.5 rounded-md px-1 text-[11px] whitespace-nowrap text-zinc-400 outline-none transition-colors",
        "hover:bg-white/[0.04] hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400",
        className,
      )}
    >
      <Database aria-hidden className="size-3 shrink-0 text-zinc-500 transition-colors group-hover:text-[var(--fl-iris)]" />
      {/* whitespace between the parts: not rendered in the flex row, but it keeps words apart in the accessible name */}
      {compact ? null : <span>via FalkorDB</span>}{" "}
      {algoText ? (
        <>
          {compact ? null : <span className="text-[var(--fl-subtle)]">·</span>}{" "}
          <span className="truncate font-mono text-zinc-300 group-hover:text-zinc-50">{algoText}</span>{" "}
        </>
      ) : null}
      {!compact || algoText ? <span className="text-[var(--fl-subtle)]">·</span> : null}{" "}
      <span className="font-mono">{idText}</span>
    </button>
  );
}

/** Row-level query id (timeline rows, gate checks, crew calls): neutral, never a coloured badge. */
export const QUERY_ID_CLS =
  "inline-flex min-h-6 shrink-0 items-center rounded px-1 font-mono text-[11px] whitespace-nowrap text-zinc-400 outline-none transition-colors hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400";
