"use client";

import { useMemo } from "react";
import { lineDiff, toHunks } from "@/lib/diff";
import { cn } from "@/lib/utils";

/**
 * Unified diff of the exact action's file (`before` → `after` as returned by /choose).
 * Added / removed lines carry a + / − glyph and a screen-reader word, not only a colour.
 */
export function DiffView({ file, before, after }: { file: string; before: string; after: string }) {
  const hunks = useMemo(() => {
    const lines = lineDiff(before, after);
    return lines ? toHunks(lines) : null;
  }, [before, after]);

  if (hunks === null) {
    return <p className="text-xs text-amber-300">The file is too large to diff in the browser.</p>;
  }
  if (hunks.length === 0) {
    return <p className="text-xs text-amber-300">before and after are identical: this action changes nothing in {file}.</p>;
  }
  const adds = hunks.reduce((n, h) => n + h.lines.filter((l) => l.kind === "add").length, 0);
  const dels = hunks.reduce((n, h) => n + h.lines.filter((l) => l.kind === "del").length, 0);
  return (
    <figure className="overflow-hidden rounded-md border border-zinc-700">
      <figcaption className="flex items-center gap-2 border-b border-zinc-700 bg-zinc-800/70 px-2 py-1 font-mono text-[11px] text-zinc-200">
        <span>--- a/{file}</span>
        <span>+++ b/{file}</span>
        <span className="ml-auto text-zinc-400">
          <span className="text-emerald-300">+{adds}</span> <span className="text-red-300">−{dels}</span>
        </span>
      </figcaption>
      <div className="max-h-72 overflow-auto bg-zinc-950">
        <table className="w-full border-collapse font-mono text-[11.5px] leading-[1.15rem]">
          <caption className="sr-only">
            Unified diff of {file}: {adds} line{adds === 1 ? "" : "s"} added, {dels} removed
          </caption>
          {hunks.map((h, hi) => (
            <tbody key={hi}>
              <tr>
                <td colSpan={4} className="bg-sky-500/10 px-2 text-sky-300">
                  {h.header}
                </td>
              </tr>
              {h.lines.map((l, i) => (
                <tr
                  key={i}
                  className={cn(l.kind === "add" && "bg-emerald-500/15", l.kind === "del" && "bg-red-500/15")}
                >
                  <td className="w-8 pr-1 text-right text-zinc-400 select-none">{l.oldNo ?? ""}</td>
                  <td className="w-8 pr-1 text-right text-zinc-400 select-none">{l.newNo ?? ""}</td>
                  <td
                    className={cn(
                      "w-4 text-center font-bold select-none",
                      l.kind === "add" ? "text-emerald-300" : l.kind === "del" ? "text-red-300" : "text-zinc-600",
                    )}
                  >
                    <span aria-hidden>{l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "}</span>
                    <span className="sr-only">{l.kind === "add" ? "added" : l.kind === "del" ? "removed" : ""}</span>
                  </td>
                  <td
                    className={cn(
                      "pr-2 whitespace-pre",
                      l.kind === "add" ? "text-emerald-100" : l.kind === "del" ? "text-red-100" : "text-zinc-300",
                    )}
                  >
                    {l.text}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </figure>
  );
}
