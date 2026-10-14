/** Shown at once while a route's data and code arrive: the page's shape, so the switch never flashes blank. */
export default function Loading() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-5 pt-12 sm:px-8" role="status" aria-live="polite">
      <span className="sr-only">Loading</span>
      <div className="h-3 w-28 animate-pulse rounded bg-white/[0.06]" />
      <div className="mt-5 h-10 w-[min(36rem,80%)] animate-pulse rounded-md bg-white/[0.07]" />
      <div className="mt-4 h-4 w-[min(48rem,90%)] animate-pulse rounded bg-white/[0.05]" />
      <div className="mt-10 grid gap-4 lg:grid-cols-2">
        <div className="h-64 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]" />
        <div className="h-64 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]" />
      </div>
    </div>
  );
}
