import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { FaultlineMark } from "@/components/TopBar";
import { REPO_URL, STATIC_SITE } from "@/lib/site";
import { CodeCard } from "./CodeCard";

type Item = { label: string; href?: string; route?: string };

/** A repo file: a link when the repo URL is configured, otherwise its path as plain text (never a dead link). */
const file = (label: string, p: string): Item => ({ label, href: REPO_URL ? `${REPO_URL}/blob/main/${p}` : undefined });

const COLUMNS: { head: string; items: Item[] }[] = [
  { head: "Product", items: [
    { label: STATIC_SITE ? "Recorded incidents" : "Incidents", route: "/" },
    { label: "On-call", route: "/oncall" },
    { label: "Preflight gate", route: "/preflight" },
    { label: "Company brain", route: "/brain" },
    { label: "Memory", route: "/memory" },
    { label: "Inside FalkorDB", route: "/engine" },
    { label: "Replay", route: "/replay" },
  ] },
  { head: "Evidence", items: [
    file("Eval results", "evals/RESULTS.md"),
    file("How we measure", "docs/EVALS.md"),
    file("Design decisions", "docs/DESIGN_DECISIONS.md"),
    file("Engine compatibility", "docs/FALKORDB_COMPAT.md"),
  ] },
  { head: "FalkorDB", items: [
    { label: "algo.SPpaths · algo.maxFlow" },
    { label: "GRAPH.COPY clean rooms" },
    { label: "GRAPH.RO_QUERY for every read" },
    { label: "vecf32 + full-text indexes" },
  ] },
  { head: "Repo", items: [
    file("README", "README.md"),
    file("License (Apache-2.0)", "LICENSE"),
    file("Security", "SECURITY.md"),
  ] },
];

/** The one-row footer of the product pages: the pages and the evidence, nothing else. */
const COMPACT_LINKS: Item[] = [
  ...COLUMNS[0].items,
  ...COLUMNS[1].items.slice(0, 1),
  ...COLUMNS[3].items.slice(0, 1),
];

/** The product pages' footer links: dim until hovered or focused (--fl-subtle is AA for small text on the page). */
const quietCls = "rounded text-[var(--fl-subtle)] outline-none transition-colors duration-150 hover:text-zinc-200 focus-visible:text-zinc-200 focus-visible:ring-2 focus-visible:ring-sky-400";

const linkCls = "rounded text-[var(--fl-muted)] outline-none transition-colors duration-150 hover:text-zinc-50 focus-visible:ring-2 focus-visible:ring-sky-400";

/** The close (a centred call to action with a copyable keyless check), the site map, and a giant wordmark.
 *  `compact` (every page but home) is one quiet dark row (the mark, the pages, the evidence and the licence) over a
 *  faint echo of the home wordmark. */
const QUICKSTART =
  "curl -fsSLO https://raw.githubusercontent.com/Prashant-thakur77/Faultline/main/deploy/quickstart.yml\n" +
  "docker compose -f quickstart.yml up";
const MCP_NPX = "claude mcp add faultline -- npx -y @prashantthakur77/faultline-mcp";

export function SiteFooter({ compact = false }: { compact?: boolean }) {
  const cmd = (REPO_URL ? `git clone ${REPO_URL}.git && cd Faultline\n` : "") + "make setup && make judge-check";
  return (
    <footer aria-labelledby={compact ? undefined : "footer-title"} aria-label={compact ? "Site footer" : undefined}
            className="relative isolate overflow-hidden">
      {compact ? null : <section className="relative mx-auto max-w-[920px] px-5 py-28 text-center sm:px-8 lg:py-36">
        <div className="pointer-events-none absolute inset-x-0 top-10 -z-10 mx-auto h-64 max-w-[640px] rounded-full bg-[radial-gradient(closest-side,rgb(255_255_255/0.07),transparent)]" aria-hidden />
        <h2 id="footer-title" className="text-[clamp(2.2rem,5.4vw,4rem)] font-[510] leading-[1.04] tracking-[-0.03em]">
          <span className="fl-gradient-text">Don&apos;t trust this page.</span><br />
          <span className="fl-gradient-text">Run it.</span>
        </h2>
        <p className="mx-auto mt-5 max-w-md text-[17px] leading-relaxed text-[var(--fl-muted)]">
          One command, no API key, nothing remote: the pinned engine, the tests and every number on this site, checked. It prints PASS.
        </p>
        <div className="mx-auto mt-9 grid max-w-[560px] gap-3 text-left">
          <CodeCard title="judge-check" meta="keyless" code={cmd} lang="shell" />
          <CodeCard title="Run it all, Docker only" meta="UI on localhost:3000" code={QUICKSTART} lang="shell" />
          <CodeCard title="Give your agent the graph tools" meta="any MCP client" code={MCP_NPX} lang="shell" />
        </div>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
          <Link href="/replay" data-magnetic className="fl-press group inline-flex h-10 items-center gap-2 rounded-full bg-zinc-50 px-5 text-sm font-medium text-zinc-950 outline-none hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400">
            Watch a recorded incident <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
          {REPO_URL ? (
            <a href={REPO_URL} className="fl-press inline-flex h-10 items-center rounded-full px-5 text-sm text-zinc-200 outline-none hover:bg-white/[0.06] focus-visible:ring-2 focus-visible:ring-sky-400">Source</a>
          ) : null}
        </div>
      </section>}

      {compact ? (
        <div className="mt-12 border-t border-white/[0.04]">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-5 pt-4 pb-2 text-[12.5px] sm:px-8">
            <span className="flex items-center gap-2">
              <FaultlineMark className="size-4 opacity-70" />
              <span className="font-[590] tracking-tight text-[var(--fl-subtle)]">Faultline</span>
            </span>
            <nav aria-label="Site" className="flex flex-wrap gap-x-4 gap-y-1.5">
              {COMPACT_LINKS.map((it) =>
                it.route ? (
                  <Link key={it.label} href={it.route} className={quietCls}>{it.label}</Link>
                ) : it.href ? (
                  <a key={it.label} href={it.href} className={quietCls} rel="noreferrer" target="_blank">{it.label}</a>
                ) : null,
              )}
            </nav>
            <span className="text-xs text-[var(--fl-subtle)] sm:ml-auto">On a FalkorDB context graph · synthetic and public data · Apache-2.0</span>
          </div>
          {/* the home close's wordmark, as texture: about a third of its size, ~5 % white, decorative (SVG text, so it
              is not body text for contrast checks) */}
          <div className="mx-auto max-w-[1400px] overflow-hidden px-5 sm:px-8" aria-hidden>
            <svg viewBox="0 0 1000 200" className="block h-auto w-[min(42vw,440px)] select-none" focusable="false">
              <text x="0" y="188" textLength="1000" lengthAdjust="spacingAndGlyphs" className="font-hero" fontSize="241" fill="rgb(255 255 255 / 0.05)">
                Faultline
              </text>
            </svg>
          </div>
        </div>
      ) : (
      <div className="border-t border-white/[0.06]">
        <div className="mx-auto grid max-w-[1200px] gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_3fr]">
          <div className="flex items-start gap-2">
            <FaultlineMark className="size-6" />
            <span className="text-[15px] font-[590] tracking-tight text-zinc-100">Faultline</span>
          </div>
          <nav aria-label="Site" className="grid grid-cols-2 gap-x-6 gap-y-10 sm:grid-cols-4">
            {COLUMNS.map((c) => (
              <div key={c.head}>
                <p className="text-[13px] font-[510] text-zinc-200">{c.head}</p>
                <ul className="mt-4 space-y-2.5 text-[13px]">
                  {c.items.map((it) => (
                    <li key={it.label}>
                      {it.route ? <Link href={it.route} className={linkCls}>{it.label}</Link>
                        : it.href ? <a href={it.href} className={linkCls} rel="noreferrer" target="_blank">{it.label}</a>
                        : <span className="text-[var(--fl-muted)]">{it.label}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
      </div>

      )}

      {/* the close in white (home only): it rises over the dark page as it scrolls in */}
      {compact ? null : (
      <div className="fl-rise fl-light relative mx-2 overflow-hidden rounded-t-[28px] bg-[#f4f4f2] text-zinc-950 sm:mx-3 sm:rounded-t-[40px]">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-end justify-between gap-6 px-5 pt-12 sm:px-8 sm:pt-16">
          <p className="font-hero max-w-[16ch] text-[clamp(1.9rem,4.4vw,3.4rem)] leading-[1.02]">
            No path,<br /><span className="text-[var(--fl-subtle)]">no claim.</span>
          </p>
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-[14px] font-[510]">
            {[{ l: "Replay", r: "/replay" }, { l: "Brain", r: "/brain" }, { l: "Preflight", r: "/preflight" }, { l: "Memory", r: "/memory" }].map((x) => (
              <li key={x.r}>
                <Link href={x.r} className="group relative rounded text-zinc-900 outline-none focus-visible:ring-2 focus-visible:ring-zinc-900">
                  {x.l}
                  <span className="absolute -bottom-0.5 left-0 h-[1.5px] w-full origin-left scale-x-0 bg-zinc-900 transition-transform duration-500 ease-[cubic-bezier(0.65,0.05,0,1)] group-hover:scale-x-100" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <p className="font-hero mt-6 select-none bg-gradient-to-b from-zinc-950 to-zinc-500 bg-clip-text px-2 text-center text-[clamp(4.6rem,22vw,20rem)] leading-[0.82] text-transparent" aria-hidden>
          Faultline
        </p>
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 border-t border-black/10 px-5 py-5 text-xs text-zinc-600 sm:px-8">
          <span>An on-call agent on a FalkorDB context graph.</span>
          <span>Synthetic and public data only · Apache-2.0</span>
        </div>
      </div>
      )}
    </footer>
  );
}
