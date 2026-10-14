"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { getSmoothScroller } from "@/lib/smooth";

/**
 * Navigation feel: a thin progress line at the top from the click on an internal link until the new page is in
 * place, and every new page starts at the top (the shell's <main> is the scroll column and survives navigation, so
 * without this a page could open part-way down). Hash links on the same page keep their own scrolling.
 */
export function NavFlow() {
  const pathname = usePathname();
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const first = useRef(true);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin || url.pathname === location.pathname) return;
      setState("loading");
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  useEffect(() => {
    if (first.current) { first.current = false; return; }
    // the new page: start at the top, and finish the progress line
    const lenis = getSmoothScroller();
    if (lenis) lenis.scrollTo(0, { immediate: true });
    const main = document.getElementById("main");
    if (main) main.scrollTop = 0;
    window.scrollTo(0, 0);
    setState((s) => (s === "loading" ? "done" : s));
    const t = setTimeout(() => setState("idle"), 450);
    return () => clearTimeout(t);
  }, [pathname]);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-[60] h-[2px]">
      <div className={"h-full origin-left bg-white shadow-[0_0_10px_rgb(255_255_255/0.7)] transition-[transform,opacity] ease-[cubic-bezier(0.65,0.05,0,1)] " +
        (state === "loading" ? "scale-x-[0.72] opacity-100 duration-[1600ms]"
          : state === "done" ? "scale-x-100 opacity-0 duration-[450ms]" : "scale-x-0 opacity-0 duration-0")} />
    </div>
  );
}
