/** What the graph is made to do, as an endless strip: only FalkorDB features the templates actually call. */
const ITEMS = [
  "algo.SPpaths", "algo.maxFlow", "algo.WCC", "algo.BFS", "algo.SSpaths", "algo.betweenness", "algo.pageRank",
  "algo.HarmonicCentrality", "algo.labelPropagation", "algo.MSF", "GRAPH.COPY", "GRAPH.RO_QUERY", "vecf32 vector index",
  "CREATE FULLTEXT INDEX",
];

export function Marquee() {
  const row = (hidden: boolean) => (
    <ul className="flex shrink-0 items-center gap-10 pr-10" aria-hidden={hidden || undefined}>
      {ITEMS.map((t) => (
        <li key={t} className="flex items-center gap-10 whitespace-nowrap font-mono text-[13px] text-[var(--fl-muted)]">
          {t}<span className="size-1 rounded-full bg-white/20" aria-hidden />
        </li>
      ))}
    </ul>
  );
  return (
    <section aria-label="FalkorDB features in use" className="relative overflow-hidden border-y border-white/[0.06] py-6 [mask-image:linear-gradient(90deg,transparent,#000_12%,#000_88%,transparent)]">
      <div className="fl-marquee">{row(false)}{row(true)}</div>
    </section>
  );
}
