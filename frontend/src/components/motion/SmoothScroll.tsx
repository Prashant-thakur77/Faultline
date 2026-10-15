"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import Lenis from "lenis";
import "lenis/dist/lenis.css";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { pageContent } from "@/lib/scroller";
import { setSmoothScroller } from "@/lib/smooth";

/**
 * Inertial wheel scrolling on every page (Lenis, as on landonorris.com): desktop only, where the shell's <main> is the
 * scroll column. Phones keep native touch scrolling; reduced motion keeps native scrolling. Nested scrollers (panes,
 * code blocks, lists) keep their own wheel. Not on the incident room, which scrolls inside its own panes.
 * Re-created per route, since each page brings its own content element.
 */
export function SmoothScroll() {
  const reduced = useReducedMotion();
  const pathname = usePathname() ?? "/";
  useEffect(() => {
    if (reduced || pathname.startsWith("/incidents")) return;
    const main = document.getElementById("main");
    const content = pageContent();
    if (!main || !content || !/(auto|scroll)/.test(getComputedStyle(main).overflowY)) return;
    const lenis = new Lenis({
      wrapper: main,
      content,
      autoRaf: true,
      anchors: true,
      allowNestedScroll: true,
      // lerp, not a fixed-duration tween: each wheel event only moves the target and the position eases towards it
      // (frame-rate independent), so quick up-and-down flicks blend instead of restarting a curve mid-flight
      lerp: 0.1,
      smoothWheel: true,
    });
    setSmoothScroller(lenis);
    return () => {
      setSmoothScroller(null);
      lenis.destroy();
    };
  }, [reduced, pathname]);
  return null;
}
