"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "@/hooks/useReducedMotion";

/** A phrase a highlighter sweeps across when it scrolls into view (once). Reduced motion: highlighted, no sweep. */
export function Mark({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect(); } }, { threshold: 0.8 });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  return <span ref={ref} className="fl-mark" data-in={seen || reduced ? "" : undefined}>{children}</span>;
}
