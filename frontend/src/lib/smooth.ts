import type Lenis from "lenis";

/**
 * The active smooth scroller, when SmoothScroll runs (home page, desktop, motion allowed). A programmatic jump
 * must go through it: a native scrollIntoView during an eased scroll is overridden by the easing's next frame.
 */
let current: Lenis | null = null;

export function setSmoothScroller(l: Lenis | null): void {
  current = l;
}

export function getSmoothScroller(): Lenis | null {
  return current;
}

/** Bring `el` into view: eased through Lenis when it is active, natively otherwise. */
export function scrollToElement(el: HTMLElement, opts: { block?: "center" | "start"; smooth?: boolean } = {}): void {
  const block = opts.block ?? "start";
  if (current) {
    // an exact scrollTop, not an element target: Lenis's element offset is measured from the window, and our
    // wrapper (<main>) starts below the top bar
    const wrapper = current.options.wrapper as HTMLElement;
    const w = wrapper.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const top = wrapper.scrollTop + (r.top - w.top) - (block === "center" ? (wrapper.clientHeight - r.height) / 2 : 0);
    current.scrollTo(Math.max(0, top), { immediate: opts.smooth === false });
    return;
  }
  el.scrollIntoView({ behavior: opts.smooth === false ? "auto" : "smooth", block });
}
