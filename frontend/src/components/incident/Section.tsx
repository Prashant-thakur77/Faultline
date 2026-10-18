"use client";

import { createContext, useContext, useId, useState } from "react";
import { ChevronRight } from "lucide-react";
import { ViaCompactProvider } from "@/components/cypher/ViaFalkor";
import { cn } from "@/lib/utils";

/**
 * Sections inside a <SectionFold> start folded to their header: the title, the status chip (`aside`) and the
 * "via FalkorDB" affordance (`via`) stay visible, so the summary and its Cypher are one click away; the body is
 * one expand away. Outside a SectionFold (and in unit tests) every section renders open with no toggle.
 */
const SectionFoldContext = createContext(false);

export function SectionFold({ children }: { children: React.ReactNode }) {
  return <SectionFoldContext.Provider value={true}>{children}</SectionFoldContext.Provider>;
}

/** A titled card section (keyboard-reachable heading; `${id}-h` labels the section for scripts and AT). */
export function Section({
  id,
  title,
  aside,
  via,
  children,
  className,
  level = 2,
}: {
  id: string;
  title: string;
  /** Heading level: 2 (default) for a page's cards; 3 for cards nested under a panel's own h2. */
  level?: 2 | 3;
  /** Status chips / counts, right of the title. */
  aside?: React.ReactNode;
  /** The section's "via FalkorDB" affordance (one per card). */
  via?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const foldable = useContext(SectionFoldContext);
  const [open, setOpen] = useState(!foldable);
  const bodyId = useId();
  const H = level === 3 ? "h3" : "h2";
  return (
    <section aria-labelledby={`${id}-h`} className={cn("fl-card rounded-2xl px-5", foldable ? "py-3" : "py-4", className)}>
      <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1", open && "mb-3")}>
        <H id={`${id}-h`} className="text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
          {foldable ? (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={bodyId}
              onClick={() => setOpen((o) => !o)}
              className="group -mx-1 inline-flex items-center gap-1.5 rounded-md px-1 outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <ChevronRight
                aria-hidden
                className={cn(
                  "size-4 text-[var(--fl-subtle)] transition-transform duration-150 group-hover:text-zinc-300 motion-reduce:transition-none",
                  open && "rotate-90",
                )}
              />
              {title}
            </button>
          ) : (
            title
          )}
        </H>
        {aside ? <div className="flex flex-wrap items-center gap-1.5">{aside}</div> : null}
        {via ? (
          // min-w-0 + max-w-full: on a phone the chip takes its own line and truncates inside it, never widening the card
          <div className="ml-auto flex max-w-full min-w-0 items-center *:min-w-0 *:shrink">
            {foldable ? <ViaCompactProvider>{via}</ViaCompactProvider> : via}
          </div>
        ) : null}
      </div>
      <div id={bodyId} hidden={!open}>
        {children}
      </div>
    </section>
  );
}
