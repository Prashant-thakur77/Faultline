/**
 * The element the page scrolls in. On desktop the app shell's <main id="main"> is a fixed-height scroll column;
 * on phones the document scrolls. Anything that tracks or drives page scroll asks here instead of guessing.
 */
export function pageScroller(): HTMLElement {
  const main = document.getElementById("main");
  if (main && /(auto|scroll)/.test(getComputedStyle(main).overflowY)) return main;
  return (document.scrollingElement as HTMLElement) ?? document.documentElement;
}

/** The page's own root inside <main> (main > route template > page), whose height is the scrolled length. */
export function pageContent(): HTMLElement | null {
  const tpl = document.getElementById("main")?.firstElementChild;
  return ((tpl?.firstElementChild ?? tpl) as HTMLElement | null) ?? null;
}
