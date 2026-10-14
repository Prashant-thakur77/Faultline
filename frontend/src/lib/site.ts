/**
 * Build target constants, inlined at build time from next.config.ts `env`.
 *
 * STATIC_SITE is true only in the GitHub Pages replay build (npm run build:pages): no page may
 * call the live API there, and pages that need it render <LiveOnly> instead of fake data.
 * BASE_PATH is the Pages project-site prefix (e.g. "/Faultline"); "" in the live build.
 */
export const STATIC_SITE = process.env.FAULTLINE_STATIC_SITE === "1";

export const BASE_PATH = (process.env.FAULTLINE_BASE_PATH ?? "").replace(/\/$/, "");

/** Optional link to the source repository (set by the Pages workflow), shown on the static site. */
export const REPO_URL = process.env.NEXT_PUBLIC_FAULTLINE_REPO_URL ?? "";
