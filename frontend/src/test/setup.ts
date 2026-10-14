import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { resetEvalSummaryCache } from "@/hooks/useEvalSummary";
import { tenantStore } from "@/lib/tenant";

afterEach(() => {
  cleanup();
  tenantStore.reset();
  resetEvalSummaryCache();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});
