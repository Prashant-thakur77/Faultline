"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Database, Film, Menu, ShieldAlert, ShieldCheck, Unplug, X } from "lucide-react";
import { fmtInt, shortDigest } from "@/lib/format";
import { STATIC_SITE } from "@/lib/site";
import type { StatusState } from "@/hooks/useStatus";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { DemoControls } from "./DemoControls";
import { StatusChip } from "./StatusChip";
import { IsolationBadge, TenantSwitch } from "./TenantSwitch";

const NAV: { href: string; label: string; match: (p: string) => boolean; live?: boolean }[] = [
  { href: "/", label: "Incidents", match: (p) => p === "/" || p.startsWith("/incidents") },
  { href: "/preflight", label: "Preflight", match: (p) => p.startsWith("/preflight") },
  { href: "/memory", label: "Memory", match: (p) => p.startsWith("/memory") },
  { href: "/brain", label: "Brain", match: (p) => p.startsWith("/brain") },
  { href: "/explore", label: "Explore", match: (p) => p.startsWith("/explore") },
  { href: "/playground", label: "Break it", match: (p) => p.startsWith("/playground"), live: true },
  { href: "/replay", label: "Replay", match: (p) => p.startsWith("/replay") },
];

/** The Faultline mark: a fault line cutting through a node (the claim is only made along a path). */
/**
 * The mark: a block split by a fault, the right plate slipped, the crack in ember. Plates take the current text colour,
 * so it reads on the dark page and the light footer alike; no ids, so it can render any number of times.
 */
export function FaultlineMark({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="currentColor" aria-hidden>
      <path d="M10 4H18.1L11.1 28H10A6 6 0 0 1 4 22V10A6 6 0 0 1 10 4Z" />
      <path d="M20.9 4H22A6 6 0 0 1 28 10V22A6 6 0 0 1 22 28H13.9Z" transform="translate(1 1.4)" />
      <path d="M19.5 4L12.5 28" transform="translate(0.5 0.7)" stroke="var(--fl-ember)" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Top bar: brand, sections, tenant and a single status pill whose panel carries the live system
 * facts (engine tag + digest, graph size, ACL mode, isolation, demo controls), all from
 * GET /api/status; unknown values render as "–", never as a guess. On phones the sections and the
 * status move into a menu sheet. The static replay site says it is a recording with no backend.
 */
export function TopBar({ state }: { state: StatusState }) {
  const pathname = usePathname() ?? "/";
  // the menu remembers the page it was opened on, so any navigation closes it (no state change in an effect)
  const [openedAt, setOpenedAt] = useState<string | null>(null);
  const menu = openedAt === pathname;
  const setMenu = (open: boolean) => setOpenedAt(open ? pathname : null);
  const reduced = useReducedMotion();
  const s = state.status;
  const ok = s?.status === "ok" && !state.error;
  const nav = NAV.filter((n) => !(STATIC_SITE && n.live));

  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenedAt(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  const statusPill = STATIC_SITE ? (
    <StatusChip tone="info" icon={Film}>Static replay site</StatusChip>
  ) : state.loading && !s ? (
    <StatusChip tone="running">checking FalkorDB…</StatusChip>
  ) : ok ? (
    <StatusChip tone="pass" icon={Database}>FalkorDB ready</StatusChip>
  ) : (
    <StatusChip tone="fail" icon={Database}>{state.error ? "API unreachable" : "FalkorDB unavailable"}</StatusChip>
  );

  // the phone dot says the same as the pill: "checking" until the first status answer, never "not ready" before it
  const dotLabel = STATIC_SITE ? "static replay site" : ok ? "FalkorDB ready"
    : state.loading && !s ? "checking FalkorDB" : state.error ? "API unreachable" : "FalkorDB unavailable";

  return (
    // while the phone menu is open the bar is solid: a backdrop-filter would make it the containing block of the
    // fixed menu sheet and clip the sheet to the bar's height
    <header className={"sticky top-0 z-40 border-b border-white/[0.06] " + (menu ? "bg-[var(--fl-bg)]" : "bg-[color-mix(in_srgb,var(--fl-bg)_72%,transparent)] backdrop-blur-xl")}>
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="group flex shrink-0 items-center gap-2 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
          <FaultlineMark className="size-7 transition-transform duration-500 group-hover:rotate-[8deg]" />
          <span className="text-[15px] font-[590] tracking-[-0.01em] text-zinc-50">Faultline</span>
        </Link>

        <nav aria-label="Sections" className="ml-6 hidden items-center gap-1 text-[14px] lg:flex">
          {nav.map((n) => (
            <NavLink key={n.href} href={n.href} active={n.match(pathname)}>
              {STATIC_SITE && n.href === "/" ? "Home" : n.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {STATIC_SITE ? null : (
            <div className="hidden items-center md:flex">
              <TenantSwitch />
            </div>
          )}
          <div className="hidden sm:block" aria-live="polite">
            {STATIC_SITE ? statusPill : <StatusPanel state={state} pill={statusPill} />}
          </div>
          <span className="sm:hidden" aria-live="polite">
            <span className={"block size-2.5 rounded-full " + (STATIC_SITE ? "bg-sky-400" : ok ? "bg-emerald-400 shadow-[0_0_12px] shadow-emerald-400/70" : state.loading ? "bg-zinc-500" : "bg-red-500")}
                  title={dotLabel} />
            <span className="sr-only">{dotLabel}</span>
          </span>
          <button
            type="button"
            onClick={() => setMenu(!menu)}
            aria-expanded={menu}
            aria-controls="fl-menu"
            className="inline-flex size-9 items-center justify-center rounded-full border border-white/10 text-zinc-200 outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-sky-400 lg:hidden"
          >
            {menu ? <X className="size-4" aria-hidden /> : <Menu className="size-4" aria-hidden />}
            <span className="sr-only">{menu ? "Close menu" : "Open menu"}</span>
          </button>
        </div>
      </div>

      <AnimatePresence>
        {menu ? (
          <motion.div
            id="fl-menu"
            key="menu"
            initial={reduced ? false : { clipPath: "inset(0 0 100% 0)" }}
            animate={{ clipPath: "inset(0 0 0% 0)" }}
            exit={reduced ? { opacity: 0 } : { clipPath: "inset(0 0 100% 0)" }}
            transition={{ duration: reduced ? 0 : 0.6, ease: [0.65, 0.05, 0, 1] }}
            className="fixed inset-x-0 bottom-0 top-14 overflow-y-auto border-t border-white/[0.06] bg-[var(--fl-bg)] px-5 pb-8 pt-6 lg:hidden"
          >
            <nav aria-label="Sections (menu)" className="grid gap-1">
              {nav.map((n, i) => (
                <motion.div key={n.href} initial={reduced ? false : { opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: reduced ? 0 : 0.12 + 0.045 * i, duration: reduced ? 0 : 0.6, ease: [0.65, 0.05, 0, 1] }}>
                  <Link
                    href={n.href}
                    aria-current={n.match(pathname) ? "page" : undefined}
                    className={"fl-press flex items-center justify-between rounded-xl px-1 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 " +
                      (n.match(pathname) ? "text-zinc-50" : "text-[var(--fl-muted)] hover:text-zinc-100")}
                  >
                    <span className="text-[34px] font-[600] uppercase leading-[1.05] tracking-[-0.03em]">
                      {STATIC_SITE && n.href === "/" ? "Home" : n.label}
                    </span>
                    {n.match(pathname) ? <span className="h-[3px] w-10 rounded-full bg-[linear-gradient(90deg,var(--fl-ember),var(--fl-iris))]" aria-hidden /> : null}
                  </Link>
                </motion.div>
              ))}
            </nav>
            {STATIC_SITE ? (
              <p className="mt-4 text-sm text-zinc-400">Recorded runs only · no API, no FalkorDB behind this site</p>
            ) : (
              <div className="mt-8 grid gap-3 rounded-2xl border border-white/[0.08] bg-[var(--fl-surface)] p-4">
                <div className="flex items-center justify-between gap-2">{statusPill}<TenantSwitch /></div>
                <SystemFacts state={state} />
                <div className="flex flex-wrap gap-2"><DemoControls state={state} /></div>
              </div>
            )}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </header>
  );
}

/** The status pill and its panel of system facts (desktop). */
function StatusPanel({ state, pill }: { state: StatusState; pill: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={id}
        className="flex items-center gap-1 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        {pill}
        <ChevronDown aria-hidden className={"size-3.5 text-zinc-400 transition-transform " + (open ? "rotate-180" : "")} />
        <span className="sr-only">system details</span>
      </button>
      {open ? (
        // opaque, not glass: inside the bar's own backdrop-filter a blur here would only see the bar, not the page
        <div id={id} className="absolute right-0 top-[calc(100%+10px)] z-50 w-[340px] rounded-2xl border border-white/10 bg-[oklch(0.17_0.006_285)] p-4 shadow-[0_24px_48px_-12px_oklch(0_0_0/0.7)]">
          <SystemFacts state={state} />
          <div className="mt-3 flex flex-wrap gap-2 border-t border-white/[0.06] pt-3"><DemoControls state={state} /></div>
        </div>
      ) : null}
    </div>
  );
}

/** Engine, digest, graph, size, ACL and the A4 switch, from GET /api/status ("–" when unknown). */
function SystemFacts({ state }: { state: StatusState }) {
  const s = state.status;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-xs" aria-label="Live system status">
      <dt className="text-zinc-400">graph</dt>
      <dd className="min-w-0"><IsolationBadge status={s} /></dd>
      <dt className="text-zinc-400">engine</dt>
      <dd className="truncate font-mono text-zinc-100" title={s?.engine.digest}>
        {s ? `FalkorDB ${s.engine.engine} · ${shortDigest(s.engine.digest)}` : "–"}
      </dd>
      <dt className="text-zinc-400">size</dt>
      <dd className="font-mono text-zinc-100">
        {s?.counts ? `${fmtInt(s.counts.nodes)} nodes · ${fmtInt(s.counts.edges)} edges` : "–"}
      </dd>
      <dt className="text-zinc-400">ACL</dt>
      <dd>
        {s ? (
          s.acl === "ro_user" ? (
            <StatusChip tone="pass" icon={ShieldCheck}>read-only user</StatusChip>
          ) : (
            <StatusChip tone="warn" icon={ShieldAlert} title="RO_QUERY still enforced; ACL user not configured">
              default user (no ACL)
            </StatusChip>
          )
        ) : "–"}
      </dd>
      {s?.graph_disabled ? (
        <>
          <dt className="text-zinc-400">ablation</dt>
          <dd><StatusChip tone="fail" icon={Unplug}>graph disabled (A4 ablation)</StatusChip></dd>
        </>
      ) : null}
    </dl>
  );
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={
        "relative rounded-md px-3 py-1.5 outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-sky-400 " +
        (active ? "text-zinc-50" : "text-[var(--fl-muted)] hover:text-zinc-100")
      }
    >
      {active ? (
        <motion.span layoutId="fl-nav-dot" className="absolute -bottom-[9px] left-1/2 h-[2px] w-5 -translate-x-1/2 rounded-full bg-[linear-gradient(90deg,var(--fl-ember),var(--fl-iris))]"
                     transition={{ type: "spring", stiffness: 380, damping: 32 }} aria-hidden />
      ) : null}
      <span className="relative">{children}</span>
    </Link>
  );
}
