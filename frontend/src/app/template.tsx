"use client";

import { motion } from "framer-motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

/**
 * Every navigation slides the new page in (Next re-mounts a template per route): a short rise with the
 * slide ease. It keeps <main>'s column layout, so full-height pages (the incident room) still fill it.
 * Reduced motion: an instant target, never a missing one (see Hero for why).
 */
export default function Template({ children }: { children: React.ReactNode }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className="flex min-h-0 flex-1 flex-col"
      initial={reduced ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0, transitionEnd: { transform: "none" } }}
      transition={reduced ? { duration: 0 } : { duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
