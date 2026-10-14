/** A section seam: a hairline across the page with "+" registration marks where it meets the content edges. */
export function SectionRule() {
  return (
    <div aria-hidden className="pointer-events-none relative mx-auto h-px w-full max-w-[1280px] px-5 sm:px-8">
      <div className="h-px w-full bg-[var(--fl-line)]" />
      {["left-5 sm:left-8", "right-5 sm:right-8"].map((pos) => (
        <span key={pos} className={`absolute top-1/2 ${pos} size-[11px] -translate-y-1/2 ${pos.startsWith("left") ? "-translate-x-1/2" : "translate-x-1/2"} text-zinc-500`}>
          <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-current" />
          <span className="absolute left-0 top-1/2 h-px w-full -translate-y-1/2 bg-current" />
        </span>
      ))}
    </div>
  );
}
