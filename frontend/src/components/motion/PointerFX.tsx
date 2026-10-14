"use client";

import { useEffect, useRef } from "react";
import { useReducedMotion } from "@/hooks/useReducedMotion";

const ACTIVE = "a[href], button:not(:disabled), [role=tab], [role=button], select, summary, label[for], [data-cursor]";

/**
 * Pointer feedback, one listener set for the whole app:
 *  - a ring that trails a fine pointer and grows over anything clickable (inverts what it covers);
 *  - a light that follows the pointer across cards (.fl-card, [data-spot]: sets --mx/--my, see globals.css);
 *  - a slight pull of [data-magnetic] controls towards the pointer;
 *  - a ripple where a control is pressed or tapped (touch included).
 * The native cursor stays. Nothing runs under reduced motion.
 */
export function PointerFX() {
  const reduced = useReducedMotion();
  const ring = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (reduced) return;
    const fine = window.matchMedia("(pointer: fine)").matches;
    const el = ring.current;
    let x = -100, y = -100, rx = -100, ry = -100, raf = 0, shown = false;
    let magnet: HTMLElement | null = null;

    const loop = () => {
      rx += (x - rx) * 0.22;
      ry += (y - ry) * 0.22;
      if (el) el.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
      raf = Math.abs(x - rx) + Math.abs(y - ry) > 0.2 ? requestAnimationFrame(loop) : 0;
    };
    const release = () => {
      if (magnet) magnet.style.translate = "";
      magnet = null;
    };
    const onMove = (e: PointerEvent) => {
      const t = e.target as Element | null;
      // card light: works for touch drags too
      const card = t?.closest?.(".fl-card, [data-spot]") as HTMLElement | null;
      if (card) {
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", `${e.clientX - r.left}px`);
        card.style.setProperty("--my", `${e.clientY - r.top}px`);
      }
      if (e.pointerType !== "mouse") return;
      const m = t?.closest?.("[data-magnetic]") as HTMLElement | null;
      if (m !== magnet) release();
      if (m) {
        const r = m.getBoundingClientRect();
        const dx = (e.clientX - (r.left + r.width / 2)) * 0.18, dy = (e.clientY - (r.top + r.height / 2)) * 0.28;
        m.style.translate = `${Math.max(-8, Math.min(8, dx))}px ${Math.max(-6, Math.min(6, dy))}px`;
        magnet = m;
      }
      if (!fine || !el) return;
      x = e.clientX; y = e.clientY;
      if (!shown) { rx = x; ry = y; el.style.opacity = "1"; shown = true; }
      // data-cursor="ring": a control whose content must stay visible under the pointer (the 3D cube) keeps the thin ring
      const act = t?.closest?.(ACTIVE);
      el.toggleAttribute("data-hover", !!act && act.getAttribute("data-cursor") !== "ring");
      if (!raf) raf = requestAnimationFrame(loop);
    };
    const onDown = (e: PointerEvent) => {
      el?.setAttribute("data-down", "");
      const t = (e.target as Element | null)?.closest?.(ACTIVE);
      if (!t) return;
      const r = document.createElement("span");
      r.className = "fl-ripple";
      r.style.left = `${e.clientX}px`;
      r.style.top = `${e.clientY}px`;
      r.addEventListener("animationend", () => r.remove(), { once: true });
      document.body.appendChild(r);
    };
    const onUp = () => el?.removeAttribute("data-down");
    const onLeave = () => { if (el) el.style.opacity = "0"; shown = false; release(); };

    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("pointerup", onUp, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointerup", onUp);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      if (raf) cancelAnimationFrame(raf);
      release();
    };
  }, [reduced]);

  if (reduced) return null;
  return <div ref={ring} className="fl-cursor hidden [@media(pointer:fine)]:block" style={{ opacity: 0 }} aria-hidden />;
}
