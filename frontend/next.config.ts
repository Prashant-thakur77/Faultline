import type { NextConfig } from "next";

/**
 * Two build targets from one config, selected by FAULTLINE_PAGES:
 *
 *   npm run dev / npm run build   the live command center (talks to the API, default target);
 *   npm run build:pages           FAULTLINE_PAGES=1: the static, backend-free replay site for
 *                                 GitHub Pages (output: "export" into out-pages/), served under
 *                                 NEXT_PUBLIC_BASE_PATH (default "/Faultline", "" for a root site).
 *
 * The client reads the target through two build-time constants (src/lib/site.ts):
 * FAULTLINE_STATIC_SITE ("1" on the Pages build) and FAULTLINE_BASE_PATH (the prefix for
 * fetches of public/replay/** bundles, which next/link and assets get from basePath already).
 */

const PAGES = process.env.FAULTLINE_PAGES === "1";

function pagesBasePath(): string {
  const raw = process.env.NEXT_PUBLIC_BASE_PATH ?? "/Faultline";
  const v = raw.trim().replace(/\/+$/, "");
  if (v !== "" && !/^\/[A-Za-z0-9._~-]+(\/[A-Za-z0-9._~-]+)*$/.test(v)) {
    throw new Error(
      `NEXT_PUBLIC_BASE_PATH must be "" or a path like "/Faultline" (got ${JSON.stringify(raw)})`,
    );
  }
  return v;
}

const liveConfig: NextConfig = {
  env: { FAULTLINE_STATIC_SITE: "", FAULTLINE_BASE_PATH: "" },
};

function pagesConfig(): NextConfig {
  const basePath = pagesBasePath();
  // scripts/build-pages.mjs builds from a staging project dir (.pages-build/, src and public
  // symlinked) so that next build's scratch .next/ never overwrites the live build's .next/.
  // It passes the frontend dir as the Turbopack root and the export dir relative to staging.
  const root = process.env.FAULTLINE_PAGES_ROOT;
  return {
    output: "export",
    // With output: "export", a custom distDir is the export directory itself.
    distDir: process.env.FAULTLINE_PAGES_OUT ?? "out-pages",
    ...(root ? { turbopack: { root }, outputFileTracingRoot: root } : {}),
    basePath,
    trailingSlash: true,
    images: { unoptimized: true },
    env: { FAULTLINE_STATIC_SITE: "1", FAULTLINE_BASE_PATH: basePath },
  };
}

const nextConfig: NextConfig = PAGES ? pagesConfig() : liveConfig;

export default nextConfig;
