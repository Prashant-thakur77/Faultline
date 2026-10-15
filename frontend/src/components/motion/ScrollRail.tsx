"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { pageContent, pageScroller } from "@/lib/scroller";

/**
 * The page's scrollbar, redrawn (the native one is hidden in globals.css): a slim monochrome thumb sized to the
 * visible share of the page, as on landonorris.com, that fades in while the page moves or the pointer is near and
 * fades out at rest, as overlay scrollbars do. Drag the thumb or click the track to scroll. Hidden when the page
 * does not scroll. Blends by difference, so it stays visible over the white close of the home page. Decorative for assistive tech: keyboard and wheel scrolling are unchanged.
 */
export function ScrollRail() {
  const pathname = usePathname();
  const thumb = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const grab = useRef<number | null>(null);   // pointer offset inside the thumb while dragging
  const [scrollable, setScrollable] = useState(false);
  const [awake, setAwake] = useState(false);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    let raf = 0;
    let sleep: ReturnType<typeof setTimeout> | undefined;
    let last = -1;
    const update = () => {
      raf = 0;
      const el = pageScroller();
      const t = track.current?.clientHeight ?? 0;
      const max = el.scrollHeight - el.clientHeight;
      setScrollable(max > 40);
      const h = Math.max(36, (el.clientHeight / el.scrollHeight) * t);
      const y = max > 0 ? (el.scrollTop / max) * (t - h) : 0;
      if (thumb.current) {
        const hp = `${Math.round(h)}px`;
        if (thumb.current.style.height !== hp) thumb.current.style.height = hp;   // a height write invalidates layout: only on change
        thumb.current.style.transform = `translateY(${y}px)`;                     // compositor-only
      }
      if (el.scrollTop !== last) {   // moved: wake, then sleep after a moment of rest
        if (last >= 0) {
          // no attribute on <html> here: toggling one restyles the whole page at the start and end of every scroll
          setAwake(true);
          clearTimeout(sleep);
          sleep = setTimeout(() => setAwake(false), 1100);
        }
        last = el.scrollTop;
      }
    };
    const queue = () => { if (!raf) raf = requestAnimationFrame(update); };
    const main = document.getElementById("main");
    main?.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    const ro = new ResizeObserver(queue);
    const content = pageContent();
    if (content) ro.observe(content);
    update();
    return () => {
      main?.removeEventListener("scroll", queue);
      window.removeEventListener("scroll", queue);
      window.removeEventListener("resize", queue);
      ro.disconnect();
      clearTimeout(sleep);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [pathname]);

  const seek = (clientY: number) => {
    const t = track.current?.getBoundingClientRect();
    const th = thumb.current?.getBoundingClientRect();
    if (!t || !th) return;
    const el = pageScroller();
    const off = grab.current ?? th.height / 2;   // keep the grabbed point under the pointer
    const ratio = (clientY - t.top - off) / Math.max(1, t.height - th.height);
    el.scrollTop = Math.min(1, Math.max(0, ratio)) * (el.scrollHeight - el.clientHeight);
  };

  const shown = drag || awake;
  return (
    <div
      ref={track}
      aria-hidden
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        const th = thumb.current?.getBoundingClientRect();
        grab.current = th && e.clientY >= th.top && e.clientY <= th.bottom ? e.clientY - th.top : null;
        setDrag(true);
        seek(e.clientY);
      }}
      onPointerMove={(e) => drag && seek(e.clientY)}
      onPointerUp={() => { setDrag(false); grab.current = null; }}
      onPointerCancel={() => { setDrag(false); grab.current = null; }}
      className={"group fixed bottom-2 right-0 top-[60px] z-30 w-3.5 touch-none mix-blend-difference " + (scrollable ? "" : "pointer-events-none hidden")}
    >
      <div className={"absolute inset-y-0 right-[3px] rounded-full transition-all duration-300 " +
        (drag ? "w-[6px] bg-white/[0.06]" : "w-[4px] bg-transparent group-hover:w-[6px] group-hover:bg-white/[0.05]")}>
        <div ref={thumb}
             className={"absolute inset-x-0 top-0 rounded-full transition-[opacity,background-color] duration-300 " +
               (drag ? "bg-white/80 opacity-100" : shown ? "bg-white/45 opacity-100 group-hover:bg-white/70" : "bg-white/45 opacity-0 group-hover:opacity-100 group-hover:bg-white/70")} />
      </div>
    </div>
  );
}
