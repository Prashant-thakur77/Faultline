import { Contours } from "@/components/motion/Contours";

/** Page heading (Inter 510, tight tracking): an eyebrow, a title with one gradient phrase, one line of context. */
export function PageIntro({ eyebrow, title, accent, after = "", children }: {
  eyebrow: string;
  title: string;
  accent: string;
  after?: string;
  children?: React.ReactNode;
}) {
  return (
    <header data-fl-intro className="relative isolate shrink-0 overflow-hidden border-b border-white/[0.06]">
      <div className="fl-aurora -z-10 opacity-40" aria-hidden />
      <Contours opacity={0.09} />
      <div className="mx-auto max-w-[1400px] px-5 pb-9 pt-12 sm:px-8">
        <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-[var(--fl-subtle)]">{eyebrow}</p>
        <h1 className="mt-4 text-[clamp(2rem,4.4vw,3.25rem)] font-[510] leading-[1.06] tracking-[-0.03em] text-zinc-50">
          {title} <span className="fl-gradient-text pr-1">{accent}</span>{after}
        </h1>
        {children ? <p className="mt-4 max-w-3xl text-[15px] leading-relaxed text-[var(--fl-muted)]">{children}</p> : null}
      </div>
    </header>
  );
}
