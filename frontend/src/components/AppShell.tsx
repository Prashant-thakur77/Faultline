"use client";

import { createContext, Suspense, useContext, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { STATIC_SITE } from "@/lib/site";
import { TENANT_RE, tenantStore, useTenant } from "@/lib/tenant";
import { useStatus, type StatusState } from "@/hooks/useStatus";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CypherPanelProvider } from "@/components/cypher/CypherPanelContext";
import { BudgetBanner } from "./BudgetBanner";
import { IntroLoader } from "./home/IntroLoader";
import { SiteFooter } from "./home/SiteFooter";
import { NavFlow } from "./motion/NavFlow";
import { PointerFX } from "./motion/PointerFX";
import { ScrollRail } from "./motion/ScrollRail";
import { SmoothScroll } from "./motion/SmoothScroll";
import { FailBanner } from "./FailBanner";
import { TopBar } from "./TopBar";

const StatusCtx = createContext<StatusState>({ status: null, error: null, loading: true });

export function useAppStatus(): StatusState {
  return useContext(StatusCtx);
}

/** Top bar + fail-loudly banner + shared providers (status poller, Cypher panel, tooltips). */
export function AppShell({ children }: { children: React.ReactNode }) {
  // The static replay site has no API: it never polls /api/status (no request leaves for :8400).
  const tenant = useTenant();
  const status = useStatus(tenant, !STATIC_SITE);
  const path = usePathname();
  const home = path === "/";
  // home closes with its own full footer; the incident room and the replay player are fixed panes, with no page to end
  const footer = !home && !/^\/(incidents|replay)\/[^/]+/.test(path ?? "");
  return (
    <StatusCtx.Provider value={status}>
      <TooltipProvider delay={200}>
        <CypherPanelProvider>
          <a
            href="#main"
            className="sr-only z-50 rounded bg-sky-500 px-3 py-1 text-zinc-950 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
          >
            Skip to content
          </a>
          {STATIC_SITE ? null : (
            <Suspense fallback={null}>
              <TenantUrlSync />
            </Suspense>
          )}
          {home ? <IntroLoader /> : null}
          <SmoothScroll />
          <NavFlow />
          <ScrollRail />
          <PointerFX />
          <div className="flex min-h-dvh flex-col lg:h-dvh">
            <TopBar state={status} />
            <FailBanner />
            {STATIC_SITE ? null : <BudgetBanner status={status.status} />}
            <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none lg:overflow-y-auto">
              {footer ? (
                <>
                  {/* the page keeps its own height (never shrunk under the footer), then the footer follows it */}
                  <div className="flex shrink-0 grow flex-col">{children}</div>
                  <div className="shrink-0"><SiteFooter compact /></div>
                </>
              ) : children}
            </main>
          </div>
        </CypherPanelProvider>
      </TooltipProvider>
    </StatusCtx.Provider>
  );
}

/** A `?tenant=` deep link (e.g. from the launcher or a shared URL) selects that tenant on client navigation too. */
function TenantUrlSync() {
  const sp = useSearchParams();
  const t = sp?.get("tenant") ?? null;
  useEffect(() => {
    if (t && TENANT_RE.test(t)) tenantStore.set(t);
  }, [t]);
  return null;
}
