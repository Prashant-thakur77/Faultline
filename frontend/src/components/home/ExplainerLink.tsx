import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { TOTAL } from "@/components/explainer/scenes";

/** One line under the system map: the way into /explainer (how FalkorDB decides, in 3D). */
export function ExplainerLink() {
  return (
    <div className="mx-auto -mt-12 max-w-[1200px] px-5 pb-16 sm:px-8 lg:-mt-20">
      <Link href="/explainer"
            className="group inline-flex items-center gap-2 rounded-full border border-[var(--fl-iris)]/35 bg-[var(--fl-iris)]/[0.07] px-4 py-2 text-[14px] text-zinc-100 outline-none transition-colors hover:border-[var(--fl-iris)]/70 focus-visible:ring-2 focus-visible:ring-sky-400">
        <span className="size-1.5 rounded-full bg-[var(--fl-iris)]" aria-hidden />
        See how FalkorDB decides
        <span className="font-mono text-[11px] text-zinc-400">3D · {Math.round(TOTAL)} s</span>
        <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </Link>
    </div>
  );
}
