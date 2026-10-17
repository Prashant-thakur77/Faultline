"use client";

import { createContext, useContext, useId, useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Whether disclosures start folded. Pages that want a calm first view (the incident room, preflight, brain) wrap
 * their content in <FoldProvider fold>; everywhere else (and in unit tests, which render cards on their own)
 * every disclosure starts open, so nothing is hidden by default outside a page that chose to fold it.
 */
const FoldContext = createContext(false);

export function FoldProvider({ fold = true, children }: { fold?: boolean; children: React.ReactNode }) {
  return <FoldContext.Provider value={fold}>{children}</FoldContext.Provider>;
}

export function useFold(): boolean {
  return useContext(FoldContext);
}

/**
 * Summary first, details on demand. A real button (aria-expanded, aria-controls) toggles a region; `actions` sit
 * beside the toggle, outside it, so a summary can carry its own one-click "via FalkorDB" Cypher button without
 * nesting interactive elements. The folded region stays mounted (`hidden`), so its state survives a fold.
 */
export function Disclosure({
  summary,
  actions,
  defaultOpen,
  children,
  className,
  bodyClassName,
  size = "sm",
  onToggle,
}: {
  summary: React.ReactNode;
  actions?: React.ReactNode;
  /** Overrides the page default (FoldProvider). */
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  size?: "xs" | "sm";
  /** Called with the new state after each toggle (e.g. read the body's data on first open). */
  onToggle?: (open: boolean) => void;
}) {
  const fold = useFold();
  const [open, setOpen] = useState(defaultOpen ?? !fold);
  const id = useId();
  return (
    <div className={className}>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => {
            setOpen(!open);
            onToggle?.(!open);
          }}
          className={cn(
            "group -mx-1 inline-flex min-h-7 min-w-0 items-center gap-1.5 rounded-md px-1 text-left outline-none transition-colors",
            "text-zinc-300 hover:text-zinc-50 focus-visible:ring-2 focus-visible:ring-sky-400",
            size === "xs" ? "text-xs" : "text-[13px]",
          )}
        >
          <ChevronRight
            aria-hidden
            className={cn(
              "size-3.5 shrink-0 text-[var(--fl-subtle)] transition-transform duration-150 group-hover:text-zinc-300 motion-reduce:transition-none",
              open && "rotate-90",
            )}
          />
          <span className="min-w-0">{summary}</span>
        </button>
        {actions ? <span className="ml-auto inline-flex items-center gap-2">{actions}</span> : null}
      </div>
      <div id={id} hidden={!open} className={cn("mt-2", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
