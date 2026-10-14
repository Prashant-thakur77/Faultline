import { Ban, Gauge, Scissors, Siren, Waves } from "lucide-react";
import { fmtValue } from "@/lib/format";
import { CUT_STYLE, EDGE_STYLE, NODE_MAX, NODE_MIN, type GraphMode } from "./GraphView";

/** Legend: every encoding in the graph view has a line/shape sample, an icon and words. */
export function GraphLegend({
  mode = "path",
  hasCut = false,
  topBetweenness = null,
  rippleText = null,
}: {
  mode?: GraphMode;
  hasCut?: boolean;
  topBetweenness?: { id: string; score: number } | null;
  /** Overrides the ripple-mode wording (preflight: changed / impacted). */
  rippleText?: { cause: [string, string]; blast: [string, string] } | null;
}) {
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-zinc-300" aria-label="Graph legend">
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5" aria-label="Edge kinds">
        {Object.entries(EDGE_STYLE).map(([k, s]) => (
          <li key={k} className="flex items-center gap-1.5">
            <svg width="30" height="8" aria-hidden>
              <line x1="0" y1="4" x2="30" y2="4" stroke={s.stroke} strokeWidth={s.width + 0.4} strokeDasharray={s.dash} />
            </svg>
            {s.text}
          </li>
        ))}
        {mode === "path" ? (
          <>
            <li className="flex items-center gap-1.5">
              <svg width="30" height="8" aria-hidden>
                <line x1="0" y1="4" x2="30" y2="4" stroke="#f87171" strokeWidth={3.4} />
              </svg>
              proof path, lit hop by hop (thick red)
            </li>
            <li className="flex items-center gap-1.5">
              <svg width="30" height="8" aria-hidden>
                <line x1="0" y1="4" x2="30" y2="4" stroke="#d4d4d8" strokeWidth={2.2} strokeDasharray="5 5" />
              </svg>
              rejected suspect&apos;s chain (dashed light grey)
            </li>
          </>
        ) : (
          <li className="flex items-center gap-1.5">
            <svg width="30" height="8" aria-hidden>
              <line x1="0" y1="4" x2="30" y2="4" stroke="#fbbf24" strokeWidth={2.6} />
            </svg>
            edge inside the blast radius (solid amber)
          </li>
        )}
        {hasCut ? (
          <li className="flex items-center gap-1.5">
            <svg width="30" height="8" aria-hidden>
              <line x1="0" y1="4" x2="30" y2="4" stroke={CUT_STYLE.stroke} strokeWidth={CUT_STYLE.width} strokeDasharray={CUT_STYLE.dash} />
            </svg>
            <Scissors aria-hidden className="size-3 text-red-300" />
            min-cut edge to contain the failure (dashed red, labelled &quot;✂ cut&quot; with its cost)
          </li>
        ) : null}
      </ul>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5" aria-label="Node markers">
        <li className="flex items-center gap-1.5">
          <span className="flex items-center gap-0.5 rounded border border-red-400 bg-red-700 px-1 text-[9px] font-bold text-white">
            <Siren aria-hidden className="size-2.5" /> {rippleText?.cause[0] ?? "CAUSE"}
          </span>
          {rippleText?.cause[1] ?? "proven cause (red)"}
        </li>
        {mode === "path" ? (
          <>
            <li className="flex items-center gap-1.5">
              <span className="rounded border border-amber-300 bg-amber-950/60 px-1.5 text-[10px] text-amber-100">step n</span>
              on the proof path (amber)
            </li>
            <li className="flex items-center gap-1.5">
              <span className="flex items-center gap-0.5 rounded border border-zinc-400 bg-zinc-700 px-1 text-[9px] font-bold text-zinc-50">
                <Ban aria-hidden className="size-2.5" /> REJECTED
              </span>
              suspect rejected by the gate
            </li>
            <li className="flex items-center gap-1.5">
              <span className="rounded bg-zinc-100 px-1 font-mono text-[10px] font-semibold text-zinc-950">cap n</span>
              outgoing hop capacity below 1 (PROPAGATES_TO cap: the share of the flow that hop can carry)
            </li>
          </>
        ) : (
          <>
            <li className="flex items-center gap-1.5">
              <span className="flex items-center gap-0.5 rounded border border-amber-300 bg-amber-300 px-1 text-[9px] font-bold text-zinc-950">
                <Waves aria-hidden className="size-2.5" /> {rippleText?.blast[0] ?? "BLAST"}
              </span>
              {rippleText?.blast[1] ?? "in the blast radius (yellow, with BFS hops from the symptom; algo.BFS, Q-BLAST-1)"}
            </li>
            <li>Dimmed: outside the blast radius.</li>
          </>
        )}
        <li className="flex items-center gap-1.5">
          <span className="flex items-center gap-0.5 rounded border border-amber-300 bg-amber-400 px-1 text-[9px] font-bold text-zinc-950">
            <Gauge aria-hidden className="size-2.5" /> SYMPTOM
          </span>
          alerting target
        </li>
        <li className="flex items-center gap-1.5">
          <svg width="40" height="16" aria-hidden>
            <rect x="0.5" y="4.5" width={NODE_MIN.w / 12} height={NODE_MIN.h / 4} rx="2" fill="none" stroke="#a1a1aa" />
            <rect x="18.5" y="1.5" width={NODE_MAX.w / 10} height={NODE_MAX.h / 4.5} rx="2" fill="none" stroke="#a1a1aa" />
          </svg>
          node size grows with betweenness (√-scaled; algo.betweenness over CALLS, Q-CHOKE-ALL; data assets and changes have none and stay small)
          {topBetweenness ? (
            <span className="text-zinc-400">
              · largest: <span className="font-mono text-zinc-200">{topBetweenness.id}</span> ({fmtValue(topBetweenness.score)})
            </span>
          ) : null}
        </li>
        <li>Shapes: rounded box = service, square dashed box = data asset, pill = change.</li>
      </ul>
    </div>
  );
}
