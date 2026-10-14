"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { motion } from "framer-motion";
import { useAppStatus } from "@/components/AppShell";
import { introStore } from "@/lib/intro";
import { BASE_PATH, STATIC_SITE } from "@/lib/site";

const KEY = "fl-intro";
const WIPE = [0.35, 0, 0, 1] as const;

/**
 * Skip the intro? The head script in layout.tsx decides before first paint (repeat visit in this tab, reduced
 * motion, or the document loaded on another page): it sets window.__flIntroSkip, and <html data-fl-seen> for the
 * CSS that hides the server-rendered overlay until hydration. Read as an external store so hydration renders the
 * server's markup first, then drops the overlay.
 */
const never = () => () => {};
const skipped = () => (window as unknown as { __flIntroSkip?: boolean }).__flIntroSkip === true;

/**
 * First visit in a session: an odometer rolls to the real size of the graph behind the page, then the
 * overlay wipes up. Live: node count of the tenant graph from /api/status. Static site: the node count
 * of the recorded hero graph. No number (status error, missing file) means no roll: the intro just ends.
 */
export function IntroLoader() {
  const onDone = introStore.done;
  const { status, error } = useAppStatus();
  const skip = useSyncExternalStore(never, skipped, () => false);
  const [staticCount, setStaticCount] = useState<number | null>(null);
  const [phase, setPhase] = useState<"count" | "wipe" | "gone">("count");

  useEffect(() => {
    if (skip) onDone();
  }, [skip, onDone]);
  useEffect(() => {
    // the overlay covers the page: nothing behind it should take focus or scroll meanwhile
    if (skip || phase !== "count") return;
    document.documentElement.style.overflow = "hidden";
    return () => { document.documentElement.style.overflow = ""; };
  }, [skip, phase]);

  useEffect(() => {
    if (skip || !STATIC_SITE) return;
    let live = true;
    fetch(`${BASE_PATH}/replay/s1-hero/graph.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then((g: { nodes?: unknown[] } | null) => live && setStaticCount(g?.nodes?.length ?? 0))
      .catch(() => live && setStaticCount(0));
    return () => { live = false; };
  }, [skip]);

  const count = STATIC_SITE ? staticCount : status?.counts?.nodes ?? (error ? 0 : null);
  const label = STATIC_SITE ? "nodes · recorded hero graph" : status ? `nodes · ${status.graph} · FalkorDB ${status.engine?.engine ?? ""}` : "";

  // mount the digits at 0, then roll them on the next frame (a fresh digit would otherwise appear in place)
  const [rolled, setRolled] = useState(false);
  useEffect(() => {
    if (!count) return;
    const f = requestAnimationFrame(() => requestAnimationFrame(() => setRolled(true)));
    return () => cancelAnimationFrame(f);
  }, [count]);

  useEffect(() => {
    if (skip || phase !== "count") return;
    // wait for the number (up to 1.6 s), let it roll, then wipe
    const t = setTimeout(() => setPhase("wipe"), count === null ? 1600 : count === 0 ? 200 : 1500);
    return () => clearTimeout(t);
  }, [skip, phase, count]);

  useEffect(() => {
    if (phase !== "wipe") return;
    try { sessionStorage.setItem(KEY, "1"); } catch { /* private mode: replay next time, harmless */ }
    (window as unknown as { __flIntroSkip?: boolean }).__flIntroSkip = true;   // back to home later in this document: no replay
    onDone();
    const t = setTimeout(() => setPhase("gone"), 900);
    return () => clearTimeout(t);
  }, [phase, onDone]);

  if (skip || phase === "gone") return null;
  const digits = count ? String(count).split("") : ["0", "0", "0"];
  return (
    <motion.div
      className="fl-loader fixed inset-0 z-[100] flex flex-col justify-end bg-[var(--fl-bg)] px-6 pb-10 sm:px-10 sm:pb-14"
      initial={false}
      animate={{ clipPath: phase === "wipe" ? "inset(0 0 100% 0)" : "inset(0 0 0% 0)" }}
      transition={{ duration: 0.85, ease: WIPE }}
      role="status"
      aria-label="Loading Faultline"
    >
      <div className="flex items-end justify-between gap-6">
        <p className="font-hero text-[clamp(4.5rem,18vw,13rem)] leading-[0.85] text-zinc-50 tabular-nums" aria-hidden>
          {digits.map((d, i) => (
            <span key={i} className="fl-odo">
              <span style={{ transform: `translateY(-${rolled ? Number(d) : 0}em)`, transitionDelay: `${i * 90}ms` }}>
                {Array.from({ length: 10 }, (_, k) => <span key={k}>{k}</span>)}
              </span>
            </span>
          ))}
        </p>
        <p className="mb-3 hidden max-w-[16rem] text-right font-mono text-[11px] uppercase tracking-[0.25em] text-zinc-400 sm:block">
          No path,<br />no claim.
        </p>
      </div>
      <p className="mt-4 h-4 font-mono text-[11px] uppercase tracking-[0.25em] text-zinc-400">{count ? label : ""}</p>
      <div className="mt-4 h-px w-full bg-white/10">
        <motion.div className="h-px origin-left bg-[linear-gradient(90deg,var(--fl-ember),var(--fl-iris),var(--fl-proof))]" initial={{ scaleX: 0 }}
                    animate={{ scaleX: count === null ? 0.35 : 1 }} transition={{ duration: count === null ? 1.2 : 1.1, ease: WIPE }} />
      </div>
    </motion.div>
  );
}
